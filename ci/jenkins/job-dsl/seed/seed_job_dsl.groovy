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
 * Consolidated Seed Job DSL Script
 *
 * Run by Jenkinsfile.seed (ci/jenkins/Jenkinsfile.seed) via the jobDsl() step.
 * Do not run this directly as a Freestyle Job DSL step.
 *
 * What this script does:
 *   1. Reads adoptium_pipeline_config.json and jenkins_job_config.json from
 *      the vendor config repo checkout in the workspace root.
 *   2. Parses the pre-computed COLLATED_PARAMS_JSON produced by
 *      SeedHelper.groovy (via collect-stage-params.py) — the single source of
 *      truth for stage parameter collation shared by seed, launch, and build jobs.
 *   3. Creates Build_openjdk_launchers/ folder and one launch job per enabled
 *      JDK version, each carrying the full collated stage parameter set.
 *   4. Creates Build_openjdk/ folder and Jenkins views.
 *
 * Workspace layout (set up by ci/jenkins/Jenkinsfile.seed):
 *   <workspace>/
 *     adoptium_pipeline_config.json   — vendor config repo root (SCM checkout)
 *     jenkins_job_config.json         — vendor config repo root
 *     configurations/                 — per-version platform configs
 *     vendor-scripts/                 — vendor stage param overrides
 *     collated-stage-params.json      — written by SeedHelper via collect-stage-params.py
 *     pipelines/                      — ci-adoptium-pipelines checkout
 *       scripts/stages/               — default *.params.json files
 *       ci/jenkins/job-dsl/
 *
 * Binding variables (passed via additionalParameters from SeedHelper.groovy):
 *   CONFIG_REPO_URL      — vendor config repo URL (baked into generated launch jobs)
 *   CONFIG_REPO_BRANCH   — vendor config repo branch (baked into generated launch jobs)
 *   COLLATED_PARAMS_JSON — JSON produced by collect-stage-params.py
 *   PIPELINE_COMMIT_SHA  — SHA of the ci-adoptium-pipelines checkout
 *
 * jenkins_job_config.json fields consumed here:
 *   pipelineBaseFolder   — (optional) Jenkins folder path under which all generated
 *                          jobs and views are placed (e.g. "MyOrg/OpenJDK").
 *                          Omit or set to "" to generate at the Jenkins root.
 */

import groovy.json.JsonSlurper

// ============================================================================
// STEP 1: Validate binding variables
// ============================================================================

def configRepoUrl      = binding.variables.get('CONFIG_REPO_URL')       ?: ''
def configRepoBranch   = binding.variables.get('CONFIG_REPO_BRANCH')    ?: ''
def pipelineCommitSha  = binding.variables.get('PIPELINE_COMMIT_SHA')   ?: 'unknown'
def collatedParamsJson = binding.variables.get('COLLATED_PARAMS_JSON')  ?: ''

final int SEPARATOR_WIDTH  = 80
final int VERSION_MODULO   = 4
final int LTS_BASE_VERSION = 17
final int DUPLICATE_ZERO   = 0

if (!configRepoUrl?.trim()) {
    throw new IllegalStateException(
        'CONFIG_REPO_URL is required but was not provided.\n' +
        'Set it as a parameter on the seed job (see docs/JOB_DSL_AUTOMATION.md).'
    )
}
if (!configRepoBranch?.trim()) {
    throw new IllegalStateException(
        'CONFIG_REPO_BRANCH is required but was not provided.\n' +
        'Set it as a parameter on the seed job (see docs/JOB_DSL_AUTOMATION.md).'
    )
}
if (!collatedParamsJson?.trim()) {
    throw new IllegalStateException(
        'COLLATED_PARAMS_JSON is empty.\n' +
        'Ensure SeedHelper.groovy ran collect-stage-params.py successfully.'
    )
}

println '=' * SEPARATOR_WIDTH
println 'SEED JOB'
println "  CONFIG_REPO_URL    : ${configRepoUrl}"
println "  CONFIG_REPO_BRANCH : ${configRepoBranch}"
println "  PIPELINE_COMMIT_SHA: ${pipelineCommitSha}"
println '=' * SEPARATOR_WIDTH
println ''
// (pipelineBaseFolder is printed after jenkinsConfig is loaded below)

// ============================================================================
// STEP 2: Load configuration using readFileFromWorkspace
// ============================================================================

def slurper = new JsonSlurper()

def pipelineConfig = slurper.parseText(readFileFromWorkspace('adoptium_pipeline_config.json'))
println '✓ Loaded adoptium_pipeline_config.json'
println "  Active JDK versions: ${pipelineConfig.activeJdkVersions.findAll { it.enabled }*.version.join(', ')}"

def jenkinsConfig = slurper.parseText(readFileFromWorkspace('jenkins_job_config.json'))
println '✓ Loaded jenkins_job_config.json'

