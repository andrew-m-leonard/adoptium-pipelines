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
 * SeedHelper.groovy — loaded by Jenkinsfile.seed and Jenkinsfile.trigger.
 *
 * Encapsulates the collation and Job DSL invocation so that callers stay
 * minimal and the logic lives alongside the rest of the pipeline library.
 *
 * Two entry points with different workspace layouts:
 *
 *   generateJobs()     — called by Jenkinsfile.seed
 *     config repo files at workspace root, pipeline repo under pipelines/
 *
 *   reseedForTrigger() — called by Jenkinsfile.trigger before firing launch jobs
 *     pipeline repo at workspace root (checkout scm), config repo under config-repo/
 *     Ensures launch job parameters always match the config repo truth, even if
 *     an admin has manually edited a parameter default in the Jenkins UI.
 */

/**
 * Run the Python collator and invoke the Job DSL script to create/update all
 * launch and trigger jobs for every deployment declared in jenkins_job_config.json.
 *
 * Workspace layout (Jenkinsfile.seed):
 *   <workspace>/
 *     config-repo/                    — config repo checkout (explicit, parameter-driven)
 *       adoptium_pipeline_config.json
 *       jenkins_job_config.json
 *       vendor-scripts/
 *       trigger_config.json           — optional
 *     pipelines/                      — ci-adoptium-pipelines checkout
 *       scripts/stages/
 *       ci/jenkins/job-dsl/
 *
 * @param configRepoUrl      Vendor config repo URL — baked into generated jobs.
 * @param configRepoBranch   Vendor config repo branch — baked into generated jobs.
 * @param pipelineCommitSha  SHA of the ci-adoptium-pipelines checkout.
 * @param pipelineBaseFolder (optional) Jenkins folder path to place all generated jobs
 *                           under (e.g. "MyOrg/OpenJDK").  When non-empty, overrides
 *                           pipelineBaseFolder in jenkins_job_config.json — intended for
 *                           use by the development seed job to target a sandbox folder
 *                           without editing the config file.  Empty string means "use the
 *                           value from jenkins_job_config.json" (production default).
 * @param configRepoPrefix   Workspace-relative path to the config repo root (e.g.
 *                           "config-repo").  Passed to the Job DSL script so that all
 *                           readFileFromWorkspace calls are correctly prefixed.
 * @param pipelinesRepoUrl   (optional) Override for the ci-adoptium-pipelines repo URL.
 *                           When non-empty, takes precedence over repository.url in
 *                           adoptium_pipeline_config.json — used by the development seed
 *                           job to bake a fork URL into generated jobs.
 * @param pipelinesRepoBranch (optional) Override for the ci-adoptium-pipelines branch.
 *                           When non-empty, takes precedence over repository.branch in
 *                           adoptium_pipeline_config.json.
 */
void generateJobs(String configRepoUrl, String configRepoBranch, String pipelineCommitSha, String pipelineBaseFolder = '', String configRepoPrefix = 'config-repo', String pipelinesRepoUrl = '', String pipelinesRepoBranch = '') {
    String vendorScriptsDir  = configRepoPrefix ? "${configRepoPrefix}/vendor-scripts"   : 'vendor-scripts'
    String triggerConfigFile = configRepoPrefix ? "${configRepoPrefix}/trigger_config.json" : 'trigger_config.json'
    _runSeedDsl(
        configRepoUrl:        configRepoUrl,
        configRepoBranch:     configRepoBranch,
        pipelineCommitSha:    pipelineCommitSha,
        pipelineBaseFolder:   pipelineBaseFolder,
        pipelinesDir:         'pipelines',
        configRepoPrefix:     configRepoPrefix,
        vendorScriptsDir:     vendorScriptsDir,
        triggerConfigFile:    triggerConfigFile,
        pipelinesRepoUrl:     pipelinesRepoUrl,
        pipelinesRepoBranch:  pipelinesRepoBranch,
    )
}

/**
 * Re-seed jobs from within a trigger job workspace, scoped to a single deployment.
 *
 * Called by Jenkinsfile.trigger before firing any launch job to ensure every
 * launch job's parameter definitions match the config repo — correcting any
 * admin drift (e.g. a default value manually changed in the Jenkins UI).
 *
 * Only the named deployment is regenerated (via DEPLOYMENT_FILTER in the seed DSL)
 * to prevent other deployments from being created or deleted mid-trigger.
 *
 * Workspace layout (Jenkinsfile.trigger):
 *   <workspace>/
 *     ci/jenkins/job-dsl/             — pipeline repo at root (checkout scm)
 *     scripts/stages/
 *     config-repo/                    — config repo checkout
 *       adoptium_pipeline_config.json
 *       jenkins_job_config.json
 *       vendor-scripts/
 *       trigger_config.json           — optional
 *
 * @param configRepoUrl      Vendor config repo URL — baked into generated jobs.
 * @param configRepoBranch   Vendor config repo branch — baked into generated jobs.
 * @param pipelineCommitSha  SHA of the ci-adoptium-pipelines checkout.
 * @param pipelineBaseFolder Jenkins root folder (PIPELINE_BASE_FOLDER param, may be empty
 *                           for Jenkins root). Same semantics as generateJobs().
 * @param deploymentName     Deployment name (DEPLOYMENT_NAME param) — passed as
 *                           DEPLOYMENT_FILTER so only this deployment is reseeded.
 * @param pipelinesRepoUrl   (optional) ci-adoptium-pipelines repo URL baked into the
 *                           trigger job. Must be forwarded so the reseed regenerates
 *                           launch jobs with the same pipelines repo, not the config-file value.
 * @param pipelinesRepoBranch (optional) ci-adoptium-pipelines branch, as above.
 */
