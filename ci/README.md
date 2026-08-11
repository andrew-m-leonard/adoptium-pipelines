# CI Integration Directory

This directory contains CI-platform-specific orchestration files. All build _logic_ lives in `../scripts/` as portable shell scripts; the files here are thin wrappers that call those scripts from a given CI platform.

## Directory Structure

```
ci/
├── jenkins/
│   ├── Jenkinsfile.declarative          # Single-platform build pipeline
│   ├── Jenkinsfile.launch               # Multi-platform launch pipeline
│   ├── lib/
│   │   ├── BuildUidHelper.groovy
│   │   ├── ConfigHelper.groovy
│   │   ├── PipelineHelper.groovy
│   │   └── StageScriptRunner.groovy
│   └── job-dsl/
│       ├── openjdk_build_pipeline_job_dsl.groovy
│       └── seed/
│           └── seed_job_dsl.groovy
├── local/
│   ├── run-pipeline.py
│   ├── stage_resolver.py
│   └── workspace_manager.py
└── README.md  (this file)
```

## jenkins/

Jenkins-specific pipeline definitions and job automation.

### Jenkinsfile.declarative

Single-platform build pipeline. Loaded by every `jdk${version}-${platform}-build-pipeline` job created by the seed job. Orchestrates all pipeline stages from Initialize through Publish, loading shared helpers from `lib/` after the initial SCM checkout.

**Script path** (in Jenkins job config): `ci/jenkins/Jenkinsfile.declarative`

### Jenkinsfile.launch

Multi-platform launch pipeline. Loaded by `jdk${version}-launch-build-pipelines` jobs. Reads the config repo, determines which platforms to build, optionally regenerates platform build jobs via Job DSL, then triggers all selected platform builds in parallel.

**Script path**: `ci/jenkins/Jenkinsfile.launch`

### lib/

Shared Groovy helpers loaded at runtime with `load()`. Each file is a plain CPS script — pipeline steps (`echo`, `sh`, `env`, `params`, `currentBuild`, etc.) are called directly without any delegation wrapper.

| File | Role |
|---|---|
| `BuildUidHelper.groovy` | `BUILD_UID` / `GROUP_UID` generation and reuse; `BUILD_STAGE_RESULTS` serialisation; prerequisite validation |
| `PipelineHelper.groovy` | `initializeStage()`, `finalizeStage()`, `executeStageWithTracking()`, `ensureBuildDescriptionSet()` |
| `ConfigHelper.groovy` | Generates `pipeline-config.json` by calling `load-json-config.py`; sets `CONFIG_*` env vars |
| `StageScriptRunner.groovy` | Resolves and executes per-stage scripts with vendor-override support |

### job-dsl/

Job DSL scripts that create and maintain all Jenkins jobs from code.

| File | Role |
|---|---|
| `seed/seed_job_dsl.groovy` | Bootstrap — run once to create all launch and platform jobs |
| `openjdk_build_pipeline_job_dsl.groovy` | Called by the launch pipeline to create/update one platform build job |

See [docs/JOB_DSL_AUTOMATION.md](../docs/JOB_DSL_AUTOMATION.md) for setup instructions.

## local/

Python-based tools for running the pipeline locally without a CI server.

```bash
python3 ci/local/run-pipeline.py \
  --jdk-version jdk21u \
  --variant temurin \
  --target-os linux \
  --architecture x64
```

See [`local/README.md`](local/README.md) for full usage.

## Adding a New CI Platform

1. Create `ci/<platform-name>/`
2. Add a pipeline definition that calls the same `scripts/stages/` shell scripts
3. Pass the same environment variables documented in [docs/STAGE_IO_SPECIFICATION.md](../docs/STAGE_IO_SPECIFICATION.md)
4. Update this README

## Related Documentation

- [docs/CI_AGNOSTIC_ARCHITECTURE.md](../docs/CI_AGNOSTIC_ARCHITECTURE.md) — 3-layer architecture overview
- [docs/JOB_DSL_AUTOMATION.md](../docs/JOB_DSL_AUTOMATION.md) — Jenkins job creation guide
- [docs/BUILD_UID_INTEGRATION.md](../docs/BUILD_UID_INTEGRATION.md) — BUILD_UID tracking
- [docs/STAGE_IO_SPECIFICATION.md](../docs/STAGE_IO_SPECIFICATION.md) — Stage input/output contracts
