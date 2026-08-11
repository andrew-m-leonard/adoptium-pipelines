# Universal Stage Pattern

Every stage requires four artefacts to be fully functional. This document provides the template for each. For the full schema reference and step-by-step guides, see [`docs/STAGE_DEFINITION_REFERENCE.md`](./STAGE_DEFINITION_REFERENCE.md).

## Four-Artefact Checklist

When adding or modifying a stage, ensure all four artefacts are present and consistent:

- [ ] **Shell script** — `scripts/stages/NN-stem.sh`
- [ ] **Params sidecar** — `scripts/stages/NN-stem.params.json`
- [ ] **Declarative stage block** — `ci/jenkins/Jenkinsfile.declarative`
- [ ] **Local runner entry** — `ci/local/run-pipeline.py`

---

## Shell Script Template

```bash
#!/bin/bash
# <NN>-<stage-name>.sh — <one-line description>
#
# Required Environment Variables:
#   WORKSPACE           - Stage working directory
#   CONFIG_FILE         - Path to pipeline-config.json
#   TARGET_DIR          - Where to write output artifacts
#   INPUT_ARTIFACTS_DIR - Where to read input artifacts from (if needed)
#   BUILD_NUMBER        - Build identifier (optional, defaults to 'local')
#
# Outputs:
#   ${TARGET_DIR}/**/*  - Stage output artifacts

set -euo pipefail

# Source shared utilities (paths relative to this script's location)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/logging-utils.sh"
source "${SCRIPT_DIR}/../lib/config-utils.sh"
source "${SCRIPT_DIR}/../lib/artifact-utils.sh"

STAGE_NAME="<stage-name>"
BUILD_NUMBER="${BUILD_NUMBER:-local}"

main() {
    log_section "${STAGE_NAME} Stage - Start"

    # 1. Validate environment
    validate_standard_environment

    # 2. Read build configuration from CONFIG_* env vars set by the pipeline.
    #    These are pre-populated from pipeline-config.json by the orchestrator
    #    so stage scripts do not need jq.
    local java_to_build="${CONFIG_JAVA_TO_BUILD:-}"
    local target_os="${CONFIG_TARGET_OS:-}"
    local architecture="${CONFIG_ARCHITECTURE:-}"
    local variant="${CONFIG_VARIANT:-}"

    log_info "Building: ${java_to_build} ${variant} ${target_os}-${architecture}"

    # 3. Prepare output directory
    prepare_output_dir "${TARGET_DIR}"

    # 4. Stage-specific logic
    do_work

    # 5. Create stage metadata
    create_stage_metadata "${STAGE_NAME}" "success"

    log_section "${STAGE_NAME} Stage - Complete"
}

do_work() {
    # Read inputs from ${INPUT_ARTIFACTS_DIR}
    # Write outputs to ${TARGET_DIR}
    :
}

main "$@"
```

## Params Sidecar Template

Every stage that introduces new parameters or has runtime gate conditions needs a `scripts/stages/NN-stem.params.json` sidecar. Minimal example:

```json
{
  "stageId": "NN-stem",
  "stageDisabled": false,
  "stageCondition": [],
  "description": "Parameters consumed by the NN-stem stage.",
  "parameterGroups": [
    {
      "name": "Stage Selections",
      "description": "Boolean flags that control which pipeline stages are enabled.",
      "parameters": [
        {
          "name": "ENABLE_NN_STEM",
          "type": "boolean",
          "default": false,
          "description": "Enable this stage. Disabled by default — enable for builds that require it."
        }
      ]
    }
  ]
}
```

**`stageDisabled` convention:** stages added to the core repo that are not intended for all vendors should ship with `"stageDisabled": true`. Vendors re-enable them via a `vendor-scripts/NN-stem.params.json` override with `"stageDisabled": false`.

**Gate-only file:** if the stage has no new parameters but should only run when certain conditions are met, omit `parameterGroups` and provide only `stageCondition`:

```json
{
  "stageId": "12-validate-sbom",
  "stageDisabled": false,
  "stageCondition": [
    { "param": "CREATE_SBOM", "value": true }
  ],
  "description": "Gate-only params.json for the validate-sbom stage. Runs only when CREATE_SBOM is true."
}
```

---

## Key Rules

| Rule | Reason |
|---|---|
| `set -euo pipefail` at the top | Any unhandled error exits immediately |
| Source all three lib files | Ensures consistent logging and config access |
| Call `validate_standard_environment` first | Fails fast if required vars are missing |
| Read build config from `CONFIG_*` env vars | Pre-populated from `pipeline-config.json` by the orchestrator — no `jq` needed |
| Read inputs from `${INPUT_ARTIFACTS_DIR}` | Standard input location set by the pipeline |
| Write to `${TARGET_DIR}` | Standard output location archived by Jenkins |
| Call `create_stage_metadata "${STAGE_NAME}" "success"` at end | Writes `stage-metadata.json` to `${WORKSPACE}/`; takes exactly 2 args |
| Exit 0 on success, non-zero on failure | The Jenkinsfile checks `stageRunner.run()` return value |

## Variable Conventions

