# TARGET_DIR and archiveArtifacts Consistency Guide

## Overview

This document describes the consistent usage of `TARGET_DIR` environment variable and corresponding `archiveArtifacts` patterns across all pipeline stages in the declarative pipeline.

## Design Principle

**Every stage that produces artifacts MUST:**
1. Set `TARGET_DIR` environment variable to specify where outputs are written
2. Use `archiveArtifacts` with a pattern that matches the `TARGET_DIR` location
3. Ensure the artifact pattern is derived from or consistent with `TARGET_DIR`

## Stage-by-Stage Breakdown

### 1. Initialize Stage

**Purpose:** Load configuration and set up pipeline metadata

**TARGET_DIR:** Not applicable (no build artifacts)

**archiveArtifacts:**
```groovy
archiveArtifacts artifacts: 'pipeline-config.json',
               fingerprint: true,
               allowEmptyArchive: false
```

**Notes:** Archives only the configuration file, not build outputs.

---

### 2. Build Stage

**Purpose:** Compile JDK and organize build artifacts

**TARGET_DIR:**
```groovy
env.TARGET_DIR = "${WORKSPACE}/workspace/target"
```

**archiveArtifacts:**
```groovy
archiveArtifacts artifacts: "${env.TARGET_DIR.replace(env.WORKSPACE + '/', '')}/**/*",
               fingerprint: true,
               allowEmptyArchive: false
```

**Consistency:** ✅ **CONSISTENT**
- The `archiveArtifacts` pattern is dynamically derived from `TARGET_DIR`
- Strips workspace prefix to get relative path: `workspace/target/**/*`
- All build outputs (tar.gz, zip, JSON, SBOM files) are in this directory

**Script Reference:** [`scripts/stages/02-build.sh`](../scripts/stages/02-build.sh)
- Line 534: Copies artifacts to `${TARGET_DIR}` using `organize_build_outputs()`

---

### 3. Internal Sign Stage

**Purpose:** Code sign binaries (Mac/Windows only)

**TARGET_DIR:** Not set (uses downstream job)

**archiveArtifacts:** None (handled by downstream job)

**Notes:** This stage triggers a downstream signing job and doesn't produce artifacts directly.

---

### 4. Verify Signing Stage

**Purpose:** Verify code signatures

**TARGET_DIR:** Not set (verification only)

**archiveArtifacts:** None

**Notes:** Verification stage doesn't produce artifacts, only validates existing signatures.

---

### 5. Validate SBOM Stage

**Purpose:** Validate Software Bill of Materials files

**TARGET_DIR:**
```groovy
env.TARGET_DIR = "${WORKSPACE}"
```

**initializeStage artifacts:**
```groovy
'pipeline-config.json,*sbom*.json'
```

**archiveArtifacts:** None

**Consistency:** ✅ **CONSISTENT**
- This stage validates SBOM files but doesn't produce new artifacts
- `TARGET_DIR` points to workspace root where `copyArtifacts` places files (Jenkins flattens paths)
- Artifact filter uses flattened paths: `*sbom*.json` not `workspace/target/**/*sbom*.json`
- No archiving needed as SBOM files were already archived in Build stage

**Script Reference:** [`scripts/stages/12-validate-sbom.sh`](../scripts/stages/12-validate-sbom.sh)
- Line 99: Validates SBOM files in `${TARGET_DIR}` (workspace root after copyArtifacts flattening)

---

### 6. Smoke Tests Stage

**Purpose:** Run basic functionality tests on built JDK

**TARGET_DIR:**
```groovy
env.TARGET_DIR = "${WORKSPACE}"
```

**initializeStage artifacts:**
```groovy
'pipeline-config.json,*.tar.gz,*.zip'
```

**archiveArtifacts:** None

**Consistency:** ✅ **CONSISTENT**
- Stage reads artifacts from `TARGET_DIR` (workspace root where copyArtifacts places them)
- Artifact filter uses flattened paths: `*.tar.gz,*.zip` not `workspace/target/**/*.tar.gz`
- Test results are logged but not archived separately
- Jenkins `copyArtifacts` flattens directory structure, so files appear in workspace root

