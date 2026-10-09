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
 *   4. Creates Build_openjdk/ folder and Jenkins views for each enabled JDK version.
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
 *   PIPELINE_BASE_FOLDER — (optional) Jenkins folder path under which all generated
 *                          jobs and views are placed (e.g. "MyOrg/OpenJDK").
 *                          Omit or set to "" to generate at the Jenkins root.
 *                          Set as a parameter on the seed job — NOT in jenkins_job_config.json.
 */

import groovy.json.JsonSlurper

// Map shorthand permission names (e.g. "Job/Read") to fully-qualified DSL names.
// The Job DSL permission() call requires FQN form.
@groovy.transform.Field
static final Map<String, String> PERMISSION_SHORTHAND = [
    'Credentials/Create'      : 'com.cloudbees.plugins.credentials.CredentialsProvider.Create',
    'Credentials/Delete'      : 'com.cloudbees.plugins.credentials.CredentialsProvider.Delete',
    'Credentials/ManageDomains': 'com.cloudbees.plugins.credentials.CredentialsProvider.ManageDomains',
    'Credentials/Update'      : 'com.cloudbees.plugins.credentials.CredentialsProvider.Update',
    'Credentials/View'        : 'com.cloudbees.plugins.credentials.CredentialsProvider.View',
    'Job/Build'               : 'hudson.model.Item.Build',
    'Job/Cancel'              : 'hudson.model.Item.Cancel',
    'Job/Configure'           : 'hudson.model.Item.Configure',
    'Job/Create'              : 'hudson.model.Item.Create',
    'Job/Delete'              : 'hudson.model.Item.Delete',
    'Job/Discover'            : 'hudson.model.Item.Discover',
    'Job/ExtendedRead'        : 'hudson.model.Item.ExtendedRead',
    'Job/Move'                : 'hudson.model.Item.Move',
    'Job/Read'                : 'hudson.model.Item.Read',
    'Job/ViewStatus'          : 'hudson.model.Item.ViewStatus',
    'Job/Workspace'           : 'hudson.model.Item.Workspace',
    'Run/Delete'              : 'hudson.model.Run.Delete',
    'Run/Replay'              : 'hudson.model.Run.Replay',
    'Run/Update'              : 'hudson.model.Run.Update',
    'View/Configure'          : 'hudson.model.View.Configure',
    'View/Create'             : 'hudson.model.View.Create',
    'View/Delete'             : 'hudson.model.View.Delete',
    'View/Read'               : 'hudson.model.View.Read',
    'SCM/Tag'                 : 'hudson.scm.SCM.Tag',
].asImmutable()

/** Resolve a permission string to its FQN, passing through if already qualified. */
static String resolvePermission(String perm) {
    if (perm.contains('.')) { return perm }  // already FQN
    return PERMISSION_SHORTHAND.getOrDefault(perm, perm)
}

// ============================================================================
// STEP 1: Validate binding variables
// ============================================================================

def configRepoUrl      = binding.variables.get('CONFIG_REPO_URL')      ?: ''
def configRepoBranch   = binding.variables.get('CONFIG_REPO_BRANCH')   ?: ''
def pipelineCommitSha  = binding.variables.get('PIPELINE_COMMIT_SHA')  ?: 'unknown'
def collatedParamsJson = binding.variables.get('COLLATED_PARAMS_JSON') ?: ''
def triggerConfigJson  = binding.variables.get('TRIGGER_CONFIG_JSON')  ?: ''
// PIPELINE_BASE_FOLDER binding: set by the development seed job to target a sandbox
// folder without editing jenkins_job_config.json.  Empty string means "use the value
// from jenkins_job_config.json" (production default — binding is absent or blank).
def pipelineBaseFolderOverride = (binding.variables.get('PIPELINE_BASE_FOLDER') ?: '').toString().trim().replaceAll(/\/+$/, '')

// CONFIG_REPO_PREFIX: optional path prefix for all readFileFromWorkspace calls.
// Empty string (default) → seed layout: config files at workspace root.
// 'config-repo/' → trigger layout: config files under config-repo/ subdirectory.
def configRepoPrefix   = (binding.variables.get('CONFIG_REPO_PREFIX') ?: '').toString()
if (configRepoPrefix && !configRepoPrefix.endsWith('/')) { configRepoPrefix += '/' }

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
println "  CONFIG_REPO_URL     : ${configRepoUrl}"
println "  CONFIG_REPO_BRANCH  : ${configRepoBranch}"
println "  PIPELINE_COMMIT_SHA : ${pipelineCommitSha}"
println '=' * SEPARATOR_WIDTH
println ''

