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
 * PipelineHelper — stage lifecycle functions for Jenkinsfile.declarative.
 *
 * Loaded with:
 *   def pipelineHelper = load('ci/jenkins/lib/PipelineHelper.groovy')
 *
 * This file is a CpsScript. All pipeline steps (echo, sh, cleanWs, checkout,
 * copyArtifacts, env, params, currentBuild, load, etc.) are called directly —
 * no 'steps.' prefix, no init(this) delegation.
 *
 * Public API:
 *   initializeStage(stageName, prerequisites=[], artifactFilter='pipeline-config.json')
 *     → cleans workspace, checks out repos, initialises BUILD_UID, validates
 *       prerequisites, copies artifacts into WORKSPACE root; returns parsed config Map (or [:] for Initialize)
 *
 *   finalizeStage(stageName)
 *     → optional cleanWs + completion log
 *
 *   executeStageWithTracking(stageName, body)
 *     → runs body closure; records SUCCESS/FAILURE/ABORTED in BUILD_STAGE_RESULTS
 *
 *   ensureBuildDescriptionSet(config)
 *     → sets currentBuild.displayName and .description from config + BUILD_UID
 */

buildUidHelper = null // Lazy-loaded by initializeStage(); explicit null initialises the Binding entry

/**
 * Return configured stage timeout in minutes from env.COLLATED_STAGE_TIMEOUTS, or 0 if none.
 */
int getStageTimeout(String stageName) {
    String timeoutJson = env.COLLATED_STAGE_TIMEOUTS
    if (!timeoutJson) { return 0 }
    try {
        Map timeoutMap = new groovy.json.JsonSlurper().parseText(timeoutJson)
        return (timeoutMap[stageName] ?: 0) as int
    } catch (Exception e) {
        return 0
    }
}

/**
 * Execute a stage body with automatic result tracking via BuildUidHelper and optional timeout.
 */
void executeStageWithTracking(String stageName, Closure body) {
    int timeoutMins = getStageTimeout(stageName)
    Closure trackedBody = {
        try {
            body()
            buildUidHelper.recordStageResult(stageName, 'SUCCESS')
        } catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException e) {
            buildUidHelper.recordStageResult(stageName, 'ABORTED')
            throw e
        } catch (Exception e) {
            String result = currentBuild.result ?: 'FAILURE'
            buildUidHelper.recordStageResult(stageName, result)
            throw e
        }
    }

    if (timeoutMins > 0) {
        echo "Enforcing stage timeout for '${stageName}': ${timeoutMins} minute(s)"
        timeout(time: timeoutMins, unit: 'MINUTES') {
            trackedBody()
        }
    } else {
        trackedBody()
    }
}

/**
 * Common stage initialization: workspace cleanup, checkout, config-repo,
 * BUILD_UID setup, prerequisite validation, and artifact retrieval.
 *
 * Returns the parsed pipeline-config.json for non-Initialize stages,
 * or an empty map for the Initialize stage.
 */
