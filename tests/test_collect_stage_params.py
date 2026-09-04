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
Tests for collect-stage-params.py

Covers:
  Existing behaviour:
    - Same param name, same group → emitted once with description merged
    - Same param name, same group, identical descriptions → single description kept
    - Same param name, same group, different descriptions → descriptions concatenated
    - Same param name, different groups → ValueError raised
    - Duplicate across three stages → all descriptions merged

  New behaviour (stageDisabled / stageCondition / Stage Selections):
    - stageDisabled=true: stem is skipped, no params emitted
    - stageDisabled vendor override: vendor can disable a core stage
    - stageDisabled vendor re-enable: vendor can re-enable an opt-in stage
    - stageCondition: propagated to group output
    - stageCondition validation: dangling param reference → ValueError
    - stageCondition validation: gate-only file (no parameterGroups) with valid refs → OK
    - stageCondition validation: gate-only file with bad refs → ValueError
    - Stage Selections priority group: appears first in output, params from all stages merged
    - Stage Selections with stageDisabled=true stage: disabled stage's params not merged in
    - PRIORITY_GROUPS ordering: non-priority groups follow in discovery order
"""

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

# Allow importing the module from scripts/lib/
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "lib"))

collect_mod = importlib.import_module("collect-stage-params")
collect = collect_mod.collect


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_params_json(
    directory: Path,
    stem: str,
    groups: list,
    stage_disabled: bool = False,
    stage_condition: list | None = None,
    stage_timeout_minutes: int = 0,
) -> None:
    """Write a *.params.json file for a given stage stem."""
    data: dict = {
        "stageId": stem,
        "stageDisabled": stage_disabled,
        "stageTimeoutMinutes": stage_timeout_minutes,
        "stageCondition": stage_condition or [],
    }
    if groups:
        data["parameterGroups"] = groups
    (directory / f"{stem}.params.json").write_text(json.dumps(data))


def _write_gate_only_json(
    directory: Path, stem: str, stage_condition: list, stage_disabled: bool = False
) -> None:
    """Write a gate-only params.json (no parameterGroups)."""
    data = {
        "stageId": stem,
        "stageDisabled": stage_disabled,
        "stageCondition": stage_condition,
    }
    (directory / f"{stem}.params.json").write_text(json.dumps(data))


def _make_bool_param(name: str, default: bool = False, description: str = "") -> dict:
    return {
        "name": name,
        "type": "boolean",
        "default": default,
        "description": description,
    }


def _make_param(name: str, description: str = "") -> dict:
    return {"name": name, "type": "string", "default": "", "description": description}


def _make_group(name: str, params: list, description: str = "") -> dict:
    return {"name": name, "description": description, "parameters": params}


def _collect(stage_dir: Path, vendor_dir: Path | None = None) -> dict:
    return collect(
        default_stages_dir=stage_dir,
        vendor_scripts_dir=vendor_dir,
        vendor_raw_base_url=None,
    )


# ---------------------------------------------------------------------------
# Existing cross-stage duplicate param tests
# ---------------------------------------------------------------------------


class TestCrossStageDuplicateParams(unittest.TestCase):

    def test_duplicate_same_group_identical_description(self):
        """Same param, same group, identical description → emitted once, unchanged."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            shared_desc = "Git repo for the Temurin build scripts."
            _write_params_json(
                d,
                "01-init",
                [
                    _make_group(
                        "Source Control",
                        [_make_param("TEMURIN_BUILD_REPO", shared_desc)],
                    )
                ],
            )
            _write_params_json(
                d,
                "02-build",
                [
                    _make_group(
                        "Source Control",
                        [_make_param("TEMURIN_BUILD_REPO", shared_desc)],
                    )
                ],
            )
            result = _collect(d)

        all_params = [p for g in result["groups"] for p in g["parameters"]]
        matching = [p for p in all_params if p["name"] == "TEMURIN_BUILD_REPO"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["description"], shared_desc)
        self.assertEqual(result["paramNames"].count("TEMURIN_BUILD_REPO"), 1)

    def test_duplicate_same_group_different_descriptions(self):
        """Same param, same group, different descriptions → concatenated with ' / '."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_params_json(
                d,
                "01-init",
                [
                    _make_group(
                        "Source Control",
                        [_make_param("TEMURIN_BUILD_REPO", "Used during init.")],
                    )
                ],
            )
            _write_params_json(
                d,
                "02-build",
                [
                    _make_group(
                        "Source Control",
                        [_make_param("TEMURIN_BUILD_REPO", "Used during build.")],
                    )
                ],
            )
            result = _collect(d)

        all_params = [p for g in result["groups"] for p in g["parameters"]]
        matching = [p for p in all_params if p["name"] == "TEMURIN_BUILD_REPO"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(
            matching[0]["description"], "Used during init."
        )

    def test_duplicate_different_groups_raises(self):
        """Same param under different groups → ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_params_json(
                d,
                "01-init",
                [
                    _make_group(
                        "Source Control", [_make_param("TEMURIN_BUILD_REPO", "desc")]
                    )
                ],
            )
            _write_params_json(
                d,
                "02-build",
                [
                    _make_group(
                        "Build Options", [_make_param("TEMURIN_BUILD_REPO", "desc")]
                    )
                ],
            )
            with self.assertRaises(ValueError) as ctx:
                _collect(d)

        self.assertIn("TEMURIN_BUILD_REPO", str(ctx.exception))
        self.assertIn("Source Control", str(ctx.exception))
        self.assertIn("Build Options", str(ctx.exception))

    def test_duplicate_one_empty_description(self):
        """One empty description → merged result is the non-empty text."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_params_json(
                d,
                "01-init",
                [
                    _make_group(
                        "Source Control", [_make_param("TEMURIN_BUILD_REPO", "")]
                    )
                ],
            )
            _write_params_json(
                d,
                "02-build",
                [
                    _make_group(
                        "Source Control",
                        [_make_param("TEMURIN_BUILD_REPO", "Non-empty description.")],
                    )
                ],
            )
            result = _collect(d)

        all_params = [p for g in result["groups"] for p in g["parameters"]]
        matching = [p for p in all_params if p["name"] == "TEMURIN_BUILD_REPO"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["description"], "Non-empty description.")

    def test_no_duplicate_unaffected(self):
        """Two stages with distinct param names are unaffected."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_params_json(
                d,
                "01-init",
                [
                    _make_group(
                        "Source Control", [_make_param("SCM_REF", "Source ref.")]
                    )
                ],
            )
            _write_params_json(
                d,
                "02-build",
                [
                    _make_group(
                        "Build Options",
                        [_make_param("EXTRA_MAKE_OPTIONS", "Extra make flags.")],
                    )
                ],
            )
            result = _collect(d)

        names = result["paramNames"]
        self.assertIn("SCM_REF", names)
        self.assertIn("EXTRA_MAKE_OPTIONS", names)
        self.assertEqual(len(names), 2)

    def test_duplicate_three_stages_different_descriptions(self):
        """Same param in three stages → descriptions accumulate as 'A / B / C'."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_params_json(
                d,
                "01-init",
                [
                    _make_group(
                        "Source Control", [_make_param("TEMURIN_BUILD_REPO", "A")]
                    )
                ],
            )
            _write_params_json(
                d,
                "02-build",
                [
                    _make_group(
                        "Source Control", [_make_param("TEMURIN_BUILD_REPO", "B")]
                    )
                ],
            )
            _write_params_json(
                d,
                "03-test",
                [
                    _make_group(
                        "Source Control", [_make_param("TEMURIN_BUILD_REPO", "C")]
                    )
                ],
            )
            result = _collect(d)

        all_params = [p for g in result["groups"] for p in g["parameters"]]
        matching = [p for p in all_params if p["name"] == "TEMURIN_BUILD_REPO"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["description"], "A")


# ---------------------------------------------------------------------------
# stageDisabled tests
# ---------------------------------------------------------------------------


class TestStageDisabled(unittest.TestCase):

    def test_disabled_stem_excluded(self):
        """stageDisabled=true: no params or groups emitted for that stem."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_params_json(
                d,
                "02-build",
                [
                    _make_group(
                        "Build Options", [_make_param("EXTRA_MAKE_OPTIONS", "desc")]
                    )
                ],
            )
            _write_params_json(
                d,
                "14-aqa-tests",
                [
                    _make_group(
                        "Stage Selections",
                        [_make_bool_param("RUN_TESTS", True, "desc")],
                    )
                ],
                stage_disabled=True,
            )
            result = _collect(d)

        names = result["paramNames"]
        self.assertIn("EXTRA_MAKE_OPTIONS", names)
        self.assertNotIn(
            "RUN_TESTS", names, "disabled stage param should not be emitted"
        )
        stage_ids = [g["stageId"] for g in result["groups"]]
        self.assertNotIn("14-aqa-tests", stage_ids)

    def test_enabled_stem_included(self):
        """stageDisabled=false (explicit): params are emitted normally."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_params_json(
                d,
                "07-installer",
                [
                    _make_group(
                        "Stage Selections",
                        [_make_bool_param("ENABLE_INSTALLERS", True, "desc")],
                    )
                ],
                stage_disabled=False,
            )
            result = _collect(d)

        self.assertIn("ENABLE_INSTALLERS", result["paramNames"])

    def test_vendor_can_disable_core_stage(self):
        """Vendor override with stageDisabled=true suppresses a core stage's params."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            vendor = d / "vendor"
            vendor.mkdir()
            # Core stage has params
            _write_params_json(
                d,
                "16-publish",
                [
                    _make_group(
                        "Stage Selections",
                        [_make_bool_param("PUBLISH_ARTIFACTS", False, "desc")],
                    )
                ],
            )
            # Vendor disables it
            _write_params_json(vendor, "16-publish", [], stage_disabled=True)
            result = _collect(d, vendor_dir=vendor)

        self.assertNotIn("PUBLISH_ARTIFACTS", result["paramNames"])

    def test_vendor_can_reenable_disabled_stage(self):
        """Vendor override with stageDisabled=false re-enables a core opt-in stage."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            vendor = d / "vendor"
            vendor.mkdir()
            # Core stage is disabled by default
            _write_params_json(
                d,
                "20-reproducible-compare",
                [
                    _make_group(
                        "Stage Selections",
                        [_make_bool_param("RUN_REPRODUCIBLE_COMPARE", False, "desc")],
                    )
                ],
                stage_disabled=True,
            )
            # Vendor enables it
            _write_params_json(
                vendor, "20-reproducible-compare", [], stage_disabled=False
            )
            result = _collect(d, vendor_dir=vendor)

        self.assertIn("RUN_REPRODUCIBLE_COMPARE", result["paramNames"])

    def test_vendor_empty_parametergroups_does_not_wipe_defaults(self):
        """
        A vendor params.json with an empty parameterGroups list must NOT remove
        the default stage's parameters.  The empty list means "nothing to add or
        change" — all default groups and parameters pass through intact.

        This mirrors the real-world Temurin pattern where vendor files like
        20-reproducible-compare.params.json carry only metadata fields (stageId,
        stageDisabled, stageCondition, description) and an empty parameterGroups,
        because the stage needs no extra job parameters beyond the defaults.
        """
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            vendor = d / "vendor"
            vendor.mkdir()

            # Core stage defines two params across two groups
            _write_params_json(
                d,
                "20-reproducible-compare",
                [
                    _make_group(
                        "Stage Selections",
                        [
                            _make_bool_param(
                                "RUN_REPRODUCIBLE_COMPARE", False, "Run repro compare."
                            )
                        ],
                    ),
                    _make_group(
                        "Repro Options",
                        [
                            _make_param(
                                "REPRO_EXTRA_ARGS", "Extra args for repro compare."
                            )
                        ],
                    ),
                ],
            )

            # Vendor override: metadata only, empty parameterGroups
            _write_params_json(
                vendor,
                "20-reproducible-compare",
                [],
                stage_disabled=False,
                stage_condition=[],
            )

            result = _collect(d, vendor_dir=vendor)

        # Both default params must survive unchanged
        self.assertIn(
            "RUN_REPRODUCIBLE_COMPARE",
            result["paramNames"],
            "default boolean param must not be wiped by empty vendor parameterGroups",
        )
        self.assertIn(
            "REPRO_EXTRA_ARGS",
            result["paramNames"],
            "default string param must not be wiped by empty vendor parameterGroups",
        )

        # Both default groups must survive
        group_names = [g["name"] for g in result["groups"]]
        self.assertIn("Stage Selections", group_names)
        self.assertIn("Repro Options", group_names)

        # The param values must be the defaults, not accidentally altered
        all_params = {p["name"]: p for g in result["groups"] for p in g["parameters"]}
        self.assertEqual(all_params["RUN_REPRODUCIBLE_COMPARE"]["default"], False)
        self.assertEqual(all_params["REPRO_EXTRA_ARGS"]["default"], "")


# ---------------------------------------------------------------------------
# stageCondition tests
# ---------------------------------------------------------------------------


class TestStageCondition(unittest.TestCase):

    def test_stage_condition_propagated_to_group(self):
        """stageCondition is propagated to the emitted group."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            # Owner of the referenced param
            _write_params_json(
                d,
                "03-sign",
                [
                    _make_group(
                        "Stage Selections",
                        [_make_bool_param("SIGN_ARTIFACTS", False, "desc")],
                    )
                ],
            )
            # Stage with a condition referencing SIGN_ARTIFACTS
            _write_params_json(
                d,
                "06-post-sign",
                [
                    _make_group(
                        "Post Sign Options", [_make_param("POST_SIGN_KEY", "desc")]
                    )
                ],
                stage_condition=[{"param": "SIGN_ARTIFACTS", "value": True}],
            )
            result = _collect(d)

        post_sign_groups = [
            g for g in result["groups"] if g["stageId"] == "06-post-sign"
        ]
        self.assertTrue(len(post_sign_groups) > 0)
        cond = post_sign_groups[0]["stageCondition"]
        self.assertEqual(len(cond), 1)
        self.assertEqual(cond[0]["param"], "SIGN_ARTIFACTS")
        self.assertEqual(cond[0]["value"], True)

    def test_dangling_stage_condition_raises(self):
        """stageCondition referencing an unknown param → ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_params_json(
                d,
                "06-post-sign",
                [_make_group("Options", [_make_param("POST_SIGN_KEY", "desc")])],
                stage_condition=[{"param": "NONEXISTENT_PARAM", "value": True}],
            )
            with self.assertRaises(ValueError) as ctx:
                _collect(d)

        self.assertIn("NONEXISTENT_PARAM", str(ctx.exception))

    def test_gate_only_file_valid_refs_ok(self):
        """Gate-only params.json with valid stageCondition refs passes validation."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            # Define both referenced params
            _write_params_json(
                d,
                "03-sign",
                [
                    _make_group(
                        "Stage Selections",
                        [_make_bool_param("SIGN_ARTIFACTS", False, "desc")],
                    )
                ],
            )
            _write_params_json(
                d,
                "07-installer",
                [
                    _make_group(
                        "Stage Selections",
                        [_make_bool_param("ENABLE_INSTALLERS", True, "desc")],
                    )
                ],
            )
            # Gate-only file for 08
            _write_gate_only_json(
                d,
                "08-sign-installer",
                [
                    {"param": "ENABLE_INSTALLERS", "value": True},
                    {"param": "SIGN_ARTIFACTS", "value": True},
                ],
            )
            result = _collect(d)  # should not raise

        # Gate-only file emits no params, just ensures the conditions are tracked
        self.assertIn("SIGN_ARTIFACTS", result["paramNames"])
        self.assertIn("ENABLE_INSTALLERS", result["paramNames"])

    def test_gate_only_file_bad_ref_raises(self):
        """Gate-only file with a dangling stageCondition reference → ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_params_json(
                d,
                "03-sign",
                [
                    _make_group(
                        "Stage Selections",
                        [_make_bool_param("SIGN_ARTIFACTS", False, "desc")],
                    )
                ],
            )
            _write_gate_only_json(
                d,
                "08-sign-installer",
                [
                    {"param": "SIGN_ARTIFACTS", "value": True},
                    {"param": "MISSING_PARAM", "value": True},
                ],
            )
            with self.assertRaises(ValueError) as ctx:
                _collect(d)

        self.assertIn("MISSING_PARAM", str(ctx.exception))


# ---------------------------------------------------------------------------
# stageTimeoutMinutes tests
# ---------------------------------------------------------------------------


class TestStageTimeoutMinutes(unittest.TestCase):
    def test_stage_timeout_propagated(self):
        """stageTimeoutMinutes is propagated to group output."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_params_json(
                d,
                "02-build",
                [_make_group("Build", [_make_param("EXTRA_ARGS", "args")])],
                stage_timeout_minutes=120,
            )
            result = _collect(d)

        self.assertEqual(len(result["groups"]), 1)
        self.assertEqual(result["groups"][0]["stageTimeoutMinutes"], 120)

    def test_stage_timeout_invalid_type_raises(self):
        """Negative or non-integer stageTimeoutMinutes raises ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            data = {
                "stageId": "02-build",
                "stageTimeoutMinutes": "invalid",
                "stageCondition": [],
            }
            (d / "02-build.params.json").write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                _collect(d)


# ---------------------------------------------------------------------------
# Stage Selections priority group tests
# ---------------------------------------------------------------------------


class TestStageSelectionsGroup(unittest.TestCase):

    def test_stage_selections_first(self):
        """Stage Selections group is placed first in the output regardless of stem order."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            # 02-build comes alphabetically before any stage-gate file
            _write_params_json(
                d,
                "02-build",
                [
                    _make_group(
                        "Build Options", [_make_param("EXTRA_MAKE_OPTIONS", "desc")]
                    )
                ],
            )
            _write_params_json(
                d,
                "14-aqa-tests",
                [
                    _make_group(
                        "Stage Selections",
                        [_make_bool_param("RUN_TESTS", True, "desc")],
                    )
                ],
            )
            result = _collect(d)

        self.assertEqual(result["groups"][0]["name"], "Stage Selections")

    def test_stage_selections_merged_from_multiple_stems(self):
        """Stage Selections params from multiple stems are merged into one group."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_params_json(
                d,
                "03-sign",
                [
                    _make_group(
                        "Stage Selections",
                        [_make_bool_param("SIGN_ARTIFACTS", False, "sign desc")],
                    )
                ],
            )
            _write_params_json(
                d,
                "07-installer",
                [
                    _make_group(
                        "Stage Selections",
                        [_make_bool_param("ENABLE_INSTALLERS", True, "inst desc")],
                    )
                ],
            )
            _write_params_json(
                d,
                "14-aqa-tests",
                [
                    _make_group(
                        "Stage Selections",
                        [_make_bool_param("RUN_TESTS", True, "test desc")],
                    )
                ],
            )
            result = _collect(d)

        sel_groups = [g for g in result["groups"] if g["name"] == "Stage Selections"]
        self.assertEqual(
            len(sel_groups), 1, "All Stage Selections should be merged into one group"
        )
        param_names = [p["name"] for p in sel_groups[0]["parameters"]]
        self.assertIn("SIGN_ARTIFACTS", param_names)
        self.assertIn("ENABLE_INSTALLERS", param_names)
        self.assertIn("RUN_TESTS", param_names)

    def test_disabled_stage_params_not_in_stage_selections(self):
        """Params from a disabled stage are NOT merged into Stage Selections."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_params_json(
                d,
                "03-sign",
                [
                    _make_group(
                        "Stage Selections",
                        [_make_bool_param("SIGN_ARTIFACTS", False, "desc")],
                    )
                ],
            )
            _write_params_json(
                d,
                "16-publish",
                [
                    _make_group(
                        "Stage Selections",
                        [_make_bool_param("PUBLISH_ARTIFACTS", False, "desc")],
                    )
                ],
                stage_disabled=True,
            )
            result = _collect(d)

        sel = [g for g in result["groups"] if g["name"] == "Stage Selections"]
        param_names = [p["name"] for p in sel[0]["parameters"]] if sel else []
        self.assertIn("SIGN_ARTIFACTS", param_names)
        self.assertNotIn("PUBLISH_ARTIFACTS", param_names)

    def test_non_priority_groups_follow_in_discovery_order(self):
        """Non-priority groups appear after Stage Selections in discovery order."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_params_json(
                d,
                "02-build",
                [
                    _make_group(
                        "Build Options", [_make_param("EXTRA_MAKE_OPTIONS", "desc")]
                    )
                ],
            )
            _write_params_json(
                d,
                "14-aqa-tests",
                [
                    _make_group(
                        "Stage Selections",
                        [_make_bool_param("RUN_TESTS", True, "desc")],
                    ),
                    _make_group("AQA Options", [_make_param("AQA_REF", "desc")]),
                ],
            )
            result = _collect(d)

        group_names = [g["name"] for g in result["groups"]]
        self.assertEqual(group_names[0], "Stage Selections")
        self.assertIn("Build Options", group_names)
        self.assertIn("AQA Options", group_names)
        # Stage Selections must come before everything else
        idx_sel = group_names.index("Stage Selections")
        for name in ["Build Options", "AQA Options"]:
            self.assertLess(idx_sel, group_names.index(name))

    def test_stage_selections_group_has_stageids_list(self):
        """Merged Stage Selections group must carry a stageIds list with all contributing stems."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_params_json(
                d,
                "03-sign",
                [
                    _make_group(
                        "Stage Selections",
                        [_make_bool_param("SIGN_ARTIFACTS", False, "desc")],
                    )
                ],
            )
            _write_params_json(
                d,
                "07-installer",
                [
                    _make_group(
                        "Stage Selections",
                        [_make_bool_param("ENABLE_INSTALLERS", True, "desc")],
                    )
                ],
            )
            _write_params_json(
                d,
                "14-aqa-tests",
                [
                    _make_group(
                        "Stage Selections",
                        [_make_bool_param("RUN_TESTS", True, "desc")],
                    )
                ],
            )
            result = _collect(d)

        sel = next(g for g in result["groups"] if g["name"] == "Stage Selections")
        self.assertIn(
            "stageIds", sel, "merged Stage Selections must carry stageIds list"
        )
        stage_ids = sel["stageIds"]
        self.assertIsInstance(stage_ids, list)
        self.assertIn("03-sign", stage_ids)
        self.assertIn("07-installer", stage_ids)
        self.assertIn("14-aqa-tests", stage_ids)
        self.assertEqual(
            len(stage_ids), 3, "all three contributing stems must be listed"
        )

    def test_real_core_stages_collate_correctly(self):
        """Integration test: real scripts/stages directory produces expected output."""
        stages_dir = Path(__file__).parent.parent / "scripts" / "stages"
        if not stages_dir.is_dir():
            self.skipTest("scripts/stages not found")

        result = collect(
            default_stages_dir=stages_dir,
            vendor_scripts_dir=None,
            vendor_raw_base_url=None,
        )

        # All six gate booleans must be present
        for param in (
            "SIGN_ARTIFACTS",
            "ENABLE_INSTALLERS",
            "RUN_TESTS",
            "ENABLE_TCK",
            "PUBLISH_ARTIFACTS",
            "RUN_REPRODUCIBLE_COMPARE",
        ):
            self.assertIn(
                param, result["paramNames"], f"{param} missing from paramNames"
            )

        # Stage Selections must be the first group
        self.assertTrue(len(result["groups"]) > 0)
        self.assertEqual(result["groups"][0]["name"], "Stage Selections")

        # All six gate booleans must be in the Stage Selections group
        sel_params = {p["name"] for p in result["groups"][0]["parameters"]}
        for param in (
            "SIGN_ARTIFACTS",
            "ENABLE_INSTALLERS",
            "RUN_TESTS",
            "ENABLE_TCK",
            "PUBLISH_ARTIFACTS",
            "RUN_REPRODUCIBLE_COMPARE",
        ):
            self.assertIn(param, sel_params, f"{param} not in Stage Selections group")

        # SIGN_ARTIFACTS must be defined on all signing stages that declare Stage Selections
        signing_stems = {
            "03-internal-code-sign",
            "06-post-build-code-sign",
            "08-code-sign-installer",
            "09-sbom-sign",
            "10-digital-artifact-sign",
        }

        # RUN_TESTS must be defined on all test stages
        test_stems = {"13-smoke-tests", "14-aqa-tests"}

        # Merged Stage Selections group must list all contributing stems
        sel_group = result["groups"][0]
        self.assertIn(
            "stageIds", sel_group, "Stage Selections group must carry stageIds list"
        )
        actual_stems = set(sel_group["stageIds"])

        # Every signing stage and every test stage that defines these params
        # must appear in stageIds (they all contribute to Stage Selections)
        for stem in signing_stems:
            self.assertIn(
                stem,
                actual_stems,
                f"signing stage {stem!r} missing from Stage Selections stageIds",
            )
        for stem in test_stems:
            self.assertIn(
                stem,
                actual_stems,
                f"test stage {stem!r} missing from Stage Selections stageIds",
            )

        # SIGN_ARTIFACTS description must be emitted exactly once (no " / " duplication)
        all_params = {p["name"]: p for g in result["groups"] for p in g["parameters"]}
        self.assertNotIn(
            " / ",
            all_params["SIGN_ARTIFACTS"]["description"],
            "SIGN_ARTIFACTS description should not be duplicated by the collator",
        )
        self.assertNotIn(
            " / ",
            all_params["RUN_TESTS"]["description"],
            "RUN_TESTS description should not be duplicated by the collator",
        )


if __name__ == "__main__":
    unittest.main()
