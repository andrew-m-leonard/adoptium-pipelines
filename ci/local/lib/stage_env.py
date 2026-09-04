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
Stage environment builder for the local pipeline runner.

Provides build_stage_env() which constructs the standard environment dict
passed to every stage script, mirroring PipelineHelper.initializeStage()
in Jenkins.
"""

import json
import os
import stat
from pathlib import Path


def _setup_git_auth(stage_workspace: Path, env: dict) -> None:
    """
    Configure transparent GitHub HTTPS authentication via GIT_ASKPASS.

    When GITHUB_TOKEN is present in the environment (set by the developer
    before running run-pipeline.py), writes a tiny git-askpass.sh script to
    the stage workspace and sets GIT_ASKPASS in the env dict to its path.

    Why GIT_ASKPASS:
      The token value must never be embedded in a git config key or value
      string — that would expose it as plain text in a different variable.
      GIT_ASKPASS is a *path* to a script; the token stays in its own
      GITHUB_TOKEN variable and is only read by git at auth time.

    git-askpass.sh content:  #!/bin/sh\\necho "${GITHUB_TOKEN}"\\n
      No secret literal in the file.  The script inherits GITHUB_TOKEN from
      the subprocess env dict that already contains it via os.environ.copy().

    The script is written to the stage workspace which is cleaned up by
    WorkspaceManager after every stage, so it never persists between stages.

    Args:
        stage_workspace: Ephemeral per-stage workspace directory.
        env:             Mutable env dict (modified in-place).
    """
    token = env.get("GITHUB_TOKEN", "")
    if not token:
        return

    askpass = stage_workspace / "git-askpass.sh"
    askpass.write_text("#!/bin/sh\necho \"${GITHUB_TOKEN}\"\n", encoding="utf-8")
    askpass.chmod(askpass.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    env["GIT_ASKPASS"] = str(askpass)
    print("🔑 GITHUB_TOKEN present — git HTTPS operations will be authenticated via GIT_ASKPASS")


def resolve_target_dir(stage_workspace: Path, stage_id: str) -> Path:
    """
    Derive the TARGET_DIR for a stage — mirrors StageScriptRunner.resolveTargetDir()
    in the Jenkins pipeline.

    Always derived from the current stage_workspace so it is never a stale path
    from a prior stage.

    Args:
        stage_workspace: Ephemeral per-stage workspace directory.
        stage_id:        Stage stem e.g. '02-build'.

    Returns:
        Absolute Path: <stage_workspace>/<stage_id>-output
    """
    return stage_workspace / f"{stage_id}-output"


def build_stage_env(
    *,
    script_dir: Path,
    stage_workspace: Path,
    build_artifacts_dir: Path,
    build_number: str,
    release_type: str,
    clean_workspace: bool,
    stage_param_values: dict[str, str],
    stage_id: str,
    extra: dict | None = None,
) -> dict:
    """
    Build the standard environment dict passed to every stage script.

    Mirrors PipelineHelper.initializeStage() + StageScriptRunner.run() in Jenkins.

    Standard stage contract variables set for every stage:

      WORKSPACE            — Ephemeral per-stage working directory.  Stage scripts
                             clone repos and produce intermediate files here.
      CONFIG_FILE          — Absolute path to pipeline-config.json inside WORKSPACE.
      INPUT_ARTIFACTS_DIR  — Directory containing artifacts copied in before the
                             stage runs (equals WORKSPACE for the local runner).
      TARGET_DIR           — Stage output directory.  Derived from stage_id as
                             <WORKSPACE>/<stage_id>-output so each stage writes to
                             its own subdirectory and never inherits a stale path
                             from a prior stage.
      BUILD_NUMBER         — Build identifier string (e.g. 'local-20240101-120000').
      RELEASE_TYPE         — Build type: NIGHTLY, WEEKLY, or RELEASE.
      PIPELINE_ROOT        — Absolute path to the ci-adoptium-pipelines checkout root.
                             Allows vendor stage scripts to source shared lib utilities
                             (e.g. scripts/lib/config-utils.sh) by a stable path that
                             is independent of the ephemeral WORKSPACE.
                             Jenkins equivalent: the pipeline repo is checked out into
                             every agent workspace so scripts/ is always at a fixed
                             relative path — PIPELINE_ROOT makes that same root
                             explicitly accessible in the local runner.

    CONFIG_* variables are populated from pipeline-config.json so that
    stage scripts (e.g. 02-build.sh) can read them without needing jq.

    Stage param values are injected last so vendor stage scripts can read
    them as environment variables without needing any other mechanism.

    If GITHUB_TOKEN is present in the ambient environment, a git-askpass.sh
    helper is written to the stage workspace and GIT_ASKPASS is set so that
    all git HTTPS operations in stage scripts are transparently authenticated
    without any changes to those scripts.

    Args:
        script_dir:          Root of the ci-adoptium-pipelines checkout.
        stage_workspace:     Ephemeral per-stage workspace directory.
        build_artifacts_dir: Durable artifact store directory.
        build_number:        Build identifier string.
        release_type:        Release type string (e.g. 'NIGHTLY').
        clean_workspace:     Whether --clean-workspace was requested.
        stage_param_values:  Dict of PARAM_NAME → value from collated stage params.
        stage_id:            Stage stem e.g. '02-build' — used to derive TARGET_DIR.
        extra:               Additional env vars to merge in last (highest priority).

    Returns:
        A copy of os.environ with all standard and config variables applied.
    """
    env = os.environ.copy()
    env["WORKSPACE"] = str(stage_workspace)
    env["PIPELINE_ROOT"] = str(script_dir)
    env["CONFIG_FILE"] = str(stage_workspace / "pipeline-config.json")
    env["INPUT_ARTIFACTS_DIR"] = str(stage_workspace)
    env["TARGET_DIR"] = str(resolve_target_dir(stage_workspace, stage_id))
    env["BUILD_NUMBER"] = build_number
    # Fixed job-level params that stage scripts read directly
    env["RELEASE_TYPE"] = release_type.upper()
    env["CLEAN_WORKSPACE_AFTER_STAGE"] = "true" if clean_workspace else "false"

    # Inject CONFIG_* variables from pipeline-config.json so that stage
    # shell scripts can consume them without a jq dependency.
    config_path = build_artifacts_dir / "pipeline-config.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        build_cfg = cfg.get("buildConfig", {})
        for key, value in build_cfg.items():
            env[f"CONFIG_{key}"] = str(value) if value is not None else ""

        repo_defaults = cfg.get("repoDefaults", {})
        if repo_defaults.get("buildRef"):
            env["CONFIG_BUILD_REF"] = repo_defaults["buildRef"]
        if repo_defaults.get("buildRepoUrl"):
            env["CONFIG_BUILD_REPO_URL"] = repo_defaults["buildRepoUrl"]
        if repo_defaults.get("aqaRef"):
            env["CONFIG_AQA_REF"] = repo_defaults["aqaRef"]
        if repo_defaults.get("aqaRepoUrl"):
            env["CONFIG_AQA_REPO_URL"] = repo_defaults["aqaRepoUrl"]

    # Inject collated stage params so vendor stage scripts can read them
    # as environment variables.  Stage params always override ambient env.
    for name, value in stage_param_values.items():
        env[name] = str(value)

    if extra:
        env.update(extra)

    # Configure GIT_ASKPASS for transparent GitHub HTTPS authentication.
    # Called after all other env vars (including any extra overrides) are set
    # so that stage_workspace is fully resolved before the script is written.
    _setup_git_auth(stage_workspace, env)

    return env
