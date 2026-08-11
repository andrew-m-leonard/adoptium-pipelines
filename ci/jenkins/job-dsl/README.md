# Job DSL Directory Structure

This directory contains Jenkins Job DSL scripts for automated job creation.

## Directory Organization

```
ci/jenkins/job-dsl/
├── seed/
│   └── seed_job_dsl.groovy                # Seed job script
│
└── openjdk_build_pipeline_job_dsl.groovy  # Dynamic job creation (called by launch jobs)
```

## Script Categories

### Seed Scripts (`seed/` directory)

The seed job uses a **consolidated script** that contains all logic in a single file to avoid binding issues between separate script executions.

**Active Script:**
- **`seed_job_dsl.groovy`**: Main seed job script that:
  1. Loads configuration from `jenkins_job_config.json` and `adoptium_pipeline_config.json`
  2. Creates `Build_openjdk_launchers/Build_openjdk<version>_launch` jobs for each active JDK version
  3. Creates the `Build_openjdk_launchers/` and `Build_openjdk/` top-level folders
  4. Creates/updates the seed job itself (self-updating)
  5. Creates the `Build_openjdk_launchers` and `Build_openjdk` views

**Seed Job Configuration:**
- DSL Scripts: `ci/jenkins/job-dsl/seed/seed_job_dsl.groovy`
- Processes a single consolidated script
- Requires `CONFIG_REPO_URL` and `CONFIG_REPO_BRANCH` parameters

**Why Consolidated?**
Job DSL's `external()` method creates separate script execution contexts, so binding variables set in one script aren't available to the next. The consolidated approach solves this by keeping all logic in a single script execution context.

### Dynamic Job Creation Scripts (root directory)

These scripts are NOT processed by the seed job. They are called dynamically by pipeline jobs using the `jobDsl` step.

**Files:**
- **`openjdk_build_pipeline_job_dsl.groovy`**: Creates platform-specific build jobs
  - Called by: Launch jobs (`Jenkinsfile.launch`)
  - When: `REGENERATE_JOBS=true` or when platform jobs don't exist
  - Requires: `JDK_VERSION`, `PLATFORM`, `CONFIG_REPO_URL`, `CONFIG_REPO_BRANCH` parameters
  - Creates: `Build_openjdk/Build_openjdk<version>_<distro>_<arch>_<os>` (AQA-style naming)
  - See [docs/BUILD_JOB_NAMING_CONVENTION.md](../../../docs/BUILD_JOB_NAMING_CONVENTION.md) for the naming schema

## Adding New Scripts

### For Seed Job Processing

If you need to add new functionality to the seed job:

1. Edit `seed_job_dsl.groovy` directly
2. Add your logic in the appropriate section (marked with comments)
3. The seed job is self-updating, so it will recreate itself on the next run
4. Ensure your code doesn't require parameters beyond `CONFIG_REPO_URL` and `CONFIG_REPO_BRANCH`

**Do NOT create separate scripts in the seed/ directory** - they won't share the binding context and will fail to access shared variables.

### For Dynamic Job Creation

If you need to add a new script for dynamic job creation:

1. Create the script in the root `job-dsl/` directory (NOT in `seed/`)
2. Call it from a pipeline using the `jobDsl` step
3. Pass required parameters via the binding

Example:
```groovy
jobDsl {
    targets('ci/jenkins/job-dsl/your_script.groovy')
    additionalParameters([
        PARAM1: 'value1',
        PARAM2: 'value2'
    ])
}
```

## Important Notes

⚠️ **Do NOT add scripts to the `seed/` directory unless they should be processed by the seed job!**

Scripts in `seed/` are processed automatically and must not require runtime parameters that aren't available during seed job execution (only `CONFIG_REPO_URL` and `CONFIG_REPO_BRANCH` are available).

✅ **For dynamic job creation, keep scripts in the root `job-dsl/` directory.**

This separation ensures:
- Clear distinction between bootstrap and dynamic job creation
- Prevents accidental processing of dynamic scripts by the seed job
- Makes it obvious which scripts are for which purpose