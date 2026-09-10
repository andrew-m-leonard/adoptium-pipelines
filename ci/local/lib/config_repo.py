#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
Configuration repository helpers for the local pipeline runner.

Provides:
  - sync_config_repo()                  — clone or update the config repo
  - load_adoptium_pipeline_config()     — read adoptium_pipeline_config.json
"""

import json
import subprocess
from pathlib import Path


def sync_config_repo(
    workspace: Path, config_repo_url: str, config_repo_branch: str
) -> Path:
    """
    Ensure the configuration repository is cloned and up-to-date.

    If the directory already exists and its remote origin matches
    *config_repo_url*, a shallow fetch + hard-reset is performed so the
    workspace always reflects the tip of *config_repo_branch*.

    If the existing clone's remote origin does NOT match *config_repo_url*
    a RuntimeError is raised — the caller must re-run with --clean-workspace
    to resolve the conflict.

    If the directory does not exist, a fresh shallow clone is performed.

    Args:
        workspace:          Pipeline workspace root (config-repo/ is placed here).
        config_repo_url:    Remote URL of the configuration repository.
        config_repo_branch: Branch to clone/fetch.

    Returns:
        Path to the cloned config-repo directory.

    Raises:
        RuntimeError: On git errors or URL mismatch.
    """
    config_repo_dir = workspace / "config-repo"

    if config_repo_dir.exists():
        # Verify the existing clone's remote origin matches the requested URL.
        try:
            url_result = subprocess.run(
                ["git", "-C", str(config_repo_dir), "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                check=True,
            )
            existing_url = url_result.stdout.strip()
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"Could not determine remote URL of existing config-repo at "
                f"{config_repo_dir}: {e.stderr.strip()}"
            ) from e

        if existing_url != config_repo_url:
            raise RuntimeError(
                f"ERROR: Existing config-repo remote URL does not match --config-repo-url.\n"
                f"\n"
                f"  Existing:  {existing_url}\n"
                f"  Requested: {config_repo_url}\n"
                f"\n"
                f"Use --clean-workspace to remove the existing workspace and re-clone "
                f"from the requested URL.\n"
            )

        # Same repo — fetch latest and reset to the requested branch tip.
        print(f"ℹ️  Configuration repository already exists: {config_repo_dir}")
        print(f"   Fetching latest from origin/{config_repo_branch}...")
        try:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(config_repo_dir),
                    "fetch",
                    "--depth",
                    "1",
                    "origin",
                    config_repo_branch,
                ],
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(config_repo_dir),
                    "reset",
                    "--hard",
                    f"origin/{config_repo_branch}",
                ],
                check=True,
            )
            print("✅ Configuration repository updated to latest")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to update config-repo from remote: {e}") from e

    else:
        print("📥 Cloning configuration repository...")
        print(f"   URL: {config_repo_url}")
        print(f"   Branch: {config_repo_branch}")
        subprocess.run(
            [
                "git",
                "clone",
                "--branch",
                config_repo_branch,
                "--depth",
                "1",
                config_repo_url,
                str(config_repo_dir),
            ],
            check=True,
        )
        print("✅ Configuration repository cloned")

    return config_repo_dir


def load_adoptium_pipeline_config(config_repo_dir: Path) -> dict:
    """
    Load adoptium_pipeline_config.json from the config repo directory.

    Args:
        config_repo_dir: Root of the cloned configuration repository.

    Returns:
        Parsed JSON dict, or an empty dict if the file does not exist.
    """
    cfg_path = config_repo_dir / "adoptium_pipeline_config.json"
    if not cfg_path.exists():
        print(
            "ℹ️  adoptium_pipeline_config.json not found in config repo — using defaults"
        )
        return {}

    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    print("✅ Loaded adoptium_pipeline_config.json")
    print(f"   Default variant: {cfg.get('defaultVariant', 'temurin')}")
    active = [
        v["version"] for v in cfg.get("activeJdkVersions", []) if v.get("enabled")
    ]
    if active:
        print(f"   Active JDK versions: {', '.join(active)}")
    return cfg
