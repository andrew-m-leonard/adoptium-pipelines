# Code/Config Separation Pattern

## Overview

The Adoptium CI Pipelines architecture maintains a strict separation between **pipeline code** (this repository) and **pipeline configuration** (a separate config repository such as `ci-temurin-config`). The pipeline code never contains build-specific settings; all such data lives in the config repo.

This separation enables:

- **Vendor independence** — different organizations maintain their own config repos while reusing the same pipeline code
- **Privacy** — vendors can keep their configs in private repos without forking the pipeline
- **Governance** — config and code are owned and reviewed separately
- **Testability** — swap configs at build time without touching code

---

## Config Repository Structure

The config repo is the single source of all externalized settings. It must contain:

```
<config-repo>/
├── adoptium_pipeline_config.json          # CI-agnostic defaults and repo pointers
├── jenkins_job_config.json                # Jenkins-specific job and agent settings
├── configurations/
│   ├── jdk8u_pipeline_config.json         # Per-version platform build settings
│   ├── jdk11u_pipeline_config.json
│   ├── jdk17u_pipeline_config.json
│   ├── jdk21u_pipeline_config.json
│   └── ...
└── vendor-scripts/                        # Optional vendor-specific stage overrides
    ├── 02-build.sh                        # Overrides scripts/stages/02-build.sh
    └── ...
```

---

## Config Files in Detail

### 1. `adoptium_pipeline_config.json` — CI-agnostic pipeline defaults

**Location**: root of the config repo  
**Consumed by**: seed job, launch pipeline (`Jenkinsfile.launch`), build pipeline (`ConfigHelper.groovy`), local runner (`run-pipeline.py`)

This is the top-level config file that glues everything together. It tells the system:
- which JDK versions are active
- the default build variant and args
- where to find the per-version config files (prefix/suffix pattern)
- URLs and branch refs for `temurin-build` and `aqa-tests` repositories

**Example structure**:
```json
{
  "defaultVariant": "temurin",
  "defaultBuildArgs": "--create-jre-image",
  "defaultConfigureArgs": "",
  "defaultScmReference": "",
  "configFilePrefix": "configurations/",
  "configFileSuffix": "_pipeline_config.json",
  "activeJdkVersions": [
    { "version": "jdk21u", "enabled": true },
    { "version": "jdk17u", "enabled": true },
    { "version": "jdk11u", "enabled": false }
  ],
  "repository": {
    "url": "https://github.com/adoptium/ci-adoptium-pipelines.git",
    "branch": "main",
    "credentialsId": "",
    "buildRepoUrl": "https://github.com/adoptium/temurin-build.git",
    "buildBranch": "master",
    "aqaRepoUrl": "https://github.com/adoptium/aqa-tests.git",
    "aqaBranch": "master"
  }
}
```

**How it is loaded**:

| Consumer | Method |
|---|---|
| Seed job (`seed_job_dsl.groovy`) | Fetched directly from `raw.githubusercontent.com` via HTTP during seed job execution |
| Build pipeline (`ConfigHelper.groovy`) | Read from `./config-repo/adoptium_pipeline_config.json` after Git sparse-checkout |
| Local runner (`run-pipeline.py`) | Read from `<workspace>/config-repo/adoptium_pipeline_config.json` after `git clone` |
| CLI tool (`load-adoptium-pipeline-config-json.py`) | Either local path (`--config-repo-dir`) or fetched from remote (`--config-repo-url`) |

---

### 2. `jenkins_job_config.json` — Jenkins-specific job and agent settings

**Location**: root of the config repo  
**Consumed by**: seed job (`seed_job_dsl.groovy`) at job-creation time, and by `ConfigHelper.generateJenkinsConfig()` at build runtime (via `ci/jenkins/lib/load-jenkins-json-config.py`)

Contains two distinct groups of settings:

