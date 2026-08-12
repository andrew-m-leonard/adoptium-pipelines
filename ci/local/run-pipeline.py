#!/usr/bin/env python3
################################################################################
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
################################################################################
"""
Local Pipeline Runner — orchestrates OpenJDK build pipeline stages locally.

Stage-specific parameters are loaded dynamically from scripts/stages/*.params.json
(and any vendor-scripts/*.params.json overrides in a checked-out config repo) via
scripts/lib/collect-stage-params.py. This ensures the local runner always presents
the same parameter surface as the Jenkins jobs without any hardcoding.

Stage IDs and display labels are loaded from scripts/stages/pipeline-stages.json —
the same canonical registry used by Jenkinsfile.declarative and the migration tools.

Usage:
    python3 run-pipeline.py --jdk-version jdk21 --target-os mac --architecture aarch64
    python3 run-pipeline.py --help
"""

import argparse
import enum
import os
import sys
import subprocess
import json
import re
from pathlib import Path
from datetime import datetime
from workspace_manager import WorkspaceManager
from stage_resolver import StageResolver
from lib.stage_params import (
    collect_stage_params,
    parse_extra_args,
    build_stage_params_help,
)
from lib.stage_env import build_stage_env
from lib.config_repo import sync_config_repo, load_adoptium_pipeline_config


class StageResult(enum.Enum):
    """Mirrors Jenkins build result states: SUCCESS → UNSTABLE → FAILURE."""

    SUCCESS = "SUCCESS"
    UNSTABLE = "UNSTABLE"
    FAILURE = "FAILURE"

    def is_worse_than(self, other: "StageResult") -> bool:
        _rank = {
            StageResult.SUCCESS: 0,
            StageResult.UNSTABLE: 1,
            StageResult.FAILURE: 2,
        }
        return _rank[self] > _rank[other]

    @staticmethod
    def from_exit_code(exit_code: int) -> "StageResult":
        if exit_code == 0:
            return StageResult.SUCCESS
        if exit_code == 1:
            return StageResult.UNSTABLE
        return StageResult.FAILURE


def _load_stage_registry(script_dir: Path) -> dict:
    """Load pipeline-stages.json and return an id → label mapping.

    Args:
        script_dir: Root of the ci-adoptium-pipelines checkout.

    Returns:
        Dict mapping stageId strings to their display labels,
        e.g. {'02-build': 'Build', '13-smoke-tests': 'Smoke Tests', ...}
    """
    registry_path = script_dir / "scripts" / "stages" / "pipeline-stages.json"
    with open(registry_path, "r") as f:
        stages = json.load(f)["pipelineStages"]
    return {s["id"]: s["label"] for s in stages}


# ---------------------------------------------------------------------------
# Stage ID constants — match the "id" fields in pipeline-stages.json exactly.
# Used throughout PipelineRunner to refer to stages without raw string literals.
# ---------------------------------------------------------------------------
INITIALIZE = "01-initialize"
BUILD = "02-build"
INTERNAL_CODE_SIGN = "03-internal-code-sign"
ASSEMBLE_IMAGES = "04-assemble-images"
POST_BUILD_CODE_SIGN = "06-post-build-code-sign"
BUILD_INSTALLERS = "07-installer"
CODE_SIGN_INSTALLER = "08-code-sign-installer"
SBOM_SIGN = "09-sbom-sign"
DIGITAL_ARTIFACT_SIGN = "10-digital-artifact-sign"
VERIFY_SIGNING = "11-verify-signing"
VALIDATE_SBOM = "12-validate-sbom"
SMOKE_TESTS = "13-smoke-tests"
AQA_TESTS = "14-aqa-tests"
TCK_TESTS = "15-tck-tests"
PUBLISH_ARTIFACTS = "16-publish"
REPRODUCIBLE_COMPARE = "20-reproducible-compare"

# Ordered list of stageIds that the local runner executes (subset of all pipeline
# stages — CI-only stages such as code-signing and publishing are excluded).
_LOCAL_STAGES = [
    INITIALIZE,
    BUILD,
    VALIDATE_SBOM,
    SMOKE_TESTS,
    AQA_TESTS,
    REPRODUCIBLE_COMPARE,
]


