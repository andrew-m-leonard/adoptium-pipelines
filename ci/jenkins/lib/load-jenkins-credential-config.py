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
Jenkins credential configuration loader.

Reads jenkins_credential_config.json from the config repository root (optional)
and writes jenkins-credential-config.json to the working directory containing:

  credentials      — named credential definitions (type, credentialId, env var names)
  stageCredentials — map of stageId → [credentialName, ...]

The file is optional.  If absent, both fields are written as empty objects and
the pipeline behaves exactly as before — no stage receives any credentials.

Supported credential types and their env var fields:

  string           → variable name = the credential key itself
  usernamePassword → usernameEnvVar (default: <KEY>_USER)
                     passwordEnvVar (default: <KEY>_PASS)
  sshUserPrivateKey→ keyFileEnvVar  (default: <KEY>_KEYFILE)
  file             → fileEnvVar     (default: <KEY>_FILE)

Usage:
    python3 ci/jenkins/lib/load-jenkins-credential-config.py \\
        --config-repo-path ./config-repo \\
        --output           ./jenkins-credential-config.json
"""

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Supported credential types and their required / optional fields
# ---------------------------------------------------------------------------

_VALID_TYPES = {"string", "usernamePassword", "sshUserPrivateKey", "file"}

# Fields that carry env var names for each type (used for validation messaging)
_TYPE_ENV_VAR_FIELDS = {
    "string":           [],
    "usernamePassword": ["usernameEnvVar", "passwordEnvVar"],
    "sshUserPrivateKey": ["keyFileEnvVar"],
    "file":             ["fileEnvVar"],
}


def _default_env_var_names(name, cred_type):
    """Return the default env var names for a credential that omits explicit fields."""
    if cred_type == "string":
        return {name: name}
    if cred_type == "usernamePassword":
        return {
            "usernameEnvVar": f"{name}_USER",
            "passwordEnvVar": f"{name}_PASS",
        }
    if cred_type == "sshUserPrivateKey":
        return {"keyFileEnvVar": f"{name}_KEYFILE"}
    if cred_type == "file":
        return {"fileEnvVar": f"{name}_FILE"}
    return {}


def _validate_credentials(credentials):
    """Validate the credentials map.  Exits non-zero on any error."""
    errors = []
    for name, cred in credentials.items():
        if not isinstance(cred, dict):
            errors.append(f"  credentials['{name}']: must be an object")
            continue
        cred_type = cred.get("type")
        if cred_type not in _VALID_TYPES:
            errors.append(
                f"  credentials['{name}'].type: '{cred_type}' is not valid. "
                f"Must be one of: {sorted(_VALID_TYPES)}"
            )
            continue
        if not cred.get("credentialId"):
            errors.append(
                f"  credentials['{name}'].credentialId: must be a non-empty string"
            )
    if errors:
        print("ERROR: jenkins_credential_config.json validation failed:", file=sys.stderr)
        for e in errors:
            print(e, file=sys.stderr)
        sys.exit(1)


def _validate_stage_credentials(stage_credentials, credentials):
    """Validate stageCredentials references.  All names must exist in credentials."""
    errors = []
    for stage_id, names in stage_credentials.items():
        if not isinstance(names, list):
            errors.append(
                f"  stageCredentials['{stage_id}']: must be an array of credential names"
            )
            continue
        for name in names:
            if name not in credentials:
                errors.append(
                    f"  stageCredentials['{stage_id}']: '{name}' is not defined in credentials"
                )
    if errors:
        print("ERROR: jenkins_credential_config.json validation failed:", file=sys.stderr)
        for e in errors:
            print(e, file=sys.stderr)
        sys.exit(1)


def generateCredentialConfig(config_repo_path, output_path):
    """Generate jenkins-credential-config.json from jenkins_credential_config.json.

    If the source file does not exist, writes an empty-but-valid output file
    so downstream consumers always have a file to read.

    Args:
        config_repo_path: Path to the config repository root.
        output_path:      Path to write jenkins-credential-config.json.
    """
    source_path = Path(config_repo_path) / "jenkins_credential_config.json"

    if not source_path.exists():
        print(
            f"ℹ️  jenkins_credential_config.json not found in {config_repo_path} "
            "— no stage credentials will be configured",
            file=sys.stderr,
        )
        out = {"pipelineRepoCredentialsId": "", "configRepoCredentialsId": "", "credentials": {}, "stageCredentials": {}}
        with open(Path(output_path), "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
        print(f"✓ Created {output_path} (empty — no credential config found)")
        return

    with open(source_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    pipeline_repo_credentials_id = config.get("pipelineRepoCredentialsId", "")
    config_repo_credentials_id   = config.get("configRepoCredentialsId", "")
    credentials      = config.get("credentials", {})
    stage_credentials = config.get("stageCredentials", {})

    _validate_credentials(credentials)
    _validate_stage_credentials(stage_credentials, credentials)

    # Apply defaults for omitted env var name fields
    resolved_credentials = {}
    for name, cred in credentials.items():
        resolved = dict(cred)
        defaults = _default_env_var_names(name, cred["type"])
        for field, default_val in defaults.items():
            if field not in resolved:
                resolved[field] = default_val
        resolved_credentials[name] = resolved

    out = {
        "pipelineRepoCredentialsId": pipeline_repo_credentials_id,
        "configRepoCredentialsId":   config_repo_credentials_id,
        "credentials":               resolved_credentials,
        "stageCredentials":          stage_credentials,
    }

    with open(Path(output_path), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    print(f"✓ Created {output_path}")
    print(f"  Credentials defined: {list(resolved_credentials.keys())}")
    print(f"  Stages with credentials: {list(stage_credentials.keys())}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate jenkins-credential-config.json from jenkins_credential_config.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
  python3 ci/jenkins/lib/load-jenkins-credential-config.py \\
      --config-repo-path ./config-repo \\
      --output           ./jenkins-credential-config.json
        """,
    )
    parser.add_argument(
        "--config-repo-path",
        required=True,
        help="Path to the config repository root (may contain jenkins_credential_config.json)",
    )
    parser.add_argument(
        "--output",
        default="./jenkins-credential-config.json",
        help="Path to write jenkins-credential-config.json (default: ./jenkins-credential-config.json)",
    )
    args = parser.parse_args()
    generateCredentialConfig(args.config_repo_path, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
