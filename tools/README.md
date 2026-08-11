# Pipeline Tools

Utility tools for migrating legacy Groovy pipeline configurations to the JSON-based format used by this pipeline.

## Tool Chain

The three scripts form a chain — the top-level tool calls the middle one, which calls the low-level one:

```
migrate-groovy-pipeline-configs.py   ← top-level: run this
  └─ calls batch-convert-groovy-configs.py      ← batch driver
       └─ calls groovy-pipeline-config-to-json.py  ← single-file converter
```

---

## Tools

### `migrate-groovy-pipeline-configs.py`

**Purpose**: Top-level migration tool. Converts a directory of legacy `*_pipeline_config.groovy` files to the new JSON architecture, strips the `u` suffix from output filenames, and generates `adoptium_pipeline_config.json` (CI-agnostic) and `jenkins_job_config.json` (Jenkins-specific).

**Usage**:
```bash
python3 tools/migrate-groovy-pipeline-configs.py \
    --source ~/workspace/ci-jenkins-pipelines/pipelines/jobs/configurations \
    --output ~/workspace/ci-temurin-config
```

**Options**:

| Option | Description |
|---|---|
| `--source` / `-s` | Source directory containing `*_pipeline_config.groovy` files (required) |
| `--output` / `-o` | Output directory — receives `jenkins_job_config.json` and `configurations/*.json` (required) |
| `--dry-run` / `-n` | Preview what would be converted without writing files |
| `--verbose` / `-v` | Show detailed conversion output |
| `--force` / `-f` | Overwrite existing JSON files |

**What it does**:
1. Delegates file conversion to `batch-convert-groovy-configs.py`
2. Renames output files — strips `u` suffix (`jdk21u_pipeline_config.groovy` → `configurations/jdk21_pipeline_config.json`)
3. Checks source directory for `jdkNNu.groovy` / `jdkNN.groovy` and reads `disableJob = true` to set `enabled` flags
4. Generates `adoptium_pipeline_config.json` with `activeJdkVersions`, build defaults, and repository references
5. Generates `jenkins_job_config.json` with Jenkins-specific pipeline settings

