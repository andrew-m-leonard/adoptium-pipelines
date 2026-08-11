# Parameter Consolidation and Standardization

## Overview

This document describes the parameter consolidation effort to eliminate duplicate parameters and ensure consistency across launch and build jobs.

## Changes Made

### 1. Launch Job Parameters Added

**File**: [`ci/jenkins/job-dsl/seed/seed_job_dsl.groovy`](../ci/jenkins/job-dsl/seed/seed_job_dsl.groovy)

Added three new parameters to the launch job to support source control and release management:

```groovy
// Source control parameters
stringParam('SCM_REF', '',
    'Git reference (tag/branch) for the JDK source code (e.g., jdk-21.0.12+6_adopt)')

stringParam('BUILD_REF', '',
    'Git reference for the build scripts repository (leave empty for default branch)')

choiceParam('RELEASE_TYPE',
    ['NIGHTLY', 'WEEKLY', 'RELEASE'],
    'Type of release build (NIGHTLY=default nightly builds, WEEKLY=weekly EA beta builds, RELEASE=official releases)')
```

### 2. Build Job Duplicate Parameters Removed

**File**: [`ci/jenkins/job-dsl/openjdk_build_pipeline_job_dsl.groovy`](../ci/jenkins/job-dsl/openjdk_build_pipeline_job_dsl.groovy)

Removed duplicate parameters that conflicted with existing parameters:

#### Removed Parameters

| Removed Parameter | Replaced By | Reason |
|------------------|-------------|---------|
| `ENABLE_TESTS` | `RUN_TESTS` | Duplicate functionality - both control test execution |
| `ENABLE_SIGNER` | `SIGN_ARTIFACTS` | Duplicate functionality - both control artifact signing |

#### Added Parameters

Added the same source control parameters to build jobs for consistency:

```groovy
stringParam('SCM_REF', '',
    'Git reference (tag/branch) for the JDK source code (e.g., jdk-21.0.12+6_adopt)')

stringParam('BUILD_REF', '',
    'Git reference for the build scripts repository (leave empty for default branch)')
```

Note: `RELEASE_TYPE` was already present in build jobs.

### 3. Launch Job Parameter Passing Updated

**File**: [`ci/jenkins/Jenkinsfile.launch`](../ci/jenkins/Jenkinsfile.launch)

Updated the launch job to pass all parameters to build jobs, including the new source control parameters:

```groovy
parameters: [
    string(name: 'JDK_VERSION', value: env.JDK_VERSION),
    string(name: 'PLATFORM', value: platform),
    string(name: 'VARIANT', value: params.VARIANT),
    string(name: 'BUILD_ARGS', value: params.BUILD_ARGS ?: ''),
    string(name: 'CONFIG_REPO_URL', value: params.CONFIG_REPO_URL),
    string(name: 'CONFIG_REPO_BRANCH', value: params.CONFIG_REPO_BRANCH),
    string(name: 'SCM_REF', value: params.SCM_REF ?: ''),
    string(name: 'BUILD_REF', value: params.BUILD_REF ?: ''),
    string(name: 'RELEASE_TYPE', value: params.RELEASE_TYPE),
    booleanParam(name: 'CLEAN_WORKSPACE_AFTER_STAGE', value: params.CLEAN_WORKSPACE_AFTER_STAGE),
    booleanParam(name: 'RUN_TESTS', value: params.RUN_TESTS),
    booleanParam(name: 'ENABLE_INSTALLERS', value: params.ENABLE_INSTALLERS),
    booleanParam(name: 'SIGN_ARTIFACTS', value: params.SIGN_ARTIFACTS),
    booleanParam(name: 'PUBLISH_ARTIFACTS', value: params.PUBLISH_ARTIFACTS),
    booleanParam(name: 'RUN_REPRODUCIBLE_COMPARE', value: params.RUN_REPRODUCIBLE_COMPARE)
]
```

### 4. Script Updates

**File**: [`scripts/stages/01-initialize.sh`](../scripts/stages/01-initialize.sh)

Updated hardcoded JSON examples to use the standardized parameter names:

```json
{
  "RUN_TESTS": true,           // Was: ENABLE_TESTS
  "SIGN_ARTIFACTS": true,      // Was: ENABLE_SIGNER
  "ENABLE_INSTALLERS": true,
  ...
}
```

## Parameter Reference

