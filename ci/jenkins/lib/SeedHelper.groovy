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

import groovy.json.JsonSlurper

/**
 * Run the Python collator and invoke the Job DSL script to create/update all
 * launch and trigger jobs for every deployment declared in jenkins_job_config.json.
 *
 * Workspace layout (Jenkinsfile.seed):
 *   <workspace>/
 *     adoptium_pipeline_config.json
 *     jenkins_job_config.json
 *     vendor-scripts/
 *     trigger_config.json             — optional
 *     pipelines/                      — ci-adoptium-pipelines checkout
 *       scripts/stages/
 *       ci/jenkins/job-dsl/
 *
 * @param configRepoUrl      Vendor config repo URL — baked into generated jobs.
 * @param configRepoBranch   Vendor config repo branch — baked into generated jobs.
 * @param pipelineCommitSha  SHA of the ci-adoptium-pipelines checkout.
 */
void generateJobs(String configRepoUrl, String configRepoBranch, String pipelineCommitSha) {
    _runSeedDsl(
        configRepoUrl:     configRepoUrl,
        configRepoBranch:  configRepoBranch,
        pipelineCommitSha: pipelineCommitSha,
        pipelinesDir:      'pipelines',
        configRepoPrefix:  '',
        vendorScriptsDir:  'vendor-scripts',
        triggerConfigFile: 'trigger_config.json',
    )
}

/**
 * Re-seed all jobs from within a trigger job workspace.
 *
 * Called by Jenkinsfile.trigger before firing any launch job to ensure every
 * launch job's parameter definitions match the config repo — correcting any
 * admin drift (e.g. a default value manually changed in the Jenkins UI).
 *
 * Identical reconciliation semantics to generateJobs() — the config repo is
 * always the source of truth, so removed versions delete their jobs just as
 * a scheduled seed run would.
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
 */
void reseedForTrigger(String configRepoUrl, String configRepoBranch, String pipelineCommitSha) {
    _runSeedDsl(
        configRepoUrl:     configRepoUrl,
        configRepoBranch:  configRepoBranch,
        pipelineCommitSha: pipelineCommitSha,
        pipelinesDir:      '',
        configRepoPrefix:  'config-repo',
        vendorScriptsDir:  'config-repo/vendor-scripts',
        triggerConfigFile: 'config-repo/trigger_config.json',
    )
}

/**
 * Internal implementation shared by generateJobs() and reseedForTrigger().
 * All paths are relative to the calling job's workspace root.
 */
private void _runSeedDsl(Map args) {
    String pipelinesDir      = args.pipelinesDir      ?: ''
    String configRepoPrefix  = args.configRepoPrefix  ?: ''
    String vendorScriptsDir  = args.vendorScriptsDir  ?: 'vendor-scripts'
    String triggerConfigFile = args.triggerConfigFile ?: 'trigger_config.json'

    String psPath    = pipelinesDir ? "${pipelinesDir}/ci/jenkins/lib/PipelineStages.groovy"
                                    : 'ci/jenkins/lib/PipelineStages.groovy'
    String pyPath    = pipelinesDir ? "${pipelinesDir}/scripts/lib/collect-stage-params.py"
                                    : 'scripts/lib/collect-stage-params.py'
    String stagesDir = pipelinesDir ? "${pipelinesDir}/scripts/stages" : 'scripts/stages'
    String dslDir    = pipelinesDir ? "${pipelinesDir}/ci/jenkins/job-dsl" : 'ci/jenkins/job-dsl'

    def ps = load(psPath)
    String collectCmd = "python3 '${pyPath}'" +
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
            CONFIG_REPO_URL:      args.configRepoUrl,
            CONFIG_REPO_BRANCH:   args.configRepoBranch,
            COLLATED_PARAMS_JSON: collatedJson,
            PIPELINE_COMMIT_SHA:  args.pipelineCommitSha,
            TRIGGER_CONFIG_JSON:  triggerConfigJson,
            CONFIG_REPO_PREFIX:   configRepoPrefix,
        ]
    )
}

return this
