# Workspace and Artifacts Architecture

## Overview

The pipeline maintains a clear separation between **ephemeral workspace** (stage working directory, cleaned between stages) and **persistent artifacts** (cross-stage outputs that survive restarts). Both Jenkins and the local runner honour this contract through equivalent archive and restore semantics. The local runner now mirrors Jenkins precisely: each stage starts with a clean workspace, has its inputs explicitly copied in from a durable artifact store, and archives its outputs back to that store before finishing.

Understanding the two systems helps when writing stage scripts that must work identically in both environments.

---

## Common Interface Contract

Every stage script receives the same five environment variables regardless of which CI system is running it. Their **meaning** is consistent; only their **physical paths** differ:

| Variable | Meaning | Jenkins value | Local runner value |
|---|---|---|---|
| `WORKSPACE` | Ephemeral scratch directory for this stage | Jenkins workspace root | `<pipeline_workspace>/stage_workspace/` |
| `CONFIG_FILE` | Path to `pipeline-config.json` | `${WORKSPACE}/pipeline-config.json` | `${WORKSPACE}/pipeline-config.json` |
| `INPUT_ARTIFACTS_DIR` | Directory containing artifacts from previous stages | `${WORKSPACE}` | `${WORKSPACE}` |
| `TARGET_DIR` | Directory where this stage writes its output artifacts | `${WORKSPACE}/<stage>_output/`; defaults to `${WORKSPACE}/target` | `${WORKSPACE}/<stage>_output/`; defaults to `${WORKSPACE}/target` |
| `BUILD_NUMBER` | Build identifier | Jenkins build number | `local-<YYYYMMDD-HHMMSS>` |

`validate_standard_environment()` in [`scripts/lib/config-utils.sh`](../scripts/lib/config-utils.sh) checks `WORKSPACE` and `CONFIG_FILE`, and defaults `TARGET_DIR` to `${WORKSPACE}/target` if not already set by the orchestration layer.

---

## Jenkins Architecture

### Directory Layout (per stage)

Every stage begins with a fresh workspace — `cleanWs()` wipes the entire `WORKSPACE` root. The orchestration layer then re-populates it:

```
${WORKSPACE}/                         # Jenkins workspace root — wiped by cleanWs() at stage start
├── ci/                               # ← checked out from ci-adoptium-pipelines (checkout scm)
│   └── jenkins/lib/
├── scripts/                          # ← checked out from ci-adoptium-pipelines
│   └── stages/, lib/
├── config-repo/                      # ← sparse-checkout: configurations/, vendor-scripts/,
│   ├── configurations/               #   adoptium_pipeline_config.json
│   ├── vendor-scripts/
│   └── adoptium_pipeline_config.json
├── pipeline-config.json              # ← copyArtifacts pulls here (target: '.', i.e. WORKSPACE root)
└── <previous stage outputs>          #   INPUT_ARTIFACTS_DIR == WORKSPACE

# Stage outputs:
${WORKSPACE}/build_output/            # TARGET_DIR — stage writes here
                                      # archiveArtifacts uploads to Jenkins artifact store
```

### How artifacts flow (Jenkins)

```
Initialize stage
  ConfigHelper.generatePipelineConfig()
  → writes pipeline-config.json to WORKSPACE root
  → archiveArtifacts: pipeline-config.json   ← enters Jenkins artifact store

Build stage (and every subsequent stage)
  initializeStage():
    cleanWs()                                ← wipe entire WORKSPACE
    checkout scm                             ← restore scripts/
    sparse-checkout config-repo              ← restore vendor-scripts/ + config files
    copyArtifacts(filter, target: '.')
      ← retrieves pipeline-config.json + selected prior stage outputs into WORKSPACE root

  env.INPUT_ARTIFACTS_DIR = "${WORKSPACE}"
  env.TARGET_DIR = "${WORKSPACE}/build_output"
  stageRunner.run('02-build', config)
    ← stage script reads from INPUT_ARTIFACTS_DIR (= WORKSPACE root)
    ← stage script writes to TARGET_DIR (build_output/)

  archiveArtifacts("${TARGET_DIR}/**/*")    ← uploads build_output/** to artifact store

  finalizeStage()
    ← optional cleanWs()
```

