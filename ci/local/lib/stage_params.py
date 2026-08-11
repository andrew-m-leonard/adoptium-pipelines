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
Stage parameter collation helpers for the local pipeline runner.

Provides:
  - collect_stage_params()     — invoke collect-stage-params.py and return parsed JSON
  - param_name_to_cli_flag()   — UPPER_SNAKE_CASE → --lower-kebab-case
  - parse_extra_args()         — validate raw CLI tokens against collated param defs
  - build_stage_params_help()  — build the dynamic epilog for --help output
"""

import json
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path


def collect_stage_params(script_dir: Path, vendor_scripts_dir: Path | None,
                         silent: bool = False,
                         orchestrated_stages: list[str] | None = None) -> dict:
    """
    Run scripts/lib/collect-stage-params.py and return the parsed output.

    Args:
        script_dir:           Root of the ci-adoptium-pipelines checkout.
        vendor_scripts_dir:   Path to config-repo/vendor-scripts, or None.
        silent:               Suppress stdout (used when building --help text).
        orchestrated_stages:  List of stage IDs to include; stems not in this
                              list are skipped by the collator.

    Returns:
        Dict with keys 'groups' and 'paramNames', or empty structure on failure.
    """
    collector = script_dir / 'scripts' / 'lib' / 'collect-stage-params.py'
    if not collector.exists():
        return {'groups': [], 'paramNames': []}

    stages_dir = script_dir / 'scripts' / 'stages'
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp:
        tmp_path = tmp.name

    cmd = [
        sys.executable, str(collector),
        '--default-stages-dir', str(stages_dir),
        '--output', tmp_path,
    ]
    if vendor_scripts_dir and vendor_scripts_dir.exists():
        cmd += ['--vendor-scripts-dir', str(vendor_scripts_dir)]
    if orchestrated_stages:
        cmd += ['--orchestrated-stages', ','.join(orchestrated_stages)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"WARNING: collect-stage-params.py failed — stage params not loaded.\n"
              f"{result.stderr.strip()}", file=sys.stderr)
        return {'groups': [], 'paramNames': []}

    if not silent and result.stdout.strip():
        print(f"  {result.stdout.strip()}")

    with open(tmp_path, 'r') as f:
        return json.load(f)


def param_name_to_cli_flag(name: str) -> str:
    """Convert UPPER_SNAKE_CASE param name to --lower-kebab-case CLI flag."""
    return '--' + name.lower().replace('_', '-')


def parse_extra_args(extra: list[str], collated: dict) -> tuple[dict, list[str], list[str]]:
    """
    Parse a list of raw unknown CLI tokens against the collated stage parameter
    definitions.

    Both boolean and string parameters require an explicit value token:
      --create-sbom true          boolean
      --create-sbom false         boolean
      --scm-ref jdk-21.0.7+6     string
      --extra-build-args "..."    string

    Returns:
        (stage_params, unrecognised, errors)
          stage_params   — dict of PARAM_NAME → value for every valid token
          unrecognised   — list of flag names that matched no collated param
          errors         — list of human-readable error strings for malformed
                           tokens (missing value, wrong boolean value)
    """
    # Build a lookup: --lower-kebab-case flag → param def dict
    flag_to_param: dict[str, dict] = {}
    for group in collated.get('groups', []):
        for p in group.get('parameters', []):
            flag_to_param[param_name_to_cli_flag(p['name'])] = p

    stage_params: dict[str, str] = {}
    unrecognised: list[str] = []
    errors:       list[str] = []

    i = 0
    while i < len(extra):
        token = extra[i]
        if not token.startswith('--'):
            i += 1
            continue

        # Handle --flag=value and --flag value forms
        if '=' in token:
            flag, value = token.split('=', 1)
        else:
            flag = token
            value = None

        p = flag_to_param.get(flag)
        if p is None:
            unrecognised.append(flag)
            i += 1
            continue

        # All parameter types (boolean and string) require an explicit value token
        if value is None:
            if i + 1 < len(extra) and not extra[i + 1].startswith('--'):
                value = extra[i + 1]
                i += 2
            else:
                errors.append(
                    f"  {flag}: missing value (expected {p['type']})"
                )
                i += 1
                continue

        if p['type'] == 'boolean':
            if value.lower() not in ('true', 'false'):
                errors.append(
                    f"  {flag}: invalid value {value!r} — boolean must be 'true' or 'false'"
                )
                i += 1
                continue
            stage_params[p['name']] = value.lower()
        else:
            stage_params[p['name']] = value

    return stage_params, unrecognised, errors


def build_stage_params_help(script_dir: Path, argv: list[str],
                             local_stages: list[str]) -> str:
    """
    Build the stage parameters section for --help output.

    If --config-repo-url is present in argv, clone/reuse that repo into a
    temporary directory and collate the full vendor param set (default +
    vendor-scripts overrides).  Otherwise collate from the default
    scripts/stages/*.params.json files only.

    Args:
        script_dir:   Root of the ci-adoptium-pipelines checkout.
        argv:         Raw sys.argv list.
        local_stages: Ordered list of stage IDs the local runner executes.

    Returns:
        A formatted string ready to append to the argparse epilog, or '' if
        --help is not in argv or no params are found.
    """
    # Only do any work when --help or -h is actually requested
    if '--help' not in argv and '-h' not in argv:
        return ''

    # Extract --config-repo-url and --config-repo-branch from raw argv
    config_repo_url    = None
    config_repo_branch = 'main'
    for i, tok in enumerate(argv):
        if tok == '--config-repo-url' and i + 1 < len(argv):
            config_repo_url = argv[i + 1]
        elif tok.startswith('--config-repo-url='):
            config_repo_url = tok.split('=', 1)[1]
        elif tok == '--config-repo-branch' and i + 1 < len(argv):
            config_repo_branch = argv[i + 1]
        elif tok.startswith('--config-repo-branch='):
            config_repo_branch = tok.split('=', 1)[1]

    # Also check --workspace so we can reuse an already-cloned config repo
    workspace = Path('~/openjdk-build').expanduser()
    for i, tok in enumerate(argv):
        if tok == '--workspace' and i + 1 < len(argv):
            workspace = Path(argv[i + 1]).expanduser()
        elif tok.startswith('--workspace='):
            workspace = Path(tok.split('=', 1)[1]).expanduser()

    vendor_scripts_dir = None
    tmp_dir            = None

    if config_repo_url:
        # Reuse the already-cloned repo in the workspace only when its remote
        # origin URL matches the requested --config-repo-url exactly.
        existing = workspace / 'config-repo'
        reused   = False
        if existing.exists():
            try:
                result = subprocess.run(
                    ['git', '-C', str(existing), 'remote', 'get-url', 'origin'],
                    capture_output=True, text=True, check=True
                )
                existing_url = result.stdout.strip()
            except Exception:
                existing_url = ''
            if existing_url == config_repo_url:
                # URL matches — fetch latest so we always collate against
                # up-to-date vendor params.
                try:
                    subprocess.run(
                        ['git', '-C', str(existing), 'fetch', '--depth', '1',
                         'origin', config_repo_branch],
                        check=True, capture_output=True
                    )
                    subprocess.run(
                        ['git', '-C', str(existing), 'reset', '--hard',
                         f'origin/{config_repo_branch}'],
                        check=True, capture_output=True
                    )
                except Exception:
                    pass  # best-effort; stale content is better than no help output
                candidate = existing / 'vendor-scripts'
                if candidate.exists():
                    vendor_scripts_dir = candidate
                source_note = f"(from existing clone: {existing})"
                reused = True
            else:
                source_note = (
                    f"(existing clone at {existing} is for a different repo "
                    f"({existing_url!r} ≠ {config_repo_url!r}) — cloning fresh)"
                )
        if not reused:
            # Clone into a temp dir — cleaned up after help is printed
            try:
                tmp_dir = Path(tempfile.mkdtemp(prefix='run-pipeline-help-'))
                subprocess.run(
                    ['git', 'clone', '--depth', '1',
                     '--branch', config_repo_branch,
                     config_repo_url, str(tmp_dir)],
                    check=True, capture_output=True
                )
                candidate = tmp_dir / 'vendor-scripts'
                if candidate.exists():
                    vendor_scripts_dir = candidate
                source_note = f"(cloned from {config_repo_url})"
            except Exception:
                source_note = f"(clone of {config_repo_url} failed — showing defaults only)"
    else:
        source_note = "(defaults only — add --config-repo-url for vendor params)"

    try:
        collated = collect_stage_params(script_dir, vendor_scripts_dir, silent=True,
                                        orchestrated_stages=local_stages)
    except Exception:
        collated = {'groups': [], 'paramNames': []}
    finally:
        if tmp_dir and tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)

    if not collated.get('paramNames'):
        return ''

    lines = [
        '',
        f"Stage parameters {source_note}:",
        "  Pass as --<lower-kebab-case-name> <value>",
        "  Boolean params accept: true | false",
        '',
    ]

    for group in collated.get('groups', []):
        params = group.get('parameters', [])
        if not params:
            continue
        # Prefer stageIds list; fall back to scalar stageId
        stage_ids = group.get('stageIds') or [group.get('stageId', '?')]
        stage_str = ', '.join(stage_ids)
        lines.append(f"  [{stage_str}]  {group['name']}")
        for p in params:
            flag    = param_name_to_cli_flag(p['name'])
            default = str(p.get('default', '')).lower() if p['type'] == 'boolean' else repr(p.get('default', ''))
            desc = p.get('description', '').strip()
            lines.append(f"    {flag} <{p['type']}>  default: {default}")
            if desc:
                lines.append(f"      {desc}")
        lines.append('')

    return '\n'.join(lines)
