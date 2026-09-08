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
# CI-agnostic Smoke Test Stage Implementation
#
# Runs quick validation tests to ensure the JDK build is functional.
# Smoke tests performed:
#   1. Java version     — runs `java -version` and confirms the binary executes
#   2. Hello World      — compiles and runs a minimal Java class via javac + java
#   3. System properties — runs `java -XshowSettings:properties -version` and
#                          checks output contains java.version, java.home, or os.name
#   4. Class loading    — invokes `java -cp <jdk_home>/lib -version` to exercise
#                         the class-loader path
#
# Required Environment Variables:
#   WORKSPACE     - Stage workspace directory
#   CONFIG_FILE          - Path to pipeline-config.json
#   INPUT_ARTIFACTS_DIR  - Directory containing input artifacts from previous stage
#   TARGET_DIR           - Directory for this stage's output
#   BUILD_NUMBER         - Build number (optional)
#
# Outputs:
#   ${TARGET_DIR}/test-results/*  - Test results
#   stage-metadata.json           - Stage execution metadata
#
# Exit Codes:
#   0 - Tests passed
#   1 - Tests failed

set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve shared library utilities from ci-adoptium-pipelines.
# PIPELINE_ROOT: set by CI pipelines where WORKSPACE is not the location of
#   the ci-adoptium-pipelines repo. Falls back to WORKSPACE if not set.
# ---------------------------------------------------------------------------
PIPELINE_LIB="${PIPELINE_ROOT:-${WORKSPACE}}/scripts/lib"
# shellcheck disable=SC1091
source "${PIPELINE_LIB}/logging-utils.sh"
# shellcheck disable=SC1091
source "${PIPELINE_LIB}/config-utils.sh"
# shellcheck disable=SC1091
source "${PIPELINE_LIB}/artifact-utils.sh"

# Stage configuration
STAGE_NAME="smoke-test"
BUILD_NUMBER="${BUILD_NUMBER:-local}"

# Main execution
main() {
	log_section "Smoke Test Stage - Start"

	# Validate environment
	validate_standard_environment
	require_dir "${INPUT_ARTIFACTS_DIR}"
	require_dir "${TARGET_DIR}"

	# Load configuration
	log_info "Loading configuration from ${CONFIG_FILE}"

	# Extract configuration (pass file path directly)
	local java_version
	java_version=$(get_config_value "${CONFIG_FILE}" ".buildConfig.JAVA_TO_BUILD")
	local target_os
	target_os=$(get_config_value "${CONFIG_FILE}" ".buildConfig.TARGET_OS")
	local architecture
	architecture=$(get_config_value "${CONFIG_FILE}" ".buildConfig.ARCHITECTURE")

	log_info "Test Configuration:"
	log_info "  Java Version: ${java_version}"
	log_info "  Target OS: ${target_os}"
	log_info "  Architecture: ${architecture}"

	# Prepare output directory
	prepare_output_dir "${TARGET_DIR}"

	# Find JDK artifact
	local jdk_artifact
	jdk_artifact=$(find_jdk_artifact)
	log_info "Testing JDK: ${jdk_artifact}"

	# Extract JDK
	local jdk_dir
	jdk_dir=$(extract_jdk "${jdk_artifact}")

	# Run smoke tests
	local test_result=0
	run_smoke_tests "${jdk_dir}" || test_result=$?

	# Create test metadata
	if [[ ${test_result} -eq 0 ]]; then
		create_test_metadata "passed"
		log_section "Smoke Test Stage - PASSED"
	else
		create_test_metadata "failed"
		log_section "Smoke Test Stage - FAILED"
	fi

	exit ${test_result}
}

# Find JDK artifact to test
find_jdk_artifact() {
	# Look for the main JDK image, excluding other image types
	# JDK image pattern: *jdk_*.tar.gz or *jdk_*.zip (Windows)
	local artifact
	artifact=$(find "${INPUT_ARTIFACTS_DIR}" \( -name "*jdk_*.tar.gz" -o -name "*jdk_*.zip" \) |
		head -n 1)

	if [[ -z "${artifact}" ]]; then
		log_error "No JDK image artifact found in ${INPUT_ARTIFACTS_DIR}"
		log_error "Looking for pattern: *jdk_*.tar.gz or *jdk_*.zip"
		log_error "Available artifacts:"
		find "${INPUT_ARTIFACTS_DIR}" \( -name "*.tar.gz" -o -name "*.zip" \) -exec basename {} \; || true
		exit 1
	fi

	log_info "Found JDK artifact: $(basename "${artifact}")"
	echo "${artifact}"
}

# Extract JDK for testing
extract_jdk() {
	local artifact=$1
	local extract_dir="${WORKSPACE}/jdk-test"

	log_info "Extracting JDK to ${extract_dir}"

	rm -rf "${extract_dir}"
	mkdir -p "${extract_dir}"

	# Extract based on file extension
	if [[ "${artifact}" == *.tar.gz ]]; then
		tar -xzf "${artifact}" -C "${extract_dir}"
	elif [[ "${artifact}" == *.zip ]]; then
		unzip -q "${artifact}" -d "${extract_dir}"
	else
		log_error "Unsupported archive format: ${artifact}"
		exit 1
	fi

	# Find the JDK directory (usually has a version in the name)
	local jdk_dir
	jdk_dir=$(find "${extract_dir}" -maxdepth 1 -type d ! -path "${extract_dir}" | head -n 1)

	if [[ -z "${jdk_dir}" ]]; then
		log_error "Failed to find extracted JDK directory"
		exit 1
	fi

	log_info "JDK extracted to: ${jdk_dir}"

	# Return the path (echo to stdout for capture)
	echo "${jdk_dir}"
}

