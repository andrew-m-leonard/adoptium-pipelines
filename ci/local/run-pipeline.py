#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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

import enum
import sys
from datetime import datetime
from pathlib import Path

from lib.cli_parser import PipelineArgParser
from lib.stage_executor import StageExecutor
from lib.stage_params import collect_stage_params, parse_extra_args
from lib.stage_registry import load_stage_registry
from lib.workspace_manager import WorkspaceManager


# ---------------------------------------------------------------------------
# Stage ID constants — match the "id" fields in pipeline-stages.json exactly.
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


class StageResult(enum.Enum):
    """Mirrors Jenkins build result states: SUCCESS → UNSTABLE → FAILURE."""

    SUCCESS = "SUCCESS"
    UNSTABLE = "UNSTABLE"
    FAILURE = "FAILURE"

    def is_worse_than(self, other: "StageResult") -> bool:
        _rank = {StageResult.SUCCESS: 0, StageResult.UNSTABLE: 1, StageResult.FAILURE: 2}
        return _rank[self] > _rank[other]

    @staticmethod
    def from_exit_code(exit_code: int) -> "StageResult":
        if exit_code == 0:
            return StageResult.SUCCESS
        if exit_code == 1:
            return StageResult.UNSTABLE
        return StageResult.FAILURE


class _PipelineAbort(Exception):
    """Raised internally to stop stage execution after a FAILURE result."""


class PipelineRunner:
    """Orchestrates which stages run and in what order."""

    def __init__(self, args, executor: StageExecutor, workspace_mgr: WorkspaceManager):
        self.args = args
        self.executor = executor
        self.workspace_mgr = workspace_mgr

        if args.start_from_stage:
            start_index = _LOCAL_STAGES.index(args.start_from_stage)
            self.stages_to_run = _LOCAL_STAGES[start_index:]
            print(f"ℹ️  Starting from stage: {args.start_from_stage}")
            print(f"   Will run: {', '.join(self.stages_to_run)}")
        else:
            self.stages_to_run = _LOCAL_STAGES.copy()

    def run(self, skip_initialize: bool = False) -> int:
        """
        Run the pipeline from the first scheduled stage to the last.

        Args:
            skip_initialize: When True the Initialize stage is skipped here —
                the caller (main) has already run it before stage params were
                collated, so the config repo is available for subsequent stages.

        Returns:
            Process exit code: 0 = success, 1 = unstable, 2 = failure.
        """
        build_number = self.executor._build_number
        print("=" * 80)
        print("OpenJDK Build Pipeline - Local Runner")
        print("=" * 80)
        print(f"Workspace: {self.workspace_mgr.pipeline_workspace}")
        print(f"Build Number: {build_number}")
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
            """Run one stage, track the worst result; return False to stop pipeline."""
            nonlocal pipeline_result, failure_exit_code
            exit_code = self.executor.run_stage(stage_id, artifact_filter, extra_env)
            result = StageResult.from_exit_code(exit_code)
            if result == StageResult.UNSTABLE:
                print(f"\n⚠️  {stage_id} completed as UNSTABLE (exit code: {exit_code})")
            elif result == StageResult.FAILURE:
                print(f"\n❌ {stage_id} FAILED (exit code: {exit_code})")
            if result.is_worse_than(pipeline_result):
                pipeline_result = result
            if result == StageResult.FAILURE:
                failure_exit_code = 2
                return False
            return True

        try:
            # #####################################################################
            # Stage: 01-initialize
            # #####################################################################
            if not skip_initialize and INITIALIZE in self.stages_to_run:
                self.executor.run_initialize()

            # #####################################################################
            # Stage: 02-build
            # #####################################################################
            if BUILD in self.stages_to_run:
                if not _run(BUILD, "pipeline-config.json"):
                    raise _PipelineAbort()

            # #####################################################################
            # Stage: 12-validate-sbom
            # #####################################################################
            if VALIDATE_SBOM in self.stages_to_run:
                if not _run(VALIDATE_SBOM, "pipeline-config.json,*sbom*.json"):
                    raise _PipelineAbort()

            # #####################################################################
            # Stage: 13-smoke-tests
            # #####################################################################
            if SMOKE_TESTS in self.stages_to_run and self.executor.condition_met(SMOKE_TESTS):
                if not _run(SMOKE_TESTS, "pipeline-config.json,*.tar.gz,*.zip"):
                    raise _PipelineAbort()

            # #####################################################################
            # Stage: 14-aqa-tests
            # #####################################################################
            if AQA_TESTS in self.stages_to_run and self.executor.condition_met(AQA_TESTS):
                if not _run(AQA_TESTS, "pipeline-config.json,*.tar.gz,*.zip"):
                    raise _PipelineAbort()

            # #####################################################################
            # Stage: 20-reproducible-compare
            # #####################################################################
            if REPRODUCIBLE_COMPARE in self.stages_to_run and self.executor.condition_met(REPRODUCIBLE_COMPARE):
                _run(REPRODUCIBLE_COMPARE, "pipeline-config.json,*.tar.gz,*.zip")

        except _PipelineAbort:
            pass
        except Exception as e:
            print(f"\n{'=' * 80}\n❌ Pipeline failed: {e}\n{'=' * 80}")
            return 1

        print(f"\n{'=' * 80}")
        if pipeline_result == StageResult.SUCCESS:
            print("✅ Pipeline completed successfully!")
            rc = 0
        elif pipeline_result == StageResult.UNSTABLE:
            print("⚠️  Pipeline completed as UNSTABLE (one or more stages reported warnings)")
            rc = 1
        else:
            print("❌ Pipeline FAILED")
            rc = failure_exit_code
        print("=" * 80)
        print(f"\n📦 All artifacts in: {self.workspace_mgr.build_artifacts_dir}")
        return rc


