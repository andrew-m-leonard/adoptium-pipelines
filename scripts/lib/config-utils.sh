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
# Configuration utilities for CI-agnostic pipeline stages

# Source logging utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/logging-utils.sh"

# Require environment variable to be set
require_env() {
	local var_name=$1
	if [[ -z "${!var_name:-}" ]]; then
		log_error "Required environment variable not set: ${var_name}"
		exit 1
	fi
	log_debug "Environment variable ${var_name} = ${!var_name}"
}

# Require file to exist
require_file() {
	local file_path=$1
	if [[ ! -f "${file_path}" ]]; then
		log_error "Required file not found: ${file_path}"
		exit 1
	fi
	log_debug "Found required file: ${file_path}"
}

# Require directory to exist
require_dir() {
	local dir_path=$1
	if [[ ! -d "${dir_path}" ]]; then
		log_error "Required directory not found: ${dir_path}"
		exit 1
	fi
	log_debug "Found required directory: ${dir_path}"
}

# Resolve the path to json-utils.py relative to this script.
_JSON_UTILS="${SCRIPT_DIR}/json-utils.py"

# Load JSON configuration file
load_config() {
	local config_file=$1
	require_file "${config_file}"
	cat "${config_file}"
}

# Extract a value from JSON using a simple dot-notation path (e.g. ".foo.bar").
# Uses scripts/lib/json-utils.py — no jq required.
# Accepts either a file path or a raw JSON string as the first argument.
_json_get() {
	local config=$1
	local json_path=$2

	if [[ -f "${config}" ]]; then
		python3 "${_JSON_UTILS}" get "${json_path}" "${config}"
	else
		echo "${config}" | python3 "${_JSON_UTILS}" get "${json_path}" -
	fi
}

# Get value from JSON configuration
get_config_value() {
	local config=$1
	local json_path=$2
	local default_value=${3:-}
	local value

	if ! value=$(_json_get "${config}" "${json_path}" 2>&1); then
		if [[ "${value}" == "null" ]]; then
			: # handled below
		else
			log_error "Error reading ${json_path} from config: ${value}"
			return 1
		fi
	fi

	if [[ "${value}" == "null" ]] || [[ -z "${value}" ]]; then
		if [[ -n "${default_value}" ]]; then
			echo "${default_value}"
		else
			log_error "Configuration value not found: ${json_path}"
			return 1
		fi
	else
		echo "${value}"
	fi
}

# Get boolean value from JSON configuration
get_config_bool() {
	local config=$1
	local json_path=$2
	local default_value=${3:-false}
	local value

	if ! value=$(_json_get "${config}" "${json_path}" 2>&1); then
		if [[ "${value}" != "null" ]]; then
			log_error "Error reading ${json_path} from config: ${value}"
			return 1
		fi
	fi

	if [[ "${value}" == "true" ]]; then
		echo "true"
	elif [[ "${value}" == "false" ]]; then
		echo "false"
	else
		echo "${default_value}"
	fi
}

# Validate standard environment
validate_standard_environment() {
	log_info "Validating environment..."

	require_env "WORKSPACE"
	require_env "CONFIG_FILE"
	# shellcheck disable=SC2153
	require_file "${CONFIG_FILE}"

	# Set default directory if not set.
	# WORKSPACE points to stage_workspace/ (local) or the Jenkins agent workspace.
	# Outputs land in stage_workspace/target/ so they can be archived after the stage.
	export TARGET_DIR="${TARGET_DIR:-${WORKSPACE}/target}"

	log_info "Environment validated successfully"
	log_debug "WORKSPACE=${WORKSPACE}"
	log_debug "CONFIG_FILE=${CONFIG_FILE}"
	log_debug "TARGET_DIR=${TARGET_DIR}"
}

# Made with Bob
