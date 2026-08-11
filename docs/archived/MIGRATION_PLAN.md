# OpenJDK Build Pipeline Migration Plan

## Executive Summary

This document outlines the step-by-step migration strategy from the current monolithic [`openjdk_build_pipeline.groovy`](../../ci-jenkins-pipelines/pipelines/build/common/openjdk_build_pipeline.groovy) to the new modular, CI-agnostic architecture.

### Why Refactor?

The current Jenkins-specific scripted pipeline has served well but faces significant limitations as the project scales. This refactoring delivers substantial benefits:

**Operational Excellence:**
- **Restartability**: Declarative pipelines support "Restart from Stage" - eliminating costly full rebuilds when late-stage failures occur (e.g., restart from signing instead of rebuilding JDK)
- **Faster Debugging**: Modular shell scripts can be tested locally without Jenkins, reducing iteration time from minutes to seconds
- **Reduced CI Lock-in**: 90% of build logic moves to portable shell scripts, making future CI platform migrations trivial

**Maintainability & Quality:**
- **Clear Separation of Concerns**: Build logic (shell), configuration (JSON), and orchestration (Jenkinsfile) are cleanly separated
- **Easier Testing**: Each stage script can be unit tested independently; `run-pipeline.py` enables full local pipeline execution
- **Better Code Review**: Smaller, focused files are easier to review than a 2000+ line Groovy monolith
- **Reduced Complexity**: Eliminates deeply nested Groovy closures and implicit Jenkins dependencies

**Team Productivity:**
- **Lower Barrier to Entry**: New contributors can understand and modify shell scripts without learning Jenkins/Groovy
- **Parallel Development**: Multiple team members can work on different stages without merge conflicts
- **Reusable Components**: Stage scripts become building blocks for other pipelines (e.g., nightly builds, release candidates)

**Risk Mitigation:**
- **Incremental Migration**: Parallel execution validates new pipeline against production before cutover
- **Easy Rollback**: Old pipeline remains available during migration
- **Platform Independence**: Reduces vendor lock-in risk if Jenkins becomes unsuitable

**Key Principles:**
- ✅ Zero downtime migration
- ✅ Parallel execution for validation
- ✅ Incremental rollout by platform/version
- ✅ Comprehensive testing at each phase
- ✅ Easy rollback capability

---

## Migration Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    MIGRATION TIMELINE (ACCELERATED)              │
│                                                                  │
│  Phase 1: Foundation (1 week)                                   │
│  ├─ Setup infrastructure (tooling exists)                       │
│  ├─ Integrate repro_compare.sh                                  │
│  └─ Configure parallel execution                                │
│                                                                  │
│  Phase 2: Pilot (2 weeks)                                       │
│  ├─ Linux x64 JDK21u pilot                                      │
│  ├─ Run 5 parallel validation builds                            │
│  └─ Document edge cases                                         │
│                                                                  │
│  Phase 3: Rapid Rollout (5-7 weeks)                             │
│  ├─ Week 3-4: Tier 1 (Linux x64 all versions)                  │
│  ├─ Week 5-6: Tier 2 (Mac + Windows primary)                   │
│  └─ Week 7-9: Tier 3 (remaining platforms)                     │
│                                                                  │
│  Phase 4: Completion (2-4 weeks)                                │
│  ├─ Final platform migrations                                   │
│  ├─ Decommission old pipeline                                   │
│  └─ Team training & documentation                               │
│                                                                  │
│  Total Duration: 10-14 weeks (2.5-3.5 months)                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Foundation (Week 1)

### Objectives
- Establish infrastructure for new pipeline
- Create tooling for parallel execution
- Set up comparison framework

### Deliverables

#### 1.1 Infrastructure Setup
```
Repository Structure:
ci-jenkins-pipelines/
├── pipelines/
│   ├── build/
│   │   ├── common/
│   │   │   ├── openjdk_build_pipeline.groovy          # OLD (keep)
│   │   │   └── openjdk_build_pipeline_v2.groovy       # NEW
│   │   └── modular/                                    # NEW
│   │       ├── scripts/
│   │       │   ├── stages/
│   │       │   │   ├── 01-initialize.sh
│   │       │   │   ├── 02-build.sh
│   │       │   │   ├── 06-sign.sh
│   │       │   │   ├── 07-installer.sh
│   │       │   │   └── 13-smoke-tests.sh
│   │       │   └── lib/
│   │       │       ├── logging-utils.sh
│   │       │       ├── config-utils.sh
│   │       │       └── artifact-utils.sh
│   │       ├── configurations/
│   │       │   └── *.json
│   │       └── tools/
│   │           └── convert-groovy-config-to-json.sh
│   └── comparison/                                     # NEW
│       └── compare-builds.groovy
```

