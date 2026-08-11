# Jenkins Integration

This directory contains Jenkins-specific pipeline definitions, shared Groovy libraries, and Job DSL automation for the Adoptium build infrastructure.

## Files and Directories

### Jenkinsfile.declarative

Single-platform build pipeline. Every `Build_openjdk<version>_<distro>_<arch>_<os>` job points at this file. It:

1. Loads shared helpers from `lib/` after checkout
2. Runs all applicable pipeline stages in sequence
3. Calls the appropriate `scripts/stages/` shell script for each stage via `StageScriptRunner`
4. Tracks stage results in `BUILD_STAGE_RESULTS` to support "Restart from Stage"

**Script path in Jenkins job config**: `ci/jenkins/Jenkinsfile.declarative`

### Jenkinsfile.launch

Multi-platform launch pipeline. Jobs named `Build_openjdk<version>_launch` (in `Build_openjdk_launchers/`) use this file. It:

1. Reads `jdk${version}_pipeline_config.json` from the config repo to discover available platforms
2. Determines which platforms to build (all, or a subset from the `PLATFORMS` parameter)
3. Optionally regenerates platform build jobs via Job DSL (on first run or when `REGENERATE_JOBS=true`)
4. Triggers all selected platform build jobs in parallel, passing a shared `GROUP_UID`

### lib/

Shared Groovy helpers loaded with `load()` at the start of each stage. These are plain CPS scripts — they call pipeline steps (`echo`, `sh`, `env`, `params`, `currentBuild`, `cleanWs`, `copyArtifacts`, etc.) directly without any delegation wrapper.

#### BuildUidHelper.groovy

- Generates a unique `BUILD_UID` (timestamp + UUID fragment) on first stage execution; reuses it on restarts
- Manages `GROUP_UID` to link all platform builds from the same launch run
- Serialises per-stage pass/fail results into `BUILD_STAGE_RESULTS` (format: `Stage1==SUCCESS||Stage2==FAILURE`)
- `validatePrerequisites()` reads `BUILD_STAGE_RESULTS` and fails with a clear message if required stages haven't passed

#### PipelineHelper.groovy

- `initializeStage(stageName, prerequisites, artifactFilter, inputArtifactsDir)` — cleans workspace, checks out this repo, sparse-clones the config repo, calls `BuildUidHelper.initializeBuildContext()`, validates prerequisites, copies required artifacts from the current build
- `finalizeStage(stageName)` — optional post-stage workspace cleanup, logs completion
- `executeStageWithTracking(stageName, body)` — wraps a stage body closure; records SUCCESS/FAILURE/ABORTED in `BUILD_STAGE_RESULTS`
- `ensureBuildDescriptionSet(config)` — sets build display name and description from config + `BUILD_UID`

#### ConfigHelper.groovy

- `generatePipelineConfig(configDir)` — invokes `scripts/lib/load-json-config.py` with parameters resolved from job params and `adoptium_pipeline_config.json`; writes `pipeline-config.json`; sets all `CONFIG_*` env vars used by `when {}` blocks
- `summarizePipelineConfig(config)` — logs the key build configuration values

#### StageScriptRunner.groovy

- `run(scriptStem, config)` — resolves the script to execute for a given stage stem using the vendor-override search order:
  1. `config-repo/vendor-scripts/<stem>.sh` / `.groovy` / `.py`
  2. `scripts/stages/<stem>.sh` / `.groovy` / `.py`
  3. No-op (stage skipped)
- `.groovy` scripts receive the `config` map as their `call()` argument; `.sh` and `.py` scripts receive config via environment variables

### job-dsl/

Job DSL scripts that create and maintain all Jenkins jobs from code — no manual job configuration required.

#### seed/seed_job_dsl.groovy

Bootstrap script. Run once from a Freestyle "seed job" to create all other jobs:
- Creates `Build_openjdk_launchers/Build_openjdk<version>_launch` jobs for each active JDK version
- Reads the config repo to discover active JDK versions and their platform lists
- Configures log rotation, parameters, and SCM from the config repo's `jenkins_job_config.json`
- Creates the `Build_openjdk_launchers/` and `Build_openjdk/` top-level folders

#### openjdk_build_pipeline_job_dsl.groovy

Called by the launch pipeline (via `jobDsl()` step) to create or update a single platform build job:
- Fetches `jdk${version}_pipeline_config.json` from the config repo to extract `arch`, `os`, and `variant` for the platform
- Creates `Build_openjdk/Build_openjdk<version>_<distro>_<arch>_<os>` following the AQA-style naming convention
- Configures all pipeline parameters with defaults from `jenkins_job_config.json`
- Sets `disableResume()`, `disableConcurrentBuilds()`, and `CopyArtifactPermissionProperty`

## Jenkins Setup

### Prerequisites

- Pipeline plugin
- Git plugin
- Job DSL plugin
- Copy Artifact plugin
- Workspace Cleanup plugin (`cleanWs`)
- Timestamper plugin

### Seed Job Bootstrap

1. Create a **Freestyle** job named `seed-job`
2. Add string parameters: `CONFIG_REPO_URL`, `CONFIG_REPO_BRANCH`
3. SCM: Git → `https://github.com/adoptium/ci-adoptium-pipelines.git`, branch `main`
4. Build step: **Process Job DSLs** → script path `ci/jenkins/job-dsl/seed/seed_job_dsl.groovy`
5. Run the seed job with your configuration repository URL and branch

