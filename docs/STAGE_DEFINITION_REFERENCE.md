# Stage Definition Reference

Every pipeline stage is defined by four artefacts that must all be consistent with each other. This document is the authoritative reference for authoring, modifying, disabling, and enabling stages.

---

## The Four Artefacts of a Stage

| Artefact | Location | Purpose |
|---|---|---|
| Shell script | `scripts/stages/NN-stem.sh` | Actual build/sign/test logic — CI-agnostic |
| Params sidecar | `scripts/stages/NN-stem.params.json` | Stage metadata, gate conditions, and Jenkins/local parameters |
| Declarative stage block | `ci/jenkins/Jenkinsfile.declarative` | Jenkins stage definition, agent, `when{}` conditions |
| Local runner entry | `ci/local/run-pipeline.py` | `_stage_condition_met()` guard + `_run_stage()` call |

A stage is only fully functional when all four artefacts are present and consistent.

---

## Numeric Stem Convention

Stage scripts are prefixed with a two-digit number that defines their execution order:

- `02` through `20` are used; `01` is reserved for the Initialize stage (handled by `ConfigHelper`), `05` is currently unused (reserved gap).
- Numbers must be globally unique. New stages must not reuse or squeeze between existing numbers without a migration plan.
- The collator processes params files in alphabetical (numeric) order, which is also the execution order in the pipeline.

### Current stage numbering

| # | Stage | Script |
|---|---|---|
| 02 | Build | `02-build.sh` |
| 03 | Internal Code Sign | `03-internal-code-sign.sh` |
| 04 | Assemble Images | `04-assemble-images.sh` |
| 06 | Post-Build Code Sign | `06-post-build-code-sign.sh` |
| 07 | Build Installer | `07-installer.sh` |
| 08 | Code Sign Installer | `08-code-sign-installer.sh` |
| 09 | SBOM Sign | `09-sbom-sign.sh` |
| 10 | Digital Artifact Sign | `10-digital-artifact-sign.sh` |
| 11 | Verify Signing | `11-verify-signing.sh` |
| 12 | Validate SBOM | `12-validate-sbom.sh` |
| 13 | Smoke Tests | `13-smoke-tests.sh` |
| 14 | AQA Tests | `14-aqa-tests.sh` |
| 15 | TCK Tests | `15-tck-tests.sh` |
| 16 | Publish Artifacts | `16-publish.sh` |
| 20 | Reproducible Compare | `20-reproducible-compare.sh` |

---

## The params.json Schema

Every `scripts/stages/NN-stem.params.json` file follows this schema:

```json
{
  "stageId": "NN-stem",
  "stageDisabled": false,
  "stageCondition": [
    { "param": "PARAM_NAME", "value": true }
  ],
  "description": "Human-readable description of this file's purpose.",
  "parameterGroups": [
    {
      "name": "Group Name",
      "description": "Why this group exists and what it controls.",
      "parameters": [
        {
          "name": "PARAM_NAME",
          "type": "boolean",
          "default": false,
          "description": "What enabling this does. What the default means. Any important values."
        }
      ]
    }
  ]
}
```

### Top-level fields

#### `stageId` (string, required)
Must exactly match the stem of this file (e.g. `"14-aqa-tests"` for `14-aqa-tests.params.json`). Used by the collator, Job DSL, and local runner to associate metadata with the correct stage.

#### `stageDisabled` (boolean, default `false`)
Controls whether this stage is active.

- `false` — stage is active; its parameters are included in the collated output and appear in the Jenkins job UI.
- `true` — stage is entirely skipped; **no parameters are emitted** for it, so the stage gate booleans do not appear in the UI. In Jenkins, the stage shows as a grey "Skipped" pill. In the local runner, the stage is silently bypassed.

**Convention:** any stage added to the core pipeline repo that is not intended for all vendors should ship with `"stageDisabled": true`. Vendors re-enable it by providing a `vendor-scripts/NN-stem.params.json` override with `"stageDisabled": false`.

A vendor can also disable a core stage (e.g. `16-publish`) by supplying a `vendor-scripts/16-publish.params.json` with `"stageDisabled": true`.

#### `stageCondition` (array, default `[]`)
A list of runtime conditions that must all be satisfied (AND) for the stage to execute. Each entry is:

```json
{ "param": "PARAM_NAME", "value": true }
```

- `param` — the name of a collated parameter (must exist in the final `paramNames` set; the collator validates this and exits non-zero on a dangling reference).
- `value` — the required value. Comparison is string-based (`"true"` == `true`).

