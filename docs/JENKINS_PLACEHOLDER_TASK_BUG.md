# Jenkins PlaceholderTask Stale Entry Bug

**Upstream issue:** [jenkinsci/workflow-durable-task-step-plugin #579](https://github.com/jenkinsci/workflow-durable-task-step-plugin/issues/579)
(tracked upstream as JENKINS-60507)

---

## Symptom

A pipeline build reaches a `node()` / `agent { label '...' }` block, enters the Jenkins queue,
and immediately prints:

```
Still waiting to schedule task
Stopping part of <folder> » <job-name> #N - <build description>
```

The build then hangs **permanently**. The target node is online and has free executors. Waiting
longer does not help — the `AnomalousStatus` background task (which normally clears stuck queue
items after ~30 minutes) does **not** resolve this because the item appears legitimately blocked,
not anomalous.

---

## Root cause

`ExecutorStepExecution` maintains a static in-memory registry called `RunningTasks` — a
`Map<StepContext, RunningTask>` keyed by `CpsStepContext`. The key encodes:

- the Jenkins job's full name
- the build number
- the CPS step counter (position of the `node()` call in the pipeline graph)

When a build is **aborted while its `PlaceholderTask` is in the queue** (i.e. a `node()` step
has been reached but no executor has been allocated yet), `ExecutorStepExecution.stop()` sets
`stopping = true` on the `RunningTask` entry and attempts to cancel the queue item. Under certain
conditions — not fully characterised upstream, but consistently observed when abort happens
immediately after the task is queued — **the entry is not removed from `RunningTasks`** after
cancellation.

The stale entry sits in memory indefinitely. When the **same job is subsequently recreated** (e.g.
by a Job DSL `removedJobAction: DELETE` followed by re-generation), the build number resets to
`#1` and the CPS step counter resets to its original value. The new build's `PlaceholderTask` is
constructed with an **identical `CpsStepContext` key**. It finds the stale entry in `RunningTasks`,
inherits `stopping = true` the moment it is created, and immediately reports:

```
"Stopping part of <job> #1"
```

as its `CauseOfBlockage`. It can never be dispatched to an executor. The build hangs forever.

---

## When this occurs in this pipeline

The build jobs (`Build_openjdk<N>_<variant>_<arch>_<os>`) are created on-demand by
[`openjdk_build_pipeline_job_dsl.groovy`](../ci/jenkins/job-dsl/openjdk_build_pipeline_job_dsl.groovy)
from within the launch job's `Create/Update Platform Jobs` stage.

### Normal re-generation (low risk)

When the pipeline repo SHA changes (e.g. a new commit is pushed to `jenkins-creds`), the DSL
detects a SHA mismatch and **updates the existing job in place** — it calls `pipelineJob()` on a
job that already exists. Jenkins updates the job configuration but **preserves the build history
and the build number sequence**. In this case the next build is `#2`, `#3`, etc. — not `#1` —
so even if a stale `RunningTasks` entry exists for an old `#1` run, the key never matches and
the bug is not triggered.

### Folder deletion followed by re-generation (high risk)

The bug is reliably triggered when the **entire deployment folder is deleted manually** (e.g.
deleting `andrew-pipeline-sandbox/beta` from the Jenkins UI) and then the jobs are regenerated.
Deleting the folder destroys the job objects and their build history entirely. When the DSL next
runs and recreates the jobs, they start from **build `#1`**. If a stale `RunningTasks` entry
exists for any of these jobs at step counter `132` (the `node()` call inside `withBuildAgent`),
the new `#1` build hits it immediately and hangs.

This is the most common way to encounter this bug in practice:

1. You delete a deployment folder to do a clean reset during development/testing.
2. Some of the deleted jobs had been aborted mid-queue in a prior run, leaving stale entries.
3. You regenerate the jobs — they all start at `#1`.
4. The first trigger run hits the stale entries and every platform build hangs.

The same outcome occurs if you delete individual build jobs manually rather than the whole folder.

---

## Diagnosis

Run the following in **Manage Jenkins → Script Console** to inspect `RunningTasks`:

```groovy
import org.jenkinsci.plugins.workflow.support.steps.ExecutorStepExecution
import jenkins.model.Jenkins

def holder = Jenkins.get().getExtensionList(ExecutorStepExecution.RunningTasks.class)[0]

synchronized (holder) {
    def field = ExecutorStepExecution.RunningTasks.getDeclaredField('runningTasks')
    field.setAccessible(true)
    def map = field.get(holder)
    println "Total entries: ${map.size()}"
    map.each { ctx, task ->
        println "  context : ${ctx}"
        println "  stopping: ${task.stopping}"
        println()
    }
}
```

Stale entries appear as `stopping: true`. Entries with `stopping: false` are legitimately
running builds — **do not remove them**.

---

## Fix (immediate — no restart required)

### Option A — remove only entries for a specific folder prefix

Use this when you know the affected folder and want to avoid touching anything else on the
controller:

```groovy
import org.jenkinsci.plugins.workflow.support.steps.ExecutorStepExecution
import jenkins.model.Jenkins

// Edit this to match the Jenkins folder prefix of your stuck jobs, e.g.:
//   'andrew-pipeline-sandbox'   — all sandbox build jobs
//   'andrew-pipeline-sandbox/beta'  — only the beta deployment
def folderPrefix = 'andrew-pipeline-sandbox'

def holder = Jenkins.get().getExtensionList(ExecutorStepExecution.RunningTasks.class)[0]

synchronized (holder) {
    def field = ExecutorStepExecution.RunningTasks.getDeclaredField('runningTasks')
    field.setAccessible(true)
    def map = field.get(holder)
    def before = map.size()
    def toRemove = map.findAll { ctx, task ->
        task.stopping && ctx.toString().contains(folderPrefix)
    }.keySet()
    toRemove.each { ctx ->
        map.remove(ctx)
        println "Removed: ${ctx}"
    }
    println "\nDone. Removed ${toRemove.size()} of ${before} entries. Remaining: ${map.size()}"
}
```

### Option B — remove all `stopping=true` entries across the controller

Use this only if you are confident **no other builds are legitimately being stopped** at the
moment you run the script (i.e. no other pipelines are mid-abort):

```groovy
import org.jenkinsci.plugins.workflow.support.steps.ExecutorStepExecution
import jenkins.model.Jenkins

def holder = Jenkins.get().getExtensionList(ExecutorStepExecution.RunningTasks.class)[0]

synchronized (holder) {
    def field = ExecutorStepExecution.RunningTasks.getDeclaredField('runningTasks')
    field.setAccessible(true)
    def map = field.get(holder)
    def before = map.size()
    def toRemove = map.findAll { ctx, task -> task.stopping }.keySet()
    toRemove.each { ctx ->
        map.remove(ctx)
        println "Removed: ${ctx}"
    }
    println "\nDone. Removed ${toRemove.size()} of ${before} entries. Remaining: ${map.size()}"
}
```

After running either script:

1. If the stuck build is still showing as running, **abort it manually** from the Jenkins UI.
2. Re-trigger the build normally — it will now schedule successfully.

---

## Notes

- **No Jenkins restart is required.** The fix takes effect immediately in-memory.
- **Entries with `stopping: false` must not be removed** — those are active running tasks and
  removing them would corrupt the state of live builds.
- The `AnomalousStatus` background task (runs every 5 minutes, waits up to 30 minutes before
  acting) does **not** resolve this condition. A blocked item is not classified as anomalous.
- This bug affects all Jenkins versions as of the time of writing. It is tracked upstream at
  [workflow-durable-task-step-plugin #579](https://github.com/jenkinsci/workflow-durable-task-step-plugin/issues/579).
  Monitor that issue for a permanent fix in the plugin.
- The condition is most reliably triggered by aborting a build **while its `node()` task is
  queued but before an executor is allocated**, then deleting and recreating the job (resetting
  the build number). It can also occur without job recreation in some race conditions during
  controller-side processing of the abort.
