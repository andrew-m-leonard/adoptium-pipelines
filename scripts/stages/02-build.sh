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
# CI-agnostic Build Stage Implementation
#
# This script replicates the build stage from openjdk_build_pipeline.groovy
# It calls build-farm/make-adopt-build-farm.sh exactly as the Jenkins pipeline does.
# This ensures reliable, reproducible builds without relying on caches.
#
# Prerequisites:
#   - temurin-build repository cloned in workspace
#   - Required build tools installed (make, gcc, etc.)
#
# Required Environment Variables:
#   WORKSPACE     - Stage workspace directory
#   CONFIG_FILE   - Path to pipeline-config.json
#   TARGET_DIR    - Directory for build artifacts (reads/writes here)
#   BUILD_NUMBER  - Build number (optional, defaults to 'local')
#
# Outputs:
#   ${TARGET_DIR}/**/*           - Built JDK artifacts
#   stage-metadata.json          - Stage execution metadata

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
STAGE_NAME="build"
BUILD_NUMBER="${BUILD_NUMBER:-local}"

# Main execution
main() {
	log_section "Build Stage - Start"

	# Validate environment
	validate_standard_environment

	# Read build configuration from CONFIG_* environment variables set by the pipeline.
	# CONFIG_BUILD_ARGS / CONFIG_CONFIGURE_ARGS are the config-file baselines from
	# platform buildConfigurations. EXTRA_BUILD_ARGS / EXTRA_CONFIGURE_ARGS are the
	# stage params set by the operator at trigger time. Both are merged below.
	local java_to_build="${CONFIG_JAVA_TO_BUILD:-}"
	local target_os="${CONFIG_TARGET_OS:-}"
	local architecture="${CONFIG_ARCHITECTURE:-}"
	local variant="${CONFIG_VARIANT:-}"
	local build_args="${CONFIG_BUILD_ARGS:-}${EXTRA_BUILD_ARGS:+ ${EXTRA_BUILD_ARGS}}"
	local configure_args="${CONFIG_CONFIGURE_ARGS:-}${EXTRA_CONFIGURE_ARGS:+ ${EXTRA_CONFIGURE_ARGS}}"
	local make_args="${EXTRA_MAKE_OPTIONS:-}"
	local create_sbom="${CREATE_SBOM:-true}"
	local scm_ref="${SCM_REF:-}"
	# BUILD_REF stage param takes precedence; fall back to the repo default
	# from pipeline-config.json (CONFIG_BUILD_REF), then hard-coded 'master'.
	local build_ref="${BUILD_REF:-${CONFIG_BUILD_REF:-master}}"
	local build_ref_source
	[[ -n "${BUILD_REF:-}" ]] && build_ref_source="param" || build_ref_source="default"
	local build_repo_url="${CONFIG_BUILD_REPO_URL:-https://github.com/adoptium/temurin-build.git}"
	local clean_workspace="${CLEAN_WORKSPACE_AFTER_STAGE:-false}"
	local release_type="${RELEASE_TYPE:-NIGHTLY}"
	local compare_build="${RUN_REPRODUCIBLE_COMPARE:-false}"

	# Validate required values
	[[ -z "${java_to_build}" ]] && {
		log_error "CONFIG_JAVA_TO_BUILD not set"
		exit 1
	}
	[[ -z "${target_os}" ]] && {
		log_error "CONFIG_TARGET_OS not set"
		exit 1
	}
	[[ -z "${architecture}" ]] && {
		log_error "CONFIG_ARCHITECTURE not set"
		exit 1
	}
	[[ -z "${variant}" ]] && {
		log_error "CONFIG_VARIANT not set"
		exit 1
	}

	# If WEEKLY build, append --with-version-opt=ea to configure args
	if [[ "${release_type}" == "WEEKLY" ]]; then
		if [[ -n "${configure_args}" ]]; then
			configure_args="${configure_args} --with-version-opt=ea"
		else
			configure_args="--with-version-opt=ea"
		fi
		log_info "WEEKLY build - added --with-version-opt=ea to configure args"
	fi

	log_info "Build Configuration:"
	log_info "  Java Version: ${java_to_build}"
	log_info "  Target OS: ${target_os}"
	log_info "  Architecture: ${architecture}"
	log_info "  Variant: ${variant}"
	log_info "  SCM Ref: ${scm_ref}"
	log_info "  Build Repo URL: ${build_repo_url} (default)"
	log_info "  Build Ref: ${build_ref} (${build_ref_source})"
	log_info "  Build Args: ${build_args}"
	log_info "  Configure Args: ${configure_args}"
	log_info "  Clean Workspace: ${clean_workspace}"
	log_info "  Release Type: ${release_type}"
	log_info "  Compare Build: ${compare_build}"
	log_info "  Create SBOM: ${create_sbom}"

	# Setup build environment
	setup_build_environment

	# Append --create-sbom to build_args if CREATE_SBOM is enabled
	if [[ "${create_sbom}" == "true" ]]; then
		build_args="${build_args:+${build_args} }--create-sbom"
		log_info "CREATE_SBOM enabled - added --create-sbom to build args"
	fi

	# Setup reproducible build from SBOM if compare-build is enabled.
	# This must happen BEFORE cloning temurin-build so it clones into the padded workspace.
	# Returns --build-reproducible-date for WEEKLY EA builds which is appended to build_args.
	if [[ "${compare_build}" == "true" ]]; then
		local extra_build_args
		extra_build_args=$(setup_reproducible_build_from_sbom "${scm_ref}")
		build_args="${build_args:+${build_args} }${extra_build_args}"
	fi

	# Clone temurin-build repository (after padding so it goes into the right place)
	setup_temurin_build "${build_repo_url}" "${build_ref}"

	# Prepare workspace
	prepare_workspace "${clean_workspace}"

	# Prepare target directory
	# shellcheck disable=SC2153
	prepare_output_dir "${TARGET_DIR}"

	# Execute build using build-farm/make-adopt-build-farm.sh
	execute_build "${java_to_build}" "${target_os}" "${architecture}" "${variant}" "${build_args}" "${scm_ref}" "${configure_args}" "${make_args}"

	# Extract and save metadata
	extract_build_metadata

	# Copy outputs to standard location
	organize_build_outputs

	# Create checksums
	create_checksums "${TARGET_DIR}"

	# Create stage metadata
	create_stage_metadata "${STAGE_NAME}" "success"

	# List final artifacts
	list_artifacts "${TARGET_DIR}"

	log_section "Build Stage - Complete"
}

