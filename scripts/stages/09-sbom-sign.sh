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
# DEFAULT STUB: 09-sbom-sign
#
# JSF-signs the SBOM by embedding a JSON signature directly inside the SBOM
# document. Must run before 10-digital-artifact-sign so that the signed SBOM
# is included in the set of artifacts that receive a detached GPG signature.
# Only applicable when SBOMs are generated (CREATE_SBOM=true).
#
# Override this stub by placing a script at:
#   config-repo/vendor-scripts/09-sbom-sign.{sh,groovy,py}
#
# Required Environment Variables (for vendor implementations):
#   WORKSPACE             - Stage workspace directory
#   CONFIG_FILE           - Path to pipeline-config.json
#   INPUT_ARTIFACTS_DIR   - Directory containing SBOM files
#   TARGET_DIR            - Directory for JSF-signed SBOM output
echo "ℹ️  SBOM Sign: no vendor implementation configured — skipping"
exit 0