- **Job-creation settings** (`jenkinsfilePath`, `pipelineTimeoutHours`, `activeNodeTimeoutMinutes`, `jobConfiguration`) — used by the seed job to configure Jenkins job definitions. Not needed at build runtime.
- **Agent-selection settings** (`stageAgentLabels`) — used at build runtime to resolve which Jenkins node each pipeline stage runs on. Keys are **stage IDs** (from `pipeline-stages.json`), not display labels. The `{os}` and `{arch}` placeholders are substituted with `sw.os.*` / `hw.arch.*` schema label tokens derived from the platform's `os` and `arch` fields. The special key `__any__` provides the fallback label used for any stage whose ID is not explicitly listed.

**Example structure**:
```json
{
  "jenkinsfilePath": "ci/jenkins/Jenkinsfile.declarative",
  "pipelineTimeoutHours": 8,
  "activeNodeTimeoutMinutes": 10,
  "stageAgentLabels": {
    "__any__":               "ci.role.worker",
    "01-initialize":         "ci.role.worker",
    "02-build":              "ci.role.build&&sw.os.{os}&&hw.arch.{arch}",
    "03-internal-code-sign": "eclipse-codesign",
    "04-assemble-images":    "ci.role.build&&sw.os.{os}&&hw.arch.{arch}",
    "06-post-build-code-sign": "ci.role.worker",
    "07-installer":          "ci.role.build&&sw.os.{os}&&hw.arch.{arch}",
    "08-code-sign-installer": "ci.role.worker",
    "09-sbom-sign":          "ci.role.worker",
    "10-digital-artifact-sign": "ci.role.worker",
    "11-verify-signing":     "ci.role.worker",
    "12-validate-sbom":      "ci.role.build&&sw.os.{os}&&hw.arch.{arch}",
    "13-smoke-tests":        "ci.role.build&&sw.os.{os}&&hw.arch.{arch}",
    "14-aqa-tests":          "ci.role.build&&hw.arch.{arch}",
    "15-tck-tests":          "ci.role.build&&hw.arch.{arch}",
    "16-publish":            "ci.role.worker",
    "20-reproducible-compare": "ci.role.build&&sw.os.{os}&&hw.arch.{arch}"
  },
  "jobConfiguration": {
    "defaultParameters": {
      "VARIANT": "temurin",
      "CLEAN_WORKSPACE_AFTER_STAGE": true,
      "CREATE_SBOM": true,
      "RUN_TESTS": true,
      "ENABLE_INSTALLERS": true,
      "SIGN_ARTIFACTS": true,
      "PUBLISH_ARTIFACTS": false,
      "RUN_REPRODUCIBLE_COMPARE": false
    },
    "logRotation": {
      "daysToKeep": 30,
      "numToKeep": 50,
      "artifactDaysToKeep": 7,
      "artifactNumToKeep": 10
    }
  }
}
```

**How it is loaded**:

- **Seed job** — fetched from `raw.githubusercontent.com` alongside `adoptium_pipeline_config.json`; used to set log rotation and default parameter values on generated jobs.
- **Build pipeline** — sparse-checked out into `config-repo/` alongside `adoptium_pipeline_config.json`; then read by `ci/jenkins/lib/load-jenkins-json-config.py` (called from `ConfigHelper.generateJenkinsConfig()`) to produce `jenkins-config.json`. See §4 below.
- **Local runner** — not consumed; `jenkins_job_config.json` is Jenkins-specific and the local runner has no equivalent.

---

### 3. `configurations/jdkNN_pipeline_config.json` — Per-version platform build settings

**Location**: `configurations/` directory of the config repo (path determined by `configFilePrefix` / `configFileSuffix` in `adoptium_pipeline_config.json`)
**Consumed by**: `scripts/lib/load-json-config.py` (invoked by `ConfigHelper.groovy` on Jenkins, or `run-pipeline.py` locally)

One file per JDK version. Describes every supported build platform and its platform-specific settings. The filename pattern is `<configFilePrefix><version><configFileSuffix>`, e.g. `configurations/jdk21_pipeline_config.json`.

