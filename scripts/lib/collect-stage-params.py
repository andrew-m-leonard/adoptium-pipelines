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
collect-stage-params.py — CI-agnostic stage parameter collation helper.

Walks all *.params.json sidecar files from the default stage scripts directory
and optionally merges vendor overrides from a config-repo vendor-scripts
directory (fetched via raw GitHub URL or read from a local path).

Merge strategy per stage stem:
  1. Load scripts/stages/<stem>.params.json  → default parameter groups
  2. If a vendor file exists for the same stem:
       a. Remove any param named in ignoreDefaultParams from the defaults
       b. For each vendor param: replace default with same name, or add if new
       c. Merge vendor parameterGroups: groups with the same name are merged;
          new vendor groups are appended
       d. Vendor top-level metadata (stageDisabled, stageCondition,
          stageTimeoutMinutes) takes precedence over the defaults when present
  3. Also load optional vendor_stage_params.json (cross-stage extras,
     for params not tied to a specific script override)
  4. Cross-stage duplicate param names: both definitions MUST share the same
     Group name (error if not). The param is emitted once; the first
     description seen is kept and subsequent ones are ignored.

Stage-level metadata fields (top-level in each .params.json):
  stageDisabled   (boolean, default false)
    When true the stem is skipped entirely — no groups or parameters are
    emitted, and the stage will be excluded from the Jenkins job UI.
    Vendors may override this to true (disable a core stage) or false
    (re-enable an opt-in stage) in their vendor-scripts/<stem>.params.json.

  stageCondition  (array, default [])
    Each entry is { "param": "NAME", "value": <bool|string> }.  All
    conditions are ANDed.  The pipeline evaluates these at runtime to decide
    whether to execute the stage.  Every referenced param name must exist in
    the final collated paramNames set — the collator validates this and exits
    non-zero if a reference is dangling.

    String values may begin with "regex:" to trigger a regex match instead of
    a string equality check.  Example:
      { "param": "SOME_STRING_PARAM", "value": "regex:.*some-flag.*" }
    The collator validates that the pattern after "regex:" is a valid Python
    regex.  Both the Jenkins Groovy evaluator and the local Python runner
    honour this prefix.

  stageTimeoutMinutes (integer, optional, default 0 / not set)
    Optional wall-clock timeout in minutes for the stage. If set to > 0,
    pipelineHelper.executeStageWithTracking() enforces a timeout around the
    stage body. 0 or absent means no stage timeout is applied.

Output JSON (written to --output):
  {
    "stages": [
      {
        "stageId":             "03-internal-code-sign",
        "stageDisabled":       false,
        "stageCondition":      [{"param": "SIGN_ARTIFACTS", "value": true}],
        "stageTimeoutMinutes": 0
      },
      {
        "stageId":             "06-post-build-code-sign",
        "stageDisabled":       false,
        "stageCondition":      [{"param": "SIGN_ARTIFACTS", "value": true}],
        "stageTimeoutMinutes": 0
      },
      ...
    ],
    "groups": [
      {
        "name":        "Stage Selections",
        "description": "...",
        "stageIds":    ["03-internal-code-sign", "06-post-build-code-sign", ...],
        "parameters": [
          { "name": "RUN_TESTS", "type": "boolean", "default": true, "description": "..." },
          ...
        ]
      },
      ...
    ],
    "paramNames": ["RUN_TESTS", "AQA_REF", ...]
  }

  "stages" — one entry per non-disabled stage stem, in declaration order.
  Carries all per-stage metadata (stageCondition, stageDisabled,
  stageTimeoutMinutes).  Gate-only stages (no parameterGroups) appear here
  but produce no entry in "groups".

  "groups" — one entry per distinct group name, carrying the merged parameters
  from all contributing stage stems.  Every entry carries a "stageIds" list.
  Groups have no per-stage metadata fields.  "Stage Selections" is always first.

The output is consumed by CI-specific tooling (Jenkins Job DSL, local runner,
etc.) to construct job/pipeline parameters appropriate for that CI system.

Usage:
    # Local paths — used by the local CI runner and tests:
    python3 scripts/lib/collect-stage-params.py \\
        --default-stages-dir  scripts/stages \\
        --vendor-scripts-dir  config-repo/vendor-scripts \\
        --orchestrated-stages 01-initialize,02-build,12-validate-sbom,\\
