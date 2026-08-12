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
Batch converter for legacy Groovy pipeline configurations to JSON format.

This tool helps vendors migrate from legacy Groovy-based pipeline configurations
to the new JSON-based configuration format used by the declarative pipeline.

Usage:
    # Convert all configs in a directory
    python3 batch-convert-groovy-configs.py --source /path/to/groovy/configs --output /path/to/json/configs

    # Convert with custom pattern
    python3 batch-convert-groovy-configs.py --source ./configs --output ./json --pattern "*_config.groovy"

    # Dry run to see what would be converted
    python3 batch-convert-groovy-configs.py --source ./configs --output ./json --dry-run

    # Verbose output
    python3 batch-convert-groovy-configs.py --source ./configs --output ./json --verbose
"""

import argparse
import sys
from pathlib import Path
import subprocess


def find_converter_script() -> Path:
    """Find the groovy-pipeline-config-to-json.py script."""
    # Try current directory first
    script_dir = Path(__file__).parent
    converter = script_dir / "groovy-pipeline-config-to-json.py"

    if converter.exists():
        return converter

    # Try parent directory
    converter = script_dir.parent / "tools" / "groovy-pipeline-config-to-json.py"
    if converter.exists():
        return converter

    raise FileNotFoundError(
        "Could not find groovy-pipeline-config-to-json.py script. "
        "Please ensure it's in the same directory as this script."
    )


def find_groovy_configs(source_dir: Path, pattern: str) -> list[Path]:
    """Find all Groovy configuration files matching the pattern."""
    if not source_dir.exists():
        raise FileNotFoundError(f"Source directory not found: {source_dir}")

    if not source_dir.is_dir():
        raise NotADirectoryError(f"Source path is not a directory: {source_dir}")

    # Find all matching files
    configs = sorted(source_dir.glob(pattern))

    if not configs:
        raise FileNotFoundError(
            f"No Groovy configuration files found in {source_dir} "
            f"matching pattern '{pattern}'"
        )

    return configs


def convert_config(
    converter: Path, input_file: Path, output_file: Path, verbose: bool = False
) -> tuple[bool, str]:
    """Convert a single Groovy config to JSON."""
    try:
        # Run the converter
        result = subprocess.run(
            ["python3", str(converter), str(input_file), str(output_file)],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode == 0:
            return True, result.stdout
        else:
            error_msg = result.stderr or result.stdout or "Unknown error"
            return False, error_msg

    except Exception as e:
        return False, str(e)


def main():
    parser = argparse.ArgumentParser(
        description="Batch convert legacy Groovy pipeline configurations to JSON format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert all configs from ci-jenkins-pipelines to ci-temurin-config
  %(prog)s --source ../ci-jenkins-pipelines/pipelines/jobs/configurations \\
           --output ../ci-temurin-config/configurations

  # Convert with custom pattern
  %(prog)s --source ./my-configs --output ./json-configs \\
           --pattern "jdk*_pipeline_config.groovy"

  # Dry run to preview what would be converted
  %(prog)s --source ./configs --output ./json --dry-run

  # Verbose output with detailed conversion info
  %(prog)s --source ./configs --output ./json --verbose
        """,
    )

    parser.add_argument(
        "--source",
        "-s",
        type=Path,
        required=True,
        help="Source directory containing Groovy configuration files",
    )

    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        required=True,
        help="Output directory for JSON configuration files",
    )

    parser.add_argument(
        "--pattern",
        "-p",
        type=str,
        default="*_pipeline_config.groovy",
        help="Glob pattern for Groovy config files (default: *_pipeline_config.groovy)",
    )

    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Show what would be converted without actually converting",
    )

    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show detailed conversion output"
    )

    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Overwrite existing JSON files without prompting",
    )

    args = parser.parse_args()

    # Print header
    print("=" * 70)
    print("Legacy Groovy to JSON Configuration Converter")
    print("=" * 70)
    print()

    try:
        # Find the converter script
        converter = find_converter_script()
        if args.verbose:
            print(f"Using converter: {converter}")
            print()

        # Find all Groovy configs
        print(f"Scanning: {args.source}")
        print(f"Pattern:  {args.pattern}")
        configs = find_groovy_configs(args.source, args.pattern)
        print(f"Found:    {len(configs)} configuration file(s)")
        print()

        # Create output directory if it doesn't exist
        if not args.dry_run:
            args.output.mkdir(parents=True, exist_ok=True)

        # List files to be converted
        if args.dry_run:
            print("DRY RUN - No files will be converted")
            print()
            print("Files that would be converted:")
            for config in configs:
                output_file = args.output / config.with_suffix(".json").name
                print(f"  {config.name} -> {output_file.name}")
            print()
            print(f"Output directory: {args.output}")
            return 0

        # Convert each file
        print(f"Converting to: {args.output}")
        print()

        success_count = 0
        failed_count = 0
        failed_files = []

        for i, config in enumerate(configs, 1):
            output_file = args.output / config.with_suffix(".json").name

            # Check if output file exists
            if output_file.exists() and not args.force:
                print(
                    f"[{i}/{len(configs)}] Skipping {config.name} (output exists, use --force to overwrite)"
                )
                continue

            print(
                f"[{i}/{len(configs)}] Converting {config.name}...", end=" ", flush=True
            )

            success, message = convert_config(
                converter, config, output_file, args.verbose
            )

            if success:
                print("✅")
                success_count += 1
                if args.verbose:
                    print(f"  Output: {output_file}")
                    print(message)
            else:
                print("❌")
                failed_count += 1
                failed_files.append((config.name, message))
                print(f"  Error: {message}")

        # Print summary
        print()
        print("=" * 70)
        print("Conversion Summary")
        print("=" * 70)
        print(f"Total:   {len(configs)}")
        print(f"Success: {success_count}")
        print(f"Failed:  {failed_count}")
        print()

        if failed_files:
            print("Failed conversions:")
            for filename, error in failed_files:
                print(f"  ❌ {filename}")
                print(f"     {error}")
            print()
            return 1

        print("✅ All configurations converted successfully!")
        print()
        print("Next steps:")
        print("1. Review the generated JSON files")
        print("2. Verify nested configurations are correct")
        print("3. Test with your pipeline's JSON config loader")
        print("4. Commit to your configuration repository")
        print()

        return 0

    except FileNotFoundError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1
    except NotADirectoryError as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"❌ Unexpected error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback

            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

# Made with Bob
