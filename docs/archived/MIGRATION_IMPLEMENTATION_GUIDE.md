# Migration Implementation Guide: Detailed Code and Examples

## Overview

This document provides detailed implementation instructions, code examples, and technical guidance for each phase of the migration from legacy to modularized declarative pipeline. This is a companion document to the [Migration Strategy](./MIGRATION_STRATEGY.md), which provides the high-level overview and phase descriptions.

**Prerequisites**: Read the [Migration Strategy](./MIGRATION_STRATEGY.md) document first to understand the overall approach, phases, and success criteria.

## Document Purpose

This guide contains:
- Detailed code examples for each phase
- Configuration file templates
- Script implementations
- Jenkins pipeline definitions
- Validation procedures
- Troubleshooting guidance

## Quick Reference

| Phase | Section | Key Deliverables |
|-------|---------|------------------|
| 1 | [Phase 1 Implementation](#phase-1-linux-x64-jdk-build-implementation) | Linux x64 pipeline, config, validation |
| 2 | [Phase 2 Implementation](#phase-2-job-generation-automation-implementation) | Job generation tools |
| 3 | [Phase 3 Implementation](#phase-3-windows-x64-with-internal-signing-implementation) | Windows pipeline, signing scripts |
| 4 | [Phase 4 Implementation](#phase-4-mac-aarch64-implementation) | Mac pipeline, platform scripts |
| 5 | [Phase 5 Implementation](#phase-5-installers-and-packages-implementation) | Installer scripts |
| 6 | [Phase 6 Implementation](#phase-6-aqa-test-integration-implementation) | Test trigger scripts |
| 7 | [Phase 7 Implementation](#phase-7-publish-stage-implementation) | Publish scripts |
| 8 | [Phase 8 Implementation](#phase-8-jck-test-integration-implementation) | JCK trigger scripts |
| 9 | [Phase 9 Implementation](#phase-9-remaining-platforms-implementation) | Platform configs |
| 10 | [Phase 10 Implementation](#phase-10-full-ea-validation-implementation) | Validation procedures |
| 11 | [Phase 11 Implementation](#phase-11-production-cutover-implementation) | Cutover procedures |

## Phase 1: Linux x64 JDK Build Implementation

**Reference**: See [Migration Strategy - Phase 1](./MIGRATION_STRATEGY.md#phase-1-linux-x64-jdk-build-weeks-1-2) for objectives and success criteria.

### Implementation Tasks

#### 1.1 Configuration Preparation
```bash
# Convert legacy pipeline config to JSON
cd refactored_pipeline_examples/tools
./convert-groovy-config-to-json.sh \
    /path/to/legacy/jdk21u_pipeline_config.groovy \
    ../configurations/jdk21u_linux_x64_config.json

# Validate configuration
python3 ../scripts/lib/load-json-config.py \
    ../configurations/jdk21u_linux_x64_config.json \
    --validate
```

**Deliverable**: `jdk21u_linux_x64_config.json` with build-only configuration

#### 1.2 Create New Pipeline Job

**Job Name**: `build-jdk21u-linux-x64-modular`

**Jenkinsfile**:
```groovy
@Library('adoptium-jenkins-helper') _

pipeline {
    agent {
        label 'linux-x64-build'
    }

    parameters {
        string(
            name: 'RELEASE_UUID',
            defaultValue: '',
            description: 'Release UUID for tracking (optional)'
        )
        string(
            name: 'JDK_VERSION',
            defaultValue: 'jdk21u',
            description: 'JDK version to build'
        )
        string(
            name: 'BUILD_VARIANT',
            defaultValue: 'temurin',
            description: 'Build variant'
        )
        booleanParam(
            name: 'CLEAN_WORKSPACE_AFTER_STAGE',
            defaultValue: true,
            description: 'Clean workspace after each stage'
        )
        booleanParam(
            name: 'ENABLE_REPRODUCIBLE_COMPARE',
            defaultValue: true,
            description: 'Run reproducible build comparison'
        )
    }

    environment {
        CONFIG_FILE = "${WORKSPACE}/configurations/jdk21u_linux_x64_config.json"
        PLATFORM = 'linux-x64'
        TARGET_OS = 'linux'
        TARGET_ARCH = 'x64'
    }

    stages {
        stage('Initialize') {
            steps {
                script {
                    // Load configuration
                    sh """
                        python3 scripts/lib/load-json-config.py \
                            ${CONFIG_FILE} \
                            --export-env > env.properties
                    """

                    // Load environment
                    def props = readProperties file: 'env.properties'
                    props.each { key, value ->
                        env[key] = value
                    }

                    // Run initialization script
                    sh 'bash scripts/stages/01-initialize.sh'
                }
            }
            post {
                always {
                    script {
                        if (params.CLEAN_WORKSPACE_AFTER_STAGE) {
                            cleanWs(
                                deleteDirs: true,
                                patterns: [[pattern: 'stage_workspace/**', type: 'INCLUDE']]
                            )
                        }
                    }
                }
            }
        }

        stage('Build JDK') {
            steps {
                script {
                    sh 'bash scripts/stages/02-build.sh'
                }
            }
            post {
                success {
                    archiveArtifacts artifacts: 'artifacts/**/*', fingerprint: true
                }
                always {
                    script {
                        if (params.CLEAN_WORKSPACE_AFTER_STAGE) {
                            cleanWs(
                                deleteDirs: true,
                                patterns: [[pattern: 'stage_workspace/**', type: 'INCLUDE']]
                            )
                        }
                    }
                }
            }
        }

        stage('Reproducible Build Comparison') {
            when {
                expression { params.ENABLE_REPRODUCIBLE_COMPARE }
            }
            steps {
                script {
                    // Download legacy build artifact
                    def legacyBuildUrl = "https://ci.adoptium.net/job/build-scripts/job/jobs/job/jdk21u/job/jdk21u-linux-x64-temurin/lastSuccessfulBuild"

                    sh """
                        # Download legacy artifact
                        wget ${legacyBuildUrl}/artifact/workspace/target/OpenJDK21U-jdk_x64_linux_hotspot_*.tar.gz \
                            -O legacy_jdk.tar.gz

                        # Run reproducible comparison
                        bash scripts/stages/20-reproducible-compare.sh
                    """
                }
            }
            post {
                always {
                    publishHTML([
                        reportDir: 'artifacts/repro-compare',
                        reportFiles: 'repro_diff.html',
                        reportName: 'Reproducible Build Comparison'
                    ])
                }
            }
        }
    }

    post {
        always {
            script {
                // Store build metadata
                def metadata = [
                    releaseUuid: params.RELEASE_UUID,
                    jdkVersion: params.JDK_VERSION,
                    platform: env.PLATFORM,
                    buildNumber: env.BUILD_NUMBER,
                    buildUrl: env.BUILD_URL,
                    timestamp: new Date().format("yyyy-MM-dd'T'HH:mm:ss'Z'", TimeZone.getTimeZone('UTC'))
                ]
                writeJSON file: 'artifacts/build-metadata.json', json: metadata
                archiveArtifacts artifacts: 'artifacts/build-metadata.json'
            }
        }
    }
}
```

**Deliverable**: Working pipeline job for Linux x64 JDK build

#### 1.3 Validation Testing

**Test Plan**:
1. Trigger build manually
2. Verify build completes successfully
3. Compare artifacts with legacy build using `repro_compare.sh`
4. Verify reproducibility (should be byte-for-byte identical)
5. Test restart capability (fail a stage, restart from that stage)

**Success Criteria**:
- ✅ Build completes without errors
- ✅ Artifacts match legacy build (reproducible)
- ✅ Stage restart works correctly
- ✅ Build time comparable to legacy (±10%)

**Deliverable**: Validation report with reproducibility comparison results

#### 1.4 EA Beta Integration

**Tasks**:
1. Configure pipeline to trigger from jdk21u EA Beta builds
2. Set up automatic triggering (SCM polling or webhook)
3. Run 3-5 EA Beta builds for validation
4. Monitor and document any issues

**Deliverable**: Pipeline integrated with EA Beta build triggers

### Phase 1 Completion Criteria
- ✅ Linux x64 JDK build pipeline operational
- ✅ Reproducibility validated against legacy
- ✅ EA Beta builds running successfully
- ✅ Documentation updated with any learnings

**Duration**: 2 weeks
**Risk Level**: Low (single platform, build only)
**Rollback**: Continue using legacy pipeline

---

## Phase 2: Pipeline Job Generation Automation (Week 3)

### Objective
Design and implement automated Jenkins pipeline job generation from configuration files, eliminating manual job creation.

### Scope
- Job generation script/tool
- Parameter extraction from configuration
- Trigger configuration
- Job template system

### Tasks

#### 2.1 Job Generation Script

**Create**: `tools/generate-jenkins-jobs.py`

```python
#!/usr/bin/env python3
"""
Generate Jenkins pipeline jobs from configuration files.
"""

import json
import argparse
from pathlib import Path
from typing import Dict, List
import xml.etree.ElementTree as ET

class JenkinsJobGenerator:
    def __init__(self, config_file: Path, template_dir: Path):
        self.config = self._load_config(config_file)
        self.template_dir = template_dir

    def _load_config(self, config_file: Path) -> Dict:
        with open(config_file) as f:
            return json.load(f)

    def generate_job_xml(self, job_type: str = 'build') -> str:
        """
        Generate Jenkins job XML configuration.
        """
        # Load template
        template_file = self.template_dir / f'{job_type}-job-template.xml'
        tree = ET.parse(template_file)
        root = tree.getroot()

        # Update job parameters
        self._update_parameters(root)

        # Update SCM configuration
        self._update_scm(root)

        # Update triggers
        self._update_triggers(root)

        # Update build steps
        self._update_build_steps(root)

        return ET.tostring(root, encoding='unicode')

    def _update_parameters(self, root: ET.Element):
        """Update job parameters from configuration."""
        params_def = root.find('.//hudson.model.ParametersDefinitionProperty')
        if params_def is None:
            return

        param_defs = params_def.find('parameterDefinitions')

        # Add RELEASE_UUID parameter
        self._add_string_parameter(
            param_defs,
            'RELEASE_UUID',
            '',
            'Release UUID for tracking'
        )

        # Add JDK_VERSION parameter
        self._add_string_parameter(
            param_defs,
            'JDK_VERSION',
            self.config.get('jdkVersion', 'jdk21u'),
            'JDK version to build'
        )

        # Add platform-specific parameters
        platform = self.config.get('platform', {})
        self._add_string_parameter(
            param_defs,
            'TARGET_OS',
            platform.get('os', 'linux'),
            'Target operating system'
        )
        self._add_string_parameter(
            param_defs,
            'TARGET_ARCH',
            platform.get('architecture', 'x64'),
            'Target architecture'
        )

    def _add_string_parameter(
        self,
        parent: ET.Element,
        name: str,
        default: str,
        description: str
    ):
        """Add a string parameter to job configuration."""
        param = ET.SubElement(parent, 'hudson.model.StringParameterDefinition')
        ET.SubElement(param, 'name').text = name
        ET.SubElement(param, 'defaultValue').text = default
        ET.SubElement(param, 'description').text = description

    def _update_scm(self, root: ET.Element):
        """Update SCM configuration."""
        scm = root.find('.//scm')
        if scm is None:
            return

        repo_config = self.config.get('repository', {})

        # Update Git repository URL
        url_elem = scm.find('.//url')
        if url_elem is not None:
            url_elem.text = repo_config.get('url', '')

        # Update branch
        branch_elem = scm.find('.//branches/hudson.plugins.git.BranchSpec/name')
        if branch_elem is not None:
            branch_elem.text = repo_config.get('branch', 'master')

    def _update_triggers(self, root: ET.Element):
        """Update build triggers."""
        triggers = root.find('.//triggers')
        if triggers is None:
            return

        trigger_config = self.config.get('triggers', {})

        # Add SCM polling trigger if configured
        if trigger_config.get('scmPolling'):
            scm_trigger = ET.SubElement(
                triggers,
                'hudson.triggers.SCMTrigger'
            )
            ET.SubElement(scm_trigger, 'spec').text = trigger_config.get(
                'scmPollingSchedule',
                'H/15 * * * *'
            )

    def _update_build_steps(self, root: ET.Element):
        """Update build steps with Jenkinsfile path."""
        definition = root.find('.//definition')
        if definition is None:
            return

        # Update Jenkinsfile path
        script_path = definition.find('scriptPath')
        if script_path is not None:
            script_path.text = self.config.get(
                'jenkinsfilePath',
                'Jenkinsfile'
            )

def main():
    parser = argparse.ArgumentParser(
        description='Generate Jenkins pipeline jobs from configuration'
    )
    parser.add_argument(
        'config_file',
        type=Path,
        help='Path to pipeline configuration JSON file'
    )
    parser.add_argument(
        '--template-dir',
        type=Path,
        default=Path('templates'),
        help='Directory containing job templates'
    )
    parser.add_argument(
        '--output',
        type=Path,
        help='Output file for generated job XML'
    )
    parser.add_argument(
        '--job-type',
        choices=['build', 'test', 'release'],
        default='build',
        help='Type of job to generate'
    )

    args = parser.parse_args()

    generator = JenkinsJobGenerator(args.config_file, args.template_dir)
    job_xml = generator.generate_job_xml(args.job_type)

    if args.output:
        args.output.write_text(job_xml)
        print(f"Generated job XML: {args.output}")
    else:
        print(job_xml)

if __name__ == '__main__':
    main()
```

**Deliverable**: Job generation script

#### 2.2 Jenkins Job DSL Integration

**Alternative Approach**: Use Jenkins Job DSL Plugin

**Create**: `tools/generate-jobs.groovy`

```groovy
// Jenkins Job DSL script for generating pipeline jobs
def configs = [
    'jdk21u_linux_x64',
    'jdk21u_windows_x64',
    'jdk21u_mac_aarch64'
]

configs.each { configName ->
    def config = readJSON file: "configurations/${configName}_config.json"

    pipelineJob("build-${config.jdkVersion}-${config.platform.os}-${config.platform.architecture}") {
        description("Modularized build pipeline for ${config.jdkVersion} on ${config.platform.os}-${config.platform.architecture}")

        parameters {
            stringParam('RELEASE_UUID', '', 'Release UUID for tracking')
            stringParam('JDK_VERSION', config.jdkVersion, 'JDK version to build')
            stringParam('BUILD_VARIANT', config.buildVariant ?: 'temurin', 'Build variant')
            booleanParam('CLEAN_WORKSPACE_AFTER_STAGE', true, 'Clean workspace after each stage')
            booleanParam('ENABLE_REPRODUCIBLE_COMPARE', false, 'Run reproducible build comparison')
        }

        definition {
            cpsScm {
                scm {
                    git {
                        remote {
                            url(config.repository.url)
                            credentials(config.repository.credentials)
                        }
                        branch(config.repository.branch)
                    }
                }
                scriptPath(config.jenkinsfilePath ?: 'Jenkinsfile')
            }
        }

        triggers {
            if (config.triggers?.scmPolling) {
                scm(config.triggers.scmPollingSchedule ?: 'H/15 * * * *')
            }
        }

        properties {
            buildDiscarder {
                strategy {
                    logRotator {
                        numToKeepStr('50')
                        artifactNumToKeepStr('10')
                    }
                }
            }
        }
    }
}
```

**Deliverable**: Job DSL script for automated job creation

#### 2.3 Validation

**Test**:
1. Generate job configuration for Linux x64
2. Create job in Jenkins (manually or via Job DSL)
3. Verify job parameters match configuration
4. Trigger build and verify it works

**Success Criteria**:
- ✅ Jobs can be generated from configuration
- ✅ Generated jobs work correctly
- ✅ Parameters are correctly populated

**Deliverable**: Working job generation system

### Phase 2 Completion Criteria
- ✅ Job generation automation working
- ✅ Documentation for adding new platforms
- ✅ Template system established

**Duration**: 1 week
**Risk Level**: Low (tooling only)

---

## Phase 3: Windows x64 with Internal Signing (Weeks 4-5)

### Objective
Implement Windows x64 build pipeline with two-phase build process including internal signing stage.

### Scope
- **Platform**: Windows x64
- **JDK Version**: jdk21u
- **Stages**: Initialize, Build Phase 1, Internal Sign, Build Phase 2
- **Validation**: Reproducible build comparison

### Tasks

#### 3.1 Configuration Preparation

**Create**: `configurations/jdk21u_windows_x64_config.json`

```json
{
  "jdkVersion": "jdk21u",
  "buildVariant": "temurin",
  "platform": {
    "os": "windows",
    "architecture": "x64",
    "label": "windows-x64-build"
  },
  "repository": {
    "url": "https://github.com/adoptium/temurin-build.git",
    "branch": "master"
  },
  "stages": {
    "initialize": {
      "enabled": true,
      "script": "scripts/stages/01-initialize.sh"
    },
    "build_phase1": {
      "enabled": true,
      "script": "scripts/stages/02-build-phase1.sh",
      "description": "Build JDK up to signing point"
    },
    "internal_sign": {
      "enabled": true,
      "script": "scripts/stages/03-internal-sign.sh",
      "signingServer": "https://signing.adoptium.net",
      "description": "Sign Windows binaries internally"
    },
    "build_phase2": {
      "enabled": true,
      "script": "scripts/stages/04-build-phase2.sh",
      "description": "Complete JDK build after signing"
    }
  },
  "buildOptions": {
    "configureArgs": "--with-vendor-name=Eclipse Adoptium",
    "makeTargets": "product-images",
    "enableCCache": false
  }
}
```

#### 3.2 Implement Build Phase Scripts

**Create**: `scripts/stages/02-build-phase1.sh`

```bash
#!/bin/bash
set -euo pipefail

# Build Phase 1: Build up to signing point
source scripts/lib/logging-utils.sh
source scripts/lib/config-utils.sh

log_section "Build Phase 1: Pre-Signing"

# Validate environment
require_env_var "TARGET_OS" "windows"
require_env_var "TARGET_ARCH" "x64"

# Run build up to signing point
log_info "Building JDK (phase 1)..."

bash make-adopt-build-farm.sh \
    --jdk-boot-dir "${JDK_BOOT_DIR}" \
    --configure-args "${CONFIGURE_ARGS}" \
    --make-args "images" \
    --build-variant "${BUILD_VARIANT}" \
    --stop-before-signing

log_success "Build phase 1 complete"

# Copy unsigned binaries to staging
mkdir -p stage_workspace/unsigned_binaries
cp -r workspace/build/*/images/jdk/* stage_workspace/unsigned_binaries/

log_info "Unsigned binaries staged for signing"
```

**Create**: `scripts/stages/03-internal-sign.sh`

```bash
#!/bin/bash
set -euo pipefail

source scripts/lib/logging-utils.sh
source scripts/lib/config-utils.sh

log_section "Internal Signing"

# Get signing configuration
SIGNING_SERVER=$(get_config_value "stages.internal_sign.signingServer")
SIGNING_CERT=$(get_config_value "stages.internal_sign.certificate")

log_info "Signing server: ${SIGNING_SERVER}"

# Find binaries to sign
UNSIGNED_DIR="stage_workspace/unsigned_binaries"
SIGNED_DIR="stage_workspace/signed_binaries"

mkdir -p "${SIGNED_DIR}"

# Sign all .exe and .dll files
find "${UNSIGNED_DIR}" -type f \( -name "*.exe" -o -name "*.dll" \) | while read -r file; do
    log_info "Signing: $(basename "$file")"

    # Call signing service
    curl -X POST "${SIGNING_SERVER}/sign" \
        -F "file=@${file}" \
        -F "certificate=${SIGNING_CERT}" \
        -o "${SIGNED_DIR}/$(basename "$file")"

    if [ $? -eq 0 ]; then
        log_success "Signed: $(basename "$file")"
    else
        log_error "Failed to sign: $(basename "$file")"
        exit 1
    fi
done

log_success "All binaries signed"
```

**Create**: `scripts/stages/04-build-phase2.sh`

```bash
#!/bin/bash
set -euo pipefail

source scripts/lib/logging-utils.sh

log_section "Build Phase 2: Post-Signing"

# Copy signed binaries back
SIGNED_DIR="stage_workspace/signed_binaries"
BUILD_DIR="workspace/build/*/images/jdk"

log_info "Copying signed binaries back to build directory..."

find "${SIGNED_DIR}" -type f | while read -r signed_file; do
    filename=$(basename "$signed_file")

    # Find original location
    original=$(find "${BUILD_DIR}" -name "$filename" -type f)

    if [ -n "$original" ]; then
        cp "$signed_file" "$original"
        log_info "Replaced: $filename"
    fi
done

# Complete build
log_info "Completing JDK build..."

bash make-adopt-build-farm.sh \
    --continue-after-signing \
    --make-args "product-images"

log_success "Build phase 2 complete"

# Archive artifacts
mkdir -p artifacts
cp -r workspace/build/*/images/jdk/* artifacts/

log_success "Artifacts archived"
```

#### 3.3 Create Windows Pipeline

**Generate job using automation**:
```bash
python3 tools/generate-jenkins-jobs.py \
    configurations/jdk21u_windows_x64_config.json \
    --job-type build \
    --output jenkins-jobs/build-jdk21u-windows-x64.xml
```

**Or use Job DSL** to create job automatically

#### 3.4 Validation

**Test Plan**:
1. Trigger Windows x64 build
2. Verify two-phase build process works
3. Verify signing stage completes
4. Compare with legacy Windows build
5. Test restart from each stage

**Success Criteria**:
- ✅ Two-phase build works correctly
- ✅ Signing stage completes successfully
- ✅ Artifacts match legacy build
- ✅ Stage restart works from any stage

### Phase 3 Completion Criteria
- ✅ Windows x64 pipeline operational
- ✅ Internal signing integrated
- ✅ Reproducibility validated

**Duration**: 2 weeks
**Risk Level**: Medium (signing integration)

---

## Phase 4: Mac aarch64 (Week 6)

### Objective
Implement Mac aarch64 build pipeline with platform-specific considerations.

### Scope
- **Platform**: Mac aarch64
- **JDK Version**: jdk21u
- **Stages**: Initialize, Build, (Internal Sign if needed)
- **Validation**: Reproducible build comparison

### Tasks

#### 4.1 Configuration and Implementation

Similar to Windows but with Mac-specific considerations:
- Code signing requirements
- Notarization (if applicable)
- Mac-specific build options

**Create**: `configurations/jdk21u_mac_aarch64_config.json`

#### 4.2 Validation

**Test Plan**:
1. Trigger Mac aarch64 build
2. Verify build completes on Mac hardware
3. Compare with legacy Mac build
4. Test on actual Mac aarch64 hardware

**Success Criteria**:
- ✅ Mac aarch64 build works
- ✅ Artifacts match legacy
- ✅ Code signing works (if applicable)

### Phase 4 Completion Criteria
- ✅ Mac aarch64 pipeline operational
- ✅ Platform-specific features working

**Duration**: 1 week
**Risk Level**: Medium (platform-specific)

---

## Phase 5: Installers and Packages (Weeks 7-8)

### Objective
Add installer creation and package generation stages to all platforms.

### Scope
- MSI installers (Windows)
- PKG installers (Mac)
- DEB/RPM packages (Linux)
- Integration with existing tooling

### Tasks

#### 5.1 Installer Stage Implementation

**Create**: `scripts/stages/07-installer.sh`

```bash
#!/bin/bash
set -euo pipefail

source scripts/lib/logging-utils.sh
source scripts/lib/config-utils.sh

log_section "Installer Creation"

TARGET_OS=$(get_config_value "platform.os")
TARGET_ARCH=$(get_config_value "platform.architecture")

case "${TARGET_OS}" in
    windows)
        log_info "Creating MSI installer..."
        bash scripts/installers/create-windows-msi.sh
        ;;
    mac|darwin)
        log_info "Creating PKG installer..."
        bash scripts/installers/create-mac-pkg.sh
        ;;
    linux)
        log_info "Creating DEB/RPM packages..."
        bash scripts/installers/create-linux-packages.sh
        ;;
    *)
        log_error "Unsupported OS: ${TARGET_OS}"
        exit 1
        ;;
esac

log_success "Installer creation complete"
```

#### 5.2 Update Pipeline Configurations

Add installer stage to all platform configurations:

```json
{
  "stages": {
    ...
    "installer": {
      "enabled": true,
      "script": "scripts/stages/07-installer.sh",
      "description": "Create platform-specific installer"
    }
  }
}
```

#### 5.3 Validation

**Test Plan**:
1. Build with installer stage enabled
2. Verify installers are created
3. Test installers on target platforms
4. Compare with legacy installers

**Success Criteria**:
- ✅ Installers created for all platforms
- ✅ Installers work correctly
- ✅ Match legacy installer functionality

### Phase 5 Completion Criteria
- ✅ Installer creation integrated
- ✅ All platforms producing installers

**Duration**: 2 weeks
**Risk Level**: Medium (installer tooling)

---

## Phase 6: AQA Test Integration (Week 9)

### Objective
Enable remote triggering of AQA Test Pipeline for full test coverage.

### Scope
- Remote test pipeline triggering
- Test result collection
- Integration with TRSS

### Tasks

#### 6.1 Test Trigger Stage

**Create**: `scripts/stages/14-trigger-tests.sh`

```bash
#!/bin/bash
set -euo pipefail

source scripts/lib/logging-utils.sh
source scripts/lib/config-utils.sh

log_section "Trigger AQA Tests"

# Get test configuration
TEST_JENKINS_URL=$(get_config_value "testing.jenkinsUrl")
TEST_SUITES=$(get_config_value "testing.suites")
RELEASE_UUID="${RELEASE_UUID:-}"

log_info "Triggering AQA tests on: ${TEST_JENKINS_URL}"

# Trigger each test suite
for suite in ${TEST_SUITES}; do
    log_info "Triggering test suite: ${suite}"

    curl -X POST "${TEST_JENKINS_URL}/job/test-${PLATFORM}-${suite}/buildWithParameters" \
        -d "RELEASE_UUID=${RELEASE_UUID}" \
        -d "BUILD_NUMBER=${BUILD_NUMBER}" \
        -d "PLATFORM=${PLATFORM}" \
        -d "TEST_SUITE=${suite}" \
        --user "${JENKINS_USER}:${JENKINS_TOKEN}"

    log_success "Triggered: ${suite}"
done

log_success "All test suites triggered"
```

#### 6.2 Update Pipeline

Add test trigger stage to Jenkinsfile:

```groovy
stage('Trigger AQA Tests') {
    when {
        expression { params.ENABLE_TESTING }
    }
    steps {
        script {
            sh 'bash scripts/stages/14-trigger-tests.sh'
        }
    }
}
```

#### 6.3 Validation

**Test Plan**:
1. Trigger build with testing enabled
2. Verify test pipelines are triggered
3. Monitor test execution
4. Verify test results are collected

**Success Criteria**:
- ✅ Tests triggered successfully
- ✅ Test results available
- ✅ Integration with TRSS working

### Phase 6 Completion Criteria
- ✅ AQA test integration complete
- ✅ Test results flowing to TRSS

**Duration**: 1 week
**Risk Level**: Low (triggering only)

---

## Phase 7: Publish Stage (Dry-Run) (Week 10)

### Objective
Add publish stage that runs in dry-run mode for validation.

### Scope
- Artifact publishing logic
- Dry-run mode (no actual publishing)
- Validation of publish process

### Tasks

#### 7.1 Publish Stage Implementation

**Create**: `scripts/stages/15-publish.sh`

```bash
#!/bin/bash
set -euo pipefail

source scripts/lib/logging-utils.sh
source scripts/lib/config-utils.sh

log_section "Publish Artifacts"

DRY_RUN="${DRY_RUN:-true}"
PUBLISH_URL=$(get_config_value "publishing.url")

if [ "${DRY_RUN}" = "true" ]; then
    log_warn "DRY-RUN MODE: No actual publishing will occur"
fi

# Prepare artifacts for publishing
log_info "Preparing artifacts..."

ARTIFACTS_DIR="artifacts"
PUBLISH_DIR="stage_workspace/publish"

mkdir -p "${PUBLISH_DIR}"

# Copy artifacts to publish directory
cp -r "${ARTIFACTS_DIR}"/* "${PUBLISH_DIR}/"

# Generate checksums
cd "${PUBLISH_DIR}"
find . -type f -exec sha256sum {} \; > SHA256SUMS.txt

log_info "Artifacts prepared for publishing"

if [ "${DRY_RUN}" = "true" ]; then
    log_info "Would publish to: ${PUBLISH_URL}"
    log_info "Files to publish:"
    ls -lh
    log_warn "DRY-RUN: Skipping actual publish"
else
    log_info "Publishing to: ${PUBLISH_URL}"
    # Actual publish logic here
    rsync -avz --progress "${PUBLISH_DIR}/" "${PUBLISH_URL}/"
    log_success "Published successfully"
fi
```

#### 7.2 Validation

**Test Plan**:
1. Run build with publish stage (dry-run)
2. Verify publish preparation works
3. Verify checksums are generated
4. Review dry-run output

**Success Criteria**:
- ✅ Publish stage runs in dry-run mode
- ✅ Artifacts prepared correctly
- ✅ No actual publishing occurs

### Phase 7 Completion Criteria
- ✅ Publish stage implemented
- ✅ Dry-run mode working

**Duration**: 1 week
**Risk Level**: Low (dry-run only)

---

## Phase 8: JCK Test Integration (Week 11)

### Objective
Add remote triggering of JCK tests.

### Scope
- JCK test triggering
- Result collection
- Integration with test reporting

### Tasks

Similar to AQA test integration but for JCK tests.

**Create**: `scripts/stages/16-trigger-jck.sh`

### Phase 8 Completion Criteria
- ✅ JCK test integration complete

**Duration**: 1 week
**Risk Level**: Low

---

## Phase 9: Remaining Platforms (Weeks 12-14)

### Objective
Roll out modularized pipeline to all remaining platforms.

### Scope
- Linux aarch64
- Linux ppc64le
- Linux s390x
- AIX ppc64
- Alpine Linux x64
- Alpine Linux aarch64
- Windows x86-32
- Solaris x64 (if still supported)

### Tasks

#### 9.1 Platform Rollout

For each platform:
1. Create configuration file
2. Generate pipeline job
3. Run validation builds
4. Compare with legacy
5. Document any platform-specific issues

#### 9.2 Parallel Execution

Roll out multiple platforms in parallel where possible:
- Week 12: Linux aarch64, Linux ppc64le, Linux s390x
- Week 13: AIX ppc64, Alpine Linux x64, Alpine Linux aarch64
- Week 14: Windows x86-32, Solaris x64

### Phase 9 Completion Criteria
- ✅ All platforms migrated
- ✅ All platforms validated

**Duration**: 3 weeks
**Risk Level**: Medium (multiple platforms)

---

## Phase 10: Full EA Build Validation (Weeks 15-18)

### Objective
Run complete EA jdk21u builds for all platforms and validate against legacy.

### Scope
- Full EA build cycle
- All platforms
- All stages (build, test, installer, publish dry-run)
- Comparison with legacy EA builds

### Tasks

#### 10.1 EA Build Execution

**Week 15-16**: Run 2-3 complete EA builds
- Trigger all platform builds
- Run all tests
- Create all installers
- Dry-run publish

**Week 17-18**: Validation and refinement
- Compare all artifacts with legacy
- Validate reproducibility
- Fix any issues found
- Document differences

#### 10.2 Validation Criteria

For each EA build:
- ✅ All platforms build successfully
- ✅ All tests pass (or match legacy pass rate)
- ✅ All installers created
- ✅ Artifacts reproducible vs legacy
- ✅ Build times comparable to legacy
- ✅ No critical issues

#### 10.3 Parallel Operation

Run new and legacy pipelines in parallel:
- Legacy continues to publish
- New pipeline runs for validation
- Compare results
- Document any discrepancies

### Phase 10 Completion Criteria
- ✅ Multiple successful EA builds
- ✅ All platforms validated
- ✅ Reproducibility confirmed
- ✅ Performance acceptable
- ✅ Team confident in new pipeline

**Duration**: 4 weeks
**Risk Level**: High (full system validation)

---

## Phase 11: Production Cutover (Week 19-20)

### Objective
Switch from legacy to new pipeline for EA build publishing.

### Scope
- Disable legacy EA publishing
- Enable new pipeline publishing
- Monitor first production builds
- Rollback plan ready

### Tasks

#### 11.1 Pre-Cutover Checklist

- ✅ All platforms validated
- ✅ Multiple successful EA builds
- ✅ Team trained on new pipeline
- ✅ Documentation complete
- ✅ Monitoring in place
- ✅ Rollback plan documented
- ✅ Stakeholders informed

#### 11.2 Cutover Process

**Day 1**: Preparation
- Final validation build
- Review all systems
- Confirm rollback plan

**Day 2**: Cutover
- Disable legacy EA publishing
- Enable new pipeline publishing (DRY_RUN=false)
- Trigger first production EA build
- Monitor closely

**Day 3-7**: Monitoring
- Monitor first production builds
- Address any issues immediately
- Collect feedback
- Document lessons learned

#### 11.3 Rollback Plan

If critical issues occur:
1. Immediately disable new pipeline publishing
2. Re-enable legacy pipeline
3. Investigate issues
4. Fix and re-validate
5. Plan new cutover date

### Phase 11 Completion Criteria
- ✅ New pipeline publishing EA builds
- ✅ Legacy pipeline deprecated for EA
- ✅ No critical issues
- ✅ Team comfortable with new system

**Duration**: 2 weeks
**Risk Level**: High (production cutover)

---

## Success Metrics

### Technical Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Build Reproducibility | 100% | Byte-for-byte comparison with legacy |
| Build Time | ±10% of legacy | Average across all platforms |
| Stage Restart Success | 100% | All stages restartable |
| Test Pass Rate | Match legacy | Compare with legacy test results |
| Artifact Quality | Match legacy | Functional testing |

### Operational Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Pipeline Reliability | >95% | Successful builds / total builds |
| Time to Restart | <5 minutes | From failure to restart |
| Configuration Changes | <1 hour | Time to add new platform |
| Documentation Coverage | 100% | All features documented |

### Business Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Release Confidence | High | Team survey |
| Operational Efficiency | +20% | Time saved in operations |
| Issue Resolution Time | -30% | Faster debugging with restartability |

## Risk Management

### High-Risk Areas

1. **Windows Internal Signing**
   - Risk: Signing integration may fail
   - Mitigation: Extensive testing, fallback to legacy signing
   - Contingency: Manual signing process documented

2. **Production Cutover**
   - Risk: Issues in first production build
   - Mitigation: Multiple validation builds, rollback plan
   - Contingency: Immediate rollback to legacy

3. **Multi-Platform Coordination**
   - Risk: Platform-specific issues
   - Mitigation: Phased rollout, platform-by-platform validation
   - Contingency: Roll back individual platforms

### Medium-Risk Areas

1. **Reproducibility Validation**
   - Risk: Builds may not be byte-for-byte identical
   - Mitigation: Extensive comparison testing
   - Contingency: Document acceptable differences

2. **Test Integration**
   - Risk: Test triggering may fail
   - Mitigation: Thorough testing of trigger mechanism
   - Contingency: Manual test triggering

### Low-Risk Areas

1. **Job Generation**
   - Risk: Generated jobs may be incorrect
   - Mitigation: Validation before deployment
   - Contingency: Manual job creation

2. **Documentation**
   - Risk: Incomplete documentation
   - Mitigation: Document as you go
   - Contingency: Post-migration documentation sprint

## Communication Plan

### Stakeholders

1. **Build Team**: Daily updates during active phases
2. **Release Team**: Weekly updates, critical issues immediately
3. **QA Team**: Updates before test integration phases
4. **Management**: Bi-weekly status reports

### Status Reporting

**Weekly Status Report Template**:
```
Migration Status Report - Week X

Current Phase: [Phase Name]
Progress: [X%]
Status: [On Track / At Risk / Delayed]

Completed This Week:
- [Item 1]
- [Item 2]

Planned Next Week:
- [Item 1]
- [Item 2]

Risks/Issues:
- [Issue 1]: [Status]
- [Issue 2]: [Status]

Metrics:
- Builds Completed: X
- Reproducibility: X%
- Issues Found: X
- Issues Resolved: X
```

## Rollback Procedures

### Per-Phase Rollback

Each phase has a rollback procedure:

1. **Identify Issue**: Determine if rollback needed
2. **Notify Stakeholders**: Inform team of rollback
3. **Execute Rollback**: Follow phase-specific procedure
4. **Validate**: Confirm legacy system working
5. **Investigate**: Root cause analysis
6. **Plan Recovery**: Fix and re-attempt

### Emergency Rollback

For critical production issues:

1. **Immediate Action**: Disable new pipeline
2. **Enable Legacy**: Re-activate legacy pipeline
3. **Notify All**: Emergency communication
4. **Investigate**: Urgent root cause analysis
5. **Fix**: Address critical issue
6. **Re-validate**: Full validation before retry

## Timeline Summary

| Phase | Duration | Weeks | Risk | Dependencies |
|-------|----------|-------|------|--------------|
| 1. Linux x64 JDK Build | 2 weeks | 1-2 | Low | None |
| 2. Job Generation | 1 week | 3 | Low | Phase 1 |
| 3. Windows x64 + Signing | 2 weeks | 4-5 | Medium | Phase 2 |
| 4. Mac aarch64 | 1 week | 6 | Medium | Phase 2 |
| 5. Installers & Packages | 2 weeks | 7-8 | Medium | Phases 3-4 |
| 6. AQA Test Integration | 1 week | 9 | Low | Phase 5 |
| 7. Publish Stage (Dry-Run) | 1 week | 10 | Low | Phase 6 |
| 8. JCK Test Integration | 1 week | 11 | Low | Phase 6 |
| 9. Remaining Platforms | 3 weeks | 12-14 | Medium | Phases 3-8 |
| 10. Full EA Validation | 4 weeks | 15-18 | High | Phase 9 |
| 11. Production Cutover | 2 weeks | 19-20 | High | Phase 10 |

**Total Duration**: 20 weeks (approximately 5 months)

## Conclusion

This migration plan provides a structured, phased approach to transitioning from the legacy monolithic pipeline to the new modularized declarative pipeline architecture. The plan emphasizes:

1. **Incremental Progress**: Start small, expand gradually
2. **Continuous Validation**: Verify at each step
3. **Risk Mitigation**: Rollback capability at every phase
4. **Reproducibility**: Ensure builds match legacy
5. **Automation**: Generate jobs from configuration
6. **Parallel Operation**: Run alongside legacy for validation

By following this plan, the migration can be completed with minimal risk and maximum confidence in the new system.

---

**Related Documentation:**
- [CI-Agnostic Architecture](../CI_AGNOSTIC_ARCHITECTURE.md)
- [Pipeline Orchestration Architecture](./PIPELINE_ORCHESTRATION_ARCHITECTURE.md)
- [Restartability Guide](./RESTARTABILITY_GUIDE.md)
- [Configuration Guide](./CONFIGURATION_GUIDE.md)
- [Build Monitoring and Traceability](./BUILD_MONITORING_TRACEABILITY.md)