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
from pathlib import Path


def build_stage_env(
    *,
    script_dir: Path,
    stage_workspace: Path,
    build_artifacts_dir: Path,
    build_number: str,
    release_type: str,
    clean_workspace: bool,
    stage_param_values: dict[str, str],
    extra: dict | None = None,
) -> dict:
    """
    Build the standard environment dict passed to every stage script.

    Mirrors PipelineHelper.initializeStage() in Jenkins.

    All five standard variables are set:
      WORKSPACE, CONFIG_FILE, INPUT_ARTIFACTS_DIR, TARGET_DIR, BUILD_NUMBER
    plus PIPELINE_ROOT for vendor scripts that source shared lib utilities.

    CONFIG_* variables are populated from pipeline-config.json so that
    stage scripts (e.g. 02-build.sh) can read them without needing jq.

    Stage param values are injected last so vendor stage scripts can read
    them as environment variables without needing any other mechanism.

    Args:
        script_dir:          Root of the ci-adoptium-pipelines checkout.
        stage_workspace:     Ephemeral per-stage workspace directory.
        build_artifacts_dir: Durable artifact store directory.
        build_number:        Build identifier string.
        release_type:        Release type string (e.g. 'NIGHTLY').
        clean_workspace:     Whether --clean-workspace was requested.
        stage_param_values:  Dict of PARAM_NAME → value from collated stage params.
        extra:               Additional env vars to merge in last (highest priority).

    Returns:
        A copy of os.environ with all standard and config variables applied.
    """
    env = os.environ.copy()
    env['WORKSPACE']                   = str(stage_workspace)
    env['PIPELINE_ROOT']               = str(script_dir)
    env['CONFIG_FILE']                 = str(stage_workspace / 'pipeline-config.json')
    env['INPUT_ARTIFACTS_DIR']         = str(stage_workspace)
    env['TARGET_DIR']                  = str(stage_workspace / 'target')
    env['BUILD_NUMBER']                = build_number
    # Fixed job-level params that stage scripts read directly
    env['RELEASE_TYPE']                = release_type.upper()
    env['CLEAN_WORKSPACE_AFTER_STAGE'] = 'true' if clean_workspace else 'false'

    # Inject CONFIG_* variables from pipeline-config.json so that stage
    # shell scripts can consume them without a jq dependency.
    config_path = build_artifacts_dir / 'pipeline-config.json'
    if config_path.exists():
        with open(config_path, 'r') as f:
            cfg = json.load(f)

        build_cfg = cfg.get('buildConfig', {})
        for key, value in build_cfg.items():
            env[f'CONFIG_{key}'] = str(value) if value is not None else ''

        repo_defaults = cfg.get('repoDefaults', {})
        if repo_defaults.get('buildRef'):
            env['CONFIG_BUILD_REF'] = repo_defaults['buildRef']
        if repo_defaults.get('buildRepoUrl'):
            env['CONFIG_BUILD_REPO_URL'] = repo_defaults['buildRepoUrl']
        if repo_defaults.get('aqaRef'):
            env['CONFIG_AQA_REF'] = repo_defaults['aqaRef']
        if repo_defaults.get('aqaRepoUrl'):
            env['CONFIG_AQA_REPO_URL'] = repo_defaults['aqaRepoUrl']

    # Inject collated stage params so vendor stage scripts can read them
    # as environment variables.  Stage params always override ambient env.
    for name, value in stage_param_values.items():
        env[name] = str(value)

    if extra:
        env.update(extra)
    return env
