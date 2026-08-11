# Pluggable Stage Script Design

This document describes the vendor-overridable stage script mechanism used by
`ci-adoptium-pipelines`. It allows multiple vendors to share the same pipeline
code while supplying their own implementations of stages that differ between
organisations (e.g. code-signing), while still benefiting from a common set of
default implementations for stages that are universal (e.g. build, smoke tests).

---

## Core Idea: Resolution Order

A single Jenkinsfile helper function `runStageScript(stem, config)` resolves the
implementation to run using a fixed priority chain:

```
1. config-repo/vendor-scripts/<stem>.sh      ← vendor override (sh)
2. config-repo/vendor-scripts/<stem>.groovy  ← vendor override (groovy)
3. config-repo/vendor-scripts/<stem>.py      ← vendor override (python)
4. scripts/stages/<stem>.sh                  ← default (sh)
5. scripts/stages/<stem>.groovy              ← default (groovy)
6. scripts/stages/<stem>.py                  ← default (python)
7. built-in no-op stub                       ← safe fallback (logs and exits 0)
```

Vendor scripts live in **the config repo** under `vendor-scripts/`.  
Default scripts live in **this repo** under `scripts/stages/`.  
The Jenkinsfile never hard-codes a path — it always delegates to the resolver.

---

## Stage Script Name Convention

Script file names (stems) are derived from the stage number and a short
lower-cased hyphenated description:

| Stage Name             | Script Stem              | Default in this repo           |
|------------------------|--------------------------|--------------------------------|
| Build                  | `02-build`               | Full implementation (`.sh`)    |
| Internal Sign          | `03-internal-sign`       | No-op stub (`.sh`)             |
| Assemble               | `04-assemble`            | No-op stub (`.sh`)             |
| Sign Artifacts         | `06-sign`                | No-op stub (`.sh`)             |
| Build Installers       | `07-installer`           | No-op stub (`.sh`)             |
| Sign Installers        | `08-sign-installer`      | No-op stub (`.sh`)             |
| GPG Sign               | `09-gpg-sign`            | No-op stub (`.sh`)             |
| SBOM Sign              | `10-sbom-sign`           | No-op stub (`.sh`)             |
| Verify Signing         | `11-verify-signing`      | No-op stub (`.sh`)             |
| Validate SBOM          | `12-validate-sbom`       | Full implementation (`.sh`)    |
| Smoke Tests            | `13-smoke-tests`         | Full implementation (`.sh`)    |
| AQA Tests              | `14-aqa-tests`           | No-op stub (`.sh`)             |
| TCK Tests              | `15-tck-tests`           | No-op stub (`.sh`)             |
| Publish Artifacts      | `16-publish`             | No-op stub (`.sh`)             |
| Reproducible Compare   | `20-reproducible-compare`| Full implementation (`.sh`)    |

**Full implementation** — a working default used by all vendors unless overridden.  
**No-op stub** — an echo-only placeholder; vendors must supply an override for the
stage to do real work.

---

## The `runStageScript()` Helper

One new function in `Jenkinsfile.declarative` replaces all hard-coded
`load 'scripts/stages/...'` and `sh 'bash scripts/stages/...'` calls:

```groovy
/**
 * Resolve and execute a stage script.
 * Searches vendor-scripts/ (config-repo) first, then scripts/stages/ (this repo).
 * Supports .sh, .groovy, and .py implementations.
 *
 * @param scriptStem  e.g. '03-internal-sign'
 * @param config      pipeline-config map (passed to .groovy scripts;
 *                    .sh and .py scripts use environment variables)
 */
def runStageScript(String scriptStem, def config = null) {
    def searchPaths = [
        [path: "config-repo/vendor-scripts/${scriptStem}.sh",     type: 'sh'],
        [path: "config-repo/vendor-scripts/${scriptStem}.groovy", type: 'groovy'],
        [path: "config-repo/vendor-scripts/${scriptStem}.py",     type: 'py'],
        [path: "scripts/stages/${scriptStem}.sh",                 type: 'sh'],
        [path: "scripts/stages/${scriptStem}.groovy",             type: 'groovy'],
        [path: "scripts/stages/${scriptStem}.py",                 type: 'py'],
    ]

    def found = searchPaths.find { fileExists(it.path) }

    if (!found) {
        echo "ℹ️  No script found for '${scriptStem}' — stage is a no-op (stub)"
        return
    }

    echo "▶ Running ${found.type.toUpperCase()} stage script: ${found.path}"

    switch (found.type) {
        case 'sh':
            sh "bash ${found.path}"
            break
        case 'groovy':
            def script = load found.path
            script(config)
            break
        case 'py':
            sh "python3 ${found.path}"
            break
    }
}
```

---

## Script Contracts

### Shell scripts (`.sh`)

Communicate entirely via environment variables. The Jenkinsfile sets the
relevant variables before calling `runStageScript()`. Common variables:

