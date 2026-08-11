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
Load JSON Configuration and Generate Pipeline Config

Reads adoptium_pipeline_config.json and jdkNN_pipeline_config.json from
the config repository root and generates the CI-agnostic pipeline-config.json
consumed by all stage scripts.

Architecture:
  pipeline-config.json contains ONLY values derived from config-file data at
  init time — platform identity, build tool config, repo defaults, and the
  single pipeline-level control (cleanWorkspaceAfterStage).

  Stage params (SCM_REF, BUILD_REF, AQA_REF, CREATE_SBOM, RUN_TESTS, etc.)
  are NOT stored here — they flow exclusively through the process environment,
  injected by the orchestrator (Jenkins: params→env; ci/local: _stage_env()).

Usage:
    python3 load-json-config.py \
        --jdk-version jdk21u \
        --variant temurin \
        --target-os mac \
        --architecture aarch64 \
        --config-repo-path ./config-repo \
        --output-dir .
"""

import json
import sys
import argparse
from pathlib import Path


# Mapping from temurin-build arch values to the aqa-tests hw.arch suffix.
# The suffix is the part that follows 'hw.arch.' in label templates.
# Templates use 'hw.arch.{arch}' — {arch} is replaced with just the suffix.
# Note: x64 and x86-32 both map to 'x86' — the aqa-tests schema uses
# hw.arch.x86 for the whole x86 family; there is no hw.arch.x86-64.
ARCH_SUFFIX = {
    'x64':     'x86',
    'x86-32':  'x86',
    'aarch64': 'aarch64',
    'arm':     'aarch32',
    'ppc64':   'ppc64',
    'ppc64le': 'ppc64le',
    's390x':   's390x',
    'riscv64': 'riscv',
    'sparcv9': 'sparcv9',
}

# Mapping from temurin-build os values to the aqa-tests sw.os suffix.
# The suffix is the part that follows 'sw.os.' in label templates.
# Templates use 'sw.os.{os}' — {os} is replaced with just the suffix.
OS_SUFFIX = {
    'linux':        'linux',
    'alpine-linux': 'alpine-linux',
    'mac':          'mac',
    'windows':      'windows',
    'aix':          'aix',
    'solaris':      'solaris',
    'zos':          'zos',
}

# Mapping from old camelCase platform keys to new aqa-aligned {arch}_{os} keys.
# Enables graceful lookup when configs still use the legacy naming.
LEGACY_PLATFORM_KEY_MAP = {
    'x64Linux':           'x86-64_linux',
    'x64Mac':             'x86-64_mac',
    'x64Windows':         'x86-64_windows',
    'x64AlpineLinux':     'x86-64_alpine-linux',
    'x32Windows':         'x86-32_windows',
    'aarch64Linux':       'aarch64_linux',
    'aarch64Mac':         'aarch64_mac',
    'aarch64Windows':     'aarch64_windows',
    'aarch64AlpineLinux': 'aarch64_alpine-linux',
    'arm32Linux':         'arm_linux',
    'ppc64Aix':           'ppc64_aix',
    'ppc64leLinux':       'ppc64le_linux',
    's390xLinux':         's390x_linux',
    'riscv64Linux':       'riscv64_linux',
    'sparcv9Solaris':     'sparcv9_solaris',
    'x64Solaris':         'x86-64_solaris',
}


def get_platform_key(architecture, target_os):
    """Construct aqa-aligned platform key from architecture and OS.

    Returns the canonical {arch}_{os} key used in PLATFORM_MAP, e.g.
    get_platform_key('x64', 'linux') -> 'x86-64_linux'.
    Falls back to the old camelCase construction if the combination is not in
    the explicit map, so novel platforms are still handled gracefully.
    """
    # Build the arch segment: map temurin-build arch → aqa arch prefix
    arch_segment_map = {
        'x64':     'x86-64',
        'x86-32':  'x86-32',
        'aarch64': 'aarch64',
        'arm':     'arm',
        'ppc64':   'ppc64',
        'ppc64le': 'ppc64le',
        's390x':   's390x',
        'riscv64': 'riscv64',
        'sparcv9': 'sparcv9',
    }
    arch_seg = arch_segment_map.get(architecture, architecture)
    return f"{arch_seg}_{target_os}"


def extract_variant_value(value, variant):
    """
    Extract variant-specific value from config.
    Handles both simple strings and variant-specific objects.

    Args:
        value: Either a string or a dict with variant keys
        variant: The variant to extract (temurin, openj9, hotspot)

    Returns:
        The value for the specified variant, or None
    """
    if value is None:
        return None

    # If it's a string, return it directly
    if isinstance(value, str):
        return value

    # If it's a dict, extract variant-specific value
    if isinstance(value, dict):
        variant_value = value.get(variant)
        if variant_value is not None:
            return variant_value
        # Fall back to 'default' key if present
        return value.get('default')

    return None


def resolve_label_placeholders(template, target_os, architecture):
    """Resolve {os} and {arch} placeholders in a label template.

    Replaces {os} with the sw.os suffix and {arch} with the hw.arch suffix
    so that templates like 'ci.role.build&&sw.os.{os}&&hw.arch.{arch}'
    produce 'ci.role.build&&sw.os.linux&&hw.arch.x86' — not a double-prefixed
    result like 'sw.os.sw.os.linux'.
    """
    os_suffix   = OS_SUFFIX.get(target_os, target_os)
    arch_suffix = ARCH_SUFFIX.get(architecture, architecture)
    return template.replace('{os}', os_suffix).replace('{arch}', arch_suffix)


def build_node_label(build_label_template, additional_labels, target_os, architecture):
    """Build the fully-resolved Build-stage node label.

    Resolves {os} and {arch} placeholders in the stageAgentLabels["02-build"]
    template via the sw.os.* / hw.arch.* label schema, then appends any
    platform additionalNodeLabels with '&&'.
    """
    label = resolve_label_placeholders(build_label_template, target_os, architecture)
    if additional_labels:
        label = label + '&&' + additional_labels
    return label


def load_configuration(args):
    """Load CI-agnostic JSON configuration and generate pipeline-config.json."""

    jdk_version  = args.jdk_version
    variant      = args.variant
    target_os    = args.target_os
    architecture = args.architecture
    output_dir   = args.output_dir

    # Resolve release type (defaults to NIGHTLY)
    release_type = (args.release_type or 'NIGHTLY').upper()
    valid_release_types = ['NIGHTLY', 'WEEKLY', 'RELEASE']
    if release_type not in valid_release_types:
        print(f"ERROR: Invalid release type '{args.release_type}'. "
              f"Must be one of: {', '.join(valid_release_types)} (case-insensitive)",
              file=sys.stderr)
        sys.exit(1)

    # ── Load adoptium_pipeline_config.json ───────────────────────────────────
    # Always read from the config repo root — this is the single source of truth
    # for repo default refs and the configFilePrefix.  Stage params (SCM_REF,
    # BUILD_REF, etc.) are NOT read here; they come from the process environment.
    config_repo_path  = Path(args.config_repo_path)
    adoptium_cfg_path = config_repo_path / 'adoptium_pipeline_config.json'
    if not adoptium_cfg_path.exists():
        print(f"ERROR: adoptium_pipeline_config.json not found at: {adoptium_cfg_path}",
              file=sys.stderr)
        sys.exit(1)
    with open(adoptium_cfg_path, 'r') as f:
        adoptium_cfg = json.load(f)

    repo_defaults = adoptium_cfg.get('repository', {})
    build_ref      = repo_defaults.get('buildBranch')
    build_repo_url = repo_defaults.get('buildRepoUrl')
    aqa_ref        = repo_defaults.get('aqaBranch')
    aqa_repo_url   = repo_defaults.get('aqaRepoUrl')

    missing_defaults = [k for k, v in {
        'repository.buildBranch':  build_ref,
        'repository.buildRepoUrl': build_repo_url,
        'repository.aqaBranch':    aqa_ref,
        'repository.aqaRepoUrl':   aqa_repo_url,
    }.items() if not v]
    if missing_defaults:
        print(f"ERROR: Required fields missing from adoptium_pipeline_config.json: "
              f"{', '.join(missing_defaults)}", file=sys.stderr)
        sys.exit(1)

    # Use defaultVariant from adoptium_pipeline_config.json if variant not overridden
    if not variant:
        variant = adoptium_cfg.get('defaultVariant', 'temurin')

    # ── Load jdkNN_pipeline_config.json ──────────────────────────────────────
    config_prefix = adoptium_cfg.get('configFilePrefix', 'configurations/')
    config_dir    = config_repo_path / config_prefix.rstrip('/')
    config_file   = config_dir / f"{jdk_version}_pipeline_config.json"
    if not config_file.exists():
        print(f"ERROR: Configuration file not found: {config_file}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading configuration for: {jdk_version} {variant} {target_os} {architecture}")

    with open(config_file, 'r') as f:
        json_config = json.load(f)

    build_configurations = json_config.get('buildConfigurations', {})
    openjdk_version = json_config.get('openjdkVersion', jdk_version)

    # Construct platform key
    platform_key = get_platform_key(architecture, target_os)
    print(f"Platform key: {platform_key}")

    # Get platform configuration — also accept legacy camelCase keys
    if platform_key not in build_configurations:
        legacy_key = next(
            (old for old, new in LEGACY_PLATFORM_KEY_MAP.items() if new == platform_key),
            None
        )
        if legacy_key and legacy_key in build_configurations:
            print(f"Warning: config uses legacy platform key '{legacy_key}'; "
                  f"treating as '{platform_key}'")
            platform_key = legacy_key
        else:
            available = ', '.join(build_configurations.keys())
            print(f"ERROR: Platform '{platform_key}' not found in configuration.",
                  file=sys.stderr)
            print(f"Available platforms: {available}", file=sys.stderr)
            sys.exit(1)

    platform_config = build_configurations[platform_key]

    # Extract variant-specific values
    build_args             = extract_variant_value(platform_config.get('buildArgs'), variant)
    configure_args         = extract_variant_value(platform_config.get('configureArgs'), variant)
    docker_image           = extract_variant_value(platform_config.get('dockerImage'), variant)
    docker_file            = extract_variant_value(platform_config.get('dockerFile'), variant)
    additional_node_labels = extract_variant_value(platform_config.get('additionalNodeLabels'), variant)
    podman_args            = platform_config.get('podmanArgs', '')

    # Build the fully-resolved Build-stage node label using a CI-agnostic default.
    # CI-specific stageAgentLabels (from jenkins_job_config.json) are injected by
    # ci/jenkins/lib/load-jenkins-json-config.py which augments this file after generation.
    build_label_template = 'ci.role.build&&sw.os.{os}&&hw.arch.{arch}'
    node_label = build_node_label(build_label_template, additional_node_labels,
                                  target_os, architecture)

    # ── Generate pipeline-config.json ────────────────────────────────────────
    #
    # Three sections — each with a clear, non-overlapping ownership:
    #
    #   buildConfig   — platform identity and build tool config derived from
    #                   jdkNN_pipeline_config.json.  Exposed as CONFIG_* env vars
    #                   by the orchestrator so stage scripts don't need jq.
    #
    #   parameters    — pipeline-level controls that are NOT stage params.
    #                   Only cleanWorkspaceAfterStage belongs here; it is a
    #                   platform config value consumed by workspace-cleanup logic,
    #                   not by stage scripts.
    #
    #   repoDefaults  — DEFAULT git refs from adoptium_pipeline_config.json that
    #                   stage scripts (02-build.sh, 14-aqa-tests.sh, …) fall back
    #                   to when their own stage params (BUILD_REF, AQA_REF) are
    #                   empty.  Exposed as CONFIG_BUILD_REF / CONFIG_AQA_REF env
    #                   vars.  Stage params always take precedence.
    #
    # Stage params (SCM_REF, BUILD_REF, AQA_REF, CREATE_SBOM, RUN_TESTS,
    # ENABLE_INSTALLERS, SIGN_ARTIFACTS, RUN_REPRODUCIBLE_COMPARE, …) are NOT
    # stored here — they flow exclusively through the process environment.
    pipeline_config = {
        'buildConfig': {
            'JAVA_TO_BUILD':     openjdk_version,
            'TARGET_OS':         target_os,
            'ARCHITECTURE':      architecture,
            'VARIANT':           variant,
            'BUILD_ARGS':        build_args or '',
            'CONFIGURE_ARGS':    configure_args or '',
            'NODE_LABEL':        node_label,
            'DOCKER_IMAGE':      docker_image or '',
            'DOCKER_FILE':       docker_file or '',
            'DOCKER_REGISTRY':   platform_config.get('dockerRegistry', ''),
            'DOCKER_CREDENTIAL': platform_config.get('dockerCredential', ''),
            'DOCKER_ARGS':       platform_config.get('dockerArgs', ''),
            'PODMAN_ARGS':       podman_args,
        },
        'parameters': {
            'cleanWorkspaceAfterStage': platform_config.get('cleanWorkspaceAfterBuild', True),
        },
        'repoDefaults': {
            'buildRef':     build_ref,
            'buildRepoUrl': build_repo_url,
            'aqaRef':       aqa_ref,
            'aqaRepoUrl':   aqa_repo_url,
        },
    }

    # Save configuration
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    pipeline_config_file = output_path / 'pipeline-config.json'
    with open(pipeline_config_file, 'w') as f:
        json.dump(pipeline_config, f, indent=2)
    print(f"Created: {pipeline_config_file}")

    print("\nConfiguration Summary:")
    print(f"  Platform:       {platform_key}")
    print(f"  Build Args:     {build_args}")
    print(f"  Configure Args: {configure_args}")
    print(f"  Node Label:     {node_label}")
    print(f"  Docker Image:   {docker_image}")
    print(f"  Build Ref:      {build_ref}  (repoDefault)")
    print(f"  AQA Ref:        {aqa_ref}  (repoDefault)")

    return pipeline_config


def main():
    parser = argparse.ArgumentParser(
        description='Load JSON configuration and generate pipeline-config.json',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Nightly build
  python3 load-json-config.py \\
      --jdk-version jdk21u \\
      --variant temurin \\
      --target-os mac \\
      --architecture aarch64 \\
      --config-repo-path ./config-repo

  # Release build
  python3 load-json-config.py \\
      --jdk-version jdk17u \\
      --variant temurin \\
      --target-os linux \\
      --architecture x64 \\
      --release-type RELEASE \\
      --config-repo-path ./config-repo
        """
    )

    # ── Required ──────────────────────────────────────────────────────────────
    parser.add_argument('--jdk-version',      required=True,
                        help='JDK version (e.g., jdk21u, jdk17u)')
    parser.add_argument('--variant',          required=True,
                        help='Build variant (temurin, openj9, hotspot)')
    parser.add_argument('--target-os',        required=True,
                        help='Target OS (mac, linux, windows, aix)')
    parser.add_argument('--architecture',     required=True,
                        help='Target architecture (aarch64, x64, x32, ppc64, s390x)')
    parser.add_argument('--config-repo-path', required=True,
                        help='Path to the checked-out config repository root '
                             '(must contain adoptium_pipeline_config.json and '
                             'the configurations/ subdirectory)')

    # ── Optional ──────────────────────────────────────────────────────────────
    parser.add_argument('--output-dir', default='.',
                        help='Output directory for pipeline-config.json (default: .)')
    parser.add_argument('--release-type', type=str,
                        help='Type of release build: NIGHTLY (default), WEEKLY, or RELEASE')

    args = parser.parse_args()

    try:
        load_configuration(args)
        print("\n✅ Configuration loaded successfully")
        return 0
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())

# Made with Bob
