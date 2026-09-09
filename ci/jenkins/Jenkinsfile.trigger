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
 * Trigger Pipeline — Layer 1b CI orchestration for all trigger types.
 *
 * One instance of this job is generated per deployment by the seed job
 * (seed_job_dsl.groovy), scoped to that deployment's trigger types and folder.
 *
 * Job Name pattern:
 *   <pipelineBaseFolder>/<deployment.folder>/Triggers/Trigger_<type>
 *
 * Parameters (baked in at seed time — do not edit manually):
 *   DEPLOYMENT_NAME          — deployment name from jenkins_job_config.json deployments[]
 *   TRIGGER_TYPE             — trigger type stem, e.g. 'detect-ga-tag'
 *   TRIGGER_VERSIONS_JSON    — JSON array of enabled version configs for this trigger type
 *   LAUNCH_JOB_BASE_PATH     — Jenkins folder path containing the launch jobs,
 *                              e.g. "temurin/release/Build_openjdk_launchers"
 *   CONFIG_REPO_URL          — vendor config repo URL
 *   CONFIG_REPO_BRANCH       — vendor config repo branch
 *   CONFIG_REPO_CREDENTIALS_ID — Jenkins credential ID for config repo (optional)
 *   DEFAULT_PARAMETERS_JSON  — JSON object of merged default parameters for this deployment
 *                              (base jobConfiguration.defaultParameters merged with
 *                               deployment.defaultParameterOverrides)
 *
 * Type-specific dedup policies (all Jenkins API logic lives here, not in scripts):
 *
 *   detect-build-tag-for-github-release:
 *     Script already checked targetRepo — if shouldTrigger=true, trigger directly.
 *
 *   detect-ga-tag:
 *     If detected=true: query Jenkins API for an existing completed or in-progress
 *     build with matching SCM_REF on the launch job.
 *       IN_PROGRESS or ALREADY_BUILT → skip (build running or built, awaiting publish)
 *       NOT_FOUND                    → trigger
 *
 *   weekly-head:
 *     No dedup — always trigger. Idempotent by design.
 *
 *   vendor types (unknown):
 *     Treated as detect-ga-tag policy (Jenkins history dedup check).
 */

import groovy.json.JsonOutput
import groovy.json.JsonSlurper

// ---------------------------------------------------------------------------
// suppressTestingConditions evaluation
// ---------------------------------------------------------------------------

/**
 * Return a UTC Calendar set to midnight (start-of-day) of the given calendar.
 * Uses only sandbox-safe java.util.Calendar operations.
 */
Calendar _utcMidnight(Calendar cal) {
    cal.set(Calendar.HOUR_OF_DAY, 0)
    cal.set(Calendar.MINUTE, 0)
    cal.set(Calendar.SECOND, 0)
    cal.set(Calendar.MILLISECOND, 0)
    return cal
}

/**
 * Resolve a named window event to [windowStartMs, windowEndMs] epoch-millis pair.
 *
 * Built-in event names:
 *   OPENJDK_RELEASE_DAY — the 3rd Tuesday of the current UTC month.
 *
 * Returns null if the event name is unrecognised (logs a warning; testing
 * is NOT suppressed for unknown events to avoid accidentally blocking builds).
 */
List resolveEventWindow(String eventName, int daysBefore, int daysAfter) {
    // Use Calendar (UTC) — fully sandbox-safe; java.time APIs are sandbox-blocked.
    Calendar now = Calendar.getInstance(TimeZone.getTimeZone('UTC'))
    Calendar eventDay

    switch (eventName) {
        case 'OPENJDK_RELEASE_DAY':
            // 3rd Tuesday of the current month
            eventDay = Calendar.getInstance(TimeZone.getTimeZone('UTC'))
            eventDay.set(Calendar.DAY_OF_MONTH, 1)
            _utcMidnight(eventDay)
            // Advance to first Tuesday, then add 14 days for the 3rd Tuesday
            while (eventDay.get(Calendar.DAY_OF_WEEK) != Calendar.TUESDAY) {
                eventDay.add(Calendar.DAY_OF_MONTH, 1)
            }
            eventDay.add(Calendar.DAY_OF_MONTH, 14)
            break
        default:
            echo "⚠️  Unknown suppressTestingConditions event '${eventName}' — ignoring window, testing NOT suppressed"
            return null
    }

    Calendar windowStart = eventDay.clone() as Calendar
    windowStart.add(Calendar.DAY_OF_MONTH, -daysBefore)
    _utcMidnight(windowStart)

    Calendar windowEnd = eventDay.clone() as Calendar
    windowEnd.add(Calendar.DAY_OF_MONTH, daysAfter + 1)
    _utcMidnight(windowEnd)

    echo "Event '${eventName}': ${eventDay.format('yyyy-MM-dd')} | Window: ${windowStart.format('yyyy-MM-dd')} to ${windowEnd.format('yyyy-MM-dd')} (exclusive) (daysBefore=${daysBefore}, daysAfter=${daysAfter})"
    return [windowStart.getTimeInMillis(), windowEnd.getTimeInMillis()]
}

