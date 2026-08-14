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
# DEFAULT STUB: 06-post-build-code-sign
#
# Code signs EXEs/DLLs and dylibs that were not signed during the internal
# signing stage (03-internal-code-sign). This covers all binaries for jdk8
# (which has no internal signing stage), and the limited set of jdk11+
# binaries that exist outside of JMODs.
# Windows & Mac only.
#
# Override this stub by placing a script at:
#   config-repo/vendor-scripts/06-post-build-code-sign.{sh,groovy,py}
#
# Required Environment Variables (for vendor implementations):
#   WORKSPACE             - Stage workspace directory
#   CONFIG_FILE           - Path to pipeline-config.json
#   INPUT_ARTIFACTS_DIR   - Directory containing the assembled JDK image
#   TARGET_DIR            - Directory for code-signed output
echo "ℹ️  Post-Build Code Sign: no vendor implementation configured — skipping"
exit 0
