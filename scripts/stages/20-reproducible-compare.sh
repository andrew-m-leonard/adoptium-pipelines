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
# DEFAULT STUB: 20-reproducible-compare
#
# Compares a locally built JDK against the vendor's published production binary
# to verify bit-for-bit reproducibility. The comparison tooling, the binary
# source (API endpoint, artifact store, etc.), and acceptance criteria are all
# vendor-specific (e.g., Temurin downloads from api.adoptium.net and uses
# temurin-build/tooling/reproducible/repro_compare.sh).
#
# Override this stub by placing a script at:
#   config-repo/vendor-scripts/20-reproducible-compare.{sh,groovy,py}
#
# Required Environment Variables (for vendor implementations):
#   WORKSPACE            - Stage workspace directory
#   CONFIG_FILE          - Path to pipeline-config.json
#   INPUT_ARTIFACTS_DIR  - Directory containing locally built JDK tarballs/zips
#   TARGET_DIR           - Directory for comparison report output
#   SCM_REF              - Git tag/ref for the build (e.g., jdk-21.0.2+13)
#   RELEASE_TYPE         - Build type: RELEASE or NIGHTLY (default: NIGHTLY)
echo "ℹ️  Reproducible Compare: no vendor implementation configured — skipping"
exit 0