class _PipelineAbort(Exception):
    """Raised internally to stop stage execution after a FAILURE result."""


class PipelineRunner:
    def __init__(
        self, args, stage_params: dict | None = None, collated: dict | None = None
    ):
        self.args = args
        self.script_dir = Path(
            __file__
        ).parent.parent.parent.resolve()  # ci-adoptium-pipelines root
        self._stage_registry = _load_stage_registry(self.script_dir)

        # Collated stage params: { paramName → value } derived from
        # scripts/stages/*.params.json + vendor-scripts/*.params.json.
        # Injected into every stage environment via _stage_env().
        self._stage_param_values: dict[str, str] = stage_params or {}

        # Stage metadata maps derived from the collated output.
        # _stage_disabled:    stageId → bool   (stageDisabled field)
        # _stage_conditions:  stageId → list of { param, value } dicts
        self._stage_disabled: dict[str, bool] = {}
        self._stage_conditions: dict[str, list[dict]] = {}
        if collated:
            self._load_stage_metadata(collated)

        # StageResolver is initialised lazily after stage_initialize() has
        # cloned the config repo.  _make_resolver() is called at the start
        # of each _run_stage() call to ensure it is always up-to-date.
        self._resolver: StageResolver | None = None

        # Initialize workspace manager
        pipeline_workspace = Path(args.workspace).expanduser().resolve()
        config_file = pipeline_workspace / "pipeline-config.json"
        self.workspace_mgr = WorkspaceManager(pipeline_workspace, config_file)

        # Convenience properties
        self.pipeline_workspace = self.workspace_mgr.pipeline_workspace
        self.stage_workspace = self.workspace_mgr.stage_workspace
        self.build_artifacts_dir = self.workspace_mgr.build_artifacts_dir
        self.workspace = self.pipeline_workspace
        self.config_file = self.workspace_mgr.config_file
        self.build_number = (
            args.build_number or f"local-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )

        # Determine which stages to run
        if args.start_from_stage:
            if args.start_from_stage not in _LOCAL_STAGES:
                raise ValueError(
                    f"Invalid stage: {args.start_from_stage}. Must be one of: {', '.join(_LOCAL_STAGES)}"
                )
            start_index = _LOCAL_STAGES.index(args.start_from_stage)
            self.stages_to_run = _LOCAL_STAGES[start_index:]
            print(f"ℹ️  Starting from stage: {args.start_from_stage}")
            print(f"   Will run: {', '.join(self.stages_to_run)}")
        else:
            self.stages_to_run = _LOCAL_STAGES.copy()

    def _load_stage_metadata(self, collated: dict) -> None:
        """Extract stageDisabled and stageCondition maps from the collated output."""
        for grp in collated.get("groups", []):
            stage_id = grp.get("stageId", "")
            if not stage_id:
                continue
            # stageDisabled — first group seen per stageId wins
            if stage_id not in self._stage_disabled:
                self._stage_disabled[stage_id] = bool(grp.get("stageDisabled", False))
            # stageCondition — merge across groups sharing the same stageId
            conds = grp.get("stageCondition", [])
            if conds:
                existing = self._stage_conditions.get(stage_id, [])
                seen_params = {c["param"] for c in existing}
                merged = existing + [c for c in conds if c["param"] not in seen_params]
                self._stage_conditions[stage_id] = merged

    def _stage_condition_met(self, stage_id: str) -> bool:
        """
        Return True if all stageCondition entries for stage_id are satisfied,
        or if no conditions are defined (unconditional stage).

        Checks _stage_param_values (explicit CLI overrides) first, then the
        process environment.

        Value matching:
          - If the condition value begins with "regex:" the remainder is treated
            as a Python regex and matched with re.search() (substring match,
            mirroring Groovy's =~ find operator).
          - Otherwise a case-insensitive string equality check is performed to
            handle boolean coercion ('true'/'false' strings).
        """
        if self._stage_disabled.get(stage_id, False):
            print(f"  ↳ [{stage_id}] stageDisabled=true — skipping")
            return False
        conditions = self._stage_conditions.get(stage_id, [])
        for cond in conditions:
            param_name = cond["param"]
            expected = str(cond["value"])
            actual = str(
                self._stage_param_values.get(param_name, os.environ.get(param_name, ""))
            )
            if expected.startswith("regex:"):
                pattern = expected[len("regex:") :]
                if not re.search(pattern, actual):
                    print(
                        f"  ↳ [{stage_id}] skipped: {param_name}={actual!r} "
                        f"(regex {pattern!r} did not match)"
                    )
                    return False
            else:
                if actual.lower() != expected.lower():
                    print(
                        f"  ↳ [{stage_id}] skipped: {param_name}={actual!r} (need {expected!r})"
                    )
                    return False
        return True

    def _make_resolver(self) -> StageResolver:
        """
        Return a StageResolver, (re-)creating it if the config repo has
        been cloned since the last call (i.e. after stage_initialize()).
        """
        config_repo_root = None
        if self.args.config_repo_url:
            candidate = self.workspace / "config-repo"
            if candidate.exists():
                config_repo_root = candidate

        if self._resolver is None or (
            config_repo_root is not None
            and self._resolver.config_repo_root != config_repo_root
        ):
            self._resolver = StageResolver(self.script_dir, config_repo_root)
            src = str(config_repo_root) if config_repo_root else "defaults only"
            print(f"ℹ️  StageResolver initialised (config repo: {src})")

        return self._resolver

    def _stage_env(self, extra: dict | None = None) -> dict:
        """Build the standard environment dict passed to every stage script."""
        return build_stage_env(
            script_dir=self.script_dir,
            stage_workspace=self.stage_workspace,
            build_artifacts_dir=self.build_artifacts_dir,
            build_number=self.build_number,
            release_type=self.args.release_type or "NIGHTLY",
            clean_workspace=self.args.clean_workspace,
            stage_param_values=self._stage_param_values,
            extra=extra,
        )

    def _run_stage(
        self, stage_id: str, artifact_filter: str, extra_env: dict | None = None
    ) -> StageResult:
        """
        Execute one pipeline stage — the local equivalent of a Jenkins stage block.

        Mirrors the Jenkins pattern exactly:
          1. Pre-cleanup  (≈ cleanWs)
          2. Restore inputs from build_artifacts/ (≈ copyArtifacts)
          3. Build standard environment
          4. Run stage script via StageResolver
          5. Archive outputs from stage_workspace/target/ (≈ archiveArtifacts)
          6. Post-cleanup (≈ finalizeStage cleanWs)

        Exit-code → StageResult mapping (mirrors Jenkins):
          0  → SUCCESS
          1  → UNSTABLE  (stage completed but reported differences / warnings)
          >1 → FAILURE   (hard failure — pipeline stops after this stage)

        Args:
            stage_id:        StageId from pipeline-stages.json (e.g. '02-build').
                             Used as both the script stem and the display label source.
            artifact_filter: Comma-separated glob patterns for restore_stage_inputs.
            extra_env:       Additional env vars beyond the standard set.

        Returns:
            StageResult reflecting the stage outcome.
        """
        stage_label = self._stage_registry.get(stage_id, stage_id)
        print(f"\n{'=' * 80}")
        print(f"STAGE: {stage_label}")
        print("=" * 80)

        self.workspace_mgr.cleanup_stage_workspace("pre")
        self.workspace_mgr.restore_stage_inputs(stage_label, artifact_filter)

        env = self._stage_env(extra_env)
        exit_code = self._make_resolver().run(stage_id, env)

        self.workspace_mgr.archive_stage_outputs(
            stage_label, target_dir=env.get("TARGET_DIR")
        )
        self.workspace_mgr.cleanup_stage_workspace("post")

        result = StageResult.from_exit_code(exit_code)
        if result == StageResult.UNSTABLE:
            print(f"\n⚠️  {stage_label} completed as UNSTABLE (exit code: {exit_code})")
        elif result == StageResult.FAILURE:
            print(f"\n❌ {stage_label} FAILED (exit code: {exit_code})")

        return result

    # ------------------------------------------------------------------
    # Pipeline entry point
    # ------------------------------------------------------------------

    def run(self, skip_initialize: bool = False):
        """Run the complete pipeline.

        Args:
            skip_initialize: When True the Initialize stage is not run by this
                method — the caller (main) has already run it so that the
                config repo is available before stage params are validated.
                Also suppresses the workspace-exists guard in validate_and_setup.
        """
        print("=" * 80)
        print("OpenJDK Build Pipeline - Local Runner")
        print("=" * 80)
        print(f"Workspace: {self.workspace}")
        print(f"Build Number: {self.build_number}")
        print()

        self.workspace_mgr.validate_and_setup(
            is_restarting=self.args.start_from_stage is not None,
            clean_requested=self.args.clean_workspace,
            start_from_stage=self.args.start_from_stage,
            initialize_already_run=skip_initialize,
        )

        pipeline_result = StageResult.SUCCESS
        failure_exit_code = 0

        def _run(stage_id, artifact_filter, extra_env=None):
            """Run a stage, update pipeline_result, return False if pipeline should stop."""
            nonlocal pipeline_result, failure_exit_code
            result = self._run_stage(stage_id, artifact_filter, extra_env=extra_env)
            if result.is_worse_than(pipeline_result):
                pipeline_result = result
            if result == StageResult.FAILURE:
                failure_exit_code = 2  # sentinel — actual code already printed
                return False
            return True

        try:
            if not skip_initialize and INITIALIZE in self.stages_to_run:
                self.stage_initialize()

            if BUILD in self.stages_to_run:
                if not _run(
                    BUILD,
                    "pipeline-config.json",
                    extra_env={
                        "TARGET_DIR": str(self.stage_workspace / "build_output")
                    },
                ):
                    raise _PipelineAbort()

            if VALIDATE_SBOM in self.stages_to_run:
                if not _run(
                    VALIDATE_SBOM,
                    "pipeline-config.json,*sbom*.json",
                    extra_env={
                        "TARGET_DIR": str(
                            self.stage_workspace / "sbom_validation_output"
                        )
                    },
                ):
                    raise _PipelineAbort()

            if SMOKE_TESTS in self.stages_to_run and self._stage_condition_met(
                SMOKE_TESTS
            ):
                if not _run(
                    SMOKE_TESTS,
                    "pipeline-config.json,*.tar.gz,*.zip",
                    extra_env={
                        "TARGET_DIR": str(self.stage_workspace / "smoke_test_output")
                    },
                ):
                    raise _PipelineAbort()

            if AQA_TESTS in self.stages_to_run and self._stage_condition_met(AQA_TESTS):
                if not _run(
                    AQA_TESTS,
                    "pipeline-config.json,*.tar.gz,*.zip",
                    extra_env={
                        "TARGET_DIR": str(self.stage_workspace / "aqa_test_output")
                    },
                ):
                    raise _PipelineAbort()

            if (
                REPRODUCIBLE_COMPARE in self.stages_to_run
                and self._stage_condition_met(REPRODUCIBLE_COMPARE)
            ):
                release_type = (self.args.release_type or "NIGHTLY").upper()
                _run(
                    REPRODUCIBLE_COMPARE,
                    "pipeline-config.json,*.tar.gz,*.zip",
                    extra_env={
                        "TARGET_DIR": str(
                            self.stage_workspace / "reproducible_compare_output"
                        ),
                        "RELEASE": "true" if release_type == "RELEASE" else "false",
                    },
                )

        except _PipelineAbort:
            pass
        except Exception as e:
            print()
            print("=" * 80)
            print(f"❌ Pipeline failed: {e}")
            print("=" * 80)
            return 1

        print()
        print("=" * 80)
        if pipeline_result == StageResult.SUCCESS:
            print("✅ Pipeline completed successfully!")
            rc = 0
        elif pipeline_result == StageResult.UNSTABLE:
            print(
                "⚠️  Pipeline completed as UNSTABLE (one or more stages reported warnings)"
            )
            rc = 1
        else:
            print("❌ Pipeline FAILED")
            rc = failure_exit_code
        print("=" * 80)
        print(f"\n📦 All artifacts in: {self.build_artifacts_dir}")
        return rc

    # ------------------------------------------------------------------
    # Initialize stage (unique logic — not reducible to _run_stage)
    # ------------------------------------------------------------------

    def stage_initialize(self):
        """Stage 1: Generate pipeline configuration."""
        print("\n" + "=" * 80)
        print("STAGE: Initialize - Generate Configuration")
        print("=" * 80)

        self.workspace_mgr.cleanup_stage_workspace("pre")

        config_repo_dir = sync_config_repo(
            self.workspace,
            self.args.config_repo_url,
            self.args.config_repo_branch,
        )

        pipeline_config = load_adoptium_pipeline_config(config_repo_dir)

        cmd = [
            sys.executable,
            str(self.script_dir / "scripts" / "lib" / "load-json-config.py"),
            "--jdk-version",
            self.args.jdk_version,
            "--variant",
            pipeline_config.get("defaultVariant", "temurin"),
            "--target-os",
            self.args.target_os,
            "--architecture",
            self.args.architecture,
            "--config-repo-path",
            str(config_repo_dir),
            "--output-dir",
            str(self.workspace),
        ]

        if self.args.release_type:
            release_type = self.args.release_type.upper()
            valid = ["NIGHTLY", "WEEKLY", "RELEASE"]
            if release_type not in valid:
                raise ValueError(
                    f"Invalid release type '{self.args.release_type}'. "
                    f"Must be one of: {', '.join(valid)}"
                )
            cmd.extend(["--release-type", release_type])

        print(f"Running: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)

        if not self.config_file.exists():
            raise FileNotFoundError(
                f"Configuration file not created: {self.config_file}"
            )

        with open(self.config_file, "r") as f:
            config = json.load(f)
        print("\nGenerated Configuration:")
        print(json.dumps(config, indent=2))

        # Archive pipeline-config.json → build_artifacts/ (≈ Jenkins archiveArtifacts)
        self.workspace_mgr.archive_file(self.config_file, "Initialize")

        print("\n✅ Initialize stage complete")
        self.workspace_mgr.cleanup_stage_workspace("post")


def main():
    script_dir = Path(__file__).parent.parent.parent.resolve()

    # -----------------------------------------------------------------------
    # If --help/-h is in sys.argv, build a dynamic stage params epilog before
    # the parser is created.  The parser exits after printing help, so this
    # must happen first.
    #
    # If --config-repo-url is also present we clone/reuse that repo and collate
    # the full vendor param set.  Otherwise we fall back to the default
    # scripts/stages/*.params.json files (always available locally).
    # -----------------------------------------------------------------------
    stage_params_epilog = build_stage_params_help(script_dir, sys.argv, _LOCAL_STAGES)

    # -----------------------------------------------------------------------
    # Parse known fixed args; capture everything else as raw tokens.
    # Unknown tokens are stage params validated after Initialize clones the
    # config repo and the full vendor param set is collated.
    # -----------------------------------------------------------------------
    parser = argparse.ArgumentParser(
        description="Run OpenJDK build pipeline locally",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Standard nightly build
  python3 run-pipeline.py --jdk-version jdk21 --target-os mac --architecture aarch64 \\
      --config-repo-url https://github.com/adoptium/ci-temurin-config.git

  # Release build with reproducible compare, pinned source tag
  python3 run-pipeline.py \\
      --jdk-version jdk21 --target-os linux --architecture x64 \\
      --config-repo-url https://github.com/adoptium/ci-temurin-config.git \\
      --release-type RELEASE \\
      --scm-ref jdk-21.0.7+6_adopt \\
      --run-reproducible-compare true
"""
        + stage_params_epilog,
    )

    # ── Required ─────────────────────────────────────────────────────────────
    parser.add_argument(
        "--jdk-version",
        required=True,
        help="JDK version to build (e.g., jdk21, jdk8). Format: jdkNN.",
    )
    parser.add_argument(
        "--target-os",
        required=True,
        choices=["mac", "linux", "windows", "aix"],
        help="Target operating system",
    )
    parser.add_argument(
        "--architecture",
        required=True,
        choices=["aarch64", "x64", "x32", "ppc64", "s390x"],
        help="Target architecture",
    )

    # ── Pipeline / workspace control ─────────────────────────────────────────
    parser.add_argument(
        "--workspace",
        default="~/openjdk-build",
        help="Workspace directory (default: ~/openjdk-build)",
    )
    parser.add_argument(
        "--build-number", help="Build number (default: local-YYYYMMDD-HHMMSS)"
    )
    parser.add_argument(
        "--clean-workspace",
        action="store_true",
        help="Remove existing workspace before starting (ensures clean build)",
    )
    parser.add_argument(
        "--start-from-stage",
        choices=_LOCAL_STAGES,
        help="Start pipeline from a specific stage (skips earlier stages)",
    )

    # ── Release / build type ──────────────────────────────────────────────────
    parser.add_argument(
        "--release-type",
        type=str,
        help="Type of release build: NIGHTLY (default), WEEKLY, or RELEASE",
    )

    # ── Configuration repository ──────────────────────────────────────────────
    parser.add_argument(
        "--config-repo-url", required=True, help="Configuration repository URL"
    )
    parser.add_argument(
        "--config-repo-branch",
        default="main",
        help="Configuration repository branch (default: main)",
    )

    # parse_known_args: fixed args parsed normally; anything else returned as
    # a flat list of raw tokens (stage params from *.params.json, e.g.
    # --scm-ref, --run-tests, --create-sbom) validated after Initialize has
    # cloned the config repo and stage params are collated.
    args, extra_tokens = parser.parse_known_args()

    if not re.match(r"^jdk\d+$", args.jdk_version):
        parser.error(
            f"Invalid --jdk-version format: '{args.jdk_version}'. "
            f"Must be in format jdkNN (e.g., jdk21, jdk8)."
        )

    # Syntax-only pre-check: reject any extra token that doesn't start with '--'.
    # Single-dash flags (e.g. -dsfsdfsdf) are never valid stage params and would
    # otherwise silently pass through until post-Initialize collation.
    bad_tokens = [
        t for t in extra_tokens if t.startswith("-") and not t.startswith("--")
    ]
    if bad_tokens:
        parser.error(
            f"Unrecognised argument(s): {' '.join(bad_tokens)}\n"
            f"Stage parameters must use --<lower-kebab-case-name> <value> syntax.\n"
            f"Run with --help to see all available parameters."
        )

    # Create runner — stage params are empty until the config repo is cloned.
    runner = PipelineRunner(args, stage_params={}, collated=None)

    # Perform workspace validation and clean BEFORE Initialize runs, so that
    # --clean-workspace takes effect even though validate_and_setup() will be
    # called again (with initialize_already_run=True) inside run() and skip it.
    runner.workspace_mgr.validate_and_setup(
        is_restarting=args.start_from_stage is not None,
        clean_requested=args.clean_workspace,
        start_from_stage=args.start_from_stage,
        initialize_already_run=False,
    )

    # Run Initialize: clones the config repo and generates pipeline-config.json.
    if not args.start_from_stage or args.start_from_stage == INITIALIZE:
        try:
            runner.stage_initialize()
        except Exception as e:
            print(f"\n❌ Initialize stage failed: {e}")
            return 1

    # -----------------------------------------------------------------------
    # Collate stage params now that the config repo has been cloned.
    # Merges default scripts/stages/*.params.json with any vendor-scripts/
    # *.params.json overrides so vendor-specific params are also recognised.
    # -----------------------------------------------------------------------
    vendor_dir = runner.workspace / "config-repo" / "vendor-scripts"
    collated = collect_stage_params(
        script_dir,
        vendor_dir if vendor_dir.exists() else None,
        orchestrated_stages=_LOCAL_STAGES,
    )

    # Load stage metadata (disabled flags, conditions) from the collated output.
    runner._load_stage_metadata(collated)

    stage_params, unrecognised, param_errors = parse_extra_args(extra_tokens, collated)

    failed = False
    if unrecognised:
        print(
            f"\n❌ Unrecognised parameter(s) — not defined in any *.params.json for this config repo:"
        )
        for flag in unrecognised:
            print(f"   {flag}")
        print(f"\n   Run with --help to see all available stage parameters.")
        failed = True

    if param_errors:
        print(f"\n❌ Invalid parameter value(s):")
        for msg in param_errors:
            print(msg)
        print(f"\n   Run with --help to see all available stage parameters.")
        failed = True

    if failed:
        return 1

    if stage_params:
        print("Stage parameters accepted:")
        for name, value in stage_params.items():
            print(f"  {name} = {value!r}")
        print()

    # Inject into the runner and continue from the next stage
    runner._stage_param_values = stage_params

    return runner.run(skip_initialize=True)


if __name__ == "__main__":
    sys.exit(main())
