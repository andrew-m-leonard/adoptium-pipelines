# Pipeline Orchestration Architecture

## Overview

This document describes the fundamental shift in how Adoptium build pipelines are orchestrated, moving from a daisy-chained monolithic approach to independent platform-based pipelines that provide clear separation between build success and test results, enabling better restartability, accurate status reporting, and distributed test execution across multiple Jenkins instances for improved scalability and resilience.

## Problem Statement

The original pipeline architecture had critical flaws that prevented effective use of CI restart capabilities and created misleading status reporting.

### Business Impact
- **Misleading Status**: Build pipelines reported as FAILED when only a single test case failed
- **Lost Context**: Cannot distinguish between build failures and test failures
- **Fragile Artifact Flow**: Extra copy step from downstream to top-level can lose artifacts
- **No Build Restartability**: Cannot restart build stages independently of tests
- **Cascading Failures**: Test failures propagate up and mask successful builds

## Old Architecture: Daisy-Chained Orchestration

### Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│ Top-Level "Release Trigger" Pipeline                           │
│ (Collects all artifacts from downstream)                       │
└────────┬────────────────────────────────────────────────────────┘
         │
         │ Triggers all platform build pipelines
         │
         ├──────────┬──────────┬──────────┬──────────┬──────────┐
         ▼          ▼          ▼          ▼          ▼          ▼
    ┌─────────────────────────────────────────────────────────────┐
    │ Platform Build Pipeline (e.g., Linux x64)                   │
    │                                                             │
    │ ┌─────────────────────────────────────────────────────┐   │
    │ │ Build Stages (Compile, Sign, Installer, SBOM)      │   │
    │ │ Status: ✅ SUCCESS                                   │   │
    │ └─────────────────────────────────────────────────────┘   │
    │                        │                                    │
    │                        │ Triggers downstream                │
    │                        ▼                                    │
    │ ┌─────────────────────────────────────────────────────┐   │
    │ │ AQA Test Job 1                                      │   │
    │ │ ├─ Test Suite A: ✅ PASS (10,000 tests)             │   │
    │ │ ├─ Test Suite B: ✅ PASS (15,000 tests)             │   │
    │ │ └─ Test Suite C: ❌ FAIL (1 test out of 20,000)     │   │
    │ │ Status: ❌ UNSTABLE                                  │   │
    │ └─────────────────────────────────────────────────────┘   │
    │                        │                                    │
    │                        │ Propagates status up               │
    │                        ▼                                    │
    │ Overall Pipeline Status: ❌ UNSTABLE                        │
    │                                                             │
    │ ⚠️  PROBLEM: Build was successful but pipeline shows       │
    │     UNSTABLE due to 1 test failure out of 45,000 tests    │
    └─────────────────────────────────────────────────────────────┘
                             │
                             │ Artifacts copied back to top-level
                             │ ⚠️  Extra copy step can fail
                             ▼
    ┌─────────────────────────────────────────────────────────────┐
    │ Top-Level Pipeline                                          │
    │ ├─ Collect Linux x64 artifacts    ✅                        │
    │ ├─ Collect Linux aarch64 artifacts ❌ Copy failed           │
    │ ├─ Collect Mac x64 artifacts      ✅                        │
    │ ├─ Collect Mac aarch64 artifacts  ✅                        │
    │ ├─ Collect Windows x64 artifacts  ✅                        │
    │ └─ Collect Windows x32 artifacts  ✅                        │
    │                                                             │
    │ ⚠️  PROBLEM: Linux aarch64 build succeeded but artifacts   │
    │     lost due to copy failure                               │
    └─────────────────────────────────────────────────────────────┘
```

### Critical Problems

#### 1. **Misleading Status Reporting**

**Problem**: Build pipeline status includes test results, making it impossible to distinguish build success from test success.

```
Scenario: Linux x64 Build Pipeline

Build Stages:
├─ Compile:    ✅ SUCCESS
├─ Sign:       ✅ SUCCESS
├─ Installer:  ✅ SUCCESS
└─ SBOM:       ✅ SUCCESS

