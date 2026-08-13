# Development Guide

This guide covers everything you need to work on the pipeline codebase: running linters and tests locally, the testing strategy, and the architecture and code style rules to follow when making changes.

---

## Local Linting

Linting is enforced automatically on every pull request via GitHub Actions ([`.github/workflows/linter.yml`](../.github/workflows/linter.yml)). Run the same checks locally before pushing to catch issues early.

### Python — black + pylint

[black](https://black.readthedocs.io/) enforces consistent formatting. [pylint](https://pylint.readthedocs.io/) enforces style and catches common errors. Both are configured in the repository:

- pylint config: [`.github/linters/.python-lint`](../.github/linters/.python-lint)

```bash
# Check formatting (--check does not modify files)
python3.11 -m black --check .

# Apply formatting
python3.11 -m black .

# Run pylint across all Python source
python3.11 -m pylint --rcfile=.github/linters/.python-lint \
    scripts/lib/*.py \
    tools/*.py \
    tests/*.py \
    ci/local/*.py \
    ci/local/lib/*.py
```

> **Note**: black and pylint must be installed in the Python environment you are using. If `python3.11 -m black` fails, check which Python has them installed (`pip show black pylint`) and use that interpreter. The project has no runtime dependency on third-party packages — black and pylint are developer-only tools.

### Shell — shellcheck

```bash
shellcheck scripts/stages/*.sh scripts/lib/*.sh
```

---

## Running Unit Tests

Python unit tests live in [`tests/`](../tests/) and use the standard `unittest` module.

```bash
python3 -m unittest discover -s tests -v
```

Shell-based tests use plain shell scripts:

```bash
bash tests/test_determine_filename.sh
bash tests/test_release_type_validation.sh
```

---

## Testing Strategy

| Level | What | When required |
|---|---|---|
| 1 — Syntax & linting | `black`, `pylint`, `shellcheck` | Always |
| 2 — Unit tests | `python3 -m unittest discover -s tests` | Always |
| 3 — Stage smoke | Run a single stage script directly | Stage script changes |
| 4 — Local pipeline | `ci/local/run-pipeline.py` end-to-end | Major or cross-stage changes |
| 5 — CI validation | Automatic on PR via GitHub Actions | All PRs |

**By change type:**

| Change type | Minimum levels |
|---|---|
| Documentation only | — |
| Configuration change | 1 |
| Python utility change | 1, 2 |
| Stage script change | 1, 2, 3 |
| Cross-stage / orchestration | 1, 2, 4 |
| Major refactoring | All |

### Running a single stage locally

Stage scripts rely on environment variables set by the orchestrator (Jenkins or `run-pipeline.py`). Before invoking a script directly you must populate those variables yourself. The full contract is documented in [UNIVERSAL_STAGE_PATTERN.md](./UNIVERSAL_STAGE_PATTERN.md); the minimum required set is:

| Variable | Purpose |
|---|---|
| `WORKSPACE` | Stage working directory |
| `CONFIG_FILE` | Path to `pipeline-config.json` |
| `TARGET_DIR` | Directory for this stage's output artefacts |
| `INPUT_ARTIFACTS_DIR` | Directory containing artefacts from previous stages |
| `BUILD_NUMBER` | Build identifier (can be any string, e.g. `local`) |
| `CONFIG_*` | Build config values pre-populated from `pipeline-config.json` (e.g. `CONFIG_TARGET_OS`, `CONFIG_ARCHITECTURE`) |

```bash
export WORKSPACE="$(pwd)/workspace"
export CONFIG_FILE="${WORKSPACE}/pipeline-config.json"
export TARGET_DIR="${WORKSPACE}/build_output"
export INPUT_ARTIFACTS_DIR="${WORKSPACE}/build_artifacts"
export BUILD_NUMBER="local"
# CONFIG_* vars depend on the stage — check the script header for what it reads

./scripts/stages/02-build.sh
echo $?  # 0 = success
```

For a fully wired local run that sets up all of this automatically, use `ci/local/run-pipeline.py` (see [PIPELINE_RUNNER_GUIDE.md](./PIPELINE_RUNNER_GUIDE.md)).

### Running the full local pipeline

See [PIPELINE_RUNNER_GUIDE.md](./PIPELINE_RUNNER_GUIDE.md) for full argument reference.

```bash
python3 ci/local/run-pipeline.py \
  --jdk-version jdk21 \
  --target-os linux \
  --architecture x64 \
  --config-repo-url https://github.com/adoptium/ci-temurin-config.git
```

---

## Architecture

All changes must respect the 3-layer architecture. Full design detail is in [CI_AGNOSTIC_ARCHITECTURE.md](./CI_AGNOSTIC_ARCHITECTURE.md).

```text
Layer 1: Configuration (JSON — config repository)
  ↓
Layer 2: Build Logic (Shell scripts — CI-agnostic)
  ↓
Layer 3: Orchestration (CI-specific — Jenkins / GitHub Actions)
```

### Layer 1 — Configuration

- Pure JSON data, no logic
- Lives in the separate config repository (`ci-temurin-config` or equivalent)
- Schema reference: [CONFIG_SCHEMA.md](./CONFIG_SCHEMA.md)

### Layer 2 — Build Logic (`scripts/`)

- Plain shell scripts (`set -euo pipefail`), no CI-specific APIs
- Read config from `pipeline-config.json`; write outputs to `TARGET_DIR`
- Use `scripts/lib/logging-utils.sh` for structured log output
- New stage template: [UNIVERSAL_STAGE_PATTERN.md](./UNIVERSAL_STAGE_PATTERN.md)

### Layer 3 — Orchestration (`ci/`)

- Thin wrappers that call Layer 2 scripts
- Handle CI-specific features (artifact archiving, notifications, job parameters)
- No business logic or inline shell snippets

---

## Code Style

### Shell scripts

- Use `[[ ]]` instead of `[ ]`
- Always quote variables: `"${var}"`
- Use `$(command)` instead of backticks
- Check exit codes explicitly: `command || handle_error`
- No `eval`, no parsing of `ls` output, no bare `cd`

```bash
# Good
if [[ -f "${config_file}" ]]; then
    log_info "Loading config from ${config_file}"
    source "${config_file}"
fi

# Bad
if [ -f $config_file ]; then
    echo "Loading $config_file"
    source $config_file
fi
```

### Python

- Formatted with **black** (no manual style decisions needed)
- All imports from the standard library; no third-party runtime dependencies
- Naming: `UPPER_SNAKE_CASE` for module-level constants, `lower_snake_case` for everything else

### Naming conventions

| Thing | Convention | Example |
|---|---|---|
| Stage scripts | `NN-stage-name.sh` | `02-build.sh` |
| Library scripts | `feature-utils.sh` | `logging-utils.sh` |
| Environment variables | `UPPER_SNAKE_CASE` | `BUILD_UID`, `TARGET_DIR` |
| Local shell variables | `lower_snake_case` | `jdk_home` |
| Shell functions (public) | `verb_noun` | `validate_workspace` |
| Shell functions (private) | `_verb_noun` | `_parse_json` |
