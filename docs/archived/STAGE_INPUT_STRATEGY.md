# Stage Input Strategy: Workspace vs Archive

## The Critical Question

**Should a stage rely on inputs from the current WORKSPACE, or always retrieve from archives?**

## The Problem

When a stage runs, it could be in one of two scenarios:

### Scenario 1: Normal Sequential Run
```
Build stage just ran
  ↓
Build artifacts are in WORKSPACE
  ↓
Sign stage starts
  ↓
Should Sign use artifacts from WORKSPACE?
```

### Scenario 2: Restart from Stage
```
Build stage ran hours/days ago
  ↓
User clicks "Restart from Sign"
  ↓
Sign stage starts with potentially stale/empty WORKSPACE
  ↓
Should Sign use artifacts from WORKSPACE? (NO - might be wrong!)
```

## The Danger of Using WORKSPACE

**Problem:** WORKSPACE might contain:
- ❌ Artifacts from a different build number
- ❌ Artifacts from a different branch
- ❌ Partial/corrupted artifacts from failed run
- ❌ Nothing at all (workspace cleaned)

**Example of the problem:**
```groovy
stage('Build') {
    steps {
        sh './build.sh'
        // Artifacts in workspace/target/
    }
}

stage('Sign') {
    steps {
        // ❌ DANGEROUS - assumes workspace has correct artifacts
        sh 'sign workspace/target/*.tar.gz'
    }
}
```

**What can go wrong:**
1. Normal run: Works fine (Build just ran)
2. Restart from Sign: Might sign wrong artifacts or fail
3. Different node: Workspace is empty
4. After workspace cleanup: No artifacts

## How to Detect "Restart from Stage"

### Method 1: Check if Previous Build Exists

```groovy
def isRestart() {
    return currentBuild.previousBuild != null &&
           currentBuild.previousBuild.number == currentBuild.number
}
```

**Problem:** This doesn't work! When you restart, Jenkins creates a new build number.

### Method 2: Check Build Causes

```groovy
def isRestart() {
    def causes = currentBuild.getBuildCauses()
    return causes.any { it._class == 'org.jenkinsci.plugins.workflow.support.steps.build.BuildUpstreamCause' }
}
```

**Problem:** Unreliable - build causes vary by Jenkins version and plugins.

### Method 3: Environment Variable

```groovy
def isRestart() {
    return env.JENKINS_RESTART_FROM_STAGE != null
}
```

**Problem:** No such environment variable exists by default.

### The Truth

**There is no reliable way to detect if a stage is running from a restart.**

## The Solution: Always Use Archives

### The Reliable Pattern with Fallback

**ALWAYS retrieve inputs from archives, with fallback for restart scenarios.**

```groovy
stage('Sign') {
    steps {
        script {
            // Try to retrieve from current build first (normal run)
            // If not found, fallback to previous build (restart scenario)
            def retrieved = false

            try {
                copyArtifacts(
                    projectName: env.JOB_NAME,
                    selector: specific(env.BUILD_NUMBER),
                    filter: 'workspace/target/**/*',
                    target: '.',
                    optional: false
                )
                retrieved = true
                println "Retrieved artifacts from current build ${env.BUILD_NUMBER}"
            } catch (Exception e) {
                println "No artifacts in current build, trying previous build..."

                if (currentBuild.previousBuild) {
                    copyArtifacts(
                        projectName: env.JOB_NAME,
                        selector: specific(currentBuild.previousBuild.number.toString()),
                        filter: 'workspace/target/**/*',
                        target: '.'
                    )
                    retrieved = true
                    println "Retrieved artifacts from previous build ${currentBuild.previousBuild.number}"
                } else {
                    error("No artifacts found in current or previous build!")
                }
            }

            // Now we KNOW we have the correct artifacts
            sh './sign-artifacts.sh'

            // Archive for next stage
            archiveArtifacts artifacts: 'signed/**/*'
        }
    }
}
```

### Why This Pattern is Necessary

**The Build Number Problem:**

When you restart from a stage, Jenkins creates a **NEW build number**:

```
Original run:
  Build #100: Build → Sign → Installer
  Artifacts archived under build #100

Restart from Sign:
  Build #101: Sign → Installer (restart)
  Build #101 has NO artifacts from Build stage
  Build #100 has the artifacts we need
```

