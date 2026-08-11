# BUILD_UID Integration

## Overview

`BUILD_UID` and `GROUP_UID` provide unique build identification and per-stage result tracking that persists across pipeline restarts. The implementation lives in [`ci/jenkins/lib/BuildUidHelper.groovy`](../ci/jenkins/lib/BuildUidHelper.groovy), loaded lazily by [`PipelineHelper.groovy`](../ci/jenkins/lib/PipelineHelper.groovy) at the start of each stage.

## Purpose

1. **Unique build tracking** — each build gets a `BUILD_UID` that is reused on "Restart from Stage"
2. **Stage result tracking** — every stage outcome is recorded in `BUILD_STAGE_RESULTS` so prerequisites can be validated
3. **Prerequisite validation** — stages fail fast if required earlier stages did not pass
4. **Group linking** — `GROUP_UID` links all platform builds from the same launch run together
5. **Build display** — `BUILD_UID` and `GROUP_UID` are written into the Jenkins build description on every stage

## Components

| Symbol | File | Role |
|---|---|---|
| `BuildUidHelper.groovy` | `ci/jenkins/lib/` | All UID and stage-result logic |
| `PipelineHelper.initializeStage()` | `ci/jenkins/lib/PipelineHelper.groovy` | Calls `BuildUidHelper` at start of every stage |
| `PipelineHelper.executeStageWithTracking()` | `ci/jenkins/lib/PipelineHelper.groovy` | Wraps stage body; calls `recordStageResult()` on exit |
| `PipelineHelper.finalizeStage()` | `ci/jenkins/lib/PipelineHelper.groovy` | Optional cleanup; logs `BUILD_UID` |
| `PipelineHelper.ensureBuildDescriptionSet()` | `ci/jenkins/lib/PipelineHelper.groovy` | Sets Jenkins display name and description |

## How It Works

### Per-stage call sequence

Every stage in `Jenkinsfile.declarative` follows the same pattern:

```groovy
pipelineHelper.executeStageWithTracking('Smoke Tests') {  // (1)
    def config = pipelineHelper.initializeStage(           // (2)
        'Smoke Tests',
        ['Build'],                              // prerequisites
        'pipeline-config.json,*.tar.gz,*.zip', // copyArtifacts filter
        "${WORKSPACE}/stage_input_artifacts"    // INPUT_ARTIFACTS_DIR
    )
    env.TARGET_DIR = "${WORKSPACE}/smoke_test_output"

    def exitCode = stageRunner.run('13-smoke-tests', config)
    env.SMOKE_TESTS_PASSED = (exitCode == 0).toString()
    if (exitCode != 0) {
        currentBuild.result = 'UNSTABLE'
    }

    pipelineHelper.finalizeStage('Smoke Tests')             // (3)
}
```

1. **`executeStageWithTracking`** — wraps the closure; calls `recordStageResult()` with the appropriate result code on every exit path (including exceptions and aborts)
2. **`initializeStage`** — cleans workspace, checks out repos, loads `BuildUidHelper` (lazy), calls `initializeBuildContext()`, validates prerequisites, copies artifacts, reads and returns the config map
3. **`finalizeStage`** — runs `cleanWs()` if `CLEAN_WORKSPACE_AFTER_STAGE=true`; logs `BUILD_UID`

### `initializeBuildContext()` (BuildUidHelper)

Called by `initializeStage()` on every stage allocation:

```
BUILD_UID:
  if env.BUILD_UID is empty → generate "build-<yyyyMMdd-HHmmss>-<uuid8>"
  else                       → reuse existing (restart case)

GROUP_UID:
  if env.GROUP_UID is already set → reuse (already resolved earlier in this run)
  else if params.GROUP_UID is non-empty → use the job parameter value
  else → generate "group-<yyyyMMdd-HHmmss>-<uuid8>"

BUILD_STAGE_RESULTS:
  if env.BUILD_STAGE_RESULTS is set → parse and log existing results
  else                               → set to "" (first run)
```

### `executeStageWithTracking()` (PipelineHelper)

```groovy
try {
    body()
    buildUidHelper.recordStageResult(stageName, 'SUCCESS')
} catch (FlowInterruptedException e) {       // user abort
    buildUidHelper.recordStageResult(stageName, 'ABORTED')
    throw e
} catch (Exception e) {
    def result = currentBuild.result ?: 'FAILURE'  // honours UNSTABLE set by stage
    buildUidHelper.recordStageResult(stageName, result)
    throw e
}
```

### `validatePrerequisites()` (BuildUidHelper)

Called for every stage except `Initialize`. Checks `BUILD_STAGE_RESULTS` for each required stage:

- If `BUILD_STAGE_RESULTS` is empty on a non-Initialize stage → **Rebuild error** (see below)
- If a required stage name is absent from the map → "Missing stages: ..."
- If a required stage has a non-SUCCESS result → "Failed stages: ... (FAILURE)"

Both missing and failed prerequisites produce the same `error()` call that aborts the stage.

### `ensureBuildDescriptionSet()` (PipelineHelper)

Called by `initializeStage()` after loading the config (all stages except Initialize call this). Sets:

- **`currentBuild.displayName`** — `#<N> - <JAVA_TO_BUILD> <VARIANT> <OS>-<ARCH>[@<SCM_REF>][ [RELEASE_TYPE]]`
- **`currentBuild.description`** — `[Restart of #<original> | ]BUILD_UID: <uid> | GROUP_UID: <uid>`

The restart detection walks backwards through `currentBuild.previousBuild` looking for builds that share the same `BUILD_UID`.

### `post { always }` (Jenkinsfile)

After all stages complete:

