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
# DEFAULT STUB: 14-aqa-tests
#
# AQA test execution is vendor-specific.
# Override this stub by placing a script at:
#   config-repo/vendor-scripts/14-aqa-tests.{sh,groovy,py}
#
# Required Environment Variables (for vendor implementations):
#   WORKSPACE             - Stage workspace directory
#   CONFIG_FILE           - Path to pipeline-config.json
#   INPUT_ARTIFACTS_DIR   - Directory containing JDK artifacts to test
#   TARGET_DIR            - Directory for test results output

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/logging-utils.sh"

# AQA_REF stage param takes precedence; fall back to CONFIG_AQA_REF then 'master'.
aqa_ref="${AQA_REF:-${CONFIG_AQA_REF:-master}}"
aqa_ref_source="default"
[[ -n "${AQA_REF:-}" ]] && aqa_ref_source="param"
aqa_repo_url="${CONFIG_AQA_REPO_URL:-https://github.com/adoptium/aqa-tests.git}"

log_info "Test Configuration:"
log_info "  AQA Repo URL: ${aqa_repo_url} (default)"
log_info "  AQA Ref: ${aqa_ref} (${aqa_ref_source})"

echo "ℹ️  AQA Tests: no vendor implementation configured — skipping"
exit 0