**Script Reference:** [`scripts/stages/13-smoke-tests.sh`](../scripts/stages/13-smoke-tests.sh)
- Extracts and tests JDK from `${TARGET_DIR}` (workspace root)

---

### 7. Reproducible Compare Build Stage

**Purpose:** Compare local build against production binaries

**TARGET_DIR:**
```groovy
env.TARGET_DIR = "${WORKSPACE}"
```

**initializeStage artifacts:**
```groovy
'pipeline-config.json,*.tar.gz,*.zip'
```

**archiveArtifacts:**
```groovy
// Archive comparison results (output directory is fixed by repro_compare.sh)
// Note: This stage outputs to ${WORKSPACE}/reproducible-compare/ regardless of TARGET_DIR
archiveArtifacts artifacts: 'reproducible-compare/comparison-report.txt,reproducible-compare/reprotest.diff,reproducible-compare/reproducible_evidence.log,reproducible-compare/ReproduciblePercent',
               fingerprint: true,
               allowEmptyArchive: true
```

**Consistency:** ⚠️ **SPECIAL CASE**
- `TARGET_DIR` points to workspace root where `copyArtifacts` places build artifacts (input)
- Artifact filter uses flattened paths: `*.tar.gz,*.zip` not `workspace/target/**/*.tar.gz`
- Output directory is hardcoded by `repro_compare.sh` to `${WORKSPACE}/reproducible-compare/`
- This is intentional: comparison results are separate from build artifacts
- The script creates its own output directory structure

**Script Reference:** [`scripts/stages/20-reproducible-compare.sh`](../scripts/stages/20-reproducible-compare.sh)
- Line 54: Creates `COMPARE_WORKSPACE="${WORKSPACE}/reproducible-compare"`
- Reads build artifacts from `${TARGET_DIR}` (workspace root)
- Writes comparison results to fixed location

---

### 8. AQA Tests Stage

**Purpose:** Run Adoptium Quality Assurance test suite

**TARGET_DIR:** Not set (uses downstream job)

**archiveArtifacts:** None (handled by downstream job)

**Notes:** Triggers downstream AQA test job which handles its own artifact management.

---

## Critical Concept: Jenkins copyArtifacts Flattening

**IMPORTANT:** Jenkins `copyArtifacts` step flattens the directory structure when copying artifacts between jobs or stages.

### Example

**Build Stage archives:**
```groovy
env.TARGET_DIR = "${WORKSPACE}/workspace/target"
archiveArtifacts artifacts: "workspace/target/**/*"
```

This creates archived artifacts with paths like:
- `workspace/target/OpenJDK21U-jdk_x64_linux_hotspot_21.0.5_11.tar.gz`
- `workspace/target/OpenJDK21U-jdk_x64_linux_hotspot_21.0.5_11_sbom.json`

**Downstream Stage copies:**
```groovy
copyArtifacts projectName: 'upstream-job',
              filter: '*.tar.gz,*.zip,*sbom*.json',
              target: '.'
```

Jenkins **flattens** the paths, so files appear in workspace root:
- `${WORKSPACE}/OpenJDK21U-jdk_x64_linux_hotspot_21.0.5_11.tar.gz`
- `${WORKSPACE}/OpenJDK21U-jdk_x64_linux_hotspot_21.0.5_11_sbom.json`

### Implications for TARGET_DIR

**Build Stage (produces artifacts):**
```groovy
env.TARGET_DIR = "${WORKSPACE}/workspace/target"  // Where build outputs go
```

**Downstream Stages (consume artifacts):**
```groovy
env.TARGET_DIR = "${WORKSPACE}"  // Where copyArtifacts places files (flattened)
```

### Implications for initializeStage Artifact Filters

**WRONG (assumes directory structure is preserved):**
```groovy
initializeStage('Smoke Tests', ['Build'], 'workspace/target/**/*.tar.gz')
```

**CORRECT (uses flattened paths):**
```groovy
initializeStage('Smoke Tests', ['Build'], '*.tar.gz,*.zip')
```