// jenkins_credential_config.json is optional — absent for public-repo setups.
def credentialConfig = [:]
try {
    credentialConfig = slurper.parseText(readFileFromWorkspace('jenkins_credential_config.json'))
    println '✓ Loaded jenkins_credential_config.json'
} catch (Exception e) {
    println 'ℹ️  jenkins_credential_config.json not found — no SCM credentials configured'
}

// Read optional base folder from jenkins_job_config.json.
// Strip any trailing slashes so path construction is consistent.
def pipelineBaseFolder = (jenkinsConfig?.pipelineBaseFolder ?: '').toString().trim().replaceAll(/\/+$/, '')

// Helper: prefix a job/view/folder name with the base folder when one is set.
// Returns the name unchanged when pipelineBaseFolder is empty (Jenkins root).
def inFolder = { String name -> pipelineBaseFolder ? "${pipelineBaseFolder}/${name}" : name }

println "  pipelineBaseFolder : ${pipelineBaseFolder ?: '(root)'}\n"

// ============================================================================
// STEP 3: Parse collated stage parameters from pre-computed JSON
// ============================================================================

// COLLATED_PARAMS_JSON was produced by collect-stage-params.py (via SeedHelper)
// with priority group ordering and stageDisabled filtering already applied.
// The cross-stem group merge (same group name across stages → single entry with
// a stageIds list) is re-applied here to obtain the stageIds list structure
// that configure{} needs for separator labels.
def rawGroups = slurper.parseText(collatedParamsJson).groups ?: []

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
            name:           gname,
            description:    grp.description ?: '',
            stageIds:       new ArrayList(incomingIds),
            stageDisabled:  grp.stageDisabled ?: false,
            stageCondition: grp.stageCondition ?: [],
            parameters:     new ArrayList(grp.parameters ?: [])
        ]
    }
}

// Capture at script scope — configure{} runs with a different delegate.
def collatedParamGroups = mergedGroupMap.values().toList()
println "✓ Received ${rawGroups.size()} raw group(s), merged to ${collatedParamGroups.size()} group(s)\n"

// ============================================================================
// STEP 4: Create folders
// ============================================================================

// If a base folder is specified, ensure every ancestor folder in the path
// exists before creating the leaf folders.  Job DSL's folder() only creates
// the leaf; intermediate path segments must each be declared explicitly.
if (pipelineBaseFolder) {
    List parts = pipelineBaseFolder.tokenize('/')
    parts.eachWithIndex { String part, int idx ->
        String ancestorPath = parts[0..idx].join('/')
        folder(ancestorPath) { }
    }
}

folder(inFolder('Build_openjdk_launchers')) {
    displayName('Build_openjdk_launchers')
    description('Launch orchestrator jobs that trigger platform-specific builds across all selected platforms for a given JDK version')
}

folder(inFolder('Build_openjdk')) {
    displayName('Build_openjdk')
    description('OpenJDK platform build pipeline jobs, named using the AQA-style Build_openjdk<version>_<distro>_<arch>_<os> convention')
}

// ============================================================================
// STEP 5: Create Launch Orchestrator Jobs
// ============================================================================

def pipelineRepoUrl           = pipelineConfig.repository?.url ?: 'https://github.com/adoptium/ci-adoptium-pipelines.git'
def pipelineRepoBranch        = pipelineConfig.repository?.branch ?: 'main'
def pipelineRepoCredentialsId = credentialConfig.pipelineRepoCredentialsId ?: ''
def defaultParams             = jenkinsConfig.jobConfiguration?.defaultParameters ?: [:]

