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
# detect-ga-tag.sh
#
# CI-agnostic trigger script: detects the latest upstream GA tag on monitorRepo
# matching gaTagPattern, resolves the corresponding build tag at the same commit
# SHA matching buildTagPattern, and writes the result to
# $TARGET_DIR/trigger-result.json.
#
# Deduplication (have we already triggered for this scmRef?) is NOT handled
# here — that is the responsibility of the CI orchestration layer
# (Jenkinsfile.trigger), which queries Jenkins build history.
#
# Required env:
#   WORKSPACE                    — working directory
#   TARGET_DIR                   — directory to write trigger-result.json
#   TRIGGER_VERSION_CONFIG_FILE  — path to trigger-version-config.json
#                                  (written by TriggerScriptRunner)
#
# Optional env:
#   GITHUB_TOKEN   — PAT for authenticated git requests (rate-limit avoidance)
#   PIPELINE_ROOT  — root of ci-adoptium-pipelines checkout;
#                    falls back to WORKSPACE
#
# trigger-version-config.json fields:
#   monitorRepo      (required) — git repo to watch for GA tags
#   version          (required) — JDK version string, e.g. "jdk21"
#   gaTagPattern     (optional) — ERE regex to match GA tags;      default: ".*-ga$"
#   buildTagPattern  (optional) — ERE regex to match build tags at the GA commit SHA;
#                                  default derived from version by trigger-utils.py
#
# Outputs $TARGET_DIR/trigger-result.json:
#   {
#     "detected": true|false,
#     "scmRef":   "<build tag at GA commit SHA, or empty>",
#     "gaTag":    "<latest GA tag, or empty>"
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
    log_section "detect-ga-tag — Start"

    require_env "WORKSPACE"
    require_env "TARGET_DIR"
    require_env "TRIGGER_VERSION_CONFIG_FILE"
    require_file "${TRIGGER_VERSION_CONFIG_FILE}"

    mkdir -p "${TARGET_DIR}"

    local cfg="${TRIGGER_VERSION_CONFIG_FILE}"

    local monitor_repo version
    monitor_repo=$(get_config_value "${cfg}" ".monitorRepo")
    version=$(get_config_value      "${cfg}" ".version")

    # gaTagPattern — use config value or default to any -ga tag
    local ga_tag_pattern
    if ga_tag_pattern=$(get_config_value "${cfg}" ".gaTagPattern" 2>/dev/null) \
            && [ -n "${ga_tag_pattern}" ]; then
        log_info "Using configured gaTagPattern: ${ga_tag_pattern}"
    else
        ga_tag_pattern=".*-ga$"
        log_info "Using default gaTagPattern: ${ga_tag_pattern}"
    fi

    # buildTagPattern — use config value or derive default via trigger-utils.py
    local build_tag_pattern
    if build_tag_pattern=$(get_config_value "${cfg}" ".buildTagPattern" 2>/dev/null) \
            && [ -n "${build_tag_pattern}" ]; then
        log_info "Using configured buildTagPattern: ${build_tag_pattern}"
    else
        build_tag_pattern=$(${TRIGGER_UTILS} default-build-tag-pattern "${version}")
        log_info "Using default buildTagPattern for ${version}: ${build_tag_pattern}"
    fi

    log_info "monitorRepo      : ${monitor_repo}"
    log_info "version          : ${version}"
    log_info "gaTagPattern     : ${ga_tag_pattern}"
    log_info "buildTagPattern  : ${build_tag_pattern}"

    # Step 1 — find the latest GA tag on monitorRepo matching gaTagPattern
    log_info "Querying ${monitor_repo} for latest GA tag..."
    local latest_ga_tag
    latest_ga_tag=$(git ls-remote --sort=-v:refname --tags "${monitor_repo}" \
        | grep -v '\^{}' \
        | grep -E "${ga_tag_pattern}" \
        | tr -s '\t ' ' ' | cut -d' ' -f2 | sed 's|refs/tags/||' \
        | sort -V -r | head -1 | tr -d '\n') || true

    if [ -z "${latest_ga_tag}" ]; then
        log_warn "No GA tag found matching '${ga_tag_pattern}' on ${monitor_repo}"
        ${TRIGGER_UTILS} write-trigger-result "${TARGET_DIR}" \
            "detected=false" "scmRef=" "gaTag="
        log_section "detect-ga-tag — Complete (no GA tag found)"
        return 0
    fi
    log_info "Latest GA tag: ${latest_ga_tag}"

    # Step 2 — resolve the commit SHA that the GA tag points at
    local ga_commit_sha
    ga_commit_sha=$(git ls-remote --tags "${monitor_repo}" "${latest_ga_tag}^{}" \
        | tr -s '\t ' ' ' | cut -d' ' -f1 | tr -d '\n') || true

    if [ -z "${ga_commit_sha}" ]; then
        # Lightweight tag — try without the ^{} dereference
        ga_commit_sha=$(git ls-remote --tags "${monitor_repo}" "${latest_ga_tag}" \
            | tr -s '\t ' ' ' | cut -d' ' -f1 | tr -d '\n') || true
    fi

    if [ -z "${ga_commit_sha}" ]; then
        log_error "Cannot resolve commit SHA for GA tag ${latest_ga_tag}"
        ${TRIGGER_UTILS} write-trigger-result "${TARGET_DIR}" \
            "detected=false" "scmRef=" "gaTag=${latest_ga_tag}"
        return 1
    fi
    log_info "GA tag commit SHA: ${ga_commit_sha}"

    # Step 3 — find build tags at that same commit SHA matching buildTagPattern
    log_info "Looking for build tag at ${ga_commit_sha} matching '${build_tag_pattern}'..."
    local scm_ref
    scm_ref=$(git ls-remote --tags "${monitor_repo}" \
        | grep '\^{}' \
        | grep "${ga_commit_sha}" \
        | tr -s '\t ' ' ' | cut -d' ' -f2 | sed 's|refs/tags/||' | sed 's|\^{}||' \
        | grep -E "${build_tag_pattern}" \
        | sort -V -r | head -1 | tr -d '\n') || true

    if [ -z "${scm_ref}" ]; then
        log_warn "No build tag matching '${build_tag_pattern}' found at GA commit ${ga_commit_sha}"
        log_warn "The _adopt mirror tag may not have been applied yet"
        ${TRIGGER_UTILS} write-trigger-result "${TARGET_DIR}" \
            "detected=false" "scmRef=" "gaTag=${latest_ga_tag}"
        log_section "detect-ga-tag — Complete (no build tag at GA commit yet)"
        return 0
    fi
    log_info "Resolved scmRef: ${scm_ref}"

    ${TRIGGER_UTILS} write-trigger-result "${TARGET_DIR}" \
        "detected=true" \
        "scmRef=${scm_ref}" \
        "gaTag=${latest_ga_tag}"

    log_info "trigger-result.json written to ${TARGET_DIR}"
    log_section "detect-ga-tag — Complete"
}

main "$@"
