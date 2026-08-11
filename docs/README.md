# CI Adoptium Pipelines — Documentation

This directory contains reference documentation for the Adoptium CI pipeline infrastructure.

## Quick Navigation

### I want to...

| Goal | Start here |
|---|---|
| Set up Jenkins from scratch | [JOB_DSL_AUTOMATION.md](./JOB_DSL_AUTOMATION.md) |
| Check Jenkins instance requirements | [JENKINS_REQUIREMENTS.md](./JENKINS_REQUIREMENTS.md) |
| Understand the job naming convention | [BUILD_JOB_NAMING_CONVENTION.md](./BUILD_JOB_NAMING_CONVENTION.md) |
| Understand the overall design | [CI_AGNOSTIC_ARCHITECTURE.md](./CI_AGNOSTIC_ARCHITECTURE.md) |
| Configure a build | [CODE_CONFIG_SEPARATION.md](./CODE_CONFIG_SEPARATION.md) |
| Look up a config file schema | [CONFIG_SCHEMA.md](./CONFIG_SCHEMA.md) |
| Restart a failed stage | [BUILD_UID_INTEGRATION.md](./BUILD_UID_INTEGRATION.md) |
| Run the pipeline locally | [PIPELINE_RUNNER_GUIDE.md](./PIPELINE_RUNNER_GUIDE.md) |
| Add or modify a stage script | [CI_AGNOSTIC_ARCHITECTURE.md](./CI_AGNOSTIC_ARCHITECTURE.md) (Per-Stage Summary) + [UNIVERSAL_STAGE_PATTERN.md](./UNIVERSAL_STAGE_PATTERN.md) |
| Understand BUILD_UID tracking | [BUILD_UID_INTEGRATION.md](./BUILD_UID_INTEGRATION.md) |
| Work with reproducible builds | [REPRO_COMPARE_INTEGRATION.md](./REPRO_COMPARE_INTEGRATION.md) |
| Convert legacy Groovy configs | [`tools/README.md`](../tools/README.md) |

---

## Architecture & Design

- **[CI_AGNOSTIC_ARCHITECTURE.md](./CI_AGNOSTIC_ARCHITECTURE.md)** — 3-layer design (Configuration / Shell Scripts / CI Orchestration), standard interface contract, per-stage summary
- **[UNIVERSAL_STAGE_PATTERN.md](./UNIVERSAL_STAGE_PATTERN.md)** — How to write a new stage script following the standard pattern

## Configuration

- **[CONFIG_SCHEMA.md](./CONFIG_SCHEMA.md)** — Full schema reference for `adoptium_pipeline_config.json`, `jenkins_job_config.json`, and `configurations/jdkNN_pipeline_config.json`
- **[LABEL_SCHEMA.md](./LABEL_SCHEMA.md)** — Jenkins node label schema reference: `ci.role.*`, `sw.os.*`, `hw.arch.*`, `sw.tool.*` conventions; platform key mapping; `additionalNodeLabels` migration rules
- **[CODE_CONFIG_SEPARATION.md](./CODE_CONFIG_SEPARATION.md)** — Config repo layout, vendor-scripts resolution, config flow through the pipeline

## Jenkins Integration

- **[JENKINS_REQUIREMENTS.md](./JENKINS_REQUIREMENTS.md)** — Mandatory Jenkins instance requirements: required plugins, node label requirements (including `ci.role.worker`), and timeout behaviour
- **[BUILD_JOB_NAMING_CONVENTION.md](./BUILD_JOB_NAMING_CONVENTION.md)** — Job naming schema (`Build_openjdk<version>_<distro>_<arch>_<os>`), folder layout, and AQA convention alignment
- **[JOB_DSL_AUTOMATION.md](./JOB_DSL_AUTOMATION.md)** — Complete seed job and Job DSL setup guide; how launch jobs and platform build jobs are created
- **[BUILD_UID_INTEGRATION.md](./BUILD_UID_INTEGRATION.md)** — `BUILD_UID` and `GROUP_UID` lifecycle; `BUILD_STAGE_RESULTS` serialisation; prerequisite validation

