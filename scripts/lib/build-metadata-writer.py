#!/usr/bin/env python
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
Build Metadata Writer

Writes a build-metadata.json file from values supplied as CLI arguments and
environment variables.  All dynamic data is passed in explicitly - nothing is
read from the shell environment via string interpolation - so the script is
safe to call from any shell context.

Usage:
    python build-metadata-writer.py \\
        --output /path/to/build-metadata.json \\
        --jdk-version jdk8u \\
        --build-number 42 \\
        --stage build \\
        --workspace /workspace/build

Optional arguments (fall back to empty string when absent):
    --release-type   <type>      Release type (e.g. NIGHTLY, WEEKLY, RELEASE)
    --build-uid      <uid>
    --group-uid      <uid>
    --build-ref      <ref>       Exact temurin-build ref/commit used (after any SBOM override)
    --build-repo-url <url>       temurin-build repository URL used

The following fields are read from environment variables (set by the pipeline):
    CONFIG_JAVA_TO_BUILD
    CONFIG_TARGET_OS
    CONFIG_ARCHITECTURE
    CONFIG_VARIANT
    RELEASE_TYPE
"""

from __future__ import print_function

import io
import json
import os
import sys
import time


def _utc_iso(ts):
    """Return an ISO-8601 UTC timestamp string for the given epoch seconds."""
    t = time.gmtime(ts)
    return "{0:04d}-{1:02d}-{2:02d}T{3:02d}:{4:02d}:{5:02d}Z".format(
        t.tm_year,
        t.tm_mon,
        t.tm_mday,
        t.tm_hour,
        t.tm_min,
        t.tm_sec,
    )


def _read_file_or_default(file_path, default_val=""):
    """Read a file's content or return default_val if file is missing, empty, or unreadable."""
    if file_path and os.path.isfile(file_path):
        try:
            with io.open(file_path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
                return content if content else default_val
        except Exception:
            return default_val
    return default_val


class BuildMetadataWriter(object):
    """
    Collects build metadata and serialises it to a JSON file.

    IMPORTANT: This class and script MUST remain strictly Python 2.6+ compatible
    as it executes within the 020-build stage environment across all build platforms
    (including legacy platforms like CentOS 6 that may only provide Python 2).
    Do NOT introduce Python 3-only syntax (e.g. f-strings, type annotations,
    walrus operator, pathlib) or standard library dependencies not present in
    Python 2.6.
    """

    def __init__(self, args):
        self._output = args.output
        self._jdk_version = (
            args.jdk_version
            or os.environ.get("JDK_VERSION", "")
            or os.environ.get("CONFIG_JAVA_TO_BUILD", "")
        )
        self._release_type = args.release_type or os.environ.get("RELEASE_TYPE", "NIGHTLY")
        self._build_number = args.build_number
        self._build_uid = args.build_uid or ""
        self._group_uid = args.group_uid or ""
        self._stage = args.stage
        self._workspace = args.workspace
        self._build_ref = args.build_ref or ""
        self._build_repo_url = args.build_repo_url or ""
        self._metadata_dir = args.metadata_dir or ""
        self._config_dir = args.config_dir or ""
        self._config_file = args.config_file or ""
        self._vendor = args.vendor or ""
        self._scm_ref = args.scm_ref or ""
        self._docker_image_digest = args.docker_image_digest or ""

    def _collect(self):
        now = time.time()
        meta_dir = self._metadata_dir or ""
        config_dir = self._config_dir or ""

        def _meta(filename, default=""):
            path = os.path.join(meta_dir, filename) if meta_dir else ""
            return _read_file_or_default(path, default)

        def _config(filename, default=""):
            path = os.path.join(config_dir, filename) if config_dir else ""
            return _read_file_or_default(path, default)

        scm_ref_val = _meta("scmref.txt", self._scm_ref or os.environ.get("SCM_REF", "")).strip()
        vendor_val = _meta("vendor.txt", self._vendor or os.environ.get("VENDOR", ""))
        build_source_val = _meta("buildSource.txt", self._build_repo_url)
        full_version = _meta("version.txt", "")
        configure_args = _meta("configure.txt", "")
        make_cmd_args = _meta("makeCommandArg.txt", "")
        openjdk_source = _meta("openjdkSource.txt", "")

        built_config = _config("built_config.cfg", "")
        makejdk_args = _config("makejdk-any-platform.args", "")

        dep_alsa = _meta("dependency_version_alsa.txt", "")
        dep_freetype = _meta("dependency_version_freetype.txt", "")
        dep_freemarker = _meta("dependency_version_freemarker.txt", "")

        docker_digest = (
            self._docker_image_digest
            or os.environ.get("CONFIG_DOCKER_IMAGE_DIGEST", "")
            or os.environ.get("BUILDIMAGESHA", "")
        )

        var_version_dir = os.path.join(meta_dir, "variant_version") if meta_dir else ""
        variant_version = {
            "major": _read_file_or_default(os.path.join(var_version_dir, "major.txt") if var_version_dir else "", ""),
            "minor": _read_file_or_default(os.path.join(var_version_dir, "minor.txt") if var_version_dir else "", ""),
            "security": _read_file_or_default(os.path.join(var_version_dir, "security.txt") if var_version_dir else "", ""),
            "tags": _read_file_or_default(os.path.join(var_version_dir, "tags.txt") if var_version_dir else "", ""),
        }

        build_config_json = _read_file_or_default(self._config_file, "")

        return {
            "jdk_version": self._jdk_version,
            "releaseType": self._release_type,
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
            "buildRef": self._build_ref,
            "buildRepoUrl": self._build_repo_url,
            "vendor": vendor_val,
            "scmRef": scm_ref_val,
            "buildSource": build_source_val,
            "openjdkSource": openjdk_source,
            "full_version_output": full_version,
            "configure_arguments": configure_args,
            "make_command_args": make_cmd_args,
            "makejdk_any_platform_args": makejdk_args,
            "openjdk_built_config": built_config,
            "build_env_docker_image_digest": docker_digest,
            "dependency_version_alsa": dep_alsa,
            "dependency_version_freetype": dep_freetype,
            "dependency_version_freemarker": dep_freemarker,
            "variant_version": variant_version,
            "BUILD_CONFIGURATION_param": build_config_json,
        }

    def write(self):
        metadata = self._collect()
        try:
            content = json.dumps(metadata, indent=2, ensure_ascii=True)
            if isinstance(content, bytes):
                content = content.decode("utf-8")
            content = content + u"\n"
            with io.open(self._output, "w", encoding="utf-8") as fh:
                fh.write(content)
        except (IOError, OSError) as exc:
            print(
                "ERROR: could not write {0}: {1}".format(self._output, exc),
                file=sys.stderr,
            )
            sys.exit(1)


def _parse_args(argv=None):
    """
    Parse command-line arguments.

    Supports argparse (Python 2.7+) with fallback to optparse (Python 2.6).
    """
    if argv is None:
        argv = sys.argv[1:]

    try:
        import argparse

        parser = argparse.ArgumentParser(
            description="Write build-metadata.json for an Adoptium build stage",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog=__doc__,
        )
        parser.add_argument("--output", required=True, help="Destination path for build-metadata.json")
        parser.add_argument("--jdk-version", default="", help="JDK version string from build job")
        parser.add_argument("--release-type", default="", help="Release type (e.g. NIGHTLY, WEEKLY, RELEASE)")
        parser.add_argument("--build-number", default="", help="Build number")
        parser.add_argument("--stage", default="", help="Stage name (e.g. build)")
        parser.add_argument("--workspace", default="", help="Absolute path to the build workspace")
        parser.add_argument("--build-uid", default="", help="Build UID (optional)")
        parser.add_argument("--group-uid", default="", help="Group UID (optional)")
        parser.add_argument("--build-ref", default="", help="Exact temurin-build ref/commit used")
        parser.add_argument("--build-repo-url", default="", help="temurin-build repository URL used")
        parser.add_argument("--metadata-dir", default="", help="Path to temurin-build metadata directory")
        parser.add_argument("--config-dir", default="", help="Path to temurin-build config directory")
        parser.add_argument("--config-file", default="", help="Path to pipeline-config.json")
        parser.add_argument("--vendor", default="", help="Vendor name")
        parser.add_argument("--scm-ref", default="", help="SCM ref")
        parser.add_argument("--docker-image-digest", default="", help="Docker image digest")

        return parser.parse_args(argv)

    except ImportError:
        import optparse

        parser = optparse.OptionParser(
            description="Write build-metadata.json for an Adoptium build stage",
            epilog=__doc__,
        )
        parser.add_option("--output", dest="output", default="", help="Destination path for build-metadata.json")
        parser.add_option("--jdk-version", dest="jdk_version", default="", help="JDK version string from build job")
        parser.add_option("--release-type", dest="release_type", default="", help="Release type")
        parser.add_option("--build-number", dest="build_number", default="", help="Build number")
        parser.add_option("--stage", dest="stage", default="", help="Stage name")
        parser.add_option("--workspace", dest="workspace", default="", help="Absolute path to the build workspace")
        parser.add_option("--build-uid", dest="build_uid", default="", help="Build UID (optional)")
        parser.add_option("--group-uid", dest="group_uid", default="", help="Group UID (optional)")
        parser.add_option("--build-ref", dest="build_ref", default="", help="Exact temurin-build ref/commit used")
        parser.add_option("--build-repo-url", dest="build_repo_url", default="", help="temurin-build repository URL used")
        parser.add_option("--metadata-dir", dest="metadata_dir", default="", help="Path to temurin-build metadata directory")
        parser.add_option("--config-dir", dest="config_dir", default="", help="Path to temurin-build config directory")
        parser.add_option("--config-file", dest="config_file", default="", help="Path to pipeline-config.json")
        parser.add_option("--vendor", dest="vendor", default="", help="Vendor name")
        parser.add_option("--scm-ref", dest="scm_ref", default="", help="SCM ref")
        parser.add_option("--docker-image-digest", dest="docker_image_digest", default="", help="Docker image digest")

        options, _ = parser.parse_args(argv)
        if not options.output:
            parser.error("--output is required")
        return options


def main():
    args = _parse_args()
    BuildMetadataWriter(args).write()
    return 0


if __name__ == "__main__":
    sys.exit(main())