### Jenkins-specific notes

- `WORKSPACE` is cleaned and **fully reconstructed** on every stage allocation (including `checkout scm` + config-repo sparse-checkout). Stages may run on different physical agents.
- `INPUT_ARTIFACTS_DIR` equals `WORKSPACE`. Artifacts copied in by `copyArtifacts` land at the workspace root. Stage scripts must not assume it is the same directory as `TARGET_DIR`.
- `TARGET_DIR` is a **per-stage output sub-directory** of `WORKSPACE`. After archiving, it can be discarded.
- Artifacts **never** touch the local filesystem between stages — they travel exclusively via `archiveArtifacts` → Jenkins artifact store → `copyArtifacts`.

---

## Local Runner Architecture

### Directory Layout

The local runner uses a persistent root (`pipeline_workspace`) containing three purpose-specific sub-directories that map precisely onto Jenkins concepts:

```
<pipeline_workspace>/                 # Root — persists for the life of the pipeline run
│                                     # (default: ~/openjdk-build)
│
├── pipeline-config.json              # Generated by Initialize; immediately archived
│                                     # to build_artifacts/ — not used directly after that
│
├── config-repo/                      # git clone of the config repo (Initialize only)
│   ├── configurations/               # Not re-cloned for subsequent stages
│   ├── vendor-scripts/
│   └── adoptium_pipeline_config.json
│
├── stage_workspace/                  # ≈ Jenkins WORKSPACE
│   │                                 # Wiped BEFORE every stage (pre-cleanup)
│   │                                 # and optionally AFTER (cleanWorkspaceAfterStage)
│   ├── pipeline-config.json          # ← restored from build_artifacts/ before each stage
│   ├── *.tar.gz, *.zip, etc.         # ← restored from build_artifacts/ (stage inputs)
│   └── build_output/                 # ← TARGET_DIR example (Build stage)
│       └── <stage output files>      #   smoke_test_output/, sbom_validation_output/, etc.
│
└── build_artifacts/                  # ≈ Jenkins artifact store
    │                                 # Durable — never auto-cleaned; survives --start-from-stage
    ├── pipeline-config.json          # ← archived by Initialize
    ├── *.tar.gz, *.zip, *.json       # ← archived by Build
    └── <signed/, installers/, etc.>  # ← archived by downstream stages
```

### How artifacts flow (Local)

```
Initialize stage
  workspace_mgr.cleanup_stage_workspace('pre')      ← wipe stage_workspace/
  git clone config-repo → pipeline_workspace/config-repo/
  load-json-config.py → writes pipeline_workspace/pipeline-config.json
  workspace_mgr.archive_file(pipeline-config.json)  ← pipeline-config.json → build_artifacts/
  workspace_mgr.cleanup_stage_workspace('post')     ← optional

Build stage (and every subsequent stage)
  workspace_mgr.cleanup_stage_workspace('pre')      ← wipe stage_workspace/

  workspace_mgr.restore_stage_inputs('Build', filter)
    ← copies matching files: build_artifacts/ → stage_workspace/
    ← pipeline-config.json now at stage_workspace/pipeline-config.json

  env['WORKSPACE']           = stage_workspace/
  env['CONFIG_FILE']         = stage_workspace/pipeline-config.json
  env['INPUT_ARTIFACTS_DIR'] = stage_workspace/
  env['TARGET_DIR']          = stage_workspace/build_output/   # per-stage name, e.g. build_output

  StageResolver.run('02-build', env)
    ← stage script reads from INPUT_ARTIFACTS_DIR (= stage_workspace/)
    ← stage script writes to TARGET_DIR (= stage_workspace/build_output/)

  workspace_mgr.archive_stage_outputs('Build', target_dir=stage_workspace/build_output/)
    ← copies stage_workspace/build_output/** → build_artifacts/

  workspace_mgr.cleanup_stage_workspace('post')     ← optional
```

