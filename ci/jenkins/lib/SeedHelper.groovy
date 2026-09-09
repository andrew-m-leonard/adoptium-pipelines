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
 * SeedHelper.groovy — loaded by Jenkinsfile.seed after the pipelines repo checkout.
 *
 * Encapsulates the collation and Job DSL invocation so that Jenkinsfile.seed
 * stays minimal and the logic lives alongside the rest of the pipeline library
 * in ci/jenkins/lib/.
 *
 * Usage (from Jenkinsfile.seed Generate jobs stage):
 *   def seedHelper = load('pipelines/ci/jenkins/lib/SeedHelper.groovy')
 *   seedHelper.generateJobs(params.CONFIG_REPO_URL, params.CONFIG_REPO_BRANCH, env.PIPELINES_COMMIT_SHA)
 *
 * Reads pipelineBaseFolder and deployments[] from jenkins_job_config.json.
 * Generates all deployments in a single pass — no per-deployment parameter needed.
 */

import groovy.json.JsonSlurper

/**
 * Run the Python collator and invoke the Job DSL script to create/update all
 * launch and trigger jobs for every deployment declared in jenkins_job_config.json.
 *
 * @param configRepoUrl      Vendor config repo URL — baked into generated jobs.
 * @param configRepoBranch   Vendor config repo branch — baked into generated jobs.
 * @param pipelineCommitSha  SHA of the ci-adoptium-pipelines checkout — stamped
 *                           into job descriptions for change detection.
 */
void generateJobs(String configRepoUrl, String configRepoBranch, String pipelineCommitSha) {
    // Run the CI-agnostic Python collator — single source of truth for stage
    // parameter collation shared by seed, launch, and build jobs.
    // vendor-scripts/ lives in the workspace root (config repo SCM checkout).
    // pipelines/ contains the default *.params.json files.
    def ps = load('pipelines/ci/jenkins/lib/PipelineStages.groovy')
    String collectCmd = 'python3 pipelines/scripts/lib/collect-stage-params.py' +
        ' --default-stages-dir pipelines/scripts/stages' +
        " --orchestrated-stages ${ps.orchestratedStages()}" +
        ' --output collated-stage-params.json'
    if (fileExists('vendor-scripts')) {
        collectCmd += ' --vendor-scripts-dir vendor-scripts'
    }
    sh(script: collectCmd)

    String collatedJson = readFile('collated-stage-params.json')
    if (!collatedJson?.trim()) {
        error('collect-stage-params.py produced empty output — ensure the pipeline repo checkout succeeded.')
    }

    // Read trigger_config.json (optional — absent for setups without trigger jobs)
    String triggerConfigJson = ''
    if (fileExists('trigger_config.json')) {
        triggerConfigJson = readFile('trigger_config.json')
    }

    jobDsl(
        targets:             'pipelines/ci/jenkins/job-dsl/seed/seed_job_dsl.groovy',
        removedJobAction:    'DELETE',
        removedViewAction:   'DELETE',
        additionalClasspath: 'pipelines/ci/jenkins/job-dsl',
        additionalParameters: [
            CONFIG_REPO_URL:      configRepoUrl,
            CONFIG_REPO_BRANCH:   configRepoBranch,
            COLLATED_PARAMS_JSON: collatedJson,
            PIPELINE_COMMIT_SHA:  pipelineCommitSha,
            TRIGGER_CONFIG_JSON:  triggerConfigJson,
        ]
    )
}

return this