## Workspace Management

- **[WORKSPACE_ARTIFACTS_ARCHITECTURE.md](./WORKSPACE_ARTIFACTS_ARCHITECTURE.md)** — Three-directory layout (`stage_workspace/`, `build_artifacts/`, `config-repo/`); Jenkins vs local archive/restore semantics; validation rules; CLI usage and error messages

## Stage Implementation Details

- **[SHELL_SCRIPTS_SUMMARY.md](./SHELL_SCRIPTS_SUMMARY.md)** — Index of all `scripts/stages/` and `scripts/lib/` files; STUB vs REAL status; key functions and I/O contract per stage; vendor override resolution order
- **[STAGE_DEFINITION_REFERENCE.md](./STAGE_DEFINITION_REFERENCE.md)** — Authoritative reference for the four artefacts that define every stage; how to add, modify, disable, and enable stages

## Pipeline Features

- **[REPRO_COMPARE_INTEGRATION.md](./REPRO_COMPARE_INTEGRATION.md)** — Integration details: `REPRODUCIBLE_COMPARE_BUILD` parameter, `SCM_REF` requirement, `TARGET_DIR` outputs

## Local Execution

- **[PIPELINE_RUNNER_GUIDE.md](./PIPELINE_RUNNER_GUIDE.md)** — `ci/local/run-pipeline.py` full reference: arguments, stage names, workspace layout, examples

## Tools

- **[Tools README](../tools/README.md)** — Legacy Groovy-to-JSON configuration conversion tools: `migrate-groovy-pipeline-configs.py`, `batch-convert-groovy-configs.py`, `groovy-pipeline-config-to-json.py`

## Historical

These documents capture decisions, refactoring work, and intermediate designs from the original pipeline implementation. Retained for reference in [`docs/archived/`](./archived/).