#### 1.2 Conversion Tools
- **Config Converter**: Groovy → JSON configuration converter (already exists)
- **Build Comparator**: Use existing `repro_compare.sh` tool
- **Validation Framework**: Automated checks for build equivalence

#### 1.3 Testing Infrastructure
- **Parallel Job Setup**: Jenkins jobs that run both pipelines
- **Artifact Storage**: Separate storage for old/new builds
- **Comparison Dashboard**: Visual comparison of results

### Tasks (GitHub Issues)

**EPIC 1: Foundation Infrastructure** (Week 1)
- [ ] Issue #1.1: Create new repository structure (2 days)
- [ ] Issue #1.2: Implement config conversion tool (1 day - already exists)
- [ ] Issue #1.3: Integrate existing repro_compare.sh tool (1 day)
- [ ] Issue #1.4: Set up parallel execution jobs (2 days)
- [ ] Issue #1.5: Create comparison dashboard (1 day)

---

## Phase 2: Pilot (Weeks 2-3)

### Objectives
- Validate new pipeline with single platform
- Identify and document edge cases
- Establish confidence in new approach

### Pilot Selection Criteria

**Recommended Pilot: Linux x64 JDK21u Temurin**

Rationale:
- ✅ Most common platform
- ✅ Well-tested configuration
- ✅ Fastest build times
- ✅ Minimal edge cases
- ✅ Large user base for validation

### Parallel Execution Strategy

```
┌─────────────────────────────────────────────────────────────────┐
│                    PARALLEL EXECUTION                            │
│                                                                  │
│  Trigger: Git commit or scheduled build                         │
│     │                                                            │
│     ├──► OLD Pipeline (openjdk_build_pipeline.groovy)           │
│     │      │                                                     │
│     │      ├─ Build JDK                                          │
│     │      ├─ Sign artifacts                                     │
│     │      ├─ Create installers                                  │
│     │      ├─ Run tests                                          │
│     │      └─ Store artifacts → /old-builds/                     │
│     │                                                            │
│     └──► NEW Pipeline (openjdk_build_pipeline_v2.groovy)        │
│            │                                                     │
│            ├─ Initialize (convert config)                        │
│            ├─ Build JDK (02-build.sh)                           │
│            ├─ Sign artifacts (06-sign.sh)                        │
│            ├─ Create installers (07-installer.sh)               │
│            ├─ Run tests (13-smoke-tests.sh)                     │
│            └─ Store artifacts → /new-builds/                     │
│                                                                  │
│  Compare Results:                                                │
│     │                                                            │
│     └──► Comparison Job                                          │
│            │                                                     │
│            ├─ Binary diff of JDK artifacts                       │
│            ├─ Checksum comparison                                │
│            ├─ Metadata validation                                │
│            ├─ Test result comparison                             │
│            └─ Performance metrics                                │
│                                                                  │
│  Report: Dashboard showing differences (if any)                  │
└─────────────────────────────────────────────────────────────────┘
```

### Comparison Criteria

#### Must Match Exactly:
1. **JDK Binary**: Byte-for-byte identical (excluding timestamps)
2. **Checksums**: SHA256 sums must match
3. **Version Strings**: Identical version output
4. **Test Results**: Same pass/fail status

#### Acceptable Differences:
1. **Build Timestamps**: Different build times
2. **Log Format**: Different logging structure
3. **Intermediate Files**: Different temp file names
4. **Build Duration**: Performance may vary

### Edge Case Discovery

During pilot, document:
- Platform-specific quirks
- Docker container builds
- Cross-compilation scenarios
- Custom build arguments
- Special signing requirements
- Network/firewall issues

### Tasks (GitHub Issues)

**EPIC 2: Pilot Execution** (Weeks 2-3)
- [ ] Issue #2.1: Set up Linux x64 JDK21u pilot (2 days)
- [ ] Issue #2.2: Configure parallel execution (1 day)
- [ ] Issue #2.3: Run 5 parallel validation builds (3 days)
- [ ] Issue #2.4: Analyze comparison results (1 day)
- [ ] Issue #2.5: Document edge cases found (1 day)
- [ ] Issue #2.6: Fix identified issues (2 days)
- [ ] Issue #2.7: Validate fixes with 3 more builds (2 days)