**Example structure**:
```json
{
  "version": "jdk21",
  "buildConfigurations": {
    "aarch64_mac": {
      "os": "mac",
      "arch": "aarch64",
      "additionalNodeLabels": "sw.tool.xcode.15_0_1",
      "configureArgs": "--enable-dtrace",
      "buildArgs": {
        "temurin": "--create-jre-image",
        "hotspot": "--create-jre-image"
      }
    },
    "x86-64_linux": {
      "os": "linux",
      "arch": "x64",
      "dockerImage": "adoptopenjdk/centos7_build_image",
      "configureArgs": "--enable-unlimited-crypto",
      "buildArgs": "--create-jre-image"
    }
  }
}
```

> **Platform key naming**: keys follow the aqa-tests `PLATFORM_MAP` convention — `{arch}_{os}` using hyphens within compound segments, e.g. `x86-64_linux`, `aarch64_mac`. The `os` and `arch` **field values** inside each entry retain their temurin-build identifiers (`"os": "mac"`, `"arch": "x64"`, etc.) and do **not** change. See [`LABEL_SCHEMA.md`](./LABEL_SCHEMA.md) for the full key mapping table.

**How it is loaded**:

The file is located by [`scripts/lib/load-json-config.py`](../scripts/lib/load-json-config.py) which constructs the path as:

```
<config-dir>/<jdk-version>_pipeline_config.json
```

`--config-dir` defaults to `./configurations` and is set to `./config-repo/configurations` (Jenkins) or resolved from `configFilePrefix` in `adoptium_pipeline_config.json` (local runner).

The script extracts the entry for the requested platform key (e.g. `aarch64_mac`), merges it with runtime parameters, and writes the output to `pipeline-config.json`.

#### Platform configuration fields

| Field | Type | Description |
|---|---|---|
| `os` | string | Operating system: `mac`, `linux`, `windows`, `aix`, `alpine-linux`, `solaris`, `zos` |
| `arch` | string | Architecture: `aarch64`, `x64`, `x86-32`, `ppc64`, `ppc64le`, `s390x`, `arm`, `riscv64`, `sparcv9` |
| `buildArgs` | string or object | Build arguments passed to `make-adopt-build-farm.sh` |
| `configureArgs` | string or object | Arguments passed to OpenJDK `configure` |
| `dockerImage` | string or object | Docker image to use for the build |
| `dockerFile` | string or object | Custom Dockerfile path |
| `dockerRegistry` | string | Docker registry URL |
| `dockerCredential` | string | Jenkins credential ID for the Docker registry |
| `dockerArgs` | string | Additional arguments passed to `docker run` |
| `additionalNodeLabels` | string or object | Extra Jenkins node labels ANDed onto the base label. Must use the `sw.*` / `hw.*` / `ci.*` schema (e.g. `sw.tool.xcode.15_0_1`, `sw.os.windows.2022&&sw.tool.vs.2022`) |
| `additionalTestLabels` | string or object | Extra labels for test nodes |
| `additionalTestParams` | object | Extra parameters forwarded to the test stage |
| `cleanWorkspaceAfterBuild` | boolean | Whether to clean the workspace after the build stage |

Fields marked as "string or object" support **variant-specific values**: supply either a plain string (applies to all variants) or an object keyed by variant name:

```json
// Plain string — same value for all variants
"buildArgs": "--create-jre-image"

// Variant-specific — different value per variant; "default" is the fallback
"buildArgs": {
  "temurin": "--create-jre-image",
  "hotspot": "--create-jre-image",
  "default": "--create-jre-image"
}
```

`load-json-config.py` detects which form is used, extracts the value for the active variant, and falls back to `"default"` if the variant key is absent.

---

### 4. `pipeline-config.json` — CI-agnostic generated runtime config

**Location**: workspace root (Jenkins) or `<workspace>/pipeline-config.json` (local)  
**Generated by**: `scripts/lib/load-json-config.py` via `ConfigHelper.generatePipelineConfig()` during the Initialize stage  
**Consumed by**: every subsequent pipeline stage via the `CONFIG_FILE` environment variable; also read by `PipelineHelper.groovy` and `StageScriptRunner.groovy` to gate stage execution

This file is not stored in any repository — it is generated fresh for each build by combining the per-version JSON config with the runtime parameters supplied to the job. It is CI-agnostic: it contains no Jenkins-specific agent labels.

