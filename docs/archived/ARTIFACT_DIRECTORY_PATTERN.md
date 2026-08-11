# Artifact Directory Pattern: INPUT_ARTIFACTS_DIR vs TARGET_DIR

> **This document is historical.** The `INPUT_ARTIFACTS_DIR` / `TARGET_DIR` contract is now documented in [WORKSPACE_ARTIFACTS_ARCHITECTURE.md](../WORKSPACE_ARTIFACTS_ARCHITECTURE.md). The "Local Pipeline Execution" section of this document describes the old shared `artifacts/` model which has been superseded by the `build_artifacts/` archive/restore architecture.

## Overview

The pipeline uses a clear separation between input and output artifact directories to support restartable stages and proper artifact flow management.

## Directory Variables

### INPUT_ARTIFACTS_DIR
- **Purpose**: Directory where a stage reads input artifacts from previous stages
- **Usage**: Read-only access to artifacts produced by upstream stages
- **Set by**: Pipeline infrastructure before stage execution
- **Examples**:
  - SBOM files from build stage
  - JDK artifacts for smoke testing
  - Built JDK for reproducible comparison
  - Artifacts to be signed

### TARGET_DIR
- **Purpose**: Directory where a stage writes its output artifacts
- **Usage**: Write location for artifacts produced by the current stage
- **Set by**: Pipeline infrastructure before stage execution
- **Examples**:
  - Built JDK and SBOM files
  - Signed artifacts
  - Installer packages
  - Test results

## Pattern by Execution Environment

### Jenkins Pipeline Execution

In Jenkins, stages use **different directories** for input and output to support restartability:

```groovy
// Example: Validate SBOM stage
environment {
    INPUT_ARTIFACTS_DIR = "${WORKSPACE}/stage_input_artifacts"
    TARGET_DIR = "${WORKSPACE}/sbom_validation_output"
    CONFIG_FILE = "${INPUT_ARTIFACTS_DIR}/pipeline-config.json"
}

steps {
    script {
        initializeStage(
            'Validate SBOM',
            ['Build'],
            'pipeline-config.json,**/*.json',
            "${INPUT_ARTIFACTS_DIR}"  // Copy artifacts here
        )
    }
    sh 'scripts/stages/12-validate-sbom.sh'
}
```

**Flow**:
1. `initializeStage()` copies artifacts from previous build to `INPUT_ARTIFACTS_DIR`
2. Stage script reads from `INPUT_ARTIFACTS_DIR`
3. Stage script writes results to `TARGET_DIR`
4. Jenkins archives artifacts from `TARGET_DIR`

### Local Pipeline Execution

In local runs via [`run-pipeline.py`](../ci/local/run-pipeline.py), stages use the **same directory** for both input and output:

```python
# Example: Validate SBOM stage
env['INPUT_ARTIFACTS_DIR'] = str(self.artifacts_dir)
env['TARGET_DIR'] = str(self.artifacts_dir)
```

**Flow**:
1. All stages share the same `artifacts_dir`
2. Stage reads from `INPUT_ARTIFACTS_DIR` (artifacts_dir)
3. Stage writes to `TARGET_DIR` (artifacts_dir)
4. Artifacts accumulate in the shared directory

**Rationale**: Local runs don't need stage isolation since they run sequentially without restartability requirements.

## Stage-Specific Patterns

### Build Stage (First Stage)

**Jenkins**:
```groovy
environment {
    TARGET_DIR = "${WORKSPACE}/build_output"
    // No INPUT_ARTIFACTS_DIR - first stage
}
```

**Local**:
```python
env['TARGET_DIR'] = str(self.artifacts_dir)
# No INPUT_ARTIFACTS_DIR needed
```

**Reason**: Build stage is the first stage and produces initial artifacts, so it only needs an output directory.

### Intermediate Stages

