# Shell Scripts Reference

Index of all files under `scripts/` — stage scripts and shared utility libraries. For the stage interface contract (environment variables, archive/restore flow) see [WORKSPACE_ARTIFACTS_ARCHITECTURE.md](./WORKSPACE_ARTIFACTS_ARCHITECTURE.md). For writing a new stage see [UNIVERSAL_STAGE_PATTERN.md](./UNIVERSAL_STAGE_PATTERN.md). For the `.params.json` sidecar files that gate and parameterise each stage see [STAGE_DEFINITION_REFERENCE.md](./STAGE_DEFINITION_REFERENCE.md).

---

## Shared Libraries (`scripts/lib/`)

All stage scripts source these libraries at the top of their file.

### [`scripts/lib/logging-utils.sh`](../scripts/lib/logging-utils.sh)

Timestamped logging to stderr.

| Function | Purpose |
|---|---|
| `log_info msg` | `[INFO]` line to stderr |
| `log_warn msg` | `[WARN]` line to stderr |
| `log_error msg` | `[ERROR]` line to stderr |
| `log_debug msg` | `[DEBUG]` line — only emitted when `DEBUG=true` |
| `log_section msg` | Separator banner to stderr |

### [`scripts/lib/config-utils.sh`](../scripts/lib/config-utils.sh)

Environment validation and JSON config helpers.

| Function | Purpose |
|---|---|
| `require_env VAR` | Exit 1 if `VAR` is unset or empty |
| `require_file PATH` | Exit 1 if file does not exist |
| `require_dir PATH` | Exit 1 if directory does not exist |
| `load_config FILE` | `cat` the JSON file (requires `jq`) |
| `get_config_value FILE JQ_PATH [DEFAULT]` | Extract string value via `jq`; exit 1 if absent and no default |
| `get_config_bool FILE JQ_PATH [DEFAULT]` | Extract boolean value; returns `true`/`false` string |
| `validate_standard_environment` | Checks `WORKSPACE` and `CONFIG_FILE` are set and file exists; sets `TARGET_DIR` default to `${WORKSPACE}/target` if not already provided |

### [`scripts/lib/artifact-utils.sh`](../scripts/lib/artifact-utils.sh)

Artifact directory and file helpers.

| Function | Purpose |
|---|---|
| `create_stage_metadata STAGE STATUS` | Writes `${WORKSPACE}/stage-metadata.json` |
| `copy_artifacts SRC DEST` | `cp -r SRC/* DEST/` with existence checks |
| `verify_artifact PATH` | Exit-safe check that a file exists; logs size |
| `list_artifacts DIR` | `find DIR -type f` with `ls -lh` |
| `create_checksums DIR` | SHA256 checksums for all files in `DIR` → `DIR/checksums.txt` |
| `verify_checksums DIR` | Verify `DIR/checksums.txt` against contents |
| `prepare_output_dir [DIR]` | `mkdir -p DIR`; optionally cleans if `CLEAN_OUTPUT=true` |
| `determine_filename` | Derives the Adoptium artifact filename from config vars; exports `$FILENAME` |

### [`scripts/lib/workspace-cleanup.sh`](../scripts/lib/workspace-cleanup.sh)

**Standalone executable script** (not a function library). Cleans the ephemeral stage workspace. Called by the orchestrator before and after each stage.

Required env vars: `CONFIG_FILE`, `WORKSPACE`, `CLEANUP_TYPE` (`"pre"` or `"post"`)

- **Pre-cleanup** (`CLEANUP_TYPE=pre`): always removes `${WORKSPACE}/workspace/` — required for restartability.
- **Post-cleanup** (`CLEANUP_TYPE=post`): removes only if `parameters.cleanWorkspaceAfterStage=true` in `pipeline-config.json`.

### [`scripts/lib/build-metadata-writer.py`](../scripts/lib/build-metadata-writer.py)

CLI script. Writes `build-metadata.json` from explicit arguments and a small set of `CONFIG_*` environment variables. Called by `02-build.sh` after a successful build.