```bash
# Build configuration — read from CONFIG_* env vars pre-populated by the orchestrator
local java_to_build="${CONFIG_JAVA_TO_BUILD:-}"
local target_os="${CONFIG_TARGET_OS:-}"
local architecture="${CONFIG_ARCHITECTURE:-}"
local variant="${CONFIG_VARIANT:-}"

# Stage params — injected as env vars by the orchestrator from *.params.json values
local my_param="${MY_PARAM:-false}"      # boolean stage param
local my_string="${MY_STRING_PARAM:-}"   # string stage param

# Input artifacts from previous stages
INPUT_ARTIFACTS_DIR="${INPUT_ARTIFACTS_DIR:?INPUT_ARTIFACTS_DIR must be set}"

# Output artifacts from this stage
TARGET_DIR="${TARGET_DIR:?TARGET_DIR must be set}"
mkdir -p "${TARGET_DIR}"
```

## Vendor Override

The `StageScriptRunner` checks `config-repo/vendor-scripts/<stem>.sh` before `scripts/stages/<stem>.sh`. A vendor script placed in the config repo replaces the default implementation entirely — it should follow the same interface contract so the surrounding Jenkins/local infrastructure continues to work.

## Adding the Stage to Jenkins

Add the stage block to `ci/jenkins/Jenkinsfile.declarative` in numeric order. Use `stageConditionMet()` in the `when{}` block — it reads the `stageCondition` list from the params sidecar at runtime:

First, declare a stage ID constant at the top of the Jenkinsfile alongside the others:

```groovy
@Field final NN_MY_STAGE = 'NN-my-stage'
```

Then add the stage block:

```groovy
stage(NN_MY_STAGE) {
    agent {
        label getStageLabel(NN_MY_STAGE)
    }
    when {
        beforeAgent true
        expression { stageConditionMet(NN_MY_STAGE) }
    }
    steps {
        script {
            ensureLibsLoaded(NN_MY_STAGE)
            nodeAgentHelper.waitForActiveNode(getStageLabel(NN_MY_STAGE), getActiveNodeTimeout())
            pipelineHelper.executeStageWithTracking(NN_MY_STAGE) {
                def config = pipelineHelper.initializeStage(
                    NN_MY_STAGE,
                    [BUILD],                             // prerequisite stage constants
                    'pipeline-config.json,**/*.tar.gz'   // artifact filter
                )
                env.TARGET_DIR = "${WORKSPACE}/my_stage_output"

                def exitCode = stageRunner.run(NN_MY_STAGE, config)
                if (exitCode != 0) { error("My Stage failed with exit code: ${exitCode}") }

                dir(env.TARGET_DIR) {
                    archiveArtifacts artifacts: '**/*', allowEmptyArchive: true
                }
                pipelineHelper.finalizeStage(NN_MY_STAGE)
            }
        }
    }
}
```

- `beforeAgent true` — prevents allocating a node for skipped stages (important for efficiency).
- `stageConditionMet(NN_MY_STAGE)` — evaluates all `stageCondition` entries from the params sidecar. Returns `true` when no conditions are defined (unconditional stage).
- All stage-ID arguments (`getStageLabel`, `ensureLibsLoaded`, `initializeStage`, `stageRunner.run`, `finalizeStage`) use the constant, not a display-name string.
- Set the prerequisite list to the stage ID constants that must have passed before this one runs.
- Set the artifact filter to exactly the files the stage script needs from previous stages.
- Set `TARGET_DIR` to a unique directory name (avoids cross-stage artifact collisions).

## Adding the Stage to the Local Runner

In `ci/local/run-pipeline.py`:

1. Add a module-level stage ID constant alongside the others:

```python
NN_MY_STAGE = 'NN-my-stage'
```

2. Add it to the `_LOCAL_STAGES` list in execution order (only if the stage should run locally — CI-only stages such as signing and publishing are excluded):

```python
_LOCAL_STAGES = [
    INITIALIZE,
    BUILD,
    # ... existing stages ...
    NN_MY_STAGE,
    REPRODUCIBLE_COMPARE,
]
```

3. Add a guarded call in `PipelineRunner.run()`:

```python
if NN_MY_STAGE in self.stages_to_run and self._stage_condition_met(NN_MY_STAGE):
    if not _run(NN_MY_STAGE, 'pipeline-config.json,**/*.tar.gz'):
        raise _PipelineAbort()
```

`_stage_condition_met()` checks `stageDisabled` first, then evaluates all `stageCondition` entries against `_stage_param_values` and the process environment. `_run_stage()` takes a stage ID and artifact filter; the display label is resolved automatically from `pipeline-stages.json`.

## Related Documentation

- [`docs/STAGE_DEFINITION_REFERENCE.md`](./STAGE_DEFINITION_REFERENCE.md) — full schema reference, ownership rules, disable/enable guides
- [`docs/CI_AGNOSTIC_ARCHITECTURE.md`](./CI_AGNOSTIC_ARCHITECTURE.md) — interface contract, per-stage summary, artifact flow
- [`ci/jenkins/lib/StageScriptRunner.groovy`](../ci/jenkins/lib/StageScriptRunner.groovy) — vendor override resolution
- [`scripts/lib/collect-stage-params.py`](../scripts/lib/collect-stage-params.py) — collation logic, `PRIORITY_GROUPS`, `stageCondition` validation