**The Solution:**
1. Try `env.BUILD_NUMBER` first (works for normal sequential run)
2. Fallback to `currentBuild.previousBuild.number` (works for restart)

### Why This Works

1. **Normal run:** Build stage archived under #100, Sign retrieves from #100 ✅
2. **Restart:** Build artifacts under #100, Sign (build #101) retrieves from #100 ✅
3. **Different node:** Archives are on Jenkins master, available everywhere ✅
4. **Days later:** Archives persist (within retention policy) ✅

### The Key Insight

**Don't try to detect restart - just always use the same reliable pattern.**

## Detailed Example: Build → Sign → Installer

### Stage 1: Build (First Stage)

```groovy
stage('Build') {
    agent { label 'build-node' }
    steps {
        script {
            println "=== Building JDK ==="

            // Clean workspace to ensure fresh build
            cleanWs()

            // Checkout code
            checkout scm

            // Build
            sh './build-jdk.sh'

            // Create metadata
            def buildMetadata = [
                version: '21.0.1',
                buildNumber: env.BUILD_NUMBER,
                timestamp: currentBuild.startTimeInMillis,
                gitCommit: env.GIT_COMMIT
            ]
            writeJSON file: 'build-metadata.json', json: buildMetadata

            // Archive EVERYTHING needed by downstream stages
            archiveArtifacts artifacts: '''
                workspace/target/**/*.tar.gz,
                workspace/target/**/*.zip,
                build-metadata.json
            ''', fingerprint: true, allowEmptyArchive: false

            println "=== Build Complete - Artifacts Archived ==="
        }
    }
}
```

**Key points:**
- ✅ Cleans workspace (fresh start)
- ✅ Archives all outputs
- ✅ Archives metadata
- ✅ No assumptions about previous state

### Stage 2: Sign (Middle Stage)

```groovy
stage('Sign') {
    agent { label 'sign-node' }
    steps {
        script {
            println "=== Signing Artifacts ==="

            // Clean workspace to avoid confusion
            cleanWs()

            // Retrieve from archive with fallback for restart
            println "Retrieving artifacts from archive..."
            def buildNumber = env.BUILD_NUMBER
            def retrieved = false

            try {
                // Try current build first (normal run)
                copyArtifacts(
                    projectName: env.JOB_NAME,
                    selector: specific(buildNumber),
                    filter: '''
                        workspace/target/**/*,
                        build-metadata.json
                    ''',
                    target: '.',
                    fingerprintArtifacts: true,
                    optional: false
                )
                retrieved = true
                println "Retrieved artifacts from build ${buildNumber}"
            } catch (Exception e) {
                // Fallback to previous build (restart scenario)
                if (currentBuild.previousBuild) {
                    buildNumber = currentBuild.previousBuild.number.toString()
                    println "Trying previous build ${buildNumber}..."
                    copyArtifacts(
                        projectName: env.JOB_NAME,
                        selector: specific(buildNumber),
                        filter: '''
                            workspace/target/**/*,
                            build-metadata.json
                        ''',
                        target: '.',
                        fingerprintArtifacts: true
                    )
                    retrieved = true
                    println "Retrieved artifacts from previous build ${buildNumber}"
                } else {
                    error("No artifacts found in current or previous build!")
                }
            }

            // Verify we got what we need
            def buildMetadata = readJSON file: 'build-metadata.json'
            println "Signing version ${buildMetadata.version}"

            // Find artifacts to sign
            def artifacts = findFiles(glob: 'workspace/target/**/*.tar.gz')
            if (artifacts.length == 0) {
                error("No artifacts found to sign!")
            }
            println "Found ${artifacts.length} artifacts to sign"

            // Sign artifacts
            sh './sign-artifacts.sh'

            // Create signing metadata
            def signMetadata = [
                signedAt: currentBuild.startTimeInMillis,
                baseVersion: buildMetadata.version,
                certificate: 'production-cert'
            ]
            writeJSON file: 'sign-metadata.json', json: signMetadata

            // Archive signed artifacts
            archiveArtifacts artifacts: '''
                signed/**/*,
                sign-metadata.json,
                build-metadata.json
            ''', fingerprint: true, allowEmptyArchive: false

            println "=== Signing Complete - Artifacts Archived ==="
        }
    }
}
```

