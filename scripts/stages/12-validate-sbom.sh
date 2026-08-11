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
# DEFAULT STUB: 12-validate-sbom
#
# Validates SBOM (Software Bill of Materials) files produced during the Build
# stage. Only applicable when SBOMs are generated (CREATE_SBOM=true).
#
# The validation tooling and acceptance criteria are vendor-specific (e.g.,
# Temurin uses temurin-build/tooling/validateSBOM.sh).
#
# Override this stub by placing a script at:
#   config-repo/vendor-scripts/12-validate-sbom.{sh,groovy,py}
#
# Required Environment Variables (for vendor implementations):
#   WORKSPACE            - Stage workspace directory
#   CONFIG_FILE          - Path to pipeline-config.json
#   INPUT_ARTIFACTS_DIR  - Directory containing *sbom*.json files from Build
#   TARGET_DIR           - Directory for validation report output
echo "ℹ️  Validate SBOM: no vendor implementation configured — skipping"
exit 0
