#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for scripts/lib/build-metadata-writer.py including Python 2.6 compatibility checks.
"""

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


class TestBuildMetadataWriter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.output_json = os.path.join(self.temp_dir, "build-metadata.json")
        self.meta_dir = os.path.join(self.temp_dir, "metadata")
        self.config_dir = os.path.join(self.temp_dir, "config")
        self.variant_version_dir = os.path.join(self.meta_dir, "variant_version")
        os.makedirs(self.variant_version_dir)
        os.makedirs(self.config_dir)

        self.repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.writer_script = os.path.join(self.repo_root, "scripts", "lib", "build-metadata-writer.py")

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_writer_with_files_and_multiline_version(self):
        # Create metadata files with multiline contents
        version_txt = "openjdk version \"21.0.8\" 2026-07-21\nOpenJDK Runtime Environment (build 21.0.8+7)\n"
        with open(os.path.join(self.meta_dir, "version.txt"), "w") as f:
            f.write(version_txt)

        with open(os.path.join(self.meta_dir, "scmref.txt"), "w") as f:
            f.write("jdk-21.0.8+7_adopt\n")

        with open(os.path.join(self.meta_dir, "configure.txt"), "w") as f:
            f.write("--with-debug-level=release\n--with-jvm-variants=server\n")

        with open(os.path.join(self.meta_dir, "makeCommandArg.txt"), "w") as f:
            f.write("make images\n")

        with open(os.path.join(self.meta_dir, "vendor.txt"), "w") as f:
            f.write("Eclipse Adoptium")

        with open(os.path.join(self.meta_dir, "buildSource.txt"), "w") as f:
            f.write("https://github.com/adoptium/temurin-build.git")

        with open(os.path.join(self.meta_dir, "openjdkSource.txt"), "w") as f:
            f.write("https://github.com/adoptium/jdk21u")

        with open(os.path.join(self.config_dir, "built_config.cfg"), "w") as f:
            f.write("CONFIG_PARAM=1\nCONFIG_PARAM2=2\n")

        with open(os.path.join(self.config_dir, "makejdk-any-platform.args"), "w") as f:
            f.write("--clean-docker-build\n")

        with open(os.path.join(self.meta_dir, "dependency_version_alsa.txt"), "w") as f:
            f.write("1.0.29")

        with open(os.path.join(self.meta_dir, "dependency_version_freetype.txt"), "w") as f:
            f.write("2.10.4")

        with open(os.path.join(self.meta_dir, "dependency_version_freemarker.txt"), "w") as f:
            f.write("2.3.31")

        with open(os.path.join(self.variant_version_dir, "major.txt"), "w") as f:
            f.write("21")
        with open(os.path.join(self.variant_version_dir, "minor.txt"), "w") as f:
            f.write("0")
        with open(os.path.join(self.variant_version_dir, "security.txt"), "w") as f:
            f.write("8")
        with open(os.path.join(self.variant_version_dir, "tags.txt"), "w") as f:
            f.write("7")

        config_file = os.path.join(self.temp_dir, "pipeline-config.json")
        with open(config_file, "w") as f:
            json.dump({"test": "pipeline_config"}, f)

        cmd = [
            "python3",
            self.writer_script,
            "--output", self.output_json,
            "--metadata-dir", self.meta_dir,
            "--config-dir", self.config_dir,
            "--config-file", config_file,
            "--jdk-version", "jdk21u",
            "--release-type", "NIGHTLY",
            "--build-number", "100",
            "--stage", "build",
            "--workspace", self.temp_dir,
            "--build-uid", "uid-123",
            "--group-uid", "guid-456",
            "--build-ref", "master",
            "--build-repo-url", "https://github.com/adoptium/temurin-build.git",
            "--docker-image-digest", "sha256:abc123",
        ]

        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Script failed: {res.stderr}")

        # Verify output JSON can be loaded without any Invalid control character error
        with open(self.output_json, "r") as f:
            data = json.load(f)

        self.assertEqual(data["jdk_version"], "jdk21u")
        self.assertEqual(data["releaseType"], "NIGHTLY")
        self.assertEqual(data["buildNumber"], "100")
        self.assertEqual(data["buildUid"], "uid-123")
        self.assertEqual(data["groupUid"], "guid-456")
        self.assertEqual(data["stage"], "build")
        self.assertEqual(data["workspace"], self.temp_dir)
        self.assertEqual(data["buildRef"], "master")
        self.assertEqual(data["vendor"], "Eclipse Adoptium")
        self.assertEqual(data["scmRef"], "jdk-21.0.8+7_adopt")
        self.assertEqual(data["full_version_output"], version_txt)
        self.assertEqual(data["configure_arguments"], "--with-debug-level=release\n--with-jvm-variants=server\n")
        self.assertEqual(data["make_command_args"], "make images\n")
        self.assertEqual(data["openjdk_built_config"], "CONFIG_PARAM=1\nCONFIG_PARAM2=2\n")
        self.assertEqual(data["dependency_version_alsa"], "1.0.29")
        self.assertEqual(data["build_env_docker_image_digest"], "sha256:abc123")
        self.assertEqual(data["variant_version"]["major"], "21")
        self.assertEqual(data["variant_version"]["tags"], "7")
        self.assertIn("pipeline_config", data["BUILD_CONFIGURATION_param"])

    def test_optparse_fallback_when_argparse_unavailable(self):
        """Simulate Python 2.6 environment where argparse is not installed."""
        script_code = """
