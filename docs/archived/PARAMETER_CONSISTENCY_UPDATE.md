# Parameter Consistency Update

## Overview

This document describes the parameter naming consistency update implemented to align Job DSL parameter definitions with Jenkinsfile parameter usage and the `load-json-config.py` script expectations.

## Problem Statement

There was a mismatch between:
- **Job DSL**: Created jobs with `PLATFORM` (combined like "x64Linux") and `BUILD_VARIANT` parameters
- **Jenkinsfile**: Expected `VARIANT`, `TARGET_OS`, and `ARCHITECTURE` parameters (separate)
- **load-json-config.py**: Expected `--variant`, `--target-os`, and `--architecture` arguments

This mismatch caused the pipeline to fail because the Jenkinsfile couldn't find the required parameters.

## Solution

Updated the Job DSL to create jobs with parameters that match what the Jenkinsfile expects:

### Parameter Changes

| Old Parameter | New Parameter | Description |
|--------------|---------------|-------------|
| `PLATFORM` | `TARGET_OS` + `ARCHITECTURE` | Split combined platform into separate OS and architecture |
| `BUILD_VARIANT` | `VARIANT` | Renamed for consistency |

### New Parameter Structure

**Build Pipeline Jobs** now have these parameters:

1. **JDK_VERSION** (string) - JDK version (e.g., "21")
2. **TARGET_OS** (string) - Operating system (e.g., "linux", "mac", "windows")
3. **ARCHITECTURE** (string) - CPU architecture (e.g., "x64", "aarch64", "arm")
4. **VARIANT** (string) - Build variant (e.g., "temurin", "dragonwell")
5. **CONFIG_REPO_URL** (string) - Configuration repository URL
6. **CONFIG_REPO_BRANCH** (string) - Configuration repository branch
7. Other build configuration parameters...

## Implementation Details

### 1. Job DSL Script (`openjdk_build_pipeline_job_dsl.groovy`)

The Job DSL now:
1. Receives `PLATFORM` parameter from launch job (e.g., "x64Linux")
2. Loads the platform-specific configuration from `jdk${version}_pipeline_config.json`
3. Extracts `os`, `arch`, and `variant` from the platform configuration
4. Creates job parameters using these extracted values

**Example:**
```groovy
// Platform configuration for "x64Linux" in jdk21_pipeline_config.json:
{
  "x64Linux": {
    "os": "linux",
    "arch": "x64",
    ...
  }
}

// Job DSL extracts and creates parameters:
stringParam('TARGET_OS', 'linux', 'Target operating system (fixed)')
stringParam('ARCHITECTURE', 'x64', 'Target architecture (fixed)')
stringParam('VARIANT', 'temurin', 'Build variant (temurin, dragonwell, etc.)')
```

### 2. Launch Job Parameters

Launch jobs still use:
- `VARIANT` (renamed from `BUILD_VARIANT`)
- `PLATFORMS` (comma-separated list like "x64Linux,aarch64Mac")

### 3. Configuration Files

**jenkins_job_config.json:**
```json
{
  "jobConfiguration": {
    "defaultParameters": {
      "VARIANT": "temurin",
      ...
    }
  }
}
```

**jdk${version}_pipeline_config.json:**
```json
{
  "buildConfigurations": {
    "x64Linux": {
      "os": "linux",
      "arch": "x64",
      ...
    }
  }
}
```

## Files Modified

### ci-adoptium-pipelines Repository

1. **ci/jenkins/job-dsl/openjdk_build_pipeline_job_dsl.groovy**
   - Added platform configuration loading
   - Extracts `os`, `arch`, and `variant` from platform config
   - Creates `TARGET_OS`, `ARCHITECTURE`, and `VARIANT` parameters

2. **ci/jenkins/job-dsl/seed/seed_job_dsl.groovy**
   - Renamed `BUILD_VARIANT` to `VARIANT`
   - Added platform loading logic
   - Changed `PLATFORMS` parameter from string to choice dropdown

### ci-temurin-config Repository

4. **jenkins_job_config.json**
   - Renamed `BUILD_VARIANT` to `VARIANT` in defaultParameters

### Tools

5. **tools/convert-legacy-configs-to-new-architecture.py**
   - Updated to generate `VARIANT` instead of `BUILD_VARIANT` in jenkins_job_config.json

### UI Improvements

6. **Launch Job PLATFORMS Parameter**
   - Changed from string input to choice dropdown
   - Dynamically populated with all available platforms for that JDK version
   - "all" option appears at the top of the list
   - Platforms are sorted alphabetically for easy selection

## Jenkinsfile Usage

The Jenkinsfile already uses the correct parameter names:

```groovy
sh """
    python3 ci/jenkins/scripts/load-json-config.py \\
        --config-file "${CONFIG_FILE}" \\
        --variant ${params.VARIANT} \\
        --target-os ${params.TARGET_OS} \\
        --architecture ${params.ARCHITECTURE} \\
        --output-file pipeline-config.json
"""
```

## Benefits

1. **Consistency**: Parameters match across Job DSL, Jenkinsfile, and Python scripts
2. **Clarity**: Separate OS and architecture parameters are more explicit than combined platform
3. **Flexibility**: Easier to filter or query jobs by specific OS or architecture
4. **Maintainability**: Reduces confusion and potential errors from parameter mismatches

## Migration Notes

- Existing jobs will need to be regenerated with `REGENERATE_JOBS=true`
- The launch job will automatically create new jobs with correct parameters
- Old jobs with `PLATFORM` and `BUILD_VARIANT` parameters can be deleted

## Testing

To verify the changes:

1. Run a launch job with `REGENERATE_JOBS=true`
2. Check that platform-specific build jobs are created with correct parameters
3. Trigger a build and verify parameters are passed correctly to `load-json-config.py`
4. Confirm the pipeline executes successfully

## Related Documentation

- [Job DSL Architecture](JOB_DSL_ARCHITECTURE.md)
- [Launch Job Design](LAUNCH_JOB_DESIGN.md)
- [Configuration Repository Structure](CONFIGURATION_REPOSITORY.md)