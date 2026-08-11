/*
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

     https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/
/**
 * BUILD_UID Helper Functions
 *
 * Provides unique build tracking and stage result management that persists
 * across pipeline restarts.
 *
 * Usage in Jenkinsfile:
 *   def buildUidHelper = load 'ci/jenkins/lib/BuildUidHelper.groovy'
 *   buildUidHelper.initializeBuildContext('Stage Name')
 *   buildUidHelper.validatePrerequisites('Stage Name', ['Required', 'Stages'])
 *   buildUidHelper.recordStageResult('Stage Name', 'SUCCESS')
 */

/**
 * Parse stage results from serialized string format
 * @param resultsStr Serialized string in format "Stage1==SUCCESS||Stage2==FAILURE"
 * @return Map of stage names to their results
 */
@NonCPS
def parseStageResults(String resultsStr) {
    if (!resultsStr) return [:]
    def results = [:]
    resultsStr.split('\\|\\|').each { entry ->
        def parts = entry.split('==', 2)
        if (parts.size() == 2) {
            results[parts[0]] = parts[1]
        }
    }
    return results
}

/**
 * Serialize stage results Map to string format
 * @param results Map of stage names to their results
 * @return Serialized string in format "Stage1==SUCCESS||Stage2==FAILURE"
 */
@NonCPS
def serializeStageResults(Map results) {
    return results.collect { k, v -> "${k}==${v}" }.join('||')
}

/**
 * Record the result of a stage execution
 * @param stageName Name of the stage
 * @param result Result status (SUCCESS/FAILURE/UNSTABLE/ABORTED)
 */
def recordStageResult(String stageName, String result) {
    echo "Recording stage result: ${stageName} = ${result}"

    // Load existing results
    def existingResults = env.BUILD_STAGE_RESULTS ?
        parseStageResults(env.BUILD_STAGE_RESULTS) : [:]

    // Update with new result
    existingResults[stageName] = result

    // Serialize and save
    env.BUILD_STAGE_RESULTS = serializeStageResults(existingResults)

    echo "Updated BUILD_STAGE_RESULTS: ${env.BUILD_STAGE_RESULTS}"
}

/**
 * Validate that all required prerequisite stages completed successfully
 * @param currentStage Name of the current stage
 * @param requiredStages List of stage names that must have completed successfully
 * @throws Exception if any prerequisite failed or is missing
 */
def validatePrerequisites(String currentStage, List<String> requiredStages) {
    if (!requiredStages || requiredStages.isEmpty()) {
        echo "No prerequisites required for ${currentStage}"
        return
    }

    echo "Validating prerequisites for ${currentStage}: ${requiredStages}"

    def stageResults = env.BUILD_STAGE_RESULTS ?
        parseStageResults(env.BUILD_STAGE_RESULTS) : [:]

    // Special case: If BUILD_STAGE_RESULTS is empty and we're not in Initialize stage,
    // this is likely a Rebuild of a restarted build. Fail with clear user error.
    if (stageResults.isEmpty() && currentStage != '01-initialize') {
        def errorMsg = """
╔════════════════════════════════════════════════════════════════════════════╗
║                              USER ERROR                                    ║
╚════════════════════════════════════════════════════════════════════════════╝

Cannot validate prerequisites for '${currentStage}' stage.

BUILD_STAGE_RESULTS is empty, which indicates this is a Rebuild of a
restarted build. When you Rebuild a build that was restarted from a stage,
Jenkins creates a new build without the stage completion history.

SOLUTION:
  Instead of using 'Rebuild', use 'Restart from Stage' to continue from
  where the original build left off. This preserves the stage completion
  history needed for prerequisite validation.

  OR

  Run a fresh build from the beginning (Initialize stage).
"""
        echo errorMsg
        error(errorMsg)
    }

    def missingStages = []
    def failedStages = []

    requiredStages.each { requiredStage ->
        def result = stageResults[requiredStage]
        if (!result) {
            missingStages.add(requiredStage)
        } else if (result != 'SUCCESS') {
            failedStages.add("${requiredStage} (${result})")
        }
    }

    if (!missingStages.isEmpty() || !failedStages.isEmpty()) {
        def errorMsg = "Cannot run ${currentStage}:"
        if (!missingStages.isEmpty()) {
            errorMsg += "\n  Missing stages: ${missingStages.join(', ')}"
        }
        if (!failedStages.isEmpty()) {
            errorMsg += "\n  Failed stages: ${failedStages.join(', ')}"
        }
        echo errorMsg
        error(errorMsg)
    }

    echo "✅ All prerequisites validated for ${currentStage}"
}

/**
 * Initialize BUILD_UID and load existing stage results
 * Call this at the start of each stage
 * @param stageName Name of the current stage
 */
def initializeBuildContext(String stageName) {
    echo "Initializing build context for ${stageName}"

    // Generate or reuse BUILD_UID
    if (!env.BUILD_UID) {
        def timestamp = new Date().format('yyyyMMdd-HHmmss')
        def random = UUID.randomUUID().toString().take(8)
        env.BUILD_UID = "build-${timestamp}-${random}"
        echo "Generated new BUILD_UID: ${env.BUILD_UID}"
    } else {
        echo "Reusing existing BUILD_UID: ${env.BUILD_UID}"
    }

    // Resolve GROUP_UID: use param if supplied, reuse env if already set, else auto-generate
    if (!env.GROUP_UID) {
        def supplied = params?.GROUP_UID?.trim()
        if (supplied) {
            env.GROUP_UID = supplied
            echo "Using supplied GROUP_UID: ${env.GROUP_UID}"
        } else {
            def timestamp = new Date().format('yyyyMMdd-HHmmss')
            def random = UUID.randomUUID().toString().take(8)
            env.GROUP_UID = "group-${timestamp}-${random}"
            echo "Generated new GROUP_UID: ${env.GROUP_UID}"
        }
    } else {
        echo "Reusing existing GROUP_UID: ${env.GROUP_UID}"
    }

    // Load existing stage results if available
    if (env.BUILD_STAGE_RESULTS) {
        def results = parseStageResults(env.BUILD_STAGE_RESULTS)
        echo "Loaded ${results.size()} previous stage results"
        results.each { stage, result ->
            echo "  ${stage}: ${result}"
        }
    } else {
        echo "No previous stage results found (first run)"
        env.BUILD_STAGE_RESULTS = ""
    }
}

/**
 * Create post blocks for a stage to record results
 * This is a helper to generate the post block code
 * @param stageName Name of the stage
 * @return Map with post block closures
 */
def createPostBlocks(String stageName) {
    return [
        success: {
            script {
                recordStageResult(stageName, 'SUCCESS')
            }
        },
        unstable: {
            script {
                recordStageResult(stageName, 'UNSTABLE')
            }
        },
        failure: {
            script {
                recordStageResult(stageName, 'FAILURE')
            }
        },
        aborted: {
            script {
                recordStageResult(stageName, 'ABORTED')
            }
        }
    ]
}

// Return this object to make functions available
return this

// Made with Bob
