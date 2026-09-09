# Trigger Architecture

This document describes the CI-agnostic trigger system that detects upstream
OpenJDK tag events and automatically fires the appropriate build pipeline.

---

## Three-Layer Model

```
Layer 0: Trigger Definitions (CI-agnostic JSON in config-repo)
  trigger_config.json      — what versions to watch, patterns, repo URLs
  jenkins_job_config.json  — deployments[], pipelineBaseFolder

Layer 1b: CI Orchestration (Jenkins-specific)
  Jenkinsfile.trigger      — scheduling, dedup policy, Jenkins API calls, build() trigger

Layer 2: Trigger Scripts (CI-agnostic Bash)
  scripts/triggers/        — pure detection logic; no Jenkins calls
  config-repo/vendor-triggers/  — vendor overrides or additions
```

The Layer 2 scripts are locally executable and CI-agnostic. All Jenkins-specific
logic (cron scheduling, build history queries, `build()` calls) lives exclusively
in `Jenkinsfile.trigger`.

---

## Trigger Types

### `detect-build-tag-for-github-release`

Detects the latest upstream build tag matching `buildTagPattern` on `monitorRepo`,
derives the expected published release tag using `publishNameMap` and
`targetReleaseTagMap`, and checks whether it already exists on `targetRepo`
(GitHub or GitHub Enterprise releases API).

**Dedup policy:** the script itself checks `targetRepo` — if `shouldTrigger=true`
the CI layer triggers directly. No Jenkins history check needed.

### `detect-ga-tag`

Detects the latest upstream GA tag matching `gaTagPattern` on `monitorRepo`,
resolves the build tag at the same commit SHA matching `buildTagPattern`.

**Dedup policy:** handled entirely in `Jenkinsfile.trigger` — queries Jenkins
build history for an existing completed or in-progress build with matching
`SCM_REF`. `IN_PROGRESS` or `ALREADY_BUILT` → skip. `NOT_FOUND` → trigger.
This covers the window between a completed private build and manual publish.

### `weekly-head`

No detection — unconditionally triggers a HEAD build on a weekly cron.
No dedup needed (idempotent by design).

### Vendor types

Any `type` value not listed above is resolved via `TriggerScriptRunner` and
treated with the `detect-ga-tag` dedup policy (Jenkins history check) by default.

---

## `trigger_config.json` Schema

```json
{
  "triggers": [
    {
      "type": "<trigger-type-stem>",
      "versions": [
        {
          "version":             "jdk21",
          "monitorRepo":         "https://github.com/adoptium/jdk21u.git",
          "targetRepo":          "https://github.com/adoptium/temurin21-binaries",
          "buildTagPattern":     "jdk-21\\..+_adopt$",
          "gaTagPattern":        "jdk-21\\..+-ga$",
          "publishNameMap":      "s/_adopt$/-ea/",
          "targetReleaseTagMap": "s/$/-beta/",
          "suppressTestingConditions": [
            {
              "param": "RELEASE_TYPE",
              "value": "WEEKLY",
              "window": {
                "event":      "OPENJDK_RELEASE_DAY",
                "daysBefore": 0,
                "daysAfter":  7
              }
            }
          ],
          "enabled": true
        }
      ]
    }
  ]
}
```

### Field reference

| Field | Used in | Required | Default when absent | Description |
|---|---|---|---|---|
| `monitorRepo` | all detect types | yes | — | Git repo URL to watch for tags |
| `buildTagPattern` | `detect-build-tag-*`, `detect-ga-tag` | no | Version-derived (see below) | ERE regex to match/resolve the build tag |
| `gaTagPattern` | `detect-ga-tag` | no | `.*-ga$` | ERE regex to match the GA tag |
| `publishNameMap` | `detect-build-tag-*` | yes | — | `sed` expression: detected tag → publish name |
| `targetReleaseTagMap` | `detect-build-tag-*` | yes | — | `sed` expression: publish name → release tag checked on `targetRepo` |
| `targetRepo` | `detect-build-tag-*` | yes | — | GitHub/GHE releases repo to check for published assets |
| `suppressTestingConditions` | all | no | `[]` (never suppress) | Conditions under which `RUN_TESTS` is forced false |
| `enabled` | all | yes | — | Set `false` to disable this version without removing it |

### `buildTagPattern` defaults

When `buildTagPattern` is omitted, `trigger-utils.py default-build-tag-pattern` derives:
- `jdk8` → `jdk8u.+_adopt$`
- all others → `jdk-<N>[\\.+].+_adopt$`

Explicitly setting `buildTagPattern` is always preferred — it removes the
version-number-branching logic from the script and makes the pattern auditable.

### `suppressTestingConditions`

An array of conditions that must **all** match for `RUN_TESTS` to be forced
`false` on the triggered launch job. Each condition:

```json
{
  "param": "RELEASE_TYPE",   // parameter from effectiveParams (deployment defaults + RELEASE_TYPE)
  "value": "WEEKLY",         // required value; supports "regex:" prefix
  "window": {                // optional — condition only applies within this date window
    "event":      "OPENJDK_RELEASE_DAY",
    "daysBefore": 0,
    "daysAfter":  7
  }
}
```

Built-in `event` names:

| Name | Resolves to |
|---|---|
| `OPENJDK_RELEASE_DAY` | 3rd Tuesday of the current UTC month |

