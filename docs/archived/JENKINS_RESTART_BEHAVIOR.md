# Jenkins Declarative Pipeline Restart Behavior

## The Question

**When you restart a stage in a Jenkins declarative pipeline, does it automatically re-run the following stages?**

## The Answer

**YES** - When you use "Restart from Stage" in Jenkins declarative pipelines, it:
1. Starts from the chosen stage
2. **Automatically runs all following stages** in the pipeline

## How Jenkins "Restart from Stage" Works

### What Actually Happens

When you click "Restart from Stage X" in Jenkins:

1. **Jenkins starts at stage X** - Executes the selected stage
2. **Continues through all subsequent stages** - Automatically runs every stage after X
3. **Skips previous stages** - Stages before X are not re-run

### Example Scenario

Pipeline with 4 stages: Build → Sign → Installer → Test

**Original Run:**
```
Build     ✅ SUCCESS
Sign      ✅ SUCCESS
Installer ❌ FAILED
Test      ⊘ SKIPPED (because Installer failed)
```

**After "Restart from Installer":**
```
Build     ✅ SUCCESS (not re-run, shows previous result)
Sign      ✅ SUCCESS (not re-run, shows previous result)
Installer 🔄 RUNNING (restarted)
Test      ⏳ PENDING (will run after Installer completes)
```

**Final Result:**
```
Build     ✅ SUCCESS (not re-run)
Sign      ✅ SUCCESS (not re-run)
Installer ✅ SUCCESS (just re-ran)
Test      ✅ SUCCESS (automatically ran after Installer)
```

## Why This Matters for Pipeline Design

### 1. Stages Must Still Be Independent

Even though stages run sequentially, each stage must be able to retrieve its inputs from archived artifacts because:

- **Different agents**: Stages might run on different nodes
- **Workspace cleanup**: Workspace might be cleaned between stages
- **Time gaps**: Hours or days might pass between stages
- **Restart scenarios**: When restarting, previous stages didn't just run

```groovy
stage('Sign') {
    steps {
        script {
            // MUST retrieve inputs - can't rely on workspace state
            copyArtifacts(
                projectName: env.JOB_NAME,
                selector: specific(env.BUILD_NUMBER),
                filter: 'workspace/target/**/*',
                target: '.'
            )

            // Do signing work
            sh './sign-artifacts.sh'

            // Archive outputs for next stage
            archiveArtifacts artifacts: 'signed/**/*'
        }
    }
}
```

### 2. Why copyArtifacts + archiveArtifacts Pattern is Essential

**The Problem Without It:**

```groovy
stage('Build') {
    agent { label 'build-node' }
    steps {
        sh './build.sh'
        // ❌ Artifacts only in workspace on build-node
    }
}

stage('Sign') {
    agent { label 'sign-node' }  // Different node!
    steps {
        // ❌ FAILS - no artifacts here, different node
        sh './sign-artifacts.sh'
    }
}
```

**Why this fails:**
- Build runs on `build-node`, leaves artifacts in its workspace
- Sign runs on `sign-node`, has empty workspace
- Even though stages run sequentially, they're on different machines!

**The Solution:**

```groovy
stage('Build') {
    agent { label 'build-node' }
    steps {
        sh './build.sh'
        // ✅ Archive to Jenkins master
        archiveArtifacts artifacts: 'target/**/*'
    }
}

stage('Sign') {
    agent { label 'sign-node' }
    steps {
        // ✅ Retrieve from Jenkins master
        copyArtifacts(
            projectName: env.JOB_NAME,
            selector: specific(env.BUILD_NUMBER),
            filter: 'target/**/*',
            target: '.'
        )
        sh './sign-artifacts.sh'
        archiveArtifacts artifacts: 'signed/**/*'
    }
}
```

### 3. Restart Scenarios Still Require Independence

**Scenario: Restart from Sign**

When you restart from Sign:
1. Build stage did NOT just run
2. Build artifacts are from the original run (could be hours/days old)
3. Sign stage must retrieve those archived artifacts
4. Installer and Test stages will run automatically after Sign

```groovy
stage('Sign') {
    steps {
        script {
            // This works whether:
            // - Build just ran (normal flow)
            // - Restarting from Sign (Build didn't run)
            // - Running on different node
            // - Days after original build
            copyArtifacts(
                projectName: env.JOB_NAME,
                selector: specific(env.BUILD_NUMBER),
                filter: 'target/**/*',
                target: '.'
            )

            sh './sign-artifacts.sh'
            archiveArtifacts artifacts: 'signed/**/*'
        }
    }
}
```

## The Cascade Effect

When you restart a stage, all following stages run automatically. This means:

### Good: Automatic Propagation

If you fix a problem in stage X, all downstream stages automatically get the fix:

```
Restart from Sign (with fixed certificate)
  ↓
Sign runs with new certificate
  ↓
Installer automatically runs (uses newly signed artifacts)
  ↓
Test automatically runs (tests new installer)
```

### Important: Understand the Cascade

If you only want to re-run one stage, you can't use "Restart from Stage":