1. If `BUILD_UID == null` (no stage ran at all — e.g. Rebuild of a Restart) → sets `currentBuild.result = 'FAILURE'` with an explanatory message
2. If `CLEAN_WORKSPACE_AFTER_STAGE=true` → allocates a new agent node and calls `cleanWs()` for a final workspace cleanup

## Environment Variables

### `BUILD_UID`

- **Format**: `build-<yyyyMMdd-HHmmss>-<uuid8>` (e.g. `build-20260617-143022-abc12345`)
- Generated once at Initialize; reused on "Restart from Stage"
- Persists through the Jenkins `env` object across stage allocations

### `GROUP_UID`

- **Format**: `group-<yyyyMMdd-HHmmss>-<uuid8>` (e.g. `group-20260617-143022-f1e2d3c4`) — or any custom string when set explicitly
- Links all platform builds triggered by the same launch job run
- Resolution priority: existing `env.GROUP_UID` → `params.GROUP_UID` → auto-generate
- The launch pipeline (`Jenkinsfile.launch`) generates `GROUP_UID` and passes it as a job parameter to every platform build job it triggers
- **Custom value**: supply a human-readable string via the `GROUP_UID` parameter on the launch job or directly on a platform build job (e.g. `"April 2026 CPU jdk21u release"`). Any non-empty value is used as-is and propagated to all platform builds in that run.

### `BUILD_STAGE_RESULTS`

- **Format**: `Stage1==SUCCESS||Stage2==FAILURE||Stage3==UNSTABLE`
- Serialised by `serializeStageResults(Map)`, parsed by `parseStageResults(String)` (both `@NonCPS`)
- Updated by `recordStageResult(stageName, result)` after every stage body exits
- Read by `validatePrerequisites()` at the start of every non-Initialize stage

## Stage Prerequisites

| Stage | Prerequisites |
|---|---|
| Initialize | _(none)_ |
| Build | Initialize |
| Internal Code Sign | Build |
| Assemble Images | Build |
| Post-Build Code Sign | Assemble Images |
| Build Installers | Build |
| Code Sign Installer | Build Installers |
| SBOM Sign | Post-Build Code Sign |
| Digital Artifact Sign | Post-Build Code Sign |
| Verify Signing | Digital Artifact Sign |
| Validate SBOM | Build |
| Smoke Tests | Build |
| Reproducible Compare Build | Build |
| AQA Tests | Smoke Tests |
| TCK Tests | Smoke Tests |
| Publish Artifacts | Build |

## Scenario Walkthroughs

### Normal first run

```
Initialize:
  BUILD_UID  generated → build-20260617-143022-abc12345
  GROUP_UID  from param → group-20260617-130000-f1e2d3c4
  BUILD_STAGE_RESULTS = ""

Build:
  initializeBuildContext() reuses BUILD_UID + GROUP_UID
  validatePrerequisites(): Initialize == SUCCESS ✅
  BUILD_STAGE_RESULTS = "Initialize==SUCCESS"

Smoke Tests:
  validatePrerequisites(): Build == SUCCESS ✅
  BUILD_STAGE_RESULTS = "Initialize==SUCCESS||Build==SUCCESS"
```

### Restart from Smoke Tests

```
Jenkins skips Initialize and Build (already completed in the original run).

Smoke Tests (new agent allocation):
  cleanWs + checkout scm + sparse-checkout config-repo
  initializeBuildContext():
    BUILD_UID reused from env (same value as original run) ✅
    GROUP_UID reused from env ✅
    BUILD_STAGE_RESULTS loaded: "Initialize==SUCCESS||Build==SUCCESS"
  validatePrerequisites(): Build == SUCCESS ✅
  stage logic runs
  ensureBuildDescriptionSet() sets description: "Restart of #<N> | BUILD_UID: ... | GROUP_UID: ..."
```

### Rebuild (not Restart) — user error

```
Smoke Tests (new build, env vars cleared):
  initializeBuildContext():
    BUILD_UID generated (new, different value)
    BUILD_STAGE_RESULTS = "" (empty — new build)
  validatePrerequisites():
    BUILD_STAGE_RESULTS is empty on non-Initialize stage
    → error: "Cannot validate prerequisites... Use 'Restart from Stage', not 'Rebuild'"
```

### Build aborted by user

```
Build stage aborted mid-run:
  executeStageWithTracking catches FlowInterruptedException
  recordStageResult('Build', 'ABORTED')
  BUILD_STAGE_RESULTS = "Initialize==SUCCESS||Build==ABORTED"

Smoke Tests (if restarted):
  validatePrerequisites(): Build == ABORTED (not SUCCESS)
  → error: "Failed stages: Build (ABORTED)"
```

## `createPostBlocks()` Helper

`BuildUidHelper` also exposes `createPostBlocks(stageName)` which returns a map of closures (success/unstable/failure/aborted) suitable for use in a stage's `post` block. This is an alternative to `executeStageWithTracking` for stages that use declarative `post` syntax rather than a scripted wrapper.

## Related Documentation

- [`ci/jenkins/lib/BuildUidHelper.groovy`](../ci/jenkins/lib/BuildUidHelper.groovy) — implementation
- [`ci/jenkins/lib/PipelineHelper.groovy`](../ci/jenkins/lib/PipelineHelper.groovy) — loads and calls BuildUidHelper; `ensureBuildDescriptionSet`
- [`ci/jenkins/Jenkinsfile.declarative`](../ci/jenkins/Jenkinsfile.declarative) — pipeline that uses these helpers
- [`ci/jenkins/Jenkinsfile.launch`](../ci/jenkins/Jenkinsfile.launch) — generates GROUP_UID and passes it to platform builds
