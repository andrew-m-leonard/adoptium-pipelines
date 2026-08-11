# Declarative Pipeline Restartability Guide

## The Reliability Principle

**For reliable, restartable declarative pipelines: Always use `archiveArtifacts` + `copyArtifacts`**

This approach prioritizes **reliability and consistency** over performance optimization.

## Why Reliability Matters

When building critical software like OpenJDK:
- **Build failures are expensive** - JDK builds can take hours
- **Debugging is critical** - need to inspect artifacts between stages
- **Reproducibility is essential** - must be able to restart from any point
- **Audit trail is required** - need clear record of what was produced

**Consistent, reliable behavior trumps micro-optimizations.**

## The Reliable Pattern

Every stage follows the same reliable pattern:

```groovy
stage('Stage Name') {
    agent { label 'appropriate-label' }
    steps {
        script {
            // 1. Retrieve inputs from archive (if needed)
            if (needsInputs) {
                copyArtifacts(
                    projectName: env.JOB_NAME,
                    selector: specific(env.BUILD_NUMBER),
                    filter: 'path/to/needed/files/**/*',
                    target: '.'
                )
            }

            // 2. Do the work
            performWork()

            // 3. Archive outputs for next stage
            archiveArtifacts artifacts: 'path/to/outputs/**/*',
                           fingerprint: true
        }
    }
}
```

**This pattern works reliably:**
- ✅ On first run
- ✅ On restart from any stage
- ✅ On any agent/node
- ✅ Days or weeks later (within retention policy)

## Why This Approach is Reliable

### 1. **Predictable Behavior**
Same code path every time - no conditional logic based on run state.

### 2. **No Hidden Dependencies**
Each stage explicitly declares what it needs via `copyArtifacts`.

### 3. **Persistent State**
Artifacts survive pipeline completion, node failures, Jenkins restarts.

### 4. **Inspectable**
Can download and examine artifacts between stages for debugging.

### 5. **Testable**
Can test each stage independently by providing archived inputs.

### 6. **Auditable**
Clear record of what each stage produced and when.

## OpenJDK Pipeline: Reliable Stage Design

### Stage 1: Build JDK
```groovy
stage('Build') {
    agent { label "${buildConfig.NODE_LABEL}" }
    steps {
        script {
            println "=== Building JDK ==="

            // No inputs - this is the first stage

            // Execute build
            sh './build-jdk.sh'

            // Create build metadata for downstream stages
            def buildMetadata = [
                version: extractVersion(),
                buildNumber: env.BUILD_NUMBER,
                timestamp: currentBuild.startTimeInMillis,
                platform: "${buildConfig.ARCHITECTURE}_${buildConfig.TARGET_OS}",
                variant: buildConfig.VARIANT
            ]
            writeJSON file: 'build-metadata.json', json: buildMetadata

            // Archive EVERYTHING needed by downstream stages
            archiveArtifacts artifacts: '''
                workspace/target/**/*.tar.gz,
                workspace/target/**/*.zip,
                workspace/target/metadata/**/*,
                build-metadata.json,
                build-config.json
            ''', fingerprint: true, allowEmptyArchive: false

            println "=== Build Complete - Artifacts Archived ==="
        }
    }
}
```

**Reliability guarantees:**
- All outputs explicitly archived
- Metadata persisted to JSON
- Fingerprinting enabled for tracking
- Will fail if no artifacts produced

### Stage 2: Sign Artifacts
```groovy
stage('Sign Artifacts') {
    agent { label 'worker' }
    when {
        expression { params.ENABLE_SIGNER }
    }
    steps {
        script {
            println "=== Signing Artifacts ==="

            // Reliably retrieve build outputs
            println "Retrieving build artifacts from archive..."
            copyArtifacts(
                projectName: env.JOB_NAME,
                selector: specific(env.BUILD_NUMBER),
                filter: '''
                    workspace/target/**/*.tar.gz,
                    workspace/target/**/*.zip,
                    build-metadata.json,
                    build-config.json
                ''',
                target: '.',
                fingerprintArtifacts: true
            )

            // Load metadata
            def buildMetadata = readJSON file: 'build-metadata.json'
            def buildConfig = readJSON file: 'build-config.json'

            println "Signing ${buildMetadata.variant} version ${buildMetadata.version}"

            // Perform signing
            sh './sign-artifacts.sh'

            // Create signing metadata
            def signingMetadata = [
                signedAt: currentBuild.startTimeInMillis,
                signedBy: env.BUILD_TAG,
                originalBuild: buildMetadata.buildNumber
            ]
            writeJSON file: 'signing-metadata.json', json: signingMetadata

            // Archive signed artifacts
            archiveArtifacts artifacts: '''
                signed/**/*.tar.gz,
                signed/**/*.zip,
                signing-metadata.json,
                checksums.txt
            ''', fingerprint: true, allowEmptyArchive: false

            println "=== Signing Complete - Artifacts Archived ==="
        }
    }
}
```

