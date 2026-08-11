# Pipeline Runner Guide

The `ci/local/run-pipeline.py` script runs the complete OpenJDK build pipeline locally from the command line. It mirrors Jenkins semantics: each stage runs in a clean `stage_workspace/`, copies inputs from `build_artifacts/`, and archives outputs back to `build_artifacts/` when done.

## Quick Start

```bash
cd ci-adoptium-pipelines

python3 ci/local/run-pipeline.py \
    --jdk-version jdk21 \
    --target-os mac \
    --architecture aarch64 \
    --config-repo-url https://github.com/adoptium/ci-temurin-config.git
```

`--config-repo-url` is required. It points to the config repo that provides build configuration, variant defaults, and any vendor-specific stage overrides.

## What It Does

The pipeline runner orchestrates the locally-executable stages in sequence:

1. **Initialize** — clones the config repo; generates `pipeline-config.json`; archives it to `build_artifacts/`
2. **Build** — clones `temurin-build`; runs `make-adopt-build-farm.sh`; archives JDK tarballs to `build_artifacts/`
3. **Validate SBOM** — validates SBOM files (gated: runs only when `CREATE_SBOM=true`)
4. **Smoke Tests** — extracts JDK and runs basic checks (gated: runs only when `RUN_TESTS=true`)
5. **AQA Tests** — runs AQAVit test suite (gated: runs only when `RUN_TESTS=true`)
6. **Reproducible Compare** — downloads Adoptium production binary and compares (gated: runs only when `RUN_REPRODUCIBLE_COMPARE=true` and `SCM_REF` is non-empty)

CI-only stages (code signing, assembling images, installers, publishing) are not executed by the local runner.

Stage gates are driven by stage parameters loaded dynamically from `scripts/stages/*.params.json` (and any vendor-scripts overrides) — not hardcoded CLI flags. See **Stage Parameters** below.

---

## Command Line Reference

### Required

| Parameter | Description | Format |
|---|---|---|
| `--jdk-version` | JDK version to build | `jdk<N>` — e.g. `jdk21`, `jdk17`, `jdk8` |
| `--target-os` | Target OS | `mac`, `linux`, `windows`, `aix` |
| `--architecture` | Target architecture | `aarch64`, `x64`, `x32`, `ppc64`, `s390x` |
| `--config-repo-url` | URL of the config repo containing `configurations/`, `vendor-scripts/`, `adoptium_pipeline_config.json` | Any git-cloneable URL |

Note: `--jdk-version` must match the pattern `jdk` followed by digits only (e.g. `jdk21`). Suffixes like `jdk21u` are not accepted.

### Configuration repo

| Parameter | Description | Default |
|---|---|---|
| `--config-repo-branch` | Branch to clone | `main` |

The config repo provides: build/AQA repo URLs and branches, the default variant, and active JDK version list.

### Release type

| Parameter | Description |
|---|---|
| `--release-type` | `NIGHTLY` (default), `WEEKLY` (adds `--with-version-opt=ea`), or `RELEASE` (case-insensitive) |

### Workspace control

| Parameter | Description |
|---|---|
| `--workspace` | Root workspace directory (default: `~/openjdk-build`) |
| `--build-number` | Build identifier string (default: `local-YYYYMMDD-HHMMSS`) |
| `--clean-workspace` | Remove existing workspace before starting |

**Workspace rules** — the runner validates workspace state before any stage runs:
- **Workspace does not exist**: fresh build proceeds normally
- **Workspace exists + no flags**: ❌ error — use `--clean-workspace` or `--start-from-stage`
- **`--clean-workspace`**: removes entire `pipeline_workspace/` then creates fresh structure
- **`--start-from-stage` + workspace + `build_artifacts/` exist**: restart proceeds
- **`--clean-workspace` + `--start-from-stage`**: ❌ error — mutually exclusive

### Stage control

