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
 * CredentialHelper — per-stage credential injection for vendor stage overrides.
 *
 * Loaded with:
 *   def credentialHelper = load('ci/jenkins/lib/CredentialHelper.groovy')
 *
 * This file is a CpsScript. All pipeline steps (echo, withCredentials, error,
 * env, etc.) are called directly — no 'steps.' prefix.
 *
 * Vendors declare credentials in their config repo's jenkins_credential_config.json.
 * ConfigHelper.generateJenkinsConfig() loads that file and populates two env vars:
 *
 *   CONFIG_CREDENTIAL_DEFINITIONS — JSON map of credential name → definition
 *                                   (type, credentialId, env var name fields)
 *   CONFIG_STAGE_CREDENTIALS      — JSON map of stageId → [credentialName, ...]
 *
 * Public API:
 *   withStageCredentials(stageId, body)
 *     → Called by StageScriptRunner.run() for every stage.  If no credentials
 *       are mapped for stageId, body() is called directly with zero overhead.
 *       Otherwise builds a withCredentials([...]) bindings list and wraps body().
 *
 *       Before entering withCredentials(), sets env.STAGE_CREDENTIAL_ENV_VARS to
 *       the comma-separated list of injected env var *names* (not values) so that
 *       StageScriptRunner.containerEnvFlags() can forward the live injected values
 *       into Docker/Podman containers via -e flags.  Clears the var in a finally
 *       block after the scope exits.
 *
 * Supported credential types (mirrors Jenkins withCredentials binding types):
 *   string           → env var = the credential name itself
 *   usernamePassword → usernameEnvVar / passwordEnvVar (defaults: <NAME>_USER / <NAME>_PASS)
 *   sshUserPrivateKey→ keyFileEnvVar  (default: <NAME>_KEYFILE)
 *   file             → fileEnvVar     (default: <NAME>_FILE)
 */

import groovy.json.JsonSlurper

/**
 * Execute body wrapped in withCredentials() bindings for the given stageId.
 *
 * If no credentials are configured for stageId (or if CONFIG_STAGE_CREDENTIALS
 * is unset/empty), body() is called directly — no withCredentials overhead.
 *
 * STAGE_CREDENTIAL_ENV_VARS lifecycle:
 *   Set  → immediately before withCredentials() so containerEnvFlags() can read
 *           the var names while the withCredentials() scope is active.
 *   Clear → in finally, so a subsequent stage that has no credentials does not
 *           accidentally inherit the previous stage's var names.
 *
 * @param stageId  Stage ID string, e.g. '16-publish'
 * @param body     Closure to execute — typically StageScriptRunner._dispatch()
 */
void withStageCredentials(String stageId, Closure body) {
    Map stageCreds = new JsonSlurper().parseText(env.CONFIG_STAGE_CREDENTIALS ?: '{}')
    List<String> names = stageCreds[stageId] ?: []

    if (!names) {
        body()
        return
    }

    Map credDefs = new JsonSlurper().parseText(env.CONFIG_CREDENTIAL_DEFINITIONS ?: '{}')

    List bindings    = []
    List envVarNames = []

    names.each { String name ->
        Map cred = credDefs[name]
        if (!cred) {
            error("CredentialHelper: credential '${name}' referenced by stage '${stageId}' " +
                  "is not defined in jenkins_credential_config.json")
        }
        switch (cred.type) {
            case 'string':
                bindings     << string(credentialsId: cred.credentialId, variable: name)
                envVarNames  << name
                break
            case 'usernamePassword':
                String u = cred.usernameEnvVar ?: "${name}_USER"
                String p = cred.passwordEnvVar ?: "${name}_PASS"
                bindings    << usernamePassword(credentialsId: cred.credentialId,
                                                usernameVariable: u,
                                                passwordVariable: p)
                envVarNames << u << p
                break
            case 'sshUserPrivateKey':
                String k = cred.keyFileEnvVar ?: "${name}_KEYFILE"
                bindings    << sshUserPrivateKey(credentialsId: cred.credentialId,
                                                 keyFileVariable: k)
                envVarNames << k
                break
            case 'file':
                String f = cred.fileEnvVar ?: "${name}_FILE"
                bindings    << file(credentialsId: cred.credentialId, variable: f)
                envVarNames << f
                break
            default:
                error("CredentialHelper: unknown credential type '${cred.type}' " +
                      "for credential '${name}' in stage '${stageId}'")
        }
    }

    echo "🔑 Injecting ${names.size()} credential(s) for stage '${stageId}': ${names.join(', ')}"

    // Set STAGE_CREDENTIAL_ENV_VARS *before* withCredentials() so containerEnvFlags()
    // — called from within the body closure — can enumerate the var names and pick
    // up the live injected values via env.getProperty().
    env.STAGE_CREDENTIAL_ENV_VARS = envVarNames.join(',')
    try {
        withCredentials(bindings) {
            body()
        }
    } finally {
        // Clear so a subsequent no-credential stage does not inherit stale var names.
        env.STAGE_CREDENTIAL_ENV_VARS = ''
    }
}

return this
