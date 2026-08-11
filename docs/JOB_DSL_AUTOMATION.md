# Job DSL Automation

This document describes how Jenkins pipeline jobs are created and updated using Job DSL scripts that read configuration from a vendor-specific configuration repository.

## Overview

All Jenkins pipeline jobs are defined as code using Job DSL scripts. A seed **Pipeline** job reads these scripts and creates/updates all launch and platform build jobs automatically. This ensures jobs are reproducible and version-controlled.

**Key points**:
- The seed job is a Jenkins **Pipeline** job using "Pipeline from SCM" — it points at a `Jenkinsfile.seed` that the vendor places in their config repo.
- A template `Jenkinsfile.seed` is provided at [`ci/jenkins/Jenkinsfile.seed`](../ci/jenkins/Jenkinsfile.seed) — copy it into your config repo and adjust as needed.
- Credentials for both repositories are managed entirely by the Jenkins Credentials store — nothing is placed on agents manually.
- The seed job does **not** regenerate itself. It is a permanent, manually configured Pipeline job.

## Prerequisites

See [JENKINS_REQUIREMENTS.md](./JENKINS_REQUIREMENTS.md) for the full list of
mandatory Jenkins instance requirements (plugins, node labels, timeout behaviour).

In summary, your Jenkins instance must have:

1. **Job DSL Plugin** installed and configured
2. **Pipeline Plugin** installed
3. **Git Plugin** installed
4. **Workspace Cleanup Plugin** (`ws-cleanup`) installed
5. **Build Timeout Plugin** (`build-timeout`) installed
6. **Script Security** configured to allow Job DSL scripts
7. At least one agent labelled **`ci.role.worker`** online
8. Access to:
   - `https://github.com/adoptium/ci-adoptium-pipelines.git` (pipeline code)
   - Your vendor-specific configuration repository

## Architecture

```
openjdk-build-seed-job  (Pipeline job — Pipeline from SCM → config repo Jenkinsfile.seed)
  │
  ├─ Pipeline SCM checkout: vendor config repo → workspace root
  │    vendor-scripts/*.params.json visible at workspace root
  │
  ├─ stage('Checkout pipeline repo')
  │    git checkout ci-adoptium-pipelines → pipelines/
  │
  └─ stage('Generate jobs')  [jobDsl step]
       pipelines/ci/jenkins/job-dsl/seed/seed_job_dsl.groovy
         reads adoptium_pipeline_config.json   (active JDK versions, repo URLs)
         reads jenkins_job_config.json         (log rotation, default params)
         reads pipelines/scripts/stages/       (default stage params)
         reads vendor-scripts/                 (vendor stage param overrides)
         creates Build_openjdk_launchers/ folder + one launch job per JDK version
         creates Build_openjdk/ folder + Jenkins views

Build_openjdk_launchers/Build_openjdk21_launch  (Pipeline — Jenkinsfile.launch)
  stage('Initialize'):
    compares params._GENERATED_PIPELINE_SHA (baked in by seed) vs env.GIT_COMMIT
    → fails immediately with instructions if they differ (job is stale — re-run seed)
  reads configurations/jdk21_pipeline_config.json  (available platforms)
  stage('Create/Update Platform Jobs') — runs on every launch:
    jobDsl → openjdk_build_pipeline_job_dsl.groovy  (per platform)
      checks Jenkins.instance for existing job + stored pipeline-sha
      skips if job exists and pipeline-sha matches current GIT_COMMIT
      otherwise creates/updates Build_openjdk/Build_openjdk21_temurin_x86-64_linux  etc.
  triggers all selected platform builds in parallel
```

## Setup Instructions

### Step 1: Copy the Jenkinsfile.seed template into your config repo

Copy [`ci/jenkins/Jenkinsfile.seed`](../ci/jenkins/Jenkinsfile.seed)
from this repo into the **root of your vendor config repository** (or any path you prefer):

```
<your-config-repo>/
  Jenkinsfile.seed          ← copied from this template
  adoptium_pipeline_config.json
  jenkins_job_config.json
  vendor-scripts/
    02-build.params.json
    ...
```

Open the file and adjust the two constants at the top if needed:

```groovy
def PIPELINES_REPO_URL    = 'https://github.com/adoptium/ci-adoptium-pipelines.git'
def PIPELINES_REPO_BRANCH = 'main'
```

For a fork or a pinned branch, change these values. Commit and push.

### Step 2: Create the Pipeline seed job in Jenkins

1. In Jenkins, create a new **Pipeline** job named `openjdk-build-seed-job`

2. **Add Parameters** — click *This project is parameterized* and add two String Parameters **in the Jenkins job configuration UI**:

   | Name | Default | Description |
   |---|---|---|
   | `CONFIG_REPO_URL` | *(your config repo URL)* | URL of your vendor config repository — **REQUIRED** |
   | `CONFIG_REPO_BRANCH` | `main` | Branch of your vendor config repository |

   > **Important**: do not declare these in `Jenkinsfile.seed`. A `parameters {}` block in a Jenkinsfile causes Jenkins to reset values to the Jenkinsfile defaults on every run, wiping whatever the operator set.

   These values are baked into every generated launch job so `Jenkinsfile.launch` can check out the config repo at runtime on each build agent.

