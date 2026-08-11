# Contributing to Adoptium CI Pipelines

Thank you for your interest in contributing to the Adoptium CI Pipelines project! This document provides guidelines and instructions for contributing.

## Table of Contents

1. [Code of Conduct](#code-of-conduct)
2. [Getting Started](#getting-started)
3. [Development Workflow](#development-workflow)
4. [Testing Guidelines](#testing-guidelines)
5. [Commit Guidelines](#commit-guidelines)
6. [Pull Request Process](#pull-request-process)
7. [Architecture Guidelines](#architecture-guidelines)

---

## Code of Conduct

This project follows the [Adoptium Code of Conduct](https://github.com/adoptium/.github/blob/main/CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

---

## Getting Started

### Prerequisites

- **Shell**: Bash 4.0+ (macOS users may need to upgrade)
- **Python**: 3.8+ (for `run-pipeline.py` and utilities)
- **Git**: 2.20+
- **Optional**: Docker (for containerized builds)
- **Optional**: Jenkins (for CI testing)

### Repository Setup

```bash
# Clone the repository
git clone https://github.com/adoptium/ci-adoptium-pipelines.git
cd ci-adoptium-pipelines

# Make scripts executable
chmod +x scripts/**/*.sh
chmod +x tools/*.sh
chmod +x run-pipeline.py

# Verify setup
./run-pipeline.py --help
```

### Local Testing

See [`LOCAL_TESTING_GUIDE.md`](LOCAL_TESTING_GUIDE.md) for comprehensive local testing instructions.

Quick test:
```bash
# Test a single stage
./scripts/stages/01-initialize.sh

# Test full pipeline locally
python3 run-pipeline.py \
  --config configurations/jdk21u_pipeline_config.json \
  --platform x64Mac \
  --variant temurin
```

---

## Development Workflow

### 1. Create a Feature Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/issue-number-description
```

### 2. Make Changes

Follow the [Architecture Guidelines](#architecture-guidelines) below.

### 3. Test Locally

```bash
# Syntax check
bash -n scripts/stages/your-script.sh

# Linting
shellcheck scripts/stages/your-script.sh

# Unit tests (if applicable)
bats tests/test-your-feature.bats

# Integration test
python3 run-pipeline.py --config configurations/test-config.json
```

### 4. Commit Changes

Follow the [Commit Guidelines](#commit-guidelines) below.

### 5. Push and Create PR

```bash
git push origin feature/your-feature-name
```

Then create a Pull Request on GitHub.

---

## Testing Guidelines

### Test Pyramid

We follow a multi-level testing strategy:

#### Level 1: Syntax & Linting (Required)
```bash
# Check syntax
bash -n scripts/stages/*.sh

# Run shellcheck
shellcheck scripts/stages/*.sh scripts/lib/*.sh
```

#### Level 2: Unit Tests (Recommended)
```bash
# Run BATS tests
bats tests/
```

#### Level 3: Stage Tests (Required for stage changes)
```bash
# Test individual stage
./scripts/stages/01-initialize.sh
echo $?  # Should be 0 for success
```

#### Level 4: Local Pipeline (Required for major changes)
```bash
# Full pipeline test
python3 run-pipeline.py \
  --config configurations/jdk21u_pipeline_config.json \
  --platform x64Mac \
  --variant temurin
```

#### Level 5: CI Validation (Automatic)
- Jenkins will run parallel validation
- Both old and new pipelines execute
- Outputs compared with `repro_compare.sh`

### Test Requirements by Change Type

| Change Type | Required Tests |
|-------------|----------------|
| Documentation only | None |
| Configuration change | Level 1, 4 |
| Library script change | Level 1, 2, 3 |
| Stage script change | Level 1, 2, 3, 4 |
| Pipeline orchestration | Level 1, 4, 5 |
| Major refactoring | All levels |

---

## Commit Guidelines

### Commit Message Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types

- **feat**: New feature
- **fix**: Bug fix
- **docs**: Documentation only
- **style**: Code style changes (formatting, no logic change)
- **refactor**: Code refactoring (no feature change)
- **test**: Adding or updating tests
- **chore**: Maintenance tasks

### Examples

```
feat(stages): add smoke test for Java modules

Add comprehensive smoke tests for Java 9+ module system.
Tests verify module resolution, exports, and requires.

Closes #123
```

```
fix(build): correct JDK home detection on macOS

macOS JDK structure uses Contents/Home subdirectory.
Updated detection logic to handle both macOS and Linux.

Fixes #456
```

```
docs(migration): update timeline to 10-14 weeks

Accelerated migration timeline based on parallel
platform migrations and reduced validation periods.
```

### Commit Best Practices

- ✅ Keep commits atomic (one logical change per commit)
- ✅ Write clear, descriptive commit messages
- ✅ Reference issue numbers when applicable
- ✅ Separate subject from body with blank line
- ✅ Limit subject line to 50 characters
- ✅ Wrap body at 72 characters
- ❌ Don't commit generated files
- ❌ Don't commit credentials or secrets

---

## Pull Request Process

### Before Submitting

1. ✅ All tests pass locally
2. ✅ Code follows style guidelines
3. ✅ Documentation updated (if needed)
4. ✅ Commit messages follow guidelines
5. ✅ Branch is up to date with main

### PR Description Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] Syntax check passed
- [ ] Shellcheck passed
- [ ] Unit tests passed
- [ ] Stage tests passed
- [ ] Local pipeline test passed

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Documentation updated
- [ ] No new warnings introduced
- [ ] Tests added/updated

## Related Issues
Closes #123
```

### Review Process

1. **Automated Checks**: CI runs tests automatically
2. **Code Review**: At least one maintainer reviews
3. **Testing**: Parallel validation in Jenkins (for pipeline changes)
4. **Approval**: Maintainer approves PR
5. **Merge**: Squash and merge to main

### Review Criteria

Reviewers will check:
- ✅ Code quality and style
- ✅ Test coverage
- ✅ Documentation completeness
- ✅ Backward compatibility
- ✅ Performance impact
- ✅ Security considerations

---

## Architecture Guidelines

### 3-Layer Architecture

All changes must respect the 3-layer architecture:

```
Layer 1: Configuration (JSON)
  ↓
Layer 2: Build Logic (Shell Scripts - 90% CI-agnostic)
  ↓
Layer 3: Orchestration (CI-specific - 10%)
```

### Layer 1: Configuration

**Location**: `configurations/*.json`

**Guidelines**:
- ✅ Pure data (no logic)
- ✅ Valid JSON syntax
- ✅ Follow schema (if defined)
- ✅ Document new fields
- ❌ No embedded scripts
- ❌ No environment-specific values

**Example**:
```json
{
  "version": "jdk21u",
  "buildConfigurations": {
    "x64Linux": {
      "os": "linux",
      "arch": "x64"
    }
  }
}
```

### Layer 2: Build Logic

**Location**: `scripts/stages/*.sh`, `scripts/lib/*.sh`

**Guidelines**:
- ✅ Pure shell scripts (Bash 4.0+)
- ✅ CI-agnostic (no Jenkins/GitLab/GitHub-specific code)
- ✅ Clear input/output contracts
- ✅ Use TARGET_DIR for state
- ✅ Validate workspace (BUILD_UID pattern)
- ✅ Structured logging (use logging-utils.sh)
- ✅ Error handling (set -euo pipefail)
- ❌ No hardcoded paths
- ❌ No CI-specific APIs

**Stage Script Template**:
```bash
#!/bin/bash
set -euo pipefail

# Load utilities
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/logging-utils.sh"
source "${SCRIPT_DIR}/../lib/config-utils.sh"

# Validate workspace
validate_workspace || exit 1

# Load configuration
CONFIG=$(load_json_config)

# Read inputs from TARGET_DIR
INPUT_FILE="${TARGET_DIR}/previous-output.txt"

# Execute stage logic
log_info "Starting stage..."
perform_work

# Write outputs to TARGET_DIR
OUTPUT_FILE="${TARGET_DIR}/stage-output.txt"

log_info "Stage complete"
exit 0
```

### Layer 3: Orchestration

**Location**: `Jenkinsfile.declarative`, `.gitlab-ci.yml`, etc.

**Guidelines**:
- ✅ Minimal CI-specific code
- ✅ Call shell scripts (Layer 2)
- ✅ Handle CI-specific features (notifications, artifacts)
- ✅ Stage result tracking
- ❌ No business logic
- ❌ No inline shell snippets

**Jenkinsfile Pattern**:
```groovy
stage('Build') {
    steps {
        script {
            sh './scripts/stages/02-build.sh'
        }
    }
}
```

### File Organization

```
ci-adoptium-pipelines/
├── configurations/          # Layer 1: Data
│   └── *.json
├── scripts/                 # Layer 2: Logic
│   ├── lib/                 # Shared utilities
│   │   └── *.sh
│   └── stages/              # Stage implementations
│       └── *.sh
├── Jenkinsfile.*            # Layer 3: Jenkins
├── .gitlab-ci.yml           # Layer 3: GitLab
├── .github/workflows/       # Layer 3: GitHub Actions
└── docs/                    # Documentation
```

### Naming Conventions

**Files**:
- Stage scripts: `##-stage-name.sh` (e.g., `01-initialize.sh`)
- Library scripts: `feature-utils.sh` (e.g., `logging-utils.sh`)
- Configurations: `jdk##u_pipeline_config.json`

**Variables**:
- Environment: `UPPER_SNAKE_CASE` (e.g., `BUILD_UID`, `TARGET_DIR`)
- Local: `lower_snake_case` (e.g., `jdk_home`, `config_file`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `SCRIPT_DIR`)

**Functions**:
- Public: `verb_noun` (e.g., `validate_workspace`, `load_config`)
- Private: `_verb_noun` (e.g., `_parse_json`, `_check_file`)

### Code Style

**Shell Scripts**:
```bash
# Good
if [[ -f "${file}" ]]; then
    log_info "Processing ${file}"
    process_file "${file}"
fi

# Bad
if [ -f $file ]
then
    echo "Processing $file"
    process_file $file
fi
```

**Best Practices**:
- ✅ Use `[[ ]]` instead of `[ ]`
- ✅ Quote variables: `"${var}"`
- ✅ Use `$(command)` instead of backticks
- ✅ Check exit codes: `command || handle_error`
- ✅ Use functions for reusable code
- ✅ Add comments for complex logic
- ❌ Don't use `eval`
- ❌ Don't parse `ls` output
- ❌ Don't use `cd` without error handling

---

## Documentation

### Required Documentation

When making changes, update relevant documentation:

- **README.md**: Overview and quick start
- **Architecture docs**: For architectural changes
- **Migration docs**: For migration-related changes
- **Testing guides**: For new testing procedures
- **API docs**: For new functions/utilities

### Documentation Style

- Use clear, concise language
- Include code examples
- Add diagrams for complex concepts
- Keep table of contents updated
- Link to related documentation

---

## Getting Help

- **Issues**: [GitHub Issues](https://github.com/adoptium/ci-adoptium-pipelines/issues)
- **Discussions**: [GitHub Discussions](https://github.com/adoptium/ci-adoptium-pipelines/discussions)
- **Slack**: [Adoptium Slack](https://adoptium.net/slack)
- **Mailing List**: [adoptium-dev](https://mail.openjdk.org/mailman/listinfo/adoptium-dev)

---

## License

By contributing, you agree that your contributions will be licensed under the same license as the project (Apache License 2.0).

---

Thank you for contributing to Adoptium CI Pipelines! 🎉