/**
 * Evaluate whether testing should be suppressed for the given version config
 * and effective build parameters.
 *
 * Reads suppressTestingConditions from versionConfig — an array of conditions
 * that must ALL match for testing to be suppressed.  Each condition:
 *   {
 *     "param": "RELEASE_TYPE",    // parameter name to check in effectiveParams
 *     "value": "WEEKLY",          // required value (supports "regex:" prefix)
 *     "window": {                 // optional — condition only applies within this date window
 *       "event":      "OPENJDK_RELEASE_DAY",
 *       "daysBefore": 0,
 *       "daysAfter":  7
 *     }
 *   }
 *
 * If suppressTestingConditions is absent or empty: testing is NOT suppressed.
 * Returns true if testing should be suppressed, false otherwise.
 */
boolean shouldSuppressTesting(Map versionConfig, Map effectiveParams) {
    List conditions = versionConfig.suppressTestingConditions ?: []
    if (!conditions) { return false }

    long nowMs = Calendar.getInstance(TimeZone.getTimeZone('UTC')).getTimeInMillis()

    boolean allMatch = conditions.every { Map cond ->
        // Check param value match
        String actual   = effectiveParams[cond.param]?.toString() ?: ''
        String expected = cond.value?.toString() ?: ''
        boolean paramMatch
        if (expected.startsWith('regex:')) {
            paramMatch = actual =~ expected.substring('regex:'.length())
        } else {
            paramMatch = actual.equalsIgnoreCase(expected)
        }
        if (!paramMatch) { return false }

        // If a window is specified, check whether today falls within it
        Map window = cond.window
        if (window) {
            String eventName  = window.event    ?: ''
            int daysBefore    = (window.daysBefore ?: 0) as int
            int daysAfter     = (window.daysAfter  ?: 0) as int
            List windowRange  = resolveEventWindow(eventName, daysBefore, daysAfter)
            if (windowRange == null) { return false }   // unknown event — don't suppress
            long windowStart = windowRange[0] as long
            long windowEnd   = windowRange[1] as long
            boolean inWindow = nowMs >= windowStart && nowMs < windowEnd
            Calendar nowCal = Calendar.getInstance(TimeZone.getTimeZone('UTC'))
            echo "Window check: now=${nowCal.format('yyyy-MM-dd')} | inWindow=${inWindow}"
            return inWindow
        }

        return true   // param matched, no window constraint
    }

    if (allMatch) {
        echo "⚠️  suppressTestingConditions matched — disabling testing for this build"
    }
    return allMatch
}

// ---------------------------------------------------------------------------
// Jenkins build history dedup
// ---------------------------------------------------------------------------

/**
 * Query Jenkins build history for the given launch job to check whether a
 * build with the given SCM_REF parameter already exists or is running.
 *
 * Returns one of: 'IN_PROGRESS', 'ALREADY_BUILT', 'NOT_FOUND', 'API_ERROR'
 *
 * Requires JENKINS_API_USER and JENKINS_API_TOKEN in the environment
 * (injected via withCredentials by the caller).
 */
String checkExistingBuildForScmRef(String launchJobPath, String scmRef) {
    String jobUrlSegment = launchJobPath.split('/').collect { "job/${it}" }.join('/')
    String apiUrl = "${env.JENKINS_URL?.replaceAll('/+$', '')}/${jobUrlSegment}" +
        '/api/json?tree=builds%5Bnumber%2Cbuilding%2Cresult%2Cactions%5Bparameters%5Bname%2Cvalue%5D%5D%5D%7D&depth=1'

    String response = ''
    try {
        response = sh(
            script: """curl -sf --user "\${JENKINS_API_USER}:\${JENKINS_API_TOKEN}" '${apiUrl}'""",
            returnStdout: true
        ).trim()
    } catch (Exception e) {
        echo "⚠️  Jenkins API request failed: ${e.message} — fail open (will trigger)"
        return 'API_ERROR'
    }

    if (!response) {
        echo "⚠️  Empty Jenkins API response — fail open (will trigger)"
        return 'API_ERROR'
    }

    List builds = new JsonSlurper().parseText(response).builds ?: []
    for (Map build in builds) {
        Map buildParams = [:]
        (build.actions ?: []).each { Map action ->
            (action.parameters ?: []).each { Map p -> buildParams[p.name] = p.value }
        }
        if (buildParams['SCM_REF'] == scmRef) {
            if (build.building == true) {
                echo "→ Found IN_PROGRESS build #${build.number} for SCM_REF=${scmRef}"
                return 'IN_PROGRESS'
            }
            if (build.result in ['SUCCESS', 'UNSTABLE']) {
                echo "→ Found ALREADY_BUILT build #${build.number} (${build.result}) for SCM_REF=${scmRef}"
                return 'ALREADY_BUILT'
            }
        }
    }
    echo "→ No existing build for SCM_REF=${scmRef} on ${launchJobPath}"
    return 'NOT_FOUND'
}

