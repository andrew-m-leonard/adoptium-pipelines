# Adoptium CI Pipelines

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

A modular, CI-agnostic build pipeline for Eclipse Adoptium OpenJDK builds.

## Overview

This repository contains the pipeline code for building, signing, testing, and publishing Eclipse Adoptium OpenJDK binaries. The architecture separates pipeline _code_ (this repository) from vendor _configuration_ (a separate config repository such as [ci-temurin-config](https://github.com/adoptium/ci-temurin-config)), so the same scripts can drive builds across multiple CI platforms and vendor configurations without modification.

Key properties:

- **Two CI implementations included** — a full declarative Jenkins pipeline (`ci/jenkins/`) and a local Python runner (`ci/local/`) that executes the same stage scripts without a CI server
- **Stage-level restartability** — restart from any failed stage; no costly full rebuilds
- **CI-agnostic stage scripts** — `scripts/` contains plain shell scripts that run identically on Jenkins, locally, or any other CI platform
- **Declarative Jenkins pipeline** with shared Groovy library helpers in `ci/jenkins/lib/`
- **Two-pipeline Jenkins model** — a _launch_ pipeline fans out to parallel platform _build_ pipelines
- **Job DSL automation** — all Jenkins jobs are created and updated from code; no manual job configuration

## Repository Layout

```text
ci-adoptium-pipelines/
│
├── ci/
│   ├── jenkins/
│   │   ├── Jenkinsfile.declarative        # Platform build pipeline
│   │   ├── Jenkinsfile.launch             # Multi-platform launch pipeline
│   │   ├── Jenkinsfile.seed               # Seed job pipeline
│   │   ├── lib/
│   │   │   ├── BuildUidHelper.groovy      # BUILD_UID tracking & stage results
│   │   │   ├── ConfigHelper.groovy        # pipeline-config.json generation
│   │   │   ├── NodeAgentHelper.groovy     # Node agent label resolution
│   │   │   ├── PipelineHelper.groovy      # Stage lifecycle (init/finalize/tracking)
│   │   │   ├── PipelineStages.groovy      # Stage definitions & ordering
│   │   │   ├── SeedHelper.groovy          # Job DSL seed helpers
│   │   │   ├── StageScriptRunner.groovy   # Vendor-overridable script resolution
│   │   │   └── load-jenkins-json-config.py  # Loads Jenkins job config JSON
│   │   └── job-dsl/
│   │       ├── openjdk_build_pipeline_job_dsl.groovy   # Job DSL: per-platform build job
│   │       └── seed/
│   │           └── seed_job_dsl.groovy    # Job DSL: bootstrap seed job
│   │
│   └── local/
│       ├── run-pipeline.py          # Local pipeline runner entry point
│       └── lib/
│           ├── cli_parser.py        # CLI argument parsing
│           ├── config_repo.py       # Config repository checkout
│           ├── stage_env.py         # Stage environment variable management
│           ├── stage_executor.py    # Stage execution logic
│           ├── stage_params.py      # Stage parameter loading
│           ├── stage_registry.py    # Stage registry & ordering
│           ├── stage_resolver.py    # Stage name/script resolution
│           └── workspace_manager.py # Local workspace lifecycle
│
├── scripts/
│   ├── lib/
│   │   ├── artifact-utils.sh        # Artifact management helpers
│   │   ├── build-metadata-writer.py # Writes build metadata JSON
│   │   ├── collect-stage-params.py  # Collects stage parameter definitions
│   │   ├── config-utils.sh          # JSON config helpers
│   │   ├── load-adoptium-pipeline-config-json.py
│   │   ├── load-pipeline-config-json.py      # Generates pipeline-config.json
│   │   ├── logging-utils.sh         # Logging utilities
│   │   ├── python-runner.sh         # Wrapper to invoke Python scripts from shell
│   │   ├── sbom-workspace-extractor.py  # Extracts SBOM artifacts from workspace
│   │   └── workspace-cleanup.sh     # Workspace cleanup helper
│   └── stages/
│       ├── pipeline-stages.json     # Stage registry (names, order, conditions)
│       ├── 02-build.sh                    # JDK compilation
│       ├── 03-internal-code-sign.sh       # JMOD internal signing (Windows/Mac JDK 11+)
│       ├── 04-assemble-images.sh          # OpenJDK make images after internal signing
│       ├── 06-post-build-code-sign.sh     # Post-build binary code signing
│       ├── 07-installer.sh                # Platform installers
│       ├── 08-code-sign-installer.sh      # Installer code signing + macOS notarization
│       ├── 09-sbom-sign.sh                # SBOM JSF signing
│       ├── 10-digital-artifact-sign.sh    # GPG digital artifact signing
│       ├── 11-verify-signing.sh           # Signature verification
│       ├── 12-validate-sbom.sh            # SBOM validation
│       ├── 13-smoke-tests.sh              # Smoke tests
│       ├── 14-aqa-tests.sh                # AQA test suite
│       ├── 15-tck-tests.sh                # TCK tests
│       ├── 16-publish.sh                  # Artifact publication
│       └── 20-reproducible-compare.sh     # Reproducible build comparison
│       (each stage also has a corresponding NN-stem.params.json)
│
├── tests/
│   ├── test_collect_stage_params.py
│   ├── test_determine_filename.sh
│   └── test_release_type_validation.sh
│
├── tools/
│   ├── batch-convert-groovy-configs.py
│   ├── groovy-pipeline-config-to-json.py
│   └── migrate-groovy-pipeline-configs.py
│
└── docs/                            # Extended documentation (see docs/README.md)
```

## Jenkins Pipeline Architecture

### Two-Pipeline Model

```text
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

**Launch pipeline** (`Jenkinsfile.launch`) — fetches the config repository, determines which platforms to build, optionally regenerates platform jobs via Job DSL, then triggers all selected platform builds in parallel.

**Build pipeline** (`Jenkinsfile.declarative`) — runs the full single-platform pipeline from Initialize through Publish. Loads shared Groovy helpers from `ci/jenkins/lib/` after checkout. Supports "Restart from Stage" natively.

### Shared Groovy Libraries (`ci/jenkins/lib/`)

Each lib file is a plain CPS script loaded with `load()` — it calls pipeline steps (`echo`, `sh`, `env`, `params`, etc.) directly without any delegation wrapper. No Jenkins Shared Library plugin is required.

| File | Responsibility |
|---|---|
| [`BuildUidHelper.groovy`](ci/jenkins/lib/BuildUidHelper.groovy) | Generates/reuses `BUILD_UID` and `GROUP_UID`; serialises per-stage results into `BUILD_STAGE_RESULTS` for prerequisite validation across restarts |
| [`PipelineHelper.groovy`](ci/jenkins/lib/PipelineHelper.groovy) | `initializeStage()` (cleanWs, checkout, config-repository clone, BUILD_UID init, copyArtifacts); `finalizeStage()`; `executeStageWithTracking()` |
| [`ConfigHelper.groovy`](ci/jenkins/lib/ConfigHelper.groovy) | Calls `load-pipeline-config-json.py` to produce `pipeline-config.json`; sets `CONFIG_*` env vars used by `when {}` blocks |
| [`StageScriptRunner.groovy`](ci/jenkins/lib/StageScriptRunner.groovy) | Resolves and runs a stage script with vendor-override support (tries `config-repo/vendor-scripts/` before `scripts/stages/`) |

## Pipeline Stages

Stage execution is controlled by two mechanisms:

- **`stageDisabled`** (in `scripts/stages/NN-stem.params.json`): when `true`, the stage is entirely skipped and its parameters are excluded from the Jenkins job UI. Vendors can override this per stage in their config repository. See [`docs/STAGE_DEFINITION_REFERENCE.md`](docs/STAGE_DEFINITION_REFERENCE.md).
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

Each stage calls `initializeStage()` which: cleans the workspace, checks out this repository, clones the config repository (sparse), initialises/reuses `BUILD_UID`, validates prerequisites, and copies required artifacts from the current build.

## Jenkins Setup

### Seed Job Bootstrap

1. Create a Jenkins **Freestyle** job named `seed-job`
1. Add parameters: `CONFIG_REPO_URL` (String), `CONFIG_REPO_BRANCH` (String)
1. SCM: Git → this repository
1. Build step: **Process Job DSLs** → `ci/jenkins/job-dsl/seed/seed_job_dsl.groovy`
1. Run the seed job with your config repository URL and branch

The seed job creates all launch and platform build jobs automatically.

### Required Jenkins Plugins

- Pipeline
- Git
- Job DSL
- Copy Artifact
- Workspace Cleanup (`cleanWs`)
- Timestamper

## Local Pipeline Architecture

### Single-Process Model

```text
run-pipeline.py
  │
  ├─ Phase 1 — Initialize
  │    clone config-repo → <workspace>/config-repo/
  │    run load-pipeline-config-json.py → pipeline-config.json
  │    archive pipeline-config.json → build_artifacts/
  │
  └─ Phase 2 — Remaining stages (in sequence)
       collate *.params.json from scripts/stages/ + config-repo/vendor-scripts/
       for each enabled stage:
         wipe stage_workspace/
         restore inputs: build_artifacts/ → stage_workspace/
         run stage script (vendor-scripts/ checked first, then scripts/stages/)
         archive outputs: stage_workspace/target/ → build_artifacts/
```

The local runner executes all stages sequentially in a single process — there is no fan-out to parallel platform jobs. It mirrors the Jenkins build pipeline exactly: each stage receives a clean workspace, has its inputs explicitly restored from a durable artifact store (`build_artifacts/`), and archives its outputs back before the next stage begins. Use `--start-from-stage` to resume from any stage after a failure, the same way Jenkins supports "Restart from Stage".

### Python Library (`ci/local/lib/`)

Each module is imported by `run-pipeline.py` and has a single responsibility.

| Module | Responsibility |
|---|---|
| [`cli_parser.py`](ci/local/lib/cli_parser.py) | Phase-1 fixed CLI options (`--jdk-version`, `--target-os`, `--architecture`, etc.); deferred capture of unknown stage params for Phase-2 validation |
| [`config_repo.py`](ci/local/lib/config_repo.py) | Clones the config repository (depth-1) into `<workspace>/config-repo/` during Initialize |
| [`stage_params.py`](ci/local/lib/stage_params.py) | Discovers and merges `*.params.json` from `scripts/stages/` and `config-repo/vendor-scripts/`; validates CLI tokens against the complete param set |
| [`stage_registry.py`](ci/local/lib/stage_registry.py) | Reads `scripts/stages/pipeline-stages.json`; determines stage order and which stages are enabled given the current param values |
| [`stage_resolver.py`](ci/local/lib/stage_resolver.py) | Resolves which script to execute for a given stage stem — vendor override first, then default |
| [`stage_env.py`](ci/local/lib/stage_env.py) | Builds the environment dict injected into each stage script (`WORKSPACE`, `CONFIG_FILE`, `INPUT_ARTIFACTS_DIR`, `TARGET_DIR`, stage params) |
| [`stage_executor.py`](ci/local/lib/stage_executor.py) | Executes a resolved stage script as a subprocess; captures exit code; records stage pass/fail |
| [`workspace_manager.py`](ci/local/lib/workspace_manager.py) | Manages `stage_workspace/` (pre/post cleanup) and `build_artifacts/` (archive and restore); enforces workspace validation rules |

### Workspace Layout

```text
~/openjdk-build/                    # --workspace root (persists for the pipeline run)
├── config-repo/                    # Cloned once at Initialize; not re-cloned per stage
│   ├── adoptium_pipeline_config.json
│   ├── configurations/
│   └── vendor-scripts/
├── stage_workspace/                # ≈ Jenkins WORKSPACE — wiped before every stage
│   ├── pipeline-config.json        # Restored from build_artifacts/ before each stage
│   ├── *.tar.gz, *.zip …           # Other stage inputs restored from build_artifacts/
│   └── target/                     # TARGET_DIR — stage writes outputs here
└── build_artifacts/                # ≈ Jenkins artifact store — durable, never auto-cleaned
    ├── pipeline-config.json        # Archived by Initialize
    ├── OpenJDK*.tar.gz             # Archived by Build
    └── …                           # Archived by downstream stages
```

### Quick Start

```bash
# Full build
python3 ci/local/run-pipeline.py \
  --jdk-version jdk21 \
  --target-os linux \
  --architecture x64 \
  --config-repo-url https://github.com/adoptium/ci-temurin-config.git

# Resume from a specific stage after a failure
python3 ci/local/run-pipeline.py \
  --jdk-version jdk21 \
  --target-os linux \
  --architecture x64 \
  --config-repo-url https://github.com/adoptium/ci-temurin-config.git \
  --start-from-stage 13-smoke-tests

# Vendor-specific config repository
python3 ci/local/run-pipeline.py \
  --jdk-version jdk21 \
  --target-os mac \
  --architecture aarch64 \
  --config-repo-url https://github.com/myorg/my-jdk-configs.git
```

See [`ci/local/README.md`](ci/local/README.md) for the full CLI reference, workspace validation rules, and stage parameter documentation.

## Shared Concepts

### Configuration Repository

Both the Jenkins and local pipelines read build configuration from a separately maintained config repository supplied at runtime (`CONFIG_REPO_URL` / `--config-repo-url`). The config repository must contain:

```text
<config-repo>/
├── adoptium_pipeline_config.json      # CI-agnostic defaults (repo URLs, branches, variant)
├── jenkins_job_config.json            # Jenkins-only: job DSL settings, stage agent labels
├── configurations/
│   ├── jdk21_pipeline_config.json     # Per-version platform matrix
│   ├── jdk17_pipeline_config.json
│   └── ...
└── vendor-scripts/                    # Optional vendor-specific stage script overrides
    ├── 02-build.sh
    └── ...
```

`scripts/lib/load-pipeline-config-json.py` merges the per-version platform JSON with runtime parameters to produce `pipeline-config.json` — the single source of truth passed to every subsequent stage via `$CONFIG_FILE`. `jenkins_job_config.json` is Jenkins-specific and is not read by the local runner.

See [`docs/CODE_CONFIG_SEPARATION.md`](docs/CODE_CONFIG_SEPARATION.md) for a full breakdown of each config file and how it flows through the pipeline.

### Vendor Script Override

Any stage script in `scripts/stages/` can be replaced per-vendor by placing a script of the same stem in the config repository's `vendor-scripts/` directory. Both orchestrators resolve scripts in the same priority order, with a minor difference: Jenkins also supports `.groovy` vendor scripts; the local runner does not.

| Priority | Jenkins (`StageScriptRunner.groovy`) | Local (`stage_resolver.py`) |
|---|---|---|
| 1 | `config-repo/vendor-scripts/<stem>.sh` | `config-repo/vendor-scripts/<stem>.sh` |
| 2 | `config-repo/vendor-scripts/<stem>.groovy` | `config-repo/vendor-scripts/<stem>.py` |
| 3 | `config-repo/vendor-scripts/<stem>.py` | `scripts/stages/<stem>.sh` ← default |
| 4 | `scripts/stages/<stem>.sh` ← default | `scripts/stages/<stem>.py` |
| 5 | `scripts/stages/<stem>.groovy` | No-op (stage skipped) |
| 6 | `scripts/stages/<stem>.py` | |
| 7 | No-op (stage skipped) | |

### Shared Stage Libraries (`scripts/lib/`)

These files are sourced or invoked by every stage script regardless of whether it runs on Jenkins or locally. They are the only place shared logic lives — stage scripts must not duplicate what is here.

| File | Responsibility |
|---|---|
| [`logging-utils.sh`](scripts/lib/logging-utils.sh) | Timestamped `log_info` / `log_warn` / `log_error` / `log_section` functions written to stderr |
| [`config-utils.sh`](scripts/lib/config-utils.sh) | `validate_standard_environment()` (checks `WORKSPACE`, `CONFIG_FILE`, defaults `TARGET_DIR`); `get_config_value()` / `get_config_bool()` JSON helpers via `jq` |
| [`artifact-utils.sh`](scripts/lib/artifact-utils.sh) | `prepare_output_dir()`, `copy_artifacts()`, `verify_artifact()`, `create_checksums()`, `create_stage_metadata()`, `determine_filename()` |
| [`load-pipeline-config-json.py`](scripts/lib/load-pipeline-config-json.py) | Merges `adoptium_pipeline_config.json` + per-version platform JSON + runtime params → writes `pipeline-config.json` |
| [`load-adoptium-pipeline-config-json.py`](scripts/lib/load-adoptium-pipeline-config-json.py) | Standalone reader for `adoptium_pipeline_config.json`; used by tools and the seed job |
| [`collect-stage-params.py`](scripts/lib/collect-stage-params.py) | Collates all `*.params.json` sidecars (default + vendor) into a single document consumed by Job DSL and the local runner |
| [`build-metadata-writer.py`](scripts/lib/build-metadata-writer.py) | Writes `build-metadata.json` after a successful build stage |
| [`sbom-workspace-extractor.py`](scripts/lib/sbom-workspace-extractor.py) | Extracts the `Build Workspace Directory` path from an SBOM JSON file; used for reproducible build path padding |
| [`python-runner.sh`](scripts/lib/python-runner.sh) | Resolves `python3`/`python` and execs a given `.py` script; used as the single shell-context Python entry point |
| [`workspace-cleanup.sh`](scripts/lib/workspace-cleanup.sh) | Standalone script; cleans the ephemeral stage workspace pre/post stage based on `CLEANUP_TYPE` and `cleanWorkspaceAfterStage` config |

See [`docs/SHELL_SCRIPTS_SUMMARY.md`](docs/SHELL_SCRIPTS_SUMMARY.md) for the full function-level reference.

## Documentation

| Document | Topic |
|---|---|
| [`docs/CI_AGNOSTIC_ARCHITECTURE.md`](docs/CI_AGNOSTIC_ARCHITECTURE.md) | 3-layer design, before/after comparison, stage interface contract |
| [`docs/CODE_CONFIG_SEPARATION.md`](docs/CODE_CONFIG_SEPARATION.md) | Config repository structure, each config file explained, flow through the pipeline |
| [`docs/CONFIG_SCHEMA.md`](docs/CONFIG_SCHEMA.md) | JSON schema reference for all config files |
| [`docs/SHELL_SCRIPTS_SUMMARY.md`](docs/SHELL_SCRIPTS_SUMMARY.md) | Full function-level reference for `scripts/lib/` and all stage scripts |
| [`docs/STAGE_DEFINITION_REFERENCE.md`](docs/STAGE_DEFINITION_REFERENCE.md) | `stageCondition` / `stageDisabled` schema in `*.params.json` sidecar files |
| [`docs/WORKSPACE_ARTIFACTS_ARCHITECTURE.md`](docs/WORKSPACE_ARTIFACTS_ARCHITECTURE.md) | Workspace layout, artifact archive/restore flow, Jenkins vs local side-by-side |
| [`docs/BUILD_UID_INTEGRATION.md`](docs/BUILD_UID_INTEGRATION.md) | `BUILD_UID` / `GROUP_UID` lifecycle and restart mechanics |
| [`docs/JOB_DSL_AUTOMATION.md`](docs/JOB_DSL_AUTOMATION.md) | Seed job setup, launch job SHA staleness checks, platform job creation |
| [`docs/BUILD_JOB_NAMING_CONVENTION.md`](docs/BUILD_JOB_NAMING_CONVENTION.md) | Jenkins job naming schema and folder layout |
| [`docs/PIPELINE_RUNNER_GUIDE.md`](docs/PIPELINE_RUNNER_GUIDE.md) | Local runner CLI reference, workspace validation rules, stage parameters |
| [`docs/REPRO_COMPARE_INTEGRATION.md`](docs/REPRO_COMPARE_INTEGRATION.md) | Reproducible build comparison stage integration |
| [`docs/UNIVERSAL_STAGE_PATTERN.md`](docs/UNIVERSAL_STAGE_PATTERN.md) | Template and conventions for writing a new stage script |
| [`docs/DEVELOPMENT_GUIDE.md`](docs/DEVELOPMENT_GUIDE.md) | Contributor guide: architecture rules, code style, adding a stage |
| [`tools/README.md`](tools/README.md) | Legacy Groovy config migration tools |

## License

Apache License 2.0 — see [LICENSE](LICENSE).
