# CI-Agnostic Pipeline Architecture

## Problem Statement

The original `openjdk_build_pipeline.groovy` was a monolithic Jenkins Groovy script that tightly coupled all build logic to Jenkins:

- **Vendor lock-in**: Complete dependency on Jenkins infrastructure and Groovy DSL
- **No local testing**: Impossible to run or debug pipeline stages outside Jenkins
- **Maintenance burden**: ~2000+ line monolithic script with mixed orchestration and business logic
- **Migration barrier**: Moving to another CI system would require a complete rewrite

The solution is a **CI-agnostic architecture** that separates orchestration from implementation.

## Old Architecture (Before Refactoring)

```
┌─────────────────────────────────────────────────────────────┐
│ openjdk_build_pipeline.groovy (Monolithic Groovy Script)    │
│                                                             │
│  Stage: Build         → Groovy calls make-adopt-build-farm  │
│  Stage: Internal Sign → Groovy calls downstream job         │
│  Stage: Sign          → Groovy calls downstream job         │
│  Stage: Installer     → Groovy calls downstream job         │
│  Stage: Smoke Tests   → Groovy calls test scripts           │
│  Stage: AQA Tests     → Groovy calls downstream job         │
│                                                             │
│  ⚠ Tightly coupled to Jenkins — cannot run locally         │
│  ⚠ Cannot migrate to other CI systems                      │
│  ⚠ Cannot test individual stages independently             │
└─────────────────────────────────────────────────────────────┘
```

## Solution: Separation of Concerns

### Layer 1: CI Orchestration (CI-Specific)

- **Purpose**: Pipeline definition, stage sequencing, artifact management
- **Current implementation**: Jenkins declarative pipeline (`Jenkinsfile.declarative`) + shared Groovy libs in `ci/jenkins/lib/`
- **Responsibility**: define stages and order, manage artifacts (archive/retrieve), conditional execution, provide environment variables to stage scripts
- **Local equivalent**: `ci/local/run-pipeline.py`

### Layer 2: Stage Scripts (CI-Agnostic)

- **Purpose**: Actual build / sign / test logic
- **Language**: Portable Bash scripts (`scripts/stages/`)
- **Key property**: same scripts run identically in Jenkins, locally, or any other CI platform
- **Vendor override**: the config repo can supply `vendor-scripts/<stem>.sh` to replace any default stage script — the orchestration layer tries the vendor script first before falling back to `scripts/stages/`

### Layer 3: Build Tools (Already CI-Agnostic)

- **Purpose**: Core build functionality
- **Examples**: `make-adopt-build-farm.sh`, signing tools, test runners
- No changes needed — already portable

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────┐
│  Layer 1: CI Orchestration                                    │
│                                                              │
│  Jenkins                          Local                      │
│  ┌─────────────────────────────┐  ┌──────────────────────┐  │
│  │ Jenkinsfile.declarative     │  │ run-pipeline.py      │  │
│  │ + ci/jenkins/lib/           │  │ + workspace_manager  │  │
│  │   PipelineHelper.groovy     │  └──────────────────────┘  │
│  │   ConfigHelper.groovy       │                            │
│  │   StageScriptRunner.groovy  │  Future: GitLab, GHA, ...  │
│  │   BuildUidHelper.groovy     │                            │
│  └─────────────────────────────┘                            │
└──────────────────┬───────────────────────────────────────────┘
                   │ calls (via StageScriptRunner / subprocess)
                   │ checks vendor-scripts/ first, then default
                   ▼
