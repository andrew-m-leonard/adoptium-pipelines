# Refactoring Plan: CI-Agnostic Stage Input/Output Contract & Artifact Handling

## Overview
Refactor artifact input/output contracts across the CI layer (`ci/jenkins`, `ci/local`), default stage scripts (`scripts/stages`), and vendor scripts (`ci-temurin-config/vendor-scripts`) to establish a clean, consistent, and CI-agnostic artifact management architecture.

---

## The Contract Definition

### 1. Environment Variables (CI-Agnostic)
- **`INPUT_ARTIFACTS_DIR`**: Root directory for stage input artifacts within the stage workspace (e.g. `$WORKSPACE` in Jenkins / `$stage_workspace` in local runner).
- **`BUILD_ARTIFACTS_PATH`**: Relative sub-folder path containing build/stage outputs (e.g., `'build_output'`).
  - On disk during stage execution, build input artifacts are restored to `${INPUT_ARTIFACTS_DIR}/${BUILD_ARTIFACTS_PATH}/...`.
  - Stage scripts that trigger downstream jobs pass `env.BUILD_ARTIFACTS_PATH` (e.g. `UPSTREAM_DIR = env.BUILD_ARTIFACTS_PATH`) so downstream signers/validators know the upstream relative directory.
- **`TARGET_DIR`**: Unique stage-specific output directory (e.g. `$WORKSPACE/<stage_stem>-output`).
  - Stage outputs destined for the build artifact store are written into `${TARGET_DIR}/${BUILD_ARTIFACTS_PATH}/...` (or archived into `BUILD_ARTIFACTS_PATH` by the CI layer).
- **`CONFIG_FILE`**: Path to `pipeline-config.json` (always placed at `$WORKSPACE/pipeline-config.json`).

### 2. Stage Parameters Schema (`*.params.json`)
Artifact definitions in `*.params.json` are **relative to `BUILD_ARTIFACTS_PATH`**:
- **`buildInputArtifacts`** (list of glob strings, e.g. `["*sbom*.json"]`, `["*.tar.gz", "*.zip"]`, `["**/*"]`):
  - Patterns are defined relative to `BUILD_ARTIFACTS_PATH`.
  - The CI layer automatically prepends `${BUILD_ARTIFACTS_PATH}/` to each pattern when retrieving artifacts (and always implicitly includes `pipeline-config.json` at the root).
- **`buildOutputArtifacts`** (list of glob strings, e.g. `["**/*"]`):
  - Defines which output files from `${TARGET_DIR}/${BUILD_ARTIFACTS_PATH}` (or `${TARGET_DIR}`) are archived under `BUILD_ARTIFACTS_PATH` in the CI artifact store.

---

## Sub-Tasks

### Sub-Task 1: Update Stage Parameter Definitions (`*.params.json`) & Collation Script
- **Intent**: Add `buildInputArtifacts` and `buildOutputArtifacts` to all stage param definitions and ensure `collect-stage-params.py` aggregates them.
- **Expected Outcomes**:
  - `scripts/stages/*.params.json` updated with clean relative globs (e.g. `["*sbom*.json"]`, `["*.tar.gz", "*.zip"]`).
  - `ci-temurin-config/vendor-scripts/*.params.json` updated with corresponding relative globs.
  - `scripts/lib/collect-stage-params.py` collates `buildInputArtifacts` and `buildOutputArtifacts` per stage into `collated-stage-params.json`.
- **Status**: `[x] completed`

### Sub-Task 2: Refactor CI Execution Layer (`ci/jenkins` and `ci/local`)
- **Intent**: Centralize artifact restoration and archiving into `PipelineHelper` / `StageScriptRunner` (Jenkins) and `StageExecutor` / `WorkspaceManager` (Local runner).
- **Expected Outcomes**:
  - `BUILD_ARTIFACTS_PATH` standard env variable set to `'build_output'` in both CI layers.
  - `PipelineHelper.initializeStage(stageId, prerequisites)` reads `buildInputArtifacts` for `stageId` from `collated-stage-params.json`, prefixes each with `${BUILD_ARTIFACTS_PATH}/`, combines with `pipeline-config.json`, and executes `copyArtifacts`.
  - `Jenkinsfile.declarative` has all hardcoded artifact filter lists removed.
  - `StageScriptRunner.run()` exports `INPUT_ARTIFACTS_DIR`, `BUILD_ARTIFACTS_PATH`, `TARGET_DIR`, `CONFIG_FILE`, and archives `TARGET_DIR` outputs into `BUILD_ARTIFACTS_PATH` upon completion.
  - `ci/local` (`stage_executor.py`, `workspace_manager.py`, `run-pipeline.py`) implements matching logic using the collated `buildInputArtifacts` and `buildOutputArtifacts`.
- **Status**: `[x] completed`

### Sub-Task 3: Refactor Vendor Scripts (`ci-temurin-config/vendor-scripts`)
- **Intent**: Remove inline `archiveArtifacts` and ensure downstream jobs receive `env.BUILD_ARTIFACTS_PATH`.
- **Expected Outcomes**:
  - Remove direct `archiveArtifacts` calls in `09-sbom-sign.groovy` and `10-digital-artifact-sign.groovy`.
  - Downstream trigger calls pass `string(name: 'UPSTREAM_DIR', value: env.BUILD_ARTIFACTS_PATH)`.
  - `copyArtifacts` in vendor scripts places returned artifacts into `${env.TARGET_DIR}/${env.BUILD_ARTIFACTS_PATH}`.
- **Status**: `[x] completed`

### Sub-Task 4: Refactor Core Default Scripts (`scripts/stages`) & Documentation
- **Intent**: Ensure default core scripts search and write artifacts consistently via `INPUT_ARTIFACTS_DIR`, `BUILD_ARTIFACTS_PATH`, and `TARGET_DIR`.
- **Expected Outcomes**:
  - `02-build.sh`, `14-aqa-tests.groovy`, `13-smoke-tests.sh`, etc. operate with `BUILD_ARTIFACTS_PATH`.
  - Update `docs/` (`UNIVERSAL_STAGE_PATTERN.md`, `STAGE_DEFINITION_REFERENCE.md`, `WORKSPACE_ARTIFACTS_ARCHITECTURE.md`, `CI_AGNOSTIC_ARCHITECTURE.md`).
- **Status**: `[x] completed`

### Sub-Task 5: Validation and Testing
- **Intent**: Run unit test suites and verify param collation / local pipeline runs.
- **Expected Outcomes**:
  - All unit tests in `tests/` pass with updated params schema.
  - Verification with local test executions.
- **Status**: `[x] completed`
