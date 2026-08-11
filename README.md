# Adoptium CI Pipelines

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

A modular, CI-agnostic build pipeline for Eclipse Adoptium OpenJDK builds.

## Overview

This repository contains the pipeline code for building, signing, testing, and publishing Eclipse Adoptium OpenJDK binaries. The architecture separates pipeline _code_ (this repo) from vendor _configuration_ (a separate config repo such as [ci-temurin-config](https://github.com/adoptium/ci-temurin-config)), so the same scripts can drive builds across multiple CI platforms and vendor configurations without modification.

Key properties:

- **Stage-level restartability** — restart from any failed stage; no costly full rebuilds
- **CI-agnostic stage scripts** — `scripts/` contains plain shell scripts that run identically on Jenkins, locally, or any other CI platform
- **Declarative Jenkins pipeline** with shared Groovy library helpers in `ci/jenkins/lib/`
- **Two-pipeline Jenkins model** — a _launch_ pipeline fans out to parallel platform _build_ pipelines
- **Job DSL automation** — all Jenkins jobs are created and updated from code; no manual job configuration

## Repository Layout

```
ci-adoptium-pipelines/
│
├── ci/
│   ├── jenkins/
│   │   ├── Jenkinsfile.declarative        # Platform build pipeline
│   │   ├── Jenkinsfile.launch             # Multi-platform launch pipeline
│   │   ├── lib/
│   │   │   ├── BuildUidHelper.groovy      # BUILD_UID tracking & stage results
│   │   │   ├── ConfigHelper.groovy        # pipeline-config.json generation
│   │   │   ├── PipelineHelper.groovy      # Stage lifecycle (init/finalize/tracking)
│   │   │   └── StageScriptRunner.groovy   # Vendor-overridable script resolution
│   │   └── job-dsl/
│   │       ├── openjdk_build_pipeline_job_dsl.groovy   # Job DSL: per-platform build job
│   │       └── seed/
│   │           └── seed_job_dsl.groovy # Job DSL: bootstrap seed job
│   │
│   └── local/
│       ├── run-pipeline.py          # Local pipeline runner
│       ├── stage_resolver.py        # Stage name/script resolution
│       └── workspace_manager.py     # Local workspace lifecycle
│
├── scripts/
│   ├── lib/
│   │   ├── config-utils.sh          # JSON config helpers
│   │   ├── logging-utils.sh         # Logging utilities
│   │   ├── artifact-utils.sh        # Artifact management helpers
│   │   ├── load-json-config.py      # Generates pipeline-config.json
│   │   └── load-adoptium-pipeline-config-json.py
│   └── stages/
│       ├── 02-build.sh                    # JDK compilation
│       ├── 03-internal-code-sign.sh       # JMOD internal signing (Windows/Mac JDK 11+)
│       ├── 04-assemble-images.sh          # OpenJDK make images after internal signing
│       ├── 06-post-build-code-sign.sh     # Post-build binary code signing
│       ├── 07-installer.sh                # Platform installers
│       ├── 08-code-sign-installer.sh      # Installer code signing + macOS notarization
│       ├── 09-sbom-sign.sh                # SBOM JSF signing
│       ├── 10-digital-artifact-sign.sh    # GPG digital artifact signing
│       ├── 11-verify-signing.sh           # Signature verification
│       ├── 12-validate-sbom.sh      # SBOM validation
│       ├── 13-smoke-tests.sh        # Smoke tests
│       ├── 14-aqa-tests.sh          # AQA test suite
│       ├── 15-tck-tests.sh          # TCK tests
│       ├── 16-publish.sh            # Artifact publication
│       └── 20-reproducible-compare.sh # Reproducible build comparison
│
├── tests/
│   ├── test_determine_filename.sh
│   └── test_release_type_validation.sh
│
├── tools/
│   ├── convert-groovy-to-json.py
│   ├── convert-all-legacy-groovy-configs.py
│   └── convert-legacy-configs-to-new-architecture.py
│
└── docs/                            # Extended documentation
```

## Jenkins Pipeline Architecture

### Two-Pipeline Model

```
seed-job (Freestyle)
  └─ seed_job_dsl.groovy  ← creates/updates all jobs
       │
       ├─ Build_openjdk_launchers/
       │    ├─ Build_openjdk21_launch  (Jenkinsfile.launch)
       │    │    └─ fans out in parallel to:
       │    │         ├─ Build_openjdk21_temurin_x86-64_linux   (Jenkinsfile.declarative)
       │    │         ├─ Build_openjdk21_temurin_aarch64_linux
       │    │         └─ Build_openjdk21_temurin_aarch64_mac  ...
       │    ├─ Build_openjdk17_launch
       │    └─ ...
       │
       └─ Build_openjdk/
            ├─ Build_openjdk21_temurin_x86-64_linux
            ├─ Build_openjdk21_temurin_aarch64_linux
            └─ ...
```

**Launch pipeline** (`Jenkinsfile.launch`) — fetches the config repo, determines which platforms to build, optionally regenerates platform jobs via Job DSL, then triggers all selected platform builds in parallel.

**Build pipeline** (`Jenkinsfile.declarative`) — runs the full single-platform pipeline from Initialize through Publish. Loads shared Groovy helpers from `ci/jenkins/lib/` after checkout. Supports "Restart from Stage" natively.

### Shared Groovy Libraries (`ci/jenkins/lib/`)

Each lib file is a plain CPS script loaded with `load()` — it calls pipeline steps (`echo`, `sh`, `env`, `params`, etc.) directly without any delegation wrapper. No Jenkins Shared Library plugin is required.

| File | Responsibility |
|---|---|
| [`BuildUidHelper.groovy`](ci/jenkins/lib/BuildUidHelper.groovy) | Generates/reuses `BUILD_UID` and `GROUP_UID`; serialises per-stage results into `BUILD_STAGE_RESULTS` for prerequisite validation across restarts |
| [`PipelineHelper.groovy`](ci/jenkins/lib/PipelineHelper.groovy) | `initializeStage()` (cleanWs, checkout, config-repo clone, BUILD_UID init, copyArtifacts); `finalizeStage()`; `executeStageWithTracking()` |
| [`ConfigHelper.groovy`](ci/jenkins/lib/ConfigHelper.groovy) | Calls `load-json-config.py` to produce `pipeline-config.json`; sets `CONFIG_*` env vars used by `when {}` blocks |
| [`StageScriptRunner.groovy`](ci/jenkins/lib/StageScriptRunner.groovy) | Resolves and runs a stage script with vendor-override support (tries `config-repo/vendor-scripts/` before `scripts/stages/`) |

### Vendor Script Override

For each stage stem (e.g. `02-build`), `StageScriptRunner` searches in order:

1. `config-repo/vendor-scripts/02-build.sh`
2. `config-repo/vendor-scripts/02-build.groovy`
3. `config-repo/vendor-scripts/02-build.py`
4. `scripts/stages/02-build.sh` ← default implementation
5. `scripts/stages/02-build.groovy`
6. `scripts/stages/02-build.py`
7. No-op (stage skipped)

## Pipeline Stages

Stage execution is controlled by two mechanisms:

- **`stageDisabled`** (in `scripts/stages/NN-stem.params.json`): when `true`, the stage is entirely skipped and its parameters are excluded from the Jenkins job UI. Vendors can override this per stage in their config repo. See [`docs/STAGE_DEFINITION_REFERENCE.md`](docs/STAGE_DEFINITION_REFERENCE.md).
- **`stageCondition`**: a list of `{ param, value }` pairs that must all be satisfied at runtime for the stage to execute. Evaluated by `stageConditionMet()` in `Jenkinsfile.declarative` and `_stage_condition_met()` in `run-pipeline.py`.

| # | Stage | Script | Owns parameter | stageCondition gates on | stageDisabled default |
|---|---|---|---|---|---|
| — | Initialize | _(ConfigHelper)_ | — | always | — |
| 02 | Build | `02-build.sh` | — | always | false |
| 03 | Internal Code Sign | `03-internal-code-sign.sh` | `SIGN_ARTIFACTS` | `SIGN_ARTIFACTS=true`, macOS/Win, JDK≥11 | false |
| 04 | Assemble Images | `04-assemble-images.sh` | — | `SIGN_ARTIFACTS=true`, macOS/Win, JDK≥11 | false |
| 06 | Post-Build Code Sign | `06-post-build-code-sign.sh` | — | `SIGN_ARTIFACTS=true` | false |
| 07 | Build Installer | `07-installer.sh` | `ENABLE_INSTALLERS` | `ENABLE_INSTALLERS=true` | false |
| 08 | Code Sign Installer | `08-code-sign-installer.sh` | — | `ENABLE_INSTALLERS=true`, `SIGN_ARTIFACTS=true` | false |
| 09 | SBOM Sign | `09-sbom-sign.sh` | — | `SIGN_ARTIFACTS=true`, `CREATE_SBOM=true` | false |
| 10 | Digital Artifact Sign | `10-digital-artifact-sign.sh` | — | `SIGN_ARTIFACTS=true`, non-PR | false |
| 11 | Verify Signing | `11-verify-signing.sh` | — | `SIGN_ARTIFACTS=true`, non-PR | false |
| 12 | Validate SBOM | `12-validate-sbom.sh` | — | `CREATE_SBOM=true` (vendor impl required) | false |
| 13 | Smoke Tests | `13-smoke-tests.sh` | — | `RUN_TESTS=true`, build succeeded | false |
| 14 | AQA Tests | `14-aqa-tests.sh` | `RUN_TESTS` | `RUN_TESTS=true`, smoke tests passed | false |
| 15 | TCK Tests | `15-tck-tests.sh` | `ENABLE_TCK` | `ENABLE_TCK=true`, Temurin, smoke tests passed | false |
| 16 | Publish Artifacts | `16-publish.sh` | `PUBLISH_ARTIFACTS` | `PUBLISH_ARTIFACTS=true` | false |
| 20 | Reproducible Compare | `20-reproducible-compare.sh` | `RUN_REPRODUCIBLE_COMPARE` | `RUN_REPRODUCIBLE_COMPARE=true`, `SCM_REF` set | false |

Each stage calls `initializeStage()` which: cleans the workspace, checks out this repo, clones the config repo (sparse), initialises/reuses `BUILD_UID`, validates prerequisites, and copies required artifacts from the current build.

## Configuration Repository

The pipeline reads build configuration from a separately maintained config repo supplied via `CONFIG_REPO_URL`. The config repo must contain:

```
<config-repo>/
├── adoptium_pipeline_config.json      # Pipeline-level defaults (repo URLs, branches)
├── jenkins_job_config.json            # Job DSL settings (log rotation, default params)
└── configurations/
    ├── jdk21_pipeline_config.json     # Per-version platform matrix
    ├── jdk17_pipeline_config.json
    └── ...
```

At runtime, `ConfigHelper` calls `scripts/lib/load-json-config.py` which merges the platform-level JSON with job parameters to produce `pipeline-config.json` — the single source of truth for all subsequent stages.

## Jenkins Setup

### Seed Job Bootstrap

1. Create a Jenkins **Freestyle** job named `seed-job`
2. Add parameters: `CONFIG_REPO_URL` (String), `CONFIG_REPO_BRANCH` (String)
3. SCM: Git → this repository
4. Build step: **Process Job DSLs** → `ci/jenkins/job-dsl/seed/seed_job_dsl.groovy`
5. Run the seed job with your config repo URL and branch

The seed job creates all launch and platform build jobs automatically.

### Required Jenkins Plugins

- Pipeline
- Git
- Job DSL
- Copy Artifact
- Workspace Cleanup (`cleanWs`)
- Timestamper

## Local Execution

```bash
# Full build locally
python3 ci/local/run-pipeline.py \
  --jdk-version jdk21u \
  --variant temurin \
  --target-os linux \
  --architecture x64

# Resume from a specific stage
python3 ci/local/run-pipeline.py \
  --jdk-version jdk21u \
  --variant temurin \
  --target-os linux \
  --architecture x64 \
  --start-from-stage smoke-tests

# Use a custom config repo
python3 ci/local/run-pipeline.py \
  --jdk-version jdk21u \
  --variant temurin \
  --target-os mac \
  --architecture aarch64 \
  --config-repo-url https://github.com/myorg/my-jdk-configs.git
```

See [`ci/local/README.md`](ci/local/README.md) for full options.

## Documentation

| Document | Topic |
|---|---|
| [`docs/CI_AGNOSTIC_ARCHITECTURE.md`](docs/CI_AGNOSTIC_ARCHITECTURE.md) | 3-layer design, before/after comparison |
| [`docs/CODE_CONFIG_SEPARATION.md`](docs/CODE_CONFIG_SEPARATION.md) | Pipeline code vs config repo separation |
| [`docs/CONFIGURATION_GUIDE.md`](docs/CONFIGURATION_GUIDE.md) | JSON configuration reference |
| [`docs/RESTARTABILITY_GUIDE.md`](docs/RESTARTABILITY_GUIDE.md) | Stage restart patterns |
| [`docs/JENKINS_RESTART_BEHAVIOR.md`](docs/JENKINS_RESTART_BEHAVIOR.md) | BUILD_UID and restart mechanics |
| [`docs/BUILD_UID_INTEGRATION.md`](docs/BUILD_UID_INTEGRATION.md) | BUILD_UID tracking detail |
| [`docs/STAGE_IO_SPECIFICATION.md`](docs/STAGE_IO_SPECIFICATION.md) | Stage input/output contracts |
| [`docs/JOB_DSL_AUTOMATION.md`](docs/JOB_DSL_AUTOMATION.md) | Job DSL setup guide |
| [`docs/PIPELINE_RUNNER_GUIDE.md`](docs/PIPELINE_RUNNER_GUIDE.md) | Local runner reference |
| [`docs/REPRODUCIBLE_COMPARE.md`](docs/REPRODUCIBLE_COMPARE.md) | Reproducible build comparison |
| [`docs/JENKINS_ENVIRONMENT_VARIABLES.md`](docs/JENKINS_ENVIRONMENT_VARIABLES.md) | Environment variable reference |
| [`tools/README.md`](tools/README.md) | Legacy config conversion tools |

## License

Apache License 2.0 — see [LICENSE](LICENSE).
