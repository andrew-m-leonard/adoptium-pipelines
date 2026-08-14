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
CLI argument parser for the local pipeline runner.

Provides PipelineArgParser which owns all argparse setup, the dynamic
stage-params epilog construction, and post-parse validation (jdk-version
format, bad single-dash tokens).

Usage:
    parser = PipelineArgParser(script_dir, local_stages)
    args, extra_tokens = parser.parse()
"""

import argparse
import re
import sys
from pathlib import Path

from lib.stage_params import build_stage_params_help


_EXAMPLES = """
Examples:
  # Standard nightly build
  python3 run-pipeline.py --jdk-version jdk21 --target-os mac --architecture aarch64 \\
      --config-repo-url https://github.com/adoptium/ci-temurin-config.git

  # Release build with reproducible compare, pinned source tag
  python3 run-pipeline.py \\
      --jdk-version jdk21 --target-os linux --architecture x64 \\
      --config-repo-url https://github.com/adoptium/ci-temurin-config.git \\
      --release-type RELEASE \\
      --scm-ref jdk-21.0.7+6_adopt \\
      --run-reproducible-compare true
"""


class PipelineArgParser:
    """Builds and owns the argparse parser for run-pipeline.py."""

    def __init__(self, script_dir: Path, local_stages: list[str]):
        """
        Args:
            script_dir:   Root of the ci-adoptium-pipelines checkout.
            local_stages: Ordered list of stage IDs the local runner executes.
                          Used for --start-from-stage choices and the dynamic
                          stage-params epilog in --help output.
        """
        self._script_dir = script_dir
        self._local_stages = local_stages

    def _build_parser(self, stage_params_epilog: str) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description="Run OpenJDK build pipeline locally",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog=_EXAMPLES + stage_params_epilog,
        )

        # ── Required ──────────────────────────────────────────────────────────
        parser.add_argument(
            "--jdk-version",
            required=True,
            help="JDK version to build (e.g., jdk21, jdk8). Format: jdkNN.",
        )
        parser.add_argument(
            "--target-os",
            required=True,
            choices=["mac", "linux", "windows", "aix"],
            help="Target operating system",
        )
        parser.add_argument(
            "--architecture",
            required=True,
            choices=["aarch64", "x64", "x32", "ppc64", "s390x"],
            help="Target architecture",
        )

        # ── Pipeline / workspace control ──────────────────────────────────────
        parser.add_argument(
            "--workspace",
            default="~/openjdk-build",
            help="Workspace directory (default: ~/openjdk-build)",
        )
        parser.add_argument(
            "--build-number",
            help="Build number (default: local-YYYYMMDD-HHMMSS)",
        )
        parser.add_argument(
            "--clean-workspace",
            action="store_true",
            help="Remove existing workspace before starting (ensures clean build)",
        )
        parser.add_argument(
            "--start-from-stage",
            choices=self._local_stages,
            help="Start pipeline from a specific stage (skips earlier stages)",
        )

        # ── Release / build type ──────────────────────────────────────────────
        parser.add_argument(
            "--release-type",
            type=str,
            help="Type of release build: NIGHTLY (default), WEEKLY, or RELEASE",
        )

        # ── Configuration repository ──────────────────────────────────────────
        parser.add_argument(
            "--config-repo-url",
            required=True,
            help="Configuration repository URL",
        )
        parser.add_argument(
            "--config-repo-branch",
            default="main",
            help="Configuration repository branch (default: main)",
        )

        return parser

    def parse(self) -> tuple:
        """
        Parse sys.argv and return (args, extra_tokens).

        Builds the --help epilog (including dynamic stage params) before
        creating the parser so that --help always shows the full param list.

        parse_known_args is used so that stage params (--scm-ref, --run-tests,
        etc.) are captured as extra_tokens and validated separately after
        Initialize has cloned the config repo and params are fully collated.

        Returns:
            (args, extra_tokens) where extra_tokens is a flat list of raw
            unknown argument strings.

        Raises:
            SystemExit: On --help or any argparse error.
        """
        # Build the dynamic stage-params epilog only when --help is requested.
        # build_stage_params_help is a no-op when --help is not in sys.argv.
        stage_params_epilog = build_stage_params_help(
            self._script_dir, sys.argv, self._local_stages
        )

        parser = self._build_parser(stage_params_epilog)
        args, extra_tokens = parser.parse_known_args()

        # Validate --jdk-version format
        if not re.match(r"^jdk\d+$", args.jdk_version):
            parser.error(
                f"Invalid --jdk-version format: '{args.jdk_version}'. "
                f"Must be in format jdkNN (e.g., jdk21, jdk8)."
            )

        # Syntax-only pre-check: reject single-dash flags that can never be
        # valid stage params (e.g. -dsfsdfsdf).
        bad_tokens = [t for t in extra_tokens if t.startswith("-") and not t.startswith("--")]
        if bad_tokens:
            parser.error(
                f"Unrecognised argument(s): {' '.join(bad_tokens)}\n"
                f"Stage parameters must use --<lower-kebab-case-name> <value> syntax.\n"
                f"Run with --help to see all available parameters."
            )

        return args, extra_tokens
