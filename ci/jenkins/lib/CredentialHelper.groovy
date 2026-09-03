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
 *
 * ALL_STAGES wildcard:
 *   A credential listed under the special key "ALL_STAGES" in stageCredentials
 *   is injected into every stage, regardless of stageId.  This is the intended
 *   mechanism for GITHUB_TOKEN — a PAT needed by every stage that performs a
 *   git clone over HTTPS (see docs/GITHUB_AUTH_GIT_OPERATIONS.md).
 */

import groovy.json.JsonSlurper

// ---------------------------------------------------------------------------
// @NonCPS helpers — JSON parsing must never happen in a CPS-suspended frame.
//
// JsonSlurper returns groovy.json.internal.LazyMap, which is NOT Java-serializable.
// The Jenkins CPS engine serializes the full program state to disk between pipeline
// steps (for resume/restart support).  If a LazyMap is alive as a local variable
// at any suspension point — including the body() call inside withStageCredentials —
// the serialization fails with NotSerializableException and the build crashes.
//
// The fix: extract every JsonSlurper call into a @NonCPS method.  @NonCPS methods
// are not managed by the CPS engine, so their stack frames are never serialized.
// They must be non-blocking, non-CPS, and must return only serializable types
// (plain List<String>, plain Map<String,String>) before the CPS caller resumes.
// ---------------------------------------------------------------------------

/**
 * Parse CONFIG_STAGE_CREDENTIALS and return the credential names for stageId.
 * Returns an empty list when no credentials are mapped for the stage.
 * @NonCPS — must not call any CPS pipeline steps.
 */
@NonCPS
List<String> _credentialNamesForStage(String stageId, String stageCredsJson) {
    Map parsed = new JsonSlurper().parseText(stageCredsJson ?: '{}')
    // ALL_STAGES entries are injected into every stage regardless of stageId.
    List allStages = parsed['ALL_STAGES'] ?: []
    List stageOnly = parsed[stageId]      ?: []
    // Merge, preserving order (ALL_STAGES first), deduplicating by name.
    LinkedHashSet<String> merged = new LinkedHashSet<>()
    (allStages + stageOnly).each { merged.add(it.toString()) }
    // Return a plain ArrayList<String> — LazyMap/LazyList are not serializable.
    return new ArrayList<>(merged)
}

/**
 * Parse CONFIG_CREDENTIAL_DEFINITIONS and return a plain Map<String, Map<String,String>>
 * containing only the entries needed for the given credential names.
 * @NonCPS — must not call any CPS pipeline steps.
 */
@NonCPS
Map<String, Map<String, String>> _credentialDefs(List<String> names, String credDefsJson) {
    Map parsed = new JsonSlurper().parseText(credDefsJson ?: '{}')
    Map<String, Map<String, String>> result = [:]
    names.each { String name ->
        Map raw = parsed[name]
        if (raw != null) {
            // Flatten LazyMap into a plain LinkedHashMap with String values only.
            result[name] = raw.collectEntries { k, v -> [(k.toString()): v?.toString() ?: ''] }
        }
    }
    return result
}

// ---------------------------------------------------------------------------
// CPS public API
// ---------------------------------------------------------------------------

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
    // All JSON parsing delegated to @NonCPS helpers — no LazyMap ever enters
    // this CPS method's stack frame, so program-state serialization cannot fail.
    List<String> names = _credentialNamesForStage(stageId, env.CONFIG_STAGE_CREDENTIALS)

    if (!names) {
        body()
        return
    }

    Map<String, Map<String, String>> credDefs = _credentialDefs(names, env.CONFIG_CREDENTIAL_DEFINITIONS)

    List bindings    = []
    List envVarNames = []

    names.each { String name ->
        Map<String, String> cred = credDefs[name]
        if (!cred) {
            error("CredentialHelper: credential '${name}' referenced by stage '${stageId}' " +
                  "is not defined in jenkins_credential_config.json")
        }
        switch (cred.type) {
            case 'string':
                bindings    << string(credentialsId: cred.credentialId, variable: name)
                envVarNames << name
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

    echo "🔑 Injecting ${names.size()} credential(s) for stage '${stageId}': ${names.join(', ')}" +
         ((_credentialNamesForStage('ALL_STAGES', env.CONFIG_STAGE_CREDENTIALS) ? ' (includes ALL_STAGES)' : ''))

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
