# Release Type Parameter Migration

## Overview

This document describes the migration from separate `RELEASE` and `WEEKLY` boolean parameters to a single `RELEASE_TYPE` choice parameter.

## Motivation

- **Simplification**: Single parameter instead of two boolean flags
- **Clarity**: Explicit choice between NIGHTLY, WEEKLY, and RELEASE
- **Maintainability**: Easier to understand and extend in the future
- **Consistency**: Aligns with common CI/CD patterns

## Changes Made

### 1. Job DSL Configuration

**File**: `ci/jenkins/job-dsl/openjdk_build_pipeline_job_dsl.groovy`

**Before**:
```groovy
booleanParam('RELEASE', false, 'Is this a release build?')
booleanParam('WEEKLY', false, 'Is this a weekly build?')
```

**After**:
```groovy
choiceParam('RELEASE_TYPE',
    ['NIGHTLY', 'WEEKLY', 'RELEASE'],
    'Type of release build (NIGHTLY=default nightly builds, WEEKLY=weekly builds, RELEASE=official releases)')
```

### 2. Jenkinsfile.declarative

**File**: `ci/jenkins/Jenkinsfile.declarative`

#### Build Display Name (Lines 61-66)
**Before**:
```groovy
if (params.RELEASE) {
    displayName += " [RELEASE]"
} else if (params.WEEKLY) {
    displayName += " [WEEKLY]"
}
```

**After**:
```groovy
if (params.RELEASE_TYPE && params.RELEASE_TYPE != 'NIGHTLY') {
    displayName += " [${params.RELEASE_TYPE}]"
}
```

#### Python Script Arguments (Lines 232-241)
**Before**:
```groovy
if (params.RELEASE) {
    pythonArgs.add("--release")
}
if (params.WEEKLY) {
    pythonArgs.add("--weekly")
}
```

**After**:
```groovy
if (params.RELEASE_TYPE) {
    // Validate RELEASE_TYPE parameter
    def validReleaseTypes = ['NIGHTLY', 'WEEKLY', 'RELEASE']
    if (!validReleaseTypes.contains(params.RELEASE_TYPE)) {
        error("Invalid RELEASE_TYPE: '${params.RELEASE_TYPE}'. Must be one of: ${validReleaseTypes.join(', ')}")
    }
    pythonArgs.add("--release-type")
    pythonArgs.add(params.RELEASE_TYPE)
}
```

#### Environment Variable (Line 694)
**Before**:
```groovy
env.RELEASE = params.RELEASE ? 'true' : 'false'
```

**After**:
```groovy
env.RELEASE = (params.RELEASE_TYPE == 'RELEASE') ? 'true' : 'false'
```

### 3. Python Scripts

#### load-json-config.py

**File**: `scripts/lib/load-json-config.py`

**Parameter Definition** (Lines 258-259):
```python
parser.add_argument('--release-type', choices=['NIGHTLY', 'WEEKLY', 'RELEASE'],
                    help='Type of release build (NIGHTLY=default, WEEKLY=weekly builds, RELEASE=official releases)')
```

**Parameter Processing** (Lines 99-103):
```python
# Determine release type from --release-type parameter (defaults to NIGHTLY)
release_type = args.release_type or 'NIGHTLY'
is_release = (release_type == 'RELEASE')
is_weekly = (release_type == 'WEEKLY')
```

**Documentation Example** (Lines 227-234):
```bash
python3 load-json-config.py \
    --jdk-version jdk17u \
    --variant temurin \
    --target-os linux \
    --architecture x64 \
    --release-type RELEASE \
    --scm-ref jdk-17.0.10+7
```

#### run-pipeline.py

**File**: `ci/local/run-pipeline.py`

**Parameter Definition** (Lines 606-607):
```python
parser.add_argument('--release-type', choices=['NIGHTLY', 'WEEKLY', 'RELEASE'],
                    help='Type of release build (NIGHTLY=default, WEEKLY=weekly builds, RELEASE=official releases)')
```

**Parameter Forwarding** (Lines 213-214):
```python
if self.args.release_type:
    cmd.extend(['--release-type', self.args.release_type])
```

**Documentation Examples** (Lines 545, 581):
```bash
--release-type RELEASE
```

## Parameter Values

| Value | Description | Use Case |
|-------|-------------|----------|
| `NIGHTLY` | Default nightly builds | Regular automated builds |
| `WEEKLY` | Weekly builds | Scheduled weekly releases |
| `RELEASE` | Official releases | Production releases |

**Note**: Parameter values are **case-insensitive**. You can use `release`, `Release`, or `RELEASE` - all will be converted to uppercase internally.

## Validation

The `RELEASE_TYPE` parameter is validated at multiple layers for robustness:

### 1. Jenkins Job Definition (Job DSL)
- **Location**: Job parameter definition
- **Method**: `choiceParam()` restricts to predefined values
- **Effect**: Users can only select from dropdown menu
- **Values**: `['NIGHTLY', 'WEEKLY', 'RELEASE']`

### 2. Jenkinsfile (Pipeline Script)
- **Location**: [`Jenkinsfile.declarative`](../ci/jenkins/Jenkinsfile.declarative:232) lines 232-244
- **Method**: Converts to uppercase, then validates before passing to Python
- **Effect**: Case-insensitive input, fails fast with clear error message if invalid value
- **Error Message**: `Invalid RELEASE_TYPE: 'xyz'. Must be one of: NIGHTLY, WEEKLY, RELEASE (case-insensitive)`