The seed job creates all launch jobs. Running a launch job creates the platform build jobs.

See [docs/JOB_DSL_AUTOMATION.md](../../docs/JOB_DSL_AUTOMATION.md) for a complete walkthrough.

## Pipeline Parameters

Parameters are defined by the Job DSL seed job (from `jenkins_job_config.json`) and must not be redefined in the Jenkinsfile. Key parameters:

| Parameter | Type | Description |
|---|---|---|
| `JDK_VERSION` | String | JDK version number (e.g. `21`) |
| `TARGET_OS` | String | Target OS (`linux`, `mac`, `windows`, `aix`) |
| `ARCHITECTURE` | String | CPU architecture (`x64`, `aarch64`, `ppc64le`, `s390x`) |
| `VARIANT` | String | Build variant (`temurin`, `dragonwell`, etc.) |
| `CONFIG_REPO_URL` | String | Configuration repository URL |
| `CONFIG_REPO_BRANCH` | String | Configuration repository branch |
| `RELEASE_TYPE` | Choice | `NIGHTLY` / `WEEKLY` / `RELEASE` |
| `SCM_REF` | String | OpenJDK source tag/branch (required for reproducible compare) |
| `BUILD_REF` | String | temurin-build branch (empty = use config repo default) |
| `AQA_REF` | String | aqa-tests branch (empty = use config repo default) |
| `GROUP_UID` | String | Shared identifier linking all platforms from one launch run |
| `RUN_TESTS` | Boolean | Enable smoke/AQA/TCK test stages |
| `SIGN_ARTIFACTS` | Boolean | Enable signing stages |
| `ENABLE_INSTALLERS` | Boolean | Enable installer build/sign stages |
| `ENABLE_TCK` | Boolean | Enable TCK test stage (Temurin only) |
| `PUBLISH_ARTIFACTS` | Boolean | Enable publish stage |
| `REPRODUCIBLE_COMPARE_BUILD` | Boolean | Enable reproducible compare stage |
| `CLEAN_WORKSPACE_AFTER_STAGE` | Boolean | Clean workspace after each stage |

## Stage Restart Behaviour

Each stage:
1. Calls `cleanWs()` to start clean
2. Checks out this repo and the config repo
3. Calls `BuildUidHelper.initializeBuildContext()` — generates or **reuses** `BUILD_UID` from the previous run
4. Calls `validatePrerequisites()` — verifies required earlier stages passed (via `BUILD_STAGE_RESULTS` env var)
5. Calls `copyArtifacts` to pull in artifacts from earlier stages of the **same build number**

On "Restart from Stage", Jenkins preserves all env vars from the previous run including `BUILD_UID` and `BUILD_STAGE_RESULTS`.

> **Important**: "Rebuild" (not "Restart from Stage") does **not** preserve `BUILD_STAGE_RESULTS`. The pipeline detects this and fails with a clear user error.

## Configuration Repository

Expected structure of the config repo (e.g. `ci-temurin-config`):

```
<config-repo>/
├── adoptium_pipeline_config.json      # Pipeline defaults (repo URLs, branches, variant)
├── jenkins_job_config.json            # Job DSL settings (log rotation, default params, active JDKs)
└── configurations/
    ├── jdk21_pipeline_config.json     # Platform matrix for JDK 21
    ├── jdk17_pipeline_config.json
    └── ...
```

Optionally, vendor-specific stage overrides:
```
<config-repo>/
└── vendor-scripts/
    ├── 02-build.sh                    # Replaces scripts/stages/02-build.sh for this vendor
    └── 10-digital-artifact-sign.sh   # Replaces scripts/stages/10-digital-artifact-sign.sh
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `MissingPropertyException: No such property: buildUidHelper` | Binding entry not initialised | Ensure `buildUidHelper = null` (no `def`) at top of PipelineHelper |
| `ClassCastException: WorkflowScript cannot be cast to DSL` | `init(this)` pattern used — `this` inside a free function is `WorkflowScript`, not the DSL | Lib files must call steps directly (no `steps.` prefix, no `init()`) |
| `BUILD_STAGE_RESULTS is empty` on non-Initialize stage | Triggered via "Rebuild" instead of "Restart from Stage" | Use "Restart from Stage", or trigger a fresh build |
| `Configuration file not found` | `CONFIG_REPO_URL` or `CONFIG_REPO_BRANCH` wrong | Verify parameters; check config repo structure |
| `Artifact not found` on stage restart | Prerequisite stage artifacts not archived | Ensure prerequisite stages ran and `archiveArtifacts` succeeded |

## Related Documentation

- [docs/BUILD_JOB_NAMING_CONVENTION.md](../../docs/BUILD_JOB_NAMING_CONVENTION.md) — Job naming schema and folder layout
- [docs/JOB_DSL_AUTOMATION.md](../../docs/JOB_DSL_AUTOMATION.md) — Full Job DSL setup guide
- [docs/BUILD_UID_INTEGRATION.md](../../docs/BUILD_UID_INTEGRATION.md) — BUILD_UID lifecycle detail
- [docs/JENKINS_RESTART_BEHAVIOR.md](../../docs/JENKINS_RESTART_BEHAVIOR.md) — Restart vs Rebuild
- [docs/CONFIGURATION_GUIDE.md](../../docs/CONFIGURATION_GUIDE.md) — Config JSON reference
- [docs/STAGE_IO_SPECIFICATION.md](../../docs/STAGE_IO_SPECIFICATION.md) — Stage input/output contracts