**Example:**
- Want to re-run just the Test stage with different test parameters
- If you "Restart from Test", only Test runs (it's the last stage)
- But if you "Restart from Installer", both Installer AND Test run

**Solution for single-stage re-run:**
- Use parameterized builds
- Or create separate test jobs
- Or use `when` conditions to skip stages

## Best Practices for Restartable Pipelines

### 1. Always Use copyArtifacts

Every stage (except the first) should retrieve its inputs:

```groovy
stage('Any Stage Except First') {
    steps {
        script {
            // ALWAYS retrieve inputs
            copyArtifacts(
                projectName: env.JOB_NAME,
                selector: specific(env.BUILD_NUMBER),
                filter: 'path/to/inputs/**/*',
                target: '.'
            )

            // Do work
            // ...

            // Archive outputs
            archiveArtifacts artifacts: 'path/to/outputs/**/*'
        }
    }
}
```

**Why:** Works correctly whether stage runs normally or after restart

### 2. Always Archive Outputs

Every stage should archive what downstream stages need:

```groovy
stage('Any Stage') {
    steps {
        script {
            // Do work
            // ...

            // ALWAYS archive outputs
            archiveArtifacts artifacts: '''
                outputs/**/*,
                metadata.json
            ''', fingerprint: true
        }
    }
}
```

**Why:** Downstream stages can retrieve artifacts whether they run immediately or after restart

### 3. Design for Different Agents

Assume each stage runs on a different node:

```groovy
stage('Build') {
    agent { label 'build-node' }
    steps {
        sh './build.sh'
        archiveArtifacts artifacts: 'target/**/*'  // ✅ To Jenkins master
    }
}

stage('Sign') {
    agent { label 'sign-node' }  // Different node
    steps {
        copyArtifacts(...)  // ✅ From Jenkins master
        sh './sign.sh'
        archiveArtifacts artifacts: 'signed/**/*'
    }
}
```

**Why:** Stages often run on different nodes, can't share workspace

### 4. Include Metadata in Archives

Archive metadata alongside artifacts:

```groovy
stage('Build') {
    steps {
        sh './build.sh'

        def buildMetadata = [
            version: '21.0.1',
            buildNumber: env.BUILD_NUMBER,
            timestamp: currentBuild.startTimeInMillis
        ]
        writeJSON file: 'build-metadata.json', json: buildMetadata

        archiveArtifacts artifacts: '''
            target/**/*,
            build-metadata.json
        '''
    }
}
```

**Why:** Downstream stages need metadata to make decisions

### 5. Make Stages Idempotent

Each stage should produce the same output given the same input:

```groovy
stage('Sign') {
    steps {
        script {
            // Clean any previous outputs
            sh 'rm -rf signed/'

            // Retrieve inputs
            copyArtifacts(...)

            // Do work (deterministic)
            sh './sign-artifacts.sh'

            // Archive outputs
            archiveArtifacts artifacts: 'signed/**/*'
        }
    }
}
```

**Why:** Restarting a stage should produce consistent results

## Common Scenarios

### Scenario 1: Fix a Failed Stage

**Problem:** Installer stage failed due to missing dependency

**Solution:**
1. Install the missing dependency on the build node
2. Click "Restart from Installer"
3. **Result:** Installer runs, then Test automatically runs

### Scenario 2: Re-sign with Different Certificate

**Problem:** Need to re-sign artifacts with production certificate

**Solution:**
1. Update signing configuration
2. Click "Restart from Sign"
3. **Result:** Sign runs with new certificate, then Installer and Test automatically run with newly signed artifacts

### Scenario 3: Rebuild Everything

**Problem:** Need to rebuild from scratch

**Solution:**
1. Click "Restart from Build" (first stage)
2. **Result:** All stages run: Build → Sign → Installer → Test

**OR** just trigger a new build (cleaner!)

## Summary

| Question | Answer |
|----------|--------|
| Does restarting a stage re-run following stages? | **YES** - automatically |
| Can I restart any stage independently? | **YES** (if designed correctly) |
| Do following stages run automatically? | **YES** |
| Should each stage retrieve its inputs? | **YES** (via copyArtifacts) |
| Should each stage archive its outputs? | **YES** (via archiveArtifacts) |
| Can I rely on workspace state? | **NO** - stages may run on different nodes |
| Should I archive metadata? | **YES** |
| Can stages run on different nodes? | **YES** - very common |

## Key Takeaway

**Even though stages run sequentially and following stages run automatically, each stage must be independent.**

Each stage should:
1. Retrieve everything it needs from archives (copyArtifacts)
2. Do its work independently
3. Archive everything downstream stages might need (archiveArtifacts)

This makes the pipeline:
- ✅ Restartable from any point
- ✅ Work across different nodes
- ✅ Reliable over time
- ✅ Debuggable (can inspect archived artifacts)

The `archiveArtifacts` + `copyArtifacts` pattern is essential because:
- Stages often run on different nodes
- Workspaces are not shared between nodes
- Restart scenarios need access to previous stage outputs
- Time may pass between stages (hours, days)