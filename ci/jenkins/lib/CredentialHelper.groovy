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
 *   string           → env var name = cred.envVar field (default: credential key name)
 *                      The optional 'envVar' field allows the same well-known env var
 *                      name (e.g. GITHUB_TOKEN) to be injected from different underlying
 *                      Jenkins credentials for different stages.
 *   usernamePassword → usernameEnvVar / passwordEnvVar (defaults: <NAME>_USER / <NAME>_PASS)
 *   sshUserPrivateKey→ keyFileEnvVar  (default: <NAME>_KEYFILE)
 *   file             → fileEnvVar     (default: <NAME>_FILE)
 *
 * ALL_STAGES wildcard:
 *   A credential listed under the special key "ALL_STAGES" in stageCredentials
 *   is injected into every stage, regardless of stageId.  This is the intended
 *   mechanism for GITHUB_TOKEN — a PAT needed by every stage that performs a
 *   git clone over HTTPS (see docs/GITHUB_AUTH_GIT_OPERATIONS.md).
 *
 * envVar precedence for string credentials:
 *   When a stage-specific credential and an ALL_STAGES credential both resolve to
 *   the same envVar name, the stage-specific one takes precedence.  The ALL_STAGES
 *   entry is silently suppressed for that stage so withCredentials() never sees two
 *   bindings for the same variable name (which would cause a Jenkins runtime error).
 *   Two stage-specific (non-ALL_STAGES) credentials sharing an envVar in the same
 *   stage are rejected at config-load time by load-jenkins-credential-config.py.
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
    // ALL_STAGES entries whose envVar is overridden by a stage-specific entry are
    // removed in _buildBindings(), not here — we still need both in the list so
    // _buildBindings() can compare them.
    LinkedHashSet<String> merged = new LinkedHashSet<>()
    (allStages + stageOnly).each { merged.add(it.toString()) }
    // Return a plain ArrayList<String> — LazyMap/LazyList are not serializable.
    return new ArrayList<>(merged)
}

/**
 * Resolve the effective env var name for a string credential.
 * Uses the explicit 'envVar' field if present, otherwise falls back to the
 * credential key name.
 * @NonCPS — must not call any CPS pipeline steps.
 */
@NonCPS
String _resolveEnvVar(String name, Map<String, String> cred) {
    String ev = cred.get('envVar')
    return (ev != null && !ev.isEmpty()) ? ev : name
}

/**
 * Build the withCredentials() bindings list and the flat list of injected env var
 * names, applying ALL_STAGES suppression for string credentials whose envVar is
 * claimed by a stage-specific entry.
 *
 * Returns a plain Map with two keys:
 *   bindings    → List of withCredentials binding objects
 *   envVarNames → List<String> of all env var names that will be injected
 *
 * @NonCPS — must not call any CPS pipeline steps.
 */
