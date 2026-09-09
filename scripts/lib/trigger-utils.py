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
trigger-utils.py — utility commands for CI-agnostic trigger scripts.

Commands
--------
check-github-release-asset <target_repo> <release_tag>
    Queries the GitHub (or GitHub Enterprise) releases API to check whether a
    JDK binary asset (.tar.gz or .zip containing "jdk_") exists for the given
    release tag.
    Exits 0 if found, 1 if not found, 2 on error (callers treat as not found —
    fail open to avoid suppressing a legitimate trigger).

    Supports both github.com and GitHub Enterprise endpoints:
      github.com:         https://github.com/org/repo
                          → https://api.github.com/repos/org/repo/releases/tags/<tag>
      GitHub Enterprise:  https://github.ibm.com/org/repo
                          → https://github.ibm.com/api/v3/repos/org/repo/releases/tags/<tag>

    Args:
      target_repo   GitHub repo URL
      release_tag   Release tag to check, e.g. jdk-21.0.5+11-ea-beta

    Env (optional):
      GITHUB_TOKEN  PAT for authenticated requests (rate-limit avoidance,
                    and required for private GitHub Enterprise repos)

write-trigger-result <target_dir> [key=value ...]
    Writes trigger-result.json to <target_dir>.  key=value pairs set string
    fields; "true"/"false" values are written as JSON booleans.

    Example:
      python3 trigger-utils.py write-trigger-result /out \\
          shouldTrigger=true scmRef=jdk-21.0.5+11_adopt publishName=jdk-21.0.5+11-ea

read-trigger-field <json_file> <field>
    Reads a single field from trigger-result.json and prints it to stdout.
    Exits 1 if the field is absent, 2 on read/parse error.

default-build-tag-pattern <version>
    Prints the default buildTagPattern for the given JDK version string.
    Used by trigger scripts when buildTagPattern is absent from config.
    e.g. "jdk21" → "jdk-21[\\.+].+_adopt$"
         "jdk8"  → "jdk8u.+_adopt$"