**Reliability guarantees:**
- Explicitly retrieves all needed inputs
- Works identically on first run or restart
- Persists signing metadata
- Downstream stages can verify signing occurred

### Stage 3: Build Installers
```groovy
stage('Build Installers') {
    agent { label 'worker' }
    when {
        expression { params.ENABLE_INSTALLERS }
    }
    steps {
        script {
            println "=== Building Installers ==="

            // Retrieve signed artifacts
            println "Retrieving signed artifacts from archive..."
            copyArtifacts(
                projectName: env.JOB_NAME,
                selector: specific(env.BUILD_NUMBER),
                filter: '''
                    signed/**/*,
                    build-metadata.json,
                    build-config.json
                ''',
                target: '.'
            )

            // Load metadata
            def buildMetadata = readJSON file: 'build-metadata.json'

            println "Building installers for version ${buildMetadata.version}"

            // Build installers
            sh './build-installers.sh'

            // Create installer metadata
            def installerMetadata = [
                builtAt: currentBuild.startTimeInMillis,
                baseVersion: buildMetadata.version,
                installerTypes: ['msi', 'pkg', 'deb', 'rpm']
            ]
            writeJSON file: 'installer-metadata.json', json: installerMetadata

            // Archive installers
            archiveArtifacts artifacts: '''
                installers/**/*,
                installer-metadata.json
            ''', fingerprint: true, allowEmptyArchive: false

            println "=== Installers Complete - Artifacts Archived ==="
        }
    }
}
```

**Reliability guarantees:**
- Independent of previous stage execution state
- Can be restarted days later
- Metadata chain preserved (build → signing → installer)

### Stage 4: Run Tests
```groovy
stage('Smoke Tests') {
    agent { label 'worker' }
    when {
        expression { params.ENABLE_TESTS }
    }
    steps {
        script {
            println "=== Running Smoke Tests ==="

            // Retrieve JDK to test
            println "Retrieving JDK binary from archive..."
            copyArtifacts(
                projectName: env.JOB_NAME,
                selector: specific(env.BUILD_NUMBER),
                filter: '''
                    workspace/target/**/*.tar.gz,
                    build-metadata.json
                ''',
                target: '.'
            )

            // Load metadata
            def buildMetadata = readJSON file: 'build-metadata.json'

            println "Testing version ${buildMetadata.version}"

            // Run tests
            def testResult = sh(
                script: './run-smoke-tests.sh',
                returnStatus: true
            )

            // Create test metadata
            def testMetadata = [
                testedAt: currentBuild.startTimeInMillis,
                testResult: testResult == 0 ? 'PASS' : 'FAIL',
                testedVersion: buildMetadata.version
            ]
            writeJSON file: 'test-metadata.json', json: testMetadata

            // Archive test results
            archiveArtifacts artifacts: '''
                test-results/**/*,
                test-metadata.json
            ''', fingerprint: true, allowEmptyArchive: true

            if (testResult != 0) {
                error("Smoke tests failed")
            }

            println "=== Tests Complete - Results Archived ==="
        }
    }
}
```

**Reliability guarantees:**
- Tests run against exact archived binary
- Test results preserved for analysis
- Can rerun tests without rebuilding

## Complete Reliable Stage Flow

```
┌────────────────────────────────────────────────────────────┐
│ Build Stage                                                │
│ • Compiles JDK                                             │
│ • Archives: binaries + metadata                            │
│ • Reliable: All outputs explicitly saved                   │
└──────────────────────┬─────────────────────────────────────┘
                       │ Persistent Archive
                       ▼
┌────────────────────────────────────────────────────────────┐
│ Sign Artifacts Stage                                       │
│ • copyArtifacts: Retrieves binaries                        │
│ • Signs artifacts                                          │
│ • Archives: signed binaries + signing metadata             │
│ • Reliable: Can restart from here anytime                  │
└──────────────────────┬─────────────────────────────────────┘
                       │ Persistent Archive
                       ▼
┌────────────────────────────────────────────────────────────┐
│ Build Installers Stage                                     │
│ • copyArtifacts: Retrieves signed binaries                 │
│ • Builds installers                                        │
│ • Archives: installers + installer metadata                │
│ • Reliable: Independent of previous execution              │
└──────────────────────┬─────────────────────────────────────┘
                       │ Persistent Archive
                       ▼
┌────────────────────────────────────────────────────────────┐
│ Test Stage                                                 │
│ • copyArtifacts: Retrieves JDK binary                      │
│ • Runs tests                                               │
│ • Archives: test results + test metadata                   │
│ • Reliable: Can retest without rebuild                     │
└────────────────────────────────────────────────────────────┘
```

## Metadata Chain for Reliability

Each stage adds to the metadata chain:

