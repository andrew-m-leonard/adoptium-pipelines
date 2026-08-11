# Reproducible Build Comparison Integration

## Overview

This document describes the reproducible build comparison capability in the CI Adoptium Pipelines. The system validates build reproducibility by comparing locally built JDKs against production binaries.

**Key Principle**: The comparison logic is **CI-agnostic** — the stage contract (`scripts/stages/20-reproducible-compare.sh`) defines the interface; the vendor-specific implementation (comparison tooling, binary source, acceptance criteria) lives in the config repo.

**Temurin implementation**: `ci-temurin-config/vendor-scripts/20-reproducible-compare.sh` — downloads from `api.adoptium.net` and delegates to `temurin-build/tooling/reproducible/repro_compare.sh`.

---

## CI-Agnostic Architecture

### Core Component: Stage Script

**Default stub**: [`scripts/stages/20-reproducible-compare.sh`](../scripts/stages/20-reproducible-compare.sh) — no-op, exits 0.

**Temurin vendor override**: `ci-temurin-config/vendor-scripts/20-reproducible-compare.sh` — provides the full implementation. The vendor script is resolved at runtime via [`StageScriptRunner`](../ci/jenkins/lib/StageScriptRunner.groovy) (Jenkins) or [`stage_resolver.py`](../ci/local/stage_resolver.py) (local).

### Stage Gate

The stage is controlled by parameters defined in [`scripts/stages/20-reproducible-compare.params.json`](../scripts/stages/20-reproducible-compare.params.json):

| Parameter | Type | Default | Description |
|---|---|---|---|
| `RUN_REPRODUCIBLE_COMPARE` | boolean | `false` | Enable the reproducible compare stage |
| `SCM_REF` | string (from `02-build.params.json`) | `""` | OpenJDK source tag/ref — must be non-empty for the stage to run |

Both conditions must be satisfied for the stage to execute:
- `RUN_REPRODUCIBLE_COMPARE=true`
- `SCM_REF` matches `regex:.+` (non-empty)

### How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│  1. Clone temurin-build repository                               │
│     └─ Contains repro_compare.sh tool                           │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  2. Download production binary from Adoptium API                 │
│     └─ Uses SCM_REF to identify the exact version               │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  3. Unpack both binaries                                         │
│     ├─ Production binary (from Adoptium API)                    │
│     └─ Locally built binary (from INPUT_ARTIFACTS_DIR)          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  4. Run repro_compare.sh                                         │
│     └─ Byte-by-byte comparison after preprocessing              │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  5. Copy results to TARGET_DIR                                   │
│     ├─ comparison-report.txt                                    │
│     ├─ reprotest.diff (if differences found)                    │
│     └─ ReproduciblePercent                                      │
└─────────────────────────────────────────────────────────────────┘
```

### Required Environment Variables

| Variable | Description | Example |
|---|---|---|
| `WORKSPACE` | Stage workspace directory | `stage_workspace/` |
| `CONFIG_FILE` | Path to `pipeline-config.json` | `stage_workspace/pipeline-config.json` |
| `INPUT_ARTIFACTS_DIR` | Directory containing built JDK artifacts from the Build stage | `stage_workspace/` |
| `TARGET_DIR` | Directory where this stage writes comparison result files | `stage_workspace/target/` |
| `SCM_REF` | Git tag/ref for the build | `jdk-21.0.2+13` |
| `RELEASE` | `true` for release builds, `false` for EA/nightly | `true` |

### Optional Environment Variables

| Variable | Description | Default |
|---|---|---|
| `BUILD_REPO_URL` | temurin-build repository URL | `https://github.com/adoptium/temurin-build.git` |
| `BUILD_REF` | temurin-build branch/tag | `master` |

### Output Files

The script uses `${WORKSPACE}/reproducible-compare/` as a scratch area during execution. At the end, it copies result files to `${TARGET_DIR}/` so they are available for archiving by the orchestration layer:

| File | Location | Description |
|---|---|---|
| `comparison-report.txt` | `${TARGET_DIR}/` | Complete `repro_compare.sh` output |
| `ReproduciblePercent` | `${TARGET_DIR}/` | Reproducibility percentage (0–100) |
| `reprotest.diff` | `${TARGET_DIR}/` | List of differing files (only present when differences found) |
| `reproducible_evidence.log` | `${WORKSPACE}/reproducible-compare/` only | Detailed comparison log (written by `repro_compare.sh` but **not** copied to `TARGET_DIR`) |

### Exit Codes

- **0**: Build is 100% reproducible
- **Non-zero**: Differences detected — pipeline fails the build (`error()` is called)

---

## CI-Specific Implementations

### Jenkins Pipeline

**File**: [`ci/jenkins/Jenkinsfile.declarative`](../ci/jenkins/Jenkinsfile.declarative)

#### Enablement

The stage runs when `stageConditionMet('20-reproducible-compare')` returns true, which evaluates the conditions from `20-reproducible-compare.params.json` against the current Jenkins build parameters:

- `RUN_REPRODUCIBLE_COMPARE == true`
- `SCM_REF` is non-empty

Both must be satisfied; if either is missing the `when {}` block skips the stage entirely.

#### Stage behaviour

