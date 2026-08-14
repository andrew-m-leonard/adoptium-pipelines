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
StageResolver — local pipeline equivalent of Jenkinsfile runStageScript().

Resolution order for a given stem (e.g. '13-smoke-tests'):
  1. <config_repo_root>/vendor-scripts/<stem>.sh   — vendor override (sh)
  2. <config_repo_root>/vendor-scripts/<stem>.py   — vendor override (python)
  3. <pipeline_root>/scripts/stages/<stem>.sh      — default (sh)
  4. <pipeline_root>/scripts/stages/<stem>.py      — default (python)
  5. built-in no-op                                — logs and returns 0

Stage enablement is driven by stageCondition entries in each stage's
*.params.json sidecar file, collated by collect-stage-params.py and loaded
by run-pipeline.py into _stage_conditions.  Each condition is:
  { "param": "NAME", "value": <bool|string> }

String values may begin with "regex:" for substring matching, e.g.:
  { "param": "EXTRA_BUILD_ARGS", "value": "regex:.*--create-sbom.*" }

Stages without any stageCondition entries always run.
Groovy is not supported locally (Jenkins-only).

Script contracts:
  .sh  — signals failure via exit code
  .py  — signals failure via exit code

run() returns the exit code (0 = success, non-zero = failure).
Callers decide whether to raise or continue (e.g. UNSTABLE-equivalent).
"""

import subprocess
import sys
from pathlib import Path


class StageResolver:
    """Resolves and executes stage scripts with vendor-override support."""

    EXTENSIONS = [".sh", ".py"]

    def __init__(self, pipeline_root: Path, config_repo_root: Path | None):
        """
        Args:
            pipeline_root:    Root of the ci-adoptium-pipelines checkout
                              (contains scripts/stages/).
            config_repo_root: Root of the cloned config repo (contains
                              vendor-scripts/), or None if not yet cloned.
        """
        self.pipeline_root = pipeline_root
        self.config_repo_root = config_repo_root

    def resolve(self, stem: str) -> Path | None:
        """
        Return the Path of the script to execute for *stem*, or None (no-op).

        Searches vendor-scripts/ first, then scripts/stages/.
        """
        search_roots = []
        if self.config_repo_root and self.config_repo_root.exists():
            search_roots.append(self.config_repo_root / "vendor-scripts")
        search_roots.append(self.pipeline_root / "scripts" / "stages")

        for root in search_roots:
            for ext in self.EXTENSIONS:
                candidate = root / f"{stem}{ext}"
                if candidate.exists():
                    return candidate

        return None

    def run(self, stem: str, env: dict) -> int:
        """
        Resolve and execute the stage script for *stem*.

        Ensures TARGET_DIR exists (mirrors Jenkins runStageScript behaviour)
        before launching the script.

        Returns:
            int: exit code — 0 = success, non-zero = failure.
        """
        script = self.resolve(stem)

        if script is None:
            print(f"ℹ️  No script found for '{stem}' — stage is a no-op")
            return 0

        print(f"▶ Running {script.suffix.lstrip('.')} stage script: {script}")

        # Mirror Jenkins runStageScript: ensure TARGET_DIR exists
        target_dir = env.get("TARGET_DIR")
        if target_dir:
            Path(target_dir).mkdir(parents=True, exist_ok=True)

        if script.suffix == ".sh":
            cmd = ["bash", str(script)]
        elif script.suffix == ".py":
            cmd = [sys.executable, str(script)]
        else:
            raise ValueError(f"Unsupported script type: {script.suffix}")

        result = subprocess.run(cmd, env=env, check=False)
        return result.returncode