---

## Phase 3: Rapid Rollout (Weeks 4-10)

### Objectives
- Expand to all platforms incrementally
- Handle platform-specific edge cases
- Build confidence across all configurations

### Rollout Strategy

```
┌─────────────────────────────────────────────────────────────────┐
│                    ACCELERATED ROLLOUT SEQUENCE                  │
│                                                                  │
│  Week 4:     Tier 1 - Linux x64 (All Versions)                  │
│  ├─ JDK21u Temurin        ✓ (Pilot complete)                   │
│  ├─ JDK17u Temurin        (parallel migration)                  │
│  ├─ JDK11u Temurin        (parallel migration)                  │
│  └─ JDK8u Temurin         (parallel migration)                  │
│                                                                  │
│  Week 5-6:   Tier 2 - Mac & Windows (Primary Versions)         │
│  ├─ Mac aarch64 JDK21u + JDK17u (parallel)                     │
│  ├─ Mac x64 JDK21u + JDK17u (parallel)                         │
│  ├─ Windows x64 JDK21u + JDK17u (parallel)                     │
│  └─ Windows x86-32 JDK8u                                        │
│                                                                  │
│  Week 7-8:   Tier 3 - Alternative Architectures                 │
│  ├─ Linux aarch64 (all versions - parallel)                    │
│  ├─ Linux ppc64le (all versions - parallel)                    │
│  ├─ Linux s390x (all versions - parallel)                      │
│  └─ Linux riscv64 (if applicable)                              │
│                                                                  │
│  Week 9-10:  Final Platforms & Edge Cases                       │
│  ├─ AIX ppc64 (all versions)                                   │
│  ├─ Solaris (if still supported)                               │
│  ├─ Docker container builds                                     │
│  ├─ Cross-compilation scenarios                                 │
│  └─ Custom configurations                                       │
└─────────────────────────────────────────────────────────────────┘
```

### Platform-Specific Considerations

#### Linux
- **Standard**: Straightforward migration
- **Docker**: May need container-specific scripts
- **Cross-compile**: Requires toolchain setup

#### macOS
- **Code Signing**: Apple Developer certificates
- **Notarization**: Apple notarization process
- **Rosetta**: x64 on aarch64 considerations

#### Windows
- **Visual Studio**: Compiler setup
- **Code Signing**: Windows Authenticode
- **MSI Building**: WiX toolset requirements

#### AIX
- **Toolchain**: IBM XL compiler
- **Limited Resources**: Fewer build machines
- **Testing**: Limited test infrastructure

### Rollout Checklist (Per Platform)

For each platform/version combination:

1. **Preparation**
   - [ ] Convert configuration to JSON
   - [ ] Verify all dependencies available
   - [ ] Set up parallel execution job

2. **Execution**
   - [ ] Run 5 parallel builds
   - [ ] Compare all artifacts
   - [ ] Validate test results
   - [ ] Check performance metrics

3. **Validation**
   - [ ] Binary comparison passes
   - [ ] Checksums match
   - [ ] Tests pass identically
   - [ ] No regressions found

4. **Documentation**
   - [ ] Document any edge cases
   - [ ] Update platform-specific notes
   - [ ] Record performance data

5. **Sign-off**
   - [ ] Team review
   - [ ] Stakeholder approval
   - [ ] Mark platform as migrated

### Tasks (GitHub Issues)

**EPIC 3: Tier 1 Rollout** (Week 4)
- [ ] Issue #3.1: Migrate Linux x64 JDK17u (2 days)
- [ ] Issue #3.2: Migrate Linux x64 JDK11u (2 days)
- [ ] Issue #3.3: Migrate Linux x64 JDK8u (2 days)
- [ ] Issue #3.4: Validate all Tier 1 platforms (1 day)

**EPIC 4: Tier 2 Rollout** (Weeks 5-6)
- [ ] Issue #4.1: Migrate Mac aarch64 JDK21u + JDK17u (3 days)
- [ ] Issue #4.2: Migrate Mac x64 JDK21u + JDK17u (3 days)
- [ ] Issue #4.3: Migrate Windows x64 JDK21u + JDK17u (3 days)
- [ ] Issue #4.4: Migrate Windows x86-32 JDK8u (2 days)
- [ ] Issue #4.5: Validate all Tier 2 platforms (1 day)