13-smoke-tests,14-aqa-tests,20-reproducible-compare \\
        --output              /tmp/collated-stage-params.json

    # Remote vendor files — used by Jenkins Job DSL at job-generation time:
    python3 scripts/lib/collect-stage-params.py \\
        --default-stages-dir  scripts/stages \\
        --vendor-raw-base-url https://raw.githubusercontent.com/myorg/myrepo/main \\
        --orchestrated-stages 01-initialize,02-build,03-internal-code-sign,\\
04-assemble-images,06-post-build-code-sign,07-installer,08-code-sign-installer,\\
09-sbom-sign,10-digital-artifact-sign,11-verify-signing,12-validate-sbom,\\
13-smoke-tests,14-aqa-tests,15-tck-tests,16-publish,20-reproducible-compare \\
        --output              /tmp/collated-stage-params.json
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple  # Tuple used in all_param_names type

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Fixed job-level / pipeline built-in parameters that are always present in the
# pipeline environment and Jenkins job definitions (not emitted by stage sidecars),
# but are valid targets for stageCondition gates.
BUILTIN_PIPELINE_PARAMS: Set[str] = {
    "JDK_VERSION",
    "TARGET_OS",
    "ARCHITECTURE",
    "RELEASE_TYPE",
    "GROUP_UID",
    "CLEAN_WORKSPACE_AFTER_STAGE",
    "PIPELINE_TIMEOUT_HOURS",
}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

VALID_TYPES = {"string", "boolean"}


def _validate_param(param: dict, source: str) -> None:
    """Raise ValueError if a parameter entry is malformed."""
    name = param.get("name", "")
    if not name:
        raise ValueError(f"[{source}] Parameter entry missing 'name' field: {param}")
    if not name.isupper() or not all(c.isalnum() or c == "_" for c in name):
        raise ValueError(
            f"[{source}] Parameter name '{name}' must be UPPER_SNAKE_CASE "
            f"(uppercase letters, digits, and underscores only)"
        )
    ptype = param.get("type")
    if ptype not in VALID_TYPES:
        raise ValueError(
            f"[{source}] Parameter '{name}' has invalid type '{ptype}'. "
            f"Must be one of: {sorted(VALID_TYPES)}"
        )
    default = param.get("default")
    if ptype == "boolean" and not isinstance(default, bool):
        raise ValueError(
            f"[{source}] Parameter '{name}' is type 'boolean' but default "
            f"value {default!r} is not a JSON boolean (true/false)"
        )
    if ptype == "string" and not isinstance(default, str):
        raise ValueError(
            f"[{source}] Parameter '{name}' is type 'string' but default "
            f"value {default!r} is not a JSON string"
        )


def _validate_params_file(data: dict, source: str) -> None:
    """Validate a full .params.json document."""
    # parameterGroups is optional for gate-only files (stageCondition only)
    for group in data.get("parameterGroups") or []:
        if group is None:
            raise ValueError(f"[{source}] A parameterGroup entry is null (not allowed)")
        if "name" not in group:
            raise ValueError(f"[{source}] A parameterGroup entry is missing 'name'")
        for param in group.get("parameters") or []:
            if param is None:
                raise ValueError(
                    f"[{source}] A parameter entry in '{group['name']}' is null (not allowed)"
                )
            _validate_param(param, source)

    # Validate stageCondition entries if present
    for cond in data.get("stageCondition") or []:
        if cond is None:
            raise ValueError(f"[{source}] A stageCondition entry is null (not allowed)")
        if "param" not in cond:
            raise ValueError(
                f"[{source}] A stageCondition entry is missing 'param' field: {cond}"
            )
        if "value" not in cond:
            raise ValueError(
                f"[{source}] A stageCondition entry is missing 'value' field: {cond}"
            )
        # If the value is a string beginning with "regex:" validate the pattern.
        value = cond["value"]
        if isinstance(value, str) and value.startswith("regex:"):
            import re as _re

            pattern = value[len("regex:"):]
            try:
                _re.compile(pattern)
            except _re.error as exc:
                raise ValueError(
                    f"[{source}] stageCondition for param '{cond['param']}' has "
                    f"invalid regex pattern {pattern!r}: {exc}"
                )

    # Validate stageTimeoutMinutes if present
    if "stageTimeoutMinutes" in data and data["stageTimeoutMinutes"] is not None:
        timeout = data["stageTimeoutMinutes"]
        if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 0:
            raise ValueError(
                f"[{source}] 'stageTimeoutMinutes' must be a non-negative integer: {timeout!r}"
            )


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------


