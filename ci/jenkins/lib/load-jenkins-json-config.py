#!/usr/bin/env python3
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
"""
Jenkins-specific configuration loader — generateJenkinsConfig().

Reads jenkins_job_config.json from the config repository root and
pipeline-config.json (produced by scripts/lib/load-json-config.py) from the
working directory.  Resolves the stageAgentLabels {os}/{arch} placeholders to
their sw.os.* / hw.arch.* schema label tokens and writes a new, separate
jenkins-config.json containing:

  stageAgentLabels         — raw templates from jenkins_job_config.json
  resolvedStageAgentLabels — fully substituted labels ready for Jenkins node()
  buildNodeLabel           — resolved Build-stage label (convenience top-level key)

pipeline-config.json is read-only; it is never modified by this script.

This script is intentionally separate from scripts/lib/load-json-config.py,
which is CI-agnostic.  Only the Jenkins CI flow calls this script.

Usage:
    python3 ci/jenkins/lib/load-jenkins-json-config.py \\
        --config-repo-path ./config-repo \\
        --pipeline-config  ./pipeline-config.json \\
        --output           ./jenkins-config.json
"""

import json
import sys
import argparse
from pathlib import Path

# ---------------------------------------------------------------------------
# Label-schema mappings (self-contained — no dependency on load-json-config.py)
# ---------------------------------------------------------------------------

# Mapping from temurin-build arch values to the aqa-tests hw.arch suffix.
# The suffix is the part that follows 'hw.arch.' in the label schema.
# Templates in jenkins_job_config.json use 'hw.arch.{arch}' — the {arch}
# placeholder is replaced with just the suffix so the full token is correct.
# Note: x64 and x86-32 both map to 'x86' — the aqa-tests schema uses
# hw.arch.x86 for the whole x86 family; there is no hw.arch.x86-64.
_ARCH_SUFFIX = {
    "x64": "x86",
    "x86-32": "x86",
    "aarch64": "aarch64",
    "arm": "aarch32",
    "ppc64": "ppc64",
    "ppc64le": "ppc64le",
    "s390x": "s390x",
    "riscv64": "riscv",
    "sparcv9": "sparcv9",
}

# Mapping from temurin-build os values to the aqa-tests sw.os suffix.
# The suffix is the part that follows 'sw.os.' in the label schema.
# Templates in jenkins_job_config.json use 'sw.os.{os}' — the {os}
# placeholder is replaced with just the suffix so the full token is correct.
_OS_SUFFIX = {
    "linux": "linux",
    "alpine-linux": "alpine-linux",
    "mac": "mac",
    "windows": "windows",
    "aix": "aix",
    "solaris": "solaris",
    "zos": "zos",
}


# Sentinel key used in stageAgentLabels to specify a generic agent label that
# is not tied to a specific OS or architecture.  The value is passed through
# verbatim — no {os}/{arch} substitution is applied.  Pipelines that run on
# shared infrastructure (e.g. the launch job) use this label instead of
# Jenkins' built-in "agent any" so that only nodes with the required tooling
# (e.g. python3, git) are selected.
#
# Example in jenkins_job_config.json:
#   "stageAgentLabels": {
#     "__any__": "ci.role.launcher",
#     "Build": "ci.role.build&&sw.os.{os}&&hw.arch.{arch}",
#     ...
#   }
_ANY_SENTINEL = "__any__"


def _resolve_label(template, target_os, architecture):
    """Resolve {os} and {arch} placeholders in a label template.

    Replaces {os} with the sw.os suffix and {arch} with the hw.arch suffix
    so that templates like 'ci.role.build&&sw.os.{os}&&hw.arch.{arch}'
    produce 'ci.role.build&&sw.os.linux&&hw.arch.x86' — not a double-prefixed
    result like 'sw.os.sw.os.linux'.

    The __any__ sentinel key is passed through verbatim — call sites must skip
    substitution for that key (see generateJenkinsConfig).
    """
    os_suffix = _OS_SUFFIX.get(target_os, target_os)
    arch_suffix = _ARCH_SUFFIX.get(architecture, architecture)
    return template.replace("{os}", os_suffix).replace("{arch}", arch_suffix)


