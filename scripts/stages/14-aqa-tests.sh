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
# Core Local Implementation: 14-aqa-tests
#
# Runs the Adoptium aqa-tests sanity.openjdk suite against the freshly built
# JDK.  This script is the local equivalent of the Jenkins-only
# scripts/stages/14-aqa-tests.groovy (which fires an asynchronous
# AQA_Test_Pipeline job).  It provides a synchronous local quality gate so
# that `run-pipeline.py` produces meaningful results rather than silently
# skipping the stage.
#
# Required Environment Variables (set by StageScriptRunner / initializeStage):
#   WORKSPACE            - Stage workspace directory
#   CONFIG_FILE          - Path to pipeline-config.json
#   INPUT_ARTIFACTS_DIR  - Directory containing the built JDK artifact(s)
#   BUILD_NUMBER         - Build number
#   TARGET_DIR           - Directory for test results output
#   BUILD_OUTPUT_DIR     - Relative subfolder under INPUT_ARTIFACTS_DIR
#                          containing build outputs (from stage-constants.properties)
#
# Optional Stage Parameter Environment Variables:
#   AQA_REF              - Git branch/tag for aqa-tests (falls back to
#                          .repoDefaults.aqaRef in pipeline-config.json, then 'master')
#
# Outputs (written to TARGET_DIR):
#   TKG/output/          - TKG test results
#   aqa-test-summary.json - Stage summary

set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve script directory to find shared lib utilities from ci-adoptium-pipelines
# PIPELINE_ROOT: set by CI pipelines where WORKSPACE is not the location of
#   the ci-adoptium-pipelines repo. Falls back to WORKSPACE if not set.
# ---------------------------------------------------------------------------
PIPELINE_LIB="${PIPELINE_ROOT:-${WORKSPACE}}/scripts/lib"
# shellcheck disable=SC1091
source "${PIPELINE_LIB}/logging-utils.sh"
# shellcheck disable=SC1091
source "${PIPELINE_LIB}/config-utils.sh"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
STAGE_NAME="aqa-tests"
BUILD_NUMBER="${BUILD_NUMBER:-local}"
BUILD_LIST="openjdk"
TARGET_SUITE="sanity.openjdk"

