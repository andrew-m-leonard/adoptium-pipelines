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
# Test script for determine_filename function

set -e

# Source the utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../scripts/lib/logging-utils.sh"
source "${SCRIPT_DIR}/../scripts/lib/artifact-utils.sh"

echo "=========================================="
echo "Testing determine_filename Function"
echo "=========================================="
echo ""

# Test 1: JDK 21 Linux x64 Temurin with SCM_REF
echo "Test 1: JDK 21 Linux x64 Temurin with SCM_REF"
export JAVA_TO_BUILD="jdk21u"
export ARCHITECTURE="x64"
export TARGET_OS="linux"
export VARIANT="temurin"
export SCM_REF="jdk-21.0.5+11"
determine_filename
echo "Result: ${FILENAME}"
echo "Expected: OpenJDK21U-jdk_x64_linux_hotspot_21.0.5_11.tar.gz"
echo ""

# Test 2: JDK 17 Windows aarch64 OpenJ9 with SCM_REF
echo "Test 2: JDK 17 Windows aarch64 OpenJ9 with SCM_REF"
export JAVA_TO_BUILD="jdk17u"
export ARCHITECTURE="aarch64"
export TARGET_OS="windows"
export VARIANT="openj9"
export SCM_REF="jdk-17.0.10+7"
determine_filename
echo "Result: ${FILENAME}"
echo "Expected: OpenJDK17U-jdk_aarch64_windows_openj9_17.0.10_7.zip"
echo ""

# Test 3: JDK 8 Mac x64 Hotspot with SCM_REF
echo "Test 3: JDK 8 Mac x64 Hotspot with SCM_REF"
export JAVA_TO_BUILD="jdk8u"
export ARCHITECTURE="x64"
export TARGET_OS="mac"
export VARIANT="hotspot"
export SCM_REF="jdk8u412-b08"
determine_filename
echo "Result: ${FILENAME}"
echo "Expected: OpenJDK8U-jdk_x64_mac_hotspot_8u412b08.tar.gz"
echo ""

# Test 4: JDK 11 Linux x64 Temurin without SCM_REF (timestamp)
echo "Test 4: JDK 11 Linux x64 Temurin without SCM_REF (uses timestamp)"
export JAVA_TO_BUILD="jdk11u"
export ARCHITECTURE="x64"
export TARGET_OS="linux"
export VARIANT="temurin"
unset SCM_REF
determine_filename
echo "Result: ${FILENAME}"
echo "Expected: OpenJDK11U-jdk_x64_linux_hotspot_YYYY-MM-DD-HH-MM.tar.gz"
echo ""

# Test 5: JDK (head) Linux x64 Temurin
echo "Test 5: JDK (head) Linux x64 Temurin"
export JAVA_TO_BUILD="jdk"
export ARCHITECTURE="x64"
export TARGET_OS="linux"
export VARIANT="temurin"
export SCM_REF="jdk-24+12"
determine_filename
echo "Result: ${FILENAME}"
echo "Expected: OpenJDK-jdk_x64_linux_hotspot_24_12.tar.gz (no U suffix for head)"
echo ""

# Test 6: JDK 21 AIX ppc64 Temurin
echo "Test 6: JDK 21 AIX ppc64 Temurin"
export JAVA_TO_BUILD="jdk21u"
export ARCHITECTURE="ppc64"
export TARGET_OS="aix"
export VARIANT="temurin"
export SCM_REF="jdk-21.0.5+11"
determine_filename
echo "Result: ${FILENAME}"
echo "Expected: OpenJDK21U-jdk_ppc64_aix_hotspot_21.0.5_11.tar.gz"
echo ""

# Test 7: Missing required variables (should fail)
echo "Test 7: Missing required variables (should fail)"
unset JAVA_TO_BUILD
export ARCHITECTURE="x64"
export TARGET_OS="linux"
export VARIANT="temurin"
if determine_filename 2>/dev/null; then
	echo "ERROR: Should have failed with missing JAVA_TO_BUILD"
	exit 1
else
	echo "✓ Correctly failed with missing required variable"
fi
echo ""

# Test 8: Lowercase java_to_build (should be converted to uppercase)
echo "Test 8: Lowercase java_to_build (should be converted to uppercase)"
export JAVA_TO_BUILD="jdk21u"
export ARCHITECTURE="x64"
export TARGET_OS="linux"
export VARIANT="temurin"
export SCM_REF="jdk-21.0.5+11"
determine_filename
echo "Result: ${FILENAME}"
echo "Expected: OpenJDK21U-jdk_x64_linux_hotspot_21.0.5_11.tar.gz"
echo ""

echo "=========================================="
echo "All Tests Complete"
echo "=========================================="

# Made with Bob
