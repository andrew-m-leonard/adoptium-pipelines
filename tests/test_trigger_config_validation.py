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
Tests for trigger_config.json validation rules.

Mirrors the validateTriggerConfig closure in
ci/jenkins/job-dsl/seed/seed_job_dsl.groovy.

Rules validated:
  1. No duplicate trigger type entries (copy-paste whole block mistake).
  2. No duplicate version within a single trigger type's versions array.

Note: the same version appearing under *different* trigger types is intentional
and valid (e.g. jdk21 under both "detect-ga-tag" and
"detect-build-tag-for-github-release").  Each type runs as a separate parallel
branch with its own version-scoped workspace paths, so there is no collision.

Each rule is tested for:
  - The valid case (no error)
  - The exact invalid case the rule guards against
  - Combined / multiple-error reporting (all errors collected, not just first)
"""

import unittest


# ---------------------------------------------------------------------------
# Pure-Python mirror of the Groovy validateTriggerConfig closure
# ---------------------------------------------------------------------------

def validate_trigger_config(triggers: list) -> list[str]:
    """
    Validate a parsed trigger_config.json triggers list.

    Returns a list of error strings (empty = valid).
    Mirrors the logic in seed_job_dsl.groovy validateTriggerConfig exactly.
    """
    errors: list[str] = []

    # Rule 1 — duplicate type entries
    type_seen: dict[str, int] = {}
    for i, t in enumerate(triggers):
        ttype = str(t.get("type") or f"(missing type at index {i})")
        if ttype in type_seen:
            errors.append(
                f"  Duplicate trigger type '{ttype}' at index {i} "
                f"(first seen at index {type_seen[ttype]}). "
                "All versions for a given type must be listed in a single 'versions' array."
            )
        else:
            type_seen[ttype] = i

    # Rule 2 — duplicate version within the same type
    for t in triggers:
        ttype = str(t.get("type") or "(unknown type)")
        versions = t.get("versions") or []
        seen_in_this_type: set[str] = set()
        for j, v in enumerate(versions):
            ver = str(v.get("version") or f"(missing version at index {j} under type '{ttype}')")
            if ver in seen_in_this_type:
                errors.append(
                    f"  Duplicate version '{ver}' under trigger type '{ttype}'. "
                    "Each version must appear at most once per type."
                )
            else:
                seen_in_this_type.add(ver)

    return errors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_type(ttype: str, *versions: str) -> dict:
    return {"type": ttype, "versions": [{"version": v} for v in versions]}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestValidTriggerConfigs(unittest.TestCase):
    """Configs that must pass without errors."""

    def test_empty_triggers_list(self):
        self.assertEqual(validate_trigger_config([]), [])

    def test_single_type_single_version(self):
        triggers = [_make_type("detect-ga-tag", "jdk21")]
        self.assertEqual(validate_trigger_config(triggers), [])

    def test_single_type_multiple_distinct_versions(self):
        triggers = [_make_type("detect-ga-tag", "jdk21", "jdk25", "jdk27")]
        self.assertEqual(validate_trigger_config(triggers), [])

    def test_same_version_under_different_types_is_valid(self):
        """jdk21 under detect-ga-tag AND detect-build-tag-for-github-release is intentional."""
        triggers = [
            _make_type("detect-ga-tag", "jdk21", "jdk27"),
            _make_type("detect-build-tag-for-github-release", "jdk21", "jdk25"),
            _make_type("weekly-head", "jdk26"),
        ]
        self.assertEqual(validate_trigger_config(triggers), [])

    def test_type_with_empty_versions_array(self):
        triggers = [{"type": "detect-ga-tag", "versions": []}]
        self.assertEqual(validate_trigger_config(triggers), [])


class TestRule1DuplicateType(unittest.TestCase):
    """Rule 1: no two top-level entries may share the same 'type' value."""

    def test_duplicate_type_raises(self):
        triggers = [
            _make_type("detect-ga-tag", "jdk21"),
            _make_type("detect-ga-tag", "jdk25"),   # duplicate type
        ]
        errors = validate_trigger_config(triggers)
        self.assertEqual(len(errors), 1)
        self.assertIn("Duplicate trigger type 'detect-ga-tag'", errors[0])
        self.assertIn("index 1", errors[0])
        self.assertIn("index 0", errors[0])

    def test_two_duplicate_types(self):
        triggers = [
            _make_type("detect-ga-tag", "jdk21"),
            _make_type("weekly-head", "jdk26"),
            _make_type("detect-ga-tag", "jdk25"),   # dup at index 2
            _make_type("weekly-head", "jdk27"),     # dup at index 3
        ]
        errors = validate_trigger_config(triggers)
        self.assertEqual(len(errors), 2)
        types_mentioned = [e for e in errors if "Duplicate trigger type" in e]
        self.assertEqual(len(types_mentioned), 2)

    def test_same_type_three_times(self):
        triggers = [
            _make_type("detect-ga-tag", "jdk21"),
            _make_type("detect-ga-tag", "jdk25"),
            _make_type("detect-ga-tag", "jdk27"),
        ]
        errors = validate_trigger_config(triggers)
        self.assertEqual(len(errors), 2)  # second and third are both reported


class TestRule2DuplicateVersionWithinType(unittest.TestCase):
    """Rule 2: within a type's versions array every version must be unique."""

    def test_duplicate_version_same_type(self):
        triggers = [
            {"type": "detect-build-tag-for-github-release", "versions": [
                {"version": "jdk21"},
                {"version": "jdk25"},
                {"version": "jdk21"},   # duplicate
            ]}
        ]
        errors = validate_trigger_config(triggers)
        self.assertEqual(len(errors), 1)
        self.assertIn("Duplicate version 'jdk21'", errors[0])
        self.assertIn("detect-build-tag-for-github-release", errors[0])

    def test_two_duplicate_versions_same_type(self):
        triggers = [
            {"type": "detect-ga-tag", "versions": [
                {"version": "jdk21"},
                {"version": "jdk21"},   # dup 1
                {"version": "jdk25"},
                {"version": "jdk25"},   # dup 2
            ]}
        ]
        errors = validate_trigger_config(triggers)
        dup_errors = [e for e in errors if "Duplicate version" in e]
        self.assertEqual(len(dup_errors), 2)

    def test_triple_duplicate_version_same_type(self):
        """Third occurrence of the same version should also be reported."""
        triggers = [
            {"type": "detect-ga-tag", "versions": [
                {"version": "jdk21"},
                {"version": "jdk21"},
                {"version": "jdk21"},
            ]}
        ]
        errors = validate_trigger_config(triggers)
        dup_errors = [e for e in errors if "Duplicate version 'jdk21'" in e]
        # Second AND third occurrence each produce an error
        self.assertEqual(len(dup_errors), 2)

    def test_version_across_types_does_not_trigger_rule2(self):
        """jdk21 appearing under two different types is valid — Rule 2 only catches within-type dups."""
        triggers = [
            _make_type("detect-ga-tag", "jdk21"),
            _make_type("detect-build-tag-for-github-release", "jdk21"),
        ]
        self.assertEqual(validate_trigger_config(triggers), [])