┌──────────────────────────────────────────────────────────────┐
│  Layer 2: Stage Scripts (CI-Agnostic Bash)                   │
│                                                              │
│  config-repo/vendor-scripts/         scripts/stages/                    │
│  ├── 02-build.sh  (optional)         ├── 02-build.sh  (default)         │
│  ├── 10-digital-artifact-sign.sh     ├── 03-internal-code-sign.sh       │
│  └── ...                             ├── 06-post-build-code-sign.sh     │
│                                      ├── 07-installer.sh                │
│  Vendor overrides take               ├── 10-digital-artifact-sign.sh    │
│  priority over defaults              ├── 13-smoke-tests.sh              │
│                                      ├── 14-aqa-tests.sh                │
│                                      ├── 20-reproducible-compare.sh     │
│                                      └── ...                            │
│                                                              │
│  scripts/lib/  (shared utilities)                           │
│  ├── logging-utils.sh                                       │
│  ├── config-utils.sh                                        │
│  └── artifact-utils.sh                                      │
└──────────────────┬───────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────┐
│  Layer 3: Build Tools (Already CI-Agnostic)                  │
│  make-adopt-build-farm.sh, signing tools, test runners ...   │
└──────────────────────────────────────────────────────────────┘
```

## Standard Interface Contract

Every stage script communicates with the orchestration layer through:

### Inputs

| Channel | Description |
|---|---|
| `CONFIG_FILE` | Path to `pipeline-config.json` (generated by Initialize stage) |
| `INPUT_ARTIFACTS_DIR` | Directory containing artifacts from previous stages (set by orchestration) |
| `TARGET_DIR` | Directory where this stage writes its output artifacts (set by orchestration) |
| `WORKSPACE` | Stage working directory |
| `BUILD_NUMBER` | Build identifier (optional, defaults to `local`) |

### Outputs

| Channel | Description |
|---|---|
| Exit code 0 | Success |
| Exit code non-zero | Failure |
| Files in `${TARGET_DIR}` | Artifacts archived by the orchestration layer |
| `stage-metadata.json` | Stage execution metadata (optional) |
| stdout / stderr | Logs captured by the CI system |

### Artifact Flow

In Jenkins, `initializeStage()` calls `copyArtifacts` to pull artifacts from the current build's archive into `INPUT_ARTIFACTS_DIR` before the stage script runs. The stage writes outputs to `TARGET_DIR`, which is then archived with `archiveArtifacts` for downstream stages.

```
Initialize stage
  → archiveArtifacts pipeline-config.json, jenkins-config.json
       ↓
Each subsequent stage
  copyArtifacts → INPUT_ARTIFACTS_DIR    ← stage reads from here
                      stage logic
                  TARGET_DIR             ← stage writes here
  → archiveArtifacts TARGET_DIR/**/*
```

The local runner (`run-pipeline.py`) mirrors this: artifacts are copied into the stage workspace from a shared `artifacts/` directory, and outputs are copied back after the stage exits.

### Per-Stage Summary

Stage execution is controlled by `stageCondition` entries in each stage's `params.json` sidecar and evaluated at runtime by `stageConditionMet()`. See [`STAGE_DEFINITION_REFERENCE.md`](./STAGE_DEFINITION_REFERENCE.md) for the full schema.

| # | Stage | Script | Defines parameter | stageCondition gates on | Prerequisites | Key Outputs |
|---|---|---|---|---|---|---|
| 01 | Initialize | *(ConfigHelper + load-json-config.py)* | — | always | — | `pipeline-config.json`, `jenkins-config.json` |
| 02 | Build | `02-build.sh` | — | always | Initialize | JDK tarballs/zips, metadata, SBOMs |
| 03 | Internal Code Sign | `03-internal-code-sign.sh` | `SIGN_ARTIFACTS` | `SIGN_ARTIFACTS=true`, macOS/Win, JDK≥11 | Build | Signed JMODs |
| 04 | Assemble Images | `04-assemble-images.sh` | — | `SIGN_ARTIFACTS=true`, macOS/Win, JDK≥11 | Internal Code Sign | Assembled JDK image |
| 06 | Post-Build Code Sign | `06-post-build-code-sign.sh` | `SIGN_ARTIFACTS` | `SIGN_ARTIFACTS=true` | Assemble Images or Build | Code-signed executables |
| 07 | Build Installer | `07-installer.sh` | `ENABLE_INSTALLERS` | `ENABLE_INSTALLERS=true` | Build | `.msi` / `.pkg` / `.deb` / `.rpm` |
| 08 | Code Sign Installer | `08-code-sign-installer.sh` | `SIGN_ARTIFACTS` | `ENABLE_INSTALLERS=true`, `SIGN_ARTIFACTS=true` | Build Installer | Signed + notarized installers |
| 09 | SBOM Sign | `09-sbom-sign.sh` | `SIGN_ARTIFACTS` | `SIGN_ARTIFACTS=true`, `CREATE_SBOM=true` | Post-Build Code Sign | JSF-signed SBOM |
| 10 | Digital Artifact Sign | `10-digital-artifact-sign.sh` | `SIGN_ARTIFACTS` | `SIGN_ARTIFACTS=true` | SBOM Sign | `.sig` / `.asc` GPG signatures |
| 11 | Verify Signing | `11-verify-signing.sh` | `SIGN_ARTIFACTS` | `SIGN_ARTIFACTS=true` | Digital Artifact Sign | Verification report |
| 12 | Validate SBOM | `12-validate-sbom.sh` | — | `CREATE_SBOM=true` | Build | SBOM validation report |
| 13 | Smoke Tests | `13-smoke-tests.sh` | `RUN_TESTS` | `RUN_TESTS=true`, build succeeded | Build | Test results |
| 14 | AQA Tests | `14-aqa-tests.sh` | `RUN_TESTS` | `RUN_TESTS=true`, smoke tests passed | Smoke Tests | AQA test results |
| 15 | TCK Tests | `15-tck-tests.sh` | `ENABLE_TCK` | `ENABLE_TCK=true`, Temurin variant, smoke tests passed | Smoke Tests | TCK test results |
| 16 | Publish Artifacts | `16-publish.sh` | `PUBLISH_ARTIFACTS` | `PUBLISH_ARTIFACTS=true` | Build | Publication confirmation |
| 20 | Reproducible Compare | `20-reproducible-compare.sh` | `RUN_REPRODUCIBLE_COMPARE` | `RUN_REPRODUCIBLE_COMPARE=true`, `SCM_REF` set | Build | `comparison-report.txt`, `reprotest.diff` |

## Example: Build Stage

### Jenkins (Layer 1) — actual current pattern

```groovy
stage('Build') {
    agent { label getNodeLabel() }
    steps {
        script {
            ensureLibsLoaded()
            pipelineHelper.executeStageWithTracking('Build') {
                // cleanWs, checkout scm, config-repo clone, copyArtifacts
                def config = pipelineHelper.initializeStage('Build', ['Initialize'])

                env.TARGET_DIR = "${WORKSPACE}/build_output"

                // StageScriptRunner: tries config-repo/vendor-scripts/02-build.sh first,
                // then scripts/stages/02-build.sh
                def exitCode = stageRunner.run('02-build', config)
                if (exitCode != 0) { error("Build failed with exit code: ${exitCode}") }

                dir(env.TARGET_DIR) {
                    archiveArtifacts artifacts: '**/*', fingerprint: true
                }
                pipelineHelper.finalizeStage('Build')
            }
        }
    }
}
```

### Shell Script (Layer 2) — actual current pattern

```bash
#!/bin/bash
# scripts/stages/02-build.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/logging-utils.sh"
source "${SCRIPT_DIR}/../lib/config-utils.sh"
source "${SCRIPT_DIR}/../lib/artifact-utils.sh"

