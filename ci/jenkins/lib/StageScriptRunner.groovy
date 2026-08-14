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
 * StageScriptRunner — vendor-overridable stage script resolution and execution.
 *
 * Loaded with:
 *   def stageRunner = load('ci/jenkins/lib/StageScriptRunner.groovy')
 *
 * This file is a CpsScript. All pipeline steps (echo, sh, env, load, fileExists,
 * etc.) are called directly — no 'steps.' prefix, no init(this) delegation.
 *
 * Resolution order for run(stem):
 *   1. config-repo/vendor-scripts/<stem>.sh     ← vendor override (shell)
 *   2. config-repo/vendor-scripts/<stem>.groovy ← vendor override (Groovy)
 *   3. config-repo/vendor-scripts/<stem>.py     ← vendor override (Python)
 *   4. scripts/stages/<stem>.sh                 ← default (shell)
 *   5. scripts/stages/<stem>.groovy             ← default (Groovy)
 *   6. scripts/stages/<stem>.py                 ← default (Python)
 *   7. no-op → returns 0
 *
 * .groovy scripts receive the config Map as their call() argument.
 * .sh and .py scripts receive config via environment variables set by initializeStage().
 *
 * Container dispatch:
 *   When BUILD_CONTAINER_ID is set (by NodeAgentHelper.withBuildAgent), .sh
 *   and .py scripts are dispatched into the running container via
 *   `docker exec` or `podman exec` with -w set to BUILD_CONTAINER_WORKSPACE.
 *   .groovy scripts always run on the host JVM and cannot be dispatched
 *   automatically — a warning is logged.
 *
 * Public API:
 *   run(scriptStem, config=null) → int exit code (0 = success)
 */

/**
 * Build the -e flag arguments for `docker/podman exec` containing all
 * pipeline environment variables the stage scripts depend on.
 *
 * Why we enumerate explicitly (not printenv or env.getEnvironment()):
 *   - env.getEnvironment() is blocked by the Jenkins script security sandbox.
 *   - printenv dumps the host shell environment, which does NOT include vars
 *     set via Groovy env.X = ... or withEnv() — those live in the CPS engine,
 *     not in the shell process.
 *   - Explicit enumeration avoids accidentally forwarding Jenkins credential
 *     secrets (e.g. SSH keys, API tokens) into the container.
 *
 * Why we set HOME, PATH, GIT_ASKPASS etc. explicitly:
 *   `docker/podman exec` starts with a minimal environment — not a login shell.
 *   No profile scripts are sourced, so the image's PATH additions and HOME
 *   setting are lost.  Specifically:
 *     - HOME is unset or '/': git uses HOME for temp files; writing to '/' as
 *       the container user fails and git reports "Out of memory".
 *     - /usr/local/libexec/git-core is not on PATH: git cannot find its own
 *       git-remote-https transport helper and fails with "Out of memory".
 *     - GIT_ASKPASS / SSH_ASKPASS point to Jenkins agent binaries that don't
 *       exist inside the container; git tries to exec them and fails.
 */
String containerEnvFlags() {
    // Derived/resolved CONFIG_* vars set by ConfigHelper.generatePipelineConfig().
    // Raw stage param values (SIGN_ARTIFACTS, RUN_TESTS, etc.) are NOT listed here —
    // they arrive automatically via the STAGE_PARAM_NAMES dynamic block below.
    List vars = [
        'WORKSPACE',
        'CONFIG_FILE',
        'TARGET_DIR',
        'INPUT_ARTIFACTS_DIR',
        'BUILD_NUMBER',
        'BUILD_UID',
        'GROUP_UID',
        'JOB_NAME',
        'BUILD_URL',
        // Fixed job-level params — not in collated stage params so not in STAGE_PARAM_NAMES
        'RELEASE_TYPE',
        'CLEAN_WORKSPACE_AFTER_STAGE',
        // Derived platform identity — from pipeline-config.json buildConfig
        'CONFIG_VARIANT',
        'CONFIG_TARGET_OS',
        'CONFIG_ARCHITECTURE',
        'CONFIG_JAVA_TO_BUILD',
        'CONFIG_NODE_LABEL',
        // Config-file baseline args — merged with EXTRA_BUILD_ARGS/EXTRA_CONFIGURE_ARGS by stage scripts
        'CONFIG_BUILD_ARGS',
        'CONFIG_CONFIGURE_ARGS',
        // Resolved refs — may differ from raw stage params when config repo defaults are used
        'CONFIG_BUILD_REF',
        'CONFIG_BUILD_REPO_URL',
        'CONFIG_AQA_REF',
        // Docker/Podman — from platform config, no stage param equivalent
        'CONFIG_DOCKER_IMAGE',
        'CONFIG_DOCKER_REGISTRY',
        'CONFIG_DOCKER_CREDENTIAL',
        'CONFIG_DOCKER_ARGS',
        'CONFIG_PODMAN_ARGS',
    ]

    // Also forward all collated stage params (names baked into STAGE_PARAM_NAMES
    // at job-generation time by the Job DSL). This ensures any vendor-specific
    // parameter (e.g. OPENJ9_REPO) is automatically available inside the container
    // without needing manual additions to the list above.
    List stageParamNames = (env.getProperty('STAGE_PARAM_NAMES') ?: '')
        .split(',')
        .collect { String name -> name.trim() }
        .findAll { String name -> name }
    vars = vars + stageParamNames

    List flags = vars
        .unique()
        .findAll { String v -> env.getProperty(v) != null && env.getProperty(v) != '' }
        .collect { String v -> "-e '${v}=${env.getProperty(v)}'" }

    // Clear Jenkins agent-side askpass binaries that don't exist in the container.
    flags << "-e 'GIT_ASKPASS='"
    flags << "-e 'SSH_ASKPASS='"
    flags << "-e 'GIT_TERMINAL_PROMPT=0'"

    // Ensure the image's tools directory is on PATH.  The build image installs
    // git and its helpers under /usr/local; git-remote-https lives in
    // /usr/local/libexec/git-core which is not on the default exec PATH.
    flags << "-e 'PATH=/usr/local/libexec/git-core:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'"

    // Set HOME to the Jenkins agent's home directory.  The host home is
    // bind-mounted into the container at the same path (by NodeAgentHelper),
    // so it is writable.  Without a valid HOME, git's temp-file allocation fails.
    String jenkinsHome = env.getProperty('HOME') ?: '/home/jenkins'
    flags << "-e 'HOME=${jenkinsHome}'"

    return flags.join(' ')
}