def _load_json_local(path: Path) -> Optional[dict]:
    """Load a JSON file from a local path. Returns None if the file does not exist."""
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_json_url(url: str) -> Optional[dict]:
    """Fetch and parse a JSON file from a URL. Returns None on 404, raises on other errors."""
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise RuntimeError(f"HTTP {e.code} fetching {url}: {e.reason}") from e
    except Exception as e:
        raise RuntimeError(f"Failed to fetch {url}: {e}") from e


# ---------------------------------------------------------------------------
# Per-stage data model
# ---------------------------------------------------------------------------


def _params_list_to_map(params: list) -> dict:
    """Convert a list of param dicts to an ordered dict keyed by name."""
    return {p["name"]: p for p in params}


class StageEntry:
    """
    Holds the fully-merged definition for one stage stem.

    Stage-level metadata (stageDisabled, stageCondition, stageTimeoutMinutes)
    is stored on the entry.  At flatten time the metadata goes into the
    stages list; groups carry only parameters.
    """

    __slots__ = ("stem", "disabled", "condition", "timeout", "groups")

    def __init__(self, stem: str) -> None:
        self.stem: str = stem
        self.disabled: bool = False
        self.condition: List[dict] = []
        self.timeout: int = 0
        # groups: ordered dict of group_name → {name, description, parameters: []}
        self.groups: Dict[str, dict] = {}

    def apply(self, data: dict, source: str) -> None:
        """
        Apply one .params.json document (default or vendor) onto this entry.

        Metadata fields use last-write-wins so that a vendor file calling this
        second will override the defaults.  parameterGroups are merged: groups
        with the same name have their parameters overlaid; new groups are appended.
        """
        _validate_params_file(data, source)

        if "stageDisabled" in data:
            self.disabled = bool(data["stageDisabled"])
        if "stageCondition" in data:
            self.condition = list(data["stageCondition"] or [])
        if "stageTimeoutMinutes" in data:
            self.timeout = int(data.get("stageTimeoutMinutes") or 0)

        ignore_set: Set[str] = set(data.get("ignoreDefaultParams") or [])

        # Validate ignoreDefaultParams: a name in both ignore and vendor params is contradictory
        vendor_param_names = {
            p["name"]
            for grp in (data.get("parameterGroups") or [])
            for p in (grp.get("parameters") or [])
        }
        contradictions = [n for n in ignore_set if n in vendor_param_names]
        if contradictions:
            raise ValueError(
                f"[{source}] These names appear in both 'ignoreDefaultParams' "
                f"and 'parameters' — contradictory intent: {contradictions}"
            )

        # Warn about ignore entries that don't exist in the current groups
        existing_params = {
            p["name"]
            for grp in self.groups.values()
            for p in grp["parameters"]
        }
        for name in ignore_set:
            if name not in existing_params:
                print(
                    f"WARNING [{source}] 'ignoreDefaultParams' entry '{name}' "
                    f"does not exist in the default params file — ignoring.",
                    file=sys.stderr,
                )

        # Remove ignored params from existing groups; drop the group if it becomes empty
        for name in ignore_set:
            for gname, grp in list(self.groups.items()):
                grp["parameters"] = [p for p in grp["parameters"] if p["name"] != name]
                if not grp["parameters"]:
                    del self.groups[gname]
                break  # each param name lives in at most one group

        # Merge parameterGroups from this document
        for vgrp in data.get("parameterGroups") or []:
            gname = vgrp["name"]
            vparams = list(vgrp.get("parameters") or [])
            if gname in self.groups:
                existing = self.groups[gname]
                existing_map = _params_list_to_map(existing["parameters"])
                existing_names = set(existing_map)
                for vp in vparams:
                    existing_map[vp["name"]] = vp
                new_additions = [vp for vp in vparams if vp["name"] not in existing_names]
                existing["parameters"] = (
                    [existing_map[p["name"]] for p in existing["parameters"]]
                    + new_additions
                )
                if vgrp.get("description"):
                    existing["description"] = vgrp["description"]
            else:
                self.groups[gname] = {
                    "name": gname,
                    "description": vgrp.get("description", ""),
                    "parameters": vparams,
                }

    def to_stage_entry(self) -> dict:
        """Return the stages-list entry for this stem."""
        return {
            "stageId": self.stem,
            "stageDisabled": self.disabled,
            "stageCondition": list(self.condition),
            "stageTimeoutMinutes": self.timeout,
        }


# ---------------------------------------------------------------------------
# stageCondition cross-reference validation
# ---------------------------------------------------------------------------


