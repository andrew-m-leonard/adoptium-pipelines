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
set -euo pipefail

################################################################################
# Workspace Cleanup Utility
#
# Cleans the ephemeral workspace directory to support restartable pipelines.
# Can be called before (pre-cleanup) or after (post-cleanup) a stage.
#
# Required Environment Variables:
#   CONFIG_FILE       - Path to pipeline-config.json
#   WORKSPACE         - Jenkins/local workspace directory
#   CLEANUP_TYPE      - Either "pre" or "post"
#
# Configuration Parameters (read from CONFIG_FILE):
#   parameters.cleanWorkspaceAfterStage - Clean after stage (default: true)
#
# Behavior:
#   - Pre-cleanup: ALWAYS cleans workspace (critical for restartability)
#   - Post-cleanup: Cleans if cleanWorkspaceAfterStage=true (saves disk space)
################################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/logging-utils.sh"
source "${SCRIPT_DIR}/config-utils.sh"

# Validate required environment variables
require_env_var "CONFIG_FILE"
require_env_var "WORKSPACE"
require_env_var "CLEANUP_TYPE"

# Validate CLEANUP_TYPE
if [ "${CLEANUP_TYPE}" != "pre" ] && [ "${CLEANUP_TYPE}" != "post" ]; then
    log_error "CLEANUP_TYPE must be either 'pre' or 'post', got: ${CLEANUP_TYPE}"
    exit 1
fi

# Determine if cleanup should be performed
SHOULD_CLEAN="false"
CLEANUP_LABEL=""

if [ "${CLEANUP_TYPE}" = "pre" ]; then
    # Pre-cleanup: ALWAYS clean (critical for restartability)
    SHOULD_CLEAN="true"
    CLEANUP_LABEL="Pre-stage workspace cleanup"
elif [ "${CLEANUP_TYPE}" = "post" ]; then
    # Post-cleanup: Check configuration
    load_config "${CONFIG_FILE}"
    CLEAN_AFTER=$(get_config_value ".parameters.cleanWorkspaceAfterStage" "true")

    if [ "${CLEAN_AFTER}" = "true" ]; then
        SHOULD_CLEAN="true"
        CLEANUP_LABEL="Post-stage workspace cleanup"
    else
        log_info "Post-stage cleanup disabled (cleanWorkspaceAfterStage=false)"
        exit 0
    fi
fi

if [ "${SHOULD_CLEAN}" = "false" ]; then
    log_warning "Invalid CLEANUP_TYPE: ${CLEANUP_TYPE}"
    exit 1
fi

# Define workspace directory to clean
WORKSPACE_DIR="${WORKSPACE}/workspace"

# Perform cleanup
log_section "${CLEANUP_LABEL}"

if [ -d "${WORKSPACE_DIR}" ]; then
    log_info "Removing: ${WORKSPACE_DIR}"
    rm -rf "${WORKSPACE_DIR}"
    log_success "Workspace cleaned"
else
    log_info "Workspace directory does not exist: ${WORKSPACE_DIR}"
    log_info "Nothing to clean"
fi

# Made with Bob