Map initializeStage(String stageName, List<String> prerequisites = [], String artifactFilter = 'pipeline-config.json') {
    echo "=== ${stageName} ==="

    // Pre-cleanup: Always clean workspace for restartability
    cleanWs()

    // Checkout ci-adoptium-pipelines repository
    checkout scm

    // Checkout config repo (vendor-scripts, configurations, adoptium_pipeline_config.json)
    if (params.CONFIG_REPO_URL) {
        dir('config-repo') {
            checkout([
                $class: 'GitSCM',
                branches: [[name: "*/${params.CONFIG_REPO_BRANCH}"]],
                userRemoteConfigs: [[
                    url: params.CONFIG_REPO_URL,
                    credentialsId: params.CONFIG_REPO_CREDENTIALS_ID ?: ''
                ]],
                extensions: [
                    [$class: 'SparseCheckoutPaths',
                     sparseCheckoutPaths: [
                         [path: 'configurations/*'],
                         [path: 'vendor-scripts/*'],
                         [path: 'vendor_stage_params.json'],
                         [path: 'adoptium_pipeline_config.json'],
                         [path: 'jenkins_job_config.json'],
                         [path: 'jenkins_credential_config.json']
                     ]]
                ]
            ])
        }
    }

    // Lazy-load BuildUidHelper (only once, persists across stages via the field)
    if (buildUidHelper == null) {
        echo 'Loading BuildUidHelper library...'
        buildUidHelper = load('ci/jenkins/lib/BuildUidHelper.groovy')
    }

    // Initialize BUILD_UID and build context
    buildUidHelper.initializeBuildContext(stageName)

    // Validate prerequisites (skip for Initialize stage)
    if (stageName != '01-initialize') {
        buildUidHelper.validatePrerequisites(stageName, prerequisites)
    }

    // Retrieve artifacts into WORKSPACE root (skip for Initialize stage)
    if (artifactFilter && stageName != '01-initialize') {
        // Use currentBuild.number rather than env.BUILD_NUMBER. On a
        // "Restart from Stage" Jenkins restores env vars from the prior build,
        // so env.BUILD_NUMBER holds the original build number. currentBuild.number
        // is always the authoritative number for the currently-executing build.
        // Jenkins automatically copies artifacts from the previous build into
        // the restart build's artifact store, so specific(currentBuild.number)
        // always resolves correctly for both normal runs and restarts.
        String buildNumber = "${currentBuild.number}"
        try {
            copyArtifacts(
                projectName: env.JOB_NAME,
                selector: specific(buildNumber),
                filter: artifactFilter,
                target: '.',
                optional: false,
                fingerprintArtifacts: true
            )
            echo "✅ Successfully copied artifacts from build #${buildNumber}: ${artifactFilter}"
        } catch (Exception e) {
            error("Failed to copy artifacts '${artifactFilter}' from build #${buildNumber}: ${e.message}")
        }
    }

    // Return config for convenience (empty for Initialize stage)
    if (stageName == '01-initialize') {
        return [:]
    }
    env.INPUT_ARTIFACTS_DIR = "${env.WORKSPACE}"
    env.CONFIG_FILE         = "${env.WORKSPACE}/pipeline-config.json"

    Map config = readJSON(file: env.CONFIG_FILE)
    ensureBuildDescriptionSet(config)
    return config
}

/**
 * Common stage finalization: post-cleanup and completion message.
 */
void finalizeStage(String stageName) {
    if (params.CLEAN_WORKSPACE_AFTER_STAGE) {
        cleanWs()
    }
    echo "=== ${stageName} Complete ==="
    echo "BUILD_UID: ${env.BUILD_UID}"
}

/**
 * Set build display name and description from config + BUILD_UID.
 */
void ensureBuildDescriptionSet(Map config) {
    if (config == null || config.empty) {
        error('ensureBuildDescriptionSet() requires a valid config object')
    }

    String displayName = "#${currentBuild.number} - ${config.buildConfig.JAVA_TO_BUILD} ${config.buildConfig.VARIANT} ${config.buildConfig.TARGET_OS}-${config.buildConfig.ARCHITECTURE}"
    if (params.SCM_REF) {
        displayName += " @ ${params.SCM_REF}"
    }
    if (params.RELEASE_TYPE && params.RELEASE_TYPE != 'NIGHTLY') {
        displayName += " [${params.RELEASE_TYPE}]"
    }

    String description = ''
    boolean isRestart = env.BUILD_UID && env.BUILD_UID != '' && currentBuild.number > 1
    if (isRestart) {
        int originalBuildNumber = currentBuild.number
        def checkBuild = currentBuild.previousBuild
        while (checkBuild != null) {
            try {
                String prevBuildUid = checkBuild.buildVariables?.get('BUILD_UID')
                if (prevBuildUid == env.BUILD_UID) {
                    originalBuildNumber = checkBuild.number
                    checkBuild = checkBuild.previousBuild
                } else {
                    break
                }
            } catch (Exception e) {
                break
            }
        }
        if (originalBuildNumber != currentBuild.number) {
            description = "Restart of #${originalBuildNumber} | "
        }
    }

    description += "BUILD_UID: ${env.BUILD_UID} | GROUP_UID: ${env.GROUP_UID}"

    if (currentBuild.displayName != displayName) {
        currentBuild.displayName = displayName
        echo "Build Display Name: ${displayName}"
    }
    if (currentBuild.description != description) {
        currentBuild.description = description
        echo "Build Description: ${description}"
    }
    echo "Build UID: ${env.BUILD_UID}"
}

return this
