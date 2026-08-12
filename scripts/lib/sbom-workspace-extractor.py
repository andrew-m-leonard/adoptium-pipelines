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
SBOM Workspace Extractor

Reads an Adoptium SBOM JSON file and extracts the 'Build Workspace Directory'
property from the first component.  Prints the value to stdout so the calling
shell can capture it.  Exits with code 0 and prints an empty line when the
property is absent; exits with a non-zero code only on hard errors (unreadable
file, invalid JSON).

Usage:
    value=$(python sbom-workspace-extractor.py --sbom /path/to/sbom.json)
"""

import argparse
import json
import sys

# The SBOM property name defined by the Adoptium build pipeline
_PROPERTY_NAME = "Build Workspace Directory"


class SbomWorkspaceExtractor(object):
    """Parses an Adoptium SBOM and retrieves the build workspace directory."""

    def __init__(self, sbom_path):
        self._sbom_path = sbom_path

    def _load(self):
        try:
            with open(self._sbom_path, encoding="utf-8") as fh:
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
        """Return the Build Workspace Directory value, or an empty string."""
        data = self._load()
        try:
            properties = data["components"][0]["properties"]
        except (KeyError, IndexError, TypeError):
            return ""
        for prop in properties:
            if prop.get("name") == _PROPERTY_NAME:
                return prop.get("value", "")
        return ""


def main():
    parser = argparse.ArgumentParser(
        description="Extract Build Workspace Directory from an Adoptium SBOM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--sbom", required=True, help="Path to the SBOM JSON file")

    args = parser.parse_args()
    print(SbomWorkspaceExtractor(args.sbom).extract())
    return 0


if __name__ == "__main__":
    sys.exit(main())