// ---------------------------------------------------------------------------
// Launch job trigger
// ---------------------------------------------------------------------------

/**
 * Trigger the launch job for the given version.
 *
 * @param launchJobBase     Jenkins path to the Build_openjdk_launchers folder
 * @param jdkVersion        Version string, e.g. "jdk21"
 * @param deploymentDefaults Merged default parameters for this deployment
 * @param versionConfig     Version entry from trigger_config.json (for suppressTestingConditions)
 * @param triggerResult     Parsed trigger-result.json Map from the trigger script
 * @param releaseType       RELEASE_TYPE value to forward, e.g. "Weekly" or "Release"
 */
void triggerLaunchJob(String launchJobBase, String jdkVersion, Map deploymentDefaults,
                      Map versionConfig, Map triggerResult, String releaseType) {
    String vnum    = jdkVersion.replaceAll(/[^\d]/, '')
    String jobPath = "${launchJobBase}/Build_openjdk${vnum}_launch"

    // Build the effective parameter map for suppressTestingConditions evaluation
    Map effectiveParams = [:] + deploymentDefaults
    effectiveParams['RELEASE_TYPE'] = releaseType

    boolean enableTesting = deploymentDefaults.getOrDefault('RUN_TESTS', true) as boolean
    if (shouldSuppressTesting(versionConfig, effectiveParams)) {
        enableTesting = false
    }

    List jobParams = [
        string(name: 'RELEASE_TYPE', value: releaseType),
        string(name: 'PLATFORMS',    value: 'all'),
    ]

    if (triggerResult.scmRef) {
        jobParams << string(name: 'SCM_REF', value: triggerResult.scmRef as String)
    }
    if (triggerResult.publishName) {
        jobParams << string(name: 'OVERRIDE_PUBLISH_NAME', value: triggerResult.publishName as String)
    }

    // Forward deployment default parameters, excluding those already set above
    Set skipKeys = ['RELEASE_TYPE', 'RUN_TESTS'] as Set
    deploymentDefaults.each { String k, v ->
        if (!skipKeys.contains(k)) {
            if (v instanceof Boolean) {
                jobParams << booleanParam(name: k, value: v as boolean)
            } else {
                jobParams << string(name: k, value: v as String)
            }
        }
    }
    // RUN_TESTS applied last with the (potentially suppressed) value
    jobParams << booleanParam(name: 'RUN_TESTS', value: enableTesting)

    echo "Triggering ${jobPath} | SCM_REF=${triggerResult.scmRef ?: '(HEAD)'} | RELEASE_TYPE=${releaseType} | RUN_TESTS=${enableTesting}"
    build(job: jobPath, parameters: jobParams, wait: false, propagate: false)
    echo "✓ Triggered ${jobPath}"
}

// ---------------------------------------------------------------------------
// Pipeline
// ---------------------------------------------------------------------------

