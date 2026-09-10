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
 * TriggerScriptRunner — vendor-overridable trigger script resolution and execution.
 *
 * Loaded with:
 *   def triggerRunner = load('ci/jenkins/lib/TriggerScriptRunner.groovy')
 *
 * Mirrors StageScriptRunner's resolution pattern for the triggers layer.
 *
 * Resolution order for run(triggerType):
 *   1. config-repo/vendor-triggers/<type>.sh   ← vendor override or addition
 *   2. scripts/triggers/<type>.sh              ← default (core pipeline repo)
 *   3. not found → error (misconfiguration — never a silent no-op)
 *
 * Interface contract (mirrors stage scripts):
 *   Input:  trigger-version-config.json written to WORKSPACE before script runs
 *   Output: trigger-result.json written by the script to TARGET_DIR,
 *           read back and returned as a parsed Map
 *
 * Environment variables set for the script:
 *   WORKSPACE                   — current Jenkins workspace
 *   TARGET_DIR                  — <WORKSPACE>/trigger-<type>-<version>-output
 *   TRIGGER_VERSION_CONFIG_FILE — <WORKSPACE>/trigger-version-config-<version>.json
 *   PIPELINE_ROOT               — path to ci-adoptium-pipelines checkout
 *   GITHUB_TOKEN                — injected via withCredentials if configured
 *
 * Public API:
 *   Map run(String triggerType, Map versionConfig)
 *     Writes trigger-version-config.json, resolves and runs the trigger script,
 *     reads back trigger-result.json and returns it as a Map.
 *     Throws on any resolution or execution failure.
 *
 *   boolean scriptExists(String triggerType)
 *     Returns true if a vendor or default script exists for the given type.
 */

import groovy.json.JsonOutput

// GitHub token credential ID — injected by Jenkinsfile.trigger after load().
// When set, GITHUB_TOKEN is injected into the script environment via withCredentials.
def githubTokenCredentialId = null

void setGithubTokenCredentialId(String credId) {
    githubTokenCredentialId = credId
}

// ---------------------------------------------------------------------------
// scriptExists
// ---------------------------------------------------------------------------

/**
 * Return true if a vendor or default trigger script exists for triggerType.
 */
boolean scriptExists(String triggerType) {
    return _resolve(triggerType) != null
}

// ---------------------------------------------------------------------------
// run
// ---------------------------------------------------------------------------

/**
 * Resolve and run a trigger script for the given type and version config.
 *
 * @param triggerType   Trigger type stem, e.g. 'detect-ga-tag'
 * @param versionConfig Map of version-specific config from trigger_config.json
 * @return              Parsed trigger-result.json Map
 */
Map run(String triggerType, Map versionConfig) {
    String found = _resolve(triggerType)

    if (!found) {
        error(
            "No trigger script found for type '${triggerType}'.\n" +
            "Expected one of:\n" +
            "  config-repo/vendor-triggers/${triggerType}.sh\n" +
            "  scripts/triggers/${triggerType}.sh\n" +
            "Add the script or remove this trigger type from the deployment's trigger list."
        )
    }

    echo "▶ Running trigger script: ${found} (type: '${triggerType}')"

    String version      = versionConfig.version as String
    String targetDir    = "${env.WORKSPACE}/trigger-${triggerType}-${version}-output"
    String configFile   = "${env.WORKSPACE}/trigger-version-config-${version}.json"
    String pipelineRoot = env.WORKSPACE

    // Write trigger-version-config.json for the script to read
    writeJSON file: "trigger-version-config-${version}.json", json: versionConfig, pretty: 2
    echo "✓ Wrote trigger-version-config-${version}.json for version '${version}'"

    sh "mkdir -p '${targetDir}'"

    withEnv([
        "TARGET_DIR=${targetDir}",
        "TRIGGER_VERSION_CONFIG_FILE=${configFile}",
        "PIPELINE_ROOT=${pipelineRoot}",
    ]) {
        _withGithubToken {
            int exitCode = sh(script: "bash '${found}'", returnStatus: true)
            if (exitCode != 0) {
                error("Trigger script '${found}' exited with code ${exitCode}")
            }
        }
    }

    String resultFile = "${targetDir}/trigger-result.json"
    if (!fileExists(resultFile)) {
        error("Trigger script '${found}' did not write trigger-result.json to ${targetDir}")
    }

    Map result = readJSON(file: resultFile)
    echo "✓ trigger-result.json: ${JsonOutput.toJson(result)}"
    return result
}

// ---------------------------------------------------------------------------
// Private helpers
// ---------------------------------------------------------------------------

/**
 * Resolve the trigger script path for the given type.
 * Returns the path string if found, null otherwise.
 * Vendor scripts take priority over defaults.
 */
private String _resolve(String triggerType) {
    List candidates = [
        "config-repo/vendor-triggers/${triggerType}.sh",
        "scripts/triggers/${triggerType}.sh",
    ]
    for (String path in candidates) {
        if (fileExists(path)) {
            return path
        }
    }
    return null
}

/**
 * Wrap body in a withCredentials block injecting GITHUB_TOKEN when a
 * credential ID has been configured, otherwise call body directly.
 */
private void _withGithubToken(Closure body) {
    if (githubTokenCredentialId?.trim()) {
        withCredentials([string(credentialsId: githubTokenCredentialId, variable: 'GITHUB_TOKEN')]) {
            body()
        }
    } else {
        body()
    }
}

return this