AQA Tests (triggered as downstream):
├─ Test Suite A: ✅ 10,000 tests passed
├─ Test Suite B: ✅ 15,000 tests passed
└─ Test Suite C: ❌ 1 test failed (out of 20,000)

Pipeline Status: ❌ UNSTABLE

⚠️  PROBLEM:
- Build was 100% successful
- Only 1 test out of 45,000 failed (99.998% pass rate)
- But pipeline shows UNSTABLE
- Cannot tell if build failed or test failed
- Release team sees "UNSTABLE" and doesn't know what failed
```

#### 2. **Fragile Artifact Collection**

**Problem**: Extra copy step from downstream build pipeline to top-level pipeline can fail, losing artifacts even though build succeeded.

```
Scenario: Artifact Copy Failure

Linux aarch64 Build Pipeline:
├─ Build completed successfully
├─ Artifacts stored in build pipeline: ✅
└─ Copy artifacts to top-level: ❌ Network timeout

Result:
- Build artifacts exist in downstream pipeline
- But top-level pipeline doesn't have them
- Artifacts effectively "lost" for release
- Must re-run entire build to get artifacts again
```

#### 3. **No Independent Restartability**

**Problem**: Cannot restart build stages independently of tests, or vice versa.

```
Scenario: Need to re-run tests only

Current Situation:
- Build completed successfully 2 hours ago
- 1 test failed due to infrastructure issue (not code)
- Want to re-run just the failed test

Required Actions:
❌ Cannot restart just the test
❌ Must restart entire build pipeline
❌ Wastes 2 hours rebuilding (compile, sign, installer, SBOM)
❌ Wastes compute resources
```

#### 4. **Cascading Status Propagation**

**Problem**: Test failures propagate up through the entire chain, masking successful builds.

```
Build Pipeline Hierarchy:

Top-Level Pipeline
└─ Linux x64 Build Pipeline (shows UNSTABLE)
   ├─ Build Stages (all SUCCESS)
   └─ AQA Test Job (UNSTABLE due to 1 test)
      └─ Test failure propagates up

Result:
- Top-level shows: "Linux x64: UNSTABLE"
- Cannot see that build was successful
- Cannot see that 99.998% of tests passed
- Misleading for release decisions
```

## New Architecture: Independent Platform Pipelines

### Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│ Release Trigger Event                                           │
│ (e.g., "Build JDK 21.0.5+11")                                  │
└────────┬────────────────────────────────────────────────────────┘
         │
         │ Triggers N independent platform BUILD pipelines
         │
         ├──────────┬──────────┬──────────┬──────────┬──────────┐
         ▼          ▼          ▼          ▼          ▼          ▼
    ┌─────────────────────────────────────────────────────────────┐
    │ Platform BUILD Pipeline (e.g., Linux x64)                   │
    │ ⭐ ONLY BUILD STAGES - NO TESTS                             │
    │                                                             │
    │ ┌─────────────────────────────────────────────────────┐   │
    │ │ Build Stages (Restartable)                          │   │
    │ │ ├─ 1. Compile      ✓ Can restart from here         │   │
    │ │ ├─ 2. Sign         ✓ Can restart from here         │   │
    │ │ ├─ 3. Installer    ✓ Can restart from here         │   │
    │ │ ├─ 4. SBOM         ✓ Can restart from here         │   │
    │ │ └─ 5. Smoke Test   ✓ Can restart from here         │   │
    │ │                                                       │   │
    │ │ Status: ✅ SUCCESS (Build completed)                 │   │
    │ └─────────────────────────────────────────────────────┘   │
    │                                                             │
    │ ✅ Artifacts stored within THIS pipeline                    │
    │ ✅ No extra copy step - artifacts stay here                 │
    │ ✅ Clear status: Build succeeded or failed                  │
    └────────┬────────────────────────────────────────────────────┘
             │
             │ On BUILD SUCCESS, trigger independent TEST pipeline
             │
             ▼
    ┌─────────────────────────────────────────────────────────────┐
    │ Platform TEST Pipeline (e.g., Linux x64 AQA Tests)          │
    │ ⭐ INDEPENDENT PIPELINE - SEPARATE STATUS                   │
    │                                                             │
    │ ┌─────────────────────────────────────────────────────┐   │
    │ │ Test Suites (Restartable)                           │   │
    │ │ ├─ Test Suite A: ✅ 10,000 tests passed             │   │
    │ │ ├─ Test Suite B: ✅ 15,000 tests passed             │   │
    │ │ └─ Test Suite C: ❌ 1 test failed (out of 20,000)   │   │
    │ │                                                       │   │
    │ │ Status: ❌ UNSTABLE (1 test failed)                  │   │
    │ │                                                       │   │
    │ │ ✓ Can restart just this test suite                  │   │
    │ │ ✓ No need to rebuild                                │   │
    │ └─────────────────────────────────────────────────────┘   │
    │                                                             │
    │ ✅ Test status does NOT affect build pipeline status        │
    │ ✅ Can restart tests without rebuilding                     │
    │ ✅ Clear separation: Build vs Test results                  │
    └─────────────────────────────────────────────────────────────┘
```