**Structure**:
```json
{
  "buildConfig": {
    "JAVA_TO_BUILD": "jdk21",
    "TARGET_OS": "mac",
    "ARCHITECTURE": "aarch64",
    "VARIANT": "temurin",
    "BUILD_ARGS": "--create-jre-image",
    "CONFIGURE_ARGS": "--enable-dtrace",
    "NODE_LABEL": "ci.role.build&&sw.os.mac&&hw.arch.aarch64",
    "DOCKER_IMAGE": "",
    "DOCKER_FILE": "",
    "DOCKER_REGISTRY": "",
    "DOCKER_CREDENTIAL": "",
    "DOCKER_ARGS": "",
    "PODMAN_ARGS": ""
  },
  "parameters": {
    "cleanWorkspaceAfterStage": true
  },
  "repoDefaults": {
    "buildRef": "master",
    "buildRepoUrl": "https://github.com/adoptium/temurin-build.git",
    "aqaRef": "master",
    "aqaRepoUrl": "https://github.com/adoptium/aqa-tests.git"
  }
}
```

> **Stage parameters** (`SCM_REF`, `BUILD_REF`, `AQA_REF`, `CREATE_SBOM`, `RUN_TESTS`, `ENABLE_INSTALLERS`, `SIGN_ARTIFACTS`, `RUN_REPRODUCIBLE_COMPARE`, …) are **not** stored in this file. They flow exclusively through the process environment — injected by Jenkins job parameters or by `run-pipeline.py`'s `_stage_env()`. This keeps `pipeline-config.json` CI-agnostic and separates static platform config from per-run operator choices.

On Jenkins it is immediately archived as a build artifact so that subsequent stages (which each start with a clean workspace) can retrieve it via `copyArtifacts`.

---

### 5. `jenkins-config.json` — Jenkins-specific generated runtime config

**Location**: workspace root (Jenkins only)  
**Generated by**: `ci/jenkins/lib/load-jenkins-json-config.py` via `ConfigHelper.generateJenkinsConfig()` during the Initialize stage  
**Consumed by**: `ConfigHelper.generateJenkinsConfig()` which reads it back to set `CONFIG_NODE_LABEL` and `CONFIG_STAGE_AGENT_LABELS` environment variables used for Jenkins agent selection

This file is Jenkins-specific and has no equivalent in the local runner. It is archived alongside `pipeline-config.json` as a build artifact.

**Structure**:
```json
{
  "stageAgentLabels": {
    "__any__":        "ci.role.worker",
    "01-initialize":  "ci.role.worker",
    "02-build":       "ci.role.build&&sw.os.{os}&&hw.arch.{arch}",
    "13-smoke-tests": "ci.role.build&&sw.os.{os}&&hw.arch.{arch}"
  },
  "resolvedStageAgentLabels": {
    "__any__":        "ci.role.worker",
    "01-initialize":  "ci.role.worker",
    "02-build":       "ci.role.build&&sw.os.mac&&hw.arch.aarch64",
    "13-smoke-tests": "ci.role.build&&sw.os.mac&&hw.arch.aarch64"
  },
  "buildNodeLabel": "ci.role.build&&sw.os.mac&&hw.arch.aarch64"
}
```

The `resolvedStageAgentLabels` map has all `{os}` and `{arch}` placeholders substituted with the `sw.os.*` / `hw.arch.*` label schema tokens corresponding to the platform's `os` and `arch` field values. See [`LABEL_SCHEMA.md`](./LABEL_SCHEMA.md) for the substitution mapping.

---

### 6. `vendor-scripts/` — Optional stage overrides

**Location**: `vendor-scripts/` directory of the config repo  
**Consumed by**: `StageScriptRunner.groovy` (Jenkins) and `StageResolver` (local runner)

Vendors can place scripts here to replace any default stage script in `scripts/stages/`. Resolution order (first match wins):