# Resolve the Python interpreter (python3 preferred, falls back to python)
resolve_python() {
	if command -v python3 &>/dev/null; then
		echo "python3"
	elif command -v python &>/dev/null; then
		echo "python"
	else
		log_error "No Python interpreter found (tried python3, python)"
		exit 1
	fi
}

# Setup build environment
setup_build_environment() {
	log_info "Setting up build environment"

	# Detect OS and architecture
	local detected_os
	detected_os=$(uname -s | tr '[:upper:]' '[:lower:]')
	local detected_arch
	detected_arch=$(uname -m)

	log_info "Detected OS: ${detected_os}"
	log_info "Detected Architecture: ${detected_arch}"

	# Check for required tools
	local required_tools=("git" "make" "bash")
	for tool in "${required_tools[@]}"; do
		if ! command -v "${tool}" &>/dev/null; then
			log_error "Required tool not found: ${tool}"
			exit 1
		fi
		log_debug "Found tool: ${tool}"
	done

	log_info "Build environment ready"
}

# Clone temurin-build repository (always fresh clone)
setup_temurin_build() {
	local build_repo_url=$1
	local build_ref=$2
	local build_repo_dir="${WORKSPACE}/temurin-build"

	log_section "Setting up temurin-build repository"
	log_info "Repository URL: ${build_repo_url}"
	log_info "Branch/Ref: ${build_ref}"

	# Remove existing directory if present (ensures clean state)
	if [[ -d "${build_repo_dir}" ]]; then
		log_info "Removing existing repository directory..."
		rm -rf "${build_repo_dir}"
	fi

	# Clone repository
	log_info "Cloning repository..."
	if git clone --branch "${build_ref}" "${build_repo_url}" "${build_repo_dir}"; then
		log_info "Repository cloned successfully"
	else
		log_error "Failed to clone repository from ${build_repo_url}"
		log_error "Branch/ref: ${build_ref}"
		exit 1
	fi

	# Verify build script exists
	local build_script="${build_repo_dir}/build-farm/make-adopt-build-farm.sh"
	if [[ ! -f "${build_script}" ]]; then
		log_error "Build script not found: ${build_script}"
		log_error "Expected: build-farm/make-adopt-build-farm.sh"
		exit 1
	fi

	log_info "temurin-build repository ready at: ${build_repo_dir}"
	log_info "Build script: ${build_script}"
}