### Launch Job Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `JDK_VERSION` | String | (set by seed) | JDK version number (e.g., 21, 17, 11) |
| `CONFIG_REPO_URL` | String | (required) | URL of configuration repository |
| `CONFIG_REPO_BRANCH` | String | (required) | Branch of configuration repository |
| `REGENERATE_JOBS` | Boolean | false | Force regeneration of platform jobs |
| `PLATFORMS` | Choice | all | Platform selection (all or specific) |
| `VARIANT` | String | temurin | Build variant |
| `BUILD_ARGS` | String | "" | Additional build arguments |
| `SCM_REF` | String | "" | Git reference for JDK source |
| `BUILD_REF` | String | "" | Git reference for build scripts |
| `RELEASE_TYPE` | Choice | NIGHTLY | Release type (NIGHTLY/WEEKLY/RELEASE) |
| `RUN_TESTS` | Boolean | false | Run test stages |
| `ENABLE_INSTALLERS` | Boolean | true | Build installers |
| `SIGN_ARTIFACTS` | Boolean | false | Sign artifacts and installers |
| `PUBLISH_ARTIFACTS` | Boolean | false | Publish to release repository |
| `RUN_REPRODUCIBLE_COMPARE` | Boolean | false | Run reproducible build comparison |

### Build Job Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `JDK_VERSION` | String | (fixed) | JDK version (set by launch job) |
| `TARGET_OS` | String | (fixed) | Target operating system (set by launch job) |
| `ARCHITECTURE` | String | (fixed) | Target architecture (set by launch job) |
| `CONFIG_REPO_URL` | String | (required) | URL of configuration repository |
| `CONFIG_REPO_BRANCH` | String | (required) | Branch of configuration repository |
| `VARIANT` | String | temurin | Build variant |
| `SCM_REF` | String | "" | Git reference for JDK source |
| `BUILD_REF` | String | "" | Git reference for build scripts |
| `RELEASE_TYPE` | Choice | NIGHTLY | Release type (NIGHTLY/WEEKLY/RELEASE) |
| `CLEAN_WORKSPACE_AFTER_STAGE` | Boolean | true | Clean workspace after each stage |
| `RUN_TESTS` | Boolean | true | Run test stages |
| `SIGN_ARTIFACTS` | Boolean | false | Sign artifacts and installers |
| `PUBLISH_ARTIFACTS` | Boolean | false | Publish to release repository |
| `RUN_REPRODUCIBLE_COMPARE` | Boolean | false | Run reproducible build comparison |
| `ENABLE_INSTALLERS` | Boolean | true | Build installers |
| `ENABLE_TCK` | Boolean | false | Run TCK tests (Temurin only, release/weekly builds) |
| `RELEASE_TYPE` (WEEKLY) | — | — | Implies EA/Beta build (adds --with-version-opt=ea) |

## Migration Notes

### For Existing Jobs

If you have existing jobs using the old parameter names:

1. **ENABLE_TESTS** → Use **RUN_TESTS** instead
2. **ENABLE_SIGNER** → Use **SIGN_ARTIFACTS** instead

### For Scripts

Scripts should reference the standardized parameter names:

- Use `RUN_TESTS` for test execution control
- Use `SIGN_ARTIFACTS` for signing control
- Use `RELEASE_TYPE` for release type (case-insensitive, converted to uppercase)

### For Job DSL

When creating or updating jobs via Job DSL:

1. Remove any references to `ENABLE_TESTS` and `ENABLE_SIGNER`
2. Use `RUN_TESTS` and `SIGN_ARTIFACTS` instead
3. Ensure `SCM_REF`, `BUILD_REF`, and `RELEASE_TYPE` are passed from launch to build jobs

## Benefits

1. **Consistency**: Single parameter name for each function across all jobs
2. **Clarity**: Clear, descriptive parameter names
3. **Maintainability**: Easier to understand and modify job configurations
4. **Flexibility**: Source control parameters enable better version control
5. **Standardization**: Aligned with industry best practices

## Related Documentation

- [RELEASE_TYPE Parameter Migration](RELEASE_TYPE_PARAMETER_MIGRATION.md)
- [Migration Strategy](MIGRATION_STRATEGY.md)
- [Job DSL README](../ci/jenkins/job-dsl/README.md)

## Testing

After applying these changes:

1. Regenerate jobs using the seed job
2. Verify launch job has new parameters (SCM_REF, BUILD_REF, RELEASE_TYPE)
3. Verify build jobs no longer have ENABLE_TESTS and ENABLE_SIGNER
4. Test launching a build with various parameter combinations
5. Verify parameters are correctly passed from launch to build jobs

## Rollback

If issues arise, the old parameters can be temporarily restored by:

1. Re-adding the removed parameters to `openjdk_build_pipeline_job_dsl.groovy`
2. Reverting the changes to `Jenkinsfile.launch`
3. Regenerating jobs via the seed job

However, this is not recommended as it reintroduces the duplication issues.