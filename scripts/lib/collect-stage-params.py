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

Output JSON (written to --output):
  {
    "groups": [
      {
        "name":           "Stage Selections",
        "description":    "...",
        "stageId":        "03-internal-code-sign",
        "stageIds":       ["03-internal-code-sign", "07-installer", "14-aqa-tests", ...],
        "stageDisabled":  false,
        "stageCondition": [],
        "parameters": [
          { "name": "RUN_TESTS", "type": "boolean", "default": true, "description": "..." },
          ...
        ]
      },
      ...
    ],
    "paramNames": ["RUN_TESTS", "AQA_REF", ...]
  }

  Note: Priority groups (e.g. "Stage Selections") are merged from all contributing
  stage stems and carry a "stageIds" list with every contributing stage ID.
  Non-priority groups carry only "stageId" (the single owning stage).
  Groovy consumers should prefer "stageIds" and fall back to ["stageId"].

Priority group ordering:
  Groups whose names appear in PRIORITY_GROUPS are moved to the front of the
  collated output (in the order listed), with all other groups following in
  their natural discovery order.  This ensures "Stage Selections" always
  appears first in the Jenkins Build Parameters UI.

The output is consumed by CI-specific tooling (Jenkins Job DSL, local runner,
etc.) to construct job/pipeline parameters appropriate for that CI system.

Usage:
    # Local paths — used by the local CI runner and tests:
    python3 scripts/lib/collect-stage-params.py \\
        --default-stages-dir  scripts/stages \\
        --vendor-scripts-dir  config-repo/vendor-scripts \\
        --orchestrated-stages 01-initialize,02-build,12-validate-sbom,13-smoke-tests,14-aqa-tests,20-reproducible-compare \\
        --output              /tmp/collated-stage-params.json

    # Remote vendor files — used by Jenkins Job DSL at job-generation time:
    python3 scripts/lib/collect-stage-params.py \\
        --default-stages-dir  scripts/stages \\
        --vendor-raw-base-url https://raw.githubusercontent.com/myorg/myrepo/main \\
        --orchestrated-stages 01-initialize,02-build,03-internal-code-sign,04-assemble-images,06-post-build-code-sign,07-installer,08-code-sign-installer,09-sbom-sign,10-digital-artifact-sign,11-verify-signing,12-validate-sbom,13-smoke-tests,14-aqa-tests,15-tck-tests,16-publish,20-reproducible-compare \\
        --output              /tmp/collated-stage-params.json
