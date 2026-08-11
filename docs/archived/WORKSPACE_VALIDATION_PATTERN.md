# Workspace Validation Pattern with BUILD_UID

## The Critical Problem

```
Build #100 (original run):
  Build: Creates workspace, BUILD_UID=abc123
  Sign: Uses workspace from #100, BUILD_UID=abc123

Someone clicks "Rebuild" on #100:
  Build #101 (rebuild of #100):
    Build: Creates NEW workspace, BUILD_UID=def456

  Build #102 (restart from Sign of #101):
    Sign: Tries #102 (fails), falls back to #101
    Sign: Gets workspace with BUILD_UID=def456 ✅ CORRECT

BUT if Sign has network error:
  Build #103 (restart from Sign of #102):
    Sign: Tries #103 (fails), falls back to #102
    Sign: Gets workspace with BUILD_UID=def456
    BUT #102 might have been a restart of #101
    AND #101 might have been a rebuild of #100
    Sign: Might get workspace from WRONG pipeline run! ❌
```

## The Solution: BUILD_UID Validation

Generate a unique BUILD_UID at pipeline start and validate it in every stage.

### Step 1: Generate BUILD_UID at Pipeline Start

```groovy
pipeline {
    agent none

    parameters {
        string(name: 'BUILD_UID', defaultValue: '',
               description: 'Unique ID for this pipeline run (auto-generated if empty)')
    }

    stages {
        stage('Initialize') {
            agent any
            steps {
                script {
                    // Generate BUILD_UID if not provided
                    if (!params.BUILD_UID || params.BUILD_UID == '') {
                        // Use timestamp + random to ensure uniqueness
                        env.BUILD_UID = "${currentBuild.startTimeInMillis}-${UUID.randomUUID().toString().take(8)}"
                        println "Generated BUILD_UID: ${env.BUILD_UID}"
                    } else {
                        // Reuse BUILD_UID from restart
                        env.BUILD_UID = params.BUILD_UID
                        println "Reusing BUILD_UID: ${env.BUILD_UID}"
                    }

                    // Store BUILD_UID for downstream stages
                    currentBuild.description = "BUILD_UID: ${env.BUILD_UID}"
                }
            }
        }

        // ... other stages
    }
}
```

### Step 2: Enhanced Stage Pattern with BUILD_UID Validation

```groovy
stage('Stage Name') {
    agent { label 'appropriate-label' }
    steps {
        script {
            println "=== Stage Name - Start ==="
            println "BUILD_UID: ${env.BUILD_UID}"

            // 1. Clean workspace
            cleanWs()

            // 2. Retrieve workspace with BUILD_UID validation
            def buildNumber = env.BUILD_NUMBER
            def workspaceValid = false
            def maxAttempts = 10  // Prevent infinite loop
            def attempt = 0

            while (!workspaceValid && attempt < maxAttempts) {
                attempt++
                println "Attempt ${attempt}: Trying build ${buildNumber}..."

                try {
                    // Retrieve workspace
                    copyArtifacts(
                        projectName: env.JOB_NAME,
                        selector: specific(buildNumber),
                        filter: 'workspace/**/*',
                        target: '.',
                        optional: false,
                        fingerprintArtifacts: true
                    )

                    // Validate BUILD_UID
                    if (fileExists('workspace/pipeline-metadata.json')) {
                        def metadata = readJSON file: 'workspace/pipeline-metadata.json'

                        if (metadata.BUILD_UID == env.BUILD_UID) {
                            // Validate required stages and artifacts
                            if (validateWorkspace('Stage Name', metadata)) {
                                workspaceValid = true
                                println "✅ Valid workspace from build ${buildNumber} (BUILD_UID: ${metadata.BUILD_UID})"
                            } else {
                                println "❌ Workspace validation failed for build ${buildNumber}"
                            }
                        } else {
                            println "⚠️ BUILD_UID mismatch!"
                            println "   Expected: ${env.BUILD_UID}"
                            println "   Found: ${metadata.BUILD_UID}"
                            println "   This workspace is from a different pipeline run"
                        }
                    } else {
                        println "❌ No metadata file found in build ${buildNumber}"
                    }
                } catch (Exception e) {
                    println "⚠️ Could not retrieve from build ${buildNumber}: ${e.message}"
                }

                // If not valid, try previous build
                if (!workspaceValid) {
                    def previousBuild = Jenkins.instance.getItemByFullName(env.JOB_NAME)
                                               .getBuildByNumber(buildNumber.toInteger())
                                               ?.getPreviousBuild()

                    if (previousBuild) {
                        buildNumber = previousBuild.number.toString()
                        cleanWs()  // Clean before retry
                    } else {
                        break  // No more builds to try
                    }
                }
            }

            if (!workspaceValid) {
                error("❌ No valid workspace found with BUILD_UID: ${env.BUILD_UID}")
            }

            // 3. Do the work
            sh './do-stage-work.sh'

            // 4. Update metadata (preserving BUILD_UID)
            updateWorkspaceMetadata('Stage Name', env.BUILD_UID)

            // 5. Archive workspace
            archiveArtifacts artifacts: 'workspace/**/*',
                           fingerprint: true,
                           allowEmptyArchive: false

            println "=== Stage Name - Complete ==="
        }
    }
}
```

