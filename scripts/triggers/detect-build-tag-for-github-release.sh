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
# detect-build-tag-for-github-release.sh
#
# CI-agnostic trigger script: detects the latest upstream build tag on
# monitorRepo matching buildTagPattern, checks whether it has already been
# published as a GitHub (or GitHub Enterprise) release asset on targetRepo,
# and writes the result to $TARGET_DIR/trigger-result.json.
#
# Required env:
#   WORKSPACE                    — working directory
#   TARGET_DIR                   — directory to write trigger-result.json
#   TRIGGER_VERSION_CONFIG_FILE  — path to trigger-version-config.json
#                                  (written by TriggerScriptRunner)
#
# Optional env:
#   GITHUB_TOKEN   — PAT for authenticated API/git requests
#   PIPELINE_ROOT  — root of ci-adoptium-pipelines checkout;
#                    falls back to WORKSPACE
#
# trigger-version-config.json fields:
#   monitorRepo         (required) — git repo to watch for build tags
#   targetRepo          (required) — GitHub releases repo to check for assets
#   version             (required) — JDK version string, e.g. "jdk21"
#   buildTagPattern     (optional) — ERE regex to match build tags;
#                                    default derived from version by trigger-utils.py
#   publishNameMap      (required) — sed expression mapping detected tag → publish name
#                                    e.g. "s/_adopt$/-ea/"
#   targetReleaseTagMap (required) — sed expression mapping publish name → release tag
#                                    checked on targetRepo, e.g. "s/$/-beta/"
#
# Outputs $TARGET_DIR/trigger-result.json:
#   {
#     "shouldTrigger": true|false,
#     "scmRef":        "<latest build tag, or empty>",
#     "publishName":   "<publish name, or empty>",
#     "releaseType":   "Weekly"
#   }

set -euo pipefail

PIPELINE_LIB="${PIPELINE_ROOT:-${WORKSPACE}}/scripts/lib"
# shellcheck source=scripts/lib/logging-utils.sh
source "${PIPELINE_LIB}/logging-utils.sh"
# shellcheck source=scripts/lib/config-utils.sh
source "${PIPELINE_LIB}/config-utils.sh"

TRIGGER_UTILS="${PIPELINE_LIB}/python-runner.sh ${PIPELINE_LIB}/trigger-utils.py"

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
main() {
    log_section "detect-build-tag-for-github-release — Start"

    require_env "WORKSPACE"
    require_env "TARGET_DIR"
    require_env "TRIGGER_VERSION_CONFIG_FILE"
    require_file "${TRIGGER_VERSION_CONFIG_FILE}"

    mkdir -p "${TARGET_DIR}"

    local cfg="${TRIGGER_VERSION_CONFIG_FILE}"

    local monitor_repo target_repo version publish_name_map target_release_tag_map
    monitor_repo=$(get_config_value          "${cfg}" ".monitorRepo")
    target_repo=$(get_config_value           "${cfg}" ".targetRepo")
    version=$(get_config_value               "${cfg}" ".version")
    publish_name_map=$(get_config_value      "${cfg}" ".publishNameMap")
    target_release_tag_map=$(get_config_value "${cfg}" ".targetReleaseTagMap")

    # buildTagPattern — use config value or derive default via trigger-utils.py
    local build_tag_pattern
    if build_tag_pattern=$(get_config_value "${cfg}" ".buildTagPattern" 2>/dev/null) \
            && [ -n "${build_tag_pattern}" ]; then
        log_info "Using configured buildTagPattern: ${build_tag_pattern}"
    else
        build_tag_pattern=$(${TRIGGER_UTILS} default-build-tag-pattern "${version}")
        log_info "Using default buildTagPattern for ${version}: ${build_tag_pattern}"
    fi

    log_info "monitorRepo         : ${monitor_repo}"
    log_info "targetRepo          : ${target_repo}"
    log_info "version             : ${version}"
    log_info "buildTagPattern     : ${build_tag_pattern}"
    log_info "publishNameMap      : ${publish_name_map}"
    log_info "targetReleaseTagMap : ${target_release_tag_map}"

    # Step 1 — find the latest build tag on monitorRepo matching buildTagPattern
    log_info "Querying ${monitor_repo} for latest build tag..."
    local latest_tag
    latest_tag=$(git ls-remote --sort=-v:refname --tags "${monitor_repo}" \
        | grep -v '\^{}' \
        | grep -v '+0$' \
        | grep -v '\-ga$' \
        | grep -E "${build_tag_pattern}" \
        | tr -s '\t ' ' ' | cut -d' ' -f2 | sed 's|refs/tags/||' \
        | sort -V -r | head -1 | tr -d '\n') || true

    if [ -z "${latest_tag}" ]; then
        log_warn "No build tag found matching '${build_tag_pattern}' on ${monitor_repo}"
        ${TRIGGER_UTILS} write-trigger-result "${TARGET_DIR}" \
            "shouldTrigger=false" "scmRef=" "publishName=" "releaseType=Weekly"
        log_section "detect-build-tag-for-github-release — Complete (no tag found)"
        return 0
    fi
    log_info "Latest build tag: ${latest_tag}"

    # Step 2 — map detected tag to publishName and targetRepo release tag
    local publish_name target_release_tag
    publish_name=$(echo "${latest_tag}"   | sed "${publish_name_map}")
    target_release_tag=$(echo "${publish_name}" | sed "${target_release_tag_map}")
    log_info "publishName        : ${publish_name}"
    log_info "targetReleaseTag   : ${target_release_tag}"

    # Step 3 — check whether this release already exists on targetRepo
    # check-github-release-asset exits 0=found, 1=not found, 2=error (fail open)
    log_info "Checking ${target_repo} for existing release ${target_release_tag}..."
    if ${TRIGGER_UTILS} check-github-release-asset "${target_repo}" "${target_release_tag}"; then
        log_info "Release ${target_release_tag} already published — nothing to do"
        ${TRIGGER_UTILS} write-trigger-result "${TARGET_DIR}" \
            "shouldTrigger=false" \
            "scmRef=${latest_tag}" \
            "publishName=${publish_name}" \
            "releaseType=Weekly"
    else
        log_info "Release ${target_release_tag} not yet published — trigger required"
        ${TRIGGER_UTILS} write-trigger-result "${TARGET_DIR}" \
            "shouldTrigger=true" \
            "scmRef=${latest_tag}" \
            "publishName=${publish_name}" \
            "releaseType=Weekly"
    fi

    log_info "trigger-result.json written to ${TARGET_DIR}"
    log_section "detect-build-tag-for-github-release — Complete"
}

main "$@"