```json
// build-metadata.json (from Build stage)
{
  "version": "21.0.1+12",
  "buildNumber": "123",
  "timestamp": 1234567890,
  "platform": "x64_linux",
  "variant": "temurin"
}

// signing-metadata.json (from Sign stage)
{
  "signedAt": 1234567900,
  "signedBy": "jenkins-build-123",
  "originalBuild": "123",
  "signatureAlgorithm": "SHA256withRSA"
}

// installer-metadata.json (from Installer stage)
{
  "builtAt": 1234567910,
  "baseVersion": "21.0.1+12",
  "installerTypes": ["msi", "pkg"],
  "signedBuild": "123"
}

// test-metadata.json (from Test stage)
{
  "testedAt": 1234567920,
  "testResult": "PASS",
  "testedVersion": "21.0.1+12",
  "testSuite": "smoke"
}
```

This metadata chain provides:
- **Traceability**: Track artifacts through entire pipeline
- **Auditability**: Know exactly what was done when
- **Debuggability**: Understand state at each stage
- **Reliability**: Verify each stage completed correctly

## Testing Reliability

### Reliability Test Checklist

For each stage, verify:

1. **First Run Test**
   - [ ] Stage completes successfully
   - [ ] All expected artifacts are archived
   - [ ] Metadata files are created and archived
   - [ ] Next stage can retrieve artifacts

2. **Restart Test**
   - [ ] Add `error("Test")` to stage
   - [ ] Run pipeline - stage fails
   - [ ] Remove error
   - [ ] Restart from that stage
   - [ ] Stage retrieves all needed artifacts
   - [ ] Stage completes successfully
   - [ ] Produces same outputs as first run

3. **Delayed Restart Test**
   - [ ] Run pipeline to completion
   - [ ] Wait 24 hours
   - [ ] Restart from middle stage
   - [ ] Verify artifacts still available
   - [ ] Verify stage completes successfully

4. **Cross-Node Test**
   - [ ] Run pipeline on node A
   - [ ] Restart stage on node B
   - [ ] Verify artifacts retrieved correctly
   - [ ] Verify no node-specific dependencies

## Common Reliability Pitfalls

### ❌ Unreliable: Workspace Dependencies
```groovy
stage('Build') {
    steps {
        sh './build.sh'
        // Files left in workspace - NOT RELIABLE
    }
}

stage('Sign') {
    steps {
        // Assumes workspace files exist - FAILS on restart
        sh './sign.sh workspace/file.tar.gz'
    }
}
```

**Problem**: Workspace may be cleaned, on different node, or unavailable.

### ✅ Reliable: Archived Dependencies
```groovy
stage('Build') {
    steps {
        sh './build.sh'
        archiveArtifacts 'workspace/**/*'  // RELIABLE
    }
}

stage('Sign') {
    steps {
        copyArtifacts filter: 'workspace/**/*'  // RELIABLE
        sh './sign.sh workspace/file.tar.gz'
    }
}
```

**Benefit**: Works on any node, any time, after any failure.

### ❌ Unreliable: Pipeline Variables
```groovy
def version = ""

stage('Build') {
    steps {
        script {
            version = "1.0.0"  // UNRELIABLE - lost on restart
        }
    }
}

stage('Sign') {
    steps {
        script {
            println version  // EMPTY on restart!
        }
    }
}
```

**Problem**: Variables don't persist across restarts.

### ✅ Reliable: JSON Metadata
```groovy
stage('Build') {
    steps {
        script {
            def metadata = [version: "1.0.0"]
            writeJSON file: 'metadata.json', json: metadata
            archiveArtifacts 'metadata.json'  // RELIABLE
        }
    }
}

stage('Sign') {
    steps {
        script {
            copyArtifacts filter: 'metadata.json'
            def metadata = readJSON file: 'metadata.json'
            println metadata.version  // RELIABLE - works on restart
        }
    }
}
```

**Benefit**: Metadata persists and is available on restart.

## Implementation Checklist

For reliable, restartable stages:

- [ ] Every stage archives all outputs
- [ ] Every stage uses `copyArtifacts` for inputs
- [ ] All metadata stored in JSON files
- [ ] JSON files archived with artifacts
- [ ] No dependencies on pipeline variables
- [ ] No assumptions about workspace state
- [ ] Fingerprinting enabled on archives
- [ ] `allowEmptyArchive: false` for critical artifacts
- [ ] Clear logging of what's being retrieved/archived
- [ ] Each stage tested for restart capability

## Summary: The Reliability Contract

**Each stage promises:**
1. I will archive everything I produce
2. I will retrieve everything I need from archives
3. I will not depend on previous stage execution state
4. I will persist all important data to JSON files
5. I will work the same way on first run and restart

**This contract ensures:**
- ✅ Predictable behavior
- ✅ Debuggable failures
- ✅ Restartable from any point
- ✅ Auditable artifact trail
- ✅ Testable in isolation

**Reliability over optimization. Consistency over cleverness.**