| Parameter | Description |
|---|---|
| `--start-from-stage` | Start from a specific stage, skipping earlier ones (requires existing workspace) |

Valid `--start-from-stage` values (exact stage IDs from `pipeline-stages.json`):

| Stage ID | Stage |
|---|---|
| `01-initialize` | Initialize |
| `02-build` | Build |
| `12-validate-sbom` | Validate SBOM |
| `13-smoke-tests` | Smoke Tests |
| `14-aqa-tests` | AQA Tests |
| `20-reproducible-compare` | Reproducible Compare |

Stage enable/disable is controlled via **stage parameters**, not dedicated CLI flags. See **Stage Parameters** below.

---

## Stage Parameters

Stage-specific parameters are loaded dynamically from `scripts/stages/*.params.json` (and any `vendor-scripts/*.params.json` overrides in the checked-out config repo). This ensures the local runner always presents the same parameter surface as the Jenkins jobs.

Pass stage parameters as `--<lower-kebab-case-name> <value>` after all fixed arguments. Both boolean and string parameters require an explicit value token:

```bash
--create-sbom true
--run-tests false
--scm-ref jdk-21.0.7+6_adopt
--extra-build-args "--enable-dtrace"
```

Run `--help` to see all available stage parameters for a given config repo:

```bash
python3 ci/local/run-pipeline.py \
    --jdk-version jdk21 --target-os mac --architecture aarch64 \
    --config-repo-url https://github.com/adoptium/ci-temurin-config.git \
    --help
```

### Common stage parameters

These are defined in the default `scripts/stages/*.params.json` files and apply to all builds unless overridden by a vendor config repo:

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--scm-ref` | string | `""` | OpenJDK source tag/ref (e.g. `jdk-21.0.7+6_adopt`). Required for `--run-reproducible-compare true`. |
| `--build-ref` | string | `""` | `temurin-build` branch/tag. Empty = default from `adoptium_pipeline_config.json`. |
| `--extra-build-args` | string | `""` | Additional arguments appended to the build stage invocation. |
| `--extra-configure-args` | string | `""` | Extra options appended to the configure invocation. |
| `--extra-make-options` | string | `""` | Extra options appended to the make invocation. |
| `--create-sbom` | boolean | `false` | Generate an SBOM during build; also gates the Validate SBOM stage. |
| `--run-tests` | boolean | `true` | Enable Smoke Tests and AQA Tests stages. |
| `--enable-installers` | boolean | `true` | Enable the installer build stage (CI-only; has no effect in the local runner). |
| `--sign-artifacts` | boolean | `false` | Enable artifact signing stages (CI-only; has no effect in the local runner). |
| `--run-reproducible-compare` | boolean | `false` | Enable the Reproducible Compare stage. Requires `--scm-ref` to be set. |
| `--aqa-ref` | string | `""` | AQA tests branch/tag. Empty = default from `adoptium_pipeline_config.json`. |

---

## Usage Examples

### Full build (macOS Apple Silicon)

```bash
python3 ci/local/run-pipeline.py \
    --jdk-version jdk21 \
    --target-os mac \
    --architecture aarch64 \
    --config-repo-url https://github.com/adoptium/ci-temurin-config.git
```

### Clean build (remove existing workspace first)

```bash
python3 ci/local/run-pipeline.py \
    --jdk-version jdk21 \
    --target-os mac \
    --architecture aarch64 \
    --config-repo-url https://github.com/adoptium/ci-temurin-config.git \
    --clean-workspace
```

### Build only — skip tests

```bash
python3 ci/local/run-pipeline.py \
    --jdk-version jdk21 \
    --target-os mac \
    --architecture aarch64 \
    --config-repo-url https://github.com/adoptium/ci-temurin-config.git \
    --run-tests false
```

### Build with SBOM generation

```bash
python3 ci/local/run-pipeline.py \
    --jdk-version jdk21 \
    --target-os mac \
    --architecture aarch64 \
    --config-repo-url https://github.com/adoptium/ci-temurin-config.git \
    --create-sbom true