| Argument | Required | Description |
|---|---|---|
| `--output` | ✅ | Destination path for `build-metadata.json` |
| `--version` | ✅ | JDK version string (e.g. `jdk-21.0.12+7`) |
| `--build-number` | ✅ | Build number |
| `--stage` | ✅ | Stage name (e.g. `build`) |
| `--workspace` | ✅ | Absolute path to the build workspace |
| `--build-uid` | ☑️ | `BUILD_UID` value (optional) |
| `--group-uid` | ☑️ | `GROUP_UID` value (optional) |

Reads from env: `CONFIG_JAVA_TO_BUILD`, `CONFIG_TARGET_OS`, `CONFIG_ARCHITECTURE`, `CONFIG_VARIANT`.

### [`scripts/lib/sbom-workspace-extractor.py`](../scripts/lib/sbom-workspace-extractor.py)

CLI script. Reads an Adoptium SBOM JSON file and prints the `"Build Workspace Directory"` property value to stdout. Used by `02-build.sh` to derive the workspace path length needed for reproducible build path padding.

```bash
value=$(python3 sbom-workspace-extractor.py --sbom /path/to/sbom.json)
```

Exits 0 (prints empty line) when the property is absent; exits non-zero only on unreadable file or invalid JSON.

### [`scripts/lib/python-runner.sh`](../scripts/lib/python-runner.sh)

Thin shim. Resolves the Python interpreter (`python3` → `python` fallback) and execs the given script with all arguments forwarded. Exits 127 if no Python is found. Used as the single canonical entry point for all shell-context Python invocations.

```bash
python-runner.sh <script.py> [args...]
```

### [`scripts/lib/collect-stage-params.py`](../scripts/lib/collect-stage-params.py)

CLI script. Collates all `scripts/stages/*.params.json` sidecar files (plus optional vendor overrides) into a single structured JSON document consumed by Jenkins Job DSL (at job-creation time) and the local runner (at runtime).

Key behaviour:
- Merges default + vendor params per stage stem; vendor params override defaults with the same name
- Deduplicates params shared across stages (e.g. `RUN_TESTS` defined in multiple `*.params.json` files)
- Validates `stageCondition` cross-references — every referenced param name must exist in the final set
- Applies priority group ordering (`"Stage Selections"` always appears first)
- Supports `--orchestrated-stages` to restrict output to only the stages a given orchestrator runs

```bash
python3 scripts/lib/collect-stage-params.py \
    --default-stages-dir scripts/stages \
    --vendor-scripts-dir config-repo/vendor-scripts \
    --output /tmp/collated-stage-params.json
```

### [`scripts/lib/load-adoptium-pipeline-config-json.py`](../scripts/lib/load-adoptium-pipeline-config-json.py)

CLI script. Loads `adoptium_pipeline_config.json` from a local directory or remote GitHub URL and outputs the content in three formats: `json` (default), `env` (shell `export` statements), or `summary` (human-readable).

```bash
# Print as env exports
python3 load-adoptium-pipeline-config-json.py --config-repo-dir ./ci-temurin-config --format env

# Fetch from remote and print a specific field
python3 load-adoptium-pipeline-config-json.py \
    --config-repo-url https://github.com/adoptium/ci-temurin-config.git \
    --field activeJdkVersions
```

---

## Stage Scripts (`scripts/stages/`)

Stages are invoked by the pipeline runner via [`StageScriptRunner.groovy`](../ci/jenkins/lib/StageScriptRunner.groovy) (Jenkins) or [`ci/local/stage_resolver.py`](../ci/local/stage_resolver.py) (local). Both resolve vendor overrides from `config-repo/vendor-scripts/` first, then fall back to defaults here.

**Key:** `REAL` = has a full working implementation. `STUB` = logs a skip message and exits 0; must be overridden via `config-repo/vendor-scripts/` for real behaviour.

### Standard environment variables received by every stage

| Variable | Value |
|---|---|
| `WORKSPACE` | Ephemeral stage scratch directory (cleaned before/after stage) |
| `CONFIG_FILE` | Path to `pipeline-config.json` inside `WORKSPACE` |
| `INPUT_ARTIFACTS_DIR` | Directory containing artifacts from previous stages |
| `TARGET_DIR` | Directory where this stage writes its output files |
| `BUILD_NUMBER` | Build number string |

---

### `02-build.sh` — Build JDK `REAL`

Clones `temurin-build`, invokes `build-farm/make-adopt-build-farm.sh`, copies outputs to `TARGET_DIR`.

