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
 * NodeAgentHelper — container agent lifecycle for build stages.
 *
 * Loaded with:
 *   def nodeAgentHelper = load('ci/jenkins/lib/NodeAgentHelper.groovy')
 *
 * This file is a CpsScript. All pipeline steps (echo, sh, node, etc.)
 * are called directly — no 'steps.' prefix.
 *
 * =========================================================================
 * WHY WE USE A SCRIPTED CONTAINER APPROACH (not docker.image().inside())
 * =========================================================================
 *
 * The standard Jenkins Docker plugin (docker.image().inside()) has two
 * hard-coded behaviours that break builds when the host Jenkins agent user uid
 * does not match the uid baked into the build image.  The Adoptium build images
 * have their jenkins user at uid=1000, which matches many Adoptium nodes — but
 * not all.  Any vendor deploying infrastructure with a different uid (e.g. 1001,
 * 1002, or any site-assigned uid) will hit these failures:
 *
 *   1. It always injects -u <hostUid>:<hostGid> into docker/podman run.
 *      When the host uid differs from the image's jenkins user (uid=1000),
 *      the container process cannot access tools compiled into the image under
 *      /usr/local (owned by uid=1000 mode=750).  The image's /home/jenkins is
 *      also mode=700 owned by uid=1000, so a different uid cannot traverse into
 *      the workspace path at all (crun: chdir permission denied).
 *
 *   2. It always injects -t (allocate pseudo-TTY).  On rootless Podman
 *      there is no daemon — the runtime tries to open a TTY directly on
 *      the calling process and hangs indefinitely when the Jenkins agent
 *      has no controlling terminal.  This flag cannot be suppressed via
 *      dockerArgs because Jenkins appends its own flags after ours.
 *
 * Our solution: call the container runtime directly via sh() so we have
 * full control of every flag.  The container runs as the image's native
 * uid (1000) which has access to all image-installed tools.  Workspace
 * access for uid 1000 is granted by bind-mounting the host's home directory
 * over the image's /home/jenkins (replacing the mode-700 image copy with
 * the host's copy, which is traversable).
 *
 * This approach works identically for Docker and Podman.  The only
 * Podman-specific addition is --userns keep-id, which maps the host uid
 * into the container's user namespace so the workspace bind-mount appears
 * with the correct ownership inside the container.
 *
 * =========================================================================
 *
 * Public API:
 *   withBuildAgent(body)
 *     → Allocates a node by CONFIG_NODE_LABEL and, when CONFIG_DOCKER_IMAGE
 *       is set, runs the body inside that container using the scripted
 *       approach described above.  Falls back to a plain node when no
 *       image is configured.
 *
 *   isPodmanNode()
 *     → Returns true when the container runtime on the current node is
 *       Podman (detected via 'docker --version').  Must be called inside
 *       a node() block.
 *
 * Config env vars (set by ConfigHelper.generatePipelineConfig):
 *   CONFIG_DOCKER_IMAGE      — image to run (e.g. ghcr.io/adoptium/adoptium_build_image:centos7_linux-amd64)
 *   CONFIG_DOCKER_REGISTRY   — registry URL for login (optional)
 *   CONFIG_DOCKER_CREDENTIAL — Jenkins credential ID for registry login (optional)
 *   CONFIG_DOCKER_ARGS       — extra args forwarded to `docker run`
 *   CONFIG_PODMAN_ARGS       — extra args forwarded to `podman run` (overrides CONFIG_DOCKER_ARGS on Podman nodes)
 *                              --userns keep-id and -u are injected automatically — do not add them here.
 *
 * Environment exposed to stage scripts:
 *   BUILD_CONTAINER_ID        — running container ID (set for both Docker and Podman)
 *   BUILD_CONTAINER_RUNTIME   — 'docker' or 'podman'
 *   BUILD_CONTAINER_WORKSPACE — workspace path inside the container
 */

