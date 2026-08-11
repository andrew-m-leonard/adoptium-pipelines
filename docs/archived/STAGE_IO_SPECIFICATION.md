# Stage Input/Output Specification

Each pipeline stage is an independently restartable unit that communicates through environment variables, the file system, and exit codes.

## Common Environment Variables

All stage scripts receive these variables (set by `PipelineHelper.initializeStage()` in Jenkins, or by `run-pipeline.py` locally):

| Variable | Description | Example |
|---|---|---|
| `WORKSPACE` | Stage working directory | `/home/jenkins/workspace/...` |
| `CONFIG_FILE` | Path to `pipeline-config.json` | `${INPUT_ARTIFACTS_DIR}/pipeline-config.json` |
| `BUILD_NUMBER` | Build identifier | `42` or `local` |
| `INPUT_ARTIFACTS_DIR` | Directory where input artifacts from previous stages are placed | `${WORKSPACE}/stage_input_artifacts` |
| `TARGET_DIR` | Directory where this stage writes its output artifacts | `${WORKSPACE}/build_output` |

## Artifact Flow Model

In Jenkins, `initializeStage()` calls `copyArtifacts` to pull artifacts from the current build's archive into `INPUT_ARTIFACTS_DIR` before the stage script runs. The stage script writes outputs to `TARGET_DIR`, which is then archived with `archiveArtifacts`.

```
archiveArtifacts (Initialize stage)
    ↓
copyArtifacts → INPUT_ARTIFACTS_DIR  ← stage reads from here
                                         stage logic
                TARGET_DIR           ← stage writes here
    ↓
archiveArtifacts
```

## Stage Specifications

### Initialize

**Orchestrated by**: `ConfigHelper.generatePipelineConfig()` (calls `scripts/lib/load-json-config.py`)

**Inputs**: Job parameters + `config-repo/configurations/jdk${N}_pipeline_config.json` + `config-repo/adoptium_pipeline_config.json`

**Outputs archived**:
- `pipeline-config.json` — generated pipeline configuration

---

### Build — `scripts/stages/02-build.sh`

**Prerequisites**: Initialize

**Inputs**:
- `${CONFIG_FILE}` — pipeline configuration
- Boot JDK, build toolchain

**Env vars**:
| Variable | Description |
|---|---|
| `TARGET_DIR` | `${WORKSPACE}/build_output` |

**Outputs archived** (from `TARGET_DIR/**/*`):
- `workspace/target/*.tar.gz` — JDK tarballs
- `workspace/target/*.zip` — JDK zips (Windows)
- `workspace/target/metadata/` — build metadata, SBOMs

---

### Internal Sign — `scripts/stages/03-internal-sign.sh`

**When**: macOS or Windows, JDK ≥ 11, signing enabled

**Prerequisites**: Build

**Inputs** (`pipeline-config.json,workspace/target/jmods/**/*`):
- `pipeline-config.json`
- `workspace/target/jmods/**/*` — unsigned JMODs

**Outputs**: signed JMODs (archived from `TARGET_DIR`)

---

### Assemble — `scripts/stages/04-assemble.sh`

**When**: macOS or Windows, JDK ≥ 11, signing enabled

**Prerequisites**: Build

**Inputs** (`pipeline-config.json,signed-jmods/**/*`):
- Signed JMODs from Internal Sign stage

**Outputs**: assembled JDK image (archived from `TARGET_DIR`)

---

### Sign Artifacts — `scripts/stages/06-sign.sh`

**When**: signing enabled

**Prerequisites**: Assemble (or Build if no Internal Sign)

**Inputs** (`pipeline-config.json,workspace/target/**/*.tar.gz,...`):
- JDK tarballs and metadata

**Env vars**:
| Variable | Description |
|---|---|
| `INPUT_ARTIFACTS_DIR` | `${WORKSPACE}/stage_input_artifacts` |
| `TARGET_DIR` | `${WORKSPACE}` |

**Outputs**: signed artifacts

---

### Build Installers — `scripts/stages/07-installer.sh`

**When**: installers enabled

**Prerequisites**: Build

**Inputs** (`pipeline-config.json,**/*.tar.gz,**/*.zip,**/metadata/**/*`):
- JDK archives

**Outputs**: platform installers (`.msi`, `.pkg`, `.deb`, `.rpm`)

---

### Sign Installers — `scripts/stages/08-sign-installer.sh`

**When**: installers enabled + signing enabled

**Prerequisites**: Build Installers

**Inputs** (`pipeline-config.json,installers/**/*`):
- Unsigned installer packages

**Outputs**: signed installer packages