### Key Improvements

#### 1. **Clear Status Separation**

**Before**: Build pipeline shows UNSTABLE due to test failure
```
Linux x64 Build Pipeline: ❌ UNSTABLE
└─ Reason: 1 test failed out of 45,000
   (But build was 100% successful!)
```

**After**: Build and test status are independent
```
Linux x64 Build Pipeline: ✅ SUCCESS
└─ All build stages completed successfully

Linux x64 Test Pipeline: ❌ UNSTABLE
└─ 1 test failed out of 45,000 (99.998% pass rate)
```

**Benefit**: Release team can immediately see:
- Build succeeded → Artifacts are ready for release
- Tests mostly passed → Only 1 test needs investigation
- Can release build while investigating test failure

#### 2. **No Artifact Copy Step**

**Before**: Artifacts copied from downstream to top-level
```
Build Pipeline → Artifacts → Copy to Top-Level
                              ↓
                         ❌ Copy can fail
                         ❌ Artifacts lost
```

**After**: Artifacts stay in build pipeline
```
Build Pipeline → Artifacts stored here
                 ↓
            ✅ No copy step
            ✅ Artifacts safe
            ✅ Test pipeline references them
```

#### 3. **Independent Restartability**

**Before**: Must restart entire pipeline
```
Need to re-run 1 failed test:
❌ Restart entire build pipeline (2 hours)
❌ Rebuild everything
❌ Then re-run tests
```

**After**: Restart only what failed
```
Need to re-run 1 failed test:
✅ Build pipeline: Already complete (no action)
✅ Test pipeline: Restart failed test suite (10 minutes)
✅ No rebuild needed
```

#### 3a. **Distributed Test Execution (Scalability & Resilience)**

**Critical Advantage**: AQA Test Pipelines can be triggered on **local OR remote Jenkins instances**

**Architecture Flexibility**:
```
Build Pipeline (Jenkins Instance A)
    │
    │ Triggers test pipeline with artifact reference
    │
    ├──────────────┬──────────────┬──────────────┐
    ▼              ▼              ▼              ▼
Local Jenkins   Remote Jenkins  Remote Jenkins  Remote Jenkins
(Instance A)    (Instance B)    (Instance C)    (Instance D)
    │              │              │              │
    ▼              ▼              ▼              ▼
Test Suite A   Test Suite B   Test Suite C   Test Suite D
```

**Scalability Benefits**:
```
Old Architecture (Single Jenkins):
├─ All tests run on same Jenkins instance
├─ Limited by single instance capacity
├─ Queue delays when multiple platforms test
└─ Bottleneck: 1 instance handles all 45,000 tests

New Architecture (Distributed):
├─ Tests distributed across multiple Jenkins instances
├─ Parallel execution without queue delays
├─ Each instance handles subset of tests
└─ Scalability: N instances = N× test throughput
```