**Inputs:** `CONFIG_FILE` (for all build parameters)
**Outputs:** `${TARGET_DIR}/*.tar.gz` or `*.zip`, `*.json` (SBOM if `CREATE_SBOM=true`), `build-metadata.json`, `checksums.txt`
**Extra env:** none required beyond standard set

Key functions: `setup_build_environment`, `setup_temurin_build`, `setup_reproducible_build_padding` (fetches upstream SBOM to derive workspace path length for reproducible builds), `prepare_workspace`, `execute_build`, `extract_build_metadata`, `organize_build_outputs`

---

### `03-internal-code-sign.sh` — Internal Code Sign `STUB`

Code signs EXEs/DLLs and dylibs inside JDK 11+ JMODs, before image assembly. Must run on a dedicated signing node. Windows & Mac only; not applicable to jdk8.

**Inputs:** `INPUT_ARTIFACTS_DIR` containing `jmods/` from Build
**Outputs:** `TARGET_DIR` containing signed jmods

---

### `04-assemble-images.sh` — Assemble Images `STUB`

Runs the final OpenJDK `make images` processing to assemble signed JMODs into a complete JDK image. Must run after `03-internal-code-sign`. Windows & Mac only; not applicable to jdk8.

**Inputs:** `INPUT_ARTIFACTS_DIR` containing signed jmods
**Outputs:** `TARGET_DIR` containing assembled JDK tarballs

---

### `06-post-build-code-sign.sh` — Post-Build Code Sign `STUB`

Code signs EXEs/DLLs and dylibs that were not signed in `03-internal-code-sign`. Covers all binaries for jdk8 (which has no internal signing stage), and the limited set of jdk11+ binaries outside of JMODs. Windows & Mac only.

**Inputs:** `INPUT_ARTIFACTS_DIR` containing the assembled JDK image
**Outputs:** `TARGET_DIR` containing code-signed output

---

### `07-installer.sh` — Build Installers `STUB`

Creates platform-specific installers (`.msi`, `.pkg`, `.deb`, `.rpm`). Vendor-specific.

**Inputs:** `INPUT_ARTIFACTS_DIR` containing signed JDK tarballs
**Outputs:** `TARGET_DIR` containing installer packages

---

### `08-code-sign-installer.sh` — Code Sign Installer `STUB`

Code signs installer packages (`.msi` on Windows, `.pkg` on macOS). On macOS also submits to Apple for Notarization and staples the ticket. Windows & Mac only.

**Inputs:** `INPUT_ARTIFACTS_DIR` containing installers from Build Installer stage
**Outputs:** `TARGET_DIR` containing signed installers

---

### `09-sbom-sign.sh` — SBOM Sign `STUB`

JSF-signs the SBOM by embedding a JSON signature directly inside the SBOM document. Must run before `10-digital-artifact-sign` so the signed SBOM is included in GPG armoring. Only runs when the `CREATE_SBOM` stage parameter is true.

**Inputs:** `INPUT_ARTIFACTS_DIR` containing SBOM JSON files
**Outputs:** `TARGET_DIR` containing JSF-signed SBOM files

---

### `10-digital-artifact-sign.sh` — Digital Artifact Sign `STUB`

Applies detached GPG signatures (`.sig` / `.asc`) to all build artifacts for public distribution verification. Covers code-signed JDK archives, installer packages, and JSF-signed SBOMs. Runs after `09-sbom-sign` so the signed SBOM is included in GPG armoring.

**Inputs:** `INPUT_ARTIFACTS_DIR` containing signed artifacts and signed SBOMs
**Outputs:** `TARGET_DIR` containing `.sig`/`.asc` signature files

---

### `11-verify-signing.sh` — Verify Signing `STUB`

Verifies that all necessary signing has been completed: Windows/macOS executables are code-signed, installer packages are code-signed (and notarized on macOS), and detached GPG signatures are present for every distribution artifact.

**Inputs:** `INPUT_ARTIFACTS_DIR` containing signed artifacts + `.sig`/`.asc` files
**Outputs:** `TARGET_DIR` containing verification report

---

### `12-validate-sbom.sh` — Validate SBOM `STUB`

