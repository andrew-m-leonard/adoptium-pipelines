# Local Runner Workspace Architecture

> **This document is historical.** The local runner now uses a three-directory architecture (`stage_workspace/`, `build_artifacts/`, `config-repo/`) with explicit archive and restore semantics that mirror Jenkins precisely. See [WORKSPACE_ARTIFACTS_ARCHITECTURE.md](../WORKSPACE_ARTIFACTS_ARCHITECTURE.md) for current documentation.

## Overview

The local pipeline runner (`ci/local/run-pipeline.py`) uses a two-directory architecture to separate ephemeral stage workspaces from persistent artifacts, similar to how Jenkins separates workspace from archived artifacts.

## Directory Structure

```
PIPELINE_WORKSPACE/
├── pipeline-config.json          # Pipeline configuration
├── stage_workspace/              # Ephemeral - cleaned before/after each stage
│   └── (stage working files)
└── artifacts/                    # Persistent - preserved between stages
    └── (stage outputs)
```

### Directory Purposes

1. **`PIPELINE_WORKSPACE`**: Root directory containing all pipeline data
   - Specified via `--workspace` parameter
   - Example: `~/openjdk-build`

2. **`stage_workspace/`**: Ephemeral working directory
   - Cleaned BEFORE every stage (pre-cleanup)
   - Optionally cleaned AFTER every stage (post-cleanup)
   - Used for temporary files during stage execution
   - Never persists between stages

3. **artifacts/`**: Persistent artifact storage
   - Acts like Jenkins' artifact store
   - Preserves outputs between stages
   - Never automatically cleaned
   - Stages copy inputs from here and outputs to here

## Workspace Validation Rules

### Fresh Build (no `--start-from-stage`)

| Condition | `--clean-workspace` | Result |
|-----------|---------------------|--------|
| Workspace doesn't exist | Not specified | ✅ Create workspace structure |
| Workspace doesn't exist | Specified | ✅ Create workspace structure |
| Workspace exists | Not specified | ❌ **ERROR**: Must use `--clean-workspace` or `--start-from-stage` |
| Workspace exists | Specified | ✅ Clean entire workspace, then create structure |

### Restart from Stage (`--start-from-stage <stage>`)

| Condition | `--clean-workspace` | Result |
|-----------|---------------------|--------|
| Workspace doesn't exist | Not specified | ❌ **ERROR**: Workspace must exist for restart |
| Workspace doesn't exist | Specified | ❌ **ERROR**: Option conflict |
| Workspace exists | Not specified | ✅ Use existing workspace |
| Workspace exists | Specified | ❌ **ERROR**: Option conflict - can't clean when restarting |

## Cleanup Behavior

### Pre-Cleanup (Before Every Stage)
- **Always runs** - no configuration option
- Cleans entire `stage_workspace/` directory
- Critical for restartability on same machine
- Ensures clean state for each stage

### Post-Cleanup (After Every Stage)
- Controlled by `cleanWorkspaceAfterStage` parameter (default: `true`)
- Cleans `stage_workspace/` directory if enabled
- Helps manage disk space
- Can be disabled for debugging

## Stage Workflow Pattern

Every stage follows this pattern:

```python
def stage_example(self):
    """Example stage implementation"""

    # 1. Pre-cleanup: Clean stage_workspace
    self.cleanup_stage_workspace('pre')

    # 2. Copy inputs from artifacts/ to stage_workspace/
    # (if needed from previous stages)

    # 3. Execute stage logic in stage_workspace/
    # ...

    # 4. Move outputs from stage_workspace/ to artifacts/
    # (before post-cleanup!)

    # 5. Post-cleanup: Clean stage_workspace if configured
    self.cleanup_stage_workspace('post')
```

## Example Usage

### Fresh Build
```bash
# First time - workspace doesn't exist
python3 run-pipeline.py \
    --jdk-version jdk21u \
    --variant temurin \
    --target-os mac \
    --architecture aarch64 \
    --workspace ~/openjdk-build

