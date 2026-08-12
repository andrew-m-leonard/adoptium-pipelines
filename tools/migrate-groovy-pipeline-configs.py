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
Migrate legacy Groovy pipeline configurations to new JSON architecture.

This tool converts legacy Groovy configs to the new launch job architecture:
- Uses batch-convert-groovy-configs.py for conversion
- Removes "u" suffix from output filenames
- Generates adoptium_pipeline_config.json  (CI-agnostic config)
- Generates jenkins_job_config.json        (Jenkins-specific config)
- Structures output for launch job + platform job architecture

Usage:
    # Convert all configs and generate config files
    python3 migrate-groovy-pipeline-configs.py \
        --source ~/workspace/ci-jenkins-pipelines/pipelines/jobs/configurations \
        --output ~/workspace/ci-temurin-config

    # Dry run to preview
    python3 migrate-groovy-pipeline-configs.py \
        --source ./configs --output ./output --dry-run

    # Verbose output
    python3 migrate-groovy-pipeline-configs.py \
        --source ./configs --output ./output --verbose
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List


def find_converter_script() -> Path:
    """Find the batch-convert-groovy-configs.py script."""
    script_dir = Path(__file__).parent
    converter = script_dir / "batch-convert-groovy-configs.py"

    if converter.exists():
        return converter

    raise FileNotFoundError(
        "Could not find batch-convert-groovy-configs.py script. "
        "Please ensure it's in the same directory as this script."
    )


def _find_pipeline_root() -> Path:
    """Return the ci-adoptium-pipelines repository root (parent of tools/)."""
    return Path(__file__).parent.parent


def load_pipeline_stages() -> list[dict]:
    """Load the ordered stage list from scripts/stages/pipeline-stages.json.

    Returns a list of dicts with at least 'id' and 'label' keys, in pipeline order.
    Raises FileNotFoundError if the registry file is missing.
    """
    registry = _find_pipeline_root() / "scripts" / "stages" / "pipeline-stages.json"
    if not registry.exists():
        raise FileNotFoundError(
            f"pipeline-stages.json not found: {registry}\n"
            "Ensure scripts/stages/pipeline-stages.json exists in the repository."
        )
    with open(registry, "r", encoding="utf-8") as f:
        return json.load(f)["pipelineStages"]


def extract_version_from_filename(filename: str) -> str | None:
    """Extract JDK version from filename, removing 'u' suffix."""
    match = re.search(r"(jdk\d+)u?_pipeline_config", filename)
    if match:
        return match.group(1)  # Returns jdk8, jdk11, jdk17, etc. (without 'u')
    return None


def check_if_job_disabled(source_dir: Path, version: str) -> bool:
    """
    Check if the job is disabled by looking for 'disableJob = true' in jdkNN(u).groovy file.

    Args:
        source_dir: Directory containing the Groovy files
        version: JDK version (e.g., 'jdk21')

    Returns:
        True if job is disabled, False otherwise
    """
    # Try both with and without 'u' suffix
    for suffix in ["u", ""]:
        groovy_file = source_dir / f"{version}{suffix}.groovy"
        if groovy_file.exists():
            try:
                with open(groovy_file, "r", encoding="utf-8") as f:
                    content = f.read()
                    # Look for disableJob = true (with optional whitespace)
                    if re.search(r"disableJob\s*=\s*true", content):
                        return True
            except Exception as e:
                print(f"  Warning: Could not read {groovy_file.name}: {e}")

    # If we can't find the file or disableJob, assume it's enabled
    return False


