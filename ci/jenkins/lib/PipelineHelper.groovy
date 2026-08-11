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
 * Execute a stage body with automatic result tracking via BuildUidHelper.
 */
def executeStageWithTracking(String stageName, Closure body) {
    try {
        body()
        buildUidHelper.recordStageResult(stageName, 'SUCCESS')
    } catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException e) {
        buildUidHelper.recordStageResult(stageName, 'ABORTED')
        throw e
    } catch (Exception e) {
        def result = currentBuild.result ?: 'FAILURE'
        buildUidHelper.recordStageResult(stageName, result)
        throw e
    }
}

/**
 * Common stage initialization: workspace cleanup, checkout, config-repo,
 * BUILD_UID setup, prerequisite validation, and artifact retrieval.
 *
 * Returns the parsed pipeline-config.json for non-Initialize stages,
 * or an empty map for the Initialize stage.
 */
def initializeStage(String stageName, List<String> prerequisites = [], String artifactFilter = 'pipeline-config.json') {
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
                    url: params.CONFIG_REPO_URL
                ]],
                extensions: [
                    [$class: 'SparseCheckoutPaths',
                     sparseCheckoutPaths: [
                         [path: 'configurations/*'],
                         [path: 'vendor-scripts/*'],
                         [path: 'vendor_stage_params.json'],
                         [path: 'adoptium_pipeline_config.json'],
                         [path: 'jenkins_job_config.json']
                     ]]
                ]
            ])
        }
    }

    // Lazy-load BuildUidHelper (only once, persists across stages via the field)
    if (buildUidHelper == null) {
        echo "Loading BuildUidHelper library..."
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
        def buildNumber = "${currentBuild.number}"
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
    } else {
        env.INPUT_ARTIFACTS_DIR   = "${env.WORKSPACE}"
        env.CONFIG_FILE           = "${env.WORKSPACE}/pipeline-config.json"

        def config = readJSON(file: env.CONFIG_FILE)
        ensureBuildDescriptionSet(config)
        return config
    }
}

/**
 * Common stage finalization: post-cleanup and completion message.
 */
def finalizeStage(String stageName) {
    if (params.CLEAN_WORKSPACE_AFTER_STAGE) {
        cleanWs()
    }
    echo "=== ${stageName} Complete ==="
    echo "BUILD_UID: ${env.BUILD_UID}"
}

/**
 * Set build display name and description from config + BUILD_UID.
 */
def ensureBuildDescriptionSet(def config) {
    if (config == null || config.isEmpty()) {
        error("ensureBuildDescriptionSet() requires a valid config object")
    }

    def displayName = "#${currentBuild.number} - ${config.buildConfig.JAVA_TO_BUILD} ${config.buildConfig.VARIANT} ${config.buildConfig.TARGET_OS}-${config.buildConfig.ARCHITECTURE}"
    if (params.SCM_REF) {
        displayName += " @ ${params.SCM_REF}"
    }
    if (params.RELEASE_TYPE && params.RELEASE_TYPE != 'NIGHTLY') {
        displayName += " [${params.RELEASE_TYPE}]"
    }

    def description = ""
    def isRestart = env.BUILD_UID && env.BUILD_UID != '' && currentBuild.number > 1
    if (isRestart) {
        def originalBuildNumber = currentBuild.number
        def checkBuild = currentBuild.previousBuild
        while (checkBuild != null) {
            try {
                def prevBuildUid = checkBuild.getBuildVariables()?.get('BUILD_UID')
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
