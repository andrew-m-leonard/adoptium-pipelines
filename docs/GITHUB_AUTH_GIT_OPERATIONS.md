# GitHub Authentication for Git Operations

GitHub is introducing rate-limiting for unauthenticated HTTPS git operations. Pipeline stages that call `git clone https://github.com/...` (build repo, AQA tests, etc.) will be affected. This document describes how the framework provides transparent GitHub authentication to every stage without requiring any changes to stage scripts.

---

## Design principles

- **No secrets in config files** — the token value never appears in any file committed to any repository.
- **No changes to stage scripts** — `.sh`, `.py`, and `.groovy` stage implementations are unchanged; authentication is injected transparently by the stage runner.
- **CI-specific token source** — each CI adapter obtains the token in its own natural way; the mechanism that delivers it to `git` is identical across all adapters.
- **Safe credential handling** — the token is never interpolated into a `withEnv` argument string or a git config key/value. It stays in its own named environment variable, which the CI system already masks in logs.

---

## Token source — CI-specific

### Jenkins

The token is stored as a **Jenkins `string` credential** and declared in the vendor config repo's `jenkins_credential_config.json` using the existing [Stage Credentials](./STAGE_CREDENTIALS.md) mechanism:

```json
{
  "credentials": {
    "GITHUB_TOKEN": {
      "type": "string",
      "credentialId": "my-github-pat-cred-id",
      "description": "GitHub PAT for authenticated git operations (rate-limit avoidance)"
    }
  },
  "stageCredentials": {
    "ALL_STAGES": ["GITHUB_TOKEN"]
  }
}
```

The special key `ALL_STAGES` in `stageCredentials` instructs `CredentialHelper` to inject this credential into every stage, not just specific ones. Only the non-secret `credentialId` string appears in the config repo. The token value lives exclusively in the Jenkins credential store.

### Local runner

The developer sets `GITHUB_TOKEN` in their shell before invoking `run-pipeline.py`:

```bash
export GITHUB_TOKEN=ghp_xxxxxxxxxxxx
python3 ci/local/run-pipeline.py --jdk-version jdk21 --target-os linux --architecture x64 \
    --config-repo-url https://github.com/adoptium/ci-temurin-config.git
```

`stage_env.py` picks it up from `os.environ` automatically — no CLI flag is required and no configuration file is needed.

---

## How authentication reaches `git` — the `GIT_ASKPASS` mechanism

Git calls the program named by `GIT_ASKPASS` when it needs HTTPS credentials. The framework writes a tiny script to the stage workspace:

```sh
#!/bin/sh
echo "${GITHUB_TOKEN}"
```

`GIT_ASKPASS` is set to the **path** of this script, not to the token value itself. When git performs any HTTPS operation it executes the script, which reads `GITHUB_TOKEN` from its inherited environment and prints it. The token therefore:

- never appears in a `withEnv` argument (only the script path does)
- never appears in a git config key or value string
- remains in the `GITHUB_TOKEN` environment variable, which Jenkins already masks in all log output

The script is written to the stage workspace, which is wiped by `cleanWs()` / stage cleanup after every stage completes.

---

## Flow diagrams

### Jenkins

```
jenkins_credential_config.json
  "stageCredentials": { "ALL_STAGES": ["GITHUB_TOKEN"] }
       │
       ▼
CredentialHelper.withStageCredentials()          ← wraps every stage (existing mechanism)
  withCredentials([string(credentialId: ..., variable: 'GITHUB_TOKEN')])
  ↳ Jenkins masks GITHUB_TOKEN value in all log output
       │
       ▼
StageScriptRunner._dispatch()                    ← single change point
  writeFile 'git-askpass.sh' ← "#!/bin/sh\necho \"${GITHUB_TOKEN}\"\n"
  withEnv(['GIT_ASKPASS=<workspace>/git-askpass.sh']) {
       │
       ├─ .sh      sh("bash <script>")
       │             shell inherits GIT_ASKPASS; git calls script at auth time
       │
       ├─ .py      sh("python-runner.sh <script>")
       │             shell inherits GIT_ASKPASS; git calls script at auth time
       │
       └─ .groovy  load() + script(config)
                     every sh("git ...") inside inherits GIT_ASKPASS from withEnv scope
  }
```

### Local runner