pipeline {
    agent none

    // NOTE: The cron trigger schedule is baked in by the seed job for each
    // trigger type — not defined here so it does not reset on every SCM checkout.

    options {
        timestamps()
        disableConcurrentBuilds()
    }

    stages {

        stage('Detect & Trigger') {
            agent { label 'ci.role.worker' }
            steps {
                script {
                    checkout scm   // ci-adoptium-pipelines — for scripts/triggers/ and scripts/lib/

                    dir('config-repo') {
                        checkout([
                            $class: 'GitSCM',
                            branches: [[name: "*/${params.CONFIG_REPO_BRANCH}"]],
                            userRemoteConfigs: [[
                                url: params.CONFIG_REPO_URL,
                                credentialsId: params.CONFIG_REPO_CREDENTIALS_ID ?: ''
                            ]]
                        ])
                    }

                    def triggerRunner = load('ci/jenkins/lib/TriggerScriptRunner.groovy')

                    // Inject GitHub token if configured
                    String ghTokenCredId = ''
                    if (fileExists('config-repo/jenkins_credential_config.json')) {
                        Map credCfg = readJSON(file: 'config-repo/jenkins_credential_config.json')
                        ghTokenCredId = credCfg?.credentials?.DEFAULT_GITHUB_TOKEN?.credentialId ?: ''
                        env.JENKINS_API_CREDENTIALS_ID = credCfg?.jenkinsApiCredentialsId ?: ''
                    }
                    if (ghTokenCredId) {
                        triggerRunner.setGithubTokenCredentialId(ghTokenCredId)
                    }

                    List versions          = new JsonSlurper().parseText(params.TRIGGER_VERSIONS_JSON) as List
                    Map  deploymentDefaults = new JsonSlurper().parseText(params.DEFAULT_PARAMETERS_JSON) as Map
                    String triggerType     = params.TRIGGER_TYPE
                    String launchJobBase   = params.LAUNCH_JOB_BASE_PATH

                    echo "=== Trigger: ${triggerType} | Deployment: ${params.DEPLOYMENT_NAME} ==="
                    echo "    Launch job base : ${launchJobBase}"
                    echo "    Versions        : ${versions.findAll { it.enabled }.collect { it.version }.join(', ')}"

                    Map triggerJobs = [:]
                    versions.findAll { Map v -> v.enabled == true }.each { Map versionConfig ->
                        String version = versionConfig.version
                        triggerJobs[version] = {
                            stage("${triggerType} — ${version}") {
                                echo "Processing ${triggerType} for ${version}"

                                Map result = triggerRunner.run(triggerType, versionConfig)

                                if (triggerType == 'detect-build-tag-for-github-release') {
                                    // ── Script verified targetRepo — trust its shouldTrigger ──
                                    if (result.shouldTrigger == true) {
                                        triggerLaunchJob(launchJobBase, version, deploymentDefaults,
                                            versionConfig, result, result.releaseType as String ?: 'Weekly')
                                    } else {
                                        echo "↷ ${version}: already published or no new tag — skipping"
                                    }

                                } else if (triggerType == 'weekly-head') {
                                    // ── Always trigger — no dedup ──
                                    triggerLaunchJob(launchJobBase, version, deploymentDefaults,
                                        versionConfig, result, 'Weekly')

                                } else {
                                    // ── detect-ga-tag and unknown vendor types ──
                                    // Gate on Jenkins build history before triggering
                                    if (result.detected != true) {
                                        echo "↷ ${version}: no GA tag detected — skipping"
                                        return
                                    }
                                    String scmRef = result.scmRef as String
                                    if (!scmRef) {
                                        echo "⚠️  ${version}: detected=true but scmRef is empty — skipping"
                                        return
                                    }

                                    String vnum      = version.replaceAll(/[^\d]/, '')
                                    String launchJob = "${launchJobBase}/Build_openjdk${vnum}_launch"
                                    String buildStatus = 'NOT_FOUND'

                                    if (env.JENKINS_API_CREDENTIALS_ID?.trim()) {
                                        withCredentials([
                                            usernamePassword(
                                                credentialsId: env.JENKINS_API_CREDENTIALS_ID,
                                                usernameVariable: 'JENKINS_API_USER',
                                                passwordVariable: 'JENKINS_API_TOKEN'
                                            )
                                        ]) {
                                            buildStatus = checkExistingBuildForScmRef(launchJob, scmRef)
                                        }
                                    } else {
                                        echo "⚠️  jenkinsApiCredentialsId not configured — skipping dedup, triggering directly"
                                    }

                                    if (buildStatus == 'IN_PROGRESS') {
                                        echo "↷ ${version}: build already in progress for ${scmRef} — skipping"
                                    } else if (buildStatus == 'ALREADY_BUILT') {
                                        echo "↷ ${version}: already built (awaiting publish) for ${scmRef} — skipping"
                                    } else {
                                        // NOT_FOUND or API_ERROR (fail open) — trigger
                                        triggerLaunchJob(launchJobBase, version, deploymentDefaults,
                                            versionConfig, result, 'Release')
                                    }
                                }
                            }
                        }
                    }

                    parallel triggerJobs
                }
            }
            post { always { cleanWs() } }
        }
    }

    post {
        success  { echo '✓ Trigger pipeline completed' }
        failure  { echo '✗ Trigger pipeline failed' }
        unstable { echo '⚠ Trigger pipeline unstable' }
    }
}
