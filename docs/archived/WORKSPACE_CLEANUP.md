# Workspace Cleanup System

## Overview

The workspace cleanup system provides configurable pre-stage and post-stage cleanup of workspace directories based on configuration parameters. This ensures clean builds and prevents pollution from previous runs while allowing flexibility through configuration.

## Configuration Parameters

The cleanup behavior is controlled by two parameters in the pipeline configuration:

```json
{
  "parameters": {
    "cleanWorkspace": true,
    "cleanWorkspaceAfter": false
  }
}
```

### cleanWorkspace

- **Type**: Boolean
- **Default**: `true`
- **Description**: Clean stage-specific workspace directories **before** each stage executes
- **Use Case**: Ensures fresh start for each stage, prevents pollution from previous runs

### cleanWorkspaceAfter

- **Type**: Boolean
- **Default**: `false`
- **Description**: Clean stage-specific workspace directories **after** each stage completes
- **Use Case**: Free up disk space immediately after stage completion, useful for space-constrained environments

## Stage-Specific Directories

Each stage has its own workspace directory that gets cleaned:

| Stage | Directory | Contents |
|-------|-----------|----------|
| `build` | `${WORKSPACE}/workspace/build` | Build artifacts, intermediate files |
| `sign` | `${WORKSPACE}/workspace/sign` | Signing workspace |
| `installer` | `${WORKSPACE}/workspace/installer` | Installer build workspace |
| `smoke-tests` | `${WORKSPACE}/workspace/test-results` | Test results and logs |
| `reproducible-compare` | `${WORKSPACE}/reproducible-compare` | Comparison workspace, downloaded binaries |

**Note**: The shared artifact directory `${WORKSPACE}/workspace/target` is **never** cleaned automatically, as it contains artifacts that need to persist across stages.

## Implementation

### Bash Utility Script

The cleanup logic is implemented in [`scripts/lib/workspace-cleanup.sh`](../scripts/lib/workspace-cleanup.sh):

```bash
#!/bin/bash
# Usage:
export WORKSPACE="/path/to/workspace"
export CONFIG_FILE="/path/to/pipeline-config.json"
export STAGE_NAME="build"  # or sign, installer, smoke-tests, reproducible-compare
export CLEANUP_TYPE="pre"  # or post

bash scripts/lib/workspace-cleanup.sh
```

The script:
1. Reads configuration parameters from `pipeline-config.json`
2. Determines if cleanup should be performed based on `CLEANUP_TYPE` and config
3. Identifies stage-specific directories to clean
4. Removes directories if they exist
5. Logs all actions

### Python Integration (run-pipeline.py)

The local pipeline runner integrates cleanup via the `cleanup_workspace()` method:

```python
def cleanup_workspace(self, stage_name, cleanup_type):
    """
    Run workspace cleanup for a stage.

    Args:
        stage_name: Name of the stage (e.g., 'build', 'sign')
        cleanup_type: Either 'pre' or 'post'
    """
    env = os.environ.copy()
    env['WORKSPACE'] = str(self.workspace)
    env['CONFIG_FILE'] = str(self.config_file)
    env['STAGE_NAME'] = stage_name
    env['CLEANUP_TYPE'] = cleanup_type

    cleanup_script = self.script_dir / 'scripts' / 'lib' / 'workspace-cleanup.sh'
    subprocess.run([str(cleanup_script)], env=env, check=True)
```

Each stage method calls cleanup before and after execution:

```python
def stage_build(self):
    """Stage 2: Build OpenJDK"""
    # Pre-stage cleanup
    self.cleanup_workspace('build', 'pre')

    # ... stage execution ...

    # Post-stage cleanup
    self.cleanup_workspace('build', 'post')
```

### Jenkins Integration (Jenkinsfile.declarative)

The Jenkinsfile provides a helper function:

```groovy
/**
 * Run workspace cleanup for a stage
 */
def cleanupWorkspace(String stageName, String cleanupType) {
    sh """
        export WORKSPACE="${env.WORKSPACE}"
        export CONFIG_FILE="${env.WORKSPACE}/pipeline-config.json"
        export STAGE_NAME="${stageName}"
        export CLEANUP_TYPE="${cleanupType}"
        bash scripts/lib/workspace-cleanup.sh
    """
}
```

Each stage calls cleanup before and after execution:

```groovy
stage('Build') {
    steps {
        script {
            // Retrieve configuration
            copyArtifacts(...)
            def config = readJSON file: 'pipeline-config.json'

            // Pre-stage cleanup
            cleanupWorkspace('build', 'pre')

            // Execute stage
            def buildScript = load 'scripts/stages/02-build.groovy'
            buildScript(config)

            // Post-stage cleanup
            cleanupWorkspace('build', 'post')
        }
    }
}
```

## Usage Examples

### Example 1: Default Behavior (Clean Before, Keep After)

```json
{
  "parameters": {
    "cleanWorkspace": true,
    "cleanWorkspaceAfter": false
  }
}
```

**Behavior**:
- Before each stage: Clean stage-specific workspace
- After each stage: Keep workspace for debugging/inspection
- **Use Case**: Development, debugging, troubleshooting