// ─────────────────────────────────────────────────────────────────────────────
// Active-node guard
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Abort the build when no Jenkins agent matching the label expression is online.
 *
 * Jenkins queues builds when all matching agents are *busy* — that is the
 * expected behaviour and we leave it alone.  But when *zero* agents are
 * online for the label (e.g. a cloud template is misconfigured, or all
 * physical nodes are offline), a build would hang indefinitely.  This guard
 * detects that case and aborts with a clear message after timeoutMinutes,
 * giving cloud provisioners (e.g. Kubernetes, EC2) time to spin up a fresh agent.
 *
 * Uses the sandboxed pipeline step nodesByLabel(label) (Pipeline Utility Steps
 * plugin) — no Script Security approval required, works in both scripted and
 * declarative pipelines.
 *
 * Logic:
 *   1. Call nodesByLabel(labelExpr) — returns names of ALL nodes carrying the
 *      label, regardless of whether they are online or busy.
 *   2. If the list is non-empty, at least one agent exists; return immediately
 *      and let Jenkins queue the build normally (busy is fine).
 *   3. If the list is empty (zero agents match the label at all), wait
 *      POLL_INTERVAL_SECONDS and retry.
 *   4. If timeoutMinutes elapses without any agent appearing, throw
 *      FlowInterruptedException(ABORTED) — infrastructure issue, not a code bug.
 *
 * Must be called from a controller-side step context (e.g. inside script {})
 * and NOT from inside an already-allocated node() block.
 *
 * @param labelExpr      Label expression string (same value passed to node()).
 * @param timeoutMinutes How long to wait for at least one matching agent to appear.
 *                       Defaults to CONFIG_ACTIVE_NODE_TIMEOUT env var or 10.
 */