**EPIC 5: Tier 3 Rollout** (Weeks 7-8)
- [ ] Issue #5.1: Migrate Linux aarch64 (all versions - 3 days)
- [ ] Issue #5.2: Migrate Linux ppc64le (all versions - 3 days)
- [ ] Issue #5.3: Migrate Linux s390x (all versions - 3 days)
- [ ] Issue #5.4: Validate all Tier 3 platforms (1 day)

**EPIC 6: Final Platforms & Edge Cases** (Weeks 9-10)
- [ ] Issue #6.1: Migrate AIX ppc64 (all versions - 3 days)
- [ ] Issue #6.2: Handle Docker container builds (2 days)
- [ ] Issue #6.3: Handle cross-compilation scenarios (2 days)
- [ ] Issue #6.4: Handle custom configurations (2 days)
- [ ] Issue #6.5: Document all edge cases (1 day)

---

## Phase 4: Completion (Weeks 11-14)

### Objectives
- Complete migration of all platforms
- Decommission old pipeline
- Finalize documentation

### Cutover Strategy

```
┌─────────────────────────────────────────────────────────────────┐
│                    ACCELERATED CUTOVER PROCESS                   │
│                                                                  │
│  Week 11: Final Validation                                      │
│  ├─ All platforms running in parallel                           │
│  ├─ 100% comparison success rate                                │
│  ├─ Performance metrics acceptable                              │
│  └─ Stakeholder sign-off                                        │
│                                                                  │
│  Week 12: Cutover Preparation                                   │
│  ├─ Announce cutover date (3 days notice)                       │
│  ├─ Prepare rollback plan                                       │
│  ├─ Update documentation                                        │
│  └─ Conduct team training                                       │
│                                                                  │
│  Week 13: Cutover Execution                                     │
│  ├─ Switch default to new pipeline                              │
│  ├─ Keep old pipeline available (1 week)                        │
│  ├─ Monitor closely for issues                                  │
│  └─ Ready to rollback if needed                                 │
│                                                                  │
│  Week 14: Stabilization & Decommission                          │
│  ├─ Monitor production builds (3 days)                          │
│  ├─ Address any issues quickly                                  │
│  ├─ Archive old pipeline                                        │
│  ├─ Remove parallel execution                                   │
│  ├─ Clean up old artifacts                                      │
│  └─ Celebrate success! 🎉                                       │
└─────────────────────────────────────────────────────────────────┘
```

### Rollback Plan

If critical issues arise:

1. **Immediate Rollback** (< 1 hour)
   - Switch Jenkins default back to old pipeline
   - All builds continue with old pipeline
   - New pipeline disabled but not removed

2. **Investigation** (1-3 days)
   - Analyze root cause
   - Develop fix
   - Test fix in isolation

3. **Re-attempt** (1 week)
   - Deploy fix
   - Re-enable new pipeline
   - Monitor closely

### Success Criteria

Migration is complete when:
- ✅ All platforms migrated
- ✅ 100% artifact comparison success
- ✅ No performance regressions
- ✅ Team trained and confident
- ✅ Documentation complete
- ✅ Old pipeline decommissioned

### Tasks (GitHub Issues)

**EPIC 7: Completion** (Weeks 11-14)
- [ ] Issue #8.1: Complete final platform migrations
- [ ] Issue #8.2: Achieve 100% comparison success
- [ ] Issue #8.3: Prepare cutover plan
- [ ] Issue #7.4: Announce cutover date (Week 12)
- [ ] Issue #7.5: Execute cutover (Week 13)
- [ ] Issue #7.6: Monitor production (Week 13-14)
- [ ] Issue #7.7: Decommission old pipeline (Week 14)
- [ ] Issue #7.8: Complete documentation (Week 14)
- [ ] Issue #7.9: Conduct team training (Week 12-13)

---

## Risk Management

### High-Risk Areas

#### 1. Build Reproducibility
**Risk**: New pipeline produces different binaries
**Mitigation**:
- Extensive comparison testing
- Byte-level diff analysis
- Parallel execution for validation

#### 2. Platform-Specific Issues
**Risk**: Edge cases not discovered until production
**Mitigation**:
- Comprehensive pilot phase
- Gradual rollout by platform
- Easy rollback capability

#### 3. Performance Regression
**Risk**: New pipeline slower than old
**Mitigation**:
- Performance benchmarking
- Optimization phase
- Acceptable threshold defined

#### 4. Team Adoption
**Risk**: Team unfamiliar with new approach
**Mitigation**:
- Comprehensive documentation
- Training sessions
- Gradual transition period

### Rollback Triggers