@NonCPS
Map _buildBindings(String stageId, List<String> names,
                   Map<String, Map<String, String>> credDefs,
                   String stageCredsJson) {
    // Determine which credential names are stage-specific (not from ALL_STAGES).
    Map parsed         = new JsonSlurper().parseText(stageCredsJson ?: '{}')
    Set allStagesNames = new HashSet<>(parsed['ALL_STAGES']?.collect { it.toString() } ?: [])
    Set stageOnlyNames = new HashSet<>(parsed[stageId]?.collect    { it.toString() } ?: [])

    // Collect the envVar names claimed by stage-specific string credentials.
    // These take precedence over any ALL_STAGES entry with the same envVar.
    Set<String> stageClaimedEnvVars = new HashSet<>()
    stageOnlyNames.each { String name ->
        Map<String, String> cred = credDefs[name]
        if (cred && cred.type == 'string') {
            stageClaimedEnvVars.add(_resolveEnvVar(name, cred))
        }
    }

    List bindings    = []
    List envVarNames = []

    names.each { String name ->
        Map<String, String> cred = credDefs[name]
        if (!cred) { return }  // error reported by caller

        boolean isAllStages = allStagesNames.contains(name) && !stageOnlyNames.contains(name)

        switch (cred.type) {
            case 'string':
                String ev = _resolveEnvVar(name, cred)
                // Suppress ALL_STAGES entry when a stage-specific entry claims the same envVar.
                if (isAllStages && stageClaimedEnvVars.contains(ev)) {
                    return  // skip — stage-specific wins
                }
                bindings    << [type: 'string', credentialId: cred.credentialId, variable: ev]
                envVarNames << ev
                break
            case 'usernamePassword':
                String u = cred.usernameEnvVar ?: "${name}_USER"
                String p = cred.passwordEnvVar ?: "${name}_PASS"
                bindings    << [type: 'usernamePassword', credentialId: cred.credentialId,
                                usernameVariable: u, passwordVariable: p]
                envVarNames << u << p
                break
            case 'sshUserPrivateKey':
                String k = cred.keyFileEnvVar ?: "${name}_KEYFILE"
                bindings    << [type: 'sshUserPrivateKey', credentialId: cred.credentialId,
                                keyFileVariable: k]
                envVarNames << k
                break
            case 'file':
                String f = cred.fileEnvVar ?: "${name}_FILE"
                bindings    << [type: 'file', credentialId: cred.credentialId, variable: f]
                envVarNames << f
                break
        }
    }

    // Return plain serializable types — no LazyMap.
    return [bindings: new ArrayList(bindings), envVarNames: new ArrayList(envVarNames)]
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

    // Validate that every referenced credential is defined.
    names.each { String name ->
        if (!credDefs[name]) {
            error("CredentialHelper: credential '${name}' referenced by stage '${stageId}' " +
                  "is not defined in jenkins_credential_config.json")
        }
    }

    // Build bindings with ALL_STAGES suppression for envVar conflicts.
    // _buildBindings() is @NonCPS so no LazyMap escapes into this CPS frame.
    Map built = _buildBindings(stageId, names, credDefs, env.CONFIG_STAGE_CREDENTIALS)
    List bindings    = built.bindings    as List
    List envVarNames = built.envVarNames as List

    // Convert the plain maps produced by the @NonCPS helper into Jenkins
    // withCredentials() binding objects (these are CPS-safe value types).
    List wcBindings = bindings.collect { Map b ->
        switch (b.type) {
            case 'string':
                return string(credentialsId: b.credentialId, variable: b.variable)
            case 'usernamePassword':
                return usernamePassword(credentialsId: b.credentialId,
                                        usernameVariable: b.usernameVariable,
                                        passwordVariable: b.passwordVariable)
            case 'sshUserPrivateKey':
                return sshUserPrivateKey(credentialsId: b.credentialId,
                                         keyFileVariable: b.keyFileVariable)
            case 'file':
                return file(credentialsId: b.credentialId, variable: b.variable)
            default:
                error("CredentialHelper: unknown credential type '${b.type}' in stage '${stageId}'")
        }
    }

    echo "🔑 Injecting ${wcBindings.size()} credential binding(s) for stage '${stageId}': ${names.join(', ')}" +
         ((_credentialNamesForStage('ALL_STAGES', env.CONFIG_STAGE_CREDENTIALS) ? ' (includes ALL_STAGES)' : ''))

    // Set STAGE_CREDENTIAL_ENV_VARS *before* withCredentials() so containerEnvFlags()
    // — called from within the body closure — can enumerate the var names and pick
    // up the live injected values via env.getProperty().
    env.STAGE_CREDENTIAL_ENV_VARS = envVarNames.join(',')
    try {
        withCredentials(wcBindings) {
            body()
        }
    } finally {
        // Clear so a subsequent no-credential stage does not inherit stale var names.
        env.STAGE_CREDENTIAL_ENV_VARS = ''
    }
}

return this