**Key points:**
- ✅ Cleans workspace (no stale data)
- ✅ ALWAYS retrieves from archive
- ✅ Verifies inputs exist
- ✅ Archives outputs + metadata
- ✅ Works for normal run AND restart

### Stage 3: Installer (Final Stage)

```groovy
stage('Installer') {
    agent { label 'installer-node' }
    steps {
        script {
            println "=== Building Installers ==="

            // Clean workspace
            cleanWs()

            // Retrieve from archive with fallback for restart
            println "Retrieving signed artifacts from archive..."
            def buildNumber = env.BUILD_NUMBER

            try {
                // Try current build first
                copyArtifacts(
                    projectName: env.JOB_NAME,
                    selector: specific(buildNumber),
                    filter: '''
                        signed/**/*,
                        build-metadata.json,
                        sign-metadata.json
                    ''',
                    target: '.',
                    fingerprintArtifacts: true,
                    optional: false
                )
                println "Retrieved artifacts from build ${buildNumber}"
            } catch (Exception e) {
                // Fallback to previous build
                if (currentBuild.previousBuild) {
                    buildNumber = currentBuild.previousBuild.number.toString()
                    println "Trying previous build ${buildNumber}..."
                    copyArtifacts(
                        projectName: env.JOB_NAME,
                        selector: specific(buildNumber),
                        filter: '''
                            signed/**/*,
                            build-metadata.json,
                            sign-metadata.json
                        ''',
                        target: '.',
                        fingerprintArtifacts: true
                    )
                    println "Retrieved artifacts from previous build ${buildNumber}"
                } else {
                    error("No artifacts found!")
                }
            }

            // Verify inputs
            def buildMetadata = readJSON file: 'build-metadata.json'
            def signMetadata = readJSON file: 'sign-metadata.json'
            println "Building installers for version ${buildMetadata.version}"
            println "Using artifacts signed at ${signMetadata.signedAt}"

            // Build installers
            sh './build-installers.sh'

            // Archive installers
            archiveArtifacts artifacts: '''
                installers/**/*,
                build-metadata.json
            ''', fingerprint: true, allowEmptyArchive: false

            println "=== Installers Complete ==="
        }
    }
}
```

**Key points:**
- ✅ Cleans workspace
- ✅ ALWAYS retrieves from archive
- ✅ Retrieves metadata chain
- ✅ Verifies inputs
- ✅ Archives outputs

## Why Clean Workspace?

```groovy
stage('Sign') {
    steps {
        script {
            // Clean workspace FIRST
            cleanWs()

            // Then retrieve from archive
            copyArtifacts(...)
        }
    }
}
```

**Benefits:**
1. **No confusion** - Workspace only contains what you just retrieved
2. **No stale data** - Previous run artifacts are gone
3. **Predictable state** - Always start from known clean state
4. **Easier debugging** - Know exactly what's in workspace

## The Anti-Pattern: Conditional Logic

**DON'T DO THIS:**

```groovy
stage('Sign') {
    steps {
        script {
            // ❌ WRONG - trying to detect restart
            def isRestart = /* some detection logic */

            if (isRestart) {
                // Retrieve from archive
                copyArtifacts(...)
            } else {
                // Use workspace
                // Assumes Build just ran
            }

            sh './sign-artifacts.sh'
        }
    }
}
```

**Problems:**
1. Detection logic is unreliable
2. Two different code paths (harder to test)
3. Workspace assumption is dangerous
4. More complex, more bugs

**DO THIS INSTEAD:**

```groovy
stage('Sign') {
    steps {
        script {
            // ✅ CORRECT - always same pattern
            cleanWs()
            copyArtifacts(...)
            sh './sign-artifacts.sh'
            archiveArtifacts(...)
        }
    }
}
```

**Benefits:**
1. One code path (easier to test)
2. Works for all scenarios
3. No detection needed
4. Simpler, more reliable

## Performance Considerations

**Question:** "Isn't it wasteful to archive and retrieve artifacts every time?"

**Answer:** No, because:

