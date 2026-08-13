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
Build Metadata Writer

Writes a build-metadata.json file from values supplied as CLI arguments and
environment variables.  All dynamic data is passed in explicitly - nothing is
read from the shell environment via string interpolation - so the script is
safe to call from any shell context.

Usage:
    python build-metadata-writer.py \\
        --output /path/to/build-metadata.json \\
        --version  jdk-21.0.12+7 \\
        --build-number 42 \\
        --stage build \\
        --workspace /workspace/build

Optional arguments (fall back to empty string when absent):
    --build-uid   <uid>
    --group-uid   <uid>

The following fields are read from environment variables (set by the pipeline):
    CONFIG_JAVA_TO_BUILD
    CONFIG_TARGET_OS
    CONFIG_ARCHITECTURE
    CONFIG_VARIANT
"""

from __future__ import print_function

import argparse
import io
import json
import os
import sys
import time


def _utc_iso(ts):
    """Return an ISO-8601 UTC timestamp string for the given epoch seconds."""
    t = time.gmtime(ts)
    return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}Z".format(
        t.tm_year,
        t.tm_mon,
        t.tm_mday,
        t.tm_hour,
        t.tm_min,
        t.tm_sec,
    )


class BuildMetadataWriter(object):
    """Collects build metadata and serialises it to a JSON file."""

    def __init__(self, args):
        self._output = args.output
        self._version = args.version
        self._build_number = args.build_number
        self._build_uid = args.build_uid or ""
        self._group_uid = args.group_uid or ""
        self._stage = args.stage
        self._workspace = args.workspace

    def _collect(self):
        now = time.time()
        return {
            "version": self._version,
            "buildNumber": self._build_number,
            "buildUid": self._build_uid,
            "groupUid": self._group_uid,
            "timestamp": int(now),
            "timestampISO": _utc_iso(now),
            "stage": self._stage,
            "workspace": self._workspace,
            "javaVersion": os.environ.get("CONFIG_JAVA_TO_BUILD", ""),
            "targetOS": os.environ.get("CONFIG_TARGET_OS", ""),
            "architecture": os.environ.get("CONFIG_ARCHITECTURE", ""),
            "variant": os.environ.get("CONFIG_VARIANT", ""),
        }

    def write(self):
        metadata = self._collect()
        try:
            content = json.dumps(metadata, indent=2, ensure_ascii=True)
            if not isinstance(content, type(u"")):
                content = content.decode("utf-8")
            with io.open(self._output, "w", encoding="utf-8") as fh:
                fh.write(content)
                fh.write(u"\n")
        except (IOError, OSError) as exc:
            print(
                "ERROR: could not write {0}: {1}".format(self._output, exc),
                file=sys.stderr,
            )
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Write build-metadata.json for an Adoptium build stage",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--output", required=True, help="Destination path for build-metadata.json"
    )
    parser.add_argument(
        "--version", required=True, help="JDK version string (e.g. jdk-21.0.12+7)"
    )
    parser.add_argument("--build-number", required=True, help="Build number")
    parser.add_argument("--stage", required=True, help="Stage name (e.g. build)")
    parser.add_argument(
        "--workspace", required=True, help="Absolute path to the build workspace"
    )
    parser.add_argument("--build-uid", default="", help="Build UID (optional)")
    parser.add_argument("--group-uid", default="", help="Group UID (optional)")

    args = parser.parse_args()
    BuildMetadataWriter(args).write()
    return 0


if __name__ == "__main__":
    sys.exit(main())