# Run smoke tests
run_smoke_tests() {
	local jdk_dir=$1
	local java_bin=""
	local jdk_home=""

	log_section "Running Smoke Tests"

	# Determine JDK home location (platform-specific)
	# macOS: jdk-dir/Contents/Home
	# Linux/Others: jdk-dir
	if [[ -f "${jdk_dir}/Contents/Home/bin/java" ]]; then
		jdk_home="${jdk_dir}/Contents/Home"
		java_bin="${jdk_home}/bin/java"
		log_info "Detected macOS JDK structure"
	elif [[ -f "${jdk_dir}/bin/java" ]]; then
		jdk_home="${jdk_dir}"
		java_bin="${jdk_home}/bin/java"
		log_info "Detected Linux/standard JDK structure"
	else
		log_error "Java binary not found in expected locations:"
		log_error "  - ${jdk_dir}/Contents/Home/bin/java (macOS)"
		log_error "  - ${jdk_dir}/bin/java (Linux)"
		log_error "JDK directory contents:"
		ls -la "${jdk_dir}" || true
		return 1
	fi

	log_info "Using JDK home: ${jdk_home}"
	log_info "Using Java binary: ${java_bin}"

	local test_failed=0

	# Test 1: Java version
	test_java_version "${java_bin}" || test_failed=1

	# Test 2: Hello World (needs javac)
	test_hello_world "${java_bin}" "${jdk_home}" || test_failed=1

	# Test 3: System properties
	test_system_properties "${java_bin}" || test_failed=1

	# Test 4: Class loading
	test_class_loading "${java_bin}" "${jdk_home}" || test_failed=1

	if [[ ${test_failed} -eq 0 ]]; then
		log_info "All smoke tests passed ✓"
		return 0
	else
		log_error "Some smoke tests failed ✗"
		return 1
	fi
}

# Test: Java version
test_java_version() {
	local java_bin=$1

	log_info "Test 1: Java version"

	if "${java_bin}" -version 2>&1 | tee "${TARGET_DIR}/java-version.txt"; then
		log_info "  ✓ Java version test passed"
		return 0
	else
		log_error "  ✗ Java version test failed"
		return 1
	fi
}

# Test: Hello World
test_hello_world() {
	local java_bin=$1
	local jdk_home=$2
	local javac_bin="${jdk_home}/bin/javac"

	log_info "Test 2: Hello World"

	# Create a simple Hello World program
	local test_dir="${WORKSPACE}/test-hello"
	mkdir -p "${test_dir}"

	cat >"${test_dir}/HelloWorld.java" <<'EOF'
public class HelloWorld {
    public static void main(String[] args) {
        System.out.println("Hello, World!");
    }
}
EOF

	# Compile
	if "${javac_bin}" "${test_dir}/HelloWorld.java" 2>&1 | tee "${TARGET_DIR}/hello-compile.txt"; then
		log_info "  ✓ Compilation successful"
	else
		log_error "  ✗ Compilation failed"
		return 1
	fi

	# Run
	if "${java_bin}" -cp "${test_dir}" HelloWorld 2>&1 | tee "${TARGET_DIR}/hello-run.txt" | grep -q "Hello, World!"; then
		log_info "  ✓ Hello World test passed"
		return 0
	else
		log_error "  ✗ Hello World test failed"
		return 1
	fi
}

# Test: System properties
test_system_properties() {
	local java_bin=$1

	log_info "Test 3: System properties"

	# Run the command and capture output
	if "${java_bin}" -XshowSettings:properties -version >"${TARGET_DIR}/system-properties.txt" 2>&1; then
		# Check if output contains expected properties
		if grep -q "java.version" "${TARGET_DIR}/system-properties.txt" ||
			grep -q "java.home" "${TARGET_DIR}/system-properties.txt" ||
			grep -q "os.name" "${TARGET_DIR}/system-properties.txt"; then
			log_info "  ✓ System properties test passed"
			return 0
		else
			log_error "  ✗ System properties test failed - no properties found in output"
			log_debug "Output file: ${TARGET_DIR}/system-properties.txt"
			return 1
		fi
	else
		log_error "  ✗ System properties test failed - command execution failed"
		return 1
	fi
}

# Test: Class loading
test_class_loading() {
	local java_bin=$1
	local jdk_home=$2

	log_info "Test 4: Class loading"

	# Test loading a standard Java class
	if "${java_bin}" -cp "${jdk_home}/lib" -version 2>&1 | tee "${TARGET_DIR}/class-loading.txt"; then
		log_info "  ✓ Class loading test passed"
		return 0
	else
		log_error "  ✗ Class loading test failed"
		return 1
	fi
}

# Create test metadata
create_test_metadata() {
	local status=$1

	cat >"${WORKSPACE}/test-metadata.json" <<EOF
{
  "stage": "${STAGE_NAME}",
  "status": "${status}",
  "timestamp": $(date +%s),
  "buildNumber": "${BUILD_NUMBER}",
  "smokeTestsPassed": $([ "${status}" = "passed" ] && echo "true" || echo "false")
}
EOF

	# Also create stage metadata
	create_stage_metadata "${STAGE_NAME}" "${status}"

	log_info "Test metadata created"
}

# Error handler (called indirectly via trap)
# shellcheck disable=SC2317
error_handler() {
	local line_number=$1
	log_error "Smoke test stage failed at line ${line_number}"
	create_test_metadata "failed"
	exit 1
}

# Set error trap
trap 'error_handler ${LINENO}' ERR

# Execute main function
main "$@"

# Made with Bob