1. **Archives are fast** - Jenkins uses efficient storage
2. **Reliability > Speed** - JDK builds take hours, archive/retrieve takes seconds
3. **Debugging value** - Can inspect artifacts between stages
4. **Restart value** - Can restart from any point
5. **Audit trail** - Clear record of what was produced

**Example timing:**
- Build JDK: 2 hours
- Archive artifacts (500MB): 30 seconds
- Retrieve artifacts: 20 seconds
- **Total overhead: < 1% of build time**

## Best Practices Summary

### 1. Always Clean Workspace

```groovy
stage('Any Stage') {
    steps {
        script {
            cleanWs()  // Start fresh
            // ...
        }
    }
}
```

### 2. Always Retrieve from Archive (with Fallback)

```groovy
stage('Any Stage Except First') {
    steps {
        script {
            // Try current build, fallback to previous
            def buildNumber = env.BUILD_NUMBER
            try {
                copyArtifacts(
                    projectName: env.JOB_NAME,
                    selector: specific(buildNumber),
                    filter: 'path/to/inputs/**/*',
                    target: '.',
                    optional: false
                )
            } catch (Exception e) {
                if (currentBuild.previousBuild) {
                    buildNumber = currentBuild.previousBuild.number.toString()
                    copyArtifacts(
                        projectName: env.JOB_NAME,
                        selector: specific(buildNumber),
                        filter: 'path/to/inputs/**/*',
                        target: '.'
                    )
                } else {
                    error("No artifacts found!")
                }
            }
            // ...
        }
    }
}
```

### 3. Always Verify Inputs

```groovy
stage('Sign') {
    steps {
        script {
            copyArtifacts(...)

            // Verify we got what we need
            def artifacts = findFiles(glob: 'workspace/target/**/*.tar.gz')
            if (artifacts.length == 0) {
                error("No artifacts found!")
            }

            // ...
        }
    }
}
```

### 4. Always Archive Outputs

```groovy
stage('Any Stage') {
    steps {
        script {
            // Do work
            // ...

            // Archive outputs
            archiveArtifacts artifacts: '''
                outputs/**/*,
                metadata.json
            ''', fingerprint: true, allowEmptyArchive: false
        }
    }
}
```

### 5. Chain Metadata

```groovy
stage('Sign') {
    steps {
        script {
            // Retrieve previous metadata
            copyArtifacts(
                filter: '''
                    artifacts/**/*,
                    build-metadata.json
                '''
            )

            // Read it
            def buildMetadata = readJSON file: 'build-metadata.json'

            // Create new metadata
            def signMetadata = [
                signedAt: currentBuild.startTimeInMillis,
                baseVersion: buildMetadata.version
            ]
            writeJSON file: 'sign-metadata.json', json: signMetadata

            // Archive both
            archiveArtifacts artifacts: '''
                signed/**/*,
                build-metadata.json,
                sign-metadata.json
            '''
        }
    }
}
```

## Decision Matrix

| Scenario | Use Workspace? | Use Archive? | Why |
|----------|---------------|--------------|-----|
| Normal sequential run | ❌ No | ✅ Yes | Consistent pattern |
| Restart from stage | ❌ No | ✅ Yes | Workspace unreliable |
| Different node | ❌ No | ✅ Yes | Workspace not shared |
| Days later | ❌ No | ✅ Yes | Workspace cleaned |
| Debugging | ❌ No | ✅ Yes | Can inspect archives |

**Answer: ALWAYS use archive, NEVER rely on workspace**

## Summary

### The Question
"Should stages rely on WORKSPACE or archives?"

### The Answer
**ALWAYS use archives via copyArtifacts + archiveArtifacts**

### The Reason
1. Can't reliably detect restart
2. Workspace state is unpredictable
3. Stages may run on different nodes
4. Time may pass between stages
5. One pattern works for all scenarios

### The Pattern

```groovy
stage('Any Stage') {
    steps {
        script {
            cleanWs()                    // Clean slate
            copyArtifacts(...)           // Retrieve inputs
            // Do work
            archiveArtifacts(...)        // Archive outputs
        }
    }
}
```

### The Benefit
- ✅ Works for normal run
- ✅ Works for restart
- ✅ Works across nodes
- ✅ Works over time
- ✅ Debuggable
- ✅ Auditable
- ✅ Reliable