| Variable             | Description                                      |
|----------------------|--------------------------------------------------|
| `WORKSPACE`          | Stage workspace root                             |
| `CONFIG_FILE`        | Path to `pipeline-config.json`                   |
| `INPUT_ARTIFACTS_DIR`| Directory containing input artifacts             |
| `TARGET_DIR`         | Directory for this stage's output                |
| `BUILD_NUMBER`       | Jenkins build number                             |
| `BUILD_UID`          | Unique build identifier                          |
| `GROUP_UID`          | Group identifier (set by Launch pipeline)        |

### Groovy scripts (`.groovy`)

Must expose a `call(Map config)` function and end with `return this`:

```groovy
def call(Map config) {
    def buildConfig = config.buildConfig
    // ... implementation ...
}

return this
```

### Python scripts (`.py`)

Like shell scripts, communicate via environment variables. Must exit with
code `0` on success and non-zero on failure.

---

## No-op Stub Convention

For stages with no universal default (e.g. Internal Sign), the default script
is a minimal stub that logs clearly and exits 0. The build does **not** fail
when a stub runs — the `when {}` guard in the Jenkinsfile is the sole gate for
deciding whether a stage should run at all.

```bash
#!/bin/bash
# DEFAULT STUB: 03-internal-sign.sh
# This is a no-op placeholder. Override by placing a script at:
#   config-repo/vendor-scripts/03-internal-sign.{sh,groovy,py}
echo "ℹ️  Internal Sign: no vendor implementation configured — skipping"
```

---

## Config Repo Layout for Vendor Overrides

```
config-repo/                          ← checked out by Initialize stage
  configurations/
    jdk21_pipeline_config.json
  vendor-scripts/                     ← vendor override scripts go here
    03-internal-sign.sh               ← vendor's own signing impl
    09-gpg-sign.groovy                ← vendor's GPG sign (groovy)
    14-aqa-tests.sh                   ← vendor's AQA test runner
```

The `vendor-scripts/` path must be included in the sparse checkout performed
by the Initialize stage:

```groovy
extensions: [
    [$class: 'SparseCheckoutPaths',
     sparseCheckoutPaths: [
         [path: 'configurations/*'],
         [path: 'vendor-scripts/*']    // required for vendor overrides
     ]]
]
```

---

## How Stages Change in the Jenkinsfile

Before (hard-coded, mixed patterns):

```groovy
// groovy stage
def signScript = load 'scripts/stages/03-internal-sign.groovy'
signScript(config)

// sh stage
sh 'bash scripts/stages/12-validate-sbom.sh'
```

After (uniform, vendor-aware):

```groovy
runStageScript('03-internal-sign', config)

runStageScript('12-validate-sbom')
```

The Jenkinsfile no longer cares what the implementation language is.

---

## What Stays the Same

- `when {}` guards — unchanged. Stage enablement is still controlled by config
  flags and environment variables.
- Environment variable contract for `.sh` scripts — unchanged.
- `initializeStage()` / `finalizeStage()` / `executeStageWithTracking()` — unchanged.
- `pipeline-config.json` schema — no changes needed. The script resolver is
  purely filesystem-based.

---

## What a Vendor Does

To override **Internal Sign** for Temurin (Eclipse CBI codesign service):

1. Create `vendor-scripts/03-internal-sign.sh` in the config repo:

```bash
#!/bin/bash
# Temurin internal signing via Eclipse CBI codesign service
set -euo pipefail
# ... actual curl signing logic ...
```

2. No changes to `ci-adoptium-pipelines` are required. The next pipeline run
   picks up the vendor script automatically.

---

## Implementation Checklist (Jenkins)

- [ ] Add `runStageScript()` helper to `Jenkinsfile.declarative` (above `pipeline {}`)
- [ ] Replace every `load '...'` + `script(config)` call with `runStageScript('<stem>', config)`
- [ ] Replace every `sh 'bash scripts/stages/...'` call with `runStageScript('<stem>')`
- [ ] Add `vendor-scripts/*` to sparse checkout paths in the Initialize stage
- [ ] Replace `scripts/stages/03-internal-sign.groovy` with a `03-internal-sign.sh` stub
- [ ] Add no-op stub `.sh` files for all other not-yet-implemented stages

---

## Local Pipeline (`ci/local/run-pipeline.py`)

### Overview

`run-pipeline.py` is a CI-agnostic local runner that mirrors the Jenkins pipeline
stages on a developer's machine. It currently hard-codes each stage script path
inside a dedicated `stage_<name>()` method. The same pluggable model applies here,
with two simplifications:

1. **No Groovy** — only `.sh` and `.py` scripts can run locally.
2. **No Jenkins artifacts** — stages communicate via the filesystem
   (`INPUT_ARTIFACTS_DIR`, `TARGET_DIR`) rather than `archiveArtifacts`.

### Stage Enablement via `pipeline-config.json`

The `StageResolver` reads the `parameters` section of `pipeline-config.json`
(the same `CONFIG_FILE` used by stage scripts) to decide whether a stage should
run.  This is the single source of truth — the same file that
`load-json-config.py` writes and that stage scripts read at runtime.

**Parameter-to-stage mapping:**

| Stage stem                | Parameter key             | Default |
|---------------------------|---------------------------|---------|
| `06-sign`                 | `parameters.enableSigner`     | `true`  |
| `07-installer`            | `parameters.enableInstallers` | `true`  |
| `13-smoke-tests`          | `parameters.enableTests`      | `true`  |
| `20-reproducible-compare` | `parameters.compareBuild`     | `false` |