def waitForActiveNode(String labelExpr, Integer timeoutMinutes = null) {
    def timeoutMins = timeoutMinutes
                   ?: (env.CONFIG_ACTIVE_NODE_TIMEOUT ? env.CONFIG_ACTIVE_NODE_TIMEOUT.toInteger() : 10)
    final int POLL_INTERVAL_SECONDS = 30

    echo "Checking for active agents matching label: '${labelExpr}' (timeout: ${timeoutMins} min)"

    def deadline = System.currentTimeMillis() + timeoutMins * 60 * 1000L

    while (true) {
        // nodesByLabel is a sandboxed Pipeline Utility Steps step — no Script Security
        // approval needed.  It returns node names whose label set satisfies labelExpr,
        // online or not.  An empty list means zero agents carry this label at all.
        def matchingNodes = nodesByLabel(label: labelExpr, offline: true)
        def activeCount = matchingNodes.size()

        if (activeCount > 0) {
            echo "✓ Found ${activeCount} agent(s) matching '${labelExpr}' — proceeding."
            return
        }

        def remaining = (deadline - System.currentTimeMillis()) / 1000
        if (remaining <= 0) {
            // Set ABORTED before calling error() — Jenkins preserves a result that is
            // already worse-than-SUCCESS, so the build shows as Aborted rather than Failed.
            // FlowInterruptedException constructors are not sandbox-safe, so this is the
            // correct approach for sandboxed declarative/scripted pipelines.
            def msg = "No agent found for label '${labelExpr}' after ${timeoutMins} minute(s). " +
                      "Ensure at least one agent with this label is online (busy agents are fine — " +
                      "this timeout only fires when zero agents match the label). " +
                      "If using cloud provisioning, verify the cloud template is configured correctly."
            currentBuild.result = 'ABORTED'
            error(msg)
        }

        echo "  No active agent yet for '${labelExpr}'. Waiting ${POLL_INTERVAL_SECONDS}s " +
             "(${remaining.toInteger()}s remaining)..."
        sleep(POLL_INTERVAL_SECONDS)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Runtime detection
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Return true when the container runtime on the current node is Podman.
 *
 * 'docker --version' on a Podman shim prints "podman version X.Y.Z".
 * On real Docker it prints "Docker version X.Y.Z, build ...".
 */
def isPodmanNode() {
    return sh(script: 'docker --version 2>&1 | grep -qi podman', returnStatus: true) == 0
}

/**
 * Return true when the image name has no registry host prefix.
 *
 * Podman requires fully-qualified image names — it will not implicitly
 * prepend "docker.io/" the way Docker does.  A name is unqualified when
 * the part before the first '/' contains no '.' or ':' (host indicators).
 */
def isUnqualifiedImageName(String image) {
    def prefix = image.contains('/') ? image.split('/')[0] : image
    return !prefix.contains('.') && !prefix.contains(':')
}

// ─────────────────────────────────────────────────────────────────────────────
// Scripted container execution (Docker)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Run body with a Docker container started via `docker run` directly.
 *
 * See the module-level comment for the full rationale.  Key points:
 *
 *   - No -u flag: the container runs as the image's native user (uid=1000),
 *     which has access to all image-installed tools under /usr/local.
 *
 *   - Host home bind-mount: the host's $HOME (/home/jenkins, owned by uid=1001)
 *     is mounted over the image's /home/jenkins (uid=1000 mode=700).  This
 *     makes the workspace path traversable because the workspace lives under
 *     /home/jenkins/workspace and uid=1000 can now enter that directory tree.
 *
 *   - Workspace bind-mount: the Jenkins workspace is mounted at the same
 *     absolute path inside the container so stage scripts see identical paths.
 *
 *   - BUILD_CONTAINER_ID / BUILD_CONTAINER_WORKSPACE are set in the environment
 *     so StageScriptRunner can dispatch scripts via `docker exec`.
 *
 * Must be called from within a node() block.
 */
def runInDockerContainer(String image, String extraArgs, Closure body) {
    def ws          = env.WORKSPACE
    def hostHome    = sh(script: 'echo $HOME', returnStdout: true).trim()
    def containerId = ''
    try {
        echo "Pulling image (docker): ${image}"
        sh "docker pull '${image}'"

        echo "Starting Docker container: ${image}"
        containerId = sh(
            script: """docker run -d --rm \\
                         --ulimit nofile=1048576:1048576 \\
                         --pids-limit -1 \\
                         ${extraArgs} \\
                         -v '${hostHome}:${hostHome}:rw' \\
                         -v '${ws}:${ws}:rw' \\
                         -v '${ws}@tmp:${ws}@tmp:rw' \\
                         '${image}' \\
                         sleep infinity""",
            returnStdout: true
        ).trim()
        echo "Container started: ${containerId}"

        withEnv([
            "BUILD_CONTAINER_ID=${containerId}",
            "BUILD_CONTAINER_RUNTIME=docker",
            "BUILD_CONTAINER_WORKSPACE=${ws}",
        ]) {
            body()
        }
    } finally {
        if (containerId) {
            echo "Stopping Docker container: ${containerId}"
            sh(script: "docker stop '${containerId}'", returnStatus: true)
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Scripted container execution (Podman)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Run body with a Podman container started via `podman run` directly.
 *
 * See the module-level comment for the full rationale.  Podman-specific
 * additions on top of the Docker approach:
 *
 *   - --userns keep-id: rootless Podman uses subuid/subgid mappings by
 *     default, which maps the host Jenkins uid (1001) to a high unmapped
 *     uid inside the container's user namespace.  The workspace bind-mount
 *     then appears unowned and crun refuses to enter it.  --userns keep-id
 *     maps the calling process uid (1001) to the same uid inside the
 *     container's user namespace, so bind-mounted paths appear with their
 *     real host ownership.
 *
 *   - Unqualified image names are prefixed with "docker.io/" because Podman
 *     requires fully-qualified names without a configured unqualified-search
 *     registry.
 *
 * Must be called from within a node() block.
 */
def runInPodmanContainer(String image, String extraArgs, Closure body) {
    def ws          = env.WORKSPACE
    def hostHome    = sh(script: 'echo $HOME', returnStdout: true).trim()
    def containerId = ''
    try {
        echo "Pulling image (podman): ${image}"
        sh "podman pull '${image}'"

        echo "Starting Podman container: ${image}"
        containerId = sh(
            script: """podman run -d --rm \\
                         --userns keep-id \\
                         --ulimit nofile=1048576:1048576 \\
                         --pids-limit -1 \\
                         ${extraArgs} \\
                         -v '${hostHome}:${hostHome}:rw,z' \\
                         -v '${ws}:${ws}:rw,z' \\
                         -v '${ws}@tmp:${ws}@tmp:rw,z' \\
                         '${image}' \\
                         sleep infinity""",
            returnStdout: true
        ).trim()
        echo "Container started: ${containerId}"

        withEnv([
            "BUILD_CONTAINER_ID=${containerId}",
            "BUILD_CONTAINER_RUNTIME=podman",
            "BUILD_CONTAINER_WORKSPACE=${ws}",
        ]) {
            body()
        }
    } finally {
        if (containerId) {
            echo "Stopping Podman container: ${containerId}"
            sh(script: "podman stop '${containerId}'", returnStatus: true)
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Public entry point
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Allocate a node and optionally run inside a container.
 *
 * With CONFIG_DOCKER_IMAGE set:
 *   1. Checks that at least one agent matching CONFIG_NODE_LABEL is online
 *      (waitForActiveNode — fails after CONFIG_ACTIVE_NODE_TIMEOUT minutes if
 *      zero agents are online; busy agents are fine and do not trigger this).
 *   2. Allocates a node by CONFIG_NODE_LABEL.
 *   3. Detects the container runtime (Docker or Podman).
 *   4. Performs registry login if CONFIG_DOCKER_REGISTRY + CONFIG_DOCKER_CREDENTIAL are set.
 *   5. Starts the container via runInDockerContainer or runInPodmanContainer.
 *      Both use the scripted approach — see the module-level comment.
 *
 * Without CONFIG_DOCKER_IMAGE:
 *   Checks active agents, then allocates a node by CONFIG_NODE_LABEL and runs body directly.
 */
def withBuildAgent(Closure body) {
    def nodeLabel   = env.CONFIG_NODE_LABEL?.trim() ?: 'worker'
    def image       = env.CONFIG_DOCKER_IMAGE?.trim()

    waitForActiveNode(nodeLabel)
    node(nodeLabel) {
        if (!image) {
            body()
            return
        }

        def registry   = env.CONFIG_DOCKER_REGISTRY?.trim()
        def credential = env.CONFIG_DOCKER_CREDENTIAL?.trim()
        def podman     = isPodmanNode()
        def runtime    = podman ? 'podman' : 'docker'

        // Podman requires fully-qualified image names.
        if (podman && !registry && isUnqualifiedImageName(image)) {
            image = 'docker.io/' + image
            echo "Resolved image to fully-qualified name: ${image}"
        }

        // Use podmanArgs on Podman nodes, dockerArgs on Docker nodes.
        def extraArgs = podman
            ? (env.CONFIG_PODMAN_ARGS?.trim() ?: env.CONFIG_DOCKER_ARGS?.trim() ?: '')
            : (env.CONFIG_DOCKER_ARGS?.trim() ?: '')

        echo "Container runtime: ${runtime}  image: ${image}  args: ${extraArgs ?: '(none)'}"

        // Registry login.
        if (registry && credential) {
            withCredentials([usernamePassword(credentialsId: credential,
                                              usernameVariable: 'REG_USER',
                                              passwordVariable: 'REG_PASS')]) {
                sh "${runtime} login '${registry}' -u '${REG_USER}' -p '${REG_PASS}'"
            }
        }

        if (podman) {
            runInPodmanContainer(image, extraArgs, body)
        } else {
            runInDockerContainer(image, extraArgs, body)
        }
    }
}

return this

// Made with Bob