- [ARTIFACT_DIRECTORY_PATTERN.md](./archived/ARTIFACT_DIRECTORY_PATTERN.md) — `INPUT_ARTIFACTS_DIR` vs `TARGET_DIR` pattern (superseded by [`WORKSPACE_ARTIFACTS_ARCHITECTURE.md`](./WORKSPACE_ARTIFACTS_ARCHITECTURE.md))
- [LOCAL_RUNNER_WORKSPACE_ARCHITECTURE.md](./archived/LOCAL_RUNNER_WORKSPACE_ARCHITECTURE.md) — Local runner workspace architecture (superseded by [`WORKSPACE_ARTIFACTS_ARCHITECTURE.md`](./WORKSPACE_ARTIFACTS_ARCHITECTURE.md))
- [PIPELINE_ORCHESTRATION_ARCHITECTURE.md](./archived/PIPELINE_ORCHESTRATION_ARCHITECTURE.md) — Launch pipeline → build pipeline → stage script flow
- [CONFIGURATION_GUIDE.md](./archived/CONFIGURATION_GUIDE.md) — Configuration system guide (superseded by [`CODE_CONFIG_SEPARATION.md`](./CODE_CONFIG_SEPARATION.md))
- [STAGE_IO_SPECIFICATION.md](./archived/STAGE_IO_SPECIFICATION.md) — Per-stage input/output contracts (superseded by [`CI_AGNOSTIC_ARCHITECTURE.md`](./CI_AGNOSTIC_ARCHITECTURE.md) Standard Interface Contract section)
- [JENKINS_ENVIRONMENT_VARIABLES.md](./archived/JENKINS_ENVIRONMENT_VARIABLES.md) — `CONFIG_*` and pipeline env vars (superseded by [`ci/jenkins/README.md`](../ci/jenkins/README.md) parameters table)
- [PARAMETER_CONSOLIDATION.md](./archived/PARAMETER_CONSOLIDATION.md) — How job parameters were consolidated
- [JENKINS_RESTART_BEHAVIOR.md](./archived/JENKINS_RESTART_BEHAVIOR.md) — Restart from Stage mechanics (superseded by [`BUILD_UID_INTEGRATION.md`](./BUILD_UID_INTEGRATION.md))
- [RESTARTABILITY_GUIDE.md](./archived/RESTARTABILITY_GUIDE.md) — Stage restartability design (superseded by [`BUILD_UID_INTEGRATION.md`](./BUILD_UID_INTEGRATION.md))
- [JENKINS_CLEANUP_REFACTORING.md](./archived/JENKINS_CLEANUP_REFACTORING.md) — Refactoring to native `cleanWs()`
- [WORKSPACE_CLEANUP.md](./archived/WORKSPACE_CLEANUP.md) — Earlier workspace cleanup strategy
- [WORKSPACE_VALIDATION_PATTERN.md](./archived/WORKSPACE_VALIDATION_PATTERN.md) — BUILD_UID workspace integrity check design
- [STAGE_INPUT_STRATEGY.md](./archived/STAGE_INPUT_STRATEGY.md) — Earlier vendor-override resolution design
- [TARGET_DIR_ARTIFACT_CONSISTENCY.md](./archived/TARGET_DIR_ARTIFACT_CONSISTENCY.md) — `TARGET_DIR` consistency work
- [REPRODUCIBLE_COMPARE.md](./archived/REPRODUCIBLE_COMPARE.md) — Earlier reproducible compare notes
- [REPRODUCIBLE_BUILD_PATH_PADDING.md](./archived/REPRODUCIBLE_BUILD_PATH_PADDING.md) — Path padding for macOS LC_UUID
- [PATH_PADDING_IMPLEMENTATION_SUMMARY.md](./archived/PATH_PADDING_IMPLEMENTATION_SUMMARY.md) — Path padding quick reference
- [BUILD_MONITORING_TRACEABILITY.md](./archived/BUILD_MONITORING_TRACEABILITY.md) — BUILD_UID / GROUP_UID traceability design
- [MIGRATION_PLAN.md](./archived/MIGRATION_PLAN.md) — Original phased migration strategy
- [MIGRATION_STRATEGY.md](./archived/MIGRATION_STRATEGY.md) — Design choices and trade-offs
- [MIGRATION_IMPLEMENTATION_GUIDE.md](./archived/MIGRATION_IMPLEMENTATION_GUIDE.md) — Step-by-step migration instructions
- [MIGRATION_VISUAL_GUIDE.md](./archived/MIGRATION_VISUAL_GUIDE.md) — Timeline and flow diagrams
- [GITHUB_EPICS_AND_ISSUES.md](./archived/GITHUB_EPICS_AND_ISSUES.md) — Original GitHub epics and issue tracking
- [PARAMETER_CONSISTENCY_UPDATE.md](./archived/PARAMETER_CONSISTENCY_UPDATE.md) — Parameter naming standardisation history
- [RELEASE_TYPE_PARAMETER_MIGRATION.md](./archived/RELEASE_TYPE_PARAMETER_MIGRATION.md) — `RELEASE_TYPE` parameter history
- [TARGET_DIR_REFACTORING.md](./archived/TARGET_DIR_REFACTORING.md) — `TARGET_DIR` refactoring history
- [STAGE_SCRIPTS.md](./archived/STAGE_SCRIPTS.md) — Pluggable stage script design specification (implemented; superseded by [`SHELL_SCRIPTS_SUMMARY.md`](./SHELL_SCRIPTS_SUMMARY.md) and [`CI_AGNOSTIC_ARCHITECTURE.md`](./CI_AGNOSTIC_ARCHITECTURE.md))

---

See [`../README.md`](../README.md) for the project overview and quick-start.