### Artifact filter patterns (Local vs Jenkins)

Each stage passes a glob pattern telling the restore step which files to copy from `build_artifacts/` into `stage_workspace/`. These mirror the `artifactFilter` arguments in [`Jenkinsfile.declarative`](../ci/jenkins/Jenkinsfile.declarative):

| Stage | Artifact filter |
|---|---|
| Build | `pipeline-config.json` |
| Validate SBOM | `pipeline-config.json,*sbom*.json` |
| Smoke Tests | `pipeline-config.json,*.tar.gz,*.zip` |
| AQA Tests | `pipeline-config.json,*.tar.gz,*.zip` |
| Reproducible Compare | `pipeline-config.json,*.tar.gz,*.zip` |

### Local-runner-specific notes

- `WORKSPACE` points to `stage_workspace/` — the ephemeral scratch area. Stage scripts using `${WORKSPACE}` for temporary files (cloned repos, build scratch) get a clean directory on every run.
- `INPUT_ARTIFACTS_DIR` and `WORKSPACE` **point to the same directory** (`stage_workspace/`). Restored inputs land at the workspace root, matching Jenkins where `copyArtifacts` restores into a sub-directory of `WORKSPACE`.
- `TARGET_DIR` is a stage-specific sub-directory of `stage_workspace/` (e.g. `stage_workspace/build_output/`) — matching Jenkins exactly. Outputs written here are archived to `build_artifacts/` and the directory is cleaned before the next stage.
- `pipeline-config.json` is **restored** into `stage_workspace/` before each stage (like Jenkins' `copyArtifacts`). `CONFIG_FILE` therefore always points to `${WORKSPACE}/pipeline-config.json` in both systems.
- `config-repo/` is cloned once at Initialize and is permanent at the pipeline root. It is not re-cloned for subsequent stages (unlike Jenkins, which sparse-checks out on every stage).
- `build_artifacts/` is never automatically cleaned. To start fresh, use `--clean-workspace` (removes entire `pipeline_workspace/`).

---

## Local Runner: Workspace Validation and CLI Usage

### Workspace validation rules

`WorkspaceManager.validate_and_setup()` enforces these rules before any stage runs:

**Fresh build (no `--start-from-stage`):**

| Workspace exists? | `--clean-workspace`? | Result |
|---|---|---|
| No | Either | ✅ Create workspace structure |
| Yes | No | ❌ ERROR — must use `--clean-workspace` or `--start-from-stage` |
| Yes | Yes | ✅ Remove entire workspace, create fresh structure |

**Restart (`--start-from-stage <stage>`):**

| Workspace exists? | `build_artifacts/` exists? | `--clean-workspace`? | Result |
|---|---|---|---|
| No | — | Either | ❌ ERROR — workspace must exist for restart |
| Yes | No | No | ❌ ERROR — `build_artifacts/` missing (older runner version or corrupted workspace) |
| Yes | Yes | No | ✅ Use existing workspace and artifact store |
| Either | Either | Yes | ❌ ERROR — option conflict; cannot clean when restarting |

### CLI usage examples

```bash
# Fresh build (workspace must not exist, or use --clean-workspace)
python3 run-pipeline.py \
    --jdk-version jdk21 \
    --target-os mac \
    --architecture aarch64 \
    --config-repo-url https://github.com/adoptium/ci-temurin-config.git

# Fresh build cleaning a previous workspace
python3 run-pipeline.py \
    --jdk-version jdk21 \
    --target-os mac \
    --architecture aarch64 \
    --config-repo-url https://github.com/adoptium/ci-temurin-config.git \
    --clean-workspace

# Restart from a specific stage (workspace + build_artifacts/ must exist)
python3 run-pipeline.py \
    --jdk-version jdk21 \
    --target-os mac \
    --architecture aarch64 \
    --config-repo-url https://github.com/adoptium/ci-temurin-config.git \
    --start-from-stage 13-smoke-tests

# ERROR: these two flags are mutually exclusive
python3 run-pipeline.py \
    --start-from-stage 13-smoke-tests \
    --clean-workspace   # ❌ option conflict
```

### Error messages reference

**Workspace already exists (fresh build, no `--clean-workspace`):**
```
ERROR: Workspace already exists: /Users/user/openjdk-build

For a fresh build, you must either:
  1. Use --clean-workspace to clean the existing workspace
  2. Use --start-from-stage <stage> to restart from a specific stage
  3. Manually remove the workspace directory

This ensures workspace cleanliness and prevents pollution from previous runs.
```

**Restart but workspace missing:**
```
ERROR: Cannot restart from stage '13-smoke-tests' - workspace does not exist: /Users/user/openjdk-build

When restarting from a stage, the workspace must exist with artifacts from previous stages.
Run a full build first (without --start-from-stage) to create the workspace.
```

**Restart but `build_artifacts/` missing (older runner version):**
```
ERROR: Cannot restart from stage '13-smoke-tests' - build_artifacts/ does not exist: /Users/user/openjdk-build/build_artifacts

The build_artifacts/ directory is required for stage restarts — it holds outputs
archived by previously completed stages.
Run a full build first (without --start-from-stage) to create the workspace.
```

**Option conflict:**
```
ERROR: Option conflict - cannot use --clean-workspace with --start-from-stage

When restarting from a stage, the workspace must be preserved to access
artifacts from previous stages. Remove --clean-workspace to continue.
```

---

## Side-by-Side Comparison

| Aspect | Jenkins | Local runner |
|---|---|---|
| `WORKSPACE` points to | Jenkins workspace root | `<pipeline_workspace>/stage_workspace/` |
| `CONFIG_FILE` points to | `${WORKSPACE}/pipeline-config.json` | `${WORKSPACE}/pipeline-config.json` |
| `INPUT_ARTIFACTS_DIR` | `${WORKSPACE}` (workspace root) | `${WORKSPACE}` (workspace root) |
| `TARGET_DIR` | `${WORKSPACE}/<stage>_output/` (unique per stage) | `${WORKSPACE}/<stage>_output/` (same names as Jenkins) |
| `INPUT_ARTIFACTS_DIR` == `TARGET_DIR`? | **No** — separate directories | **No** — separate directories |
| Durable artifact store | Jenkins artifact store | `<pipeline_workspace>/build_artifacts/` |
| "Archive" operation | `archiveArtifacts artifacts: "TARGET_DIR/**/*"` | `workspace_mgr.archive_stage_outputs()` |
| "Restore" operation | `copyArtifacts(filter, target: '.')` into `WORKSPACE` root | `workspace_mgr.restore_stage_inputs(filter)` |
| Ephemeral area cleaned | `cleanWs()` wipes entire `WORKSPACE` | `stage_workspace/` wiped by `WorkspaceManager` |
| config-repo checkout | Sparse-checkout on **every stage** | `git clone` **once** at Initialize |
| `scripts/` availability | Re-checked-out via `checkout scm` on every stage | Permanent on disk (runner's own directory) |
| Pre-stage cleanup scope | Entire `WORKSPACE` (checked-out files removed) | Only `stage_workspace/` (`build_artifacts/` and `config-repo/` untouched) |
| Post-stage cleanup | `cleanWs()` in `finalizeStage()` if `CLEAN_WORKSPACE_AFTER_STAGE=true` | `shutil.rmtree(stage_workspace)` if `cleanWorkspaceAfterStage=true` |
| Restart (`--start-from-stage`) | Re-uses existing Jenkins artifact store | Re-uses existing `build_artifacts/` |

---

## Writing Stage Scripts That Work in Both Environments

Because `INPUT_ARTIFACTS_DIR`, `TARGET_DIR`, and `CONFIG_FILE` are always provided via environment variables and have consistent semantics across both systems, stage scripts should:

1. **Never hardcode paths** — always use `${WORKSPACE}`, `${CONFIG_FILE}`, `${INPUT_ARTIFACTS_DIR}`, `${TARGET_DIR}`
2. **Write all outputs to `${TARGET_DIR}`** — the orchestration layer handles archiving
3. **Read all inputs from `${INPUT_ARTIFACTS_DIR}`** — they are copied/restored there before the stage starts
4. **Use `${WORKSPACE}` only for ephemeral scratch** — it will be clean at stage start on both systems
5. **Call `validate_standard_environment`** — it verifies `WORKSPACE` and `CONFIG_FILE` are set and provides the `TARGET_DIR` default

```bash
# Correct — works on both Jenkins and local
source "${SCRIPT_DIR}/../lib/config-utils.sh"
validate_standard_environment

local config_file="${CONFIG_FILE}"
local input_dir="${INPUT_ARTIFACTS_DIR}"
local output_dir="${TARGET_DIR}"
local scratch="${WORKSPACE}/my-stage-scratch"

mkdir -p "${scratch}" "${output_dir}"
# read inputs from ${input_dir}/...
# write outputs to ${output_dir}/...
# temp files under ${scratch}/... (cleaned before next stage)
```

---

## Troubleshooting

### Stage script can't find `pipeline-config.json`

On Jenkins, `CONFIG_FILE` is set to `${INPUT_ARTIFACTS_DIR}/pipeline-config.json` by `PipelineHelper.initializeStage()`. Locally, it is set to `${WORKSPACE}/pipeline-config.json` (restored from `build_artifacts/` by `restore_stage_inputs()`). In both cases, `CONFIG_FILE` is inside or co-located with `INPUT_ARTIFACTS_DIR` — never assume it is at the pipeline root.

### Stage outputs not found by next stage (Jenkins)

The stage must call `archiveArtifacts` for its `TARGET_DIR` output, and the next stage's `artifactFilter` in `initializeStage()` must include the relevant glob. A file missing from the filter means `copyArtifacts` won't retrieve it.

### Stage outputs not found by next stage (Local)

`TARGET_DIR` is a stage-specific sub-directory such as `stage_workspace/build_output/`. If outputs are missing in `build_artifacts/`, the stage script wrote to `WORKSPACE` (ephemeral) instead of `TARGET_DIR` (archived). Check the script uses `${TARGET_DIR}` for all output files.

### Disk space full (local)

`build_artifacts/` is never auto-cleaned. Use `--clean-workspace` on the next run, or manually remove `<pipeline_workspace>/build_artifacts/`. Individual artifact files can also be deleted without affecting `stage_workspace/`.

### `cleanWs()` or workspace cleanup not happening (Jenkins)

`finalizeStage()` only calls `cleanWs()` when the `CLEAN_WORKSPACE_AFTER_STAGE` job parameter is `true`. The pre-stage `cleanWs()` inside `initializeStage()` always runs unconditionally.

### Restart fails with "build_artifacts/ does not exist"

This means the workspace was created by an older version of the local runner (which used `artifacts/` rather than `build_artifacts/`). Remove the existing workspace and run a fresh full build:
```bash
python3 run-pipeline.py --jdk-version jdk21 --config-repo-url https://github.com/adoptium/ci-temurin-config.git ... --clean-workspace
```

---

## Related Documentation

- [PIPELINE_RUNNER_GUIDE.md](./PIPELINE_RUNNER_GUIDE.md) — local runner CLI reference including workspace validation rules
- [CI_AGNOSTIC_ARCHITECTURE.md](./CI_AGNOSTIC_ARCHITECTURE.md) — artifact flow diagram (Jenkins `copyArtifacts` ↔ `archiveArtifacts`)
- [UNIVERSAL_STAGE_PATTERN.md](./UNIVERSAL_STAGE_PATTERN.md) — stage script template using these env vars
- [`scripts/lib/config-utils.sh`](../scripts/lib/config-utils.sh) — `validate_standard_environment()` implementation
- [`ci/local/workspace_manager.py`](../ci/local/workspace_manager.py) — `WorkspaceManager` implementation
- [`ci/local/run-pipeline.py`](../ci/local/run-pipeline.py) — per-stage `restore_stage_inputs()` / `archive_stage_outputs()` calls
