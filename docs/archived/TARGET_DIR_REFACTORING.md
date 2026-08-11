# TARGET_DIR Refactoring

## Overview

This document explains the refactoring from separate `INPUT_DIR` and `OUTPUT_DIR` variables to a single `TARGET_DIR` variable across all pipeline stages.

## Motivation

### Previous Approach (INPUT_DIR/OUTPUT_DIR)
```bash
# Stage 1: Build
OUTPUT_DIR=/workspace/target  # Write artifacts here

# Stage 2: Sign
INPUT_DIR=/workspace/target   # Read artifacts from here
OUTPUT_DIR=/workspace/target  # Write signed artifacts back here

# Stage 3: Installer
INPUT_DIR=/workspace/target   # Read signed artifacts
OUTPUT_DIR=/workspace/target  # Write installers here
```

**Problems:**
1. **Confusing**: Having separate INPUT_DIR and OUTPUT_DIR set to the same directory is misleading
2. **Redundant**: All stages use the same directory for both input and output
3. **Unclear Intent**: Doesn't clearly communicate that all stages share a common artifact directory

### New Approach (TARGET_DIR)
```bash
# All stages
TARGET_DIR=/workspace/target  # Shared artifact directory
```

**Benefits:**
1. **Clear Intent**: Single variable makes it obvious all stages share one artifact directory
2. **Simpler**: Reduces environment variable count from 2 to 1
3. **Accurate**: Reflects the actual behavior - all stages read from and write to the same location

## Implementation

### Stage Scripts Updated

All stage scripts now use `TARGET_DIR` instead of `INPUT_DIR`/`OUTPUT_DIR`:

1. **[`02-build-corrected.sh`](scripts/stages/02-build-corrected.sh)** - Build stage
   - Writes JDK artifacts to `${TARGET_DIR}/`

2. **[`06-sign.sh`](scripts/stages/06-sign.sh)** - Sign stage
   - Reads artifacts from `${TARGET_DIR}/`
   - Signs them in place
   - Writes signed artifacts back to `${TARGET_DIR}/`

3. **[`07-installer.sh`](scripts/stages/07-installer.sh)** - Installer stage
   - Reads signed JDK artifacts from `${TARGET_DIR}/`
   - Creates installers in `${TARGET_DIR}/installers/`

4. **[`13-smoke-tests.sh`](scripts/stages/13-smoke-tests.sh)** - Smoke test stage
   - Reads JDK artifacts from `${TARGET_DIR}/`
   - Writes test results to `${TARGET_DIR}/test-results/`

### Pipeline Runner Updated

[`run-pipeline.py`](run-pipeline.py) now sets `TARGET_DIR` for all stages:

```python
def stage_build(self):
    target_dir = self.workspace / 'workspace' / 'target'
    env['TARGET_DIR'] = str(target_dir)
    # ...

def stage_sign(self):
    target_dir = self.workspace / 'workspace' / 'target'
    env['TARGET_DIR'] = str(target_dir)
    # ...

def stage_installer(self):
    target_dir = self.workspace / 'workspace' / 'target'
    env['TARGET_DIR'] = str(target_dir)
    # ...

def stage_smoke_tests(self):
    target_dir = self.workspace / 'workspace' / 'target'
    env['TARGET_DIR'] = str(target_dir)
    # ...
```

## Directory Structure

The `TARGET_DIR` contains all artifacts from all stages:

```
~/openjdk-build/workspace/target/
├── OpenJDK21U-jdk_aarch64_mac_hotspot_21.0.2_13.tar.gz    # Build output
├── OpenJDK21U-jdk_aarch64_mac_hotspot_21.0.2_13.tar.gz.sig # Sign output
├── installers/                                             # Installer output
│   ├── OpenJDK21U-jdk_aarch64_mac_hotspot_21.0.2_13.pkg
│   └── OpenJDK21U-jdk_aarch64_mac_hotspot_21.0.2_13.dmg
└── test-results/                                           # Test output
    ├── smoke-test.log
    └── test-summary.json
```

## Migration Guide

### For Stage Scripts

**Before:**
```bash
# Required Environment Variables:
#   INPUT_DIR     - Directory containing input artifacts
#   OUTPUT_DIR    - Directory for output artifacts

# Usage
local input_file="${INPUT_DIR}/artifact.tar.gz"
local output_file="${OUTPUT_DIR}/result.tar.gz"
```

**After:**
```bash
# Required Environment Variables:
#   TARGET_DIR    - Directory containing artifacts (reads/writes here)

# Usage
local input_file="${TARGET_DIR}/artifact.tar.gz"
local output_file="${TARGET_DIR}/result.tar.gz"
```

### For Pipeline Runners

**Before:**
```python
env['INPUT_DIR'] = str(artifact_dir)
env['OUTPUT_DIR'] = str(artifact_dir)
```

**After:**
```python
env['TARGET_DIR'] = str(target_dir)
```

### For Jenkins Declarative Pipeline

**Before:**
```groovy
stage('Build') {
    environment {
        OUTPUT_DIR = "${WORKSPACE}/workspace/target"
    }
    // ...
}

stage('Sign') {
    environment {
        INPUT_DIR = "${WORKSPACE}/workspace/target"
        OUTPUT_DIR = "${WORKSPACE}/workspace/target"
    }
    // ...
}
```

**After:**
```groovy
stage('Build') {
    environment {
        TARGET_DIR = "${WORKSPACE}/workspace/target"
    }
    // ...
}

stage('Sign') {
    environment {
        TARGET_DIR = "${WORKSPACE}/workspace/target"
    }
    // ...
}
```

## Backward Compatibility

The refactoring is **not backward compatible** with scripts expecting `INPUT_DIR`/`OUTPUT_DIR`. All stage scripts and pipeline configurations must be updated together.

## Testing

After refactoring, test the complete pipeline:

```bash
# Test locally with run-pipeline.py
python3 run-pipeline.py \
    --jdk-version jdk21u \
    --variant temurin \
    --target-os mac \
    --architecture aarch64 \
    --workspace ~/openjdk-test

# Verify all artifacts in target directory
ls -la ~/openjdk-test/workspace/target/
```

## Related Documentation

- [`PIPELINE_RUNNER_GUIDE.md`](PIPELINE_RUNNER_GUIDE.md) - Using run-pipeline.py
- [`LOCAL_TESTING_GUIDE.md`](LOCAL_TESTING_GUIDE.md) - Local testing procedures
- [`CI_AGNOSTIC_ARCHITECTURE.md`](CI_AGNOSTIC_ARCHITECTURE.md) - Overall architecture
- [`UNIVERSAL_STAGE_PATTERN.md`](UNIVERSAL_STAGE_PATTERN.md) - Stage implementation pattern

## Summary

The TARGET_DIR refactoring simplifies the pipeline by:
- ✅ Using one variable instead of two
- ✅ Making the shared artifact directory pattern explicit
- ✅ Reducing confusion about separate input/output directories
- ✅ Maintaining the same functional behavior

All stages continue to work exactly as before, but with clearer intent and simpler configuration.