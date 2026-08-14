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
StageExecutor — per-stage execution logic for the local pipeline runner.

Owns everything needed to prepare, run, and finalise a single pipeline stage:
  - Stage metadata (stageDisabled flags and stageCondition maps)
  - StageResolver lifecycle (lazy init, refresh after config-repo clone)
  - Environment construction (delegates to build_stage_env)
  - Stage script execution (_run_stage)
  - Initialize stage (unique logic — builds config, clones config repo)

PipelineRunner composes a StageExecutor to keep its own code focused on
orchestration (which stages to run, in what order, stop-on-failure logic).
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from lib.config_repo import load_adoptium_pipeline_config, sync_config_repo
from lib.stage_env import build_stage_env
from lib.stage_registry import load_stage_registry
from lib.stage_resolver import StageResolver
from lib.workspace_manager import WorkspaceManager


class StageExecutor:
    """Prepares and executes individual pipeline stages."""

    def __init__(
        self,
        *,
        script_dir: Path,
        workspace_mgr: WorkspaceManager,
        args,
        build_number: str,
        stage_registry: dict,
    ):
        """
        Args:
            script_dir:     Root of the ci-adoptium-pipelines checkout.
            workspace_mgr:  WorkspaceManager instance for the current run.
            args:           Parsed CLI arguments namespace.
            build_number:   Build identifier string.
            stage_registry: id → label mapping from load_stage_registry().
        """
        self._script_dir = script_dir
        self._workspace_mgr = workspace_mgr
        self._args = args
        self._build_number = build_number
        self._stage_registry = stage_registry

        # Stage metadata populated by load_stage_metadata().
        # _stage_disabled:   stageId → bool
        # _stage_conditions: stageId → list of { param, value } dicts
        self._stage_disabled: dict[str, bool] = {}
        self._stage_conditions: dict[str, list[dict]] = {}

        # Stage param values injected into every stage environment.
        # Populated by PipelineRunner after post-Initialize collation.
        self.stage_param_values: dict[str, str] = {}

        # StageResolver is created lazily and refreshed after stage_initialize()
        # clones the config repo.
        self._resolver: StageResolver | None = None

    # ------------------------------------------------------------------
    # Stage metadata
    # ------------------------------------------------------------------

    def load_stage_metadata(self, collated: dict) -> None:
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

    def condition_met(self, stage_id: str) -> bool:
        """
        Return True if all stageCondition entries for stage_id are satisfied,
        or if no conditions are defined (unconditional stage).

        Checks stage_param_values (explicit CLI overrides) first, then the
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
        for cond in self._stage_conditions.get(stage_id, []):
            param_name = cond["param"]
            expected = str(cond["value"])
            actual = str(
                self.stage_param_values.get(param_name, os.environ.get(param_name, ""))
            )
            if expected.startswith("regex:"):
                pattern = expected[len("regex:"):]
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

    # ------------------------------------------------------------------
    # Resolver + environment
    # ------------------------------------------------------------------

    def _get_resolver(self) -> StageResolver:
        """Return a StageResolver, (re-)creating it if the config repo has been
        cloned since the last call (i.e. after stage_initialize())."""
        config_repo_root = None
        if self._args.config_repo_url:
            candidate = self._workspace_mgr.pipeline_workspace / "config-repo"
            if candidate.exists():
                config_repo_root = candidate

        if self._resolver is None or (
            config_repo_root is not None
            and self._resolver.config_repo_root != config_repo_root
        ):
            self._resolver = StageResolver(self._script_dir, config_repo_root)
            src = str(config_repo_root) if config_repo_root else "defaults only"
            print(f"ℹ️  StageResolver initialised (config repo: {src})")

        return self._resolver

    def _build_env(self, extra: dict | None = None) -> dict:
        """Build the standard environment dict passed to every stage script."""
        return build_stage_env(
            script_dir=self._script_dir,
            stage_workspace=self._workspace_mgr.stage_workspace,
            build_artifacts_dir=self._workspace_mgr.build_artifacts_dir,
            build_number=self._build_number,
            release_type=self._args.release_type or "NIGHTLY",
            clean_workspace=self._args.clean_workspace,
            stage_param_values=self.stage_param_values,
            extra=extra,
        )

    # ------------------------------------------------------------------
    # Stage execution
    # ------------------------------------------------------------------

    def run_stage(self, stage_id: str, artifact_filter: str, extra_env: dict | None = None) -> int:
        """
        Execute one pipeline stage — the local equivalent of a Jenkins stage block.

        Mirrors the Jenkins pattern exactly:
          1. Pre-cleanup  (≈ cleanWs)
          2. Restore inputs from build_artifacts/ (≈ copyArtifacts)
          3. Build standard environment
          4. Run stage script via StageResolver
          5. Archive outputs from stage_workspace/target/ (≈ archiveArtifacts)
          6. Post-cleanup (≈ finalizeStage cleanWs)

        Returns:
            Exit code — 0 = SUCCESS, 1 = UNSTABLE, >1 = FAILURE.
        """
        stage_label = self._stage_registry.get(stage_id, stage_id)
        print(f"\n{'=' * 80}")
        print(f"STAGE: {stage_label}")
        print("=" * 80)

        self._workspace_mgr.cleanup_stage_workspace("pre")
        self._workspace_mgr.restore_stage_inputs(stage_label, artifact_filter)

        env = self._build_env(extra_env)
        exit_code = self._get_resolver().run(stage_id, env)

        self._workspace_mgr.archive_stage_outputs(stage_label, target_dir=env.get("TARGET_DIR"))
        self._workspace_mgr.cleanup_stage_workspace("post")
        return exit_code

    def run_initialize(self) -> None:
        """
        Stage 01-initialize: clone the config repo and generate pipeline-config.json.

        Unique logic that is not reducible to run_stage() because it drives the
        workspace setup and config-repo clone that every subsequent stage depends on.

        Raises:
            ValueError:       Invalid release-type value.
            FileNotFoundError: pipeline-config.json not produced by load-pipeline-config-json.py.
            subprocess.CalledProcessError: load-pipeline-config-json.py exited non-zero.
        """
        print("\n" + "=" * 80)
        print("STAGE: Initialize - Generate Configuration")
        print("=" * 80)

        workspace = self._workspace_mgr.pipeline_workspace
        self._workspace_mgr.cleanup_stage_workspace("pre")

        config_repo_dir = sync_config_repo(
            workspace,
            self._args.config_repo_url,
            self._args.config_repo_branch,
        )

        pipeline_config = load_adoptium_pipeline_config(config_repo_dir)

        cmd = [
            sys.executable,
            str(self._script_dir / "scripts" / "lib" / "load-pipeline-config-json.py"),
            "--jdk-version", self._args.jdk_version,
            "--variant", pipeline_config.get("defaultVariant", "temurin"),
            "--target-os", self._args.target_os,
            "--architecture", self._args.architecture,
            "--config-repo-path", str(config_repo_dir),
            "--output-dir", str(workspace),
        ]

        if self._args.release_type:
            release_type = self._args.release_type.upper()
            valid = ["NIGHTLY", "WEEKLY", "RELEASE"]
            if release_type not in valid:
                raise ValueError(
                    f"Invalid release type '{self._args.release_type}'. "
                    f"Must be one of: {', '.join(valid)}"
                )
            cmd.extend(["--release-type", release_type])

        print(f"Running: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)

        config_file = self._workspace_mgr.config_file
        if not config_file.exists():
            raise FileNotFoundError(f"Configuration file not created: {config_file}")

        with open(config_file, "r", encoding="utf-8") as f:
            config = json.load(f)
        print("\nGenerated Configuration:")
        print(json.dumps(config, indent=2))

        self._workspace_mgr.archive_file(config_file, "Initialize")
        print("\n✅ Initialize stage complete")
        self._workspace_mgr.cleanup_stage_workspace("post")
