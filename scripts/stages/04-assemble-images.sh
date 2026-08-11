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
# DEFAULT STUB: 04-assemble-images
#
# Runs the final OpenJDK make image processing to assemble signed JMODs into
# a complete JDK image. Must run after 03-internal-code-sign so that the
# resulting image contains only signed internal binaries.
# Windows & Mac only. Not applicable to jdk8.
#
# Override this stub by placing a script at:
#   config-repo/vendor-scripts/04-assemble-images.{sh,groovy,py}
#
# Required Environment Variables (for vendor implementations):
#   WORKSPACE             - Stage workspace directory
#   CONFIG_FILE           - Path to pipeline-config.json
#   INPUT_ARTIFACTS_DIR   - Directory containing signed jmods
#   TARGET_DIR            - Directory for assembled JDK image output
echo "ℹ️  Assemble Images: no vendor implementation configured — skipping"
exit 0