STAGE_NAME="build"
BUILD_NUMBER="${BUILD_NUMBER:-local}"

main() {
    log_section "${STAGE_NAME} Stage - Start"
    validate_standard_environment

    local config
    config="$(load_config "${CONFIG_FILE}")"
    local java_to_build variant target_os architecture build_args
    java_to_build="$(get_config_value "${config}" ".buildConfig.JAVA_TO_BUILD")"
    variant="$(get_config_value       "${config}" ".buildConfig.VARIANT")"
    target_os="$(get_config_value     "${config}" ".buildConfig.TARGET_OS")"
    architecture="$(get_config_value  "${config}" ".buildConfig.ARCHITECTURE")"
    build_args="$(get_config_value    "${config}" ".buildConfig.BUILD_ARGS")"

    log_info "Building: ${java_to_build} ${variant} ${target_os}-${architecture}"

    prepare_output_dir "${TARGET_DIR}"

    # Clone temurin-build and call make-adopt-build-farm.sh
    # ... (actual build logic)

    create_stage_metadata "${STAGE_NAME}" "SUCCESS" "${TARGET_DIR}"
    log_section "${STAGE_NAME} Stage - Complete"
}

main "$@"
```

## Directory Structure

### ci-adoptium-pipelines (Pipeline Code)

```
ci-adoptium-pipelines/
├── ci/
│   ├── jenkins/
│   │   ├── Jenkinsfile.declarative         # Platform build pipeline
│   │   ├── Jenkinsfile.launch              # Multi-platform launch pipeline
│   │   ├── lib/
│   │   │   ├── BuildUidHelper.groovy       # BUILD_UID tracking & stage results
│   │   │   ├── ConfigHelper.groovy         # pipeline-config.json + jenkins-config.json generation
│   │   │   ├── load-jenkins-json-config.py # Jenkins-specific: jenkins-config.json generation
│   │   │   ├── PipelineHelper.groovy       # Stage lifecycle
│   │   │   └── StageScriptRunner.groovy    # Vendor-override script resolution
│   │   └── job-dsl/
│   │       ├── openjdk_build_pipeline_job_dsl.groovy
│   │       └── seed/
│   │           └── seed_job_dsl.groovy
│   └── local/
│       ├── run-pipeline.py
│       ├── stage_resolver.py
│       └── workspace_manager.py
├── scripts/
│   ├── stages/
│   │   ├── 02-build.sh
│   │   ├── 03-internal-code-sign.sh
│   │   ├── 04-assemble-images.sh
│   │   ├── 06-post-build-code-sign.sh
│   │   ├── 07-installer.sh
│   │   ├── 08-code-sign-installer.sh
│   │   ├── 09-sbom-sign.sh
│   │   ├── 10-digital-artifact-sign.sh
│   │   ├── 11-verify-signing.sh
│   │   ├── 12-validate-sbom.sh
│   │   ├── 13-smoke-tests.sh
│   │   ├── 14-aqa-tests.sh
│   │   ├── 15-tck-tests.sh
│   │   ├── 16-publish.sh
│   │   └── 20-reproducible-compare.sh
│   └── lib/
│       ├── logging-utils.sh
│       ├── config-utils.sh
│       ├── artifact-utils.sh
│       ├── load-json-config.py             # Generates pipeline-config.json
│       └── load-adoptium-pipeline-config-json.py
├── tests/
│   ├── test_determine_filename.sh
│   └── test_release_type_validation.sh
├── tools/
│   ├── convert-groovy-to-json.py
│   ├── convert-all-legacy-groovy-configs.py
│   └── convert-legacy-configs-to-new-architecture.py
└── docs/
```

### ci-temurin-config (Vendor Configuration — Separate Repo)

```
ci-temurin-config/
├── adoptium_pipeline_config.json           # Pipeline defaults (repo URLs, branches, variant)
├── jenkins_job_config.json                 # Job DSL settings + stage agent label templates
├── configurations/
│   ├── jdk8u_pipeline_config.json          # Per-version platform build matrix
│   ├── jdk11u_pipeline_config.json
│   ├── jdk17u_pipeline_config.json
│   ├── jdk21u_pipeline_config.json
│   └── ...
└── vendor-scripts/                              # Optional: overrides for default stage scripts
    ├── 02-build.sh                              # Replaces scripts/stages/02-build.sh
    ├── 10-digital-artifact-sign.sh             # Replaces scripts/stages/10-digital-artifact-sign.sh
    └── ...