**Resilience Benefits**:
```
Scenario: Jenkins Instance Failure

Old Architecture:
├─ Single Jenkins instance fails
├─ ❌ All testing stops
├─ ❌ Cannot run any tests until instance recovered
└─ ❌ Complete testing blockage

New Architecture:
├─ One Jenkins instance fails
├─ ✅ Other instances continue testing
├─ ✅ Failed tests can be re-triggered on different instance
└─ ✅ No complete blockage - partial degradation only
```

**Real-World Example**:
```
Scenario: Testing JDK 21.0.5 across 12 platforms

Old Architecture:
├─ All 12 platforms queue on single Jenkins
├─ Platform 1: Tests at Hour 0
├─ Platform 2: Tests at Hour 2 (waits for Platform 1)
├─ Platform 3: Tests at Hour 4 (waits for Platform 2)
└─ Total time: 24 hours (sequential)

New Architecture:
├─ Platform 1 → Jenkins Instance A (Hour 0)
├─ Platform 2 → Jenkins Instance B (Hour 0)
├─ Platform 3 → Jenkins Instance C (Hour 0)
├─ ... all platforms test in parallel
└─ Total time: 2 hours (parallel)

Improvement: 12× faster testing
```

**Geographic Distribution**:
```
Build Artifacts (Central Location)
    │
    ├─────────────┬─────────────┬─────────────┐
    ▼             ▼             ▼             ▼
US Jenkins    EU Jenkins    APAC Jenkins  Local Jenkins
    │             │             │             │
    ▼             ▼             ▼             ▼
US Tests      EU Tests      APAC Tests    Dev Tests

Benefits:
✅ Reduced network latency (tests run near artifacts)
✅ Compliance (data stays in region if needed)
✅ Load distribution across geographic regions
✅ Developer testing on local Jenkins without affecting production
```

**Failure Recovery**:
```
Scenario: Remote Jenkins Instance Becomes Unavailable

Action:
1. Detect instance failure
2. Re-trigger test pipeline on different Jenkins instance
3. Reference same build artifacts (still available)
4. Continue testing without rebuild

Old Architecture:
❌ Would require complete pipeline restart
❌ Would lose all progress
❌ Would waste hours of work

New Architecture:
✅ Re-trigger on different instance (5 minutes)
✅ Keep all progress from other instances
✅ Only re-run tests from failed instance
```

#### 4. **Accurate Status Reporting**

**Before**: Confusing status
```
Dashboard shows:
├─ Linux x64: UNSTABLE
├─ Mac x64: UNSTABLE
└─ Windows x64: SUCCESS

Question: Did builds fail or tests fail?
Answer: Unknown without deep investigation
```

**After**: Clear status
```
Dashboard shows:

BUILD PIPELINES:
├─ Linux x64 Build: ✅ SUCCESS
├─ Mac x64 Build: ✅ SUCCESS
└─ Windows x64 Build: ✅ SUCCESS

TEST PIPELINES:
├─ Linux x64 Tests: ❌ UNSTABLE (1 test failed)
├─ Mac x64 Tests: ✅ SUCCESS
└─ Windows x64 Tests: ✅ SUCCESS

Answer: All builds succeeded, 1 test needs investigation
```

## Detailed Comparison

### Scenario: Single Test Failure

#### Old Architecture
```
Timeline:
Hour 0:   Release trigger starts
Hour 1:   Linux x64 build completes (compile, sign, installer, SBOM)
Hour 1.5: AQA tests start (45,000 tests)
Hour 3:   Test Suite C fails (1 test out of 20,000)
Hour 3:   Pipeline status: UNSTABLE

Problems:
❌ Build pipeline shows UNSTABLE (but build was successful!)
❌ Cannot tell if build failed or test failed
❌ Cannot restart just the failed test
❌ Must restart entire pipeline to re-run test
❌ Wastes 3 hours rebuilding everything

Release Team Sees:
"Linux x64: UNSTABLE"
└─ What failed? Build or test?
└─ Can we release? Unknown
└─ How to fix? Must investigate deeply
```

