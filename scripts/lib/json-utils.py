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
json-utils.py — JSON value extraction helper for CI shell scripts.

Replaces jq for simple dot-notation path lookups so that shell scripts do not
require jq to be installed on the agent.

Usage:
    # Read from a file
    python3 json-utils.py get <path> <json_file>

    # Read from stdin
    cat config.json | python3 json-utils.py get <path>

Path syntax:
    Dot-separated key names, with or without a leading dot.
    Examples:  .buildConfig.JAVA_TO_BUILD
               repoDefaults.buildRef
               parameters.cleanWorkspaceAfterStage

Output:
    Prints the value as a string.  Booleans are printed as lowercase
    'true'/'false'.  If the key is not found, prints 'null' and exits 1.
    On JSON parse errors, prints an error message to stderr and exits 2.
"""

import json
import sys


def _traverse(data, path):
    """Walk a dot-notation path through nested dicts. Returns the value or None."""
    keys = [k for k in path.lstrip(".").split(".") if k]
    val = data
    for key in keys:
        if isinstance(val, dict):
            val = val.get(key)
        else:
            return None
        if val is None:
            return None
    return val


def cmd_get(path, source):
    """Extract a value at *path* from *source* (file path or '-' for stdin)."""
    try:
        if source == "-":
            data = json.load(sys.stdin)
        else:
            with open(source) as fh:
                data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"json-utils: {exc}", file=sys.stderr)
        sys.exit(2)

    value = _traverse(data, path)

    if value is None:
        print("null")
        sys.exit(1)

    # Normalise booleans to lowercase strings so callers can compare directly.
    if isinstance(value, bool):
        print(str(value).lower())
    else:
        print(value)


def main():
    if len(sys.argv) < 3:
        print(
            "Usage: json-utils.py get <dot-path> [<json_file>|-]",
            file=sys.stderr,
        )
        sys.exit(2)

    command = sys.argv[1]
    path = sys.argv[2]
    source = sys.argv[3] if len(sys.argv) > 3 else "-"

    if command == "get":
        cmd_get(path, source)
    else:
        print(f"json-utils: unknown command '{command}'", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
