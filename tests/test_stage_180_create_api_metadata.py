#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integration test running 180-create-api-metadata.sh in bash environment
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest


class TestCreateApiMetadataStage(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.mkdtemp()
        self.repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.build_output_dir = os.path.join(self.workspace, "build_output")
        os.makedirs(self.build_output_dir)

    def tearDown(self):
        shutil.rmtree(self.workspace)

    def test_stage_execution(self):
        # Create artifacts
        test_tar = os.path.join(self.build_output_dir, "OpenJDK27U-jdk_ppc64_aix_hotspot_27_35.tar.gz")
        with open(test_tar, "wb") as f:
            f.write(b"tar binary data")

        sbom_file = os.path.join(self.build_output_dir, "OpenJDK27U-sbom_ppc64_aix_hotspot_27_35.json")
        with open(sbom_file, "wb") as f:
            f.write(b"sbom content")

        build_meta_path = os.path.join(self.workspace, "build-metadata.json")
        build_meta = {
            "vendor": "Eclipse Adoptium",
            "targetOS": "aix",
            "architecture": "ppc64",
            "variant": "temurin",
            "scmRef": "jdk-27+35_adopt",
            "buildRef": "https://github.com/adoptium/temurin-build/commit/cc31225e0aad72a5598d94e174cdd5c09e0d85a8",
            "javaVersion": "jdk27",
            "full_version_output": "openjdk version \"27\" 2026-09-15\nOpenJDK Runtime Environment Temurin-27+35 (build 27+35)\nOpenJDK 64-Bit Server VM Temurin-27+35 (build 27+35, mixed mode)\n",
            "makejdk_any_platform_args": "some args",
            "configure_arguments": "some config",
            "make_command_args": "make all",
            "BUILD_CONFIGURATION_param": json.dumps({"PUBLISH_NAME": "jdk-27+35"}),
            "openjdk_built_config": "built config",
            "openjdk_source": "https://github.com/adoptium/jdk/commit/efe86855fd73e30932993700813258c78b12b1c7",
            "build_env_docker_image_digest": "",
            "dependency_version_alsa": "",
            "dependency_version_freetype": "",
            "dependency_version_freemarker": "",
        }
        with open(build_meta_path, "w") as f:
            json.dump(build_meta, f)

        # Config file
        config_file = os.path.join(self.workspace, "pipeline-config.json")
        with open(config_file, "w") as f:
            json.dump({"test": "config"}, f)

        target_dir = os.path.join(self.workspace, "target")
        os.makedirs(target_dir)

        env = os.environ.copy()
        env["WORKSPACE"] = self.workspace
        env["PIPELINE_ROOT"] = self.repo_root
        env["CONFIG_FILE"] = config_file
        env["INPUT_ARTIFACTS_DIR"] = self.workspace
        env["TARGET_DIR"] = target_dir
        env["BUILD_NUMBER"] = "42"
        env["BUILD_OUTPUT_DIR"] = "build_output"
        env["CONFIG_TARGET_OS"] = "aix"
        env["CONFIG_ARCHITECTURE"] = "ppc64"
        env["CONFIG_VARIANT"] = "temurin"
        env["CONFIG_JAVA_TO_BUILD"] = "jdk27"

        script_path = os.path.join(self.repo_root, "scripts", "stages", "180-create-api-metadata.sh")
        proc = subprocess.run(["bash", script_path], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        self.assertEqual(proc.returncode, 0, f"Script failed: {proc.stderr}\n{proc.stdout}")

        # Verify output files in target_dir/build_output
        expected_json = os.path.join(target_dir, "build_output", "OpenJDK27U-jdk_ppc64_aix_hotspot_27_35.tar.gz.json")
        expected_sha = os.path.join(target_dir, "build_output", "OpenJDK27U-jdk_ppc64_aix_hotspot_27_35.tar.gz.sha256.txt")
        expected_sbom_meta = os.path.join(target_dir, "build_output", "OpenJDK27U-sbom_ppc64_aix_hotspot_27_35-metadata.json")
        stage_meta_ws = os.path.join(self.workspace, "stage-metadata.json")

        self.assertTrue(os.path.exists(expected_json))
        self.assertTrue(os.path.exists(expected_sha))
        self.assertTrue(os.path.exists(expected_sbom_meta))
        self.assertTrue(os.path.exists(stage_meta_ws))

        with open(expected_json, "r") as f:
            data = json.load(f)
            self.assertEqual(data["vendor"], "Eclipse Adoptium")
            self.assertEqual(data["version"]["major"], 27)
            self.assertEqual(data["version"]["build"], 35)
            self.assertEqual(data["version"]["semver"], "27.0.0+35")
            self.assertEqual(data["binary_type"], "jdk")


if __name__ == "__main__":
    unittest.main()