#### New Architecture
```
Timeline:
Hour 0:   Release trigger starts
Hour 1:   Linux x64 BUILD pipeline completes
Hour 1:   Build status: ✅ SUCCESS
Hour 1:   Artifacts stored in build pipeline
Hour 1:   TEST pipeline triggered automatically
Hour 1.5: AQA tests start (45,000 tests)
Hour 3:   Test Suite C fails (1 test out of 20,000)
Hour 3:   Test pipeline status: UNSTABLE
Hour 3:   Build pipeline status: STILL SUCCESS ✅

Actions:
✅ Build pipeline: SUCCESS - artifacts ready for release
✅ Test pipeline: UNSTABLE - 1 test needs investigation
✅ Can restart just Test Suite C (10 minutes)
✅ No rebuild needed
✅ Other platforms continue testing

Release Team Sees:
"Linux x64 Build: ✅ SUCCESS"
"Linux x64 Tests: ❌ UNSTABLE (1/45,000 tests failed)"
└─ Build succeeded → Artifacts ready
└─ 99.998% tests passed → Can release
└─ 1 test needs investigation → Restart test only
```

### Scenario: Artifact Copy Failure

#### Old Architecture
```
Timeline:
Hour 0: Linux aarch64 build completes successfully
Hour 1: Artifacts being copied to top-level pipeline
Hour 1: ❌ Network timeout during copy
Hour 1: Artifacts lost from top-level perspective

Problems:
❌ Build succeeded but artifacts not in top-level
❌ Artifacts exist in downstream but inaccessible
❌ Must re-run entire build to get artifacts
❌ Wastes 1 hour of successful build work

Recovery:
1. Restart entire build pipeline
2. Wait 1 hour for rebuild
3. Hope copy succeeds this time
```

#### New Architecture
```
Timeline:
Hour 0: Linux aarch64 build completes successfully
Hour 1: Artifacts stored in build pipeline
Hour 1: ✅ No copy step needed
Hour 1: Test pipeline references artifacts directly

Benefits:
✅ Artifacts stay in build pipeline
✅ No copy step to fail
✅ Test pipeline accesses artifacts directly
✅ No risk of losing artifacts

Recovery:
Not needed - artifacts are safe
```

## Implementation Benefits

### 1. Operational Excellence

**Clear Status Reporting**
- Old: "UNSTABLE" (ambiguous)
- New: "Build: SUCCESS, Tests: UNSTABLE" (clear)
- **Improvement: Instant clarity on what failed**

**Faster Recovery**
- Old: Restart entire pipeline (2-3 hours)
- New: Restart failed component only (10-15 minutes)
- **Improvement: 12x faster recovery**

**Artifact Safety**
- Old: Extra copy step can fail
- New: No copy step, artifacts stay in place
- **Improvement: 100% artifact retention**

**Distributed Test Execution**
- Old: Single Jenkins instance (bottleneck, single point of failure)
- New: Multiple Jenkins instances (scalable, resilient)
- **Improvement: 12× faster testing, unlimited scalability**

### 2. Release Management

**Better Decision Making**
```
Old Dashboard:
├─ Linux x64: UNSTABLE
└─ Decision: Unknown if we can release

New Dashboard:
├─ Linux x64 Build: SUCCESS
├─ Linux x64 Tests: UNSTABLE (1/45,000 failed)
└─ Decision: Can release, 1 test needs investigation
```

**Partial Releases**
- Can release platforms with successful builds
- Even if some tests are still running
- Or if some tests need investigation

### 3. Developer Experience

**Faster Iteration**
```
Old: Test failed, need to re-run
├─ Restart entire pipeline
├─ Wait 2 hours for rebuild
├─ Wait 1 hour for tests
└─ Total: 3 hours

New: Test failed, need to re-run
├─ Build already complete
├─ Restart test only
└─ Total: 10 minutes
```

**Clear Feedback**
- Know immediately if build failed vs test failed
- Can focus investigation on right component
- No confusion about pipeline status

### 4. Cost Efficiency

