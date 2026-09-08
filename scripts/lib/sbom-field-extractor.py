#!/usr/bin/env python
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
SBOM Field Extractor

Reads an Adoptium SBOM JSON file and extracts a named property from the first
component.  Prints the value to stdout so the calling shell can capture it.
Exits with code 0 and prints an empty line when the property is absent; exits
with a non-zero code only on hard errors (unreadable file, invalid JSON).

Usage:
    value=$(python sbom-field-extractor.py --sbom /path/to/sbom.json --field "Build Workspace Directory")
"""

from __future__ import print_function

import argparse
import io
import json
import sys

class SbomFieldExtractor(object):
    """Parses an Adoptium SBOM and retrieves a named property from the first component."""

    def __init__(self, sbom_path, field_name):
        self._sbom_path = sbom_path
        self._field_name = field_name

    def _load(self):
        try:
            with io.open(self._sbom_path, encoding="utf-8") as fh:
                return json.load(fh)
        except (IOError, OSError) as exc:
            print(
                "ERROR: cannot open SBOM file '{0}': {1}".format(self._sbom_path, exc),
                file=sys.stderr,
            )
            sys.exit(1)
        except ValueError as exc:
            # json.JSONDecodeError is a subclass of ValueError; both Py2 and Py3 raise ValueError
            print(
                "ERROR: invalid JSON in '{0}': {1}".format(self._sbom_path, exc),
                file=sys.stderr,
            )
            sys.exit(1)

    def extract(self):
        """Return the named property value from the first component, or an empty string."""
        data = self._load()
        try:
            properties = data["components"][0]["properties"]
        except (KeyError, IndexError, TypeError):
            return ""
        for prop in properties:
            if prop.get("name") == self._field_name:
                return prop.get("value", "")
        return ""


def main():
    parser = argparse.ArgumentParser(
        description="Extract a named property from an Adoptium SBOM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--sbom", required=True, help="Path to the SBOM JSON file")
    parser.add_argument("--field", required=True, help="Property name to extract (e.g. \"Build Workspace Directory\")")

    args = parser.parse_args()
    print(SbomFieldExtractor(args.sbom, args.field).extract())
    return 0


if __name__ == "__main__":
    sys.exit(main())