// ============================================================================
// STEP 2: Load configuration using readFileFromWorkspace
// ============================================================================

def slurper = new JsonSlurper()

def pipelineConfig = slurper.parseText(readFileFromWorkspace("${configRepoPrefix}adoptium_pipeline_config.json"))
println '✓ Loaded adoptium_pipeline_config.json'
println "  Active JDK versions: ${pipelineConfig.activeJdkVersions.findAll { it.enabled }*.version.join(', ')}"

def jenkinsConfig = slurper.parseText(readFileFromWorkspace("${configRepoPrefix}jenkins_job_config.json"))
println '✓ Loaded jenkins_job_config.json'

// pipelineBaseFolder: jenkins_job_config.json is the checked-in default (production).
// The PIPELINE_BASE_FOLDER binding overrides it when set by the development seed job,
// so developers can seed into a sandbox folder without touching the config file.
def pipelineBaseFolder = pipelineBaseFolderOverride ?: (jenkinsConfig.pipelineBaseFolder ?: '').toString().trim().replaceAll(/\/+$/, '')

// DEPLOYMENT_FILTER: when set (by reseedForTrigger), restrict processing to the single
// named deployment.  This prevents the trigger reseed from generating all deployments
// under the sandbox folder — only the deployment that owns the trigger is regenerated.
def deploymentFilterName = (binding.variables.get('DEPLOYMENT_FILTER') ?: '').toString().trim()
def deployments          = (jenkinsConfig.deployments ?: []) as List
if (deploymentFilterName) {
    deployments = deployments.findAll { it.name == deploymentFilterName }
    if (!deployments) {
        throw new IllegalStateException(
            "DEPLOYMENT_FILTER='${deploymentFilterName}' did not match any deployment in jenkins_job_config.json. " +
            "Available: ${(jenkinsConfig.deployments ?: []).collect { it.name }.join(', ')}"
        )
    }
}
println "  pipelineBaseFolder : ${pipelineBaseFolder ?: '(root)'}${pipelineBaseFolderOverride ? ' (overridden via PIPELINE_BASE_FOLDER parameter)' : ''}"
println "  deployments        : ${deployments.collect { it.name }.join(', ') ?: '(none)'}${deploymentFilterName ? ' (filtered to deployment: ' + deploymentFilterName + ')' : ''}"

// jenkins_credential_config.json is optional — absent when no credentials (e.g. for private repos or authenticated GitHub API access) are needed.
def credentialConfig = [:]
try {
    credentialConfig = slurper.parseText(readFileFromWorkspace("${configRepoPrefix}jenkins_credential_config.json"))
    println '✓ Loaded jenkins_credential_config.json'
} catch (Exception e) {
    println 'ℹ️  jenkins_credential_config.json not found — no SCM credentials configured'
}

// trigger_config.json — optional; absent for setups without automated triggers.

/**
 * Validate trigger_config.json structure and fail fast on known misconfigurations.
 *
 * Rules:
 *   1. No two entries may share the same "type" value — a type must appear at most
 *      once.  Duplicating a type entry is always a copy-paste mistake because all
 *      versions for a given type must be listed in a single "versions" array.
 *
 *   2. Within a type's "versions" array, every "version" value must be unique.
 *      Duplicate version entries under the same type would cause both parallel
 *      branches to share the same workspace paths, producing corrupted results
 *      (exactly the jdk21/jdk25 cross-contamination bug this guards against).
 *
 * Note: the same version appearing under different trigger types is intentional
 * and valid — e.g. jdk21 can legitimately appear under both "detect-ga-tag"
 * (stable release detection) and "detect-build-tag-for-github-release" (EA tag
 * detection).  Each type runs as a separate parallel branch with its own
 * version-scoped workspace paths, so there is no collision.
 *
 * Throws IllegalStateException listing every violation found so the seed fails
 * before creating any jobs.
 */
