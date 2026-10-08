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
API Metadata Generator

Parses JDK version details from build metadata, detects binary types of archives
found in BUILD_OUTPUT_DIR, computes SHA256 checksums, and produces corresponding
API metadata JSON files for use by the Adoptium API service.

Naming conventions:
- For SBOM files (*-sbom_*.json or *sbom*.json): produces *-metadata.json
- For all other archive files (e.g. *.tar.gz, *.zip, *.msi, *.pkg, *.deb, *.rpm):
  produces <filename>.json
"""

from __future__ import print_function

import argparse
import hashlib
import io
import json
import os
import re
import sys


class VersionInfo(object):
    """
    Python implementation of common.VersionInfo from Adoptium Jenkins pipelines.
    Parses Java version strings (both pre-223 / Java 8 and JEP-223 / Java 9+)
    and calculates semantic versioning and MSI product versions.
    """

    def __init__(self):
        self.major = None
        self.minor = None
        self.security = None
        self.patch = None
        self.build = None
        self.opt = None
        self.version = None
        self.pre = None
        self.adopt_build_number = None
        self.semver = None
        self.msi_product_version = None

    def parse(self, publish_name, adopt_build_number=None):
        if publish_name:
            if not self._match_pre223(publish_name):
                self._match223(publish_name)

        if adopt_build_number is not None and str(adopt_build_number).strip() != "":
            try:
                self.adopt_build_number = int(adopt_build_number)
            except ValueError:
                self.adopt_build_number = None
        elif self.opt is not None:
            # If an opt is present then set adopt_build_number to pad out the semver
            self.adopt_build_number = 0

        self.semver = self.form_semver()
        self.msi_product_version = self.form_msi_product_version()
        return self

    def _or0(self, match, group_name):
        val = match.groupdict().get(group_name)
        if val is not None:
            return int(val)
        return 0

    def _match_alt_pre223(self, version_string):
        pre223_regex = r"1\.(?P<major>[0-8])\.0(_(?P<update>[0-9]+))?(-(?P<additional>.*))?"
        m = re.search(pre223_regex, version_string)
        if m:
            self.major = self._or0(m, "major")
            self.minor = 0
            self.security = self._or0(m, "update")
            additional = m.groupdict().get("additional")
            if additional:
                for val in additional.split("-"):
                    m_build = re.match(r"b(?P<build>[0-9]+)", val)
                    if m_build:
                        self.build = int(m_build.group("build"))
                    else:
                        m_opt = re.match(r"^(?P<opt>[0-9]{12})$", val)
                        if m_opt:
                            self.opt = m_opt.group("opt")
                        else:
                            m_pre = re.match(r"^(?P<pre>[a-zA-Z0-9]+)$", val)
                            if m_pre:
                                self.pre = m_pre.group("pre")
            self.version = m.group(0)
            return True
        return False

    def _match_pre223(self, version_string):
        pre223_regex = r"jdk-?(?P<version>(?P<major>[0-8]+)(u(?P<update>[0-9]+))?(-b(?P<build>[0-9]+))(_(?P<opt>[-a-zA-Z0-9\.]+))?)"
        m = re.search(pre223_regex, version_string)
        if m:
            self.major = self._or0(m, "major")
            self.minor = 0
            self.security = self._or0(m, "update")
            self.build = self._or0(m, "build")
            if m.groupdict().get("opt"):
                self.opt = m.group("opt")
            self.version = m.group("version")
            return True
        return self._match_alt_pre223(version_string)

    def _match223(self, version_string):
        vnum_regex = r"(?P<major>[0-9]+)(\.(?P<minor>[0-9]+))?(\.(?P<security>[0-9]+))?(\.(?P<patch>[0-9]+))?"
        pre_regex = r"(?P<pre>[a-zA-Z0-9]+)"
        build_regex = r"(?P<build>[0-9]+)"
        opt_regex = r"(?P<opt>[-a-zA-Z0-9\.]+)"

        version223_patterns = [
            r"(?:jdk-)?(?P<version>" + vnum_regex + r"(-" + pre_regex + r")?\+" + build_regex + r"(-" + opt_regex + r")?)",
            r"(?:jdk-)?(?P<version>" + vnum_regex + r"-" + pre_regex + r"(-" + opt_regex + r")?)",
            r"(?:jdk-)?(?P<version>" + vnum_regex + r"(\+-" + opt_regex + r")?)",
        ]

        for pattern in version223_patterns:
            m = re.search(pattern, version_string)
            if m:
                groups = m.groupdict()
                self.major = int(groups["major"]) if groups.get("major") is not None else None
                self.minor = int(groups["minor"]) if groups.get("minor") is not None else 0
                self.security = int(groups["security"]) if groups.get("security") is not None else 0

                if groups.get("patch") is not None:
                    self.patch = int(groups["patch"])

                if groups.get("pre") is not None:
                    self.pre = groups["pre"]

                if groups.get("build") is not None:
                    self.build = int(groups["build"])

                if groups.get("opt") is not None:
                    self.opt = groups["opt"]

                self.version = groups["version"]
                return True
        return False

    def form_semver(self):
        if self.major is None:
            return None

        minor = self.minor if self.minor is not None else 0
        security = self.security if self.security is not None else 0
        semver = "{0}.{1}.{2}".format(self.major, minor, security)

        if self.pre:
            semver += "-" + self.pre

        semver += "+"
        sem_build = self.build if self.build is not None else 0

        if self.patch is not None and self.patch > 0:
            sem_build += self.patch * 100

        semver += str(sem_build)

        if self.adopt_build_number is not None:
            semver += ".{0}".format(self.adopt_build_number)

        if self.opt is not None:
            semver += ".{0}".format(self.opt)

        return semver

    def form_msi_product_version(self):
        if self.major is None:
            return None

        minor = self.minor if self.minor is not None else 0
        security = self.security if self.security is not None else 0
        product_version = "{0}.{1}.{2}".format(self.major, minor, security)

        msi_revision = self.build if self.build is not None else 0
        if self.patch is not None and self.patch > 0:
            msi_revision += self.patch * 100

        product_version += ".{0}".format(msi_revision)
        return product_version

    def as_dict(self):
        return {
            "major": self.major,
            "minor": self.minor,
            "security": self.security,
            "patch": self.patch,
            "build": self.build,
            "opt": self.opt,
            "version": self.version,
            "pre": self.pre,
            "adopt_build_number": self.adopt_build_number,
            "semver": self.semver,
            "msi_product_version": self.msi_product_version,
        }


def compute_sha256(file_path):
    """Compute SHA256 hex digest of a file in streaming chunks."""
    h = hashlib.sha256()
    with io.open(file_path, "rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def detect_binary_type(filename):
    """Classify the binary type from the filename matching openjdk_build_pipeline.groovy rules."""
    if "-jre" in filename:
        return "jre"
    if "-testimage" in filename:
        return "testimage"
    if "-debugimage" in filename:
        return "debugimage"
    if "-static-libs" in filename:
        return "staticlibs"
    if "-sources" in filename:
        return "sources"
    if "-sbom" in filename or "sbom" in filename:
        return "sbom"
    if "-jmods" in filename:
        return "jmods"
    return "jdk"


def list_archives(directory):
    """
    List all archive and SBOM files in the target directory.
    Matches .tar.gz, .zip, .msi, .pkg, .deb, .rpm, and *sbom*.json
    """
    archives = []
    if not os.path.exists(directory):
        return archives

    for root, _, files in os.walk(directory):
        for f in sorted(files):
            # Skip existing api metadata files to prevent re-processing
            if f.endswith("-metadata.json") or (f.endswith(".json") and not ("sbom" in f)):
                continue
            if (
                f.endswith(".tar.gz")
                or f.endswith(".zip")
                or f.endswith(".msi")
                or f.endswith(".pkg")
                or f.endswith(".deb")
                or f.endswith(".rpm")
                or ("sbom" in f and f.endswith(".json"))
            ):
                archives.append(os.path.join(root, f))
    return sorted(archives)


def parse_version_from_build_data(build_meta):
    """
    Derives VersionInfo by parsing full_version_output (like legacy parseVersionOutput),
    PUBLISH_NAME, or scmRef / jdk_version in order.
    """
    adopt_build_number = os.environ.get("ADOPT_BUILD_NUMBER", "").strip()
    if not adopt_build_number and "BUILD_CONFIGURATION_param" in build_meta:
        try:
            bconf = json.loads(build_meta["BUILD_CONFIGURATION_param"])
            if isinstance(bconf, dict):
                adopt_build_number = str(bconf.get("ADOPT_BUILD_NUMBER", "")).strip()
        except Exception:
            pass

    version_str = ""
    # 1. First priority: full_version_output runtime environment build string (matches legacy parseVersionOutput)
    if build_meta.get("full_version_output"):
        m = re.search(r"Runtime Environment[^\n]*\(build (?P<version>[^\)]*)\)", build_meta["full_version_output"], re.MULTILINE)
        if m:
            version_str = m.group("version").strip()
        else:
            m = re.search(r"\(build ([^\)]+)\)", build_meta["full_version_output"])
            if m:
                version_str = m.group(1).strip()

    # 2. Second priority: PUBLISH_NAME
    if not version_str:
        version_str = os.environ.get("PUBLISH_NAME", "").strip()
        if not version_str and "BUILD_CONFIGURATION_param" in build_meta:
            try:
                bconf = json.loads(build_meta["BUILD_CONFIGURATION_param"])
                if isinstance(bconf, dict):
                    version_str = bconf.get("PUBLISH_NAME", "").strip()
            except Exception:
                pass

    # 3. Third priority: scmRef or jdk_version
    if not version_str:
        version_str = build_meta.get("scmRef") or build_meta.get("jdk_version") or ""
        version_str = version_str.replace("_adopt", "")

    v_info = VersionInfo()
    v_info.parse(version_str, adopt_build_number)
    return v_info


def generate_metadata(build_metadata_path, artifacts_dir, output_dir=None):
    """
    Reads build-metadata.json, lists archives in artifacts_dir,
    and writes out api metadata JSON files for each archive.
    """
    if not os.path.exists(build_metadata_path):
        raise IOError("Build metadata file not found: {0}".format(build_metadata_path))

    with io.open(build_metadata_path, "r", encoding="utf-8") as fh:
        build_meta = json.load(fh)

    out_dir = output_dir or artifacts_dir
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)

    version_info = parse_version_from_build_data(build_meta)
    archives = list_archives(artifacts_dir)

    print("Found {0} archive(s) to generate API metadata for in {1}".format(len(archives), artifacts_dir))

    generated_files = []
    first_output = True

    # Build reference mapping
    build_ref_val = build_meta.get("buildRef") or ""
    build_repo_url = build_meta.get("buildRepoUrl") or ""
    if build_ref_val and build_repo_url:
        if not build_ref_val.startswith("http") and "commit" not in build_ref_val:
            repo_base = build_repo_url.replace(".git", "")
            build_ref_val = "{0}/commit/{1}".format(repo_base, build_ref_val)

    # Resolve version_data (e.g. jdk21, jdk21u, jdk8u)
    version_data = os.environ.get("CONFIG_JAVA_TO_BUILD") or build_meta.get("javaVersion") or build_meta.get("jdk_version") or ""
    if not version_data and version_info.major:
        version_data = "jdk{0}".format(version_info.major)

    vendor = build_meta.get("vendor") or os.environ.get("VENDOR") or os.environ.get("CONFIG_VENDOR") or ""
    os_name = os.environ.get("CONFIG_TARGET_OS") or build_meta.get("targetOS") or ""
    arch_name = os.environ.get("CONFIG_ARCHITECTURE") or build_meta.get("architecture") or ""
    variant = os.environ.get("CONFIG_VARIANT") or build_meta.get("variant") or ""
    scm_ref = build_meta.get("scmRef") or os.environ.get("SCM_REF") or ""

    for arch_file in archives:
        filename = os.path.basename(arch_file)
        b_type = detect_binary_type(filename)
        sha256_hash = compute_sha256(arch_file)

        metadata_record = {
            "vendor": vendor,
            "os": os_name,
            "arch": arch_name,
            "variant": variant,
            "version": version_info.as_dict(),
            "scmRef": scm_ref,
            "buildRef": build_ref_val,
            "version_data": version_data,
            "binary_type": b_type,
            "sha256": sha256_hash,
            "full_version_output": build_meta.get("full_version_output", ""),
            "makejdk_any_platform_args": build_meta.get("makejdk_any_platform_args", ""),
            "configure_arguments": build_meta.get("configure_arguments", ""),
            "make_command_args": build_meta.get("make_command_args", ""),
            "BUILD_CONFIGURATION_param": build_meta.get("BUILD_CONFIGURATION_param", ""),
            "openjdk_built_config": build_meta.get("openjdk_built_config", ""),
            "openjdk_source": build_meta.get("openjdk_source") or build_meta.get("openjdkSource") or "",
            "build_env_docker_image_digest": build_meta.get("build_env_docker_image_digest", ""),
            "dependency_version_alsa": build_meta.get("dependency_version_alsa", ""),
            "dependency_version_freetype": build_meta.get("dependency_version_freetype", ""),
            "dependency_version_freemarker": build_meta.get("dependency_version_freemarker", ""),
        }

        # Include variant_version if present
        if build_meta.get("variant_version"):
            # Only include if any field has value
            v_ver = build_meta["variant_version"]
            if any(v_ver.values()):
                metadata_record["variant_version"] = v_ver

        # Output metadata file naming
        # Special handling for sbom metadata file: from *sbom<XXX>.json to *sbom<XXX>-metadata.json
        if "sbom" in filename and filename.endswith(".json"):
            meta_filename = filename.replace(".json", "-metadata.json")
        else:
            meta_filename = filename + ".json"

        # Determine relative path from artifacts_dir if nested
        rel_path = os.path.relpath(os.path.dirname(arch_file), artifacts_dir)
        target_subfolder = os.path.normpath(os.path.join(out_dir, rel_path))
        if not os.path.exists(target_subfolder):
            os.makedirs(target_subfolder)

        meta_filepath = os.path.join(target_subfolder, meta_filename)

        with io.open(meta_filepath, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(metadata_record, indent=2, ensure_ascii=True) + u"\n")

        generated_files.append(meta_filepath)

        # For archive binaries (.tar.gz, .zip, .pkg, .msi), also write <filename>.sha256.txt
        # Format matches sha256sum output: "<sha256>  <filename>\n" or "<sha256> *<filename>\n" or "<sha256>  <filename>"
        # Legacy pipeline: sha256sum "$file" > $file.sha256.txt
        if not (filename.endswith(".json")):
            sha_txt_filename = filename + ".sha256.txt"
            sha_txt_filepath = os.path.join(target_subfolder, sha_txt_filename)
            with io.open(sha_txt_filepath, "w", encoding="utf-8") as fh:
                fh.write(u"{0}  {1}\n".format(sha256_hash, filename))
            generated_files.append(sha_txt_filepath)
            print("Created SHA256 checksum file: {0}".format(sha_txt_filename))

        if first_output:
            print("=== SAMPLE METADATA OUTPUT ({0}) ===".format(meta_filename))
            print(json.dumps(metadata_record, indent=2))
            print("=== END SAMPLE METADATA OUTPUT ===")
            first_output = False

        print("Created API metadata: {0} (type: {1}, sha256: {2})".format(meta_filename, b_type, sha256_hash))

    return generated_files


def main():
    parser = argparse.ArgumentParser(
        description="Generate Adoptium API metadata JSON files for built artifacts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--build-metadata",
        required=True,
        help="Path to build-metadata.json from 020-build stage",
    )
    parser.add_argument(
        "--artifacts-dir",
        required=True,
        help="Directory containing build output archives",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Destination directory for created metadata files (defaults to artifacts-dir)",
    )

    args = parser.parse_args()
    try:
        generate_metadata(args.build_metadata, args.artifacts_dir, args.output_dir)
    except Exception as e:
        print("ERROR: {0}".format(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