```

Generates an SBOM during the build stage and also runs the Validate SBOM stage.

### Release build (Linux x64)

```bash
python3 ci/local/run-pipeline.py \
    --jdk-version jdk17 \
    --target-os linux \
    --architecture x64 \
    --config-repo-url https://github.com/adoptium/ci-temurin-config.git \
    --release-type RELEASE \
    --scm-ref jdk-17.0.10+7
```

### Weekly (EA beta) build

```bash
python3 ci/local/run-pipeline.py \
    --jdk-version jdk21 \
    --target-os mac \
    --architecture aarch64 \
    --config-repo-url https://github.com/adoptium/ci-temurin-config.git \
    --release-type WEEKLY
```

Adds `--with-version-opt=ea` to configure args.

### Custom temurin-build branch

```bash
python3 ci/local/run-pipeline.py \
    --jdk-version jdk21 \
    --target-os mac \
    --architecture aarch64 \
    --config-repo-url https://github.com/adoptium/ci-temurin-config.git \
    --build-ref develop
```

### Custom workspace directory

```bash
python3 ci/local/run-pipeline.py \
    --jdk-version jdk21 \
    --target-os mac \
    --architecture aarch64 \
    --config-repo-url https://github.com/adoptium/ci-temurin-config.git \
    --workspace ~/my-jdk21-build
```

### Restart from a specific stage

```bash
# After a failed smoke-tests stage, re-run from there onwards
python3 ci/local/run-pipeline.py \
    --jdk-version jdk21 \
    --target-os mac \
    --architecture aarch64 \
    --config-repo-url https://github.com/adoptium/ci-temurin-config.git \
    --start-from-stage 13-smoke-tests
```

The workspace and `build_artifacts/` from the previous run must exist.

### Reproducible build comparison

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

Downloads the matching Adoptium production binary and compares it against the locally built JDK. See [REPRO_COMPARE_INTEGRATION.md](./REPRO_COMPARE_INTEGRATION.md).

### Parallel builds (different workspaces)

```bash
# Terminal 1: JDK 21
python3 ci/local/run-pipeline.py --jdk-version jdk21 --target-os mac --architecture aarch64 \
    --config-repo-url https://github.com/adoptium/ci-temurin-config.git \
    --workspace ~/jdk21-build

# Terminal 2: JDK 17
python3 ci/local/run-pipeline.py --jdk-version jdk17 --target-os mac --architecture aarch64 \
    --config-repo-url https://github.com/adoptium/ci-temurin-config.git \
    --workspace ~/jdk17-build
```

### Vendor fork with vendor-specific stage params

```bash
python3 ci/local/run-pipeline.py \
    --jdk-version jdk21 --target-os linux --architecture s390x \
    --config-repo-url https://github.com/myorg/ci-openj9-config.git \
    --openj9-repo git@github.ibm.com:myuser/openj9.git \
    --openj9-branch my-feature-branch