### Step 3: Metadata Functions

```groovy
// Create initial metadata (Build stage)
def createWorkspaceMetadata(String buildUid) {
    def metadata = [
        BUILD_UID: buildUid,
        completedStages: ['Build'],
        stageBuilds: [
            'Build': env.BUILD_NUMBER
        ],
        createdAt: currentBuild.startTimeInMillis,
        lastUpdated: currentBuild.startTimeInMillis,
        pipelineVersion: '1.0'
    ]

    writeJSON file: 'workspace/pipeline-metadata.json', json: metadata, pretty: 4
    println "Created metadata with BUILD_UID: ${buildUid}"
}

// Update metadata (subsequent stages)
def updateWorkspaceMetadata(String stageName, String buildUid) {
    if (!fileExists('workspace/pipeline-metadata.json')) {
        error("Metadata file missing!")
    }

    def metadata = readJSON file: 'workspace/pipeline-metadata.json'

    // Verify BUILD_UID hasn't changed
    if (metadata.BUILD_UID != buildUid) {
        error("BUILD_UID mismatch! Expected: ${buildUid}, Found: ${metadata.BUILD_UID}")
    }

    // Update metadata
    if (!metadata.completedStages.contains(stageName)) {
        metadata.completedStages.add(stageName)
    }
    metadata.stageBuilds[stageName] = env.BUILD_NUMBER
    metadata.lastUpdated = currentBuild.startTimeInMillis

    writeJSON file: 'workspace/pipeline-metadata.json', json: metadata, pretty: 4
    println "Updated metadata: ${metadata.completedStages.join(' → ')}"
}

// Validate workspace
def validateWorkspace(String currentStage, def metadata) {
    // Check BUILD_UID is present
    if (!metadata.BUILD_UID) {
        println "❌ No BUILD_UID in metadata"
        return false
    }

    // Determine required previous stages
    def stageOrder = ['Build', 'Sign', 'Installer', 'Test']
    def currentIndex = stageOrder.indexOf(currentStage)

    if (currentIndex == -1) {
        println "⚠️ Unknown stage: ${currentStage}"
        return false
    }

    // Check all previous stages completed
    for (int i = 0; i < currentIndex; i++) {
        def requiredStage = stageOrder[i]
        if (!metadata.completedStages?.contains(requiredStage)) {
            println "❌ Required stage '${requiredStage}' not completed"
            return false
        }
    }

    // Verify key artifacts exist
    def requiredArtifacts = getRequiredArtifacts(currentStage)
    for (artifact in requiredArtifacts) {
        if (!fileExists(artifact)) {
            println "❌ Required artifact missing: ${artifact}"
            return false
        }
    }

    return true
}

def getRequiredArtifacts(String stageName) {
    def requirements = [
        'Build': [],
        'Sign': ['workspace/target'],
        'Installer': ['workspace/target', 'workspace/signed'],
        'Test': ['workspace/target', 'workspace/signed', 'workspace/installers']
    ]
    return requirements[stageName] ?: []
}
```

## Complete Example

### Full Pipeline with BUILD_UID