```groovy
// Convert to uppercase for case-insensitive handling
def releaseType = params.RELEASE_TYPE.toUpperCase()

// Validate RELEASE_TYPE parameter
def validReleaseTypes = ['NIGHTLY', 'WEEKLY', 'RELEASE']
if (!validReleaseTypes.contains(releaseType)) {
    error("Invalid RELEASE_TYPE: '${params.RELEASE_TYPE}'. Must be one of: ${validReleaseTypes.join(', ')} (case-insensitive)")
}
```

### 3. Python Scripts (load-json-config.py, run-pipeline.py)
- **Location**: Argument parser and processing logic
- **Method**: Converts to uppercase, then validates against allowed values
- **Effect**: Case-insensitive input with clear error message for invalid values
- **Error Message**: `ERROR: Invalid release type 'xyz'. Must be one of: NIGHTLY, WEEKLY, RELEASE (case-insensitive)`

```python
# Convert to uppercase for case-insensitive comparison
release_type = (args.release_type or 'NIGHTLY').upper()

# Validate release type
valid_release_types = ['NIGHTLY', 'WEEKLY', 'RELEASE']
if release_type not in valid_release_types:
    print(f"ERROR: Invalid release type '{args.release_type}'. Must be one of: {', '.join(valid_release_types)} (case-insensitive)", file=sys.stderr)
    sys.exit(1)
```

### Defense in Depth

This multi-layer validation ensures:
1. **UI Protection**: Dropdown prevents typos in Jenkins UI
2. **Case Insensitivity**: All layers accept lowercase, mixed case, or uppercase
3. **API Protection**: Jenkinsfile validation catches programmatic errors
4. **Script Protection**: Python validation provides final safety net
5. **Clear Errors**: Each layer provides helpful error messages
6. **Consistent Behavior**: All layers normalize to uppercase internally

## Migration Guide

### For Job Configuration

When creating or updating jobs via Job DSL:

1. Remove the `RELEASE` and `WEEKLY` boolean parameters
2. Add the `RELEASE_TYPE` choice parameter with values `['NIGHTLY', 'WEEKLY', 'RELEASE']`
3. Set default value to `NIGHTLY`

### For Pipeline Scripts

When calling the pipeline:

**Before**:
```groovy
build job: 'openjdk-build', parameters: [
    booleanParam(name: 'RELEASE', value: true)
]
```

**After**:
```groovy
build job: 'openjdk-build', parameters: [
    choice(name: 'RELEASE_TYPE', value: 'RELEASE')
]
```

### For Python Scripts

**Before**:
```bash
python3 load-json-config.py --release
python3 load-json-config.py --weekly
```

**After**:
```bash
python3 load-json-config.py --release-type RELEASE
python3 load-json-config.py --release-type WEEKLY
python3 load-json-config.py --release-type NIGHTLY  # or omit for default
```

### For Local Testing

**Before**:
```bash
python3 run-pipeline.py --release
python3 run-pipeline.py --weekly
```

**After**:
```bash
python3 run-pipeline.py --release-type RELEASE
python3 run-pipeline.py --release-type WEEKLY
python3 run-pipeline.py --release-type NIGHTLY  # or omit for default
```

## Backward Compatibility

**Note**: This change is **NOT backward compatible**. The old `--release` and `--weekly` flags have been completely removed.

### Impact

- Existing job configurations will need to be updated
- Existing scripts calling the pipeline will need to be updated
- Manual job triggers will show the new parameter

### Rollout Strategy

1. Update Job DSL scripts to create jobs with new parameter
2. Update all pipeline scripts to use new parameter
3. Update documentation and examples
4. Communicate changes to users
5. Monitor for any issues during transition

## Testing

### Test Cases

1. **NIGHTLY build** (default):
   - Trigger build without specifying RELEASE_TYPE
   - Verify display name shows no suffix
   - Verify `env.RELEASE` is `false`

2. **WEEKLY build**:
   - Trigger build with `RELEASE_TYPE=WEEKLY`
   - Verify display name shows `[WEEKLY]`
   - Verify `env.RELEASE` is `false`

3. **RELEASE build**:
   - Trigger build with `RELEASE_TYPE=RELEASE`
   - Verify display name shows `[RELEASE]`
   - Verify `env.RELEASE` is `true`

4. **Stage restart**:
   - Verify RELEASE_TYPE persists across stage restarts
   - Verify display name remains correct after restart

## Benefits

1. **Clearer Intent**: Single parameter makes build type explicit
2. **Easier to Extend**: Adding new build types (e.g., BETA, RC) is straightforward
3. **Better UX**: Dropdown selection is more user-friendly than multiple checkboxes
4. **Reduced Errors**: Impossible to select both RELEASE and WEEKLY simultaneously
5. **Simplified Logic**: Fewer conditional branches in code

## Related Files

- `ci/jenkins/job-dsl/openjdk_build_pipeline_job_dsl.groovy`
- `ci/jenkins/Jenkinsfile.declarative`
- `scripts/lib/load-json-config.py`
- `ci/local/run-pipeline.py`

## See Also

- [Job DSL Documentation](JOB_DSL_AUTOMATION.md)
- [Pipeline Architecture](MIGRATION_STRATEGY.md)
- [Build Configuration](../scripts/lib/README.md)