import sys
# Block argparse import
sys.modules['argparse'] = None

# Import build-metadata-writer module directly
sys.path.insert(0, sys.argv[1])
import importlib
bmw = importlib.import_module('build-metadata-writer')

# Test _parse_args with optparse fallback
args = bmw._parse_args([
    '--output', sys.argv[2],
    '--jdk-version', 'jdk17u',
    '--build-number', '42',
    '--stage', 'build',
    '--workspace', '/tmp/test'
])
bmw.BuildMetadataWriter(args).write()
"""
        cmd = [
            sys.executable,
            "-c",
            script_code,
            os.path.dirname(self.writer_script),
            self.output_json,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"Optparse fallback execution failed: {res.stderr}")

        with open(self.output_json, "r") as f:
            data = json.load(f)
        self.assertEqual(data["jdk_version"], "jdk17u")
        self.assertEqual(data["buildNumber"], "42")

    def test_python26_ast_and_syntax_compatibility(self):
        """
        Validate that build-metadata-writer.py uses only syntax, AST structures,
        and imports valid in Python 2.6.
        """
        with open(self.writer_script, "r") as f:
            source = f.read()

        tree = ast.parse(source, filename=self.writer_script)

        # Disallowed AST nodes introduced in Python 3.0+
        disallowed_types = (
            "JoinedStr",        # f-strings (3.6+)
            "FormattedValue",   # f-strings (3.6+)
            "AnnAssign",        # Type annotations (3.6+)
            "AsyncFunctionDef", # async def (3.5+)
            "AsyncFor",         # async for (3.5+)
            "AsyncWith",        # async with (3.5+)
            "Await",            # await (3.5+)
            "YieldFrom",        # yield from (3.3+)
            "NamedExpr",        # walrus := (3.8+)
            "Match",            # match / case (3.10+)
            "MatchCase",
        )

        allowed_modules = {
            "__future__",
            "io",
            "json",
            "os",
            "sys",
            "time",
            "optparse",
            "argparse",
        }

        for node in ast.walk(tree):
            node_type = type(node).__name__
            self.assertNotIn(
                node_type,
                disallowed_types,
                f"Found Python 3-only construct '{node_type}' at line {getattr(node, 'lineno', '?')}",
            )

            # Check function arguments for type annotations
            if isinstance(node, (ast.FunctionDef,)):
                for arg in getattr(node.args, "args", []):
                    if hasattr(arg, "annotation") and arg.annotation is not None:
                        self.fail(f"Type annotation found on arg '{arg.arg}' at line {node.lineno}")
                if getattr(node, "returns", None) is not None:
                    self.fail(f"Return type annotation found on function '{node.name}' at line {node.lineno}")

            # Check imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod_root = alias.name.split(".")[0]
                    self.assertIn(
                        mod_root,
                        allowed_modules,
                        f"Module '{alias.name}' at line {node.lineno} is not in Python 2.6 standard library",
                    )
            elif isinstance(node, ast.ImportFrom):
                mod_root = (node.module or "").split(".")[0]
                self.assertIn(
                    mod_root,
                    allowed_modules,
                    f"Module '{node.module}' at line {node.lineno} is not in Python 2.6 standard library",
                )


if __name__ == "__main__":
    unittest.main()