"""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _github_api_url(repo_url: str, path: str) -> str:
    """Convert a GitHub repo URL to its REST API equivalent.

    github.com:
        https://github.com/org/repo
        → https://api.github.com/repos/org/repo/<path>

    GitHub Enterprise (any other hostname, e.g. github.ibm.com):
        https://github.ibm.com/org/repo
        → https://github.ibm.com/api/v3/repos/org/repo/<path>
    """
    parsed = urllib.parse.urlparse(repo_url)
    repo_path = parsed.path.rstrip("/")

    if parsed.hostname == "github.com":
        api_base = parsed._replace(
            netloc="api.github.com",
            path=f"/repos{repo_path}",
        )
    else:
        # GitHub Enterprise: API is at <host>/api/v3
        api_base = parsed._replace(path=f"/api/v3/repos{repo_path}")

    return urllib.parse.urlunparse(api_base) + "/" + path.lstrip("/")


# ---------------------------------------------------------------------------
# check-github-release-asset
# ---------------------------------------------------------------------------

def cmd_check_github_release_asset(target_repo: str, release_tag: str) -> int:
    """Return 0 if a JDK asset exists for release_tag, 1 if not, 2 on error."""
    encoded_tag = urllib.parse.quote(release_tag, safe="")
    api_url = _github_api_url(target_repo, f"releases/tags/{encoded_tag}")

    req = urllib.request.Request(api_url)
    req.add_header("Accept", "application/vnd.github+json")
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        req.add_header("Authorization", f"token {token}")

    print(f"[trigger-utils] Querying: {api_url}", file=sys.stderr)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            print(
                f"[trigger-utils] Release tag '{release_tag}' not found on {target_repo}",
                file=sys.stderr,
            )
            return 1
        print(
            f"[trigger-utils] GitHub API HTTP error {exc.code} for {api_url}",
            file=sys.stderr,
        )
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"[trigger-utils] GitHub API request failed: {exc}", file=sys.stderr)
        return 2

    assets = data.get("assets", [])
    for asset in assets:
        name = asset.get("name", "")
        if "jdk_" in name and (name.endswith(".tar.gz") or name.endswith(".zip")):
            print(f"[trigger-utils] Found JDK asset: {name}", file=sys.stderr)
            return 0

    print(
        f"[trigger-utils] No JDK asset found in release '{release_tag}' on {target_repo}",
        file=sys.stderr,
    )
    return 1


# ---------------------------------------------------------------------------
# write-trigger-result
# ---------------------------------------------------------------------------

def cmd_write_trigger_result(target_dir: str, pairs: list) -> int:
    """Write trigger-result.json from key=value pairs."""
    result: dict = {}
    for pair in pairs:
        if "=" not in pair:
            print(f"[trigger-utils] Invalid key=value pair: {pair!r}", file=sys.stderr)
            return 2
        key, _, value = pair.partition("=")
        # Coerce recognised boolean strings to JSON booleans
        if value.lower() == "true":
            result[key] = True
        elif value.lower() == "false":
            result[key] = False
        else:
            result[key] = value

    Path(target_dir).mkdir(parents=True, exist_ok=True)
    out_path = Path(target_dir) / "trigger-result.json"
    out_path.write_text(json.dumps(result, indent=2) + "\n")
    print(f"[trigger-utils] Wrote {out_path}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# read-trigger-field
# ---------------------------------------------------------------------------

def cmd_read_trigger_field(json_file: str, field: str) -> int:
    """Print the value of a field from trigger-result.json."""
    try:
        data = json.loads(Path(json_file).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[trigger-utils] Cannot read {json_file}: {exc}", file=sys.stderr)
        return 2

    if field not in data:
        print(
            f"[trigger-utils] Field '{field}' not found in {json_file}",
            file=sys.stderr,
        )
        return 1

    value = data[field]
    # Print booleans as lowercase strings for shell consumption
    print(str(value).lower() if isinstance(value, bool) else value)
    return 0


# ---------------------------------------------------------------------------
# default-build-tag-pattern
# ---------------------------------------------------------------------------

def cmd_default_build_tag_pattern(version: str) -> int:
    """Print the default buildTagPattern for the given JDK version string."""
    match = re.search(r"(\d+)", version)
    if not match:
        print(
            f"[trigger-utils] Cannot parse version number from '{version}'",
            file=sys.stderr,
        )
        return 2
    vnum = int(match.group(1))
    if vnum == 8:
        print(r"jdk8u.+_adopt$")
    else:
        # Matches both jdk-21.0.5+11_adopt and jdk-25+10_adopt style tags.
        # The double-backslash produces a literal \. in the ERE passed to grep -E.
        print(rf"jdk-{vnum}[\\.+].+_adopt$")
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)

    command = sys.argv[1]

    if command == "check-github-release-asset":
        if len(sys.argv) < 4:
            print(
                "Usage: trigger-utils.py check-github-release-asset <target_repo> <release_tag>",
                file=sys.stderr,
            )
            sys.exit(2)
        sys.exit(cmd_check_github_release_asset(sys.argv[2], sys.argv[3]))

    elif command == "write-trigger-result":
        if len(sys.argv) < 3:
            print(
                "Usage: trigger-utils.py write-trigger-result <target_dir> [key=value ...]",
                file=sys.stderr,
            )
            sys.exit(2)
        sys.exit(cmd_write_trigger_result(sys.argv[2], sys.argv[3:]))

    elif command == "read-trigger-field":
        if len(sys.argv) < 4:
            print(
                "Usage: trigger-utils.py read-trigger-field <json_file> <field>",
                file=sys.stderr,
            )
            sys.exit(2)
        sys.exit(cmd_read_trigger_field(sys.argv[2], sys.argv[3]))

    elif command == "default-build-tag-pattern":
        if len(sys.argv) < 3:
            print(
                "Usage: trigger-utils.py default-build-tag-pattern <version>",
                file=sys.stderr,
            )
            sys.exit(2)
        sys.exit(cmd_default_build_tag_pattern(sys.argv[2]))

    else:
        print(f"[trigger-utils] Unknown command '{command}'", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