# Workspace exists from previous run - must clean
python3 run-pipeline.py \
    --jdk-version jdk21u \
    --variant temurin \
    --target-os mac \
    --architecture aarch64 \
    --workspace ~/openjdk-build \
    --clean-workspace
```

### Restart from Stage
```bash
# Restart from build stage (workspace must exist)
python3 run-pipeline.py \
    --jdk-version jdk21u \
    --variant temurin \
    --target-os mac \
    --architecture aarch64 \
    --workspace ~/openjdk-build \
    --start-from-stage build

# ERROR: Can't clean workspace when restarting
python3 run-pipeline.py \
    --workspace ~/openjdk-build \
    --start-from-stage build \
    --clean-workspace  # ❌ Option conflict!
```

## Error Messages

### Workspace Exists Without Clean Flag
```
ERROR: Workspace already exists: /Users/user/openjdk-build

For a fresh build, you must either:
  1. Use --clean-workspace to clean the existing workspace
  2. Use --start-from-stage <stage> to restart from a specific stage
  3. Manually remove the workspace directory

This ensures workspace cleanliness and prevents pollution from previous runs.
```

### Restart Without Existing Workspace
```
ERROR: Cannot restart from stage 'build' - workspace does not exist: /Users/user/openjdk-build

When restarting from a stage, the workspace must exist with artifacts from previous stages.
Run a full build first (without --start-from-stage) to create the workspace.
```

### Option Conflict
```
ERROR: Option conflict - cannot use --clean-workspace with --start-from-stage

When restarting from a stage, the workspace must be preserved to access
artifacts from previous stages. Remove --clean-workspace to continue.
```

## Comparison with Jenkins

| Aspect | Local Runner | Jenkins |
|--------|-------------|---------|
| **Ephemeral workspace** | `stage_workspace/` | `${WORKSPACE}` (cleaned by `cleanWs()`) |
| **Persistent artifacts** | `artifacts/` | Jenkins artifact store (archiveArtifacts) |
| **Pre-cleanup** | Always clean `stage_workspace/` | Always `cleanWs()` |
| **Post-cleanup** | Optional clean `stage_workspace/` | Optional `cleanWs()` |
| **Artifact transfer** | File copy between directories | `archiveArtifacts` + `copyArtifacts` |
| **Restartability** | Workspace validation + cleanup | Native stage restart + cleanup |

## Benefits

1. **Restartability**: Clean stage workspace ensures consistent state when restarting
2. **Artifact Preservation**: Persistent artifacts directory acts like Jenkins artifact store
3. **Disk Space Management**: Optional post-cleanup helps manage disk usage
4. **Error Prevention**: Strict validation prevents accidental workspace pollution
5. **CI Parity**: Similar behavior to Jenkins declarative pipeline

## Implementation Details

### Workspace Initialization
```python
# Pipeline workspace is the root directory
self.pipeline_workspace = Path(args.workspace).expanduser().resolve()

# Stage workspace is ephemeral
self.stage_workspace = self.pipeline_workspace / 'stage_workspace'

# Artifacts directory persists
self.artifacts_dir = self.pipeline_workspace / 'artifacts'
```

### Cleanup Implementation
```python
def cleanup_stage_workspace(self, cleanup_type):
    """Clean the ephemeral stage_workspace directory."""
    if cleanup_type == 'pre':
        # Always clean before stage
        shutil.rmtree(self.stage_workspace)
        self.stage_workspace.mkdir(parents=True)

    elif cleanup_type == 'post':
        # Clean after stage if configured
        config = read_config()
        if config['parameters']['cleanWorkspaceAfterStage']:
            shutil.rmtree(self.stage_workspace)
            self.stage_workspace.mkdir(parents=True)
```

## Related Documentation

- [WORKSPACE_ARTIFACTS_ARCHITECTURE.md](../WORKSPACE_ARTIFACTS_ARCHITECTURE.md) — Current workspace architecture documentation (supersedes this document)
- [ci/local/README.md](../ci/local/README.md) — Local runner full reference