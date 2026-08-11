# Configuration System Guide

This guide explains the new simplified configuration system for the refactored OpenJDK build pipeline.

## Overview

The new system replaces Groovy configuration files with JSON and uses an initialize stage to generate BUILD_CONFIGURATION dynamically based on:
- JDK version (jdk8u, jdk11u, jdk17u, jdk21u, etc.)
- Target platform (OS + Architecture)
- Build variant (temurin, hotspot)

## Architecture

```
Input Parameters          Configuration Files              Generated Output
┌─────────────────┐      ┌──────────────────────┐        ┌────────────────────────┐
│ JAVA_VERSION    │      │ jdk21u_pipeline_     │        │ BUILD_CONFIGURATION    │
│ TARGET_OS       │──────│   config.json        │────────│   .json                │
│ ARCHITECTURE    │      │                      │        │                        │
│ VARIANT         │      │ Contains platform-   │        │ Complete build config  │
│ RELEASE/WEEKLY  │      │ specific settings    │        │ for this build         │
└─────────────────┘      └──────────────────────┘        └────────────────────────┘
         │                                                          │
         │                                                          │
         └──────────────────────────────────────────────────────────┘
                    01-initialize.sh processes inputs
```

## Configuration Files

### Location

Configuration files are stored in a **separate repository** from the pipeline code:

**Configuration Repository** (e.g., `ci-temurin-config/`):
```
ci-temurin-config/configurations/
├── jdk8u_pipeline_config.json
├── jdk11u_pipeline_config.json
├── jdk17u_pipeline_config.json
├── jdk21u_pipeline_config.json
├── jdk22u_pipeline_config.json
└── ...
```

**Pipeline Code Repository** (`ci-adoptium-pipelines/`):
```
ci-adoptium-pipelines/
├── ci/
│   ├── jenkins/Jenkinsfile.declarative
│   └── local/run-pipeline.py
├── scripts/
│   ├── lib/load-json-config.py
│   └── stages/
└── docs/
```

This separation enables vendor independence and allows different organizations to maintain their own configurations while using the same pipeline code.

### Structure

Each configuration file contains platform-specific build settings:

```json
{
  "buildConfigurations": {
    "aarch64Mac": {
      "os": "mac",
      "arch": "aarch64",
      "additionalNodeLabels": "xcode15.0.1",
      "configureArgs": "--enable-dtrace",
      "buildArgs": {
        "temurin": "--create-jre-image --create-sbom",
        "hotspot": "--create-jre-image"
      },
      "test": {
        "nightly": ["sanity.openjdk", "sanity.system"],
        "weekly": ["sanity.openjdk", "sanity.system", "extended.system"],
        "release": ["sanity.openjdk", "sanity.system", "extended.system", "extended.openjdk"]
      }
    },
    "x64Linux": {
      "os": "linux",
      "arch": "x64",
      "dockerImage": "adoptopenjdk/centos7_build_image",
      "buildArgs": "--create-source-archive --create-jre-image --create-sbom"
    }
  }
}
```

### Platform Keys

Platform keys are constructed as: `{architecture}{OS}`

Examples:
- `aarch64Mac` - Apple Silicon Mac
- `x64Mac` - Intel Mac
- `x64Linux` - Intel/AMD Linux
- `aarch64Linux` - ARM Linux
- `x64Windows` - Intel/AMD Windows
- `ppc64Aix` - PowerPC AIX

### Simple vs Variant-Specific Values

**IMPORTANT**: Configuration values can be specified in two ways:

#### Option 1: Simple String Value (applies to all variants)

```json
{
  "buildArgs": "--create-jre-image --create-sbom",
  "configureArgs": "--enable-dtrace",
  "additionalNodeLabels": "xcode15.0.1"
}
```
When a field contains a simple string, that value is used for **all variants** (temurin, hotspot).


#### Option 2: Variant-Specific Object (different value per variant)

```json
{
  "buildArgs": {
    "temurin": "--create-jre-image --create-sbom",
    "hotspot": "--create-jre-image"
  },
  "configureArgs": {
    "temurin": "--enable-dtrace",
    "hotspot": "--enable-dtrace"
  },
  "additionalNodeLabels": {
    "temurin": "xcode15.0.1",
    "hotspot": "xcode15.0.1"
  }
}
```

When a field contains an object with variant keys, the initialize script extracts the value for the specific variant being built.

#### How the Initialize Script Handles Values

The [`01-initialize.sh`](scripts/stages/01-initialize.sh:1) script automatically detects which format is used:

1. **If the value is a string**: Uses that value for all variants
2. **If the value is an object**: Extracts the variant-specific value
3. **If variant-specific value not found**: Falls back to a default value (if provided)

**Fields that support variant-specific values:**
- `buildArgs`
- `configureArgs`
- `dockerFile`
- `dockerImage`
- `additionalNodeLabels`
- `additionalTestLabels`