If `window` is omitted, the condition applies unconditionally whenever the
`param`/`value` match. If `window.event` is unrecognised, the condition is
ignored and testing is **not** suppressed (fail safe).

---

## GitHub Enterprise Support

The `check-github-release-asset` command in `trigger-utils.py` automatically
detects whether `targetRepo` is github.com or GitHub Enterprise:

- `https://github.com/org/repo` → `https://api.github.com/repos/org/repo/...`
- `https://github.ibm.com/org/repo` → `https://github.ibm.com/api/v3/repos/org/repo/...`

No extra configuration is needed — the URL hostname drives the API path.
`GITHUB_TOKEN` is used for authentication on both variants.

---

## `vendor-triggers/` Extension Pattern

Vendor trigger scripts follow the same resolution order as stage scripts:

```
1. config-repo/vendor-triggers/<type>.sh   ← vendor override or addition
2. scripts/triggers/<type>.sh              ← default (core pipeline repo)
3. not found → error
```

### Adding a new trigger type

1. Create `config-repo/vendor-triggers/<type>.sh` — same interface contract as
   default trigger scripts (reads `trigger-version-config.json`, writes
   `trigger-result.json` to `$TARGET_DIR`)
2. Add a `{ "type": "<type>", "versions": [...] }` entry to `trigger_config.json`
3. Add `"<type>"` to the relevant deployment's `triggers` array in
   `jenkins_job_config.json`
4. Re-run the seed job — the trigger job is created automatically

No changes to the pipeline repo are required. The vendor type receives the
`detect-ga-tag` dedup policy (Jenkins history check) by default in
`Jenkinsfile.trigger`.

### Example — Artifactory-backed build tag detection

```json
{
  "type": "detect-build-tag-for-artifactory",
  "versions": [
    {
      "version":         "jdk21",
      "monitorRepo":     "https://github.ibm.com/runtimes/openj9-openjdk-jdk21.git",
      "targetRepo":      "https://artifactory.example.com/openj9-binaries",
      "buildTagPattern": "jdk-21\\..+_openj9-.+",
      "publishNameMap":  "s/_openj9-/-/",
      "targetReleaseTagMap": "s/$/-release/",
      "enabled": true
    }
  ]
}
```

The vendor script `config-repo/vendor-triggers/detect-build-tag-for-artifactory.sh`
reads the same `monitorRepo`/`targetRepo`/`buildTagPattern`/`publishNameMap`/
`targetReleaseTagMap` fields and queries Artifactory instead of GitHub releases.

---

## `TriggerScriptRunner` Reference

```
ci/jenkins/lib/TriggerScriptRunner.groovy

Resolution order:
  1. config-repo/vendor-triggers/<type>.sh
  2. scripts/triggers/<type>.sh
  3. error (all types)

Environment set for scripts:
  WORKSPACE                   — Jenkins agent workspace
  TARGET_DIR                  — <WORKSPACE>/trigger-<type>-output
  TRIGGER_VERSION_CONFIG_FILE — <WORKSPACE>/trigger-version-config.json
  PIPELINE_ROOT               — ci-adoptium-pipelines checkout root
  GITHUB_TOKEN                — injected via withCredentials when configured

Public API:
  Map run(String triggerType, Map versionConfig)
  boolean scriptExists(String triggerType)
  void setGithubTokenCredentialId(String credId)
```

---

## Deployment Folder Layout

```
Jenkins root
└── <pipelineBaseFolder>/           (from jenkins_job_config.json)
    ├── <deployment.folder>/        e.g. "release"
    │   ├── Build_openjdk_launchers/
    │   │   └── Build_openjdk21_launch
    │   ├── Build_openjdk/          (lazy-created at launch run time)
    │   └── Triggers/
    │       └── Trigger_detect-ga-tag   (daily cron — secured to release team)
    └── <deployment.folder>/        e.g. "beta"
        ├── Build_openjdk_launchers/
        │   └── Build_openjdk21_launch
        ├── Build_openjdk/
        └── Triggers/
            ├── Trigger_detect-build-tag-for-github-release  (daily cron)
            └── Trigger_weekly-head                          (weekly cron)
```

Jenkins folder-level security is applied at the deployment folder boundary.
The seed job creates these folders — operators apply security to them after
the first seed run.

---

## Related Documentation

- [`docs/JOB_DSL_AUTOMATION.md`](./JOB_DSL_AUTOMATION.md) — seed job setup and deployment model
- [`docs/CI_AGNOSTIC_ARCHITECTURE.md`](./CI_AGNOSTIC_ARCHITECTURE.md) — three-layer pipeline architecture
- [`scripts/lib/trigger-utils.py`](../scripts/lib/trigger-utils.py) — Python utility: GitHub API query, trigger-result.json writing
- [`scripts/triggers/`](../scripts/triggers/) — default trigger scripts
- [`ci/jenkins/lib/TriggerScriptRunner.groovy`](../ci/jenkins/lib/TriggerScriptRunner.groovy) — script resolution and execution
- [`ci/jenkins/Jenkinsfile.trigger`](../ci/jenkins/Jenkinsfile.trigger) — Jenkins CI orchestration
- [`ci/jenkins/job-dsl/seed/seed_job_dsl.groovy`](../ci/jenkins/job-dsl/seed/seed_job_dsl.groovy) — trigger job generation
