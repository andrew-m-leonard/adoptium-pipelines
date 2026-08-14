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
# DEFAULT STUB: 07-installer
#
# Building platform-specific installers is vendor-specific.
# Override this stub by placing a script at:
#   config-repo/vendor-scripts/07-installer.{sh,groovy,py}
#
# Required Environment Variables (set by initializeStage):
#   WORKSPACE             - Stage workspace directory
#   CONFIG_FILE           - Path to pipeline-config.json
#   INPUT_ARTIFACTS_DIR   - Directory containing signed artifacts
#   BUILD_NUMBER          - Build number
#
# Stage-specific Environment Variables (set by Build Installers stage):
#   TARGET_DIR            - Directory for installer output
echo "ℹ️  Build Installers: no vendor implementation configured — skipping"
exit 0