println 'Creating launch orchestrator jobs for active JDK versions:'
pipelineConfig.activeJdkVersions.findAll { it.enabled }.each { versionInfo ->
    def version    = versionInfo.version
    def configFile = "${pipelineConfig.configFilePrefix ?: 'configurations/'}${version}${pipelineConfig.configFileSuffix ?: '_pipeline_config.json'}"

    def versionNum = version.replaceAll(/[^\d]/, '').toInteger()
    def isLts      = (versionNum == 8 || versionNum == 11 || (versionNum >= LTS_BASE_VERSION && (versionNum - LTS_BASE_VERSION) % VERSION_MODULO == 0))

    println "  → JDK ${version}${isLts ? ' [LTS]' : ''}"

    // Load platform list from the per-version config file
    def platforms = []
    try {
        def jdkConfig = slurper.parseText(readFileFromWorkspace(configFile))
        platforms = (jdkConfig.buildConfigurations?.keySet() as List)?.sort() ?: []
        println "    Available platforms: ${platforms.join(', ')}"
    } catch (Exception e) {
        println "    WARNING: ${configFile} not found — using 'all' as default platform choice"
        platforms = ['all']
    }

    def jobName = inFolder("Build_openjdk_launchers/Build_openjdk${version.replaceAll(/[^\d]/, '')}_launch")

    pipelineJob(jobName) {
        displayName("Build_openjdk${version.replaceAll(/[^\d]/, '')}_launch${isLts ? ' (LTS)' : ''}")
        description("""\
            <p>Launch orchestrator for JDK <strong>${version}</strong> builds.${isLts ? ' <span style="color:#b8860b">&#9733; Long Term Support (LTS)</span>' : ''}</p>
            <p>This job:</p>
            <ol>
              <li>Reads platform configuration from: <code>${configFile}</code></li>
              <li>Creates/updates platform-specific build jobs when the pipeline SHA changes</li>
              <li>Launches builds for selected platforms in parallel</li>
              <li>Aggregates and reports results</li>
            </ol>
            <p>Stage parameters are collated from <code>scripts/stages/*.params.json</code> and any
            <code>vendor-scripts/*.params.json</code> overrides in the config repo.
            All collated parameters are forwarded automatically to every platform build job launched.</p>
            <p style="color:#6a6a6a;font-size:0.85em">pipeline-sha:${pipelineCommitSha}</p>""".stripIndent().trim())

        quietPeriod(5)

        parameters {
            stringParam {
                name('JDK_VERSION')
                defaultValue(version.replaceAll(/[^\d]/, ''))
                description('JDK version number — fixed for this launch job')
                trim(true)
            }
            stringParam {
                name('GROUP_UID')
                defaultValue('')
                description('Group identifier for this launch run. Auto-generated if empty.')
                trim(true)
            }
            choiceParam('PLATFORMS', ['all'] + platforms,
                'Select platform to build, or "all" for all available platforms')
            choiceParam('RELEASE_TYPE',
                ['NIGHTLY', 'WEEKLY', 'RELEASE'],
                'Type of release build (NIGHTLY = default nightly, WEEKLY = EA beta, RELEASE = official)')

            // ── Collated stage parameters ─────────────────────────────────────────
            // Stage-gate booleans (RUN_TESTS, SIGN_ARTIFACTS, etc.) and all other
            // stage-specific params are emitted here from the collated params JSON.
            // Groups where stageDisabled=true are skipped — no parameters generated.
            // Priority group ordering (Stage Selections first) is already applied
            // by collect-stage-params.py — collatedParamGroups preserves that order.
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

            // Values baked in at generation time by the seed job — do not edit manually.
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
                            url(pipelineRepoUrl)
                            if (pipelineRepoCredentialsId) {
                                credentials(pipelineRepoCredentialsId)
                            }
                        }
                        branch("*/${pipelineRepoBranch}")
                        extensions {
                            cleanBeforeCheckout()
                        }
                    }
                }
                scriptPath('ci/jenkins/Jenkinsfile.launch')
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
            // disableResume() is intentionally omitted: the launch job uses
            // build(wait:true) to track downstream platform builds across
            // potential controller restarts.  PERFORMANCE_OPTIMIZED durability
            // (set by disableResume) interferes with the downstream build's
            // PlaceholderTask lifecycle and causes it to be stopped immediately.
        }
    }
}

println '✓ Launch orchestrator jobs created successfully\n'

// ============================================================================
// STEP 6: Create Views
// ============================================================================

// listView("a/b/viewName") creates a view named "viewName" inside folder "a/b".
// The jobs{} regex is matched against job names relative to the view's *parent*
// folder (i.e. "a/b"), so the prefix must include the immediate subfolder that
// holds the jobs.
//
// Layout when pipelineBaseFolder = "temurin-pipelines":
//   View path  : temurin-pipelines/Build_openjdk_launchers
//   Job path   : temurin-pipelines/Build_openjdk_launchers/Build_openjdkNN_launch
//   Regex base : Build_openjdk_launchers/   (relative to temurin-pipelines)
//
// Layout when pipelineBaseFolder is empty (Jenkins root):
//   View path  : Build_openjdk_launchers
//   Job path   : Build_openjdk_launchers/Build_openjdkNN_launch
//   Regex base : Build_openjdk_launchers/   (relative to root — same pattern)
//
// In both cases the regex prefix is always just the immediate subfolder name.
listView(inFolder('Build_openjdk_launchers')) {
    description('Launch orchestrator jobs for coordinating platform builds (Build_openjdk<version>_launch)')
    jobs {
        regex('Build_openjdk_launchers/Build_openjdk\\d+_launch')
    }
    recurse(true)
    columns {
        status()
        weather()
        name()
        lastSuccess()
        lastFailure()
        lastDuration()
        buildButton()
    }
}

listView(inFolder('Build_openjdk')) {
    description('Platform-specific build jobs — AQA-style naming: Build_openjdk<version>_<distro>_<arch>_<os>')
    jobs {
        regex('Build_openjdk/Build_openjdk\\d+_[^_]+_[^_]+_[^_]+')
    }
    recurse(true)
    columns {
        status()
        weather()
        name()
        lastSuccess()
        lastFailure()
        lastDuration()
        buildButton()
    }
}

println '✓ Views created successfully\n'
println '=' * SEPARATOR_WIDTH
println 'Seed job execution complete!'
println '=' * SEPARATOR_WIDTH