---

## Consistency Rules

### Rule 1: TARGET_DIR Must Match Script Output Location

Every stage script that writes artifacts MUST:
- Accept `TARGET_DIR` environment variable
- Write all outputs to `${TARGET_DIR}` or a documented subdirectory
- Document any exceptions (like reproducible-compare)

### Rule 2: archiveArtifacts Must Reference TARGET_DIR

When archiving artifacts, prefer:
```groovy
// GOOD: Dynamically derived from TARGET_DIR
archiveArtifacts artifacts: "${env.TARGET_DIR.replace(env.WORKSPACE + '/', '')}/**/*"

// ACCEPTABLE: Documented exception with clear reason
archiveArtifacts artifacts: 'reproducible-compare/...'  // Fixed by repro_compare.sh
```

Avoid:
```groovy
// BAD: Hardcoded path that doesn't match TARGET_DIR
env.TARGET_DIR = "${WORKSPACE}/workspace/target"
archiveArtifacts artifacts: 'build/output/**/*'  // MISMATCH!
```

### Rule 3: Document Exceptions

If a stage must use a different output directory than `TARGET_DIR`:
1. Add a comment explaining why
2. Document the fixed output location
3. Ensure the script creates the directory structure

Example:
```groovy
// Archive comparison results (output directory is fixed by repro_compare.sh)
// Note: This stage outputs to ${WORKSPACE}/reproducible-compare/ regardless of TARGET_DIR
archiveArtifacts artifacts: 'reproducible-compare/...'
```

## Verification Checklist

When adding or modifying a stage:

- [ ] Does the stage produce artifacts?
  - If NO: Skip remaining checks
  - If YES: Continue

- [ ] Is `TARGET_DIR` set in the stage?
  - Should point to where artifacts are written

- [ ] Does the stage script use `TARGET_DIR`?
  - Check script accepts and uses `${TARGET_DIR}`

- [ ] Does `archiveArtifacts` match `TARGET_DIR`?
  - Pattern should reference `TARGET_DIR` or be documented exception

- [ ] Are exceptions documented?
  - Add comment explaining any hardcoded paths

## Common Patterns

### Pattern 1: Build Stage (Produces Artifacts)
```groovy
// Build stage creates artifacts in nested directory
env.TARGET_DIR = "${WORKSPACE}/workspace/target"
// ... run build script that writes to TARGET_DIR ...
archiveArtifacts artifacts: "${env.TARGET_DIR.replace(env.WORKSPACE + '/', '')}/**/*"
```

### Pattern 2: Downstream Stage (Consumes Artifacts)
```groovy
// Downstream stage receives flattened artifacts from copyArtifacts
initializeStage('Smoke Tests', ['Build'], '*.tar.gz,*.zip')  // Flattened paths
env.TARGET_DIR = "${WORKSPACE}"  // copyArtifacts places files in workspace root
// ... run validation/test script that reads from TARGET_DIR ...
// No archiveArtifacts needed
```

### Pattern 3: Fixed Output Directory (Documented Exception)
```groovy
// Stage reads from TARGET_DIR but writes to fixed location
initializeStage('Compare', ['Build'], '*.tar.gz,*.zip')  // Flattened input paths
env.TARGET_DIR = "${WORKSPACE}"  // Input location (flattened)
// ... run comparison script ...
// Archive from fixed location (documented in comment)
archiveArtifacts artifacts: 'reproducible-compare/...'
```

## Benefits of This Approach

1. **Predictability:** Developers know where to find artifacts
2. **Maintainability:** Easy to update output locations
3. **Testability:** Scripts can be tested locally with different TARGET_DIR values
4. **Clarity:** Exceptions are documented and justified
5. **Consistency:** All stages follow the same pattern

## Related Documentation

- [Migration Strategy](MIGRATION_STRATEGY.md) - Overall refactoring approach
- [Stage Scripts](../scripts/stages/) - Individual stage implementations
- [Jenkinsfile.declarative](../ci/jenkins/Jenkinsfile.declarative) - Pipeline definition