**Generated `adoptium_pipeline_config.json` structure** (CI-agnostic):
```json
{
  "activeJdkVersions": [
    { "version": "jdk8",  "enabled": true },
    { "version": "jdk17", "enabled": true },
    { "version": "jdk21", "enabled": true }
  ],
  "defaultBuildArgs": "--create-jre-image --create-sbom",
  "defaultConfigureArgs": "",
  "defaultVariant": "temurin",
  "configFilePrefix": "configurations/",
  "configFileSuffix": "_pipeline_config.json",
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

**Generated `jenkins_job_config.json` structure** (Jenkins-specific):
```json
{
  "jenkinsfilePath": "ci/jenkins/Jenkinsfile.declarative",
  "pipelineTimeoutHours": 8,
  "jobConfiguration": {
    "defaultParameters": {
      "VARIANT": "temurin",
      "CLEAN_WORKSPACE_AFTER_STAGE": true,
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

> **Note**: Both `adoptium_pipeline_config.json` and `jenkins_job_config.json` are generated as starting-point templates. Review and update `repository.url` and other site-specific values before committing. See [CODE_CONFIG_SEPARATION.md](../docs/CODE_CONFIG_SEPARATION.md) for the distinction between CI-agnostic and CI-specific config.

---

### `batch-convert-groovy-configs.py`

**Purpose**: Batch driver. Finds all `*_pipeline_config.groovy` files in a directory and calls `groovy-pipeline-config-to-json.py` for each one.

Called automatically by `migrate-groovy-pipeline-configs.py`. Can also be run standalone when you only want raw JSON conversion without the `u`-suffix stripping or `jenkins_job_config.json` generation.

**Usage**:
```bash
python3 tools/batch-convert-groovy-configs.py \
    --source /path/to/groovy/configs \
    --output /path/to/json/configs
```

**Options**:

| Option | Description |
|---|---|
| `--source` / `-s` | Source directory containing Groovy files (required) |
| `--output` / `-o` | Output directory for JSON files (required) |
| `--pattern` / `-p` | Glob pattern (default: `*_pipeline_config.groovy`) |
| `--dry-run` / `-n` | Preview without converting |
| `--verbose` / `-v` | Detailed output |
| `--force` / `-f` | Overwrite existing JSON files |

Output filenames retain the original name with `.groovy` replaced by `.json` (no `u`-suffix stripping — that is handled by the top-level tool).

---

### `groovy-pipeline-config-to-json.py`

**Purpose**: Low-level single-file converter. Parses a Groovy pipeline config file and writes a JSON equivalent. Handles nested maps, lists, and variant-specific values.

Called automatically by `batch-convert-groovy-configs.py`. Can also be run directly:

```bash
python3 tools/groovy-pipeline-config-to-json.py \
    jdk21u_pipeline_config.groovy \
    jdk21_pipeline_config.json
```

---

## Full Migration Workflow

### Step 1 — Clone the legacy configuration source

```bash
git clone https://github.com/adoptium/ci-jenkins-pipelines.git ~/workspace/ci-jenkins-pipelines
```

### Step 2 — Run the conversion

```bash
python3 tools/migrate-groovy-pipeline-configs.py \
    --source ~/workspace/ci-jenkins-pipelines/pipelines/jobs/configurations \
    --output ~/workspace/ci-temurin-config
```

Expected output:
```
======================================================================
Legacy Groovy to New Architecture Converter
======================================================================

Scanning: .../pipelines/jobs/configurations
Pattern:  *_pipeline_config.groovy
Found:    7 configuration file(s)

[1/7] Converting jdk8u_pipeline_config.groovy...  ✅
...
[7/7] Converting jdk25u_pipeline_config.groovy... ✅

Generating jenkins_job_config.json... ✅

Generated files:
  - jenkins_job_config.json
  - configurations/jdk8_pipeline_config.json
  - configurations/jdk17_pipeline_config.json
  - configurations/jdk21_pipeline_config.json
  ...
```

### Step 3 — Review the generated files

```bash
# Inspect top-level config
cat ~/workspace/ci-temurin-config/jenkins_job_config.json | jq .

# Inspect a version config
cat ~/workspace/ci-temurin-config/configurations/jdk21_pipeline_config.json | jq .

# Verify active versions list
jq '.activeJdkVersions' ~/workspace/ci-temurin-config/jenkins_job_config.json
```

Pay particular attention to:
- Nested maps and lists (complex Groovy structures may need manual adjustment)
- Variant-specific values (e.g. `buildArgs: [temurin: '...', hotspot: '...']` → `"buildArgs": {"temurin": "...", "hotspot": "..."}`)
- `enabled` flags — verify disabled versions are correctly set to `false`
- `repository` block in `jenkins_job_config.json` — update `url`, `branch`, `credentialsId` for your org

### Step 4 — Commit to the configuration repository

```bash
cd ~/workspace/ci-temurin-config
git add jenkins_job_config.json configurations/*.json
git commit -m "Convert legacy Groovy configs to new JSON architecture"
git push
```

---

## Troubleshooting

### Nested maps not converting correctly

```
Error parsing x64Linux: unexpected token
```

Manually review the Groovy file for complex nested structures (closures, method calls) and adjust the JSON output directly.

### Variant-specific values

Groovy:
```groovy
buildArgs: [
    temurin: '--create-jre-image --create-sbom',
    hotspot: '--create-jre-image'
]
```

Should produce:
```json
"buildArgs": {
  "temurin": "--create-jre-image --create-sbom",
  "hotspot": "--create-jre-image"
}
```

Verify this is correct in the output — if not, edit the JSON manually.

### Version file name mismatch

```
Error: Config file not found: configurations/jdk21u_pipeline_config.json
```

The pipeline expects filenames **without** the `u` suffix. Ensure you used `migrate-groovy-pipeline-configs.py` (not the raw batch converter) — it handles the renaming.

---

## Related Documentation

- [CONFIG_SCHEMA.md](../docs/CONFIG_SCHEMA.md) — full schema reference for `adoptium_pipeline_config.json`, `jenkins_job_config.json`, and `configurations/jdkNN_pipeline_config.json`
- [CODE_CONFIG_SEPARATION.md](../docs/CODE_CONFIG_SEPARATION.md) — config repo structure and how the pipeline loads configuration
- [JOB_DSL_AUTOMATION.md](../docs/JOB_DSL_AUTOMATION.md) — how `jenkins_job_config.json` is consumed by the seed job
