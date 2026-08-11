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
# Artifact management utilities for CI-agnostic pipeline stages

# Source logging utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/logging-utils.sh"

# Create stage metadata file
create_stage_metadata() {
    local stage_name=$1
    local status=$2
    local metadata_file="${WORKSPACE}/stage-metadata.json"

    log_info "Creating stage metadata for ${stage_name}"

    cat > "${metadata_file}" <<EOF
{
  "stage": "${stage_name}",
  "status": "${status}",
  "timestamp": $(date +%s),
  "build_number": "${BUILD_NUMBER:-unknown}",
  "workspace": "${WORKSPACE}",
  "hostname": "$(hostname)",
  "user": "$(whoami)"
}
EOF

    log_info "Stage metadata created: ${metadata_file}"
}

# Copy artifacts from source to destination
copy_artifacts() {
    local source=$1
    local dest=$2

    if [[ ! -d "${source}" ]]; then
        log_error "Source directory does not exist: ${source}"
        return 1
    fi

    log_info "Copying artifacts from ${source} to ${dest}"
    mkdir -p "${dest}"

    if cp -r "${source}"/* "${dest}/" 2>/dev/null; then
        log_info "Artifacts copied successfully"
        return 0
    else
        log_warn "No artifacts found in ${source} or copy failed"
        return 1
    fi
}

# Determine the output filename for the build artifact
# Sets the FILENAME environment variable
# Requires: JAVA_TO_BUILD, ARCHITECTURE, TARGET_OS, VARIANT, SCM_REF (optional)
determine_filename() {
    local java_to_build="${JAVA_TO_BUILD}"
    local architecture="${ARCHITECTURE}"
    local os="${TARGET_OS}"
    local variant="${VARIANT}"
    local scm_ref="${SCM_REF:-}"

    # Validate required variables
    if [[ -z "${java_to_build}" || -z "${architecture}" || -z "${os}" || -z "${variant}" ]]; then
        log_error "Missing required variables for determine_filename"
        log_error "JAVA_TO_BUILD=${java_to_build}, ARCHITECTURE=${architecture}, TARGET_OS=${os}, VARIANT=${variant}"
        return 1
    fi

    # Determine file extension based on OS
    local extension="tar.gz"
    if [[ "${os}" == "windows" ]]; then
        extension="zip"
    fi

    # Convert java_to_build to uppercase and trim whitespace
    java_to_build=$(echo "${java_to_build}" | tr '[:lower:]' '[:upper:]' | xargs)

    # Add "U" to javaToBuild filename prefix for non-head versions
    # Skip if already ends with U or equals JDK
    if [[ ! "${java_to_build}" =~ U$ ]] && [[ "${java_to_build}" != "JDK" ]]; then
        java_to_build="${java_to_build}U"
    fi

    # Construct base filename
    local filename="Open${java_to_build}-jdk_${architecture}_${os}_${variant}"
    
    # For compatibility with existing releases, use hotspot for temurin variant
    if [[ "${variant}" == "temurin" ]]; then
        filename="Open${java_to_build}-jdk_${architecture}_${os}_hotspot"
    fi

    # Add version tag or timestamp
    if [[ -n "${scm_ref}" ]]; then
        # For java 11+: remove jdk- prefix and replace + with _
        # Example: jdk-11.0.3+7 -> 11.0.3_7
        local name_tag="${scm_ref}"
        name_tag="${name_tag#jdk-}"  # Remove jdk- prefix
        name_tag="${name_tag//+/_}"  # Replace + with _

        # For java 8: remove jdk prefix and -b before build number
        # Example: jdk8u212-b03 -> 8u212b03
        name_tag="${name_tag#jdk}"   # Remove jdk prefix
        name_tag="${name_tag//-b/b}" # Replace -b with b
        
        # Remove _adopt suffix if present
        # Example: 21.0.5_11_adopt -> 21.0.5_11
        name_tag="${name_tag%_adopt}"

        filename="${filename}_${name_tag}"
    else
        # Use timestamp if no SCM_REF provided
        local timestamp=$(date -u '+%Y-%m-%d-%H-%M')
        filename="${filename}_${timestamp}"
    fi

    # Add extension
    filename="${filename}.${extension}"

    # Export as environment variable
    export FILENAME="${filename}"
    
    log_info "Determined filename: ${filename}"
    return 0
}

# Verify artifact exists
verify_artifact() {
    local artifact_path=$1

    if [[ -f "${artifact_path}" ]]; then
        log_info "Verified artifact exists: ${artifact_path}"
        local size=$(du -h "${artifact_path}" | cut -f1)
        log_info "Artifact size: ${size}"
        return 0
    else
        log_error "Artifact not found: ${artifact_path}"
        return 1
    fi
}

# List artifacts in directory
list_artifacts() {
    local dir=$1

    if [[ ! -d "${dir}" ]]; then
        log_warn "Directory does not exist: ${dir}"
        return 1
    fi

    log_info "Artifacts in ${dir}:"
    find "${dir}" -type f -exec ls -lh {} \; | while read -r line; do
        log_info "  ${line}"
    done
}

# Create checksum file for artifacts
create_checksums() {
    local artifact_dir=$1
    local checksum_file="${artifact_dir}/checksums.txt"

    log_info "Creating checksums for artifacts in ${artifact_dir}"

    pushd "${artifact_dir}" > /dev/null || return 1

    find . -type f ! -name "checksums.txt" -exec sha256sum {} \; > "${checksum_file}"

    popd > /dev/null

    log_info "Checksums created: ${checksum_file}"
    cat "${checksum_file}"
}

# Verify checksums
verify_checksums() {
    local artifact_dir=$1
    local checksum_file="${artifact_dir}/checksums.txt"

    if [[ ! -f "${checksum_file}" ]]; then
        log_error "Checksum file not found: ${checksum_file}"
        return 1
    fi

    log_info "Verifying checksums in ${artifact_dir}"

    pushd "${artifact_dir}" > /dev/null || return 1

    if sha256sum -c "${checksum_file}"; then
        log_info "All checksums verified successfully"
        popd > /dev/null
        return 0
    else
        log_error "Checksum verification failed"
        popd > /dev/null
        return 1
    fi
}

# Prepare output directory
prepare_output_dir() {
    local target_dir=${1:-${TARGET_DIR}}

    log_info "Preparing target directory: ${target_dir}"

    # Create directory if it doesn't exist
    mkdir -p "${target_dir}"

    # Clean if requested
    if [[ "${CLEAN_OUTPUT:-false}" == "true" ]]; then
        log_info "Cleaning target directory"
        rm -rf "${target_dir:?}"/*
    fi

    log_info "Target directory ready: ${target_dir}"
}

# Made with Bob