void reseedForTrigger(String configRepoUrl, String configRepoBranch, String pipelineCommitSha,
                      String pipelineBaseFolder, String deploymentName,
                      String pipelinesRepoUrl = '', String pipelinesRepoBranch = '') {
    _runSeedDsl(
        configRepoUrl:       configRepoUrl,
        configRepoBranch:    configRepoBranch,
        pipelineCommitSha:   pipelineCommitSha,
        pipelineBaseFolder:  pipelineBaseFolder,
        deploymentFilter:    deploymentName,
        pipelinesDir:        '',
        configRepoPrefix:    'config-repo',
        vendorScriptsDir:    'config-repo/vendor-scripts',
        triggerConfigFile:   'config-repo/trigger_config.json',
        pipelinesRepoUrl:    pipelinesRepoUrl,
        pipelinesRepoBranch: pipelinesRepoBranch,
    )
}

/**
 * Internal implementation shared by generateJobs() and reseedForTrigger().
 * All paths are relative to the calling job's workspace root.
 */
private void _runSeedDsl(Map args) {
    String pipelinesDir       = args.pipelinesDir       ?: ''
    String configRepoPrefix   = args.configRepoPrefix   ?: ''
    String vendorScriptsDir   = args.vendorScriptsDir   ?: 'vendor-scripts'
    String triggerConfigFile  = args.triggerConfigFile  ?: 'trigger_config.json'
    String pipelineBaseFolder = args.pipelineBaseFolder ?: ''
    String deploymentFilter   = args.deploymentFilter   ?: ''

    String psPath    = pipelinesDir ? "${pipelinesDir}/ci/jenkins/lib/PipelineStages.groovy"
                                    : 'ci/jenkins/lib/PipelineStages.groovy'
    String runnerPath = pipelinesDir ? "${pipelinesDir}/scripts/lib/python-runner.sh"
                                     : 'scripts/lib/python-runner.sh'
    String pyPath    = pipelinesDir ? "${pipelinesDir}/scripts/lib/collect-stage-params.py"
                                    : 'scripts/lib/collect-stage-params.py'
    String stagesDir = pipelinesDir ? "${pipelinesDir}/scripts/stages" : 'scripts/stages'
    String dslDir    = pipelinesDir ? "${pipelinesDir}/ci/jenkins/job-dsl" : 'ci/jenkins/job-dsl'

    def ps = load(psPath)
    String collectCmd = "${runnerPath} '${pyPath}'" +
        " --default-stages-dir '${stagesDir}'" +
        " --orchestrated-stages ${ps.orchestratedStages()}" +
        ' --output collated-stage-params.json'
    if (fileExists(vendorScriptsDir)) {
        collectCmd += " --vendor-scripts-dir '${vendorScriptsDir}'"
    }
    sh(script: collectCmd)

    String collatedJson = readFile('collated-stage-params.json')
    if (!collatedJson?.trim()) {
        error('collect-stage-params.py produced empty output — ensure the pipeline repo checkout succeeded.')
    }

    String triggerConfigJson = fileExists(triggerConfigFile) ? readFile(triggerConfigFile) : ''

    jobDsl(
        targets:              "${dslDir}/seed/seed_job_dsl.groovy",
        removedJobAction:     'DELETE',
        removedViewAction:    'DELETE',
        additionalClasspath:  dslDir,
        additionalParameters: [
            CONFIG_REPO_URL:       args.configRepoUrl,
            CONFIG_REPO_BRANCH:    args.configRepoBranch,
            COLLATED_PARAMS_JSON:  collatedJson,
            PIPELINE_COMMIT_SHA:   args.pipelineCommitSha,
            TRIGGER_CONFIG_JSON:   triggerConfigJson,
            CONFIG_REPO_PREFIX:    configRepoPrefix,
            PIPELINE_BASE_FOLDER:  pipelineBaseFolder,
            DEPLOYMENT_FILTER:     deploymentFilter,
            PIPELINES_REPO_URL:    args.pipelinesRepoUrl    ?: '',
            PIPELINES_REPO_BRANCH: args.pipelinesRepoBranch ?: '',
        ]
    )
}

return this
