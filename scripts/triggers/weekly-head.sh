#!/bin/bash
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
# weekly-head.sh
#
# CI-agnostic trigger script for scheduled weekly HEAD builds.
# Does no tag detection — simply signals that a build should be triggered
# for the HEAD of the given version.
#
# This script exists as a vendor override point. Vendors that need pre-trigger
# logic before a weekly HEAD build can replace it via:
#   config-repo/vendor-triggers/weekly-head.sh
#
# Jenkinsfile.trigger handles the weekly-head type as a built-in when this
# script is absent — so the script is optional. When present its output is
# honoured, allowing a vendor override to suppress a weekly build by writing
# shouldTrigger=false (e.g. during a release freeze).
#
# Required env:
#   WORKSPACE                    — working directory
#   TARGET_DIR                   — directory to write trigger-result.json
#   TRIGGER_VERSION_CONFIG_FILE  — path to trigger-version-config.json
#                                  (written by TriggerScriptRunner)
#
# Optional env:
#   PIPELINE_ROOT  — root of ci-adoptium-pipelines checkout;
#                    falls back to WORKSPACE
#
# trigger-version-config.json fields:
#   version  (required) — JDK version string, e.g. "jdk25"
#
# Outputs $TARGET_DIR/trigger-result.json:
#   {
#     "shouldTrigger": true,
#     "scmRef":        "",
#     "releaseType":   "Weekly"
#   }

set -euo pipefail

PIPELINE_LIB="${PIPELINE_ROOT:-${WORKSPACE}}/scripts/lib"
# shellcheck source=scripts/lib/logging-utils.sh
source "${PIPELINE_LIB}/logging-utils.sh"
# shellcheck source=scripts/lib/config-utils.sh
source "${PIPELINE_LIB}/config-utils.sh"

TRIGGER_UTILS="python3 ${PIPELINE_LIB}/trigger-utils.py"

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
main() {
    log_section "weekly-head — Start"

    require_env "WORKSPACE"
    require_env "TARGET_DIR"
    require_env "TRIGGER_VERSION_CONFIG_FILE"
    require_file "${TRIGGER_VERSION_CONFIG_FILE}"

    mkdir -p "${TARGET_DIR}"

    local version
    version=$(get_config_value "${TRIGGER_VERSION_CONFIG_FILE}" ".version")
    log_info "version : ${version}"

    # Unconditionally signal a trigger — no tag detection needed.
    # scmRef is empty: the build pipeline will use HEAD of the configured branch.
    ${TRIGGER_UTILS} write-trigger-result "${TARGET_DIR}" \
        "shouldTrigger=true" \
        "scmRef=" \
        "releaseType=Weekly"

    log_info "trigger-result.json written to ${TARGET_DIR}"
    log_section "weekly-head — Complete"
}

main "$@"