3. Under **Pipeline**:
   - **Definition**: `Pipeline script from SCM`
   - **SCM**: Git
   - **Repository URL**: your vendor config repo URL
   - **Credentials**: select a Jenkins-managed credential if the repo is private
   - **Branch Specifier**: your config repo branch (e.g. `main`)
   - **Script Path**: `Jenkinsfile.seed` *(or the path you chose in Step 1)*

4. Save the job.

> **Note**: The Pipeline SCM step checks out the vendor config repo to the workspace
> root, so `adoptium_pipeline_config.json`, `jenkins_job_config.json`,
> `configurations/`, and `vendor-scripts/` are all immediately available to the Job
> DSL script without any additional checkout steps. Credentials are handled natively
> by the Git plugin using the Jenkins Credentials store.

### Step 3: Run the seed job

1. Click **Build with Parameters**
2. Set `CONFIG_REPO_URL` to your config repo URL (e.g. `https://github.com/adoptium/ci-temurin-config.git`)
3. Set `CONFIG_REPO_BRANCH` to your branch (e.g. `main`)
4. Click **Build**

The job will:
- Check out `ci-adoptium-pipelines` into `pipelines/`
- Collate stage parameters from `pipelines/scripts/stages/` and `vendor-scripts/`
- Read `adoptium_pipeline_config.json` and `jenkins_job_config.json` from the config repo
- Create the `Build_openjdk_launchers/` and `Build_openjdk/` folders
- Create one launch job per enabled JDK version under `Build_openjdk_launchers/`
- Create `Build_openjdk_launchers` and `Build_openjdk` Jenkins views

### Step 4: Create Platform Build Jobs

Simply run a launch job (e.g. `Build_openjdk_launchers/Build_openjdk21_launch`).
Platform jobs are created automatically — no extra flag is needed.

Each launch run performs two SHA-based staleness checks:

**1. Launch job self-check (Initialize stage)**
The seed job stamps its `ci-adoptium-pipelines` checkout SHA into each launch
job's description as `pipeline-sha:<sha>`. At the start of every run the launch
job reads that value via `currentBuild.rawBuild.parent.getDescription()` and
compares it against `env.GIT_COMMIT` — the SHA Jenkins actually checked out to
execute `Jenkinsfile.launch`. If they differ the build fails immediately with a
clear message:

```
This launch job is out of date.
  Job generated from : <old-sha>
  Current SCM SHA    : <new-sha>

The ci-adoptium-pipelines commit has changed since this job was last generated.
Re-run the seed job (openjdk-build-seed-job) to regenerate it, then retry this build.
```

**2. Platform job check (Create/Update Platform Jobs stage)**
On every launch run the `'Create/Update Platform Jobs'` stage compares the
`pipeline-sha` stored in each platform job's description against the SHA of the
`ci-adoptium-pipelines` commit that the launch job checked out (`GIT_COMMIT`).
If they differ, or the job does not yet exist, the job is regenerated. If they
match the job is left untouched and the stage moves on immediately.

Platform jobs created this way will look like:
- `Build_openjdk/Build_openjdk21_temurin_x86-64_linux`
- `Build_openjdk/Build_openjdk21_temurin_aarch64_mac`

## Configuration

### Active JDK Versions

Active versions are defined in `adoptium_pipeline_config.json` in the config repo:

```json
{
  "activeJdkVersions": [
    { "version": "jdk21", "enabled": true },
    { "version": "jdk17", "enabled": true },
    { "version": "jdk11", "enabled": false }
  ],
  "configFilePrefix": "configurations/",
  "configFileSuffix": "_pipeline_config.json"
}
```

The seed reads enabled entries and creates one launch job per version.

### Stage Parameters

Stage parameters are collated at seed-job time from two sources:

1. **Default params** — `pipelines/scripts/stages/*.params.json` (from `ci-adoptium-pipelines`)
2. **Vendor overrides** — `vendor-scripts/*.params.json` (from the vendor config repo, checked out to workspace root by the Pipeline SCM step)

Vendor files can add new parameters, replace defaults, or suppress defaults via `ignoreDefaultParams`.
The collated set is baked into every launch job and platform build job, with a hidden
`STAGE_PARAM_NAMES` meta-parameter that `Jenkinsfile.launch` uses to forward all stage
params to platform builds automatically.

### Job Parameters

Default parameter values come from `jenkins_job_config.json` in the config repo:

```json
{
  "pipelineTimeoutHours": 8,
  "jobConfiguration": {
    "defaultParameters": {
      "RUN_TESTS": false,
      "ENABLE_INSTALLERS": true,
      "SIGN_ARTIFACTS": false,
      "PUBLISH_ARTIFACTS": false,
      "RUN_REPRODUCIBLE_COMPARE": false,
      "CLEAN_WORKSPACE_AFTER_STAGE": true
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

## Maintenance

### Re-running the Seed Job

Run the seed job any time to pick up changes to:
- Active JDK versions (`adoptium_pipeline_config.json`)
- Default parameters or log rotation (`jenkins_job_config.json`)
- Stage parameter definitions (`scripts/stages/*.params.json` or `vendor-scripts/*.params.json`)
- Job DSL script changes (`ci/jenkins/job-dsl/`)

The config repo is re-checked out by the Pipeline SCM step; `pipelines/` (ci-adoptium-pipelines) is re-checked out by the explicit `git` step in `Jenkinsfile.seed`.

### Adding/Removing JDK Versions

1. Edit `adoptium_pipeline_config.json` in the config repo — set `"enabled": false` or add a new entry
2. Commit and push
3. Re-run the seed job

### Updating Platform Jobs

1. Edit `jenkins_job_config.json` in the config repo or the Job DSL scripts
2. Commit and push
3. Re-run the seed job

Platform build jobs are automatically regenerated on the next launch run — the
launch job detects that the `pipeline-sha` stored in each job's description no
longer matches the current `ci-adoptium-pipelines` checkout and recreates it.
No manual flag is required.

> **Note**: if `ci-adoptium-pipelines` has changed the launch job itself will
> fail in the `Initialize` stage before reaching `'Create/Update Platform Jobs'`.
> Re-run the seed job first, then re-run the launch job.

### Updating Pipeline Code

Changes to `Jenkinsfile` files or stage scripts in `ci-adoptium-pipelines` take effect on the next platform build run — no seed job run needed.

### Pinning to a specific pipeline repo version

Edit the constants in your `Jenkinsfile.seed`:

```groovy
def PIPELINES_REPO_URL    = 'https://github.com/adoptium/ci-adoptium-pipelines.git'
def PIPELINES_REPO_BRANCH = 'v2.1.0'   // pin to a tag or branch
```

Commit and push, then re-run the seed job.

## Troubleshooting

### Seed Job Fails with "CONFIG_REPO_URL is required"

**Cause**: Seed job run without parameters.

**Fix**: Use **Build with Parameters** and supply `CONFIG_REPO_URL` and `CONFIG_REPO_BRANCH`.

### Seed Job Fails with "vendor-scripts/ not found"

**Cause**: The `vendor-scripts/` directory does not exist in the workspace root.

**Fix**: Verify that your config repo contains a `vendor-scripts/` directory. The Pipeline SCM step checks out the config repo to the workspace root — if `vendor-scripts/` is missing from the repo, create it and add at least a placeholder `*.params.json` file (can be one with empty `parameterGroups`).

### Seed Job Fails with "adoptium_pipeline_config.json / jenkins_job_config.json not found"

**Cause**: One of the required JSON files is missing from the vendor config repo root.

**Fix**: Verify that both `adoptium_pipeline_config.json` and `jenkins_job_config.json` exist at the root of the config repo.

### Seed Job Fails with "Script Security"

**Cause**: Jenkins Script Security is blocking Job DSL operations.

**Fix**: Go to **Manage Jenkins → In-process Script Approval** and approve the required signatures.

### Launch Job Doesn't Show All Platforms

**Cause**: The `PLATFORMS` choice parameter is populated at seed-job time. Platforms added to the config after the last seed run will not appear.

**Fix**: Re-run the seed job.

### Launch Job Fails in Initialize — "This launch job is out of date"

**Cause**: The `ci-adoptium-pipelines` SCM branch has moved to a new commit
since the seed job last generated this launch job. The `pipeline-sha` stamped
in the job's description no longer matches `GIT_COMMIT`.

**Fix**: Re-run the seed job (`openjdk-build-seed-job`). It will regenerate the
launch job with the new SHA. Then retry the launch build.

### Launch Job Fails in Initialize — script approval required

**Cause**: `currentBuild.rawBuild.parent.getDescription()` is blocked by the
Jenkins Script Security sandbox on first use.

**Fix**: Go to **Manage Jenkins → In-process Script Approval** and approve:
```
method hudson.model.AbstractItem getDescription
```
This is a one-time, read-only approval scoped to the current job's own metadata.

### Platform Jobs Not Created / Out of Date

**Cause**: The platform job does not yet exist, or it was generated from a
different `ci-adoptium-pipelines` commit than the one the launch job has
checked out.

**Fix**: Simply run (or re-run) the launch job. The `'Create/Update Platform
Jobs'` stage automatically detects the mismatch via the `pipeline-sha` tag
embedded in each job's description and regenerates any job that is missing or
out of date.

## Related Documentation

- [`ci/jenkins/Jenkinsfile.seed`](../ci/jenkins/Jenkinsfile.seed) — template seed Jenkinsfile to copy into your config repo
- [BUILD_JOB_NAMING_CONVENTION.md](./BUILD_JOB_NAMING_CONVENTION.md) — Job naming schema and folder layout
- [BUILD_UID Integration](BUILD_UID_INTEGRATION.md) — Pipeline restart safety
- [ci/jenkins/README.md](../ci/jenkins/README.md) — Jenkins integration overview
- [CODE_CONFIG_SEPARATION.md](./CODE_CONFIG_SEPARATION.md) — Config repo JSON reference
