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
Load Adoptium Pipeline Configuration

Loads the CI-agnostic adoptium_pipeline_config.json from a configuration
repository (either via local path or remote URL) and provides the values
as structured output for consumption by CI systems and local runners.

This file is the single source of truth for:
  - activeJdkVersions
  - defaultBuildArgs / defaultConfigureArgs
  - defaultVariant
  - defaultScmReference
  - configFilePrefix / configFileSuffix
  - repository (url, branch, credentialsId)

Usage:
    # From a local config repo checkout
    python3 load-adoptium-pipeline-config-json.py --config-repo-dir ./ci-temurin-config

    # From a remote GitHub repository
    python3 load-adoptium-pipeline-config-json.py \
        --config-repo-url https://github.com/adoptium/ci-temurin-config.git \
        --config-repo-branch main

    # Output a specific field
    python3 load-adoptium-pipeline-config-json.py \
        --config-repo-dir ./ci-temurin-config \
        --field activeJdkVersions

    # Output as environment variable exports (for shell sourcing)
    python3 load-adoptium-pipeline-config-json.py \
        --config-repo-dir ./ci-temurin-config \
        --format env
"""

import argparse
import json
import sys
import urllib.request
from pathlib import Path

CONFIG_FILENAME = "adoptium_pipeline_config.json"


def load_from_local(config_repo_dir: str) -> dict:
    """Load adoptium_pipeline_config.json from a local directory."""
    config_path = Path(config_repo_dir) / CONFIG_FILENAME
    if not config_path.exists():
        print(f"ERROR: {CONFIG_FILENAME} not found at: {config_path}", file=sys.stderr)
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_from_remote(repo_url: str, branch: str) -> dict:
    """Load adoptium_pipeline_config.json from a remote GitHub repository."""
    # Convert git URL to raw.githubusercontent.com URL
    repo_path = repo_url.replace("https://github.com/", "").replace(".git", "")
    raw_url = (
        f"https://raw.githubusercontent.com/{repo_path}/{branch}/{CONFIG_FILENAME}"
    )

    try:
        with urllib.request.urlopen(raw_url) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(
            f"ERROR: Failed to fetch {CONFIG_FILENAME} from {raw_url}", file=sys.stderr
        )
        print(f"  HTTP {e.code}: {e.reason}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"ERROR: Failed to reach {raw_url}", file=sys.stderr)
        print(f"  {e.reason}", file=sys.stderr)
        sys.exit(1)


def get_active_versions(config: dict) -> list[str]:
    """Return list of enabled JDK version strings."""
    return [
        v["version"]
        for v in config.get("activeJdkVersions", [])
        if v.get("enabled", False)
    ]


def output_json(config: dict, field: str | None):
    """Output as JSON."""
    if field:
        value = config.get(field)
        if value is None:
            print(
                f"ERROR: Field '{field}' not found in {CONFIG_FILENAME}",
                file=sys.stderr,
            )
            sys.exit(1)
        print(json.dumps(value, indent=2))
    else:
        print(json.dumps(config, indent=2))


def output_env(config: dict):
    """Output as shell environment variable exports."""
    repo = config.get("repository", {})
    print(
        f"export ADOPTIUM_DEFAULT_VARIANT=\"{config.get('defaultVariant', 'temurin')}\""
    )
    print(
        f"export ADOPTIUM_DEFAULT_BUILD_ARGS=\"{config.get('defaultBuildArgs', '')}\""
    )
    print(
        f"export ADOPTIUM_DEFAULT_CONFIGURE_ARGS=\"{config.get('defaultConfigureArgs', '')}\""
    )
    print(
        f"export ADOPTIUM_DEFAULT_SCM_REF=\"{config.get('defaultScmReference', '')}\""
    )
    print(
        f"export ADOPTIUM_CONFIG_FILE_PREFIX=\"{config.get('configFilePrefix', 'configurations/')}\""
    )
    print(
        f"export ADOPTIUM_CONFIG_FILE_SUFFIX=\"{config.get('configFileSuffix', '_pipeline_config.json')}\""
    )
    print(f"export ADOPTIUM_REPO_URL=\"{repo.get('url', '')}\"")
    print(f"export ADOPTIUM_REPO_BRANCH=\"{repo.get('branch', 'main')}\"")
    print(f"export ADOPTIUM_REPO_CREDENTIALS_ID=\"{repo.get('credentialsId', '')}\"")
    print(f"export ADOPTIUM_BUILD_REPO_URL=\"{repo.get('buildRepoUrl', '')}\"")
    print(f"export ADOPTIUM_BUILD_BRANCH=\"{repo.get('buildBranch', '')}\"")
    print(f"export ADOPTIUM_AQA_REPO_URL=\"{repo.get('aqaRepoUrl', '')}\"")
    print(f"export ADOPTIUM_AQA_BRANCH=\"{repo.get('aqaBranch', '')}\"")

    active_versions = get_active_versions(config)
    print(f"export ADOPTIUM_ACTIVE_JDK_VERSIONS=\"{' '.join(active_versions)}\"")


def output_summary(config: dict):
    """Output a human-readable summary."""
    repo = config.get("repository", {})
    print(f"Adoptium Pipeline Configuration ({CONFIG_FILENAME})")
    print("=" * 60)
    print(f"  Default Variant       : {config.get('defaultVariant', 'temurin')}")
    print(f"  Default Build Args    : {config.get('defaultBuildArgs', '')}")
    print(f"  Default Configure Args: {config.get('defaultConfigureArgs', '')}")
    print(
        f"  Default SCM Reference : {config.get('defaultScmReference', '') or '(none)'}"
    )
    print(
        f"  Config File Prefix    : {config.get('configFilePrefix', 'configurations/')}"
    )
    print(
        f"  Config File Suffix    : {config.get('configFileSuffix', '_pipeline_config.json')}"
    )
    print(f"  Repository URL        : {repo.get('url', '')}")
    print(f"  Repository Branch     : {repo.get('branch', 'main')}")
    print(
        f"  Build Repo URL        : {repo.get('buildRepoUrl', '(MISSING - required)')}"
    )
    print(
        f"  Build Branch          : {repo.get('buildBranch', '(MISSING - required)')}"
    )
    print(f"  AQA Repo URL          : {repo.get('aqaRepoUrl', '(MISSING - required)')}")
    print(f"  AQA Branch            : {repo.get('aqaBranch', '(MISSING - required)')}")

    active = get_active_versions(config)
    print(f"  Active JDK Versions   : {', '.join(active)}")


def main():
    parser = argparse.ArgumentParser(
        description=f"Load {CONFIG_FILENAME} from a configuration repository",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Load from local checkout and print JSON
  python3 load-adoptium-pipeline-config-json.py --config-repo-dir ./ci-temurin-config

  # Load from remote and print a specific field
  python3 load-adoptium-pipeline-config-json.py \\
      --config-repo-url https://github.com/adoptium/ci-temurin-config.git \\
      --config-repo-branch main \\
      --field activeJdkVersions

  # Output as env vars for shell sourcing
  python3 load-adoptium-pipeline-config-json.py --config-repo-dir ./ci-temurin-config --format env
        """,
    )

    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--config-repo-dir", help="Local path to the configuration repository checkout"
    )
    source_group.add_argument(
        "--config-repo-url", help="Remote GitHub URL of the configuration repository"
    )

    parser.add_argument(
        "--config-repo-branch",
        default="main",
        help="Branch of the remote repository (default: main)",
    )
    parser.add_argument("--field", help="Output only a specific top-level field")
    parser.add_argument(
        "--format",
        choices=["json", "env", "summary"],
        default="json",
        help="Output format (default: json)",
    )

    args = parser.parse_args()

    # Load configuration
    if args.config_repo_dir:
        config = load_from_local(args.config_repo_dir)
    else:
        config = load_from_remote(args.config_repo_url, args.config_repo_branch)

    # Output
    if args.format == "env":
        output_env(config)
    elif args.format == "summary":
        output_summary(config)
    else:
        output_json(config, args.field)

    return 0


if __name__ == "__main__":
    sys.exit(main())
