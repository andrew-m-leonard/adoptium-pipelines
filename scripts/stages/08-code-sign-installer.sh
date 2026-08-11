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
# DEFAULT STUB: 08-code-sign-installer
#
# Code signs installer packages (.msi on Windows, .pkg on macOS).
# On macOS, also submits the signed package to Apple for Notarization
# and staples the notarization ticket to the installer.
# Windows & Mac only.
#
# Override this stub by placing a script at:
#   config-repo/vendor-scripts/08-code-sign-installer.{sh,groovy,py}
#
# Required Environment Variables (for vendor implementations):
#   WORKSPACE             - Stage workspace directory
#   CONFIG_FILE           - Path to pipeline-config.json
#   INPUT_ARTIFACTS_DIR   - Directory containing installers from Build Installer stage
#   TARGET_DIR            - Directory for signed installer output
echo "ℹ️  Code Sign Installer: no vendor implementation configured — skipping"
exit 0
