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
Convert Groovy pipeline config files to JSON format.

This script parses Groovy configuration files and converts them to JSON,
handling nested maps, lists, and variant-specific configurations.

Usage:
    python3 groovy-pipeline-config-to-json.py <input.groovy> <output.json>
"""

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Union, cast


class GroovyParser:
    """Parser for Groovy configuration files."""

    def __init__(self, content: str):
        self.content = content
        self.pos = 0

    def skip_whitespace(self):
        """Skip whitespace and comments."""
        while self.pos < len(self.content):
            # Skip whitespace
            if self.content[self.pos].isspace():
                self.pos += 1
                continue

            # Skip single-line comments
            if self.content[self.pos : self.pos + 2] == "//":
                while self.pos < len(self.content) and self.content[self.pos] != "\n":
                    self.pos += 1
                continue

            # Skip multi-line comments
            if self.content[self.pos : self.pos + 2] == "/*":
                self.pos += 2
                while self.pos < len(self.content) - 1:
                    if self.content[self.pos : self.pos + 2] == "*/":
                        self.pos += 2
                        break
                    self.pos += 1
                continue

            break

    def peek(self, length=1) -> str:
        """Peek at next characters without consuming."""
        return self.content[self.pos : self.pos + length]

    def consume(self, length=1) -> str:
        """Consume and return next characters."""
        result = self.content[self.pos : self.pos + length]
        self.pos += length
        return result

    def parse_string(self) -> str:
        """Parse a quoted string."""
        quote = self.consume()  # ' or "
        result = []

        while self.pos < len(self.content):
            char = self.peek()

            if char == "\\":
                self.consume()
                if self.pos < len(self.content):
                    result.append(self.consume())
            elif char == quote:
                self.consume()
                break
            else:
                result.append(self.consume())

        return "".join(result)

    def parse_identifier(self) -> str:
        """Parse an identifier (unquoted key or value)."""
        result = []

        while self.pos < len(self.content):
            char = self.peek()
            if char.isalnum() or char in "_.-":
                result.append(self.consume())
            else:
                break

        return "".join(result)

    def parse_value(self) -> Any:
        """Parse a value (string, number, boolean, list, or map)."""
        self.skip_whitespace()

        char = self.peek()

        # String
        if char in "\"'":
            return self.parse_string()

        # List or Map
        if char == "[":
            return self.parse_collection()

        # Try to parse as identifier/keyword
        identifier = self.parse_identifier()

        # Boolean
        if identifier == "true":
            return True
        if identifier == "false":
            return False
        if identifier == "null":
            return None

        # Number
        try:
            if "." in identifier:
                return float(identifier)
            return int(identifier)
        except ValueError:
            pass

        # Return as string
        return identifier

    def parse_collection(self) -> Union[List, Dict]:
        """Parse a list or map enclosed in []."""
        self.consume()  # [
        self.skip_whitespace()

        # Empty collection
        if self.peek() == "]":
            self.consume()
            return []

        # Try to determine if it's a map or list
        # Look ahead for ':' to determine if it's a map
        saved_pos = self.pos
        is_map = False

        # Scan ahead to check for key:value pattern
        depth = 0
        scan_pos = self.pos
        while scan_pos < len(self.content) and scan_pos < self.pos + 200:
            if self.content[scan_pos] in "[{":
                depth += 1
            elif self.content[scan_pos] in "]}":
                if depth == 0:
                    break
                depth -= 1
            elif self.content[scan_pos] == ":" and depth == 0:
                is_map = True
                break
            elif self.content[scan_pos] == "," and depth == 0:
                break
            scan_pos += 1

        self.pos = saved_pos

        if is_map:
            return self.parse_map_content()
        else:
            return self.parse_list_content()

    def parse_list_content(self) -> List:
        """Parse list content (already inside [])."""
        items = []

        while self.pos < len(self.content):
            self.skip_whitespace()

            if self.peek() == "]":
                self.consume()
                break

            items.append(self.parse_value())

            self.skip_whitespace()
            if self.peek() == ",":
                self.consume()
            elif self.peek() == "]":
                self.consume()
                break

        return items

    def parse_map_content(self) -> Dict:
        """Parse map content (already inside [])."""
        result = {}

        while self.pos < len(self.content):
            self.skip_whitespace()

            if self.peek() == "]":
                self.consume()
                break

            # Parse key
            if self.peek() in "\"'":
                key = self.parse_string()
            else:
                key = self.parse_identifier()

            self.skip_whitespace()

            # Expect ':'
            if self.peek() != ":":
                break
            self.consume()

            self.skip_whitespace()

            # Parse value
            value = self.parse_value()
            result[key] = value

            self.skip_whitespace()

            # Check for comma or end
            if self.peek() == ",":
                self.consume()
            elif self.peek() == "]":
                self.consume()
                break

        return result

    def parse_build_configurations(self) -> Dict:
        """Parse the buildConfigurations map from Groovy file."""
        # Find buildConfigurations = [
        pattern = r"buildConfigurations\s*=\s*\["
        match = re.search(pattern, self.content)

        if not match:
            raise ValueError("Could not find buildConfigurations in file")

        self.pos = match.end() - 1  # Position at '['

        result = self.parse_collection()
        # buildConfigurations is always a map of platform-name → config
        return cast(Dict, result)


def compact_test_arrays(json_str: str) -> str:
    """Compact test arrays to single lines for readability."""
    lines = json_str.split("\n")
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Check if this is a test array start (e.g., "weekly": [)
        if re.search(r'"(weekly|nightly|release)":\s*\[', line):
            # Collect all array elements
            array_lines = [line]
            i += 1

            # Collect elements until we find the closing bracket
            while i < len(lines):
                array_lines.append(lines[i])
                if lines[i].strip() == "]" or lines[i].strip() == "],":
                    break
                i += 1

            # Extract the array elements
            indent = len(line) - len(line.lstrip())
            match = re.search(r'"(weekly|nightly|release)":\s*\[', line)
            if match:
                test_type = match.group(1)

                # Collect all test names
                test_names = []
                for array_line in array_lines[1:-1]:  # Skip first and last lines
                    # Extract quoted strings
                    matches = re.findall(r'"([^"]+)"', array_line)
                    test_names.extend(matches)

                # Get the closing bracket line
                closing = array_lines[-1].strip()

                # Format as single line
                if test_names:
                    formatted = " " * indent + f'"{test_type}": ['
                    formatted += ", ".join(f'"{name}"' for name in test_names)
                    formatted += "]"
                    if closing.endswith(","):
                        formatted += ","
                    result.append(formatted)
                else:
                    # Empty array
                    result.extend(array_lines)
            else:
                result.extend(array_lines)
        else:
            result.append(line)

        i += 1

    return "\n".join(result)


def convert_groovy_to_json(input_file: Path, output_file: Path):
    """Convert Groovy config file to JSON."""

    print(f"Converting {input_file} to {output_file}...")

    # Read Groovy file
    with open(input_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Extract version from filename
    version_match = re.search(r"(jdk\d+u?)_pipeline_config", input_file.name)
    version = version_match.group(1) if version_match else "unknown"

    # Parse build configurations
    parser = GroovyParser(content)
    try:
        build_configs = parser.parse_build_configurations()
    except Exception as e:
        print(f"Error parsing file: {e}")
        raise

    # Create JSON structure
    config = {
        "version": version,
        "buildConfigurations": build_configs,
        "targetConfigurations": list(build_configs.keys()),
    }

    # Write JSON file with standard formatting
    json_str = json.dumps(config, indent=2)

    # Compact test arrays to single lines
    json_str = compact_test_arrays(json_str)

    # Add blank lines before each platform section for readability
    # Pattern: find "platformName": { and add a blank line before it
    lines = json_str.split("\n")
    formatted_lines: list[str] = []

    for i, line in enumerate(lines):
        # Check if this line starts a platform configuration
        # (has quotes, colon, and opening brace at the right indentation)
        if re.match(r'    "[^"]+": \{', line) and i > 0:
            # Add blank line before platform section (except first one)
            if formatted_lines and formatted_lines[-1].strip():
                formatted_lines.append("")
        formatted_lines.append(line)

    # Write formatted JSON
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(formatted_lines))

    print(f"✅ Successfully converted to {output_file}")
    print(f"   Version: {version}")
    print(f"   Found {len(build_configs)} platform configurations")
    print("")
    print("Platforms:")
    for platform in build_configs.keys():
        print(f"  - {platform}")
    print("")
    print("⚠️  Please review the output file and verify:")
    print("   - Nested maps and lists are correct")
    print("   - Variant-specific configurations are preserved")
    print("   - Test configurations are properly structured")


def main():
    if len(sys.argv) < 3:
        print(
            "Usage: python3 groovy-pipeline-config-to-json.py <input.groovy> <output.json>"
        )
        print("")
        print("Example:")
        print(
            "  python3 groovy-pipeline-config-to-json.py jdk21u_pipeline_config.groovy jdk21u_pipeline_config.json"
        )
        sys.exit(1)

    input_file = Path(sys.argv[1])
    output_file = Path(sys.argv[2])

    if not input_file.exists():
        print(f"Error: Input file not found: {input_file}")
        sys.exit(1)

    try:
        convert_groovy_to_json(input_file, output_file)
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

# Made with Bob