Stages without an entry in this table are always enabled (e.g. `02-build`,
`12-validate-sbom`).

When a stage is disabled, `StageResolver.run()` prints a message indicating
which parameter caused the skip and returns exit code 0 without executing any
script.

### Resolution Order (Local)

For each stage, `run-pipeline.py` resolves the script to run in this order:

```
1. config-repo/vendor-scripts/<stem>.sh   ← vendor override (sh)
2. config-repo/vendor-scripts/<stem>.py   ← vendor override (python)
3. scripts/stages/<stem>.sh               ← default (sh)
4. scripts/stages/<stem>.py               ← default (python)
5. built-in no-op                         ← logs and continues
```

Steps 1–4 mirror the Jenkins resolution order, minus Groovy.

### The `StageResolver` Helper Class

`ci/local/stage_resolver.py` encapsulates script resolution and
parameter-based gating, replacing hard-coded paths in each `stage_*()`
method:

```python
class StageResolver:
    """
    Resolves which script to run for a given stage stem.
    Reads parameters from pipeline-config.json to gate stages.
    Searches vendor-scripts/ (config-repo) before scripts/stages/ (this repo).
    Supports .sh and .py implementations.
    """

    EXTENSIONS = ['.sh', '.py']

    def __init__(self, pipeline_root: Path, config_repo_root: Path | None,
                 config_file: Path | None = None):
        self.pipeline_root = pipeline_root
        self.config_repo_root = config_repo_root
        self._config_file = config_file  # pipeline-config.json

    def is_enabled(self, stem: str) -> tuple[bool, str]:
        """
        Returns (enabled, reason).
        Reads parameters from pipeline-config.json.
        If no gate exists for this stem, defaults to (True, '').
        """
        ...

    def resolve(self, stem: str) -> Path | None:
        """
        Resolve the script path for the given stem.
        Returns None if no script is found (no-op).
        """
        # 1-2. Vendor override in config-repo/vendor-scripts/
        ...
        # 3-4. Default in scripts/stages/
        ...
        return None  # no-op

    def run(self, stem: str, env: dict) -> int:
        """
        Check enablement, resolve, and execute the stage script.
        Returns the exit code (0 = success).
        """
        enabled, reason = self.is_enabled(stem)
        if not enabled:
            print(f"ℹ️  Stage '{stem}' disabled: {reason}")
            return 0

        script = self.resolve(stem)
        if script is None:
            print(f"ℹ️  No script found for '{stem}' — stage is a no-op")
            return 0

        ...
        result = subprocess.run(cmd, env=env)
        return result.returncode
```

### How Stage Methods Change

Before (hard-coded path per stage method):

```python
cmd = [str(self.script_dir / 'scripts' / 'stages' / '02-build.sh')]
subprocess.run(cmd, env=env, check=True)
```

After (uniform resolver call):

```python
exit_code = self._make_resolver().run('02-build', env)
if exit_code != 0:
    raise subprocess.CalledProcessError(exit_code, '02-build')
```

The `stage_*()` methods shrink to just building the `env` dict and
calling `self._make_resolver().run()`. Stage enablement that was previously
checked in `PipelineRunner.run()` via CLI args (e.g. `if self.args.enable_signer`)
is now driven by the `parameters` section of `pipeline-config.json` — the same
file that `load-json-config.py` generates from the CLI args.

### Initialising the Resolver

The resolver is created lazily by `_make_resolver()`. It receives the
`config_file` path (pointing to `pipeline-config.json`) so it can read
parameters for stage gating:

```python
def _make_resolver(self) -> StageResolver:
    config_repo_root = None
    if self.args.config_repo_url:
        candidate = self.workspace / 'config-repo'
        if candidate.exists():
            config_repo_root = candidate

    if self._resolver is None or ...:
        self._resolver = StageResolver(
            self.script_dir, config_repo_root, self.config_file
        )
    return self._resolver
```

Because the config repo is cloned during `stage_initialize()`, the resolver
is (re-)created after that stage completes when the config repo becomes
available.

### Config Repo Layout (combined view)

```
config-repo/
  configurations/
    jdk21_pipeline_config.json        ← CI-agnostic build config (unchanged)
  vendor-scripts/
    03-internal-sign.sh               ← vendor override (Jenkins + local)
    06-sign.sh                        ← vendor sign impl
    13-smoke-tests.py                 ← vendor smoke tests (Python)
```

### Implementation Checklist (Local)

- [x] Extract `StageResolver` class (new file `ci/local/stage_resolver.py`)
- [x] `StageResolver` reads `pipeline-config.json` parameters to gate stages
- [x] Replace hard-coded `cmd = [str(self.script_dir / 'scripts' / 'stages' / ...)]`
      in each `stage_*()` method with `self._make_resolver().run(stem, env)`
- [x] Remove CLI-arg-based gating from `PipelineRunner.run()` — delegated to resolver
- [ ] Document `pipeline-config.json` parameters schema (this file serves as that doc)