**Example from Groovy (original format):**
```groovy
// Simple value - applies to all variants
buildArgs: "--create-jre-image --create-sbom"

// OR variant-specific Map
buildArgs: [
    temurin: "--create-jre-image --create-sbom",
    hotspot: "--create-jre-image"
]
```

**Equivalent JSON:**
```json
// Simple value - applies to all variants
"buildArgs": "--create-jre-image --create-sbom"

// OR variant-specific object
"buildArgs": {
  "temurin": "--create-jre-image --create-sbom",
  "hotspot": "--create-jre-image"
}
```

## Initialize Stage

### Purpose

The [`01-initialize.sh`](scripts/stages/01-initialize.sh:1) script:
1. Loads the appropriate `jdkNN_pipeline_config.json`
2. Selects the platform configuration
3. Applies variant-specific overrides
4. Generates `BUILD_CONFIGURATION.json`
5. Creates simplified `pipeline-config.json` for build stage

### Usage

```bash
export WORKSPACE=~/openjdk-build
export JAVA_VERSION=jdk21u
export TARGET_OS=mac
export ARCHITECTURE=aarch64
export VARIANT=temurin
export CONFIG_DIR=${WORKSPACE}/configurations

./scripts/stages/01-initialize.sh
```

### Required Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `WORKSPACE` | Root workspace directory | `~/openjdk-build` |
| `JAVA_VERSION` | JDK version to build | `jdk21u`, `jdk17u` |
| `TARGET_OS` | Target operating system | `mac`, `linux`, `windows` |
| `ARCHITECTURE` | Target architecture | `aarch64`, `x64` |
| `VARIANT` | Build variant | `temurin`, `hotspot` |

### Optional Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `CONFIG_DIR` | Configuration directory | `${WORKSPACE}/configurations` |
| `SCM_REF` | Git ref for OpenJDK source | `master` |
| `BUILD_REF` | Git ref for temurin-build | `master` |
| `CI_REF` | Git ref for ci-jenkins-pipelines | `master` |
| `HELPER_REF` | Git ref for helper scripts | `master` |
| `RELEASE` | Is this a release build? | `false` |
| `WEEKLY` | Is this a weekly build? | `false` |

### Output Files

**BUILD_CONFIGURATION.json** - Complete configuration matching Jenkins format:
```json
{
  "ARCHITECTURE": "aarch64",
  "TARGET_OS": "mac",
  "VARIANT": "temurin",
  "JAVA_TO_BUILD": "jdk21u",
  "TEST_LIST": ["sanity.openjdk", "sanity.system"],
  "SCM_REF": "master",
  "BUILD_REF": "master",
  "BUILD_ARGS": "--create-jre-image --create-sbom",
  "NODE_LABEL": "xcode15.0.1&&build&&mac&&aarch64",
  "DOCKER_IMAGE": "",
  "CONFIGURE_ARGS": "--enable-dtrace",
  "ENABLE_TESTS": true,
  "ENABLE_INSTALLERS": true,
  "ENABLE_SIGNER": true
}
```

**pipeline-config.json** - Simplified configuration for build stage:
```json
{
  "buildConfig": {
    "JAVA_TO_BUILD": "jdk21u",
    "TARGET_OS": "mac",
    "ARCHITECTURE": "aarch64",
    "VARIANT": "temurin",
    "BUILD_ARGS": "--create-jre-image --create-sbom"
  },
  "parameters": {
    "enableTests": true,
    "enableInstallers": true,
    "enableSigner": true
  }
}
```

## Converting Existing Groovy Configs

### Conversion Tool

Use the provided conversion tool to migrate from Groovy to JSON:

```bash
./tools/convert-groovy-config-to-json.sh \
  ~/workspace/ci-jenkins-pipelines/pipelines/jobs/configurations/jdk21u_pipeline_config.groovy \
  configurations/jdk21u_pipeline_config.json
```

### Manual Conversion Steps

#### 1. Extract Platform Configurations

**Groovy (original):**
```groovy
x64Mac: [
    os: 'mac',
    arch: 'x64',
    buildArgs: '--create-jre-image'
]
```

**JSON (new):**
```json
"x64Mac": {
  "os": "mac",
  "arch": "x64",
  "buildArgs": "--create-jre-image"
}
```

#### 2. Convert Simple Values

**Groovy:**
```groovy
buildArgs: "--create-jre-image --create-sbom"
```

**JSON:**
```json
"buildArgs": "--create-jre-image --create-sbom"
```

#### 3. Convert Variant-Specific Maps

**Groovy:**
```groovy
buildArgs: [
    temurin: '--create-jre-image --create-sbom',
    hotspot: '--create-jre-image'
]
```

