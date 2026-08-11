# Visual Migration Guide

This document provides visual representations of the migration process, architecture, and workflows.

---

## Table of Contents
1. [Migration Timeline](#migration-timeline)
2. [Parallel Execution Architecture](#parallel-execution-architecture)
3. [Comparison Workflow](#comparison-workflow)
4. [Rollout Strategy](#rollout-strategy)
5. [Risk Mitigation](#risk-mitigation)
6. [Success Metrics](#success-metrics)

---

## Migration Timeline

### High-Level Timeline

```
┌────────────────────────────────────────────────────────────────────────────┐
│                    ACCELERATED MIGRATION TIMELINE                           │
│                         (2.5-3.5 Months Total)                              │
└────────────────────────────────────────────────────────────────────────────┘

Week 1: FOUNDATION
├─ Infrastructure setup (tooling exists)
├─ Integrate repro_compare.sh
└─ Configure parallel execution

Weeks 2-3: PILOT
├─ Linux x64 JDK21u setup
├─ Run 5 validation builds
├─ Analyze results & fix issues
└─ Document edge cases

Week 4: TIER 1 ROLLOUT
├─ Linux x64 JDK17u (parallel)
├─ Linux x64 JDK11u (parallel)
└─ Linux x64 JDK8u (parallel)

Weeks 5-6: TIER 2 ROLLOUT
├─ Mac aarch64 + x64 (all versions)
└─ Windows x64 + x86-32 (all versions)

Weeks 7-8: TIER 3 ROLLOUT
├─ Linux aarch64 (all versions)
├─ Linux ppc64le (all versions)
└─ Linux s390x (all versions)

Weeks 9-10: FINAL PLATFORMS
├─ AIX ppc64 (all versions)
├─ Docker builds
├─ Cross-compilation
└─ Custom configurations

Weeks 11-14: COMPLETION
├─ Week 11: Final validation
├─ Week 12: Cutover preparation
├─ Week 13: Cutover execution
└─ Week 14: Decommission & training
```

---

## Parallel Execution Architecture

### System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     PARALLEL EXECUTION SYSTEM                            │
└─────────────────────────────────────────────────────────────────────────┘

                              ┌─────────────┐
                              │   Trigger   │
                              │ (Git/Cron)  │
                              └──────┬──────┘
                                     │
                    ┌────────────────┴────────────────┐
                    │                                 │
                    ▼                                 ▼
        ┌───────────────────────┐       ┌───────────────────────┐
        │   OLD PIPELINE        │       │   NEW PIPELINE        │
        │ (openjdk_build_       │       │ (openjdk_build_       │
        │  pipeline.groovy)     │       │  pipeline_v2.groovy)  │
        └───────────┬───────────┘       └───────────┬───────────┘
                    │                               │
                    │                               │
        ┌───────────▼───────────┐       ┌───────────▼───────────┐
        │  Build Stages:        │       │  Build Stages:        │
        │  ├─ Checkout          │       │  ├─ Initialize        │
        │  ├─ Build             │       │  ├─ Build (script)    │
        │  ├─ Sign              │       │  ├─ Sign (script)     │
        │  ├─ Installer         │       │  ├─ Installer (script)│
        │  └─ Test              │       │  └─ Test (script)     │
        └───────────┬───────────┘       └───────────┬───────────┘
                    │                               │
                    │                               │
        ┌───────────▼───────────┐       ┌───────────▼───────────┐
        │  Artifact Storage:    │       │  Artifact Storage:    │
        │  /old-builds/         │       │  /new-builds/         │
        │  ├─ JDK tarball       │       │  ├─ JDK tarball       │
        │  ├─ Signatures        │       │  ├─ Signatures        │
        │  ├─ Installers        │       │  ├─ Installers        │
        │  └─ Test results      │       │  └─ Test results      │
        └───────────┬───────────┘       └───────────┬───────────┘
                    │                               │
                    └────────────┬──────────────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │  COMPARISON ENGINE     │
                    │                        │
                    │  ├─ Binary Diff        │
                    │  ├─ Checksum Compare   │
                    │  ├─ Metadata Validate  │
                    │  ├─ Test Compare       │
                    │  └─ Performance Check  │
                    └────────────┬───────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │  COMPARISON REPORT     │
                    │                        │
                    │  Status: ✓ MATCH      │
                    │  Binary: ✓ Identical  │
                    │  Tests:  ✓ Same       │
                    │  Perf:   ✓ +2%        │
                    └────────────┬───────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │     DASHBOARD          │
                    │  (Visual Results)      │
                    └────────────────────────┘
```

---

## Comparison Workflow

### Detailed Comparison Process Using repro_compare.sh

```
┌─────────────────────────────────────────────────────────────────────────┐
│              COMPARISON WORKFLOW (using repro_compare.sh)                │
└─────────────────────────────────────────────────────────────────────────┘

Step 1: ARTIFACT COLLECTION
┌──────────────────────────────────────┐
│ Collect artifacts from both builds:  │
│ ├─ /old-builds/jdk21u-linux-x64.tgz │
│ └─ /new-builds/jdk21u-linux-x64.tgz │
└──────────────┬───────────────────────┘
               │
               ▼
Step 2: EXTRACT BUILDS
┌──────────────────────────────────────┐
│ Extract both JDK builds:             │
│ ├─ tar -xzf old-build → /tmp/old    │
│ └─ tar -xzf new-build → /tmp/new    │
└──────────────┬───────────────────────┘
               │
               ▼
Step 3: RUN repro_compare.sh
┌──────────────────────────────────────────────────────────┐
│ Execute comparison tool:                                 │
│                                                          │
│ $ cd temurin-build/tooling/reproducible                 │
│ $ ./repro_compare.sh \                                  │
│     temurin /tmp/old/jdk-21.0.12+1 \                   │
│     temurin /tmp/new/jdk-21.0.12+1 \                   │
│     Linux                                               │
│                                                          │
│ Tool performs:                                           │
│ ├─ File structure comparison                            │
│ ├─ File count validation                                │
│ ├─ Platform-specific preprocessing:                     │
│ │  ├─ Remove timestamps                                 │
│ │  ├─ Remove build IDs                                  │
│ │  ├─ Remove absolute paths                             │
│ │  └─ Normalize metadata                                │
│ ├─ Byte-by-byte binary comparison                       │
│ └─ Generate comparison reports                          │
└──────────────┬───────────────────────────────────────────┘
               │
               ├─ Exit 0 (IDENTICAL) ──────────────┐
               │                                    │
               └─ Exit 1 (DIFFER) ─────────┐       │
                                           │       │
                                           ▼       ▼
Step 4: ANALYZE RESULTS                   │       │
┌──────────────────────────────┐         │       │
│ Check output files:          │         │       │
│ ├─ reprotest.diff            │◄────────┘       │
│ │  (lists different files)   │                 │
│ ├─ reproducible_evidence.log │                 │
│ │  (detailed comparison)     │                 │
│ └─ ReproduciblePercent       │                 │
│    (percentage match)        │                 │
└──────────────┬───────────────┘                 │
               │                                  │
               ├─ 100% MATCH ────────────────────┤
               │                                  │
               └─ <100% DIFFER ──────┐           │
                                     │           │
                                     ▼           ▼
Step 5: CHECKSUM VALIDATION          │           │
┌──────────────────────────────┐     │           │
│ Verify checksums:            │     │           │
│ ├─ SHA256 of JDK tarball     │ │   │
│ ├─ SHA256 of each binary     │ │   │
│ └─ Compare checksums          │ │   │
└──────────────┬───────────────┘ │   │
               │                 │   │
               ├─ MATCH ─────────┼───┤
               │                 │   │
               └─ DIFFER ────────┤   │
                                 │   │
                                 ▼   ▼
Step 4: METADATA VALIDATION      │   │
┌──────────────────────────────┐ │   │
│ Compare metadata:            │ │   │
│ ├─ Version strings           │ │   │
│ ├─ Build info                │ │   │
│ ├─ Release file              │ │   │
│ └─ Module info               │ │   │
└──────────────┬───────────────┘ │   │
               │                 │   │
               ├─ MATCH ─────────┼───┤
               │                 │   │
               └─ DIFFER ────────┤   │
                                 │   │
                                 ▼   ▼
Step 5: TEST COMPARISON          │   │
┌──────────────────────────────┐ │   │
│ Compare test results:        │ │   │
│ ├─ Test pass/fail status     │ │   │
│ ├─ Test output               │ │   │
│ ├─ Performance metrics       │ │   │
│ └─ Coverage data             │ │   │
└──────────────┬───────────────┘ │   │
               │                 │   │
               ├─ MATCH ─────────┼───┤
               │                 │   │
               └─ DIFFER ────────┤   │
                                 │   │
                                 ▼   ▼
Step 6: PERFORMANCE CHECK        │   │
┌──────────────────────────────┐ │   │
│ Compare performance:         │ │   │
│ ├─ Build duration            │ │   │
│ ├─ Resource usage            │ │   │
│ ├─ Artifact size             │ │   │
│ └─ Test execution time       │ │   │
└──────────────┬───────────────┘ │   │
               │                 │   │
               ├─ ACCEPTABLE ────┼───┤
               │                 │   │
               └─ REGRESSION ────┤   │
                                 │   │
                                 ▼   ▼
Step 7: FINAL REPORT             │   │
┌──────────────────────────────┐ │   │
│ Generate report:             │ │   │
│                              │ │   │
│ ┌──────────────────────────┐ │ │   │
│ │ COMPARISON FAILED        │◄┼─┘   │
│ │                          │ │     │
│ │ Differences found:       │ │     │
│ │ ├─ Binary mismatch       │ │     │
│ │ ├─ Checksum differ       │ │     │
│ │ └─ Test failures         │ │     │
│ │                          │ │     │
│ │ Action: INVESTIGATE      │ │     │
│ └──────────────────────────┘ │     │
│                              │     │
│ ┌──────────────────────────┐ │     │
│ │ COMPARISON PASSED ✓      │◄┼─────┘
│ │                          │ │
│ │ All checks passed:       │ │
│ │ ├─ Binary identical      │ │
│ │ ├─ Checksums match       │ │
│ │ ├─ Tests identical       │ │
│ │ └─ Performance OK        │ │
│ │                          │ │
│ │ Action: PROCEED          │ │
│ └──────────────────────────┘ │
└──────────────────────────────┘
```

---

## Rollout Strategy

### Platform Rollout Sequence

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      PLATFORM ROLLOUT STRATEGY                           │
└─────────────────────────────────────────────────────────────────────────┘

TIER 1: HIGH PRIORITY, LOW RISK
┌────────────────────────────────────────┐
│ Linux x64 (All JDK Versions)           │
│ ├─ JDK21u Temurin ✓ (Pilot)          │
│ ├─ JDK17u Temurin → Week 8            │
│ ├─ JDK11u Temurin → Week 8            │
│ └─ JDK8u Temurin  → Week 9            │
│                                        │
│ Rationale:                             │
│ • Most common platform                 │
│ • Best tested                          │
│ • Fastest builds                       │
│ • Largest user base                    │
└────────────────────────────────────────┘
         │
         ▼
TIER 2: HIGH PRIORITY, MEDIUM RISK
┌────────────────────────────────────────┐
│ Mac & Windows (Common Versions)        │
│ ├─ Mac aarch64 JDK21u → Week 10       │
│ ├─ Mac aarch64 JDK17u → Week 10       │
│ ├─ Windows x64 JDK21u → Week 11       │
│ └─ Windows x64 JDK17u → Week 11       │
│                                        │
│ Rationale:                             │
│ • High usage platforms                 │
│ • Platform-specific signing            │
│ • More complex toolchains              │
└────────────────────────────────────────┘
         │
         ▼
TIER 3: MEDIUM PRIORITY, HIGHER RISK
┌────────────────────────────────────────┐
│ Less Common Platforms                  │
│ ├─ Linux aarch64 → Week 12            │
│ ├─ Mac x64 → Week 12                  │
│ ├─ AIX ppc64 → Week 13                │
│ └─ Linux s390x → Week 13              │
│                                        │
│ Rationale:                             │
│ • Lower usage                          │
│ • Limited build resources              │
│ • Platform-specific quirks             │
└────────────────────────────────────────┘
         │
         ▼
VARIANTS: SPECIAL HANDLING
│ Rationale:                             │
│ • Different VM implementation          │
│ • Unique build requirements            │
│ • Separate testing needed              │
└────────────────────────────────────────┘
         │
         ▼
EDGE CASES: SPECIAL CONFIGURATIONS
┌────────────────────────────────────────┐
│ Special Build Scenarios                │
│ ├─ Docker container builds → Week 9   │
│ ├─ Cross-compilation → Week 9         │
│ ├─ Custom build args → Week 10        │
│ └─ Special signing → Week 10          │
│                                        │
│ Rationale:                             │
│ • Unique requirements                  │
│ • May need custom scripts              │
│ • Thorough testing required            │
└────────────────────────────────────────┘
```

### Decision Tree for Platform Migration

```
                    ┌─────────────────┐
                    │ Start Migration │
                    │   for Platform  │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ Is this Tier 1? │
                    └────┬───────┬────┘
                         │       │
                    YES  │       │  NO
                         │       │
                         ▼       ▼
              ┌──────────────┐  ┌──────────────┐
              │ High Priority│  │ Check Tier 2?│
              │ Fast Track   │  └──────┬───────┘
              └──────┬───────┘         │
                     │            YES  │  NO
                     │                 │
                     │                 ▼
                     │        ┌──────────────┐
                     │        │ Medium Prior │
                     │        │ Standard     │
                     │        └──────┬───────┘
                     │               │
                     ▼               ▼
              ┌──────────────────────────┐
              │ Convert Configuration    │
              └──────────┬───────────────┘
                         │
                         ▼
              ┌──────────────────────────┐
              │ Any Known Edge Cases?    │
              └────┬───────────────┬─────┘
                   │               │
              YES  │               │  NO
                   │               │
                   ▼               ▼
        ┌──────────────────┐  ┌──────────────┐
        │ Review Edge Case │  │ Standard     │
        │ Documentation    │  │ Process      │
        └──────┬───────────┘  └──────┬───────┘
               │                     │
               └──────────┬──────────┘
                          │
                          ▼
              ┌──────────────────────────┐
              │ Set Up Parallel Execution│
              └──────────┬───────────────┘
                         │
                         ▼
              ┌──────────────────────────┐
              │ Run 5 Parallel Builds    │
              └──────────┬───────────────┘
                         │
                         ▼
              ┌──────────────────────────┐
              │ All Comparisons Pass?    │
              └────┬───────────────┬─────┘
                   │               │
              YES  │               │  NO
                   │               │
                   ▼               ▼
        ┌──────────────────┐  ┌──────────────┐
        │ Document Success │  │ Investigate  │
        │ Mark Complete    │  │ Differences  │
        └──────────────────┘  └──────┬───────┘
                                     │
                                     ▼
                          ┌──────────────────┐
                          │ Fix Issues       │
                          └──────┬───────────┘
                                 │
                                 ▼
                          ┌──────────────────┐
                          │ Re-run Builds    │
                          └──────┬───────────┘
                                 │
                                 └──────┐
                                        │
                                        ▼
                              ┌──────────────────┐
                              │ Platform Complete│
                              └──────────────────┘
```

---

## Risk Mitigation

### Risk Matrix

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           RISK MATRIX                                    │
└─────────────────────────────────────────────────────────────────────────┘

                    IMPACT
                    │
         HIGH       │  ┌─────────┐  ┌─────────┐
                    │  │ Binary  │  │Platform │
                    │  │ Differ  │  │ Failure │
                    │  │  [P0]   │  │  [P0]   │
                    │  └─────────┘  └─────────┘
                    │
       MEDIUM       │  ┌─────────┐  ┌─────────┐
                    │  │  Perf   │  │  Team   │
                    │  │Regression│  │Adoption │
                    │  │  [P1]   │  │  [P1]   │
                    │  └─────────┘  └─────────┘
                    │
         LOW        │  ┌─────────┐  ┌─────────┐
                    │  │  Doc    │  │Schedule │
                    │  │  Gaps   │  │  Slip   │
                    │  │  [P2]   │  │  [P2]   │
                    │  └─────────┘  └─────────┘
                    │
                    └────────────────────────────
                         LOW    MEDIUM    HIGH
                              PROBABILITY

MITIGATION STRATEGIES:

[P0] Binary Differences
├─ Extensive comparison testing
├─ Byte-level diff analysis
├─ Parallel execution validation
└─ Easy rollback capability

[P0] Platform-Specific Failure
├─ Comprehensive pilot phase
├─ Gradual rollout by platform
├─ Platform-specific testing
└─ Expert review for each platform

[P1] Performance Regression
├─ Performance benchmarking
├─ Optimization phase
├─ Acceptable threshold (±10%)
└─ Continuous monitoring

[P1] Team Adoption
├─ Comprehensive documentation
├─ Training sessions
├─ Gradual transition
└─ Support channel

[P2] Documentation Gaps
├─ Documentation reviews
├─ User feedback
└─ Continuous updates

[P2] Schedule Slip
├─ Buffer time in estimates
├─ Regular progress reviews
└─ Flexible milestone dates
```

---

## Success Metrics

### Key Performance Indicators Dashboard

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      SUCCESS METRICS DASHBOARD                           │
└─────────────────────────────────────────────────────────────────────────┘

MIGRATION PROGRESS
┌────────────────────────────────────────────────────────────────┐
│ Overall Progress:  [████████████████░░░░░░░░] 75%             │
│                                                                │
│ Platforms Migrated:     30 / 40                               │
│ ├─ Tier 1: [████████████████████] 100% (4/4)                 │
│ ├─ Tier 2: [████████████████░░░░]  80% (4/5)                 │
│ └─ Tier 3: [████████░░░░░░░░░░░░]  50% (2/4)                 │
└────────────────────────────────────────────────────────────────┘

BUILD QUALITY
┌────────────────────────────────────────────────────────────────┐
│ Comparison Success Rate:  [████████████████████] 100%         │
│ ├─ Binary Match:          [████████████████████] 100%         │
│ ├─ Checksum Match:        [████████████████████] 100%         │
│ ├─ Test Match:            [████████████████████] 100%         │
│ └─ Metadata Match:        [████████████████████] 100%         │
│                                                                │
│ Total Builds Compared:    150                                 │
│ ├─ Successful:            150 (100%)                          │
│ ├─ Failed:                  0 (0%)                            │
│ └─ In Progress:             5                                 │
└────────────────────────────────────────────────────────────────┘

PERFORMANCE
┌────────────────────────────────────────────────────────────────┐
│ Build Duration:           [████████████████░░░░] +5%          │
│ ├─ Average Old:           45 minutes                          │
│ ├─ Average New:           47 minutes                          │
│ └─ Delta:                 +2 minutes (+4.4%)                  │
│                                                                │
│ Resource Usage:           [████████████████████] Same         │
│ ├─ CPU:                   ~95% of old                         │
│ ├─ Memory:                ~98% of old                         │
│ └─ Disk:                  Same                                │
│                                                                │
│ Artifact Size:            [████████████████████] Identical    │
│ └─ Size Match:            100%                                │
└────────────────────────────────────────────────────────────────┘

RELIABILITY
┌────────────────────────────────────────────────────────────────┐
│ Build Success Rate:       [████████████████████] 98%          │
│ ├─ Old Pipeline:          97%                                 │
│ ├─ New Pipeline:          98%                                 │
│ └─ Delta:                 +1%                                 │
│                                                                │
│ Restart Success Rate:     [████████████████████] 96%          │
│ └─ Restarts Successful:   48 / 50                            │
│                                                                │
│ Failure Recovery Time:    [████████████████████] 15 min      │
│ └─ Target:                < 30 minutes                        │
└────────────────────────────────────────────────────────────────┘

ISSUES TRACKING
┌────────────────────────────────────────────────────────────────┐
│ Total Issues Found:       12                                  │
│ ├─ P0 (Critical):         0 (All resolved)                    │
│ ├─ P1 (High):             2 (In progress)                     │
│ ├─ P2 (Medium):           5 (3 resolved, 2 open)             │
│ └─ P3 (Low):              5 (2 resolved, 3 open)             │
│                                                                │
│ Average Resolution Time:  2.5 days                            │
└────────────────────────────────────────────────────────────────┘

TEAM METRICS
┌────────────────────────────────────────────────────────────────┐
│ Team Confidence:          [████████████████░░░░] 80%          │
│ ├─ Very Confident:        6 members                           │
│ ├─ Confident:             3 members                           │
│ └─ Learning:              1 member                            │
│                                                                │
│ Training Completion:      [████████████████████] 90%          │
│ └─ Completed Training:    9 / 10 members                      │
│                                                                │
│ Documentation Quality:    [████████████████░░░░] 85%          │
│ └─ User Satisfaction:     4.2 / 5.0                          │
└────────────────────────────────────────────────────────────────┘

TIMELINE
┌────────────────────────────────────────────────────────────────┐
│ Current Week:             Week 8 / 14                         │
│ ├─ On Schedule:           Yes                                 │
│ ├─ Days Ahead/Behind:     On track                            │
│ └─ Estimated Completion:  Week 14 (on schedule)              │
│                                                                │
│ Next Milestone:           Final Platforms (Week 9-10)         │
│ └─ Readiness:             [████████████████░░░░] 85%          │
└────────────────────────────────────────────────────────────────┘

STATUS: ✅ ON TRACK
```

---

## Conclusion

This visual guide provides clear representations of:
- ✅ Migration timeline and phases
- ✅ Parallel execution architecture
- ✅ Comparison workflow details
- ✅ Platform rollout strategy
- ✅ Risk mitigation approaches
- ✅ Success metrics tracking

Use these diagrams in presentations, documentation, and team communications to ensure everyone understands the migration process.

---

*Document Version: 1.0*

---

## Appendix: repro_compare.sh Tool Usage

### Tool Overview

The `repro_compare.sh` tool from `temurin-build/tooling/reproducible/` is used to validate that old and new pipeline builds are byte-for-byte identical.

### Basic Command Structure

```bash
cd temurin-build/tooling/reproducible
./repro_compare.sh <vendor1> <jdk1_path> <vendor2> <jdk2_path> <platform>
```

### Platform-Specific Examples

#### Linux x64 Example
```bash
# Extract builds
tar -xzf /old-builds/jdk21u-linux-x64-20260512.tar.gz -C /tmp/old-jdk
tar -xzf /new-builds/jdk21u-linux-x64-20260512.tar.gz -C /tmp/new-jdk

# Run comparison
cd temurin-build/tooling/reproducible
./repro_compare.sh \
  temurin /tmp/old-jdk/jdk-21.0.12+1 \
  temurin /tmp/new-jdk/jdk-21.0.12+1 \
  Linux

# Check exit code
if [ $? -eq 0 ]; then
  echo "✓ Builds are IDENTICAL"
else
  echo "✗ Builds DIFFER - check reprotest.diff"
fi
```

#### macOS aarch64 Example
```bash
# Extract builds
tar -xzf /old-builds/jdk21u-mac-aarch64-20260512.tar.gz -C /tmp/old-jdk
tar -xzf /new-builds/jdk21u-mac-aarch64-20260512.tar.gz -C /tmp/new-jdk

# Run comparison
cd temurin-build/tooling/reproducible
./repro_compare.sh \
  temurin /tmp/old-jdk/jdk-21.0.12+1 \
  temurin /tmp/new-jdk/jdk-21.0.12+1 \
  Darwin

# Archive results
cp reprotest.diff /results/mac-aarch64-comparison.diff
cp reproducible_evidence.log /results/mac-aarch64-evidence.log
```

#### Windows x64 Example
```bash
# Extract builds (in CYGWIN environment)
tar -xzf /old-builds/jdk21u-windows-x64-20260512.tar.gz -C /tmp/old-jdk
tar -xzf /new-builds/jdk21u-windows-x64-20260512.tar.gz -C /tmp/new-jdk

# Run comparison
cd temurin-build/tooling/reproducible
./repro_compare.sh \
  temurin /tmp/old-jdk/jdk-21.0.12+1 \
  temurin /tmp/new-jdk/jdk-21.0.12+1 \
  CYGWIN

# Check reproducibility percentage
grep "ReproduciblePercent" reproducible_evidence.log
```

### Output Files

After running the comparison, the following files are generated:

1. **`reprotest.diff`** - Lists files that differ
   ```
   diff: ./bin/java
   diff: ./lib/modules
   ```

2. **`reproducible_evidence.log`** - Detailed comparison evidence
   ```
   Comparing: /tmp/old-jdk/jdk-21.0.12+1
   Against:   /tmp/new-jdk/jdk-21.0.12+1
   Platform:  Linux

   File count: 15,234 (both builds)
   Files compared: 15,234
   Files identical: 15,234
   Files different: 0

   ReproduciblePercent: 100%
   ```

3. **Exit Code**
   - `0` = Builds are identical (100% reproducible)
   - `1` = Builds differ (check reprotest.diff for details)

### Jenkins Integration Example

```groovy
stage('Compare Builds') {
    steps {
        script {
            // Extract both builds
            sh '''
                mkdir -p /tmp/comparison/{old,new}
                tar -xzf ${OLD_BUILD_ARTIFACT} -C /tmp/comparison/old
                tar -xzf ${NEW_BUILD_ARTIFACT} -C /tmp/comparison/new
            '''

            // Run comparison
            def compareResult = sh(
                script: '''
                    cd ${WORKSPACE}/temurin-build/tooling/reproducible
                    ./repro_compare.sh \
                      temurin /tmp/comparison/old/jdk-${VERSION} \
                      temurin /tmp/comparison/new/jdk-${VERSION} \
                      ${PLATFORM}
                ''',
                returnStatus: true
            )

            // Archive results
            archiveArtifacts artifacts: 'temurin-build/tooling/reproducible/reprotest.diff', allowEmptyArchive: true
            archiveArtifacts artifacts: 'temurin-build/tooling/reproducible/reproducible_evidence.log'

            // Fail if not identical
            if (compareResult != 0) {
                error("Build comparison failed - builds are not identical!")
            }

            echo "✓ Build comparison PASSED - builds are identical"
        }
    }
}
```

### Interpreting Results

#### Success Case (100% Reproducible)
```
Files compared: 15,234
Files identical: 15,234
Files different: 0
ReproduciblePercent: 100%
Exit code: 0
```
**Action**: Proceed with migration ✓

#### Failure Case (Differences Found)
```
Files compared: 15,234
Files identical: 15,230
Files different: 4
ReproduciblePercent: 99.97%
Exit code: 1

reprotest.diff contents:
diff: ./bin/java
diff: ./lib/modules
diff: ./lib/server/libjvm.so
diff: ./release
```
**Action**: Investigate differences before proceeding ✗

### Common Differences (Expected)

The tool automatically handles these expected differences:
- Build timestamps
- Build IDs and UUIDs
- Absolute build paths in debug info
- Compiler-generated unique identifiers
- Platform-specific metadata

### Troubleshooting

If builds don't match:

1. **Check reprotest.diff** for list of different files
2. **Review reproducible_evidence.log** for detailed comparison
3. **Verify platform** matches (Linux/Darwin/CYGWIN)
4. **Check preprocessing** ran correctly for the platform
5. **Compare build environments** (compiler versions, flags, etc.)
6. **Review build logs** for differences in build process

### Success Criteria for Migration

For a platform to be approved for migration:
- ✅ **ReproduciblePercent = 100%**
- ✅ **Exit code = 0**
- ✅ **reprotest.diff is empty**
- ✅ **All test results match**
- ✅ **Performance within acceptable range**

### References

- **Tool Location**: `temurin-build/tooling/reproducible/repro_compare.sh`
- **Documentation**: `temurin-build/tooling/reproducible/README.md`
- **Supported Platforms**: Linux, macOS (Darwin), Windows (CYGWIN)
- **Issue Tracker**: Report tool issues to temurin-build repository
*Last Updated: 2026-05-12*
*For: Pipeline Migration Project*