```

**Key separation**: pipeline *code* (ci-adoptium-pipelines) is vendor-agnostic. Vendor-specific configuration *and* any vendor-specific stage overrides live in the config repo, cloned at runtime.

## Shared Utilities (`scripts/lib/`)

### logging-utils.sh

Consistent logging functions used by all stage scripts:

```bash
log_info()    # [INFO]  timestamped message to stdout
log_error()   # [ERROR] timestamped message to stderr
log_warn()    # [WARN]  timestamped message to stdout
log_section() # section header divider
```

### config-utils.sh

Configuration reading and environment validation:

```bash
validate_standard_environment()  # validates WORKSPACE, CONFIG_FILE, TARGET_DIR
require_env()                     # fails if env var not set
require_file()                    # fails if file doesn't exist
require_dir()                     # fails if directory doesn't exist
load_config()                     # reads pipeline-config.json as string
get_config_value()                # extracts value with jq
get_config_bool()                 # extracts boolean with jq
prepare_output_dir()              # mkdir -p TARGET_DIR
```

### artifact-utils.sh

Artifact management helpers:

```bash
create_stage_metadata()  # writes stage-metadata.json to TARGET_DIR
copy_artifacts()         # copies files between directories
verify_artifact()        # asserts an artifact exists
list_artifacts()         # lists all artifacts in a directory
create_checksums()       # generates SHA256 checksums
verify_checksums()       # verifies checksums
```

## Benefits of This Architecture

### 1. CI Portability
Shell scripts run on any CI system. Only the orchestration layer (Layer 1) needs to change when moving to a new CI platform. Stage scripts (Layer 2) remain unchanged.

### 2. Local Testing
Any stage script can be run directly on a developer machine by setting the required environment variables. No Jenkins required.

### 3. Vendor Customisation Without Forking
Vendors place override scripts in `vendor-scripts/` in their config repo. `StageScriptRunner` picks these up automatically. The pipeline code repository needs no modification.

### 4. Maintainability
Clear separation of concerns. Shell scripts are simpler than Groovy. Standard Unix tools (`jq`, `bash`). Each stage script is focused on a single task.

### 5. Consistency
The same script runs in Jenkins, locally, and in any future CI system. CI-specific bugs are minimised.

## Summary

| Layer | What | Where | CI-Specific? |
|---|---|---|---|
| 1 | Orchestration | `ci/jenkins/`, `ci/local/` | Yes — per platform |
| 2 | Stage logic | `scripts/stages/`, `config-repo/vendor-scripts/` | No — portable bash |
| 3 | Build tools | `make-adopt-build-farm.sh`, signing tools, etc. | No — already portable |

The architecture ensures OpenJDK builds can be driven from any CI system (or locally) without changing the stage scripts that contain the actual build logic.