```
export GITHUB_TOKEN=ghp_xxx      ← developer sets in shell
       │
       ▼
stage_env.py  build_stage_env()
  if "GITHUB_TOKEN" in os.environ:
      write <stage_workspace>/git-askpass.sh ← "#!/bin/sh\necho \"${GITHUB_TOKEN}\"\n"
      chmod +x git-askpass.sh
      env["GIT_ASKPASS"] = "<stage_workspace>/git-askpass.sh"
      # GITHUB_TOKEN is already present via os.environ.copy()
       │
       ▼
StageResolver.run()
  subprocess.run(cmd, env=env)   ← child process inherits GIT_ASKPASS + GITHUB_TOKEN
       │
       ├─ .sh  bash <script>     ← git calls GIT_ASKPASS script at auth time
       └─ .py  python <script>   ← git calls GIT_ASKPASS script at auth time
```

---

## Groovy stage scripts

Groovy stage scripts (`.groovy` vendor overrides) run inside the Jenkins CPS engine JVM, not in a subprocess. Any `sh("git clone ...")` call they make spawns a fresh shell. That shell is created **inside the `withEnv(['GIT_ASKPASS=...'])` scope** that `StageScriptRunner._dispatch()` establishes, so Jenkins automatically propagates `GIT_ASKPASS` into it. No changes to Groovy stage scripts are required.

---

## Security properties

| Property | Detail |
|---|---|
| Token in config file | ❌ Never — only the non-secret `credentialId` string |
| Token in `withEnv` argument | ❌ Never — only the `GIT_ASKPASS` script *path* |
| Token in git config key/value | ❌ Never — git reads it from the env at auth time via `GIT_ASKPASS` |
| Token masked in Jenkins logs | ✅ Yes — `withCredentials(string(...))` masks it everywhere |
| Token in container exec `-e` flags | ✅ Masked — forwarded via `STAGE_CREDENTIAL_ENV_VARS` / `containerEnvFlags()`, Jenkins masks the value |
| `git-askpass.sh` content | Safe — contains only `echo "${GITHUB_TOKEN}"`, no literal secret |
| `git-askpass.sh` lifetime | Stage workspace only — wiped by `cleanWs()` after every stage |

---

## What changes, what does not

### Files changed

| File | Repo | Change |
|---|---|---|
| `jenkins_credential_config.json` | vendor config repo | Add `GITHUB_TOKEN` credential entry and `ALL_STAGES` mapping (optional) |
| `ci/jenkins/lib/CredentialHelper.groovy` | ci-adoptium-pipelines | Recognise `ALL_STAGES` wildcard key in `stageCredentials` |
| `ci/jenkins/lib/StageScriptRunner.groovy` | ci-adoptium-pipelines | Write `git-askpass.sh` and wrap `_dispatch()` with `withEnv(['GIT_ASKPASS=...'])` when `GITHUB_TOKEN` is set |
| `ci/local/lib/stage_env.py` | ci-adoptium-pipelines | Write `git-askpass.sh` and set `GIT_ASKPASS` in env dict when `GITHUB_TOKEN` is present in `os.environ` |

### Files not changed

- `Jenkinsfile.declarative` — no changes
- All default stage scripts (`scripts/stages/*.sh`, `*.py`) — no changes
- All vendor stage script overrides — no changes
- `adoptium_pipeline_config.json` — no changes
- `jenkins_job_config.json` — no changes

---

## Without a token configured

If `GITHUB_TOKEN` is absent from the Jenkins credential config (i.e. no `ALL_STAGES` entry) or not set in the local shell, the pipeline behaves exactly as before: no `GIT_ASKPASS` is written, no `withEnv` wrapping is applied, and git operations proceed unauthenticated. The feature is entirely opt-in.

---

## Related documentation

- [`docs/STAGE_CREDENTIALS.md`](./STAGE_CREDENTIALS.md) — the existing per-stage credential injection mechanism that `GITHUB_TOKEN` builds on
- [`docs/CODE_CONFIG_SEPARATION.md`](./CODE_CONFIG_SEPARATION.md) — three-repo architecture and config repo layout
- [`ci/jenkins/lib/CredentialHelper.groovy`](../ci/jenkins/lib/CredentialHelper.groovy) — `withStageCredentials()`, credential binding types
- [`ci/jenkins/lib/StageScriptRunner.groovy`](../ci/jenkins/lib/StageScriptRunner.groovy) — `_dispatch()`, `containerEnvFlags()`
- [`ci/local/lib/stage_env.py`](../ci/local/lib/stage_env.py) — `build_stage_env()`