def _validate_stage_conditions(stages: List[dict], param_names: Set[str]) -> None:
    """
    Verify that every param name referenced in any stageCondition exists in
    the final collated paramNames set.  Raises ValueError listing all dangling
    references so they can be fixed in one pass.
    """
    errors: List[str] = []

    for stage in stages:
        stage_id = stage.get("stageId", "?")
        for cond in stage.get("stageCondition") or []:
            param = cond.get("param", "")
            if param not in param_names:
                errors.append(
                    f"  stageCondition in '{stage_id}' references unknown param '{param}'"
                )

    if errors:
        raise ValueError(
            "stageCondition validation failed — the following param references "
            "do not exist in the collated parameter set:\n" + "\n".join(errors)
        )


# ---------------------------------------------------------------------------
# Main collation
# ---------------------------------------------------------------------------


def collect(
    default_stages_dir: Path,
    vendor_scripts_dir: Optional[Path],
    vendor_raw_base_url: Optional[str],
    orchestrated_stages: Optional[Set[str]] = None,
) -> dict:
    """
    Collate stage *.params.json files into a single structured output dict.

    Two-pass design:
      Pass 1 — walk default_stages_dir and build a StageEntry per stem.
      Pass 2 — walk vendor_scripts_dir (or fetch remotely) and overlay each
               vendor file onto the matching StageEntry (creating one if the
               stem is vendor-only).

    When orchestrated_stages is provided only stems whose ID appears in that
    set are processed — all others are silently skipped.

    Returns:
        {
          "stages":     [ { stageId, stageDisabled, stageCondition,
                            stageTimeoutMinutes }, ... ],
          "groups":     [ { name, description, stageIds, parameters: [...] }, ... ],
          "paramNames": [ "PARAM_A", "PARAM_B", ... ]
        }
    """

    def load_vendor_stem(stem: str) -> Optional[dict]:
        filename = f"{stem}.params.json"
        if vendor_raw_base_url:
            url = f"{vendor_raw_base_url.rstrip('/')}/vendor-scripts/{filename}"
            return _load_json_url(url)
        if vendor_scripts_dir:
            return _load_json_local(vendor_scripts_dir / filename)
        return None

    def load_vendor_cross_stage() -> Optional[dict]:
        """Load optional vendor_stage_params.json from the config repo root."""
        filename = "vendor_stage_params.json"
        if vendor_raw_base_url:
            base = vendor_raw_base_url.rstrip("/")
            if base.endswith("/vendor-scripts"):
                base = base[: -len("/vendor-scripts")]
            return _load_json_url(f"{base}/{filename}")
        if vendor_scripts_dir:
            return _load_json_local(vendor_scripts_dir.parent / filename)
        return None

    def in_scope(stem: str) -> bool:
        return not orchestrated_stages or stem in orchestrated_stages

    # --- Pass 1: load default stage files ---
    # Preserve sorted (numeric-prefix) order; use an ordered dict to maintain it.
    entries: Dict[str, StageEntry] = {}

    for path in sorted(default_stages_dir.glob("*.params.json")):
        stem = path.name.replace(".params.json", "")
        if not in_scope(stem):
            continue
        entry = StageEntry(stem)
        entry.apply(_load_json_local(path), f"{stem}.params.json (default)")
        entries[stem] = entry

    # --- Pass 2: overlay vendor stage files ---
    # Collect vendor stems (may include vendor-only stems not in defaults).
    vendor_stems: List[str] = []
    if vendor_scripts_dir:
        for path in sorted(vendor_scripts_dir.glob("*.params.json")):
            stem = path.name.replace(".params.json", "")
            if in_scope(stem):
                vendor_stems.append(stem)
    elif vendor_raw_base_url:
        # When using a remote URL we don't have a directory listing; we can only
        # attempt to fetch the stems we already know about from the defaults.
        vendor_stems = list(entries.keys())

    for stem in vendor_stems:
        vendor_data = load_vendor_stem(stem)
        if vendor_data is None:
            continue
        if stem not in entries:
            entries[stem] = StageEntry(stem)
        entries[stem].apply(vendor_data, f"{stem}.params.json (vendor)")

    # --- Flatten: build stages list and merged groups map ---
    #
    # all_param_names: param name → (source_label, group_name, param_idx_in_group)
    #   where group_name is the key into groups_map.
    all_param_names: Dict[str, Tuple[str, str, int]] = {}
    # stages_list: one entry per non-disabled stem, in declaration order
    stages_list: List[dict] = []
    # groups_map: group_name → { name, description, stageIds, parameters }
    # Insertion order is preserved; "Stage Selections" is inserted first
    # whenever it is first encountered, keeping it at the front.
    groups_map: Dict[str, dict] = {}

    for stem, entry in entries.items():
        if entry.disabled:
            print(f"  [{stem}] stageDisabled=true — skipping (no parameters emitted)")
            continue

        # Always record the stage entry (metadata only).
        stages_list.append(entry.to_stage_entry())

        # Merge each group from this stem into groups_map.
        for gname, grp in entry.groups.items():
            params = list(grp["parameters"])
            if gname not in groups_map:
                groups_map[gname] = {
                    "name": gname,
                    "description": grp["description"],
                    "stageIds": [stem],
                    "parameters": [],
                }
            else:
                if stem not in groups_map[gname]["stageIds"]:
                    groups_map[gname]["stageIds"].append(stem)

            target = groups_map[gname]
            for p in params:
                source_label = f"{stem}/{gname}/{p['name']}"
                if p["name"] in all_param_names:
                    prev_label, prev_group, param_idx = all_param_names[p["name"]]
                    if gname != prev_group:
                        raise ValueError(
                            f"Parameter '{p['name']}' is defined in two different groups: "
                            f"'{prev_group}' (at '{prev_label}') and "
                            f"'{gname}' (at '{source_label}'). "
                            f"Duplicate parameters across stages must share the same Group name."
                        )
                    # Keep the first description seen; fill in if first was empty.
                    existing_param = groups_map[prev_group]["parameters"][param_idx]
                    if not existing_param.get("description"):
                        existing_param["description"] = p.get("description", "")
                    # stem is already recorded via stageIds above
                else:
                    all_param_names[p["name"]] = (
                        source_label,
                        gname,
                        len(target["parameters"]),
                    )
                    target["parameters"].append(p)

    # Ensure "Stage Selections" is first in the groups output if present.
    # Because we use an insertion-ordered dict and stages are processed in
    # sorted (numeric-prefix) order, the first stage that declares
    # "Stage Selections" will have inserted it first.  No reordering needed
    # unless a non-Stage-Selections group was somehow inserted before it —
    # which cannot happen with sorted stem processing.  Guard defensively:
    if "Stage Selections" in groups_map and next(iter(groups_map)) != "Stage Selections":
        sel = groups_map.pop("Stage Selections")
        groups_map = {"Stage Selections": sel, **groups_map}

    output_groups: List[dict] = list(groups_map.values())

    # --- Merge vendor_stage_params.json (cross-stage extras) ---
    cross_stage = load_vendor_cross_stage()
    if cross_stage:
        for stage_id, stage_entry in cross_stage.get("vendorStageParams", {}).items():
            ignore = stage_entry.get("ignoreDefaultParams") or []
            extra_params = stage_entry.get("parameters") or []
            source_label = f"vendor_stage_params.json/{stage_id}"

            # Remove ignored params from already-collated groups
            for name in ignore:
                found = False
                for grp in output_groups:
                    before = len(grp["parameters"])
                    grp["parameters"] = [p for p in grp["parameters"] if p["name"] != name]
                    if len(grp["parameters"]) < before:
                        found = True
                        # Remove from all_param_names so it's no longer tracked
                        all_param_names.pop(name, None)
                if not found:
                    print(
                        f"WARNING [{source_label}] 'ignoreDefaultParams' entry '{name}' "
                        f"not found in collated params for stage '{stage_id}' — ignoring.",
                        file=sys.stderr,
                    )

            if not extra_params:
                continue

            # Guard: name in both ignore and parameters is contradictory
            contradictions = [p["name"] for p in extra_params if p["name"] in ignore]
            if contradictions:
                raise ValueError(
                    f"[{source_label}] Names in both 'ignoreDefaultParams' and "
                    f"'parameters': {contradictions}"
                )

            for p in extra_params:
                _validate_param(p, source_label)

            # Fold into an existing 'Vendor Options' group, or create one
            if "Vendor Options" not in groups_map:
                groups_map["Vendor Options"] = {
                    "name": "Vendor Options",
                    "description": (
                        f"Additional parameters supplied via vendor_stage_params.json "
                        f"for stage {stage_id}."
                    ),
                    "stageIds": [stage_id],
                    "parameters": [],
                }
                output_groups = list(groups_map.values())
            target_group = groups_map["Vendor Options"]
            if stage_id not in target_group["stageIds"]:
                target_group["stageIds"].append(stage_id)

            existing_map = _params_list_to_map(target_group["parameters"])
            for p in extra_params:
                if p["name"] in all_param_names:
                    prev_label = all_param_names[p["name"]][0]
                    print(
                        f"WARNING: Parameter '{p['name']}' from vendor_stage_params.json "
                        f"already defined at '{prev_label}' — "
                        f"vendor_stage_params.json definition wins.",
                        file=sys.stderr,
                    )
                all_param_names[p["name"]] = (
                    f"{source_label}/{p['name']}",
                    "Vendor Options",
                    -1,
                )
                existing_map[p["name"]] = p
            target_group["parameters"] = list(existing_map.values())

    # --- Validate stageCondition cross-references ---
    all_collated_param_names: Set[str] = set(BUILTIN_PIPELINE_PARAMS)
    for grp in output_groups:
        for p in grp["parameters"]:
            all_collated_param_names.add(p["name"])

    _validate_stage_conditions(stages_list, all_collated_param_names)

    # --- Build flat ordered param name list ---
    param_names_ordered: List[str] = []
    seen_names: Set[str] = set()
    for grp in output_groups:
        for p in grp["parameters"]:
            if p["name"] not in seen_names:
                param_names_ordered.append(p["name"])
                seen_names.add(p["name"])

    return {
        "stages": stages_list,
        "groups": output_groups,
        "paramNames": param_names_ordered,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CI-agnostic collation of stage *.params.json files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Local paths (local CI runner, tests):
  python3 scripts/lib/collect-stage-params.py \\
      --default-stages-dir scripts/stages \\
      --vendor-scripts-dir config-repo/vendor-scripts \\
      --output /tmp/collated-stage-params.json

  # Remote vendor files (Jenkins Job DSL at job-generation time):
  python3 scripts/lib/collect-stage-params.py \\
      --default-stages-dir scripts/stages \\
      --vendor-raw-base-url https://raw.githubusercontent.com/myorg/myrepo/main \\
      --output /tmp/collated-stage-params.json
        """,
    )
    parser.add_argument(
        "--default-stages-dir",
        required=True,
        help="Path to the directory containing default *.params.json files (scripts/stages)",
    )
    parser.add_argument(
        "--vendor-scripts-dir",
        default=None,
        help="Local path to vendor-scripts directory inside a checked-out config repo",
    )
    parser.add_argument(
        "--vendor-raw-base-url",
        default=None,
        help=(
            "Base raw URL of the config repo "
            "(e.g. https://raw.githubusercontent.com/org/repo/branch). "
            "Used to fetch vendor-scripts/*.params.json and vendor_stage_params.json remotely."
        ),
    )
    parser.add_argument(
        "--orchestrated-stages",
        default=None,
        help=(
            "Comma-separated list of stage IDs to include (e.g. "
            '"01-initialize,02-build,14-aqa-tests"). '
            "Stems not in this list are silently skipped. "
            "Omit to process all discovered stems."
        ),
    )
    parser.add_argument(
        "--output", required=True, help="Path to write the collated output JSON"
    )
    args = parser.parse_args()

    if args.vendor_scripts_dir and args.vendor_raw_base_url:
        print(
            "ERROR: --vendor-scripts-dir and --vendor-raw-base-url are mutually exclusive.",
            file=sys.stderr,
        )
        return 1

    default_dir = Path(args.default_stages_dir)
    if not default_dir.is_dir():
        print(
            f"ERROR: --default-stages-dir '{default_dir}' is not a directory.",
            file=sys.stderr,
        )
        return 1

    vendor_dir = Path(args.vendor_scripts_dir) if args.vendor_scripts_dir else None

    orchestrated: Optional[Set[str]] = None
    if args.orchestrated_stages:
        orchestrated = {
            s.strip() for s in args.orchestrated_stages.split(",") if s.strip()
        }

    try:
        result = collect(
            default_stages_dir=default_dir,
            vendor_scripts_dir=vendor_dir,
            vendor_raw_base_url=args.vendor_raw_base_url,
            orchestrated_stages=orchestrated,
        )
    except (ValueError, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    total_params = len(result["paramNames"])
    total_groups = len(result["groups"])
    total_stages = len(result["stages"])
    print(
        f"✓ Collated {total_params} parameter(s) across "
        f"{total_groups} group(s) in {total_stages} stage(s) → {output_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