def main() -> int:
    script_dir = Path(__file__).parent.parent.parent.resolve()

    args, extra_tokens = PipelineArgParser(script_dir, _LOCAL_STAGES).parse()

    pipeline_workspace = Path(args.workspace).expanduser().resolve()
    workspace_mgr = WorkspaceManager(pipeline_workspace, pipeline_workspace / "pipeline-config.json")

    build_number = args.build_number or f"local-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    stage_registry = load_stage_registry(script_dir)

    executor = StageExecutor(
        script_dir=script_dir,
        workspace_mgr=workspace_mgr,
        args=args,
        build_number=build_number,
        stage_registry=stage_registry,
    )
    runner = PipelineRunner(args, executor, workspace_mgr)

    # Validate and optionally clean the workspace BEFORE Initialize runs so
    # that --clean-workspace takes effect on the very first invocation.
    workspace_mgr.validate_and_setup(
        is_restarting=args.start_from_stage is not None,
        clean_requested=args.clean_workspace,
        start_from_stage=args.start_from_stage,
        initialize_already_run=False,
    )

    # Run Initialize now so that the config repo is cloned before we attempt
    # to collate vendor stage params.
    if not args.start_from_stage or args.start_from_stage == INITIALIZE:
        try:
            executor.run_initialize()
        except Exception as e:
            print(f"\n❌ Initialize stage failed: {e}")
            return 1

    # Collate stage params now that the config repo exists.
    vendor_dir = pipeline_workspace / "config-repo" / "vendor-scripts"
    collated = collect_stage_params(
        script_dir,
        vendor_dir if vendor_dir.exists() else None,
        orchestrated_stages=_LOCAL_STAGES,
    )
    executor.load_stage_metadata(collated)

    stage_params, unrecognised, param_errors = parse_extra_args(extra_tokens, collated)

    failed = False
    if unrecognised:
        print("\n❌ Unrecognised parameter(s) — not defined in any *.params.json for this config repo:")
        for flag in unrecognised:
            print(f"   {flag}")
        print("\n   Run with --help to see all available stage parameters.")
        failed = True
    if param_errors:
        print("\n❌ Invalid parameter value(s):")
        for msg in param_errors:
            print(msg)
        print("\n   Run with --help to see all available stage parameters.")
        failed = True
    if failed:
        return 1

    if stage_params:
        print("Stage parameters accepted:")
        for name, value in stage_params.items():
            print(f"  {name} = {value!r}")
        print()

    executor.stage_param_values = stage_params
    return runner.run(skip_initialize=True)


if __name__ == "__main__":
    sys.exit(main())