Immediate rollback if:
- ❌ Binary differences detected
- ❌ Test failures increase
- ❌ Build time increases >20%
- ❌ Critical production issue
- ❌ Team cannot troubleshoot

---

## Monitoring & Metrics

### Key Performance Indicators (KPIs)

#### Build Quality
- **Artifact Comparison Success Rate**: Target 100%
- **Test Pass Rate**: Must match old pipeline
- **Binary Reproducibility**: Byte-for-byte match

#### Performance
- **Build Duration**: Within 10% of old pipeline
- **Resource Usage**: CPU/Memory comparable
- **Artifact Size**: Identical to old pipeline

#### Reliability
- **Build Success Rate**: ≥ old pipeline
- **Restart Success Rate**: >95%
- **Failure Recovery Time**: <30 minutes

### Monitoring Dashboard

```
┌─────────────────────────────────────────────────────────────────┐
│                    MIGRATION DASHBOARD                           │
│                                                                  │
│  Overall Progress:  [████████████░░░░░░░░] 60%                  │
│                                                                  │
│  Platforms Migrated:     24 / 40                                │
│  Comparison Success:     100%                                    │
│  Performance Delta:      +5% (acceptable)                        │
│  Issues Found:           3 (2 resolved, 1 in progress)          │
│                                                                  │
│  Recent Builds:                                                  │
│  ├─ Linux x64 JDK21u:    ✓ Match                               │
│  ├─ Mac aarch64 JDK21u:  ✓ Match                               │
│  ├─ Windows x64 JDK21u:  ✓ Match                               │
│  └─ Linux aarch64 JDK21u: ✓ Match                              │
│                                                                  │
│  Next Milestone: Tier 3 Rollout (Week 12)                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## Communication Plan

### Stakeholders

1. **Development Team**: Weekly updates
2. **QA Team**: Test result comparisons
3. **Release Team**: Migration timeline
4. **Management**: Monthly progress reports
5. **Community**: Public announcements

### Communication Channels

- **Weekly Email**: Progress updates
- **Slack Channel**: #pipeline-migration
- **Wiki Page**: Living documentation
- **Monthly Meeting**: Stakeholder review
- **GitHub Issues**: Technical tracking

---

## Success Stories & Lessons Learned

### Expected Benefits

1. **Restartability**: Save hours on failed builds
2. **CI Independence**: Easier to migrate CI systems
3. **Maintainability**: Clearer code organization
4. **Testability**: Local testing capability
5. **Reliability**: Reproducible builds

### Post-Migration Review

After completion, document:
- What went well
- What could be improved
- Unexpected challenges
- Time/resource actuals vs estimates
- Recommendations for future migrations

---

## Appendix

### A. Comparison Tool Usage

```bash
# Compare two builds
./tools/compare-builds.sh \
  --old /old-builds/jdk21u-linux-x64-20260512.tar.gz \
  --new /new-builds/jdk21u-linux-x64-20260512.tar.gz \
  --report comparison-report.html
```

### B. Rollback Procedure

```bash
# Emergency rollback
cd ci-jenkins-pipelines
git checkout main
# Update Jenkins job to use old pipeline
# Disable new pipeline jobs
# Notify team
```

### C. Platform Priority Matrix

| Platform | Priority | Complexity | Risk | Order |
|----------|----------|------------|------|-------|
| Linux x64 | High | Low | Low | 1 |
| Mac aarch64 | High | Medium | Medium | 2 |
| Windows x64 | High | Medium | Medium | 3 |
| Linux aarch64 | Medium | Low | Low | 4 |
| Mac x64 | Medium | Medium | Medium | 5 |
| AIX ppc64 | Low | High | High | 6 |
| Linux s390x | Low | High | High | 7 |

### D. Contact Information

- **Migration Lead**: TBD
- **Technical Lead**: TBD
- **QA Lead**: TBD
- **Slack Channel**: #pipeline-migration
- **Email**: pipeline-migration@adoptium.net

---

## Conclusion

This accelerated migration plan provides a structured, low-risk approach to transitioning from the monolithic pipeline to the new modular architecture. By following this plan, we can ensure:

- ✅ Zero downtime during migration
- ✅ Comprehensive validation at each step
- ✅ Easy rollback if issues arise
- ✅ Rapid team adoption
- ✅ Complete documentation
- ✅ Leverages existing tooling (repro_compare.sh)
- ✅ Parallel platform migrations for speed

**Estimated Timeline**: 10-14 weeks (2.5-3.5 months)
**Estimated Effort**: 2-3 FTE
**Risk Level**: Low-Medium (with proper execution and monitoring)

**Key Acceleration Factors:**
- Existing conversion tools and scripts
- Proven repro_compare.sh for validation
- Parallel migration of multiple platforms
- Reduced pilot validation builds (5 vs 20)
- Aggressive rollout schedule
- Combined stabilization and decommission phase

---

*Document Version: 1.0*
*Last Updated: 2026-05-12*

---

## Appendix A: Build Comparison Tool Usage

### Using repro_compare.sh

The migration uses the existing reproducible build comparison tool from the temurin-build repository:
`temurin-build/tooling/reproducible/repro_compare.sh`

This tool compares two JDK builds to verify they are byte-for-byte identical (after removing expected differences like timestamps and build IDs).

### Basic Usage

```bash
# Extract both JDK builds
tar -xzf /old-builds/jdk21u-linux-x64-20260512.tar.gz -C /tmp/old-jdk
tar -xzf /new-builds/jdk21u-linux-x64-20260512.tar.gz -C /tmp/new-jdk