### Example 2: Aggressive Cleanup (Clean Before and After)

```json
{
  "parameters": {
    "cleanWorkspace": true,
    "cleanWorkspaceAfter": true
  }
}
```

**Behavior**:
- Before each stage: Clean stage-specific workspace
- After each stage: Clean stage-specific workspace
- **Use Case**: Production builds, space-constrained environments

### Example 3: No Cleanup (Keep Everything)

```json
{
  "parameters": {
    "cleanWorkspace": false,
    "cleanWorkspaceAfter": false
  }
}
```

**Behavior**:
- Before each stage: Keep existing workspace
- After each stage: Keep workspace
- **Use Case**: Incremental builds, debugging, manual workspace management

### Example 4: Clean Only After (Unusual)

```json
{
  "parameters": {
    "cleanWorkspace": false,
    "cleanWorkspaceAfter": true
  }
}
```

**Behavior**:
- Before each stage: Keep existing workspace
- After each stage: Clean stage-specific workspace
- **Use Case**: Rare, possibly for specific debugging scenarios

## Configuration Sources

The cleanup parameters can be set in multiple ways:

### 1. Platform Configuration Files

In `configurations/jdkNN_pipeline_config.json`:

```json
{
  "buildConfigurations": {
    "x64Mac": {
      "cleanWorkspaceAfterBuild": false
    }
  }
}
```

The `load-json-config.py` script reads `cleanWorkspaceAfterBuild` from platform config and maps it to `cleanWorkspaceAfter` in the generated configuration.

### 2. Generated Configuration

The `load-json-config.py` script generates:

```json
{
  "parameters": {
    "cleanWorkspace": true,
    "cleanWorkspaceAfter": false
  }
}
```

### 3. Command-Line Override (Future Enhancement)

Could add command-line flags to `run-pipeline.py`:

```bash
python3 run-pipeline.py \
    --jdk-version jdk21u \
    --variant temurin \
    --target-os mac \
    --architecture aarch64 \
    --no-clean-workspace \
    --clean-workspace-after
```

## Logging

The cleanup utility provides clear logging:

```
================================================================================
Pre-stage cleanup: build
================================================================================
ℹ️  Removing: /Users/user/workspace/workspace/build
✅ Cleaned 1 director(ies)
```

When cleanup is disabled:

```
ℹ️  Pre-stage cleanup disabled for stage: build
```

When directory doesn't exist:

```
ℹ️  Directory does not exist (skipping): /Users/user/workspace/workspace/build
ℹ️  No directories to clean
```

## Troubleshooting

### Issue: Cleanup Not Running

**Symptoms**: Directories not being cleaned despite `cleanWorkspace: true`

**Diagnosis**:
1. Check configuration file exists: `cat pipeline-config.json`
2. Verify parameters: `jq '.parameters' pipeline-config.json`
3. Check script permissions: `ls -l scripts/lib/workspace-cleanup.sh`
4. Run script manually with debug:
   ```bash
   export WORKSPACE="$PWD"
   export CONFIG_FILE="$PWD/pipeline-config.json"
   export STAGE_NAME="build"
   export CLEANUP_TYPE="pre"
   bash -x scripts/lib/workspace-cleanup.sh
   ```

### Issue: Permission Denied

**Symptoms**: `rm: cannot remove 'directory': Permission denied`

**Solution**:
- Check file ownership: `ls -la workspace/`
- Fix permissions: `chmod -R u+w workspace/`
- Check for locked files: `lsof +D workspace/`

### Issue: Disk Space Not Freed

**Symptoms**: Disk space not freed after `cleanWorkspaceAfter: true`

**Diagnosis**:
- Verify cleanup ran: Check logs for "Post-stage cleanup"
- Check for open file handles: `lsof +D workspace/`
- Verify directories removed: `ls -la workspace/`

## Best Practices

1. **Development**: Use `cleanWorkspace: true, cleanWorkspaceAfter: false`
   - Allows inspection of artifacts after build
   - Easier debugging

2. **Production**: Use `cleanWorkspace: true, cleanWorkspaceAfter: true`
   - Minimizes disk usage
   - Prevents workspace pollution

3. **Debugging**: Use `cleanWorkspace: false, cleanWorkspaceAfter: false`
   - Preserves all artifacts
   - Allows manual inspection

4. **CI/CD**: Use `cleanWorkspace: true, cleanWorkspaceAfter: false`
   - Clean start for each build
   - Artifacts available for archiving

## Future Enhancements

1. **Selective Cleanup**: Clean only specific subdirectories
2. **Retention Policy**: Keep last N builds
3. **Size-Based Cleanup**: Clean when workspace exceeds size threshold
4. **Time-Based Cleanup**: Clean workspaces older than N days
5. **Parallel Cleanup**: Clean multiple directories concurrently

## References

- [workspace-cleanup.sh](../scripts/lib/workspace-cleanup.sh) - Cleanup utility script
- [run-pipeline.py](../ci/local/run-pipeline.py) - Local pipeline runner
- [Jenkinsfile.declarative](../ci/jenkins/Jenkinsfile.declarative) - Jenkins pipeline
- [load-json-config.py](../scripts/lib/load-json-config.py) - Configuration generator