def validateTriggerConfig = { List triggers ->
    List errors = []

    // Rule 1 — duplicate type entries
    Map typeSeen = [:]    // type → first index (0-based)
    triggers.eachWithIndex { Map t, int i ->
        String type = t.type as String ?: "(missing type at index ${i})"
        if (typeSeen.containsKey(type)) {
            errors << "  Duplicate trigger type '${type}' at index ${i} (first seen at index ${typeSeen[type]}). " +
                      "All versions for a given type must be listed in a single 'versions' array."
        } else {
            typeSeen[type] = i
        }
    }

    // Rule 2 — duplicate version within the same type
    triggers.each { Map t ->
        String type = t.type as String ?: '(unknown type)'
        List versions = t.versions ?: []
        Set seenInThisType = [] as Set
        versions.eachWithIndex { Map v, int j ->
            String ver = v.version as String ?: "(missing version at index ${j} under type '${type}')"
            if (!seenInThisType.add(ver)) {
                errors << "  Duplicate version '${ver}' under trigger type '${type}'. " +
                          "Each version must appear at most once per type."
            }
        }
    }

    if (errors) {
        throw new IllegalStateException(
            "trigger_config.json validation failed with ${errors.size()} error(s):\n" +
            errors.join('\n') + '\n' +
            'Fix trigger_config.json before re-running the seed.'
        )
    }
}

def triggerConfig = [triggers: []]
if (triggerConfigJson?.trim()) {
    triggerConfig = slurper.parseText(triggerConfigJson)
    validateTriggerConfig(triggerConfig.triggers ?: [])
    println "✓ Loaded trigger_config.json (${triggerConfig.triggers?.size() ?: 0} trigger type(s))"
} else {
    println 'ℹ️  trigger_config.json not provided — no trigger jobs will be created'
}

// Helper: prefix a job/view/folder name with the base folder when one is set.
// Returns the name unchanged when pipelineBaseFolder is empty (Jenkins root).
def inFolder = { String name -> pipelineBaseFolder ? "${pipelineBaseFolder}/${name}" : name }

// Helper: compute the effective folder path for a deployment.
// e.g. pipelineBaseFolder="temurin", deployment.folder="release" → "temurin/release"
def deploymentFolder = { Map dep ->
    String depFolder = (dep.folder ?: '').toString().trim().replaceAll(/\/+$/, '')
    if (pipelineBaseFolder && depFolder) { return "${pipelineBaseFolder}/${depFolder}" }
    if (pipelineBaseFolder)              { return pipelineBaseFolder }
    if (depFolder)                       { return depFolder }
    return ''
}

// Helper: like inFolder but scoped to a deployment's effective folder.
def inDeploymentFolder = { Map dep, String name ->
    String base = deploymentFolder(dep)
    base ? "${base}/${name}" : name
}

// ============================================================================
// STEP 3: Parse collated stage parameters from pre-computed JSON
// ============================================================================

// COLLATED_PARAMS_JSON was produced by collect-stage-params.py (via SeedHelper)
// with priority group ordering and stageDisabled filtering already applied.
// Every group already carries a stageIds list; disabled stages are already
// excluded from groups entirely, so no further filtering is needed here.
def rawGroups = slurper.parseText(collatedParamsJson).groups ?: []

