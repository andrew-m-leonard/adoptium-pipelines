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
 * Job DSL Script for Platform-Specific OpenJDK Build Pipeline Jobs
 *
 * Called by the launch job (Jenkinsfile.launch) via jobDsl() step.
 * Reads all configuration via readFileFromWorkspace — no FilePath, no HTTP.
 *
 * Workspace layout when called from Jenkinsfile.launch:
 *   <workspace>/
 *     collated-stage-params.json   — written by 'Collate Stage Parameters' stage
 *     config-repo/
 *       adoptium_pipeline_config.json
 *       jenkins_job_config.json
 *       configurations/jdk<N>_pipeline_config.json
 *
 * Binding variables (additionalParameters from Jenkinsfile.launch):
 *   JDK_VERSION           — numeric version (e.g. "21")
 *   PLATFORM              — platform key from buildConfigurations (e.g. "x86-64_linux")
 *   COLLATED_PARAMS_JSON  — JSON string produced by collect-stage-params.py, with
 *                           cross-stem group merge already applied by Jenkinsfile.launch
 *   PIPELINE_COMMIT_SHA   — git SHA of the ci-adoptium-pipelines checkout in the
 *                           launch job workspace (env.GIT_COMMIT from Jenkinsfile.launch).
 *                           Used to detect when the build job was generated from a
 *                           different commit and must be regenerated.
 *
 * jenkins_job_config.json fields consumed here:
 *   pipelineBaseFolder    — (optional) Jenkins folder path prefix for the generated
 *                           build job (e.g. "MyOrg/OpenJDK").  Must match what the
 *                           seed job used.  Omit or set to "" for the Jenkins root.
 *
 * Creates: [pipelineBaseFolder/]Build_openjdk/Build_openjdk<version>_<distro>_<arch>_<os>
 *
 * Regeneration logic (automatic — no manual parameter needed):
 *   The generated job's description embeds the SHA it was created from as
 *   "pipeline-sha:<sha>".  On each run this script compares that stored SHA
 *   against PIPELINE_COMMIT_SHA.  The job is (re-)created only when:
 *     • the job does not yet exist, OR
 *     • the stored SHA differs from the current checkout SHA
 */

import groovy.json.JsonSlurper
import jenkins.model.Jenkins

// ============================================================================
// STEP 1: Validate binding variables
// ============================================================================

def jdkVersion         = binding.variables.get('JDK_VERSION')
def platform           = binding.variables.get('PLATFORM')
def collatedParamsJson = binding.variables.get('COLLATED_PARAMS_JSON') ?: ''
def pipelineCommitSha  = binding.variables.get('PIPELINE_COMMIT_SHA')  ?: 'unknown'
def configRepoUrl      = binding.variables.get('CONFIG_REPO_URL')       ?: ''
def configRepoBranch   = binding.variables.get('CONFIG_REPO_BRANCH')    ?: ''

final int SEPARATOR_WIDTH = 80
final int DUPLICATE_ZERO  = 0

if (!jdkVersion) { throw new IllegalArgumentException('JDK_VERSION binding variable is required') }
if (!platform)   { throw new IllegalArgumentException('PLATFORM binding variable is required') }
if (!collatedParamsJson?.trim()) {
    throw new IllegalStateException(
        'COLLATED_PARAMS_JSON is empty.\n' +
        "Ensure the 'Collate Stage Parameters' stage in Jenkinsfile.launch completed successfully."
    )
}

println '=' * SEPARATOR_WIDTH
println 'openjdk_build_pipeline'
println "  JDK_VERSION         : ${jdkVersion}"
println "  PLATFORM            : ${platform}"
println "  PIPELINE_COMMIT_SHA : ${pipelineCommitSha}"
println "  CONFIG_REPO_URL     : ${configRepoUrl}"
println "  CONFIG_REPO_BRANCH  : ${configRepoBranch}"
println '=' * SEPARATOR_WIDTH

// ============================================================================
// STEP 2: Load configuration via readFileFromWorkspace
// ============================================================================

def slurper = new JsonSlurper()

def pipelineConfig = slurper.parseText(readFileFromWorkspace('config-repo/adoptium_pipeline_config.json'))
println '✓ Loaded adoptium_pipeline_config.json'

def jenkinsConfig = slurper.parseText(readFileFromWorkspace('config-repo/jenkins_job_config.json'))
println '✓ Loaded jenkins_job_config.json'

// Read optional base folder — must match what the seed job used.
def pipelineBaseFolder = (jenkinsConfig?.pipelineBaseFolder ?: '').toString().trim().replaceAll(/\/+$/, '')
def inFolder = { String name -> pipelineBaseFolder ? "${pipelineBaseFolder}/${name}" : name }
println "  pipelineBaseFolder : ${pipelineBaseFolder ?: '(root)'}"

