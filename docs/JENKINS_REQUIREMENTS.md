# Jenkins Instance Requirements

This document lists the mandatory requirements for any vendor Jenkins instance
running this pipeline.  Meeting these requirements is a prerequisite before
running the seed job or executing any build.

---

## Required Plugins

| Plugin | Purpose |
|---|---|
| **Job DSL** | Generates launch and platform build jobs from Groovy DSL scripts |
| **Pipeline** | Executes `Jenkinsfile.launch` and `Jenkinsfile.declarative` |
| **Git** | Clones `ci-adoptium-pipelines` and the vendor config repo |
| **Workspace Cleanup** (`ws-cleanup`) | `cleanWs()` calls in the pipeline |
| **Build Timeout** (`build-timeout`) | Enforces the `pipelineTimeoutHours` wall-clock limit on platform build jobs |
| **Credentials / Git credentials** | Authenticated repository access |

Script Security must be configured to allow the Job DSL scripts to run.  See
[JOB_DSL_AUTOMATION.md](./JOB_DSL_AUTOMATION.md) for the one-time script approval
step required for `currentBuild.rawBuild.parent.getDescription()`.

---

## Required Node Labels

### `ci.role.worker` — orchestration / utility agents

At least one online agent **must** carry the label `ci.role.worker`.

This label is used by:

- The **Initialize** stage of every platform build pipeline — this stage runs
  before any config has been loaded, so the agent selection falls back directly
  to the hardcoded label `ci.role.worker`.
- The **final workspace cleanup** step that runs after all stages complete.
- The **seed job** itself (unless you configure it to run on `built-in` /
  `controller`; running builds on the controller is not recommended).

> **Important:** `ci.role.worker` is a hard requirement with no configuration
> override for the Initialize stage.  If no agent carrying this label is online
> when the Initialize stage is scheduled, the pipeline will wait up to
> `activeNodeTimeoutMinutes` (default 10 minutes, configurable in
> `jenkins_job_config.json`) before failing.

### Stage-specific labels

All other stages use labels resolved from the `stageAgentLabels` map in
`jenkins_job_config.json`.  A typical platform build requires agents labelled
with a combination of `ci.role.build`, `sw.os.*`, and `hw.arch.*` labels that
match each target platform.

See [LABEL_SCHEMA.md](./LABEL_SCHEMA.md) for the full label schema and
[CONFIG_SCHEMA.md](./CONFIG_SCHEMA.md) for the `stageAgentLabels` configuration
reference.

---

## Timeout Behaviour

The pipeline uses `activeNodeTimeoutMinutes` (from `jenkins_job_config.json`,
default `10`) to wait for at least one matching agent to come online before
failing.  This is distinct from the Jenkins executor queue — it fires only when
**zero** agents carrying the required label are online (e.g. during cloud
provisioner startup).

The `ci.role.worker` agents used by the Initialize stage follow the same
timeout and are subject to the same check.

---

## Summary Checklist

| # | Requirement |
|---|---|
| 1 | Job DSL, Pipeline, Git, Workspace Cleanup, and Credentials plugins installed |
| 2 | Script Security configured (see [JOB_DSL_AUTOMATION.md](./JOB_DSL_AUTOMATION.md)) |
| 3 | At least one agent with label `ci.role.worker` online before running any build |
| 4 | Agents labelled per `stageAgentLabels` in `jenkins_job_config.json` for each target platform |

---

## See Also

- [LABEL_SCHEMA.md](./LABEL_SCHEMA.md) — full node label schema (`ci.role.*`, `sw.os.*`, `hw.arch.*`)
- [JOB_DSL_AUTOMATION.md](./JOB_DSL_AUTOMATION.md) — seed job setup and prerequisites
- [CONFIG_SCHEMA.md](./CONFIG_SCHEMA.md) — `jenkins_job_config.json` schema including `activeNodeTimeoutMinutes` and `stageAgentLabels`