def mergedGroupMap = [:] as LinkedHashMap
rawGroups.each { grp ->
    def gname = grp.name
    // stageIds is always a list in the new schema.
    def incomingIds = grp.stageIds ?: []
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
println "✓ Received ${rawGroups.size()} raw group(s), merged to ${collatedParamGroups.size()} group(s)\n"

// ============================================================================
// STEP 4: Create folders
// ============================================================================

// Ensure every ancestor folder in pipelineBaseFolder exists.
if (pipelineBaseFolder) {
    List parts = pipelineBaseFolder.tokenize('/')
    parts.eachWithIndex { String part, int idx ->
        String ancestorPath = parts[0..idx].join('/')
        folder(ancestorPath) { }
    }
}

// Create per-deployment folders and their subfolders.
// If no deployments are declared, fall back to creating the standard folders
// directly under pipelineBaseFolder (backwards-compatible behaviour).
if (deployments) {
    deployments.each { Map dep ->
        String depBase = deploymentFolder(dep)
        if (depBase) {
            // Ensure all ancestor segments of the deployment folder exist
            List parts = depBase.tokenize('/')
            parts.eachWithIndex { String part, int idx ->
                String currentFolder = parts[0..idx].join('/')
                boolean isDeploymentFolder = (idx == parts.size() - 1)
                folder(currentFolder) {
                    if (isDeploymentFolder) {
                        displayName(dep.name)
                        if (dep.description) {
                            description(dep.description)
                        }
                        if (dep.authorization) {
                            // Use a single configure block to set both permissions and
                            // the inheritanceStrategy.  Mixing authorization{} DSL with a
                            // configure{} block in the same folder() closure causes the
                            // two blocks to produce separate AuthorizationMatrixProperty
                            // nodes, so the inheritanceStrategy ends up on an empty node
                            // and "Enable project-based security" is never applied.
                            configure { Node folderNode ->
                                def props = folderNode / 'properties'
                                def authMatrix = props / 'com.cloudbees.hudson.plugins.folder.properties.AuthorizationMatrixProperty'
                                if (dep.authorization.inheritParent == false) {
                                    authMatrix.appendNode('inheritanceStrategy', [class: 'org.jenkinsci.plugins.matrixauth.inheritance.NonInheritingStrategy'])
                                }
                                dep.authorization.permissions?.each { Map perm ->
                                    if (perm.permission && perm.grantee) {
                                        authMatrix.appendNode('permission', "${resolvePermission(perm.permission as String)}:${perm.grantee}")
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        folder(inDeploymentFolder(dep, 'Build_openjdk_launchers')) {
            displayName('Build_openjdk_launchers')
            description("Launch orchestrator jobs for the '${dep.name}' deployment")
        }
        folder(inDeploymentFolder(dep, 'Build_openjdk')) {
            displayName('Build_openjdk')
            description("Platform build jobs for the '${dep.name}' deployment (AQA-style naming)")
        }
        if (dep.triggers) {
            folder(inDeploymentFolder(dep, 'Triggers')) {
                displayName('Triggers')
                description("Automated trigger jobs for the '${dep.name}' deployment")
            }
        }
    }
} else {
    // No deployments declared — create standard folders under pipelineBaseFolder
    folder(inFolder('Build_openjdk_launchers')) {
        displayName('Build_openjdk_launchers')
        description('Launch orchestrator jobs that trigger platform-specific builds across all selected platforms for a given JDK version')
    }
    folder(inFolder('Build_openjdk')) {
        displayName('Build_openjdk')
        description('OpenJDK platform build pipeline jobs, named using the AQA-style Build_openjdk<version>_<distro>_<arch>_<os> convention')
    }
}

// ============================================================================
// STEP 5: Create Launch Orchestrator Jobs
// ============================================================================

// PIPELINES_REPO_URL / PIPELINES_REPO_BRANCH bindings are set by the development
// seed job (via SeedHelper) to bake a fork URL/branch into generated jobs without
// editing adoptium_pipeline_config.json.  Empty string → use the config-file value.
def pipelinesRepoUrlOverride    = (binding.variables.get('PIPELINES_REPO_URL')    ?: '').toString().trim()
def pipelinesRepoBranchOverride = (binding.variables.get('PIPELINES_REPO_BRANCH') ?: '').toString().trim()
def pipelineRepoUrl           = pipelinesRepoUrlOverride    ?: (pipelineConfig.repository?.url    ?: 'https://github.com/adoptium/ci-adoptium-pipelines.git')
def pipelineRepoBranch        = pipelinesRepoBranchOverride ?: (pipelineConfig.repository?.branch ?: 'main')
if (pipelinesRepoUrlOverride || pipelinesRepoBranchOverride) {
    println "⚠ Pipelines repo overridden via bindings (development seed): ${pipelineRepoUrl} @ ${pipelineRepoBranch}"
}
def pipelineRepoCredentialsId = credentialConfig.pipelineRepoCredentialsId ?: ''
def configRepoCredentialsId   = credentialConfig.configRepoCredentialsId   ?: ''
// Validate: reject old-format configs that still carry a top-level jobConfiguration.
// Each deployment must now declare its own jobConfiguration (defaultParameters + logRotation).
if (jenkinsConfig.containsKey('jobConfiguration')) {
    error('''\
        jenkins_job_config.json uses the old schema: top-level "jobConfiguration" is no longer supported.
        Move "defaultParameters" and "logRotation" into a "jobConfiguration" block inside each deployment entry,
        and remove the top-level "jobConfiguration" key.  See docs/CONFIG_SCHEMA.md for the updated schema.'''.stripIndent())
}

// Helper: return the defaultParameters for a deployment.
// Each deployment owns its full parameter set — no base/override merge required.
def mergedDefaultParams = { Map dep ->
    return new LinkedHashMap(dep.jobConfiguration?.defaultParameters ?: [:])
}

// Helper: create the launch job parameter block (closure reused per deployment).
def createLaunchJobParams = { Map dep, String version, List platforms, Map defaultParams ->
    return {
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
        // Honour defaultParams.RELEASE_TYPE by placing the configured default first.
        def allReleaseTypes  = ['NIGHTLY', 'WEEKLY', 'RELEASE']
        def releaseTypeDefault = defaultParams?.RELEASE_TYPE?.toString()?.trim()
        def releaseTypeChoices = releaseTypeDefault && allReleaseTypes.contains(releaseTypeDefault)
            ? ([releaseTypeDefault] + allReleaseTypes.findAll { it != releaseTypeDefault })
            : allReleaseTypes
        choiceParam('RELEASE_TYPE',
            releaseTypeChoices,
            'Type of release build (NIGHTLY = default nightly, WEEKLY = EA beta, RELEASE = official)')

        // Collated stage parameters
        collatedParamGroups.each { group ->
            def stageLabel  = group.stageIds.join('_').replaceAll(/\W+/, '_')
            def stageHeader = group.stageIds.size() == 1
                ? "stage: ${group.stageIds[DUPLICATE_ZERO]}"
                : "stages: ${group.stageIds.join(', ')}"
            separator {
                name("__sep_${stageLabel}_${group.name.replaceAll(/\W+/, '_')}")
                sectionHeader("${group.name}  [${stageHeader}]")
                sectionHeaderStyle('')
                if (group.description) { description(group.description) }
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

        // Config repo coordinates — baked in at generation time
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
        stringParam {
            name('CONFIG_REPO_CREDENTIALS_ID')
            defaultValue(configRepoCredentialsId)
            description('Jenkins credential ID for the vendor config repo — baked in at job-generation time.')
            trim(true)
        }
        stringParam {
            name('CONFIG_DEPLOYMENT_NAME')
            defaultValue(dep.name as String)
            description('Deployment name — baked in at job-generation time. Used by platform build DSL to resolve jobConfiguration.')
            trim(true)
        }
        stringParam {
            name('PIPELINES_REPO_URL')
            defaultValue(pipelineRepoUrl)
            description('ci-adoptium-pipelines repo URL — baked in at job-generation time. Overrides repository.url in adoptium_pipeline_config.json when non-empty.')
            trim(true)
        }
        stringParam {
            name('PIPELINES_REPO_BRANCH')
            defaultValue(pipelineRepoBranch)
            description('ci-adoptium-pipelines branch — baked in at job-generation time. Overrides repository.branch in adoptium_pipeline_config.json when non-empty.')
            trim(true)
        }
    }
}

// Determine the set of deployment folder prefixes to create launch jobs under.
// If no deployments declared, create a single set under pipelineBaseFolder directly.
def launchDeployments = deployments ?: [[name: '(default)', folder: '', jobConfiguration: [:]]]

println 'Creating launch orchestrator jobs:'
launchDeployments.each { Map dep ->
    def effectiveDefaultParams = mergedDefaultParams(dep)
    def launchFolder = deployments ? inDeploymentFolder(dep, 'Build_openjdk_launchers') : inFolder('Build_openjdk_launchers')

    pipelineConfig.activeJdkVersions.findAll { it.enabled }.each { versionInfo ->
        def version    = versionInfo.version
        def configFile = "${configRepoPrefix}${pipelineConfig.configFilePrefix ?: 'configurations/'}${version}${pipelineConfig.configFileSuffix ?: '_pipeline_config.json'}"
        def versionNum = version.replaceAll(/[^\d]/, '').toInteger()
        def isLts      = (versionNum == 8 || versionNum == 11 || (versionNum >= LTS_BASE_VERSION && (versionNum - LTS_BASE_VERSION) % VERSION_MODULO == 0))

        println "  [${dep.name}] → JDK ${version}${isLts ? ' [LTS]' : ''}"

        def platforms = []
        try {
            def jdkConfig  = slurper.parseText(readFileFromWorkspace(configFile))
            def allKeys    = (jdkConfig.buildConfigurations?.keySet() as List) ?: []
            def targetList = jdkConfig.targetConfigurations as List
            // targetConfigurations is the active subset; fall back to all keys when absent.
            platforms = (targetList != null && !targetList.isEmpty())
                ? targetList.findAll { allKeys.contains(it) }.sort()
                : allKeys.sort()
        } catch (Exception e) {
            println "    WARNING: ${configFile} not found — using 'all' as default platform choice"
            platforms = ['all']
        }

        def jobName = "${launchFolder}/Build_openjdk${version.replaceAll(/[^\d]/, '')}_launch"

        pipelineJob(jobName) {
            displayName("Build_openjdk${version.replaceAll(/[^\d]/, '')}_launch${isLts ? ' (LTS)' : ''}")
            description("""\
                <p>Launch orchestrator for JDK <strong>${version}</strong> — deployment: <strong>${dep.name}</strong>.${isLts ? ' <span style="color:#b8860b">&#9733; LTS</span>' : ''}</p>
                <p>pipeline-sha:${pipelineCommitSha}</p>""".stripIndent().trim())

            quietPeriod(5)

            parameters(createLaunchJobParams(dep, version, platforms, effectiveDefaultParams))

            definition {
                cpsScm {
                    scm {
                        git {
                            remote {
                                url(pipelineRepoUrl)
                                if (pipelineRepoCredentialsId) { credentials(pipelineRepoCredentialsId) }
                            }
                            branch("*/${pipelineRepoBranch}")
                            extensions { cleanBeforeCheckout() }
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
                            def lr = dep.jobConfiguration?.logRotation ?: [:]
                            daysToKeepStr((lr.daysToKeep ?: 30).toString())
                            numToKeepStr((lr.numToKeep ?: 50).toString())
                            artifactDaysToKeepStr((lr.artifactDaysToKeep ?: 7).toString())
                            artifactNumToKeepStr((lr.artifactNumToKeep ?: 10).toString())
                        }
                    }
                }
            }
        }
    }
}

println '✓ Launch orchestrator jobs created successfully\n'

// ============================================================================
// STEP 6: Create Trigger Jobs (one per trigger type per deployment)
// ============================================================================

if (deployments && triggerConfig.triggers) {
    // Build a lookup map: triggerType → versions list from trigger_config.json
    def triggerVersionsMap = [:]
    triggerConfig.triggers.each { Map t -> triggerVersionsMap[t.type] = t.versions ?: [] }

    println 'Creating trigger jobs:'
    deployments.each { Map dep ->
        List depTriggers = dep.triggers ?: []
        if (!depTriggers) {
            println "  [${dep.name}] no triggers declared — skipping"
            return
        }

        def effectiveDefaultParams = mergedDefaultParams(dep)
        def triggerFolder          = inDeploymentFolder(dep, 'Triggers')
        def launchJobBasePath      = inDeploymentFolder(dep, 'Build_openjdk_launchers')

        depTriggers.each { triggerEntry ->
            // Each entry may be a plain String or a Map { type, cronSchedule }
            String triggerType     = (triggerEntry instanceof Map) ? triggerEntry.type    : triggerEntry as String
            String overrideCron    = (triggerEntry instanceof Map) ? triggerEntry.cronSchedule : null

            List versions = (triggerVersionsMap[triggerType] ?: []).findAll { it.enabled }
            if (!versions) {
                println "  [${dep.name}] ${triggerType}: no enabled versions — skipping"
                return
            }

            println "  [${dep.name}] → ${triggerType} (${versions.size()} version(s))"

            // Cron schedule: prefer explicit override from jenkins_job_config, then fall back to
            // built-in defaults (weekly on Sunday for weekly-head, daily otherwise).
            String defaultCron     = (triggerType == 'weekly-head') ? 'H 4 * * 0' : 'H 3 * * *'
            String cronSchedule    = overrideCron ?: defaultCron

            def jobName = "${triggerFolder}/Trigger_${triggerType.replaceAll(/[^a-zA-Z0-9_-]/, '_')}"

            pipelineJob(jobName) {
                displayName("Trigger_${triggerType}")
                description("""\
                    <p>Automated trigger for type <strong>${triggerType}</strong> — deployment: <strong>${dep.name}</strong>.</p>
                    <p>${dep.description ?: ''}</p>
                    <p>Runs on cron: <code>${cronSchedule}</code></p>
                    <p>Targets: <code>${launchJobBasePath}</code></p>
                    <p style="color:#6a6a6a;font-size:0.85em">pipeline-sha:${pipelineCommitSha}</p>""".stripIndent().trim())

                parameters {
                    stringParam {
                        name('DEPLOYMENT_NAME')
                        defaultValue(dep.name as String)
                        description('Deployment name — baked in at generation time')
                        trim(true)
                    }
                    stringParam {
                        name('TRIGGER_TYPE')
                        defaultValue(triggerType)
                        description('Trigger type stem — baked in at generation time')
                        trim(true)
                    }
                    textParam('TRIGGER_VERSIONS_JSON',
                        groovy.json.JsonOutput.prettyPrint(groovy.json.JsonOutput.toJson(versions)),
                        'JSON array of enabled version configs for this trigger type — baked in at generation time')
                    stringParam {
                        name('PIPELINE_BASE_FOLDER')
                        defaultValue(pipelineBaseFolder)
                        description('Jenkins root folder under which all generated jobs live — baked in at generation time. Empty string means Jenkins root.')
                        trim(true)
                    }
                    textParam('DEFAULT_PARAMETERS_JSON',
                        groovy.json.JsonOutput.prettyPrint(groovy.json.JsonOutput.toJson(effectiveDefaultParams)),
                        'Merged default parameters for this deployment — baked in at generation time')
                    stringParam {
                        name('CONFIG_REPO_URL')
                        defaultValue(configRepoUrl)
                        description('Vendor config repo URL — baked in at generation time')
                        trim(true)
                    }
                    stringParam {
                        name('CONFIG_REPO_BRANCH')
                        defaultValue(configRepoBranch)
                        description('Vendor config repo branch — baked in at generation time')
                        trim(true)
                    }
                    stringParam {
                        name('CONFIG_REPO_CREDENTIALS_ID')
                        defaultValue(configRepoCredentialsId)
                        description('Jenkins credential ID for the config repo — baked in at generation time')
                        trim(true)
                    }
                }

                definition {
                    cpsScm {
                        scm {
                            git {
                                remote {
                                    url(pipelineRepoUrl)
                                    if (pipelineRepoCredentialsId) { credentials(pipelineRepoCredentialsId) }
                                }
                                branch("*/${pipelineRepoBranch}")
                                extensions { cleanBeforeCheckout() }
                            }
                        }
                        scriptPath('ci/jenkins/Jenkinsfile.trigger')
                        lightweight(true)
                    }
                }

                properties {
                    pipelineTriggers {
                        triggers {
                            cron {
                                spec(cronSchedule)
                            }
                        }
                    }
                    buildDiscarder {
                        strategy {
                            logRotator {
                                def lr = dep.jobConfiguration?.logRotation ?: [:]
                                daysToKeepStr((lr.daysToKeep ?: 30).toString())
                                numToKeepStr((lr.numToKeep ?: 50).toString())
                                artifactDaysToKeepStr((lr.artifactDaysToKeep ?: 7).toString())
                                artifactNumToKeepStr((lr.artifactNumToKeep ?: 10).toString())
                            }
                        }
                    }
                }
            }
        }
    }
    println '✓ Trigger jobs created successfully\n'
} else {
    println 'ℹ️  No deployments with triggers or no trigger_config.json — skipping trigger job creation\n'
}

// ============================================================================
// STEP 7: Create Views (per deployment when deployments are declared)
// ============================================================================

def enabledVersions = pipelineConfig.activeJdkVersions.findAll { it.enabled }*.version

if (deployments) {
    deployments.each { Map dep ->
        enabledVersions.each { String v ->
            def viewPath = inDeploymentFolder(dep, v)
            listView(viewPath) {
                description("Platform build jobs for ${v} — ${dep.name} deployment")
                jobs {
                    regex(".*${v}_(?!launch).*")
                }
                recurse(true)
                columns {
                    status(); weather(); name(); lastSuccess(); lastFailure(); lastDuration(); buildButton()
                }
            }
        }
    }
} else {
    enabledVersions.each { String v ->
        def viewPath = inFolder(v)
        listView(viewPath) {
            description("Platform build jobs for ${v}")
            jobs {
                regex(".*${v}_(?!launch).*")
            }
            recurse(true)
            columns {
                status(); weather(); name(); lastSuccess(); lastFailure(); lastDuration(); buildButton()
            }
        }
    }
}

println '✓ Views created successfully\n'
println '=' * SEPARATOR_WIDTH
println 'Seed job execution complete!'
println '=' * SEPARATOR_WIDTH
