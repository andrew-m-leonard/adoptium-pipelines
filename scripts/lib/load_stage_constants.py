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
load-stage-constants.py — parse stage-constants.properties + vendor-constants.properties.

Mirrors the behaviour of scripts/lib/load-stage-constants.sh for Python consumers.
Reads scripts/stages/stage-constants.properties (core defaults) and, when
config-repo/vendor-scripts/vendor-constants.properties exists, overlays vendor
values on top.

Usage:
    import sys
    sys.path.insert(0, "/path/to/ci-adoptium-pipelines/scripts/lib")
    from load_stage_constants import load_stage_constants

    constants = load_stage_constants(script_dir, config_repo_root)
    build_output_dir = constants["BUILD_OUTPUT_DIR"]   # KeyError if missing — config error
"""

from pathlib import Path


def _parse_properties(path: Path) -> dict:
    """Parse a Java-style .properties file; returns key → value dict."""
    result: dict = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        if key and all(c.isalnum() or c == "_" for c in key):
            result[key] = value.strip()
    return result


def load_stage_constants(
    script_dir: Path,
    config_repo_root=None,
) -> dict:
    """
    Load merged stage constants from core + optional vendor properties files.

    Args:
        script_dir:       Root of the ci-adoptium-pipelines checkout.
        config_repo_root: Path to the checked-out config repo, or None.

    Returns:
        Dict of constant name → value, vendor values overriding core defaults.
    """
    constants = _parse_properties(
        script_dir / "scripts" / "stages" / "stage-constants.properties"
    )
    if config_repo_root:
        vendor_props = (
            Path(config_repo_root) / "vendor-scripts" / "vendor-constants.properties"
        )
        constants.update(_parse_properties(vendor_props))
    return constants