def jdkConfig = slurper.parseText(readFileFromWorkspace("config-repo/configurations/jdk${jdkVersion}_pipeline_config.json"))

def platformConfig = jdkConfig.buildConfigurations[platform]
if (!platformConfig) {
    throw new IllegalArgumentException(
        "Platform '${platform}' not found in config-repo/configurations/jdk${jdkVersion}_pipeline_config.json"
    )
}

def architecture = platformConfig.arch
def targetOs     = platformConfig.os
def variant      = platformConfig.variant ?: pipelineConfig?.defaultVariant ?: 'temurin'

if (!architecture || !targetOs) {
    throw new IllegalArgumentException("Platform '${platform}' is missing 'arch' or 'os' fields")
}
println "✓ Platform: arch=${architecture}, os=${targetOs}, variant=${variant}"

def defaultParams = jenkinsConfig?.jobConfiguration?.defaultParameters

// ============================================================================
// STEP 3: Build collated param groups from pre-computed JSON.
// ============================================================================

// COLLATED_PARAMS_JSON was produced by collect-stage-params.py and the
// cross-stem group merge was applied in Jenkinsfile.launch's
// 'Collate Stage Parameters' stage. Parse it and re-apply the merge here
// to obtain the stageIds list structure that configure{} needs.
def rawGroups = new JsonSlurper().parseText(collatedParamsJson).groups ?: []

def mergedGroupMap = [:] as LinkedHashMap
rawGroups.each { grp ->
    def gname = grp.name
    // stageIds list is already present on merged priority groups (e.g. "Stage Selections");
    // non-priority groups carry a scalar stageId — normalise to a list in both cases.
    def incomingIds = grp.stageIds instanceof List ? grp.stageIds : [grp.stageId]
    if (mergedGroupMap.containsKey(gname)) {
        incomingIds.each { id -> if (id && !mergedGroupMap[gname].stageIds.contains(id)) { mergedGroupMap[gname].stageIds << id } }
        mergedGroupMap[gname].parameters.addAll(grp.parameters ?: [])
    } else {
        mergedGroupMap[gname] = [
            name:        gname,
            description: grp.description ?: '',
            stageIds:    new ArrayList(incomingIds),
            parameters:  new ArrayList(grp.parameters ?: [])
        ]
    }
}

// Capture at script scope — configure{} runs with a different delegate.
def collatedParamGroups = mergedGroupMap.values().toList()
println "✓ Received ${rawGroups.size()} raw group(s), merged to ${collatedParamGroups.size()} group(s)"

// ============================================================================
// STEP 4: Determine whether the platform build job needs to be (re-)created
// ============================================================================