```

Vendor-specific parameters (like `--openj9-repo`) are declared in the vendor config repo's `vendor-scripts/*.params.json` files and are automatically recognised after the config repo is cloned.

---

## Workspace Layout

```
~/openjdk-build/                    # pipeline_workspace (--workspace)
│
├── pipeline-config.json            # Generated by Initialize
│                                   # (immediately archived to build_artifacts/)
│
├── config-repo/                    # Cloned once at Initialize
│   ├── configurations/
│   ├── vendor-scripts/
│   └── adoptium_pipeline_config.json
│
├── stage_workspace/                # Ephemeral — wiped before each stage
│   ├── pipeline-config.json        # Restored from build_artifacts/ before each stage
│   ├── *.tar.gz, *.zip …           # Other stage inputs (restored from build_artifacts/)
│   └── target/                     # Stage writes outputs here (TARGET_DIR)
│
└── build_artifacts/                # Durable archive store — persists across stages
    ├── pipeline-config.json
    ├── OpenJDK*.tar.gz             # Built JDK (after Build stage)
    ├── *.json                      # SBOM, metadata
    └── …                          # Test results, reproducible compare outputs
```

All final artifacts are in `build_artifacts/` after the pipeline completes.

---

## Environment Variables Set Per Stage

| Variable | Value |
|---|---|
| `WORKSPACE` | `stage_workspace/` — ephemeral scratch dir for this stage |
| `CONFIG_FILE` | `stage_workspace/pipeline-config.json` — restored from `build_artifacts/` |
| `INPUT_ARTIFACTS_DIR` | `stage_workspace/` — inputs copied in from `build_artifacts/` |
| `TARGET_DIR` | `stage_workspace/target/` — stage writes outputs here |
| `BUILD_NUMBER` | `local-YYYYMMDD-HHMMSS` (or `--build-number` value) |
| `PIPELINE_ROOT` | Root of the `ci-adoptium-pipelines` checkout |
| `RELEASE_TYPE` | `NIGHTLY`, `WEEKLY`, or `RELEASE` (from `--release-type`) |
| `CLEAN_WORKSPACE_AFTER_STAGE` | `true` if `--clean-workspace` was passed, `false` otherwise |

All collated stage parameters are also injected as environment variables (e.g. `RUN_TESTS`, `CREATE_SBOM`, `SCM_REF`) so that stage shell scripts can read them directly.

---

## Troubleshooting

### "Workspace already exists" error on fresh build

The runner refuses to overwrite an existing workspace without an explicit instruction. Use `--clean-workspace` to remove it first, or `--start-from-stage` to continue from where it left off.

### "build_artifacts/ does not exist" on restart

The workspace was created by an older version of the local runner (which used `artifacts/` instead of `build_artifacts/`). Run with `--clean-workspace` to start fresh.

### Unrecognised parameter error

```
❌ Unrecognised parameter(s) — not defined in any *.params.json for this config repo:
   --no-tests
```

Dedicated `--no-*` flags no longer exist. Stage gates are now controlled via stage parameters: use `--run-tests false`, `--enable-installers false`, `--sign-artifacts false`, etc. Run with `--help` to see all available parameters for the current config repo.

### Initialize fails — configuration not found

- Verify `--config-repo-url` points to a reachable repository
- Confirm the repo contains `configurations/` and `adoptium_pipeline_config.json`
- Check that `configFilePrefix` in `adoptium_pipeline_config.json` matches the actual config directory name
- Use `tools/` to convert legacy Groovy configs if migrating

### Build fails — missing dependencies

Ensure the following are installed on the build machine: `git`, `make`, `gcc`/`clang`, a boot JDK (N−1 version of the target JDK). The boot JDK must be in `PATH` or `JAVA_HOME` must be set.

### Build time

A full JDK build typically takes 30–60 minutes. Use `--run-tests false` to get just the JDK tarball without running test stages.

### Script not executable

```bash
chmod +x ci/local/run-pipeline.py
chmod +x scripts/stages/*.sh scripts/lib/*.sh
```

---

## See Also

- [WORKSPACE_ARTIFACTS_ARCHITECTURE.md](./WORKSPACE_ARTIFACTS_ARCHITECTURE.md) — workspace layout, archive/restore semantics, validation rules
- [CODE_CONFIG_SEPARATION.md](./CODE_CONFIG_SEPARATION.md) — config repo structure and `pipeline-config.json` schema
- [REPRO_COMPARE_INTEGRATION.md](./REPRO_COMPARE_INTEGRATION.md) — reproducible build comparison details
- [CI_AGNOSTIC_ARCHITECTURE.md](./CI_AGNOSTIC_ARCHITECTURE.md) — overall pipeline architecture
- [`ci/local/README.md`](../ci/local/README.md) — local runner module README