Validates SBOM files produced during Build. Vendor-specific (tooling and acceptance criteria vary). Only runs when the `CREATE_SBOM` stage parameter is true.

The Temurin implementation clones `temurin-build` and invokes `tooling/validateSBOM.sh`. It lives in `ci-temurin-config/vendor-scripts/12-validate-sbom.sh`.

**Inputs:** `INPUT_ARTIFACTS_DIR` containing `*sbom*.json`
**Outputs:** `TARGET_DIR` containing validation results

---

### `13-smoke-tests.sh` — Smoke Tests `REAL`

Extracts the built JDK into `WORKSPACE/jdk-test/` and runs four quick checks.

**Inputs:** `INPUT_ARTIFACTS_DIR` containing `*jdk_*.tar.gz` or `*jdk_*.zip`
**Outputs:** `${TARGET_DIR}/java-version.txt`, `hello-compile.txt`, `hello-run.txt`, `system-properties.txt`, `class-loading.txt`, `test-metadata.json`

Tests performed:
1. `java -version` executes successfully
2. HelloWorld.java compiles and runs (`javac` + `java`)
3. `-XshowSettings:properties` returns `java.version`, `java.home`, `os.name`
4. `-cp lib -version` verifies class loading

Key functions: `find_jdk_artifact`, `extract_jdk`, `run_smoke_tests`, `test_java_version`, `test_hello_world`, `test_system_properties`, `test_class_loading`, `create_test_metadata`

---

### `14-aqa-tests.sh` — AQA Tests `STUB`

Runs the full AQA test suite. Vendor-specific (AQA infrastructure required).

**Inputs:** `INPUT_ARTIFACTS_DIR` containing JDK tarballs + metadata
**Outputs:** `TARGET_DIR` containing AQA test reports

---

### `15-tck-tests.sh` — TCK Tests `STUB`

Runs the TCK (Technology Compatibility Kit). Vendor-specific. Skipped for `jdk8u/s390x/linux`.

**Inputs:** `INPUT_ARTIFACTS_DIR` containing JDK tarballs + metadata
**Outputs:** `TARGET_DIR` containing TCK results

---

### `16-publish.sh` — Publish Artifacts `STUB`

Publishes artifacts to a release repository. Vendor-specific.

**Inputs:** `INPUT_ARTIFACTS_DIR` containing all final artifacts
**Outputs:** `TARGET_DIR` containing publish receipts/logs

---

### `20-reproducible-compare.sh` — Reproducible Build Comparison `STUB`

Compares a locally built JDK against the vendor's published production binary to verify bit-for-bit reproducibility. The comparison tooling and binary source are vendor-specific.

The Temurin implementation downloads from `api.adoptium.net` and uses `temurin-build/tooling/reproducible/repro_compare.sh`. It lives in `ci-temurin-config/vendor-scripts/20-reproducible-compare.sh`.

**Inputs:** `INPUT_ARTIFACTS_DIR` containing built JDK tarballs
**Outputs:** `${TARGET_DIR}/comparison-report.txt`, `reprotest.diff`, `ReproduciblePercent`
**Extra env:** `SCM_REF` (required), `RELEASE` (`true`/`false`), `BUILD_REPO_URL` (optional), `BUILD_REF` (optional)

Exit codes: `0` = 100% reproducible, non-zero = differences found (pipeline fails the build)

---

## Vendor Override Pattern

Any `STUB` stage (and any `REAL` stage) can be overridden by placing a replacement script in the config repo:

```
config-repo/
└── vendor-scripts/
    ├── 06-post-build-code-sign.sh    ← overrides scripts/stages/06-post-build-code-sign.sh
    ├── 07-installer.sh               ← overrides scripts/stages/07-installer.sh
    └── ...
```

Resolution order (first match wins):
1. `config-repo/vendor-scripts/<stem>.sh`
2. `config-repo/vendor-scripts/<stem>.py`
3. `scripts/stages/<stem>.sh`
4. `scripts/stages/<stem>.py`
5. built-in no-op (logs skip, returns 0)

See [`ci/jenkins/lib/StageScriptRunner.groovy`](../ci/jenkins/lib/StageScriptRunner.groovy) (Jenkins) and [`ci/local/stage_resolver.py`](../ci/local/stage_resolver.py) (local) for the implementation.