**Jenkins**:
```groovy
environment {
    INPUT_ARTIFACTS_DIR = "${WORKSPACE}/stage_input_artifacts"
    TARGET_DIR = "${WORKSPACE}/sign_output"
    CONFIG_FILE = "${INPUT_ARTIFACTS_DIR}/pipeline-config.json"
}
```

**Local**:
```python
env['INPUT_ARTIFACTS_DIR'] = str(self.artifacts_dir)
env['TARGET_DIR'] = str(self.artifacts_dir)
env['CONFIG_FILE'] = str(self.artifacts_dir / 'pipeline-config.json')
```

**Stages using this pattern**:
- Validate SBOM ([`12-validate-sbom.sh`](../scripts/stages/12-validate-sbom.sh))
- Sign ([`06-sign.sh`](../scripts/stages/06-sign.sh))
- Installer ([`07-installer.sh`](../scripts/stages/07-installer.sh))
- Smoke Tests ([`13-smoke-tests.sh`](../scripts/stages/13-smoke-tests.sh))
- Reproducible Compare ([`20-reproducible-compare.sh`](../scripts/stages/20-reproducible-compare.sh))

## Stage Script Implementation

Stage scripts must use these variables correctly:

```bash
#!/bin/bash
set -euo pipefail

# Read input artifacts
INPUT_ARTIFACTS_DIR="${INPUT_ARTIFACTS_DIR:?INPUT_ARTIFACTS_DIR must be set}"
JDK_ARTIFACT=$(find "$INPUT_ARTIFACTS_DIR" -name "*.tar.gz" | head -1)

# Write output artifacts
TARGET_DIR="${TARGET_DIR:?TARGET_DIR must be set}"
mkdir -p "$TARGET_DIR"
cp result.txt "$TARGET_DIR/"
```

### Key Principles

1. **Always validate variables**: Use `${VAR:?error message}` to ensure variables are set
2. **Read from INPUT_ARTIFACTS_DIR**: All input artifacts come from this directory
3. **Write to TARGET_DIR**: All output artifacts go to this directory
4. **Never assume directory structure**: Use the provided variables, don't hardcode paths
5. **CONFIG_FILE location**: Always read from `${INPUT_ARTIFACTS_DIR}/pipeline-config.json`

## Benefits

### Restartability
- Each stage has isolated input/output directories in Jenkins
- Failed stages can be restarted without affecting other stages
- Previous stage artifacts are preserved in their output directories

### Clarity
- Clear separation between what a stage reads vs writes
- Easy to understand artifact flow through the pipeline
- Simplified debugging of artifact issues

### Flexibility
- Same stage scripts work in both Jenkins and local environments
- Different execution patterns (isolated vs shared) without script changes
- Easy to add new stages following the same pattern

## Migration Notes

### From Old Pattern (TARGET_DIR only)

**Before**:
```bash
TARGET_DIR="${TARGET_DIR:?TARGET_DIR must be set}"
JDK_ARTIFACT=$(find "$TARGET_DIR" -name "*.tar.gz")
cp result.txt "$TARGET_DIR/"
```

**After**:
```bash
INPUT_ARTIFACTS_DIR="${INPUT_ARTIFACTS_DIR:?INPUT_ARTIFACTS_DIR must be set}"
TARGET_DIR="${TARGET_DIR:?TARGET_DIR must be set}"
JDK_ARTIFACT=$(find "$INPUT_ARTIFACTS_DIR" -name "*.tar.gz")
cp result.txt "$TARGET_DIR/"
```

### Actual Jenkinsfile Pattern

Stages set `env.TARGET_DIR` and pass `inputArtifactsDir` to `initializeStage()`:

```groovy
pipelineHelper.executeStageWithTracking('My Stage') {
    def config = pipelineHelper.initializeStage(
        'My Stage',
        ['Build'],
        'pipeline-config.json,**/*.tar.gz',
        "${WORKSPACE}/stage_input_artifacts"   // → INPUT_ARTIFACTS_DIR
    )
    env.TARGET_DIR = "${WORKSPACE}/my_stage_output"

    def exitCode = stageRunner.run('NN-my-stage', config)
    if (exitCode != 0) { error("My Stage failed") }

    dir(env.TARGET_DIR) {
        archiveArtifacts artifacts: '**/*', allowEmptyArchive: true
    }
    pipelineHelper.finalizeStage('My Stage')
}
```