# Compare using repro_compare.sh
cd temurin-build/tooling/reproducible
./repro_compare.sh \
  temurin /tmp/old-jdk/jdk-21.0.12+1 \
  temurin /tmp/new-jdk/jdk-21.0.12+1 \
  Linux

# Check results
# - Exit code 0 = builds are identical
# - reprotest.diff = list of differences (if any)
# - reproducible_evidence.log = detailed comparison evidence
# - ReproduciblePercent = percentage match (aim for 100%)
```

### Supported Platforms

- **Linux** (all architectures: x64, aarch64, ppc64le, s390x, riscv64, arm)
- **macOS** (Darwin: x64, aarch64)
- **Windows** (CYGWIN: x64, x86-32, aarch64)

### What It Compares

1. **File Structure**: Verifies same files exist in both builds
2. **File Count**: Ensures no missing or extra files
3. **Binary Content**: Byte-by-byte comparison after preprocessing
4. **Metadata**: Checks file permissions and attributes

### Preprocessing Steps

The tool automatically removes expected differences:
- Build timestamps
- Build IDs and UUIDs
- Absolute paths in debug info
- Platform-specific metadata
- Compiler-generated unique identifiers

### Output Files

- **`reprotest.diff`**: List of files that differ
- **`reproducible_evidence.log`**: Detailed comparison log
- **`ReproduciblePercent`**: Percentage of identical files
- **Exit code**: 0 = identical, non-zero = differences found

### Integration with Migration

During parallel execution, the comparison tool runs automatically:

```bash
# In Jenkins parallel execution stage
stage('Compare Builds') {
    steps {
        script {
            sh '''
                cd ${WORKSPACE}/temurin-build/tooling/reproducible
                ./repro_compare.sh \
                  temurin ${OLD_BUILD_DIR}/jdk-${VERSION} \
                  temurin ${NEW_BUILD_DIR}/jdk-${VERSION} \
                  ${PLATFORM}

                # Archive results
                cp reprotest.diff ${WORKSPACE}/comparison-results/
                cp reproducible_evidence.log ${WORKSPACE}/comparison-results/

                # Fail if not 100% reproducible
                if [ $? -ne 0 ]; then
                    echo "ERROR: Builds are not identical!"
                    exit 1
                fi
            '''
        }
    }
}
```

### Success Criteria

For migration validation, builds must achieve:
- **100% ReproduciblePercent** (all files identical)
- **Exit code 0** (no differences found)
- **Empty reprotest.diff** (no files listed as different)

### Troubleshooting

If builds don't match:

1. **Check reprotest.diff**: Lists which files differ
2. **Review reproducible_evidence.log**: Shows detailed comparison
3. **Verify preprocessing**: Ensure platform-specific preprocessing ran
4. **Check build environment**: Verify same compiler versions, flags, etc.
5. **Compare build logs**: Look for differences in build process

### Example Output

```
Comparing builds...
Platform: Linux
Old build: /tmp/old-jdk/jdk-21.0.12+1
New build: /tmp/new-jdk/jdk-21.0.12+1

Files compared: 15,234
Files identical: 15,234
Files different: 0
ReproduciblePercent: 100%

Result: IDENTICAL ✓
```

### References

- Tool location: `temurin-build/tooling/reproducible/repro_compare.sh`
- Documentation: `temurin-build/tooling/reproducible/README.md`
- Issue tracker: Use for reporting comparison tool issues
*Next Review: Start of Phase 2*