`stageCondition` is independent of `stageDisabled`:
- If `stageDisabled: true`, the stage is always skipped regardless of conditions.
- If `stageDisabled: false` but conditions are not met, the stage is skipped at runtime.

**Gate-only files:** a `params.json` may contain only `stageId`, `stageDisabled`, and `stageCondition` with no `parameterGroups` (e.g. `08-code-sign-installer.params.json`). This is valid — it registers the gate condition without introducing any new parameters.

#### `parameterGroups` (array, optional)
Groups of parameters displayed in the Jenkins Build Parameters UI under a separator heading. May be omitted for gate-only files.

Each group:

| Field | Required | Description |
|---|---|---|
| `name` | yes | Group heading in the UI. Parameters in the `Stage Selections` group are automatically promoted to the top of the UI. |
| `description` | yes | Non-empty description explaining the group's purpose. |
| `parameters` | yes | List of parameter definitions. |

Each parameter:

| Field | Required | Type | Description |
|---|---|---|---|
| `name` | yes | string | `UPPER_SNAKE_CASE`. Must be globally unique across all params files. |
| `type` | yes | `"string"` or `"boolean"` | The parameter type. |
| `default` | yes | string or bool | Default value. Must match the declared type (`true`/`false` for boolean, a JSON string for string). |
| `description` | yes | string | Non-empty. Should state: what it controls, what the default means, any important values. |

---

## Parameter Ownership

Each parameter name must be declared in **exactly one** stage's `params.json`. The collator enforces this and errors on duplicates across different group names.

Other stages that need to gate on a parameter reference it via their `stageCondition` only — they do not re-declare it.

### Shared parameters across stages

Some parameters (e.g. `BUILD_REF`, `AQA_REF`) are logically meaningful to more than one stage and may be re-declared in multiple `params.json` files — both default and vendor. The collator permits this **only when all declarations use the same group name**. The parameter is emitted once in the collated output.

**Description precedence:** the description from the **first declaration encountered** (lowest stage number, default file before vendor file) is used. Descriptions from subsequent declarations are silently ignored. This keeps the displayed parameter description concise and avoids verbose concatenation.

> When adding a shared parameter, write its canonical description in the lowest-numbered stage that declares it, since that will be the one shown to users.

### Current ownership map

| Parameter | Owned by | Referenced via stageCondition by |
|---|---|---|
| `SIGN_ARTIFACTS` | `03-internal-code-sign` | `06`, `08`, `09`, `10`, `11` |
| `ENABLE_INSTALLERS` | `07-installer` | `08` |
| `RUN_TESTS` | `14-aqa-tests` | `13-smoke-tests` (via stem `14-aqa-tests`) |
| `ENABLE_TCK` | `15-tck-tests` | — |
| `PUBLISH_ARTIFACTS` | `16-publish` | — |
| `RUN_REPRODUCIBLE_COMPARE` | `20-reproducible-compare` | — |

---

## The `Stage Selections` Group

All stage-gate boolean parameters must be placed in a group named exactly `"Stage Selections"`. The collator automatically promotes this group to the top of the Jenkins Build Parameters UI so operators can see and adjust the full execution plan in one place.

Parameters from multiple stage files can share this group name — the collator merges them into a single UI separator.

---

## Vendor Override Rules

A vendor supplies a `config-repo/vendor-scripts/NN-stem.params.json` to:

| Intent | How |
|---|---|
| Disable a core stage | `"stageDisabled": true` |
| Re-enable an opt-in stage | `"stageDisabled": false` |
| Override a parameter's default | Declare the param in a matching group; the collator uses the vendor default instead |
| Add new parameters | Add a new group or extend an existing group |
| Remove a default parameter | Add its name to `ignoreDefaultParams` |
| Override stageCondition | Set `"stageCondition": [...]` in the vendor file; it replaces the default |

---

## Step-by-Step: Adding a New Stage

### 1. Create the shell script

```bash
# scripts/stages/NN-new-stage.sh
#!/bin/bash
# NN-new-stage.sh — one-line description
#
# Required env: WORKSPACE, CONFIG_FILE, TARGET_DIR, INPUT_ARTIFACTS_DIR
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/logging-utils.sh"
source "${SCRIPT_DIR}/../lib/config-utils.sh"
source "${SCRIPT_DIR}/../lib/artifact-utils.sh"

STAGE_NAME="new-stage"

main() {
    log_section "${STAGE_NAME} Stage - Start"
    validate_standard_environment
    prepare_output_dir "${TARGET_DIR}"

    # ... stage logic ...

    create_stage_metadata "${STAGE_NAME}" "SUCCESS" "${TARGET_DIR}"
    log_section "${STAGE_NAME} Stage - Complete"
}
main "$@"
```