---

### GPG Sign — `scripts/stages/09-gpg-sign.sh`

**When**: Temurin variant, signing enabled, non-PR build

**Prerequisites**: Sign Artifacts

**Inputs** (`pipeline-config.json,signed/**/*,signed-installers/**/*`)

**Outputs**: `.sig` / `.asc` GPG signatures

Also invokes `scripts/stages/10-sbom-sign.sh` inline if `--create-sbom` is in build args.

---

### Verify Signing — `scripts/stages/11-verify-signing.sh`

**When**: Temurin variant, signing enabled, non-PR build

**Prerequisites**: GPG Sign

**Inputs** (`pipeline-config.json,signed/**/*,*.sig,*.asc`)

**Outputs**: verification report (stage exits non-zero on failure)

---

### Validate SBOM — `scripts/stages/12-validate-sbom.sh`

**When**: `--create-sbom` in build args

**Prerequisites**: Build

**Inputs** (`pipeline-config.json,*sbom*.json`):
- SBOM JSON files from build

**Env vars**:
| Variable | Description |
|---|---|
| `INPUT_ARTIFACTS_DIR` | `${WORKSPACE}/stage_input_artifacts` |
| `TARGET_DIR` | `${WORKSPACE}/sbom_validation_output` |

**Outputs**: SBOM validation report

---

### Smoke Tests — `scripts/stages/13-smoke-tests.sh`

**When**: tests enabled

**Prerequisites**: Build

**Inputs** (`pipeline-config.json,*.tar.gz,*.zip`):
- JDK archive

**Env vars**:
| Variable | Description |
|---|---|
| `INPUT_ARTIFACTS_DIR` | `${WORKSPACE}/stage_input_artifacts` |
| `TARGET_DIR` | `${WORKSPACE}/smoke_test_output` |

**Outputs**: test result files (build set to UNSTABLE on failure, not failed)

---

### Reproducible Compare Build — `scripts/stages/20-reproducible-compare.sh`

**When**: `REPRODUCIBLE_COMPARE_BUILD=true` + `SCM_REF` non-empty + build passing

**Prerequisites**: Build

**Inputs** (`pipeline-config.json,*.tar.gz,*.zip`):
- Locally built JDK archive

**Env vars**:
| Variable | Description |
|---|---|
| `INPUT_ARTIFACTS_DIR` | `${WORKSPACE}/stage_input_artifacts` |
| `TARGET_DIR` | `${WORKSPACE}/reproducible_compare_output` |
| `SCM_REF` | Source tag used to identify the production binary |
| `RELEASE` | `true` or `false` |

**Outputs** (archived from `TARGET_DIR/**/*`):
- `comparison-report.txt`
- `reprotest.diff`
- `reproducible_evidence.log`
- `ReproduciblePercent`

Build set to UNSTABLE (not failed) on differences.

---

### AQA Tests — `scripts/stages/14-aqa-tests.sh`

**When**: tests enabled + smoke tests passed

**Prerequisites**: Smoke Tests

**Inputs** (`pipeline-config.json,workspace/target/**/*.tar.gz,workspace/target/metadata/**/*`)

**Outputs**: AQA test results

---

### TCK Tests — `scripts/stages/15-tck-tests.sh`

**When**: Temurin variant, TCK enabled, smoke tests passed; excludes jdk8u/s390x/linux

**Prerequisites**: Smoke Tests

**Inputs** (`pipeline-config.json,workspace/target/**/*.tar.gz,workspace/target/metadata/**/*`)

**Outputs**: TCK test results

---

### Publish Artifacts — `scripts/stages/16-publish.sh`

**When**: `PUBLISH_ARTIFACTS=true`

**Prerequisites**: Build

**Inputs** (`pipeline-config.json,**/*.tar.gz,**/*.zip,**/*.msi,**/*.pkg,**/metadata/**/*`)

**Env vars**:
| Variable | Description |
|---|---|
| `TARGET_DIR` | `${WORKSPACE}/publish_output` |

**Outputs**: publication confirmation

---

## Writing a New Stage Script

All stage scripts must:

1. Source shared utilities: `logging-utils.sh`, `config-utils.sh`, `artifact-utils.sh`
2. Call `validate_standard_environment` to verify required variables
3. Read inputs from `${INPUT_ARTIFACTS_DIR}` (or `${CONFIG_FILE}`)
4. Write outputs to `${TARGET_DIR}`
5. Exit 0 on success, non-zero on failure

See [`UNIVERSAL_STAGE_PATTERN.md`](../UNIVERSAL_STAGE_PATTERN.md) for the full template.