# Resolve canonical path (handles . and .. components)
resolve_path() {
	local path="$1"

	# Make absolute
	[[ "$path" != /* ]] && path="$PWD/$path"

	# Process path components
	local -a parts resolved=()
	IFS='/' read -ra parts <<<"$path"

	for part in "${parts[@]}"; do
		case "$part" in
		"" | ".") continue ;;
		"..")
			# Remove last element (bash 3.2+ compatible)
			if [[ ${#resolved[@]} -gt 0 ]]; then
				unset "resolved[${#resolved[@]}-1]"
			fi
			;;
		*) resolved+=("$part") ;;
		esac
	done

	# Reconstruct path
	printf "/%s" "${resolved[@]}" | sed 's|/$||; s|^$|/|'
}

# Pad build directory to match target length for reproducible builds
pad_build_dir_to_same_length() {
	local target_build_dir_to_match
	target_build_dir_to_match=$(resolve_path "$1")
	local ws_build_dir
	ws_build_dir=$(resolve_path "$2")
	local ws_build_folder="$3"

	local ws_dir="${ws_build_dir}/${ws_build_folder}"

	local padding_length=$((${#target_build_dir_to_match} - ${#ws_dir}))
	if [[ "$padding_length" -eq 0 ]]; then
		log_info "Build directories are already same length"
		echo ""
	elif [[ "$padding_length" -lt 0 ]] || [[ "$padding_length" -eq 1 ]]; then
		log_warn "Unable to pad ${ws_dir} to necessary length of ${target_build_dir_to_match}, padding required: ${padding_length}"
		echo ""
	else
		padding_length=$((padding_length - 1))
		local padding
		padding=$(printf "P%.0s" $(seq 1 $padding_length))
		local padded="${ws_build_dir}/${padding}"
		log_info "Padded ${ws_build_dir} with sub-folder to ${padded}"
		echo "${padded}"
	fi
}

# Setup reproducible build from SBOM: path padding + (WEEKLY) build timestamp.
#
# Arguments:
#   $1  scm_ref  - The SCM ref for this build (e.g. jdk-21.0.3+9_adopt)
#
# Stdout:
#   Prints "--build-reproducible-date <date>" for WEEKLY builds (empty otherwise).
#   Caller should capture and append to build_args.
setup_reproducible_build_from_sbom() {
	local scm_ref=$1

	log_section "Setting up reproducible build from SBOM"

	# Use CONFIG_* env vars already set by the pipeline (avoids jq dependency)
	local target_os="${CONFIG_TARGET_OS:-}"
	local architecture="${CONFIG_ARCHITECTURE:-}"
	local release_type="${RELEASE_TYPE:-NIGHTLY}"

	# Remove "_adopt" suffix from SCM_REF if present
	local scm_ref_for_api="${scm_ref/_adopt/}"
	log_info "SCM_REF for API: ${scm_ref_for_api}"

	# Add "-ea-beta" suffix for EA/WEEKLY builds
	if [[ "${release_type}" == "WEEKLY" ]]; then
		scm_ref_for_api="${scm_ref_for_api}-ea-beta"
		log_info "EA build detected, using: ${scm_ref_for_api}"
	fi

	# Map OS to Adoptium API format
	case "${target_os}" in
	mac) local api_os="mac" ;;
	linux) local api_os="linux" ;;
	windows) local api_os="windows" ;;
	aix) local api_os="aix" ;;
	*)
		log_error "Unsupported OS: ${target_os}"
		return 1
		;;
	esac

	# Map architecture to Adoptium API format
	case "${architecture}" in
	aarch64) local api_arch="aarch64" ;;
	x64) local api_arch="x64" ;;
	x32) local api_arch="x32" ;;
	ppc64) local api_arch="ppc64" ;;
	ppc64le) local api_arch="ppc64le" ;;
	s390x) local api_arch="s390x" ;;
	*)
		log_error "Unsupported architecture: ${architecture}"
		return 1
		;;
	esac

	# Construct SBOM API URL
	local api_sbom_url="https://api.adoptium.net/v3/binary/version/${scm_ref_for_api}/${api_os}/${api_arch}/sbom/hotspot/normal/eclipse?project=jdk"

	log_info "Fetching SBOM from: ${api_sbom_url}"

	# Download SBOM to temporary file
	local sbom_file="${WORKSPACE}/upstream-sbom.json"
	if curl -L -f -s -o "${sbom_file}" "${api_sbom_url}"; then
		log_info "SBOM downloaded successfully"

		# --- Path padding ---
		# Extract BUILD_WORKSPACE_DIRECTORY from SBOM using Python (no jq dependency)
		local build_workspace_directory
		build_workspace_directory=$($(resolve_python) "${PIPELINE_LIB}/sbom-field-extractor.py" --sbom "${sbom_file}" --field "Build Workspace Directory")

		if [[ -n "${build_workspace_directory}" && "${build_workspace_directory}" != "null" ]]; then
			log_info "Found BUILD_WORKSPACE_DIRECTORY in SBOM: ${build_workspace_directory}"

			# Calculate padded workspace directory
			# The build will create: ${WORKSPACE}/temurin-build/workspace/build/src
			local build_folder="temurin-build/workspace/build/src"
			local padded_workspace
			padded_workspace=$(pad_build_dir_to_same_length "${build_workspace_directory}" "${WORKSPACE}" "${build_folder}")

			if [[ -n "${padded_workspace}" ]]; then
				log_info "Applying workspace padding for reproducible build"
				log_info "Original WORKSPACE: ${WORKSPACE}"
				log_info "Padded WORKSPACE: ${padded_workspace}"

				# Create padded directory
				mkdir -p "${padded_workspace}"

				# Update WORKSPACE environment variable for the build
				export WORKSPACE="${padded_workspace}"
				log_info "WORKSPACE updated to: ${WORKSPACE}"
			else
				log_info "No padding needed - workspace paths already match"
			fi
		else
			log_warn "BUILD_WORKSPACE_DIRECTORY not found in SBOM - skipping path padding"
		fi

		# --- WEEKLY EA: --build-reproducible-date ---
		# For WEEKLY builds the build system needs the original build timestamp so the
		# reproduction is byte-for-byte identical.  The SBOM "Build Timestamp" field
		# contains a UTC datetime in "YYYY-MM-DD HH:MM:SS" format; convert it to the
		# ISO 8601 UTC form required by --build-reproducible-date ("YYYY-MM-DDTHH:MM:SSZ").
		if [[ "${release_type}" == "WEEKLY" ]]; then
			local build_timestamp
			build_timestamp=$($(resolve_python) "${PIPELINE_LIB}/sbom-field-extractor.py" --sbom "${sbom_file}" --field "Build Timestamp")

			if [[ -n "${build_timestamp}" && "${build_timestamp}" != "null" ]]; then
				# Convert "YYYY-MM-DD HH:MM:SS" → "YYYY-MM-DDTHH:MM:SSZ"
				local reproducible_date="${build_timestamp/ /T}Z"
				log_info "Found Build Timestamp in SBOM: ${build_timestamp}"
				log_info "Using --build-reproducible-date: ${reproducible_date}"
				echo "--build-reproducible-date ${reproducible_date}"
			else
				log_warn "Build Timestamp not found in SBOM - --build-reproducible-date will not be set"
			fi
		fi

		# Clean up SBOM file
		rm -f "${sbom_file}"
	else
		log_warn "Failed to download SBOM from ${api_sbom_url}"
		log_warn "Path padding will be skipped - this may affect reproducibility"
	fi

	log_info "Reproducible build from SBOM setup complete"
}

# Prepare workspace for build
prepare_workspace() {
	local clean=$1

	if [[ "${clean}" == "true" ]]; then
		log_info "Cleaning workspace build directories"

		# Clean build output directories but preserve temurin-build repo
		rm -rf "${WORKSPACE}/workspace/build" || true
		rm -rf "${WORKSPACE}/workspace/target" || true

		log_info "Workspace cleaned"
	else
		log_info "Skipping workspace clean"
	fi

	# Always clean any previous openjdk build directory
	local openjdk_build_dir="${WORKSPACE}/workspace/build/src/build"
	if [[ -d "${openjdk_build_dir}" ]]; then
		log_info "Removing previous openjdk build directory: ${openjdk_build_dir}"
		rm -rf "${openjdk_build_dir}"
	fi
}

# Execute the actual JDK build using build-farm/make-adopt-build-farm.sh
execute_build() {
	local java_version=$1
	local os=$2
	local arch=$3
	local variant=$4
	local build_args=$5
	local scm_ref=$6
	local configure_args=$7
	local make_args=${8:-}

	log_section "Executing JDK Build"

	local build_repo_dir="${WORKSPACE}/temurin-build"
	local build_script="build-farm/make-adopt-build-farm.sh"

	# Append --make-args to BUILD_ARGS if EXTRA_MAKE_OPTIONS is set.
	# make-adopt-build-farm.sh does not have a separate MAKE_ARGS env var;
	# extra make arguments are passed via --make-args inside BUILD_ARGS.
	if [[ -n "${make_args}" ]]; then
		build_args="${build_args:+${build_args} }--make-args \"${make_args}\""
	fi

	log_info "Build parameters:"
	log_info "  Script: ${build_script}"
	log_info "  Java Version: ${java_version}"
	log_info "  OS: ${os}"
	log_info "  Architecture: ${arch}"
	log_info "  Variant: ${variant}"
	log_info "  Build Args: ${build_args}"
	log_info "  Configure Args: ${configure_args}"
	log_info "  SCM Ref: ${scm_ref}"

	# Set build environment variables for make-adopt-build-farm.sh.
	# BUILD_ARGS and CONFIGURE_ARGS are the names that temurin-build expects;
	# they are populated from the pipeline's EXTRA_BUILD_ARGS / EXTRA_CONFIGURE_ARGS values.
	export JAVA_TO_BUILD="${java_version}"
	export TARGET_OS="${os}"
	export ARCHITECTURE="${arch}"
	export VARIANT="${variant}"
	export BUILD_ARGS="${build_args}"
	export WORKSPACE="${WORKSPACE}"
	export SCM_REF="${scm_ref}"
	export CONFIGURE_ARGS="${configure_args}"
	local release_value
	release_value="$([[ "${RELEASE_TYPE:-NIGHTLY}" == "RELEASE" ]] && echo "true" || echo "false")"
	export RELEASE="${release_value}"

	# Determine output filename if not already set
	if [[ -z "${FILENAME:-}" ]]; then
		log_info "FILENAME not set, determining from build configuration"
		determine_filename || {
			log_error "Failed to determine filename"
			return 1
		}
	else
		log_info "Using provided FILENAME: ${FILENAME}"
	fi

	export OVERRIDE_FILE_NAME_VERSION="${OVERRIDE_FILE_NAME_VERSION:-}"

	log_info "Environment variables set:"
	log_info "  JAVA_TO_BUILD=${JAVA_TO_BUILD}"
	log_info "  TARGET_OS=${TARGET_OS}"
	log_info "  ARCHITECTURE=${ARCHITECTURE}"
	log_info "  VARIANT=${VARIANT}"
	log_info "  BUILD_ARGS=${BUILD_ARGS}"
	log_info "  CONFIGURE_ARGS=${CONFIGURE_ARGS}"
	log_info "  EXTRA_MAKE_OPTIONS=${make_args}"
	log_info "  WORKSPACE=${WORKSPACE}"
	log_info "  SCM_REF=${SCM_REF}"
	log_info "  RELEASE=${RELEASE}"
	log_info "  JAVA_HOME=${JAVA_HOME:-not set}"

	log_info "Starting build at $(date)"
	log_info "Build command: bash ${build_script}"

	# Change to temurin-build directory
	cd "${build_repo_dir}"

	# Execute build script directly (timeout removed to allow stdin)
	# Note: Jenkins uses a 12-hour timeout, but we run without timeout to allow interactive input
	log_info "Starting build (no timeout - will run until completion)"

	if bash "${build_script}"; then
		log_info "Build completed successfully at $(date)"
	else
		local exit_code=$?
		log_error "Build failed with exit code: ${exit_code}"
		cd "${WORKSPACE}"
		exit 1
	fi

	cd "${WORKSPACE}"

	log_info "Build execution complete"
}

# Extract build metadata
extract_build_metadata() {
	log_info "Extracting build metadata"

	local version="unknown"

	# Get VERSION_STRING from build spec.gmk (most reliable source)
	# Use find rather than a glob in [[ -f ]] — bash does not expand globs in [[ ]]
	local spec_file
	spec_file=$(find "${WORKSPACE}/temurin-build/workspace/build/src/build" \
		-name "spec.gmk" 2>/dev/null | head -1)
	if [[ -n "${spec_file}" && -f "${spec_file}" ]]; then
		local v
		v=$(grep "^VERSION_STRING[ ]*:=" "${spec_file}" |
			sed "s/^VERSION_STRING[ ]*:=[ ]*//" | tr -d '[:space:]')
		if [[ -n "${v}" ]]; then
			version="jdk-${v}"
			log_info "Build version: ${version}"
		else
			log_warn "VERSION_STRING not found in spec.gmk"
		fi
	else
		log_warn "spec.gmk not found under ${WORKSPACE}/temurin-build/workspace/build/src/build"
	fi

	# Create build-metadata.json via a standalone Python script.
	# Values are passed as CLI arguments — no shell interpolation inside Python.
	$(resolve_python) "${PIPELINE_LIB}/build-metadata-writer.py" \
		--output "${WORKSPACE}/build-metadata.json" \
		--version "${version}" \
		--build-number "${BUILD_NUMBER}" \
		--stage "${STAGE_NAME}" \
		--workspace "${WORKSPACE}" \
		--build-uid "${BUILD_UID:-}" \
		--group-uid "${GROUP_UID:-}"

	log_info "Build metadata saved to build-metadata.json"
}

# Organize build outputs into standard structure
organize_build_outputs() {
	log_info "Organizing build outputs"

	local build_repo_dir="${WORKSPACE}/temurin-build"
	local target_dir="${build_repo_dir}/workspace/target"

	if [[ ! -d "${target_dir}" ]]; then
		log_error "Target directory not found: ${target_dir}"
		exit 1
	fi

	log_info "Found build outputs in: ${target_dir}"

	# Find and copy JDK artifacts
	log_info "Searching for JDK artifacts..."
	local artifacts_found=0

	# Look for tar.gz, zip, and json files (including SBOM)
	while IFS= read -r -d '' artifact; do
		log_info "Found artifact: $(basename "${artifact}")"
		cp "${artifact}" "${TARGET_DIR}/"
		artifacts_found=$((artifacts_found + 1))
	done < <(find "${target_dir}" -type f \( -name "*.tar.gz" -o -name "*.zip" -o -name "*.json" \) -print0)

	if [[ ${artifacts_found} -eq 0 ]]; then
		log_error "No tar.gz or zip artifacts found in ${target_dir}"
		log_info "Directory contents:"
		ls -la "${target_dir}" || true
		exit 1
	else
		log_info "Copied ${artifacts_found} artifact(s)"
	fi

	# Copy metadata files
	if [[ -f "${WORKSPACE}/build-metadata.json" ]]; then
		cp "${WORKSPACE}/build-metadata.json" "${TARGET_DIR}/"
	fi

	# Copy any buildinfo or release files
	find "${target_dir}" -type f \( -name "buildinfo.json" -o -name "release" \) -exec cp {} "${TARGET_DIR}/" \; 2>/dev/null || true

	log_info "Build outputs organized in: ${TARGET_DIR}"
}

# Error handler
error_handler() {
	local line_number=$1
	log_error "Build stage failed at line ${line_number}"

	# Try to capture build logs
	local build_log="${WORKSPACE}/temurin-build/workspace/logs/build.log"
	if [[ -f "${build_log}" ]]; then
		log_error "Last 50 lines of build log:"
		tail -n 50 "${build_log}" || true
	fi

	create_stage_metadata "${STAGE_NAME}" "failed"
	exit 1
}

# Set error trap
trap 'error_handler ${LINENO}' ERR

# Execute main function
main "$@"

# Made with Bob