class TestMultipleRulesSimultaneously(unittest.TestCase):
    """All errors from all rules are collected before raising — nothing is swallowed."""

    def test_rule1_and_rule2_both_reported(self):
        """Duplicate type AND duplicate version within that type — both errors collected."""
        triggers = [
            {"type": "detect-ga-tag", "versions": [
                {"version": "jdk21"},
                {"version": "jdk21"},   # Rule 2
            ]},
            _make_type("detect-ga-tag", "jdk27"),   # Rule 1
        ]
        errors = validate_trigger_config(triggers)
        self.assertTrue(any("Duplicate trigger type" in e for e in errors))
        self.assertTrue(any("Duplicate version" in e for e in errors))


class TestCurrentTemurinConfigIsValid(unittest.TestCase):
    """Snapshot test — the actual ci-temurin-config/trigger_config.json must pass.

    jdk21 appears under both 'detect-ga-tag' and
    'detect-build-tag-for-github-release' — this is intentional and must not
    be flagged as an error.
    """

    def test_temurin_trigger_config(self):
        """
        Mirrors the contents of ci-temurin-config/trigger_config.json at the
        time this test was written.  Update if the config legitimately changes.
        """
        triggers = [
            {
                "type": "detect-ga-tag",
                "versions": [
                    {"version": "jdk21", "enabled": True},
                    {"version": "jdk27", "enabled": True},
                ],
            },
            {
                "type": "detect-build-tag-for-github-release",
                "versions": [
                    {"version": "jdk21", "enabled": True},
                    {"version": "jdk25", "enabled": True},
                ],
            },
            {
                "type": "weekly-head",
                "versions": [
                    {"version": "jdk26", "enabled": True},
                ],
            },
        ]
        self.assertEqual(validate_trigger_config(triggers), [])


if __name__ == "__main__":
    unittest.main()
