# Jenkins Workspace Cleanup Refactoring

## Overview

Refactored the Jenkins declarative pipeline to use native `cleanWs()` utility instead of custom shell scripts for workspace cleanup. This simplifies the pipeline and ensures consistent, reliable cleanup behavior across all stages.

## Changes Made

### 1. Pipeline Parameters

**Before:**
```groovy
booleanParam(
    name: 'CLEAN_WORKSPACE',
    defaultValue: true,
    description: 'Clean workspace before build'
)
```

**After:**
```groovy
booleanParam(
    name: 'CLEAN_WORKSPACE_AFTER_STAGE',
    defaultValue: true,
    description: 'Clean workspace after each stage (recommended for disk space management)'
)
```

### 2. Stage Structure

**Every stage now follows this pattern:**

```groovy
stage('Stage Name') {
    steps {
        script {
            // 1. Pre-cleanup: ALWAYS clean workspace (critical for restartability)
            cleanWs()

            // 2. Checkout repository (needed after cleanup)
            checkout scm

            // 3. Copy artifacts from previous stages
            copyArtifacts(...)

            // 4. Execute stage logic
            def stageScript = load 'scripts/stages/XX-stage-name.groovy'
            stageScript(config)

            // 5. Archive outputs
            archiveArtifacts(...)

            // 6. Post-cleanup: Clean if CLEAN_WORKSPACE_AFTER_STAGE=true
            if (params.CLEAN_WORKSPACE_AFTER_STAGE) {
                cleanWs()
            }
        }
    }
}
```

### 3. Removed Custom Helper Function

**Removed:**
```groovy
def cleanupWorkspace(String cleanupType) {
    sh """
        export WORKSPACE="${env.WORKSPACE}"
        export CONFIG_FILE="${env.WORKSPACE}/pipeline-config.json"
        export CLEANUP_TYPE="${cleanupType}"
        bash scripts/lib/workspace-cleanup.sh
    """
}
```

This function is no longer needed as we use Jenkins' native `cleanWs()` directly.

### 4. Updated Post Section

**Before:**
```groovy
post {
    always {
        script {
            def config = readJSON file: 'pipeline-config.json'
            if (config.parameters.cleanWorkspaceAfter) {
                cleanWs()
            }
        }
    }
}
```

**After:**
```groovy
post {
    always {
        script {
            // Final cleanup using parameter
            if (params.CLEAN_WORKSPACE_AFTER_STAGE) {
                node(getNodeLabel()) {
                    cleanWs notFailBuild: true, deleteDirs: true
                }
            }
        }
    }
}
```

## Stages Updated

All stages now include pre and post cleanup:

1. ✅ Initialize
2. ✅ Build
3. ✅ Internal Sign
4. ✅ Assemble
5. ✅ Build Installers
6. ✅ Sign Installers
7. ✅ GPG Sign
8. ✅ Verify Signing
9. ✅ Validate SBOM
10. ✅ Smoke Tests
11. ✅ AQA Tests
12. ✅ TCK Tests

## Benefits

### 1. **Restartability**
- Pre-cleanup ensures clean state when restarting from any stage
- Stages can run on different nodes without workspace pollution
- Consistent behavior on first run and restart

### 2. **Simplicity**
- Uses Jenkins native `cleanWs()` utility
- No custom shell scripts to maintain
- Clear, declarative syntax

### 3. **Reliability**
- Jenkins handles cleanup errors gracefully
- `notFailBuild: true` prevents cleanup failures from failing the build
- `deleteDirs: true` ensures complete cleanup

### 4. **Flexibility**
- `CLEAN_WORKSPACE_AFTER_STAGE` parameter allows users to control disk space management
- Default `true` recommended for most cases
- Can be set to `false` for debugging or disk space optimization

## Migration Notes

### For Jenkins Users

1. **Parameter Change**: Update any job configurations or scripts that reference `CLEAN_WORKSPACE` to use `CLEAN_WORKSPACE_AFTER_STAGE`

2. **Behavior Change**:
   - Pre-cleanup now ALWAYS happens (no configuration option)
   - Post-cleanup is controlled by `CLEAN_WORKSPACE_AFTER_STAGE` parameter

3. **Restart Behavior**: When restarting from a stage, the workspace will be cleaned before that stage executes

### For Local run-pipeline.py Users

The `workspace-cleanup.sh` script is still used by `run-pipeline.py` for local execution. No changes needed for local development.

## Configuration File Changes

The `load-json-config.py` script already uses the correct parameter name:

```python
'parameters': {
    'enableTests': enable_tests,
    'enableInstallers': enable_installers,
    'enableSigner': enable_signer,
    'cleanWorkspaceAfterStage': platform_config.get('cleanWorkspaceAfterBuild', True)
}
```

## Testing Recommendations

1. **Test Normal Execution**: Run a complete pipeline to verify all stages work correctly
2. **Test Restart**: Restart from various stages to verify pre-cleanup works
3. **Test with Cleanup Disabled**: Set `CLEAN_WORKSPACE_AFTER_STAGE=false` to verify post-cleanup is skipped
4. **Test on Different Nodes**: Verify stages can run on different nodes without issues

## Troubleshooting

### Issue: Workspace not clean after restart
**Solution**: This is expected behavior. Pre-cleanup happens at the START of each stage, so the workspace from the previous run will be present until the restarted stage begins.

### Issue: Disk space issues
**Solution**: Ensure `CLEAN_WORKSPACE_AFTER_STAGE=true` (default). This cleans up after each stage to free disk space.

### Issue: Need to inspect workspace after stage
**Solution**: Set `CLEAN_WORKSPACE_AFTER_STAGE=false` temporarily to preserve workspace contents for debugging.

## Related Documentation

- [RESTARTABILITY_GUIDE.md](./RESTARTABILITY_GUIDE.md) - Guide to restartable pipelines
- [WORKSPACE_ARTIFACTS_ARCHITECTURE.md](../WORKSPACE_ARTIFACTS_ARCHITECTURE.md) - Workspace and artifacts separation architecture

## Implementation Date

2026-05-18

## Author

Bob AI Assistant