### 2. Create the params sidecar

```json
// scripts/stages/NN-new-stage.params.json
{
  "stageId": "NN-new-stage",
  "stageDisabled": false,
  "stageCondition": [],
  "description": "Parameters for the new stage.",
  "parameterGroups": [
    {
      "name": "Stage Selections",
      "description": "Boolean flags that control which pipeline stages are enabled.",
      "parameters": [
        {
          "name": "ENABLE_NEW_STAGE",
          "type": "boolean",
          "default": false,
          "description": "Enable the new stage. Disabled by default."
        }
      ]
    }
  ]
}
```

> If this stage should be disabled for all vendors by default, set `"stageDisabled": true`.

### 3. Add the Declarative stage block

In `ci/jenkins/Jenkinsfile.declarative`, add the stage in numeric order:

```groovy
stage('New Stage') {
    agent {
        label getStageLabel('New Stage')
    }
    when {
        beforeAgent true
        expression { stageConditionMet('NN-new-stage') }
    }
    steps {
        script {
            ensureLibsLoaded()
            nodeAgentHelper.waitForActiveNode(getStageLabel('New Stage'), getActiveNodeTimeout())
            pipelineHelper.executeStageWithTracking('New Stage') {
                def config = pipelineHelper.initializeStage(
                    'New Stage',
                    ['Build'],                              // prerequisite stages
                    'pipeline-config.json,**/*.tar.gz'     // artifact filter
                )
                env.TARGET_DIR = "${WORKSPACE}/new_stage_output"

                def exitCode = stageRunner.run('NN-new-stage', config)
                if (exitCode != 0) { error("New Stage failed with exit code: ${exitCode}") }

                dir(env.TARGET_DIR) {
                    archiveArtifacts artifacts: '**/*', allowEmptyArchive: true
                }
                pipelineHelper.finalizeStage('New Stage')
            }
        }
    }
}
```

### 4. Add the local runner entry

In `ci/local/run-pipeline.py`, add to `PipelineRunner.STAGES` and add a call in `run()`:

```python
# In STAGES list — add the stage name in execution order:
STAGES = ['initialize', 'build', ..., 'new-stage', ...]

# In run() — add the guarded call:
if 'new-stage' in self.stages_to_run and self._stage_condition_met('NN-new-stage'):
    self._run_stage('New Stage', 'NN-new-stage',
                    'pipeline-config.json,**/*.tar.gz')
```

### 5. Update documentation

- Add a row to the pipeline stages table in `README.md`.
- Add a row to the per-stage table in `docs/CI_AGNOSTIC_ARCHITECTURE.md`.
- Update this file's numeric stem table and parameter ownership map if applicable.

---

## Step-by-Step: Disabling a Stage as a Vendor

Create `config-repo/vendor-scripts/NN-stem.params.json`:

```json
{
  "stageId": "NN-stem",
  "stageDisabled": true
}
```

No other fields are required. The collator will skip this stage entirely — its parameters will not appear in the Jenkins UI and the stage will not execute.

---

## Step-by-Step: Enabling an Opt-In Stage as a Vendor

If a core stage ships with `"stageDisabled": true`, create `config-repo/vendor-scripts/NN-stem.params.json`:

```json
{
  "stageId": "NN-stem",
  "stageDisabled": false
}
```

The stage will now appear in the Jenkins UI with its default parameters, and will execute when its `stageCondition` is satisfied.

---

## Related Documentation

- [`docs/UNIVERSAL_STAGE_PATTERN.md`](./UNIVERSAL_STAGE_PATTERN.md) — shell script template and four-artefact checklist
- [`docs/CI_AGNOSTIC_ARCHITECTURE.md`](./CI_AGNOSTIC_ARCHITECTURE.md) — three-layer architecture, per-stage summary, artifact flow
- [`scripts/lib/collect-stage-params.py`](../scripts/lib/collect-stage-params.py) — collation logic, `PRIORITY_GROUPS`, `stageCondition` validation
- [`ci/jenkins/Jenkinsfile.declarative`](../ci/jenkins/Jenkinsfile.declarative) — `loadStageConditions()`, `stageConditionMet()`, stage `when{}` blocks
- [`ci/local/run-pipeline.py`](../ci/local/run-pipeline.py) — `_stage_condition_met()`, `_load_stage_metadata()`
