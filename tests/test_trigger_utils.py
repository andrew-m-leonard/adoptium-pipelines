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
"""Tests for trigger-utils.py utility commands."""

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

# Allow importing modules from scripts/lib/
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "lib"))

# Import trigger-utils as a module
trigger_utils = importlib.import_module("trigger-utils")


class TestTriggerUtils(unittest.TestCase):
    """Test suite for trigger-utils.py commands."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.target_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_write_trigger_result_success(self):
        """Test writing a valid trigger-result.json from key=value pairs."""
        pairs = [
            "shouldTrigger=true",
            "scmRef=jdk-21.0.5+11_adopt",
            "publishName=jdk-21.0.5+11-ea",
            "dedupBuildType=NONE",
            "some_number=42",
        ]
        exit_code = trigger_utils.cmd_write_trigger_result(str(self.target_dir), pairs)
        self.assertEqual(exit_code, 0)

        out_path = self.target_dir / "trigger-result.json"
        self.assertTrue(out_path.exists())

        # Verify parsed contents
        data = json.loads(out_path.read_text())
        self.assertEqual(data["shouldTrigger"], True)
        self.assertEqual(data["scmRef"], "jdk-21.0.5+11_adopt")
        self.assertEqual(data["publishName"], "jdk-21.0.5+11-ea")
        self.assertEqual(data["dedupBuildType"], "NONE")
        self.assertEqual(data["some_number"], "42")

    def test_write_trigger_result_invalid_pair(self):
        """Test that invalid key=value pairs return an error exit code."""
        pairs = ["shouldTrigger=true", "invalid_pair_missing_equals"]
        exit_code = trigger_utils.cmd_write_trigger_result(str(self.target_dir), pairs)
        self.assertEqual(exit_code, 2)

    def test_read_trigger_field_success(self):
        """Test reading a field from an existing trigger-result.json."""
        out_path = self.target_dir / "trigger-result.json"
        out_path.write_text(
            json.dumps(
                {
                    "shouldTrigger": True,
                    "scmRef": "jdk-21.0.5+11_adopt",
                    "dedupBuildType": "NONE",
                }
            )
        )

        # We can intercept stdout to verify printed value
        from io import StringIO

        old_stdout = sys.stdout
        sys.stdout = StringIO()
        try:
            exit_code = trigger_utils.cmd_read_trigger_field(
                str(out_path), "dedupBuildType"
            )
            output = sys.stdout.getvalue().strip()
        finally:
            sys.stdout = old_stdout

        self.assertEqual(exit_code, 0)
        self.assertEqual(output, "NONE")

    def test_read_trigger_field_missing(self):
        """Test reading a missing field from trigger-result.json."""
        out_path = self.target_dir / "trigger-result.json"
        out_path.write_text(json.dumps({"shouldTrigger": True}))

        exit_code = trigger_utils.cmd_read_trigger_field(str(out_path), "missing_field")
        self.assertEqual(exit_code, 1)

    def test_default_build_tag_pattern(self):
        """Test default build tag patterns derived for various JDK versions."""
        from io import StringIO

        versions_to_test = {
            "jdk8": "jdk8u.+_adopt$",
            "jdk11": r"jdk-11[\\.+].+_adopt$",
            "jdk21": r"jdk-21[\\.+].+_adopt$",
            "jdk25": r"jdk-25[\\.+].+_adopt$",
        }

        for version, expected in versions_to_test.items():
            old_stdout = sys.stdout
            sys.stdout = StringIO()
            try:
                exit_code = trigger_utils.cmd_default_build_tag_pattern(version)
                output = sys.stdout.getvalue().strip()
            finally:
                sys.stdout = old_stdout

            self.assertEqual(exit_code, 0)
            self.assertEqual(output, expected)


if __name__ == "__main__":
    unittest.main()