/**
 * Resolve and execute a stage script, returning an exit code.
 *
 * @param scriptStem  Script stem e.g. '13-smoke-tests'
 * @param config      Pipeline config map — forwarded to .groovy scripts as the call() argument.
 *                    .sh and .py scripts receive config via environment variables.
 * @return int exit code — 0 = success, non-zero = failure.
 */
int run(String scriptStem, Map config = null) {
    final int EXIT_SUCCESS = 0
    List candidates = [
        [path: "config-repo/vendor-scripts/${scriptStem}.sh",     type: 'sh'],
        [path: "config-repo/vendor-scripts/${scriptStem}.groovy", type: 'groovy'],
        [path: "config-repo/vendor-scripts/${scriptStem}.py",     type: 'py'],
        [path: "scripts/stages/${scriptStem}.sh",                 type: 'sh'],
        [path: "scripts/stages/${scriptStem}.groovy",             type: 'groovy'],
        [path: "scripts/stages/${scriptStem}.py",                 type: 'py'],
    ]

    Map found = candidates.find { Map c -> fileExists(c.path) }

    if (!found) {
        echo "ℹ️  No script found for '${scriptStem}' — stage is a no-op"
        return EXIT_SUCCESS
    }

    echo "▶ Running ${found.type.toUpperCase()} stage script: ${found.path}"

    String containerId = env.BUILD_CONTAINER_ID?.trim()
    String containerWs = env.BUILD_CONTAINER_WORKSPACE?.trim()
    String runtime     = env.BUILD_CONTAINER_RUNTIME?.trim() ?: 'docker'

    // Ensure workspace and TARGET_DIR exist on the host.  initializeStage()
    // calls cleanWs() which wipes and recreates the workspace after the
    // container starts; these mkdir calls run as the host Jenkins agent user
    // so the container (which owns those paths via the bind-mount) can enter them.
    if (containerId) {
        sh "mkdir -p '${containerWs}'"
    }
    if (env.TARGET_DIR) {
        sh "mkdir -p '${env.TARGET_DIR}'"
    }

    switch (found.type) {
        case 'sh':
            if (containerId) {
                String eFlags = containerEnvFlags()
                return sh(script: "${runtime} exec ${eFlags} -w '${containerWs}' '${containerId}' bash '${found.path}'", returnStatus: true)
            }
            return sh(script: "bash ${found.path}", returnStatus: true)

        case 'groovy':
            // Groovy scripts run on the host JVM (Jenkins CPS engine) and cannot
            // be dispatched into the container automatically.  Any sh() calls
            // inside such a script will run on the host, not in the container.
            if (containerId) {
                echo "⚠️  WARNING: Groovy stage script '${found.path}' is running on the host JVM " +
                     "while the build agent is a container (BUILD_CONTAINER_ID=${containerId}). " +
                     'Options: ' +
                     '(1) Convert to a .sh or .py script — these are dispatched into the container automatically. ' +
                     "(2) Issue '${runtime} exec' calls directly using BUILD_CONTAINER_ID and BUILD_CONTAINER_WORKSPACE."
            }
            def script = load(found.path)
            return script(config) ?: EXIT_SUCCESS

        case 'py':
            // python-runner.sh resolves python3/python and execs the script.
            if (containerId) {
                String eFlags = containerEnvFlags()
                return sh(script: "${runtime} exec ${eFlags} -w '${containerWs}' '${containerId}' scripts/lib/python-runner.sh '${found.path}'", returnStatus: true)
            }
            return sh(script: "scripts/lib/python-runner.sh '${found.path}'", returnStatus: true)
    }
    return EXIT_SUCCESS
}

return this

// Made with Bob