1. `initializeStage()` — `cleanWs()`, checkout, `copyArtifacts` (filter: `pipeline-config.json,*.tar.gz,*.zip`)
2. `env.TARGET_DIR = "${WORKSPACE}/reproducible_compare_output"`
3. `env.SCM_REF = params.SCM_REF`
4. `env.RELEASE = (params.RELEASE_TYPE == 'RELEASE') ? 'true' : 'false'`
5. `stageRunner.run('20-reproducible-compare', config)`
6. `archiveArtifacts artifacts: '**/*'` from `reproducible_compare_output/`
7. **Non-zero exit code calls `error()`** — fails the build (does **not** mark UNSTABLE)
8. `finalizeStage()` — optional `cleanWs()`

#### Jenkins archived artifact paths

Jenkins archives the contents of `reproducible_compare_output/` flat:
- `comparison-report.txt`
- `ReproduciblePercent`
- `reprotest.diff` (when differences found)

---

### Local Pipeline Runner

**File**: [`ci/local/run-pipeline.py`](../ci/local/run-pipeline.py)

#### Enabling the stage

The stage is enabled via stage parameters loaded from `scripts/stages/20-reproducible-compare.params.json`. Pass them after all fixed arguments:

```bash
python3 ci/local/run-pipeline.py \
    --jdk-version jdk21 \
    --target-os mac \
    --architecture aarch64 \
    --config-repo-url https://github.com/adoptium/ci-temurin-config.git \
    --release-type RELEASE \
    --scm-ref jdk-21.0.2+13 \
    --run-reproducible-compare true
```

`--scm-ref` is defined in `scripts/stages/02-build.params.json` and is also the `SCM_REF` condition checked by the stage gate.

#### Restart from this stage

```bash
python3 ci/local/run-pipeline.py \
    --jdk-version jdk21 \
    --target-os mac \
    --architecture aarch64 \
    --config-repo-url https://github.com/adoptium/ci-temurin-config.git \
    --start-from-stage 20-reproducible-compare \
    --scm-ref jdk-21.0.2+13 \
    --run-reproducible-compare true
```

#### Stage execution

The stage is orchestrated generically by `PipelineRunner.run()` — there is no dedicated method. The flow is:

1. `_stage_condition_met('20-reproducible-compare')` — checks `RUN_REPRODUCIBLE_COMPARE=true` and `SCM_REF` non-empty; skips silently if either fails
2. `_run_stage('20-reproducible-compare', 'pipeline-config.json,*.tar.gz,*.zip', extra_env={TARGET_DIR=..., RELEASE=...})`
   - `cleanup_stage_workspace('pre')` — wipes `stage_workspace/`
   - `restore_stage_inputs(...)` — copies `pipeline-config.json`, tarballs from `build_artifacts/`
   - Builds env: `WORKSPACE`, `CONFIG_FILE`, `INPUT_ARTIFACTS_DIR`, `TARGET_DIR`, `RELEASE`, `SCM_REF` (injected via `_stage_param_values`)
   - `StageResolver.run('20-reproducible-compare', env)`
   - `archive_stage_outputs(...)` — copies `stage_workspace/target/**` → `build_artifacts/`
   - `cleanup_stage_workspace('post')`

---

## Tool Capabilities

The underlying `repro_compare.sh` tool provides:

1. **File Structure Comparison**: Verifies same files exist in both builds
2. **File Count Validation**: Ensures no missing or extra files
3. **Binary Comparison**: Byte-by-byte comparison after preprocessing
4. **Platform-Specific Preprocessing**:
   - Removes build timestamps
   - Removes build IDs and UUIDs
   - Removes absolute paths in debug info
   - Normalises platform-specific metadata
5. **Detailed Reporting**:
   - `reprotest.diff` — lists differing files
   - `reproducible_evidence.log` — detailed comparison log (in scratch workspace, not archived)
   - `ReproduciblePercent` — percentage match metric (0–100)
   - Exit code 0 = identical, non-zero = differences

---

## Success Criteria

For a build to be considered reproducible:

- ✅ **Exit code 0** (no differences detected by `repro_compare.sh`)
- ✅ **100% ReproduciblePercent**
- ✅ **Empty or absent `reprotest.diff`**

---

## Platform Support

| Platform | `repro_compare.sh` OS identifier | Status |
|---|---|---|
| Linux x64 | `Linux` | Supported |
| Linux aarch64 | `Linux` | Supported |
| Linux ppc64le | `Linux` | Supported |
| Linux s390x | `Linux` | Supported |
| macOS x64 | `Darwin` | Supported |
| macOS aarch64 | `Darwin` | Supported |
| Windows x64 | `CYGWIN` | Supported |
| Windows x86-32 | `CYGWIN` | Supported |
| AIX ppc64 | `AIX` | Mapped but upstream tool support may vary |

---

## References

- **Stage Parameters**: [`scripts/stages/20-reproducible-compare.params.json`](../scripts/stages/20-reproducible-compare.params.json)
- **Stage Script**: [`scripts/stages/20-reproducible-compare.sh`](../scripts/stages/20-reproducible-compare.sh)
- **Comparison Tool**: `temurin-build/tooling/reproducible/repro_compare.sh`
- **Jenkins Implementation**: [`ci/jenkins/Jenkinsfile.declarative`](../ci/jenkins/Jenkinsfile.declarative) (`Reproducible Compare Build` stage)
- **Local Runner**: [`ci/local/run-pipeline.py`](../ci/local/run-pipeline.py)