// Job DSL scripts run on the Jenkins controller in a trusted (non-sandboxed)
// context, so Jenkins.instance is available without script approval.
def jobName      = "/${inFolder("Build_openjdk/Build_openjdk${jdkVersion}_${variant}_${architecture}_${targetOs}")}"
def lookupName   = jobName.replaceAll(/^\//, '')
def existingJob  = Jenkins.instance.getItemByFullName(lookupName)
println "  → Looking up job: '${lookupName}' → ${existingJob == null ? 'NOT FOUND' : 'found, description=' + existingJob.description}"
def shaMatch     = (existingJob?.description ?: '') =~ /pipeline-sha:([0-9a-f]+)/
def storedShaVal = shaMatch.find() ? shaMatch.group(1) : null

if (existingJob == null) {
    println '  → Job does not exist yet — will create'
} else if (storedShaVal != pipelineCommitSha) {
    println "  → Stored pipeline-sha (${storedShaVal ?: 'none'}) differs from current (${pipelineCommitSha}) — will regenerate"
} else {
    println "  → Job is up-to-date (pipeline-sha: ${storedShaVal}) — skipping regeneration"
    return
}

// ============================================================================
// STEP 5: Create / update platform build job
// ============================================================================

folder(inFolder('Build_openjdk')) {
    displayName('Build_openjdk')
    description('OpenJDK platform build pipeline jobs, AQA-style naming: Build_openjdk<version>_<distro>_<arch>_<os>')
}

println "Creating platform build job: ${jobName}"

pipelineJob(jobName.replaceAll(/^\//, '')) {
    displayName("Build_openjdk${jdkVersion}_${variant}_${architecture}_${targetOs}")
    description("""\
        Platform-specific build pipeline for OpenJDK ${jdkVersion} (${variant}) on ${architecture}/${targetOs}.
        <br>pipeline-sha:${pipelineCommitSha}""".stripIndent().trim())

    quietPeriod(5)

    parameters {
        // ── Build Configuration ───────────────────────────────────────────────
        separator {
            name('__sep_build_configuration')
            sectionHeader('Build Configuration')
            sectionHeaderStyle('')
            description('Fixed platform coordinates and runtime controls for this build job.')
            separatorStyle('')
        }
        stringParam {
            name('JDK_VERSION')
            defaultValue(jdkVersion)
            description('JDK version number — fixed at job-generation time')
            trim(true)
        }
        stringParam {
            name('TARGET_OS')
            defaultValue(targetOs)
            description('Target operating system — fixed at job-generation time')
            trim(true)
        }
        stringParam {
            name('ARCHITECTURE')
            defaultValue(architecture)
            description('Target CPU architecture — fixed at job-generation time')
            trim(true)
        }
        choiceParam('RELEASE_TYPE',
            ['NIGHTLY', 'WEEKLY', 'RELEASE'],
            'Type of release build')
        stringParam {
            name('GROUP_UID')
            defaultValue('')
            description('Group identifier linking all platform builds from the same launch.')
            trim(true)
        }
        booleanParam('CLEAN_WORKSPACE_AFTER_STAGE',
            defaultParams?.CLEAN_WORKSPACE_AFTER_STAGE != null ? defaultParams.CLEAN_WORKSPACE_AFTER_STAGE : true,
            'Clean workspace after each stage completes')
        stringParam {
            name('PIPELINE_TIMEOUT_HOURS')
            defaultValue((jenkinsConfig.pipelineTimeoutHours ?: 8).toString())
            description('Overall pipeline timeout in hours')
            trim(true)
        }

        // ── Collated stage parameters ─────────────────────────────────────────
        // Stage-gate booleans (RUN_TESTS, SIGN_ARTIFACTS, etc.) and all other
        // stage-specific params are emitted here from the collated params JSON.
        // Groups where stageDisabled=true are skipped — no parameters generated.
        collatedParamGroups.each { group ->
            if (group.stageDisabled == true) { return }
            def stageLabel  = group.stageIds.join('_').replaceAll(/\W+/, '_')
            def stageHeader = group.stageIds.size() == 1
                ? "stage: ${group.stageIds[DUPLICATE_ZERO]}"
                : "stages: ${group.stageIds.join(', ')}"
            separator {
                name("__sep_${stageLabel}_${group.name.replaceAll(/\W+/, '_')}")
                sectionHeader("${group.name}  [${stageHeader}]")
                sectionHeaderStyle('')
                if (group.description) {
                    description(group.description)
                }
                separatorStyle('')
            }
            group.parameters?.each { p ->
                if (p.type == 'boolean') {
                    def boolDefault = defaultParams?.containsKey(p.name)
                        ? defaultParams[p.name] == true
                        : p.default == true
                    booleanParam(p.name, boolDefault, p.description ?: '')
                } else {
                    def strDefault = defaultParams?.containsKey(p.name)
                        ? (defaultParams[p.name] ?: '')
                        : (p.default ?: '')
                    stringParam {
                        name(p.name)
                        defaultValue(strDefault)
                        description(p.description ?: '')
                        trim(true)
                    }
                }
            }
        }

        // ── Config Repository ─────────────────────────────────────────────────
        separator {
            name('__sep_config_repo')
            sectionHeader('Config Repository')
            sectionHeaderStyle('')
            description('Vendor config repo coordinates — baked in at job-generation time. Do not edit manually.')
            separatorStyle('')
        }
        stringParam {
            name('CONFIG_REPO_URL')
            defaultValue(configRepoUrl)
            description('Vendor config repo URL — baked in at job-generation time')
            trim(true)
        }
        stringParam {
            name('CONFIG_REPO_BRANCH')
            defaultValue(configRepoBranch)
            description('Vendor config repo branch — baked in at job-generation time')
            trim(true)
        }
    }

    definition {
        cpsScm {
            scm {
                git {
                    remote {
                        url(pipelineConfig.repository.url)
                        if (pipelineConfig.repository.credentialsId) {
                            credentials(pipelineConfig.repository.credentialsId)
                        }
                    }
                    branch("*/${pipelineConfig.repository.branch}")
                    extensions {
                        cleanBeforeCheckout()
                    }
                }
            }
            scriptPath(jenkinsConfig.jenkinsfilePath)
            lightweight(true)
        }
    }

    properties {
        buildDiscarder {
            strategy {
                logRotator {
                    daysToKeepStr(jenkinsConfig.jobConfiguration.logRotation.daysToKeep.toString())
                    numToKeepStr(jenkinsConfig.jobConfiguration.logRotation.numToKeep.toString())
                    artifactDaysToKeepStr(jenkinsConfig.jobConfiguration.logRotation.artifactDaysToKeep.toString())
                    artifactNumToKeepStr(jenkinsConfig.jobConfiguration.logRotation.artifactNumToKeep.toString())
                }
            }
        }
        // Allow any downstream job to copy artifacts from this build.
        copyArtifactPermissionProperty {
            projectNames('*')
        }
    }
}

println "✓ Platform build job created/updated: ${jobName}"