def generate_adoptium_pipeline_config(
    version_configs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Generate adoptium_pipeline_config.json — CI-agnostic configuration."""
    version_configs_sorted = sorted(version_configs, key=lambda x: x["version"])

    active_versions = [
        {"version": config["version"], "enabled": config.get("enabled", True)}
        for config in version_configs_sorted
    ]

    return {
        "activeJdkVersions": active_versions,
        "defaultBuildArgs": "",
        "defaultConfigureArgs": "",
        "defaultVariant": "temurin",
        "configFilePrefix": "configurations/",
        "configFileSuffix": "_pipeline_config.json",
        "repository": {
            "url": "https://github.com/adoptium/ci-adoptium-pipelines.git",
            "branch": "main",
            "credentialsId": "",
            "buildRepoUrl": "https://github.com/adoptium/temurin-build.git",
            "buildBranch": "master",
            "aqaRepoUrl": "https://github.com/adoptium/aqa-tests.git",
            "aqaBranch": "master",
        },
    }


# ---------------------------------------------------------------------------
# Platform key migration  (camelCase → aqa-aligned {arch}_{os})
# ---------------------------------------------------------------------------

PLATFORM_KEY_MAP = {
    "x64Linux": "x86-64_linux",
    "x64Mac": "x86-64_mac",
    "x64Windows": "x86-64_windows",
    "x64AlpineLinux": "x86-64_alpine-linux",
    "x32Windows": "x86-32_windows",
    "aarch64Linux": "aarch64_linux",
    "aarch64Mac": "aarch64_mac",
    "aarch64Windows": "aarch64_windows",
    "aarch64AlpineLinux": "aarch64_alpine-linux",
    "arm32Linux": "arm_linux",
    "ppc64Aix": "ppc64_aix",
    "ppc64leLinux": "ppc64le_linux",
    "s390xLinux": "s390x_linux",
    "riscv64Linux": "riscv64_linux",
    "sparcv9Solaris": "sparcv9_solaris",
    "x64Solaris": "x86-64_solaris",
}


def _strip_create_sbom(args_str: str) -> str:
    """Remove --create-sbom flag from a buildArgs string, collapsing extra whitespace."""
    return re.sub(r"\s*--create-sbom\b", "", args_str).strip()


def _strip_create_sbom_from_build_args(platform_config: Dict[str, Any]) -> None:
    """Remove --create-sbom from buildArgs in a platform config entry (in-place).

    buildArgs may be a plain string or a variant dict (e.g. {"temurin": "..."}).
    --create-sbom is now controlled by the CREATE_SBOM stage parameter.
    """
    build_args = platform_config.get("buildArgs")
    if build_args is None:
        return
    if isinstance(build_args, str):
        platform_config["buildArgs"] = _strip_create_sbom(build_args)
    elif isinstance(build_args, dict):
        platform_config["buildArgs"] = {
            variant: _strip_create_sbom(val) if isinstance(val, str) else val
            for variant, val in build_args.items()
        }


def migrate_platform_keys(config: Dict[str, Any]) -> None:
    """Rename buildConfigurations keys and targetConfigurations entries in-place.

    Converts legacy camelCase keys (e.g. 'x64Linux') to the aqa-tests
    PLATFORM_MAP convention (e.g. 'x86-64_linux').  Unknown keys are left
    unchanged so novel platforms are not silently dropped.
    """
    build_configs = config.get("buildConfigurations")
    if build_configs:
        config["buildConfigurations"] = {
            PLATFORM_KEY_MAP.get(k, k): v for k, v in build_configs.items()
        }

    target_configs = config.get("targetConfigurations")
    if target_configs:
        config["targetConfigurations"] = [
            PLATFORM_KEY_MAP.get(k, k) for k in target_configs
        ]


# ---------------------------------------------------------------------------
# Label token migration
# ---------------------------------------------------------------------------
# Schema version convention:
#   - Dots (.) are used ONLY as namespace separators between label segments,
#     e.g.  sw.tool.xcode.15_0_1   sw.os.mac.10_14   sw.os.aix.7_2
#   - Version numbers that contain dots in the legacy form have those dots
#     replaced with underscores in the schema version component via _v().
#   - Non-digit separator characters between a tool name and its version
#     (e.g. the "v" in "armv8.2") are stripped entirely.
#
# Each rule is a (compiled_regex, callable) pair; tried in order, first match
# wins.  Pattern convention: (?i) for case-insensitivity, $ anchors the end
# (re.match already anchors the start).


def _v(ver_str: str) -> str:
    """Normalise a version string for use as a label version segment.

    Dots within the version number are replaced with underscores so that dots
    remain exclusively as schema namespace separators.
    '15.0.1' -> '15_0_1',  '8.2' -> '8_2',  '10.14' -> '10_14',  '17' -> '17'
    """
    return ver_str.replace(".", "_")


_LABEL_MIGRATION_RULES = [
    # -----------------------------------------------------------------------
    # ci.role — bare role words
    # -----------------------------------------------------------------------
    (re.compile(r"(?i)^build$"), lambda m: "ci.role.build"),
    (re.compile(r"(?i)^worker$"), lambda m: "ci.role.worker"),
    (re.compile(r"(?i)^test$"), lambda m: "ci.role.test"),
    # -----------------------------------------------------------------------
    # sw.tool — Xcode  xcode[non-digit-prefix]<ver>
    # Non-digit chars between "xcode" and the version are stripped.
    # e.g. xcode15.0.1  =>  sw.tool.xcode.15_0_1
    # -----------------------------------------------------------------------
    (
        re.compile(r"(?i)^xcode[^\d]*(?P<ver>\d[\d.]*)$"),
        lambda m: f'sw.tool.xcode.{_v(m.group("ver"))}',
    ),
    # -----------------------------------------------------------------------
    # sw.tool — Visual Studio  vs<4-digit-year>
    # e.g. vs2022  =>  sw.tool.vs.2022
    # -----------------------------------------------------------------------
    (
        re.compile(r"(?i)^vs(?P<year>\d{4})$"),
        lambda m: f'sw.tool.vs.{m.group("year")}',
    ),
    # -----------------------------------------------------------------------
    # sw.tool — IBM XL C/C++  xlc<ver>
    # e.g. xlc16  =>  sw.tool.xlc.16
    # -----------------------------------------------------------------------
    (
        re.compile(r"(?i)^xlc(?P<ver>\d[\d.]*)$"),
        lambda m: f'sw.tool.xlc.{_v(m.group("ver"))}',
    ),
    # -----------------------------------------------------------------------
    # sw.tool — IBM Open XL C/C++  openxl<ver>
    # e.g. openxl17  =>  sw.tool.openxl.17
    # -----------------------------------------------------------------------
    (
        re.compile(r"(?i)^openxl(?P<ver>\d[\d.]*)$"),
        lambda m: f'sw.tool.openxl.{_v(m.group("ver"))}',
    ),
    # -----------------------------------------------------------------------
    # sw.tool — ARM architecture feature label  arm[non-digit-prefix]<ver>
    # Non-digit separator chars (e.g. "v") between "arm" and the version are
    # stripped; version dots become underscores.
    # e.g. armv8.2  =>  sw.tool.arm.8_2
    # -----------------------------------------------------------------------
    (
        re.compile(r"(?i)^arm[^\d]*(?P<ver>\d[\d.]*)$"),
        lambda m: f'sw.tool.arm.{_v(m.group("ver"))}',
    ),
    # -----------------------------------------------------------------------
    # hw.arch — bare x86 architecture tokens used as additionalNodeLabels
    # Both x86-32 and x86-64 map to hw.arch.x86 (there are no native 32-bit
    # x86 Linux build targets; aarch32 is the only 32-bit arch in use).
    # e.g. x86-32  =>  hw.arch.x86
    #      x86-64  =>  hw.arch.x86
    # -----------------------------------------------------------------------
    (
        re.compile(r"(?i)^x86-(?:32|64)$"),
        lambda m: "hw.arch.x86",
    ),
    # -----------------------------------------------------------------------
    # sw.os.windows — win<4-digit-year>
    # e.g. win2022  =>  sw.os.windows.2022
    # -----------------------------------------------------------------------
    (
        re.compile(r"(?i)^win(?P<year>\d{4})$"),
        lambda m: f'sw.os.windows.{m.group("year")}',
    ),
    # -----------------------------------------------------------------------
    # sw.os.mac — macos<ver>  (full version preserved, dots → underscores)
    # e.g. macos10.14  =>  sw.os.mac.10_14
    #      macos11     =>  sw.os.mac.11
    # -----------------------------------------------------------------------
    (
        re.compile(r"(?i)^macos(?P<ver>\d[\d.]*)$"),
        lambda m: f'sw.os.mac.{_v(m.group("ver"))}',
    ),
    # -----------------------------------------------------------------------
    # sw.os.aix — aix<3-digit-stream>
    # Stream encodes major+minor: 720 → major=7, minor=2  =>  sw.os.aix.7_2
    # e.g. aix720  =>  sw.os.aix.7_2
    #      aix715  =>  sw.os.aix.7_1
    # -----------------------------------------------------------------------
    (
        re.compile(r"(?i)^aix(?P<stream>\d{3})$"),
        lambda m: f'sw.os.aix.{m.group("stream")[0]}_{m.group("stream")[1]}',
    ),
    # -----------------------------------------------------------------------
    # sw.os.linux distributions — <distro><ver>  (dots → underscores)
    # e.g. centos7   =>  sw.os.centos.7
    #      rhel8     =>  sw.os.rhel.8
    #      ubuntu22  =>  sw.os.ubuntu.22
    # -----------------------------------------------------------------------
    (
        re.compile(
            r"(?i)^(?P<distro>centos|rhel|ubuntu|sles|debian|fedora)(?P<ver>\d[\d.]*)$"
        ),
        lambda m: f'sw.os.{m.group("distro").lower()}.{_v(m.group("ver"))}',
    ),
]

# Schema root prefixes — tokens that already start with one of these are
# already schema-compliant and must not be rewritten.
_SCHEMA_ROOTS = ("hw.", "sw.", "ci.")


def migrate_label_token(token: str) -> str:
    """Translate a single legacy label token to its schema equivalent.

    Tokens that already start with a recognised schema root (hw., sw., ci.)
    are returned unchanged.  All other tokens — including those that contain
    dots as part of a legacy version number (e.g. xcode15.0.1, armv8.2,
    macos10.14) — are tested against the migration rules in order.
    Unrecognised tokens are returned as-is so the config still works.
    """
    token = token.strip()
    if not token:
        return token

    # Already schema-compliant — pass through.
    if any(token.startswith(root) for root in _SCHEMA_ROOTS):
        return token

    for pattern, replacement in _LABEL_MIGRATION_RULES:
        m = pattern.match(token)
        if m:
            return replacement(m)

    # No rule matched — return unchanged so the config still works.
    return token


def migrate_label_tokens(label_value: str) -> str:
    """Translate a legacy &&-joined label string to schema-compliant tokens."""
    tokens = [t.strip() for t in label_value.split("&&")]
    return "&&".join(migrate_label_token(t) for t in tokens)


def migrate_additional_node_labels(platform_config: Dict[str, Any]) -> None:
    """Migrate additionalNodeLabels in-place to the aqa-tests label schema."""
    anl = platform_config.get("additionalNodeLabels")
    if anl is None:
        return
    if isinstance(anl, str):
        platform_config["additionalNodeLabels"] = migrate_label_tokens(anl)
    elif isinstance(anl, dict):
        platform_config["additionalNodeLabels"] = {
            variant: migrate_label_tokens(val) for variant, val in anl.items()
        }


# Default agent label template per stageId.
# Keys match the "id" fields in scripts/stages/pipeline-stages.json exactly.
# Stages not listed here default to "ci.role.worker".
# Placeholders {os} and {arch} are resolved at runtime to sw.os.* / hw.arch.*
# schema tokens by load-jenkins-json-config.py.
_STAGE_AGENT_LABEL_DEFAULTS: Dict[str, str] = {
    "01-initialize": "ci.role.worker",
    "02-build": "ci.role.build&&sw.os.{os}&&hw.arch.{arch}",
    "03-internal-code-sign": "eclipse-codesign",
    "04-assemble-images": "ci.role.build&&sw.os.{os}&&hw.arch.{arch}",
    "06-post-build-code-sign": "ci.role.worker",
    "07-installer": "ci.role.build&&sw.os.{os}&&hw.arch.{arch}",
    "08-code-sign-installer": "ci.role.worker",
    "09-sbom-sign": "ci.role.worker",
    "10-digital-artifact-sign": "ci.role.worker",
    "11-verify-signing": "ci.role.worker",
    "12-validate-sbom": "ci.role.build&&sw.os.{os}&&hw.arch.{arch}",
    "13-smoke-tests": "ci.role.build&&sw.os.{os}&&hw.arch.{arch}",
    "14-aqa-tests": "ci.role.build&&hw.arch.{arch}",
    "15-tck-tests": "ci.role.build&&hw.arch.{arch}",
    "16-publish": "ci.role.worker",
    "20-reproducible-compare": "ci.role.build&&sw.os.{os}&&hw.arch.{arch}",
}


def generate_jenkins_job_config(pipeline_base_folder: str = "") -> Dict[str, Any]:
    """Generate jenkins_job_config.json — Jenkins-specific configuration.

    stageAgentLabels keys are derived from scripts/stages/pipeline-stages.json
    (the canonical stage registry) so that the generated file always uses stageIds
    as keys, matching what Jenkinsfile.declarative and load-jenkins-json-config.py
    expect.  Any stage present in the registry but absent from
    _STAGE_AGENT_LABEL_DEFAULTS receives 'ci.role.worker' as a safe default.

    Args:
        pipeline_base_folder: Optional Jenkins folder path under which all
            generated jobs and views will be placed (e.g. "MyOrg/OpenJDK").
            Empty string means Jenkins root (the default).
    """
    stages = load_pipeline_stages()
    stage_agent_labels: Dict[str, str] = {"__any__": "ci.role.worker"}
    for stage in stages:
        stage_id = stage["id"]
        stage_agent_labels[stage_id] = _STAGE_AGENT_LABEL_DEFAULTS.get(
            stage_id, "ci.role.worker"
        )

    config: Dict[str, Any] = {
        "jenkinsfilePath": "ci/jenkins/Jenkinsfile.declarative",
        "pipelineTimeoutHours": 8,
        "activeNodeTimeoutMinutes": 10,
    }

    # Only emit pipelineBaseFolder when explicitly provided — omitting it is
    # equivalent to the Jenkins root and avoids confusing blank fields.
    if pipeline_base_folder:
        config["pipelineBaseFolder"] = pipeline_base_folder

    config["jobConfiguration"] = {
            "defaultParameters": {
                "VARIANT": "temurin",
                "CLEAN_WORKSPACE_AFTER_STAGE": True,
                "CREATE_SBOM": True,
                "RUN_TESTS": True,
                "ENABLE_INSTALLERS": True,
                "SIGN_ARTIFACTS": True,
                "PUBLISH_ARTIFACTS": False,
                "RUN_REPRODUCIBLE_COMPARE": False,
            },
            "logRotation": {
                "daysToKeep": 30,
                "numToKeep": 50,
                "artifactDaysToKeep": 7,
                "artifactNumToKeep": 10,
            },
        }
    config["stageAgentLabels"] = stage_agent_labels
    return config


def main():
    parser = argparse.ArgumentParser(
        description="Convert legacy Groovy configs to new launch job architecture",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert all configs and generate jenkins_job_config.json
  %(prog)s --source ../ci-jenkins-pipelines/pipelines/jobs/configurations \\
           --output ../ci-temurin-config

  # Place all generated jobs inside a Jenkins folder
  %(prog)s --source ../ci-jenkins-pipelines/pipelines/jobs/configurations \\
           --output ../ci-temurin-config \\
           --pipeline-base-folder MyOrg/OpenJDK

  # Dry run to preview
  %(prog)s --source ./configs --output ./output --dry-run

  # Verbose output
  %(prog)s --source ./configs --output ./output --verbose
        """,
    )

    parser.add_argument(
        "--source",
        "-s",
        type=Path,
        required=True,
        help="Source directory containing Groovy configuration files",
    )

    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        required=True,
        help="Output directory for JSON configuration files",
    )

    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Show what would be converted without actually converting",
    )

    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show detailed conversion output"
    )

    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Overwrite existing JSON files without prompting",
    )

    parser.add_argument(
        "--pipeline-base-folder",
        metavar="FOLDER",
        default="",
        help=(
            "Jenkins folder path under which all generated jobs and views will "
            "be placed (e.g. 'MyOrg/OpenJDK'). Written as pipelineBaseFolder in "
            "jenkins_job_config.json. Omit to generate at the Jenkins root."
        ),
    )

    args = parser.parse_args()

    # Print header
    print("=" * 70)
    print("Legacy Groovy to New Architecture Converter")
    print("=" * 70)
    print()

    try:
        # Find the converter script
        converter = find_converter_script()
        if args.verbose:
            print(f"Using converter: {converter}")
            print()

        # Create temporary directory for initial conversion
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            if args.dry_run:
                print("DRY RUN - No files will be converted")
                print()
                print(f"Would use converter: {converter}")
                print(f"Source: {args.source}")
                print(f"Output: {args.output}")
                if args.pipeline_base_folder:
                    print(f"Pipeline base folder: {args.pipeline_base_folder}")
                print()
                print("Process:")
                print("1. Convert Groovy files to JSON (temp directory)")
                print("2. Remove 'u' suffix from filenames")
                print("3. Move to configurations/ subdirectory")
                print("4. Generate adoptium_pipeline_config.json")
                print("5. Generate jenkins_job_config.json")
                return 0

            # Step 1: Run the existing converter to temp directory
            print("Step 1: Converting Groovy files to JSON...")
            print()

            cmd = [
                "python3",
                str(converter),
                "--source",
                str(args.source),
                "--output",
                str(temp_path),
            ]

            if args.force:
                cmd.append("--force")

            if args.verbose:
                cmd.append("--verbose")

            result = subprocess.run(
                cmd, capture_output=not args.verbose, text=True, check=False
            )

            if result.returncode != 0:
                print("Error: Conversion failed", file=sys.stderr)
                if result.stderr:
                    print(result.stderr, file=sys.stderr)
                return 1

            # Step 2: Process converted files
            print()
            print("Step 2: Processing converted files...")
            print()

            # Create output directories
            args.output.mkdir(parents=True, exist_ok=True)
            config_dir = args.output / "configurations"
            config_dir.mkdir(parents=True, exist_ok=True)

            # Process each converted file
            version_configs = []
            converted_files = list(temp_path.glob("*_pipeline_config.json"))
            failed_files = []

            for i, temp_file in enumerate(sorted(converted_files), 1):
                # Extract version (remove 'u' suffix)
                version = extract_version_from_filename(temp_file.name)
                if not version:
                    print(
                        f"[{i}/{len(converted_files)}] Skipping {temp_file.name} (could not extract version)"
                    )
                    continue

                try:
                    # Read the converted file
                    with open(temp_file, "r", encoding="utf-8") as f:
                        config = json.load(f)

                    # Update version field (remove 'u' suffix)
                    config["version"] = version

                    # Set openjdkVersion with 'u' suffix (e.g., jdk21u)
                    # This represents the OpenJDK version/stream, not an SCM reference
                    if not config.get("openjdkVersion"):
                        config["openjdkVersion"] = version + "u"

                    # Rename platform keys to aqa-aligned {arch}_{os} convention
                    migrate_platform_keys(config)

                    # Remove obsolete fields and migrate labels for each platform entry
                    for platform_config in config.get(
                        "buildConfigurations", {}
                    ).values():
                        platform_config.pop("test", None)
                        platform_config.pop("additionalTestParams", None)
                        platform_config.pop("additionalTestLabels", None)
                        migrate_additional_node_labels(platform_config)
                        _strip_create_sbom_from_build_args(platform_config)

                    # Check if the job is disabled in the jdkNN(u).groovy file
                    is_disabled = check_if_job_disabled(args.source, version)

                    # Add enabled flag (inverted from disabled)
                    config["enabled"] = not is_disabled

                    version_configs.append(config)

                    # Write to new location with corrected filename
                    output_file = config_dir / f"{version}_pipeline_config.json"

                    status = "✅" if config["enabled"] else "⚠️  (disabled)"
                    print(
                        f"[{i}/{len(converted_files)}] {temp_file.name} -> {output_file.name} {status}"
                    )

                    with open(output_file, "w", encoding="utf-8") as f:
                        json.dump(config, f, indent=2)

                    if args.verbose:
                        print(f"  Version: {config['version']}")
                        print(f"  OpenJDK Version: {config['openjdkVersion']}")
                        print(f"  Enabled: {config['enabled']}")
                        print(
                            f"  Platforms: {len(config.get('buildConfigurations', {}))}"
                        )
                        print(
                            "  Migrated platform keys to aqa-aligned <arch>_<os> convention"
                        )
                        print(
                            "  Removed obsolete fields: test, additionalTestParams, additionalTestLabels"
                        )
                        print("  Migrated additionalNodeLabels to label schema tokens")

                except json.JSONDecodeError as e:
                    print(
                        f"[{i}/{len(converted_files)}] {temp_file.name} ❌ (Invalid JSON: {e})"
                    )
                    failed_files.append((temp_file.name, str(e)))
                    if args.verbose:
                        print(f"  Error at line {e.lineno}, column {e.colno}")
                        print(f"  You may need to manually review: {temp_file}")
                except Exception as e:
                    print(f"[{i}/{len(converted_files)}] {temp_file.name} ❌ ({e})")
                    failed_files.append((temp_file.name, str(e)))

            # Step 3: Generate adoptium_pipeline_config.json and jenkins_job_config.json
            if version_configs:
                print()
                print("Step 3: Generating adoptium_pipeline_config.json...")

                adoptium_config = generate_adoptium_pipeline_config(version_configs)
                adoptium_config_file = args.output / "adoptium_pipeline_config.json"

                with open(adoptium_config_file, "w", encoding="utf-8") as f:
                    json.dump(adoptium_config, f, indent=2)

                print(f"  Created: {adoptium_config_file.name}")

                if args.verbose:
                    print(f"  Active versions: {adoptium_config['activeJdkVersions']}")

                print()
                print("Step 4: Generating jenkins_job_config.json...")

                jenkins_config = generate_jenkins_job_config(
                    pipeline_base_folder=args.pipeline_base_folder,
                )
                jenkins_config_file = args.output / "jenkins_job_config.json"

                with open(jenkins_config_file, "w", encoding="utf-8") as f:
                    json.dump(jenkins_config, f, indent=2)

                print(f"  Created: {jenkins_config_file.name}")
                if args.pipeline_base_folder:
                    print(f"  pipelineBaseFolder: {args.pipeline_base_folder}")

            # Print summary
            print()
            print("=" * 70)
            print("Conversion Summary")
            print("=" * 70)
            print(f"Total files: {len(converted_files)}")
            print(f"Successful: {len(version_configs)}")
            print(f"Failed: {len(failed_files)}")
            print()

            if failed_files:
                print("⚠️  Some files failed to convert:")
                for filename, error in failed_files:
                    print(f"  ❌ {filename}: {error}")
                print()
                print(
                    "Note: Failed files were skipped. You may need to convert them manually."
                )
                print()

            if version_configs:
                print("✅ Successfully converted configurations!")
            else:
                print("❌ No configurations were successfully converted")
                return 1
            print()
            print("Generated files:")
            print("  - adoptium_pipeline_config.json  (CI-agnostic)")
            print("  - jenkins_job_config.json         (Jenkins-specific)")
            for config in version_configs:
                print(f"  - configurations/{config['version']}_pipeline_config.json")
            print()
            print("Next steps:")
            print("1. Review the generated JSON files")
            print("2. Verify platform configurations are correct")
            print("3. Test with the seed job")
            print("4. Commit to your configuration repository")
            print()

            return 0

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

# Made with Bob
