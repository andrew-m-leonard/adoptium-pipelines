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
# CI-agnostic Create API Metadata Stage Implementation
#
# This stage creates associated .json metadata files for every build artifact in
# BUILD_OUTPUT_DIR (e.g. OpenJDK21U-jdk_x64_linux_hotspot_21.0.9_10.tar.gz.json,
# and OpenJDK21U-sbom_...-metadata.json for SBOMs).
# The metadata is queried by the Adoptium API server when serving release assets.
#
# Required Environment Variables (set by initializeStage / local runner):
#   WORKSPACE           - Stage workspace directory
#   CONFIG_FILE         - Path to pipeline-config.json
#   INPUT_ARTIFACTS_DIR - Directory containing build artifacts and build-metadata.json
#   TARGET_DIR          - Directory for output artifacts
#   BUILD_NUMBER        - Build number
#
# Stage Constants:
#   BUILD_OUTPUT_DIR    - Relative subfolder under INPUT_ARTIFACTS_DIR / TARGET_DIR
#
# Outputs:
#   ${TARGET_DIR}/${BUILD_OUTPUT_DIR}/*.json - Generated API metadata JSON files
#   stage-metadata.json                      - Stage execution metadata

set -euo pipefail

# ---------------------------------------------------------------------------
# Resolve shared library utilities from ci-adoptium-pipelines.
# ---------------------------------------------------------------------------
PIPELINE_LIB="${PIPELINE_ROOT:-${WORKSPACE}}/scripts/lib"
# shellcheck disable=SC1091
source "${PIPELINE_LIB}/logging-utils.sh"
# shellcheck disable=SC1091
source "${PIPELINE_LIB}/config-utils.sh"
# shellcheck disable=SC1091
source "${PIPELINE_LIB}/artifact-utils.sh"
# shellcheck disable=SC1091
source "${PIPELINE_LIB}/load-stage-constants.sh"

STAGE_NAME="180-create-api-metadata"
BUILD_NUMBER="${BUILD_NUMBER:-local}"

main() {
	log_section "Create API Metadata Stage - Start"

	validate_standard_environment

	local input_dir="${INPUT_ARTIFACTS_DIR:-${WORKSPACE}}"
	local target_dir="${TARGET_DIR:-${WORKSPACE}}"
	local build_output_dir_name="${BUILD_OUTPUT_DIR:-build_output}"
	local artifacts_dir="${input_dir}/${build_output_dir_name}"
	local target_output_dir="${target_dir}/${build_output_dir_name}"

	# Ensure build-metadata.json exists
	local build_metadata_file="${input_dir}/build-metadata.json"
	if [[ ! -f "${build_metadata_file}" ]]; then
		# Check if it was placed inside artifacts_dir or WORKSPACE
		if [[ -f "${artifacts_dir}/build-metadata.json" ]]; then
			build_metadata_file="${artifacts_dir}/build-metadata.json"
		elif [[ -f "${WORKSPACE}/build-metadata.json" ]]; then
			build_metadata_file="${WORKSPACE}/build-metadata.json"
		else
			log_error "build-metadata.json not found in ${input_dir} or ${WORKSPACE}"
			exit 1
		fi
	fi

	log_info "Input artifacts directory: ${artifacts_dir}"
	log_info "Using build metadata file: ${build_metadata_file}"
	log_info "Target output directory:   ${target_output_dir}"

	prepare_output_dir "${target_dir}"
	mkdir -p "${target_output_dir}"

	# If target_output_dir differs from artifacts_dir, copy all existing artifacts first
	if [[ "$(resolve_dir_path "${artifacts_dir}")" != "$(resolve_dir_path "${target_output_dir}")" && -d "${artifacts_dir}" ]]; then
		log_info "Copying existing artifacts to ${target_output_dir}"
		cp -R "${artifacts_dir}/." "${target_output_dir}/"
	fi

	# Also copy build-metadata.json to TARGET_DIR root if target_dir differs from input_dir
	if [[ -f "${build_metadata_file}" && "$(resolve_dir_path "${input_dir}")" != "$(resolve_dir_path "${target_dir}")" ]]; then
		cp "${build_metadata_file}" "${target_dir}/"
	fi

	# Execute api-metadata-generator.py
	log_info "Running api-metadata-generator.py..."
	"${PIPELINE_LIB}/python-runner.sh" "${PIPELINE_LIB}/api-metadata-generator.py" \
		--build-metadata "${build_metadata_file}" \
		--artifacts-dir "${target_output_dir}" \
		--output-dir "${target_output_dir}"

	# Create checksums for any newly created files
	create_checksums "${target_dir}"

	# Create stage metadata
	create_stage_metadata "${STAGE_NAME}" "success"

	# List final artifacts
	list_artifacts "${target_dir}"

	log_section "Create API Metadata Stage - Complete"
}

# Resolve directory canonical path helper
resolve_dir_path() {
	local dir_path="$1"
	if [[ -d "${dir_path}" ]]; then
		(cd "${dir_path}" && pwd)
	else
		printf '%s' "${dir_path}"
	fi
}

error_handler() {
	local line_number=$1
	log_error "Create API metadata stage failed at line ${line_number}"
	create_stage_metadata "${STAGE_NAME}" "failed"
	exit 1
}

trap 'error_handler ${LINENO}' ERR

main "$@"
