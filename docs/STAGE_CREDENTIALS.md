# Stage Credentials

Vendor config repos can declare Jenkins credentials for use in stage script overrides via an optional `jenkins_credential_config.json` file. The pipeline injects them automatically at the right stage — no changes to `Jenkinsfile.declarative` stage blocks are required.

---

## Background

The only existing credential reference in the pipeline is `dockerCredential` inside build configurations in `jdkNN_pipeline_config.json`, consumed solely by `NodeAgentHelper` for container registry login. There is no general mechanism for a vendor's `vendor-scripts/NN-stage.sh` (or `.py`/`.groovy`) override to receive arbitrary credentials (API keys, signing certs, SSH keys, etc.).

---

## Vendor config file: `jenkins_credential_config.json`

Placed at the config repo root alongside `jenkins_job_config.json`. Entirely optional — if absent, nothing changes.

```json
{
  "credentials": {
    "PUBLISH_API_KEY": {
      "type": "string",
      "credentialId": "vendor-publish-api-key",
      "description": "API key for the artifact publication endpoint"
    },
    "SIGNING_CERT": {
      "type": "usernamePassword",
      "credentialId": "vendor-code-sign-cert",
      "usernameEnvVar": "SIGN_USER",
      "passwordEnvVar": "SIGN_PASS",
      "description": "Code-signing certificate login"
    },
    "RELEASE_SSH_KEY": {
      "type": "sshUserPrivateKey",
      "credentialId": "vendor-release-ssh",
      "keyFileEnvVar": "RELEASE_SSH_KEYFILE",
      "description": "SSH key for release server upload"
    }
  },
  "stageCredentials": {
    "16-publish":              ["PUBLISH_API_KEY", "RELEASE_SSH_KEY"],
    "06-post-build-code-sign": ["SIGNING_CERT"]
  }
}
```

### Schema

#### `credentials`

Named credential definitions. Each key is a logical name used to reference the credential from `stageCredentials`. Named (not anonymous) so a single credential can be shared across multiple stages.

| Field | Required | Description |
|---|---|---|
| `type` | yes | Jenkins binding type: `string`, `usernamePassword`, `sshUserPrivateKey`, `file` |
| `credentialId` | yes | The Jenkins credential store ID. Never appears in logs. |
| `description` | no | Human-readable description. |
| `usernameEnvVar` | `usernamePassword` only | Env var name for the username. Defaults to `<NAME>_USER`. |
| `passwordEnvVar` | `usernamePassword` only | Env var name for the password. Defaults to `<NAME>_PASS`. |
| `keyFileEnvVar` | `sshUserPrivateKey` only | Env var name for the key file path. Defaults to `<NAME>_KEYFILE`. |
| `fileEnvVar` | `file` only | Env var name for the file path. Defaults to `<NAME>_FILE`. |

#### `stageCredentials`

Maps stage IDs to a list of credential names. Same shape as `stageAgentLabels` in `jenkins_job_config.json`. A stage not listed here receives no credentials.

---

## Loading path

Called inside the existing `ConfigHelper.generateJenkinsConfig()` during Initialize, alongside the existing `load-jenkins-json-config.py` call:

```
generateJenkinsConfig()
  ├─ load-jenkins-json-config.py          (existing — unchanged)
  │    → jenkins-config.json
  │    → env.CONFIG_STAGE_AGENT_LABELS
  │
  └─ load-jenkins-credential-config.py   (new)
       reads  config-repo/jenkins_credential_config.json  (optional)
       writes jenkins-credential-config.json
       → env.CONFIG_CREDENTIAL_DEFINITIONS   (JSON map of named credential defs)
       → env.CONFIG_STAGE_CREDENTIALS        (JSON map of stageId → [names])
```

If the file is absent both env vars are set to `{}`.

---

## Injection — `CredentialHelper.groovy`

A new `CredentialHelper.groovy` library provides a single public method `withStageCredentials(stageId, body)`:

- If no credentials are mapped for the stage, calls `body()` directly — zero overhead.
- Otherwise builds a `withCredentials([...])` bindings list from `CONFIG_CREDENTIAL_DEFINITIONS` and wraps `body()`.
- Sets `env.STAGE_CREDENTIAL_ENV_VARS` to the injected var *names* (not values) **before** entering `withCredentials()`, then clears it in a `finally` block.

`STAGE_CREDENTIAL_ENV_VARS` is the hook that allows `containerEnvFlags()` in `StageScriptRunner` to forward credential values into Docker/Podman containers (see below).

---

## Call site: `StageScriptRunner.run()`