"""

import argparse
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

# ---------------------------------------------------------------------------
# Priority group ordering
# ---------------------------------------------------------------------------

# Groups whose names appear here are moved to the front of the collated output,
# in the order listed.  All other groups follow in natural discovery order.
# Add entries here only when a group must always appear first in the Jenkins UI.
PRIORITY_GROUPS: list[str] = ["Stage Selections"]


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

            pattern = value[len("regex:") :]
            try:
                _re.compile(pattern)
            except _re.error as exc:
                raise ValueError(
                    f"[{source}] stageCondition for param '{cond['param']}' has "
                    f"invalid regex pattern {pattern!r}: {exc}"
                )


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------


def _load_json_local(path: Path) -> dict | None:
    """Load a JSON file from a local path. Returns None if the file does not exist."""
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_json_url(url: str) -> dict | None:
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
# Per-stage merge logic
# ---------------------------------------------------------------------------


def _params_list_to_map(params: list) -> dict:
    """Convert a list of param dicts to a dict keyed by name, preserving order."""
    return {p["name"]: p for p in params}


def _resolve_stage_disabled(
    default_data: dict | None, vendor_data: dict | None
) -> bool:
    """
    Resolve the effective stageDisabled value after vendor overlay.

    Vendor data takes precedence if it explicitly sets stageDisabled.
    Falls back to default_data, then False.
    """
    if vendor_data is not None and "stageDisabled" in vendor_data:
        return bool(vendor_data["stageDisabled"])
    if default_data is not None and "stageDisabled" in default_data:
        return bool(default_data["stageDisabled"])
    return False


def _resolve_stage_condition(
    default_data: dict | None, vendor_data: dict | None
) -> list:
    """
    Resolve the effective stageCondition list after vendor overlay.

    Vendor data takes precedence if it explicitly sets stageCondition.
    Falls back to default_data, then [].
    """
    if vendor_data is not None and "stageCondition" in vendor_data:
        return list(vendor_data["stageCondition"] or [])
    if default_data is not None and "stageCondition" in default_data:
        return list(default_data["stageCondition"] or [])
    return []


def _merge_stage(
    default_data: dict | None, vendor_data: dict | None, stage_stem: str
) -> list:
    """
    Merge default and vendor parameterGroups for one stage stem.

    Returns a list of group dicts, each containing:
      name, description, stageId, stageDisabled, stageCondition, parameters
    """
    source_default = f"{stage_stem}.params.json (default)"
    source_vendor = f"{stage_stem}.params.json (vendor)"

    if default_data:
        _validate_params_file(default_data, source_default)
    if vendor_data:
        _validate_params_file(vendor_data, source_vendor)

    stage_disabled = _resolve_stage_disabled(default_data, vendor_data)
    stage_condition = _resolve_stage_condition(default_data, vendor_data)

    # Build the default group map: group_name → group dict
    # and a reverse index: param_name → group_name
    default_groups: dict[str, dict] = {}
    default_param_to_group: dict[str, str] = {}

    if default_data:
        for grp in default_data.get("parameterGroups") or []:
            gname = grp["name"]
            default_groups[gname] = {
                "name": gname,
                "description": grp.get("description", ""),
                "stageId": stage_stem,
                "stageDisabled": stage_disabled,
                "stageCondition": stage_condition,
                "parameters": list(grp.get("parameters") or []),
            }
            for p in grp.get("parameters") or []:
                default_param_to_group[p["name"]] = gname

    if not vendor_data:
        return list(default_groups.values())

    # --- Apply ignoreDefaultParams ---
    ignore_list = vendor_data.get("ignoreDefaultParams") or []

    # A name in both ignoreDefaultParams and vendor parameters is contradictory — hard error
    vendor_param_names = {
        p["name"]
        for grp in (vendor_data.get("parameterGroups") or [])
        for p in (grp.get("parameters") or [])
    }
    contradictions = [n for n in ignore_list if n in vendor_param_names]
    if contradictions:
        raise ValueError(
            f"[{source_vendor}] These names appear in both 'ignoreDefaultParams' "
            f"and 'parameters' — contradictory intent: {contradictions}"
        )

    # A name in ignoreDefaultParams that doesn't exist in defaults is a warning, not an error
    for name in ignore_list:
        if name not in default_param_to_group:
            print(
                f"WARNING [{source_vendor}] 'ignoreDefaultParams' entry '{name}' "
                f"does not exist in the default params file — ignoring.",
                file=sys.stderr,
            )

    # Remove ignored params from their default groups; drop the group if now empty
    for name in ignore_list:
        gname = default_param_to_group.get(name)
        if gname and gname in default_groups:
            default_groups[gname]["parameters"] = [
                p for p in default_groups[gname]["parameters"] if p["name"] != name
            ]
            if not default_groups[gname]["parameters"]:
                del default_groups[gname]

    # --- Merge vendor parameterGroups ---
    for vgrp in vendor_data.get("parameterGroups") or []:
        vgname = vgrp["name"]
        vparams = vgrp.get("parameters") or []

        if vgname in default_groups:
            # Vendor params replace defaults with the same name; new names are appended
            existing_map = _params_list_to_map(default_groups[vgname]["parameters"])
            existing_names = set(existing_map)
            for vp in vparams:
                existing_map[vp["name"]] = vp
            new_additions = [vp for vp in vparams if vp["name"] not in existing_names]
            default_groups[vgname]["parameters"] = [
                existing_map[p["name"]] for p in default_groups[vgname]["parameters"]
            ] + new_additions
            # Vendor may also update the group description
            if vgrp.get("description"):
                default_groups[vgname]["description"] = vgrp["description"]
        else:
            # Brand-new vendor group — append it
            default_groups[vgname] = {
                "name": vgname,
                "description": vgrp.get("description", ""),
                "stageId": stage_stem,
                "stageDisabled": stage_disabled,
                "stageCondition": stage_condition,
                "parameters": list(vparams),
            }

    # Propagate updated stage_disabled / stage_condition to all groups
    # (vendor override may have changed them)
    for grp in default_groups.values():
        grp["stageDisabled"] = stage_disabled
        grp["stageCondition"] = stage_condition

    return list(default_groups.values())


# ---------------------------------------------------------------------------
# Priority group reordering
# ---------------------------------------------------------------------------


def _reorder_by_priority(groups: list[dict]) -> list[dict]:
    """
    Move groups whose names appear in PRIORITY_GROUPS to the front of the list,
    merging all groups that share a priority name into a single entry.

    When multiple stage params.json files declare the same group name (e.g. all
    stage-gate booleans live in "Stage Selections"), the collation loop emits one
    group per stage stem.  This function merges them into one group so that all
    Stage Selections parameters appear under a single UI separator, then places
    that merged group at the front.

    Non-priority groups follow in their original relative order.

    Groups in PRIORITY_GROUPS that are absent from the collated output are
    silently skipped (no error — a disabled stage may have removed them).

    The internal '_extra_stage_ids' set (populated by the collation loop for
    stems that contributed only duplicate params) is folded into 'stageIds' here
    and then stripped from the output.
    """
    priority_set = set(PRIORITY_GROUPS)
    # priority_map: group name → merged group dict
    priority_map: dict[str, dict] = {}
    remainder: list[dict] = []

    for grp in groups:
        name = grp["name"]
        # Collect all stems that contributed to this group: the primary stageId
        # plus any stems recorded in the internal _extra_stage_ids accumulator.
        extra_ids: set[str] = grp.pop("_extra_stage_ids", set()) or set()
        all_ids: list[str] = []
        primary = grp.get("stageId", "")
        if primary:
            all_ids.append(primary)
        for eid in sorted(extra_ids):
            if eid not in all_ids:
                all_ids.append(eid)

        if name in priority_set:
            if name not in priority_map:
                # First occurrence — seed the merged group.
                # Keep 'stageId' (the first stem) for backward compatibility with any
                # consumer that reads the singular field; also emit 'stageIds' (a list
                # of all contributing stems) so Groovy can build the full label.
                priority_map[name] = {
                    "name": name,
                    "description": grp.get("description", ""),
                    "stageId": primary,
                    "stageIds": list(all_ids),
                    "stageDisabled": grp.get("stageDisabled", False),
                    "stageCondition": list(grp.get("stageCondition") or []),
                    "parameters": list(grp.get("parameters") or []),
                }
            else:
                # Subsequent occurrence — accumulate stageIds and merge parameters
                for sid in all_ids:
                    if sid and sid not in priority_map[name]["stageIds"]:
                        priority_map[name]["stageIds"].append(sid)
                existing_names = {p["name"] for p in priority_map[name]["parameters"]}
                for p in grp.get("parameters") or []:
                    if p["name"] not in existing_names:
                        priority_map[name]["parameters"].append(p)
                        existing_names.add(p["name"])
        else:
            # Non-priority group: strip the internal field, expose extra stageIds
            # as a plain list if any were recorded (for completeness).
            if all_ids and len(all_ids) > 1:
                grp["stageIds"] = all_ids
            remainder.append(grp)

    front = [priority_map[name] for name in PRIORITY_GROUPS if name in priority_map]
    return front + remainder


# ---------------------------------------------------------------------------
# stageCondition cross-reference validation
# ---------------------------------------------------------------------------


def _validate_stage_conditions(groups: list[dict], param_names: set[str]) -> None:
    """
    Verify that every param name referenced in any stageCondition exists in
    the final collated paramNames set.  Raises ValueError listing all dangling
    references so they can be fixed in one pass.
    """
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()  # (stageId, param) — avoid duplicate messages

    for grp in groups:
        stage_id = grp.get("stageId", "?")
        conditions = grp.get("stageCondition") or []
        for cond in conditions:
            param = cond.get("param", "")
            key = (stage_id, param)
            if key in seen:
                continue
            seen.add(key)
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
    vendor_scripts_dir: Path | None,
    vendor_raw_base_url: str | None,
    orchestrated_stages: set[str] | None = None,
) -> dict:
    """
    Collate stage *.params.json files into a single structured output dict.

    When orchestrated_stages is provided only stems whose ID appears in that
    set are processed — all others are silently skipped.  This lets each CI
    orchestrator (local runner, Jenkins launch job, seed job) restrict the
    collated output to exactly the stages it actually runs, preventing
    parameters from CI-only stages (e.g. code-signing) from leaking into
    contexts where those stages are not executed.

    Returns:
        {
          "groups":     [ { name, description, stageId, stageDisabled,
                            stageCondition, parameters: [...] }, ... ],
          "paramNames": [ "PARAM_A", "PARAM_B", ... ]
        }

    Groups are reordered so that any group named in PRIORITY_GROUPS appears
    first (in PRIORITY_GROUPS order), followed by all remaining groups in
    natural discovery order.
    """

    def load_vendor_stem(stem: str) -> dict | None:
        filename = f"{stem}.params.json"
        if vendor_raw_base_url:
            url = f"{vendor_raw_base_url.rstrip('/')}/vendor-scripts/{filename}"
            return _load_json_url(url)
        if vendor_scripts_dir:
            return _load_json_local(vendor_scripts_dir / filename)
        return None

    def load_vendor_cross_stage() -> dict | None:
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

    # Collect stage stems from default params files, preserving sort order.
    # When orchestrated_stages is set, skip any stem not in that allowlist.
    stems_seen: list[str] = []
    stems_set: set[str] = set()

    for path in sorted(default_stages_dir.glob("*.params.json")):
        stem = path.name.replace(".params.json", "")
        if orchestrated_stages and stem not in orchestrated_stages:
            continue
        if stem not in stems_set:
            stems_seen.append(stem)
            stems_set.add(stem)

    # Also pick up vendor-only stems (vendor script stages with no default params file)
    if vendor_scripts_dir:
        for path in sorted(vendor_scripts_dir.glob("*.params.json")):
            stem = path.name.replace(".params.json", "")
            if orchestrated_stages and stem not in orchestrated_stages:
                continue
            if stem not in stems_set:
                stems_seen.append(stem)
                stems_set.add(stem)

    # Track all param names for cross-stage deduplication.
    # Maps param name → (source_label, group_name, index into output_groups, index in parameters)
    all_param_names: dict[str, tuple[str, str, int, int]] = {}
    output_groups: list[dict] = []
    # Track stageConditions for ALL non-disabled stems (including gate-only files
    # that have no parameterGroups) so the cross-reference validator covers them too.
    all_stage_conditions: dict[str, list[dict]] = {}

    for stem in stems_seen:
        default_data = _load_json_local(default_stages_dir / f"{stem}.params.json")
        vendor_data = load_vendor_stem(stem)

        if default_data is None and vendor_data is None:
            continue

        # Resolve stageDisabled before doing any further work on this stem
        stage_disabled = _resolve_stage_disabled(default_data, vendor_data)
        if stage_disabled:
            print(f"  [{stem}] stageDisabled=true — skipping (no parameters emitted)")
            continue

        # Track stageCondition for gate-only stems (no parameterGroups) so the
        # cross-reference validator can still check their param references.
        stage_condition = _resolve_stage_condition(default_data, vendor_data)
        if stage_condition:
            all_stage_conditions.setdefault(stem, [])
            seen = {c["param"] for c in all_stage_conditions[stem] if c is not None}
            for c in stage_condition:
                if c is not None and c.get("param") and c["param"] not in seen:
                    all_stage_conditions[stem].append(c)
                    seen.add(c["param"])

        merged_groups = _merge_stage(default_data, vendor_data, stem)

        for grp in merged_groups:
            clean_params = []
            for p in grp["parameters"]:
                source_label = f"{stem}/{grp['name']}/{p['name']}"
                if p["name"] in all_param_names:
                    prev_label, prev_group, grp_idx, param_idx = all_param_names[
                        p["name"]
                    ]
                    # Both definitions must belong to the same Group name
                    if grp["name"] != prev_group:
                        raise ValueError(
                            f"Parameter '{p['name']}' is defined in two different groups: "
                            f"'{prev_group}' (at '{prev_label}') and "
                            f"'{grp['name']}' (at '{source_label}'). "
                            f"Duplicate parameters across stages must share the same Group name."
                        )
                    # Keep the first description seen — subsequent definitions
                    # from other stages are ignored for brevity.
                    existing_param = output_groups[grp_idx]["parameters"][param_idx]
                    if not existing_param.get("description"):
                        existing_param["description"] = p.get("description", "")
                    # Record this stem as a contributor to the existing group even
                    # though it emitted no new params (needed for stageIds tracking).
                    existing_grp = output_groups[grp_idx]
                    existing_grp.setdefault("_extra_stage_ids", set()).add(stem)
                    # Skip — do not re-emit this param
                    continue
                all_param_names[p["name"]] = (
                    source_label,
                    grp["name"],
                    len(output_groups),
                    len(clean_params),
                )
                clean_params.append(p)

            if clean_params:
                output_groups.append(
                    {
                        "name": grp["name"],
                        "description": grp["description"],
                        "stageId": grp["stageId"],
                        "stageDisabled": grp["stageDisabled"],
                        "stageCondition": grp["stageCondition"],
                        "parameters": clean_params,
                    }
                )

    # --- Merge vendor_stage_params.json (cross-stage extras) ---
    cross_stage = load_vendor_cross_stage()
    if cross_stage:
        for stage_id, stage_entry in cross_stage.get("vendorStageParams", {}).items():
            ignore = stage_entry.get("ignoreDefaultParams") or []
            extra_params = stage_entry.get("parameters") or []
            source_label = f"vendor_stage_params.json/{stage_id}"

            # Remove ignored params from already-collated groups for this stage
            for name in ignore:
                found = False
                for grp in output_groups:
                    if grp["stageId"] == stage_id:
                        before = len(grp["parameters"])
                        grp["parameters"] = [
                            p for p in grp["parameters"] if p["name"] != name
                        ]
                        if len(grp["parameters"]) < before:
                            found = True
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

            # Fold into an existing 'Vendor Options' group for this stage, or create one
            target_group = next(
                (
                    g
                    for g in output_groups
                    if g["stageId"] == stage_id and g["name"] == "Vendor Options"
                ),
                None,
            )
            if target_group is None:
                target_group = {
                    "name": "Vendor Options",
                    "description": (
                        f"Additional parameters supplied via vendor_stage_params.json "
                        f"for stage {stage_id}."
                    ),
                    "stageId": stage_id,
                    "stageDisabled": False,
                    "stageCondition": [],
                    "parameters": [],
                }
                output_groups.append(target_group)

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
                    -1,
                )
                existing_map[p["name"]] = p
            target_group["parameters"] = list(existing_map.values())

    # --- Apply priority group ordering ---
    output_groups = _reorder_by_priority(output_groups)

    # --- Validate stageCondition cross-references ---
    # Build the full param name set from the reordered output groups
    all_collated_param_names: set[str] = set()
    for grp in output_groups:
        for p in grp["parameters"]:
            all_collated_param_names.add(p["name"])

    # Build a synthetic groups list that includes gate-only stems (no parameterGroups)
    # so their stageCondition references are also validated.
    # After _reorder_by_priority, priority groups carry 'stageIds' (list) instead of 'stageId';
    # check both when deciding whether a stem already has a real group in the output.
    def _stem_in_output(stage_id: str) -> bool:
        for grp in output_groups:
            if "stageIds" in grp:
                if stage_id in grp["stageIds"]:
                    return True
            elif grp.get("stageId") == stage_id:
                return True
        return False

    gate_only_groups = [
        {"stageId": stage_id, "stageCondition": conds, "parameters": []}
        for stage_id, conds in all_stage_conditions.items()
        if not _stem_in_output(stage_id)
    ]
    _validate_stage_conditions(
        output_groups + gate_only_groups, all_collated_param_names
    )

    # Build flat ordered param name list
    param_names_ordered: list[str] = []
    seen_names: set[str] = set()
    for grp in output_groups:
        for p in grp["parameters"]:
            if p["name"] not in seen_names:
                param_names_ordered.append(p["name"])
                seen_names.add(p["name"])

    return {
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

    orchestrated: set[str] | None = None
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
    print(
        f"✓ Collated {total_params} parameter(s) across "
        f"{total_groups} group(s) → {output_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