main() {
	log_section "AQA Tests (${TARGET_SUITE}) - Start"

	# -----------------------------------------------------------------------
	# Read build config
	# -----------------------------------------------------------------------
	local java_version
	local target_os
	local architecture
	local aqa_ref
	local aqa_repo_url
	java_version=$(get_config_value "${CONFIG_FILE}" ".buildConfig.JAVA_TO_BUILD")
	target_os=$(get_config_value "${CONFIG_FILE}" ".buildConfig.TARGET_OS")
	architecture=$(get_config_value "${CONFIG_FILE}" ".buildConfig.ARCHITECTURE")
	aqa_ref=$(get_config_value "${CONFIG_FILE}" ".repoDefaults.aqaRef")
	aqa_repo_url=$(get_config_value "${CONFIG_FILE}" ".repoDefaults.aqaRepoUrl")

	# Stage params take precedence; fall back to the repo defaults from
	# pipeline-config.json, then hard-coded 'master'.
	local aqa_tests_repo="${aqa_repo_url}"
	local aqa_tests_branch
	aqa_tests_branch="${AQA_REF:-${aqa_ref:-master}}"
	local aqa_ref_source="default"
	[[ -n "${AQA_REF:-}" ]] && aqa_ref_source="param"

	# -----------------------------------------------------------------------
	# Override build repo/ref from build-metadata.json when available.
	# The 02-build stage records the *actual* ref used after any SBOM-driven
	# override, which may differ from what was supplied as a stage parameter.
	# This ensures we test against the exact source that produced the artifact.
	# -----------------------------------------------------------------------
	local build_metadata_file="${INPUT_ARTIFACTS_DIR}/build-metadata.json"
	if [[ -f "${build_metadata_file}" ]]; then
		local meta_build_ref
		meta_build_ref=$(get_config_value "${build_metadata_file}" ".buildRef" "")
		if [[ -n "${meta_build_ref}" ]]; then
			aqa_tests_branch="${meta_build_ref}"
			aqa_ref_source="build-metadata"
		fi
	fi

	log_info "Test Configuration:"
	log_info "  Java Version : ${java_version}"
	log_info "  Target OS    : ${target_os}"
	log_info "  Architecture : ${architecture}"
	log_info "  AQA Suite    : ${BUILD_LIST} / ${TARGET_SUITE}"
	log_info "  AQA Repo     : ${aqa_tests_repo} (default)"
	log_info "  AQA Ref      : ${aqa_tests_branch} (${aqa_ref_source})"

	# -----------------------------------------------------------------------
	# Locate and extract the JDK artifact
	# -----------------------------------------------------------------------
	local jdk_artifact
	jdk_artifact=$(find_jdk_artifact)
	log_info "JDK artifact : ${jdk_artifact}"

	local jdk_extract_dir="${WORKSPACE}/jdk-aqa-extract"
	local test_jdk_home
	test_jdk_home=$(extract_jdk "${jdk_artifact}" "${jdk_extract_dir}" "${target_os}")
	log_info "TEST_JDK_HOME : ${test_jdk_home}"

	# -----------------------------------------------------------------------
	# Locate and extract the testimage artifact → TESTIMAGE_PATH
	#
	# Jenkins sets TESTIMAGE_PATH=$WORKSPACE/jdkbinary/openjdk-test-image after
	# get.sh extracts the testimage tarball there.  Locally we already have the
	# testimage archive in INPUT_ARTIFACTS_DIR/BUILD_OUTPUT_DIR; we extract it
	# ourselves and export the same variable so openjdk.mk can build the
	# -nativepath argument for jtreg.
	# -----------------------------------------------------------------------
	local testimage_extract_dir="${WORKSPACE}/testimage-aqa-extract"
	local testimage_path
	testimage_path=$(extract_testimage "${testimage_extract_dir}")
	if [[ -n "${testimage_path}" ]]; then
		export TESTIMAGE_PATH="${testimage_path}"
		log_info "TESTIMAGE_PATH : ${TESTIMAGE_PATH}"
	else
		log_warn "No testimage artifact found — -nativepath will not be set (tests requiring native code may fail)"
	fi

	# -----------------------------------------------------------------------
	# Clone aqa-tests
	# -----------------------------------------------------------------------
	local aqa_dir="${WORKSPACE}/aqa-tests"
	if [[ -d "${aqa_dir}" ]]; then
		log_error "aqa-tests directory already exists: ${aqa_dir}"
		log_error "Cannot guarantee its contents — aborting. Remove it and retry."
		exit 1
	fi
	log_info "Cloning aqa-tests from ${aqa_tests_repo} @ ${aqa_tests_branch} ..."
	git clone --depth 1 --branch "${aqa_tests_branch}" "${aqa_tests_repo}" "${aqa_dir}"

	# -----------------------------------------------------------------------
	# Run get.sh to pull in test material (no vendor repos, no OpenJ9)
	# -----------------------------------------------------------------------
	log_section "Running aqa-tests get.sh"
	cd "${aqa_dir}"
	bash get.sh --clone_openj9 false

	# -----------------------------------------------------------------------
	# Compile and run the test suite
	# -----------------------------------------------------------------------
	log_section "Compiling TKG test suite"
	cd "${aqa_dir}/TKG"

	export BUILD_LIST="${BUILD_LIST}"
	export TEST_JDK_HOME="${test_jdk_home}"

	make compile

	log_section "Running ${TARGET_SUITE}"
	local test_exit_code=0
	make "_${TARGET_SUITE}" || test_exit_code=$?

	# -----------------------------------------------------------------------
	# Collect results
	# -----------------------------------------------------------------------
	log_section "Collecting test results"
	collect_results "${aqa_dir}" "${test_exit_code}"

	if [[ ${test_exit_code} -eq 0 ]]; then
		log_section "AQA Tests - PASSED"
	else
		log_section "AQA Tests - FAILED (exit code: ${test_exit_code})"
	fi

	exit ${test_exit_code}
}

# ---------------------------------------------------------------------------
# Find and extract the testimage archive; return the openjdk-test-image path.
# Returns empty string (and a warning) when no testimage is present.
# ---------------------------------------------------------------------------
extract_testimage() {
	local extract_dir="$1"
	local artifacts_dir="${INPUT_ARTIFACTS_DIR}/${BUILD_OUTPUT_DIR}"

	local archive
	archive=$(find "${artifacts_dir}" \
		\( -name "*testimage*.tar.gz" -o -name "*testimage*.zip" \) |
		sort | head -n 1)

	if [[ -z "${archive}" ]]; then
		echo ""
		return 0
	fi

	log_info "Extracting testimage $(basename "${archive}") to ${extract_dir}"
	rm -rf "${extract_dir}"
	mkdir -p "${extract_dir}"

	if [[ "${archive}" == *.tar.gz ]]; then
		tar -xzf "${archive}" -C "${extract_dir}"
	elif [[ "${archive}" == *.zip ]]; then
		unzip -q "${archive}" -d "${extract_dir}"
	fi

	# The tarball expands to a single top-level directory (e.g. jdk-21+35-test-image).
	# Rename it to openjdk-test-image to match the path Jenkins uses, so that any
	# relative references inside TKG that assume that name continue to work.
	local top_dir
	top_dir=$(find "${extract_dir}" -maxdepth 1 -mindepth 1 -type d | head -n 1)

	if [[ -z "${top_dir}" ]]; then
		log_warn "Testimage archive extracted but no top-level directory found under ${extract_dir}"
		echo ""
		return 0
	fi

	local test_image_dir="${extract_dir}/openjdk-test-image"
	if [[ "${top_dir}" != "${test_image_dir}" ]]; then
		mv "${top_dir}" "${test_image_dir}"
	fi

	echo "${test_image_dir}"
}