**Reduced Waste**
```
Scenario: 1 test fails out of 45,000

Old Cost:
├─ Rebuild: 2 hours compute
├─ Re-test: 1 hour compute
└─ Total: 3 hours wasted

New Cost:
├─ Rebuild: 0 hours (not needed)
├─ Re-test: 10 minutes (single suite)
└─ Total: 10 minutes
```

**Improvement: 95% cost reduction**

## Migration Strategy

### Phase 1: Separate Build and Test Pipelines
1. Create independent build pipeline (build stages only)
2. Create independent test pipeline (tests only)
3. Build pipeline triggers test pipeline on success
4. Artifacts stay in build pipeline

### Phase 2: Update Status Reporting
1. Build pipeline reports only build status
2. Test pipeline reports only test status
3. Update dashboards to show both separately
4. Train team on new status interpretation

### Phase 3: Implement Restartability
1. Enable stage-level restart in build pipeline
2. Enable test suite restart in test pipeline
3. Remove dependency between build and test restarts
4. Document restart procedures

### Phase 4: Remove Artifact Copying
1. Test pipeline references build artifacts directly
2. Remove copy step from build to top-level
3. Update artifact storage strategy
4. Validate artifact accessibility

### Phase 5: Deprecate Old Architecture
1. Run both architectures in parallel (validation)
2. Compare status clarity and recovery times
3. Migrate all platforms to new architecture
4. Decommission old top-level collection pipeline

## Monitoring and Observability

### Old Architecture
```
Single View (Confusing):
├── Linux x64: UNSTABLE
    └── Problem: Is it build or test?
    └── Action: Must investigate to find out
```

### New Architecture
```
Clear Separation:
├── BUILD PIPELINES
│   ├── Linux x64 Build: ✅ SUCCESS
│   │   └── Artifacts: Ready for release
│   └── Mac x64 Build: ❌ FAILED at Sign stage
│       └── Action: Restart from Sign stage
│
└── TEST PIPELINES
    ├── Linux x64 Tests: ❌ UNSTABLE (1/45,000 failed)
    │   └── Action: Restart Test Suite C
    └── Mac x64 Tests: ⏳ WAITING (build not complete)
        └── Action: None (waiting for build)
```

## Conclusion

The shift from daisy-chained to independent build and test pipelines represents a fundamental improvement in clarity, reliability, and efficiency:

### Key Takeaways

1. **Clear Status Separation**: Build success vs test success are independent
2. **No Misleading Status**: Build pipeline shows only build status
3. **Artifact Safety**: No extra copy step to fail
4. **Independent Restartability**: Restart builds or tests independently
5. **Distributed Test Execution**: Tests can run on local or remote Jenkins instances
6. **Scalability**: Unlimited test parallelization across multiple Jenkins instances
7. **Resilience**: Instance failures don't stop all testing
8. **Faster Recovery**: 12× faster (minutes vs hours)
9. **Better Decisions**: Release team knows exactly what succeeded/failed
10. **Cost Reduction**: 95% less wasted compute

### Success Metrics

- **Status Clarity**: Ambiguous → Crystal clear
- **Recovery Time**: 2-3 hours → 10-15 minutes
- **Test Parallelization**: Sequential (24 hours) → Parallel (2 hours)
- **Scalability**: Single instance limit → Unlimited (add more instances)
- **Resilience**: Single point of failure → Distributed (partial degradation only)
- **Artifact Loss**: Possible → Impossible
- **Wasted Rebuilds**: Common → Never
- **Release Confidence**: Low → High

This architecture change is essential for achieving the operational excellence, clarity, and reliability required for production-grade OpenJDK releases.

---

**Related Documentation:**
- [CI-Agnostic Architecture](../CI_AGNOSTIC_ARCHITECTURE.md) - Overall architecture design
- [Restartability Guide](./RESTARTABILITY_GUIDE.md) - Stage restart implementation
- [Workspace Architecture](../WORKSPACE_ARTIFACTS_ARCHITECTURE.md) - Artifact management