```groovy
pipeline {
    agent none

    parameters {
        string(name: 'BUILD_UID', defaultValue: '',
               description: 'Unique ID for this pipeline run')
        choice(name: 'JDK_VERSION', choices: ['jdk21u', 'jdk17u'])
    }

    stages {
        stage('Initialize') {
            agent any
            steps {
                script {
                    // Generate or reuse BUILD_UID
                    if (!params.BUILD_UID || params.BUILD_UID == '') {
                        env.BUILD_UID = "${currentBuild.startTimeInMillis}-${UUID.randomUUID().toString().take(8)}"
                        println "🆕 Generated BUILD_UID: ${env.BUILD_UID}"
                    } else {
                        env.BUILD_UID = params.BUILD_UID
                        println "♻️ Reusing BUILD_UID: ${env.BUILD_UID}"
                    }

                    currentBuild.description = "BUILD_UID: ${env.BUILD_UID}"

                    // Store BUILD_UID for restart
                    // When user clicks "Restart from Stage", this BUILD_UID will be passed
                    env.RESTART_BUILD_UID = env.BUILD_UID
                }
            }
        }

        stage('Build') {
            agent { label 'build-node' }
            steps {
                script {
                    println "=== Build - Start ==="
                    println "BUILD_UID: ${env.BUILD_UID}"

                    cleanWs()
                    checkout scm

                    sh './build-jdk.sh'

                    // Create metadata with BUILD_UID
                    def metadata = [
                        BUILD_UID: env.BUILD_UID,
                        completedStages: ['Build'],
                        stageBuilds: ['Build': env.BUILD_NUMBER],
                        createdAt: currentBuild.startTimeInMillis,
                        lastUpdated: currentBuild.startTimeInMillis
                    ]
                    writeJSON file: 'workspace/pipeline-metadata.json', json: metadata, pretty: 4

                    archiveArtifacts artifacts: 'workspace/**/*', fingerprint: true

                    println "=== Build - Complete ==="
                }
            }
        }

        stage('Sign') {
            agent { label 'sign-node' }
            steps {
                script {
                    println "=== Sign - Start ==="
                    println "BUILD_UID: ${env.BUILD_UID}"

                    cleanWs()

                    // Retrieve workspace with BUILD_UID validation
                    def buildNumber = env.BUILD_NUMBER
                    def workspaceValid = false
                    def maxAttempts = 10
                    def attempt = 0

                    while (!workspaceValid && attempt < maxAttempts) {
                        attempt++
                        println "Attempt ${attempt}: Checking build ${buildNumber}..."

                        try {
                            copyArtifacts(
                                projectName: env.JOB_NAME,
                                selector: specific(buildNumber),
                                filter: 'workspace/**/*',
                                target: '.',
                                optional: false
                            )

                            if (fileExists('workspace/pipeline-metadata.json')) {
                                def metadata = readJSON file: 'workspace/pipeline-metadata.json'

                                if (metadata.BUILD_UID == env.BUILD_UID) {
                                    if (metadata.completedStages?.contains('Build') &&
                                        fileExists('workspace/target')) {
                                        workspaceValid = true
                                        println "✅ Valid workspace from build ${buildNumber}"
                                    }
                                } else {
                                    println "⚠️ BUILD_UID mismatch: expected ${env.BUILD_UID}, found ${metadata.BUILD_UID}"
                                }
                            }
                        } catch (Exception e) {
                            println "⚠️ Error retrieving from build ${buildNumber}"
                        }

                        if (!workspaceValid) {
                            def previousBuild = Jenkins.instance.getItemByFullName(env.JOB_NAME)
                                                       .getBuildByNumber(buildNumber.toInteger())
                                                       ?.getPreviousBuild()
                            if (previousBuild) {
                                buildNumber = previousBuild.number.toString()
                                cleanWs()
                            } else {
                                break
                            }
                        }
                    }

                    if (!workspaceValid) {
                        error("❌ No valid workspace found with BUILD_UID: ${env.BUILD_UID}")
                    }

                    // Do the work
                    sh './sign-artifacts.sh'

                    // Update metadata
                    def metadata = readJSON file: 'workspace/pipeline-metadata.json'
                    metadata.completedStages.add('Sign')
                    metadata.stageBuilds['Sign'] = env.BUILD_NUMBER
                    metadata.lastUpdated = currentBuild.startTimeInMillis
                    writeJSON file: 'workspace/pipeline-metadata.json', json: metadata, pretty: 4

                    archiveArtifacts artifacts: 'workspace/**/*', fingerprint: true

                    println "=== Sign - Complete ==="
                }
            }
        }
    }
}
```

## Metadata File with BUILD_UID

```json
{
    "BUILD_UID": "1704067200000-a1b2c3d4",
    "completedStages": ["Build", "Sign"],
    "stageBuilds": {
        "Build": "100",
        "Sign": "102"
    },
    "createdAt": 1704067200000,
    "lastUpdated": 1704067800000,
    "pipelineVersion": "1.0"
}
```

## How BUILD_UID Solves the Problem

### Scenario 1: Normal Run
```
Build #100:
  Initialize: BUILD_UID=abc123
  Build: Creates workspace with BUILD_UID=abc123
  Sign: Validates BUILD_UID=abc123 ✅
```

### Scenario 2: Restart from Sign
```
Build #101 (restart from Sign of #100):
  Initialize: Reuses BUILD_UID=abc123
  Sign: Looks for workspace with BUILD_UID=abc123
  Sign: Finds it in #100 ✅
```

### Scenario 3: Rebuild (Different Pipeline)
```
Build #100:
  BUILD_UID=abc123

Build #101 (rebuild of #100):
  BUILD_UID=def456 (NEW UID)

Build #102 (restart from Sign of #101):
  Sign: Looks for BUILD_UID=def456
  Sign: Tries #102 (not found)
  Sign: Tries #101 (found, BUILD_UID=def456) ✅
  Sign: Tries #100 (found, but BUILD_UID=abc123) ❌ REJECTED
```

## Benefits

✅ **Prevents wrong workspace** - BUILD_UID must match
✅ **Works across rebuilds** - Each pipeline run has unique UID
✅ **Works across restarts** - UID is preserved
✅ **Clear validation** - Know exactly which pipeline run workspace came from
✅ **Fail fast** - Reject workspace from different pipeline run immediately

## Summary

### The Pattern

1. **Generate BUILD_UID** at pipeline start (or reuse for restart)
2. **Store BUILD_UID** in workspace metadata
3. **Validate BUILD_UID** when retrieving workspace
4. **Walk back through builds** until matching BUILD_UID found
5. **Reject mismatched BUILD_UID** - fail with clear error

### Key Insight

**BUILD_UID ties workspace to specific pipeline run, preventing cross-contamination from rebuilds or unrelated runs.**

This is the bulletproof solution for workspace validation.