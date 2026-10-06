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
# load-stage-constants.sh — source this file to export pipeline + vendor constants.
#
# Reads scripts/stages/stage-constants.properties (core defaults) and, when
# config-repo/vendor-scripts/vendor-constants.properties exists, overlays those
# values on top.  Vendor values win over defaults.
#
# Usage in a stage script:
#   PIPELINE_LIB="${PIPELINE_ROOT:-${WORKSPACE}}/scripts/lib"
#   source "${PIPELINE_LIB}/load-stage-constants.sh"
#   # BUILD_OUTPUT_DIR (and any vendor additions) now available as env vars.
#
# The file is intentionally idempotent: sourcing it multiple times is safe.

_load_properties_file() {
	local props_file="$1"
	[[ -f "${props_file}" ]] || return 0
	while IFS= read -r line || [[ -n "${line}" ]]; do
		# Skip blank lines and comments
		[[ -z "${line}" || "${line}" =~ ^[[:space:]]*# ]] && continue
		# Require KEY=VALUE form
		[[ "${line}" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || continue
		local key="${line%%=*}"
		local value="${line#*=}"
		# Only set if not already set (preserves runner-injected vendor values)
		# ${var+x} expands to "x" if var is set (even to empty), else empty.
		# This works in Bash 3.2+ (macOS default) unlike [[ -v var ]].
		[[ -n "${!key+x}" ]] || export "${key}=${value}"
	done <"${props_file}"
}

# Resolve PIPELINE_ROOT (set by CI) or fall back to WORKSPACE
_pipeline_root="${PIPELINE_ROOT:-${WORKSPACE}}"

# 1. Core defaults
_load_properties_file "${_pipeline_root}/scripts/stages/stage-constants.properties"

# 2. Vendor overrides/additions (optional — absent when no config repo is used)
# CONFIG_REPO_ROOT is set by both local runner and Jenkins to the checked-out
# config repository path.
_vendor_root="${CONFIG_REPO_ROOT}"
_load_properties_file "${_vendor_root}/vendor-scripts/vendor-constants.properties"

unset _load_properties_file _pipeline_root _vendor_root