**JSON:**
```json
"buildArgs": {
  "temurin": "--create-jre-image --create-sbom",
  "hotspot": "--create-jre-image"
}
```

#### 4. Convert Test Lists

**Groovy:**
```groovy
test: [
    weekly: ['sanity.openjdk', 'sanity.system']
]
```

**JSON:**
```json
"test": {
  "weekly": ["sanity.openjdk", "sanity.system"]
}
```

### Validation

After conversion, validate the JSON:

```bash
# Check JSON syntax
jq . configurations/jdk21u_pipeline_config.json

# Test with initialize script
export WORKSPACE=~/test
export JAVA_VERSION=jdk21u
export TARGET_OS=mac
export ARCHITECTURE=aarch64
export VARIANT=temurin
export CONFIG_DIR=./configurations

./scripts/stages/01-initialize.sh
```

## Configuration Fields Reference

### Platform Configuration Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `os` | string | Yes | Operating system: `mac`, `linux`, `windows`, `aix` |
| `arch` | string | Yes | Architecture: `aarch64`, `x64`, `x32`, `ppc64` |
| `buildArgs` | string/object | No | Build arguments (can be variant-specific) |
| `configureArgs` | string/object | No | Configure arguments (can be variant-specific) |
| `dockerImage` | string/object | No | Docker image for build (can be variant-specific) |
| `dockerFile` | string/object | No | Custom Dockerfile (can be variant-specific) |
| `dockerRegistry` | string | No | Docker registry URL |
| `dockerCredential` | string | No | Docker credential ID |
| `dockerArgs` | string | No | Additional docker arguments |
| `additionalNodeLabels` | string/object | No | Extra Jenkins node labels (can be variant-specific) |
| `additionalTestLabels` | string/object | No | Extra test node labels (can be variant-specific) |
| `additionalTestParams` | object | No | Extra test parameters |
| `test` | object | No | Test lists by build type |
| `cleanWorkspaceAfterBuild` | boolean | No | Clean workspace after build |

### Test Configuration

```json
{
  "test": {
    "nightly": ["sanity.openjdk", "sanity.system"],
    "weekly": ["sanity.openjdk", "sanity.system", "extended.system"],
    "release": ["sanity.openjdk", "extended.openjdk", "special.functional"]
  }
}
```

Or use `"test": "default"` to use default test list.

## Examples

### Example 1: Mac Apple Silicon Temurin Build

```bash
export WORKSPACE=~/openjdk-build
export JAVA_VERSION=jdk21u
export TARGET_OS=mac
export ARCHITECTURE=aarch64
export VARIANT=temurin
export CONFIG_DIR=./configurations

./scripts/stages/01-initialize.sh
```

Generates configuration for building JDK 21 Temurin on Mac Apple Silicon.
### Example 2: Linux x64 HotSpot Release Build


```bash
export WORKSPACE=~/openjdk-build
export JAVA_VERSION=jdk17u
export TARGET_OS=linux
export ARCHITECTURE=x64
export VARIANT=hotspot
export RELEASE=true
export SCM_REF=jdk-17.0.10+7
export CONFIG_DIR=./configurations

./scripts/stages/01-initialize.sh
```
Generates configuration for a JDK 17 HotSpot release build on Linux x64.


### Example 3: Platform with Variant-Specific Settings

**Configuration:**
```json
{
  "buildConfigurations": {
    "x64Linux": {
      "os": "linux",
      "arch": "x64",
      "buildArgs": {
        "temurin": "--create-source-archive --create-jre-image --create-sbom",
        "hotspot": "--create-jre-image"
      },
      "dockerImage": {
        "temurin": "adoptopenjdk/centos7_build_image",
        "hotspot": "adoptopenjdk/centos7_build_image"
      }
    }
  }
}
```

**Building Temurin:**
```bash
export VARIANT=temurin
./scripts/stages/01-initialize.sh
# Uses: buildArgs="--create-source-archive --create-jre-image --create-sbom"
# Uses: dockerImage="adoptopenjdk/centos7_build_image"
```

**Building HotSpot:**
```bash
export VARIANT=hotspot
./scripts/stages/01-initialize.sh
# Uses: buildArgs="--create-jre-image"
# Uses: dockerImage="adoptopenjdk/centos7_build_image"
```

## Integration with Pipeline

### Declarative Pipeline

```groovy
pipeline {
    agent any

    environment {
        WORKSPACE = "${WORKSPACE}"
        JAVA_VERSION = 'jdk21u'
        TARGET_OS = 'mac'
        ARCHITECTURE = 'aarch64'
        VARIANT = 'temurin'
        CONFIG_DIR = "${WORKSPACE}/configurations"
    }

    stages {
        stage('Initialize') {
            steps {
                sh './scripts/stages/01-initialize.sh'
            }
        }

        stage('Build') {
            steps {
                sh '''
                    export CONFIG_FILE=${WORKSPACE}/pipeline-config.json
                    ./scripts/stages/02-build-corrected.sh
                '''
            }
        }
    }
}
```

