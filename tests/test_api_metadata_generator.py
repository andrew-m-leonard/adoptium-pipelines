#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for scripts/lib/api-metadata-generator.py
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

import importlib.util

lib_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts", "lib", "api-metadata-generator.py"))
spec = importlib.util.spec_from_file_location("api_metadata_generator", lib_path)
api_metadata_generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api_metadata_generator)

VersionInfo = api_metadata_generator.VersionInfo
compute_sha256 = api_metadata_generator.compute_sha256
detect_binary_type = api_metadata_generator.detect_binary_type
generate_metadata = api_metadata_generator.generate_metadata


class TestVersionInfo(unittest.TestCase):
    def test_version_parsing_weekly_ea(self):
        v = VersionInfo()
        v.parse("21.0.13-beta+8-ea", "")
        self.assertEqual(v.major, 21)
        self.assertEqual(v.minor, 0)
        self.assertEqual(v.security, 13)
        self.assertIsNone(v.patch)
        self.assertEqual(v.build, 8)
        self.assertEqual(v.opt, "ea")
        self.assertEqual(v.pre, "beta")
        self.assertEqual(v.adopt_build_number, 0)
        self.assertEqual(v.version, "21.0.13-beta+8-ea")
        self.assertEqual(v.semver, "21.0.13-beta+8.0.ea")
        self.assertEqual(v.msi_product_version, "21.0.13.8")

    def test_version_parsing_release(self):
        v = VersionInfo()
        v.parse("27+35", "")
        self.assertEqual(v.major, 27)
        self.assertEqual(v.minor, 0)
        self.assertEqual(v.security, 0)
        self.assertIsNone(v.patch)
        self.assertEqual(v.build, 35)
        self.assertIsNone(v.opt)
        self.assertIsNone(v.pre)
        self.assertIsNone(v.adopt_build_number)
        self.assertEqual(v.version, "27+35")
        self.assertEqual(v.semver, "27.0.0+35")
        self.assertEqual(v.msi_product_version, "27.0.0.35")

    def test_version_parsing_jdk8(self):
        v = VersionInfo()
        v.parse("1.8.0_272-b10", "")
        self.assertEqual(v.major, 8)
        self.assertEqual(v.minor, 0)
        self.assertEqual(v.security, 272)
        self.assertEqual(v.build, 10)

    def test_binary_type_detection(self):
        self.assertEqual(detect_binary_type("OpenJDK21U-jdk_x64_alpine-linux_hotspot_21.0.13_8-ea.tar.gz"), "jdk")
        self.assertEqual(detect_binary_type("OpenJDK21U-jre_x64_linux_hotspot_21.0.13_8.tar.gz"), "jre")
        self.assertEqual(detect_binary_type("OpenJDK21U-testimage_x64_windows_hotspot_21.0.9_10.zip"), "testimage")
        self.assertEqual(detect_binary_type("OpenJDK21U-debugimage_x64_mac_hotspot_21.0.9_10.tar.gz"), "debugimage")
        self.assertEqual(detect_binary_type("OpenJDK21U-static-libs_x64_linux_hotspot_21.0.9_10.tar.gz"), "staticlibs")
        self.assertEqual(detect_binary_type("OpenJDK21U-sources_21.0.9_10.tar.gz"), "sources")
        self.assertEqual(detect_binary_type("OpenJDK21U-sbom_ppc64_aix_hotspot_21.0.9_10.json"), "sbom")
        self.assertEqual(detect_binary_type("OpenJDK21U-jmods_x64_linux_hotspot_21.0.9_10.tar.gz"), "jmods")


class TestApiMetadataGenerator(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.artifacts_dir = os.path.join(self.test_dir, "build_output")
        os.makedirs(self.artifacts_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_metadata_generation(self):
        # Create dummy artifacts
        jdk_archive = os.path.join(self.artifacts_dir, "OpenJDK21U-jdk_x64_alpine-linux_hotspot_21.0.13_8-ea.tar.gz")
        with open(jdk_archive, "wb") as f:
            f.write(b"dummy jdk content")

        sbom_file = os.path.join(self.artifacts_dir, "OpenJDK21U-sbom_x64_alpine-linux_hotspot_21.0.13_8-ea.json")
        with open(sbom_file, "wb") as f:
            f.write(b'{"bomFormat": "CycloneDX"}')

        # Create dummy build-metadata.json
        build_meta_path = os.path.join(self.test_dir, "build-metadata.json")
        build_meta = {
            "vendor": "Eclipse Adoptium",
            "targetOS": "alpine-linux",
            "architecture": "x64",
            "variant": "temurin",
            "scmRef": "jdk-21.0.13+8_adopt",
            "buildRef": "https://github.com/adoptium/temurin-build/commit/cc31225e0aad72a5598d94e174cdd5c09e0d85a8",
            "javaVersion": "jdk21u",
            "full_version_output": 'openjdk version "21.0.13-beta" 2026-10-20\nOpenJDK Runtime Environment Temurin-21.0.13+8-202609301109 (build 21.0.13-beta+8-ea)\n',
            "makejdk_any_platform_args": "some args",
            "configure_arguments": "some config",
            "make_command_args": "make all",
            "BUILD_CONFIGURATION_param": json.dumps({"PUBLISH_NAME": "jdk-21.0.13+8-ea"}),
            "openjdk_built_config": "config content",
            "openjdk_source": "https://github.com/adoptium/jdk21u/commit/d6a2e06c2bce0268c601f3dc1b39f5d93721e605",
            "build_env_docker_image_digest": "adoptopenjdk/alpine3_build_image@sha256:e9ba1a90",
            "dependency_version_alsa": "https://example.com/alsa.tar.bz2",
            "dependency_version_freetype": "",
            "dependency_version_freemarker": "",
        }
        with open(build_meta_path, "w") as f:
            json.dump(build_meta, f)

        # Generate metadata
        generated = generate_metadata(build_meta_path, self.artifacts_dir)
        self.assertEqual(len(generated), 2)

        jdk_json_path = jdk_archive + ".json"
        sbom_meta_path = os.path.join(self.artifacts_dir, "OpenJDK21U-sbom_x64_alpine-linux_hotspot_21.0.13_8-ea-metadata.json")

        self.assertTrue(os.path.exists(jdk_json_path))
        self.assertTrue(os.path.exists(sbom_meta_path))

        with open(jdk_json_path, "r") as f:
            data = json.load(f)
            self.assertEqual(data["vendor"], "Eclipse Adoptium")
            self.assertEqual(data["os"], "alpine-linux")
            self.assertEqual(data["arch"], "x64")
            self.assertEqual(data["variant"], "temurin")
            self.assertEqual(data["binary_type"], "jdk")
            self.assertEqual(data["version"]["major"], 21)
            self.assertEqual(data["version"]["minor"], 0)
            self.assertEqual(data["version"]["security"], 13)
            self.assertEqual(data["version"]["opt"], "ea")
            self.assertEqual(data["version"]["pre"], "beta")
            self.assertEqual(data["version"]["semver"], "21.0.13-beta+8.0.ea")
            self.assertEqual(data["sha256"], compute_sha256(jdk_archive))

        with open(sbom_meta_path, "r") as f:
            data = json.load(f)
            self.assertEqual(data["binary_type"], "sbom")
            self.assertEqual(data["sha256"], compute_sha256(sbom_file))


if __name__ == "__main__":
    unittest.main()