def generateJenkinsConfig(config_repo_path, pipeline_config_path, output_path):
    """Generate jenkins-config.json from jenkins_job_config.json.

    Reads TARGET_OS and ARCHITECTURE from pipeline-config.json to resolve
    label placeholders, then writes a new jenkins-config.json with:
      stageAgentLabels         — raw templates
      resolvedStageAgentLabels — fully substituted sw.os.* / hw.arch.* labels
      buildNodeLabel           — resolved Build-stage label (convenience key)

    pipeline-config.json is never modified.

    Args:
        config_repo_path:    Path to the config repository root.
        pipeline_config_path: Path to the existing pipeline-config.json (read-only).
        output_path:          Path to write jenkins-config.json.
    """
    # Load jenkins_job_config.json
    jenkins_config_path = Path(config_repo_path) / "jenkins_job_config.json"
    if not jenkins_config_path.exists():
        print(
            f"ERROR: jenkins_job_config.json not found: {jenkins_config_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(jenkins_config_path, "r", encoding="utf-8") as f:
        jenkins_config = json.load(f)

    stage_agent_labels = jenkins_config.get("stageAgentLabels", {})
    if not stage_agent_labels:
        print(
            "WARNING: stageAgentLabels is empty in jenkins_job_config.json",
            file=sys.stderr,
        )

    # Read TARGET_OS and ARCHITECTURE from the CI-agnostic pipeline-config.json
    pipeline_config_path = Path(pipeline_config_path)
    if not pipeline_config_path.exists():
        print(
            f"ERROR: pipeline-config.json not found: {pipeline_config_path}",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(pipeline_config_path, "r", encoding="utf-8") as f:
        pipeline_config = json.load(f)

    target_os = pipeline_config["buildConfig"]["TARGET_OS"]
    architecture = pipeline_config["buildConfig"]["ARCHITECTURE"]

    # Resolve {os}/{arch} placeholders to sw.os.* / hw.arch.* schema tokens.
    # The __any__ sentinel is passed through verbatim — it represents a generic
    # agent label with no OS/arch binding.
    resolved = {
        stage: (
            template
            if stage == _ANY_SENTINEL
            else _resolve_label(template, target_os, architecture)
        )
        for stage, template in stage_agent_labels.items()
    }

    # Build the jenkins-config.json output — pipeline-config.json is not touched
    build_node_label = resolved.get("02-build", "")
    additional_node_labels = pipeline_config["buildConfig"].get(
        "ADDITIONAL_NODE_LABELS", ""
    )
    if build_node_label and additional_node_labels:
        build_node_label = build_node_label + "&&" + additional_node_labels

    # Pass activeNodeTimeoutMinutes through to jenkins-config.json so the
    # Jenkinsfile can enforce a "no active nodes" timeout at node() allocation.
    active_node_timeout = jenkins_config.get("activeNodeTimeoutMinutes", 10)

    jenkins_out = {
        "stageAgentLabels": stage_agent_labels,
        "resolvedStageAgentLabels": resolved,
        "buildNodeLabel": build_node_label,
        "activeNodeTimeoutMinutes": active_node_timeout,
    }

    with open(Path(output_path), "w", encoding="utf-8") as f:
        json.dump(jenkins_out, f, indent=2)

    print(f"✓ Created {output_path}")
    print(f"  Build node label: {build_node_label}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate jenkins-config.json from jenkins_job_config.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
  python3 ci/jenkins/lib/load-jenkins-json-config.py \\
      --config-repo-path ./config-repo \\
      --pipeline-config  ./pipeline-config.json \\
      --output           ./jenkins-config.json
        """,
    )
    parser.add_argument(
        "--config-repo-path",
        required=True,
        help="Path to the config repository root (contains jenkins_job_config.json)",
    )
    parser.add_argument(
        "--pipeline-config",
        default="./pipeline-config.json",
        help="Path to the CI-agnostic pipeline-config.json to read (default: ./pipeline-config.json)",
    )
    parser.add_argument(
        "--output",
        default="./jenkins-config.json",
        help="Path to write jenkins-config.json (default: ./jenkins-config.json)",
    )
    args = parser.parse_args()
    generateJenkinsConfig(args.config_repo_path, args.pipeline_config, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