# ---------------------------------------------------------------------------
# Find the main JDK image tarball/zip in INPUT_ARTIFACTS_DIR/BUILD_OUTPUT_DIR
# ---------------------------------------------------------------------------
find_jdk_artifact() {
	# Prefer the JDK image (pattern: *jdk_*.tar.gz or *jdk_*.zip)
	# Exclude jre/testimage/debugimage/static-libs variants
	# BUILD_OUTPUT_DIR is injected by the pipeline from stage-constants.properties.
	local artifacts_dir="${INPUT_ARTIFACTS_DIR}/${BUILD_OUTPUT_DIR}"
	local artifact
	artifact=$(find "${artifacts_dir}" \
		\( -name "*jdk_*.tar.gz" -o -name "*jdk_*.zip" \) \
		! -name "*jre_*" \
		! -name "*testimage*" \
		! -name "*debugimage*" \
		! -name "*static-libs*" |
		sort | head -n 1)

	if [[ -z "${artifact}" ]]; then
		log_error "No JDK image artifact found in ${artifacts_dir}"
		log_error "Expected pattern: *jdk_*.tar.gz or *jdk_*.zip"
		log_error "Available files:"
		find "${artifacts_dir}" \( -name "*.tar.gz" -o -name "*.zip" \) \
			-exec basename {} \; 2>/dev/null || true
		exit 1
	fi

	echo "${artifact}"
}

# ---------------------------------------------------------------------------
# Extract the JDK artifact and return the JAVA_HOME path
# ---------------------------------------------------------------------------
extract_jdk() {
	local artifact="$1"
	local extract_dir="$2"
	local target_os="$3"

	log_info "Extracting $(basename "${artifact}") to ${extract_dir}"
	rm -rf "${extract_dir}"
	mkdir -p "${extract_dir}"

	if [[ "${artifact}" == *.tar.gz ]]; then
		tar -xzf "${artifact}" -C "${extract_dir}"
	elif [[ "${artifact}" == *.zip ]]; then
		unzip -q "${artifact}" -d "${extract_dir}"
	else
		log_error "Unsupported archive format: ${artifact}"
		exit 1
	fi

	local top_dir
	top_dir=$(find "${extract_dir}" -maxdepth 1 -mindepth 1 -type d | head -n 1)

	if [[ -z "${top_dir}" ]]; then
		log_error "Could not find extracted JDK directory under ${extract_dir}"
		exit 1
	fi

	# macOS JDKs nest the home under Contents/Home
	if [[ "${target_os}" == "mac" && -d "${top_dir}/Contents/Home" ]]; then
		echo "${top_dir}/Contents/Home"
	else
		echo "${top_dir}"
	fi
}

# ---------------------------------------------------------------------------
# Copy TKG output and write a summary JSON to TARGET_DIR
# ---------------------------------------------------------------------------
collect_results() {
	local aqa_dir="$1"
	local test_exit_code="$2"

	mkdir -p "${TARGET_DIR}"

	local tkg_output="${aqa_dir}/TKG/output"
	if [[ -d "${tkg_output}" ]]; then
		cp -r "${tkg_output}/." "${TARGET_DIR}/"
		log_info "TKG results copied to ${TARGET_DIR}"
	else
		log_warn "TKG output directory not found: ${tkg_output}"
	fi

	cat >"${TARGET_DIR}/aqa-test-summary.json" <<EOF
{
  "stage": "${STAGE_NAME}",
  "buildList": "${BUILD_LIST}",
  "targetSuite": "${TARGET_SUITE}",
  "status": $([ "${test_exit_code}" -eq 0 ] && echo '"passed"' || echo '"failed"'),
  "exitCode": ${test_exit_code},
  "timestamp": $(date +%s),
  "timestampISO": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "buildNumber": "${BUILD_NUMBER}"
}
EOF

	log_info "Summary written to ${TARGET_DIR}/aqa-test-summary.json"
}

# ---------------------------------------------------------------------------
# Error trap
# ---------------------------------------------------------------------------
# shellcheck disable=SC2317  # error_handler is invoked indirectly via trap
error_handler() {
	log_error "AQA test stage failed at line $1"
	exit 1
}
trap 'error_handler ${LINENO}' ERR

main "$@"
