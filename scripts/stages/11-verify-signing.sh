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
# DEFAULT STUB: 11-verify-signing
#
# Verifies that all necessary signing has been completed successfully.
# Checks that Windows and macOS executables are code-signed, installer packages
# are code-signed (and notarized on macOS), and that detached GPG signatures
# (.sig / .asc) are present for every distribution artifact.
#
# Override this stub by placing a script at:
#   config-repo/vendor-scripts/11-verify-signing.{sh,groovy,py}
#
# Required Environment Variables (for vendor implementations):
#   WORKSPACE             - Stage workspace directory
#   CONFIG_FILE           - Path to pipeline-config.json
#   INPUT_ARTIFACTS_DIR   - Directory containing signed artifacts and signatures
#   TARGET_DIR            - Directory for verification report output
echo "ℹ️  Verify Signing: no vendor implementation configured — skipping"
exit 0