### GitLab CI

```yaml
variables:
  JAVA_VERSION: "jdk21u"
  TARGET_OS: "linux"
  ARCHITECTURE: "x64"
  VARIANT: "temurin"
  CONFIG_DIR: "${CI_PROJECT_DIR}/configurations"

initialize:
  script:
    - ./scripts/stages/01-initialize.sh

build:
  script:
    - export CONFIG_FILE=${CI_PROJECT_DIR}/pipeline-config.json
    - ./scripts/stages/02-build-corrected.sh
  dependencies:
    - initialize
```

### GitHub Actions

```yaml
env:
  JAVA_VERSION: jdk21u
  TARGET_OS: linux
  ARCHITECTURE: x64
  VARIANT: temurin
  CONFIG_DIR: ${{ github.workspace }}/configurations

jobs:
  initialize:
    runs-on: ubuntu-latest
    steps:
      - name: Initialize
        run: ./scripts/stages/01-initialize.sh

      - name: Upload config
        uses: actions/upload-artifact@v3
        with:
          name: build-config
          path: |
            BUILD_CONFIGURATION.json
            pipeline-config.json

  build:
    needs: initialize
    runs-on: ubuntu-latest
    steps:
      - name: Download config
        uses: actions/download-artifact@v3
        with:
          name: build-config

      - name: Build
        run: |
          export CONFIG_FILE=${GITHUB_WORKSPACE}/pipeline-config.json
          ./scripts/stages/02-build-corrected.sh
```

## Troubleshooting

### Configuration File Not Found

**Error**: `Configuration file not found: configurations/jdk21u_pipeline_config.json`

**Solution**:
1. Check `CONFIG_DIR` is set correctly
2. Verify the file exists: `ls -la ${CONFIG_DIR}/`
3. Ensure filename matches pattern: `{JAVA_VERSION}_pipeline_config.json`

### Platform Not Found

**Error**: `Platform 'aarch64Mac' not found in configuration`

**Solution**:
1. Check available platforms: `jq '.buildConfigurations | keys' config.json`
2. Verify OS and architecture are correct
3. Add missing platform to configuration file

### Variant-Specific Value Missing

**Warning**: Falls back to default value

**Solution**: Add variant-specific value to configuration:
```json
{
  "buildArgs": {
    "temurin": "--create-jre-image --create-sbom",
    "hotspot": "--create-jre-image"
  }
}
```

### Mixed Format (String and Object)

**Error**: Cannot mix string and object formats for the same field

**Solution**: Choose one format consistently:
```json
// WRONG - mixing formats
{
  "x64Linux": {
    "buildArgs": "--create-jre-image"
  },
  "aarch64Mac": {
    "buildArgs": {
      "temurin": "--create-jre-image --create-sbom"
    }
  }
}

// CORRECT - consistent format
{
  "x64Linux": {
    "buildArgs": {
      "temurin": "--create-jre-image",
      "hotspot": "--create-jre-image"
    }
  },
  "aarch64Mac": {
    "buildArgs": {
      "temurin": "--create-jre-image --create-sbom",
      "hotspot": "--create-jre-image"
    }
  }
}
```

## Migration Checklist

- [ ] Convert all `jdkNN_pipeline_config.groovy` files to JSON
- [ ] Validate JSON syntax with `jq`
- [ ] Identify fields that need variant-specific values
- [ ] Convert simple values to variant-specific objects where needed
- [ ] Test initialize script with each configuration
- [ ] Update CI/CD pipelines to use initialize stage
- [ ] Document any custom platform configurations
- [ ] Test builds for each variant (temurin, hotspot)
- [ ] Verify test lists are correct for nightly/weekly/release
- [ ] Update documentation with new configuration locations

## Benefits of New System

1. **Simpler**: JSON is easier to read and edit than Groovy
2. **CI-Agnostic**: Works with any CI system (Jenkins, GitLab, GitHub Actions)
3. **Validated**: JSON syntax is validated automatically
4. **Versioned**: Configuration files are version-controlled
5. **Testable**: Easy to test locally without Jenkins
6. **Maintainable**: Clear separation between configuration and logic
7. **Extensible**: Easy to add new platforms or variants
8. **Flexible**: Supports both simple and variant-specific values

## Resources

- [Initialize Stage Script](scripts/stages/01-initialize.sh)
- [Example Configuration](configurations/jdk21u_pipeline_config.json)
- [Conversion Tool](tools/convert-groovy-config-to-json.sh)
- [Original Groovy Configs](https://github.com/adoptium/ci-jenkins-pipelines/tree/master/pipelines/jobs/configurations)