| Priority | Jenkins (`StageScriptRunner.groovy`) | Local (`StageResolver`) |
|---|---|---|
| 1 | `config-repo/vendor-scripts/<stem>.sh` | `config-repo/vendor-scripts/<stem>.sh` |
| 2 | `config-repo/vendor-scripts/<stem>.groovy` | `config-repo/vendor-scripts/<stem>.py` |
| 3 | `config-repo/vendor-scripts/<stem>.py` | `scripts/stages/<stem>.sh` |
| 4 | `scripts/stages/<stem>.sh` | `scripts/stages/<stem>.py` |
| 5 | `scripts/stages/<stem>.groovy` | *(no-op)* |
| 6 | `scripts/stages/<stem>.py` | — |
| 7 | *(no-op)* | — |

> **Note**: `.groovy` scripts are Jenkins-only; the local runner does not support them.

---

## How Config Flows Through the Pipeline

### Jenkins path

```
Seed Job (seed_job_dsl.groovy)
  │  reads adoptium_pipeline_config.json    ← HTTP from raw.githubusercontent.com
  │  reads jenkins_job_config.json          ← HTTP from raw.githubusercontent.com
  │
  └─► Creates launch jobs and build pipeline jobs
         (CONFIG_REPO_URL / CONFIG_REPO_BRANCH baked into job parameters)

Launch Job (Jenkinsfile.launch)
  │  git clone config-repo → dir('config-repo')
  │  reads config-repo/configurations/jdkNN_pipeline_config.json
  │                                         ← selects available platforms
  └─► Creates or updates platform build jobs in parallel

Build Pipeline (Jenkinsfile.declarative)
  │
  ├─ Initialize stage (PipelineHelper + ConfigHelper)
  │     git sparse-checkout config-repo
  │       (configurations/*, vendor-scripts/*, adoptium_pipeline_config.json,
  │        jenkins_job_config.json)
  │
  │     ConfigHelper.generatePipelineConfig()  [CI-agnostic]
  │       reads config-repo/adoptium_pipeline_config.json  ← buildRef, aqaRef defaults
  │       runs scripts/lib/load-json-config.py             ← merges params + per-version JSON
  │       writes pipeline-config.json
  │
  │     ConfigHelper.generateJenkinsConfig()  [Jenkins-specific]
  │       runs ci/jenkins/lib/load-jenkins-json-config.py
  │         reads config-repo/jenkins_job_config.json      ← stageAgentLabels templates
  │         reads pipeline-config.json                     ← TARGET_OS, ARCHITECTURE
  │         writes jenkins-config.json                     ← resolved stage labels
  │       sets CONFIG_NODE_LABEL, CONFIG_STAGE_AGENT_LABELS env vars
  │
  │     archives pipeline-config.json, jenkins-config.json as build artifacts
  │
  └─ Every subsequent stage (PipelineHelper.initializeStage)
        clean workspace
        git sparse-checkout (for scripts and vendor overrides)
        copyArtifacts pipeline-config.json from Initialize
        sets CONFIG_FILE env var → stage scripts read it via config-utils.sh
```

### Local runner path

```
run-pipeline.py
  │
  ├─ stage_initialize()
  │     git clone --depth 1 config-repo  (or use local path)
  │     reads config-repo/adoptium_pipeline_config.json   ← variant, buildRef, aqaRef defaults
  │     runs scripts/lib/load-json-config.py              ← merges CLI args + per-version JSON
  │     writes <workspace>/pipeline-config.json
  │     (jenkins_job_config.json is not read — Jenkins-specific)
  │
  └─ Every subsequent stage
        StageResolver.run(stem, env)
          checks pipeline-config.json parameters to gate stage
          resolves vendor-scripts/ then scripts/stages/ for the script to run
          sets CONFIG_FILE env var pointing to pipeline-config.json
```

---

## Config vs Parameter Priority

Several values can come from either the config repo or from job parameters. The priority is:

| Value | Priority 1 (wins) | Priority 2 (fallback) |
|---|---|---|
| `BUILD_REF` | `BUILD_REF` job param (non-empty) | `repository.buildBranch` in `adoptium_pipeline_config.json` |
| `AQA_REF` | `AQA_REF` job param (non-empty) | `repository.aqaBranch` in `adoptium_pipeline_config.json` |
| `BUILD_REPO_URL` | — | `repository.buildRepoUrl` in `adoptium_pipeline_config.json` |
| `AQA_REPO_URL` | — | `repository.aqaRepoUrl` in `adoptium_pipeline_config.json` |
| `VARIANT` | — | `defaultVariant` in `adoptium_pipeline_config.json` |
| Platform build/configure args | variant key in per-version JSON | `default` key in per-version JSON |

If a required field cannot be resolved from either source, the pipeline fails early with a clear error message.

---

## Use Cases

### Adoptium official builds

- Config repo: `github.com/adoptium/ci-temurin-config` (public)
- Pipeline code: `github.com/adoptium/ci-adoptium-pipelines` (public)
- Job parameter: `CONFIG_REPO_URL=https://github.com/adoptium/ci-temurin-config.git`

### Vendor-specific builds

- Config repo: `github.com/acme-corp/openjdk-configs` (private)
- Pipeline code: `github.com/adoptium/ci-adoptium-pipelines` (public, unmodified)
- Job parameter: `CONFIG_REPO_URL=https://github.com/acme-corp/openjdk-configs.git`
- Jenkins credential configured to access the private repo

### Testing a config change

Point the job at a feature branch of the config repo:

```
CONFIG_REPO_URL:    https://github.com/adoptium/ci-temurin-config.git
CONFIG_REPO_BRANCH: feature/jdk25-platforms
```

### Local development

```bash
# From the ci-adoptium-pipelines root
python3 ci/local/run-pipeline.py \
  --jdk-version jdk21u \
  --target-os mac \
  --architecture aarch64 \
  --config-repo-url https://github.com/adoptium/ci-temurin-config.git

# Or with a local config repo checkout
python3 ci/local/run-pipeline.py \
  --jdk-version jdk21u \
  --target-os linux \
  --architecture x64 \
  --config-repo-url /path/to/local/ci-temurin-config
```

---

## Security Considerations

`ci-adoptium-pipelines` is a public repository and must **never** contain:
- Credentials, API keys, or tokens
- Internal URLs or endpoints
- Vendor-specific or proprietary settings

Sensitive settings belong in the config repo:
- Use a **private** config repo for internal URLs, signing config, etc.
- Store actual secrets in Jenkins credentials, not in JSON files — reference them by credential ID from `jenkins_job_config.json` or pipeline parameters.

---

## Troubleshooting

### Configuration file not found

**Error**: `Configuration file not found: configurations/jdk21u_pipeline_config.json`

1. Check that `CONFIG_REPO_URL` / `CONFIG_REPO_BRANCH` point to the right repo and branch.
2. Verify the file exists in the config repo under `configurations/`.
3. Confirm the filename matches the pattern set by `configFilePrefix` + `<version>` + `configFileSuffix` in `adoptium_pipeline_config.json`.

### Platform key not found

**Error**: `Platform 'aarch64_mac' not found in configuration`

1. List available keys: `jq '.buildConfigurations | keys' configurations/jdkNN_pipeline_config.json`
2. Verify the platform key uses the aqa-aligned `{arch}_{os}` format (e.g. `x86-64_linux`, not `x64Linux`).
3. Add the missing platform entry to the config file.

### Variant-specific value falls back unexpectedly

`load-json-config.py` logs a warning and falls back to `"default"` when the active variant key is absent from a variant-specific object. Add the missing key or set a `"default"` entry.

### Mixed string/object format error

Each field must consistently use either a plain string or a variant-keyed object across all platform entries. Mixing formats for the same field in different platform entries is not supported.

---

## Related Documentation

- [CI_AGNOSTIC_ARCHITECTURE.md](CI_AGNOSTIC_ARCHITECTURE.md) — overall architecture overview, artifact flow, per-stage summary
- [LABEL_SCHEMA.md](LABEL_SCHEMA.md) — node label schema reference and platform-to-label mapping
- [JOB_DSL_AUTOMATION.md](JOB_DSL_AUTOMATION.md) — seed job and job creation