## Related Documentation

- [`WORKSPACE_ARTIFACTS_ARCHITECTURE.md`](../WORKSPACE_ARTIFACTS_ARCHITECTURE.md) — current documentation (supersedes this document)
- [`UNIVERSAL_STAGE_PATTERN.md`](../UNIVERSAL_STAGE_PATTERN.md) — stage script template
- [`ci/jenkins/lib/PipelineHelper.groovy`](../ci/jenkins/lib/PipelineHelper.groovy) — `initializeStage()` implementation
- [`ci/local/run-pipeline.py`](../ci/local/run-pipeline.py) — local execution tool

## Examples


### Complete Stage Example (Local)

```python
def stage_sign(self):
    """Stage 3: Sign Artifacts"""
    print("\n" + "=" * 80)
    print("STAGE 3: Sign Artifacts")
    print("=" * 80)

    # Pre-stage cleanup
    self.workspace_mgr.cleanup_stage_workspace('pre')

    env = os.environ.copy()
    env['WORKSPACE'] = str(self.stage_workspace)
    env['CONFIG_FILE'] = str(self.config_file)
    env['BUILD_NUMBER'] = self.build_number
    env['INPUT_ARTIFACTS_DIR'] = str(self.artifacts_dir)
    env['TARGET_DIR'] = str(self.artifacts_dir)

    cmd = [str(self.script_dir / 'scripts' / 'stages' / '06-sign.sh')]

    print(f"Running: {' '.join(cmd)}")
    print(f"Environment:")
    print(f"  WORKSPACE={env['WORKSPACE']} (stage_workspace)")
    print(f"  INPUT_ARTIFACTS_DIR={env['INPUT_ARTIFACTS_DIR']} (input)")
    print(f"  TARGET_DIR={env['TARGET_DIR']} (output)")

    subprocess.run(cmd, env=env, check=True)
    print("\n✅ Sign stage complete")

    # Post-stage cleanup
    self.workspace_mgr.cleanup_stage_workspace('post')
```

## Troubleshooting

### Stage can't find input artifacts

**Problem**: Stage script fails with "No such file or directory" when looking for input artifacts.

**Solution**: 
1. Check that `INPUT_ARTIFACTS_DIR` is set correctly
2. Verify previous stage archived the expected artifacts
3. Check `initializeStage()` artifact filter pattern
4. Ensure stage prerequisites list includes the producing stage

### Artifacts not appearing in Jenkins

**Problem**: Stage completes but artifacts don't appear in Jenkins.

**Solution**:
1. Verify stage writes to `TARGET_DIR`, not `INPUT_ARTIFACTS_DIR`
2. Check `archiveArtifacts` pattern matches files in `TARGET_DIR`
3. Ensure `TARGET_DIR` directory exists before writing
4. Check Jenkins console output for archiving errors

### Local run fails but Jenkins succeeds

**Problem**: Stage works in Jenkins but fails in local run.

**Solution**:
1. Verify stage script uses both `INPUT_ARTIFACTS_DIR` and `TARGET_DIR`
2. Check that script doesn't assume different directories
3. Ensure script handles case where both variables point to same directory
4. Test with `run-pipeline.py` to reproduce the issue

## Summary

The INPUT_ARTIFACTS_DIR vs TARGET_DIR pattern provides:
- ✅ Clear separation of stage inputs and outputs
- ✅ Support for restartable stages in Jenkins
- ✅ Simplified artifact flow management
- ✅ Consistent pattern across all stages
- ✅ Works in both Jenkins and local environments
- ✅ Easy to understand and maintain