`credentialHelper` is injected into `StageScriptRunner` after load and `run()` wraps its internal dispatch. Every call site in `Jenkinsfile.declarative` is unchanged:

```groovy
int exitCode = stageRunner.run(PUBLISH_ARTIFACTS, config)   // unchanged
```

The credential scope is applied transparently inside `run()`:

```groovy
_withStageCredentials(scriptStem) {
    exitCode = _dispatch(found, scriptStem, config)
}

private void _withStageCredentials(String stageId, Closure body) {
    if (credentialHelper) {
        credentialHelper.withStageCredentials(stageId, body)
    } else {
        body()   // graceful degradation (e.g. Restart from Stage where Initialize was skipped)
    }
}
```

---

## Docker/Podman container forwarding

`withCredentials()` injects values into the Jenkins CPS environment, not the shell process. `docker/podman exec` starts a fresh process, so values must be forwarded explicitly via `-e` flags — the same mechanism already used for `STAGE_PARAM_NAMES`.

`containerEnvFlags()` in `StageScriptRunner` gets one new block, parallel to the existing `STAGE_PARAM_NAMES` block:

```groovy
List credEnvVarNames = (env.getProperty('STAGE_CREDENTIAL_ENV_VARS') ?: '')
    .split(',').collect { it.trim() }.findAll { it }
vars = vars + credEnvVarNames
```

`env.getProperty()` is called from within the `withCredentials()` scope so the live injected values are resolved. Jenkins masks them in logs wherever they appear.

### Call sequence for a containerised stage

```
stageRunner.run('16-publish', config)
  env.STAGE_CREDENTIAL_ENV_VARS = 'PUBLISH_API_KEY,RELEASE_SSH_KEYFILE'
  withCredentials([string(...), sshUserPrivateKey(...)]) {
    containerEnvFlags()
      vars += ['PUBLISH_API_KEY', 'RELEASE_SSH_KEYFILE']
      → "-e 'PUBLISH_API_KEY=****'" "-e 'RELEASE_SSH_KEYFILE=/tmp/key123'"
    docker exec -e 'PUBLISH_API_KEY=s3cr3t' -e 'RELEASE_SSH_KEYFILE=/tmp/key123' ... bash '16-publish.sh'
  }
  env.STAGE_CREDENTIAL_ENV_VARS = ''   // cleared in finally
```

---

## Files changed

| File | Repo | Change |
|---|---|---|
| `jenkins_credential_config.json` | vendor config repo | **new** — credential definitions and stage mappings |
| `ci/jenkins/lib/load-jenkins-credential-config.py` | ci-adoptium-pipelines | **new** — reads config file, validates, writes `jenkins-credential-config.json` |
| `ci/jenkins/lib/CredentialHelper.groovy` | ci-adoptium-pipelines | **new** — `withStageCredentials(stageId, body)` |
| `ci/jenkins/lib/ConfigHelper.groovy` | ci-adoptium-pipelines | **modified** — `generateJenkinsConfig()` calls new Python script, sets two env vars |
| `ci/jenkins/lib/StageScriptRunner.groovy` | ci-adoptium-pipelines | **modified** — inject helper, wrap dispatch, extend `containerEnvFlags()` |
| `ci/jenkins/Jenkinsfile.declarative` | ci-adoptium-pipelines | **modified** — one `@Field` + two lines in `ensureLibsLoaded()` only |

---

## Boundaries

- Does not change how credentials are stored — Jenkins credential store is unchanged.
- Does not expose `credentialId` values to build logs or the UI.
- Does not affect any Adoptium default stage — the file is optional and purely additive.
- Does not require changes to `.params.json` stage metadata files — credentials are a Jenkins-layer concern, not a CI-agnostic parameter concern.
- Non-container stages receive credentials via the normal process environment that `withCredentials()` already populates — no extra work needed.

---

## Related documentation

- [`docs/CODE_CONFIG_SEPARATION.md`](./CODE_CONFIG_SEPARATION.md) — three-repo architecture and config repo layout
- [`docs/STAGE_DEFINITION_REFERENCE.md`](./STAGE_DEFINITION_REFERENCE.md) — vendor override rules for stage scripts and params files
- [`ci/jenkins/lib/StageScriptRunner.groovy`](../ci/jenkins/lib/StageScriptRunner.groovy) — `containerEnvFlags()`, `run()`
- [`ci/jenkins/lib/ConfigHelper.groovy`](../ci/jenkins/lib/ConfigHelper.groovy) — `generateJenkinsConfig()`
