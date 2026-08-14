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
Stage registry loader for the local pipeline runner.

Provides load_stage_registry() which reads pipeline-stages.json and returns an
id → label mapping used by PipelineRunner to display human-readable stage names.
"""

import json
from pathlib import Path


def load_stage_registry(script_dir: Path) -> dict:
    """Load pipeline-stages.json and return an id → label mapping.

    Args:
        script_dir: Root of the ci-adoptium-pipelines checkout.

    Returns:
        Dict mapping stageId strings to their display labels,
        e.g. {'02-build': 'Build', '13-smoke-tests': 'Smoke Tests', ...}
    """
    registry_path = script_dir / "scripts" / "stages" / "pipeline-stages.json"
    with open(registry_path, "r", encoding="utf-8") as f:
        stages = json.load(f)["pipelineStages"]
    return {s["id"]: s["label"] for s in stages}
