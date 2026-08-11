# GitHub EPICs and Issues for Pipeline Migration

This document provides ready-to-use templates for creating GitHub EPICs and issues to track the pipeline migration project.

---

## Executive Summary

### Why This Refactoring?

The current OpenJDK build pipeline uses a monolithic scripted pipeline architecture that has become increasingly difficult to maintain, debug, and extend. This refactoring addresses critical operational challenges:

**Current Pain Points:**
1. **No Restart Capability**: Pipeline failures require complete rebuilds from scratch, wasting hours of compute time and developer productivity
2. **Monolithic Design**: All logic embedded in a single large Groovy script makes changes risky and testing difficult
3. **Configuration Complexity**: Build configurations mixed with pipeline code makes it hard to add new platforms or variants
4. **Debugging Challenges**: When builds fail, identifying the root cause requires navigating thousands of lines of Groovy code
5. **Vendor Lock-in**: Heavy reliance on Jenkins-specific features and shared libraries limits portability
6. **Limited Reusability**: Other vendors cannot easily adapt the pipeline for their needs

**Benefits of New Architecture:**
1. **Stage-Level Restart**: Failed stages can be restarted individually, saving hours of rebuild time
2. **Modular Design**: Each stage is an independent script, making changes safer and testing easier
3. **Code/Config Separation**: Pipeline code (ci-adoptium-pipelines) separated from vendor configurations (ci-temurin-config)
4. **Better Debugging**: Clear stage boundaries and structured logging make troubleshooting straightforward
5. **CI-Agnostic**: 90% of code is portable shell scripts, reducing Jenkins dependency
6. **Vendor-Friendly**: Other vendors can use the pipeline code with their own configuration repositories
7. **Improved Reliability**: Declarative syntax with explicit stage dependencies reduces runtime errors
8. **Faster Iteration**: Developers can test individual stages locally without full Jenkins setup

**Business Impact:**
- **Reduced Downtime**: Restart capability eliminates hours of wasted rebuild time
- **Faster Releases**: Modular design enables parallel development and faster iteration
- **Lower Costs**: Efficient resource usage and reduced compute waste
- **Better Quality**: Easier testing and validation leads to more reliable builds
- **Vendor Adoption**: Other organizations can adopt Adoptium's build infrastructure

**Migration Strategy:**
- Gradual rollout with parallel execution (old and new pipelines run side-by-side)
- Byte-by-byte comparison ensures identical outputs
- Start with pilot platform (Linux x64 JDK21u) before expanding
- Zero downtime migration with fallback capability

---

## Architecture Overview

The new pipeline architecture separates code from configuration:

- **ci-adoptium-pipelines** (Code Repository)
  - Contains: Jenkinsfile.declarative, scripts/, tools/
  - Purpose: Pipeline execution code (CI-agnostic where possible)
  - Checked out via Jenkins SCM configuration

- **ci-temurin-config** (Configuration Repository)
  - Contains: configurations/ with JSON files
  - Purpose: Temurin-specific build configurations
  - Checked out via CONFIG_REPO_URL parameter

This separation allows:
- Vendors to maintain their own configuration repositories
- Shared pipeline code across all vendors
- Independent versioning of code and configurations
- Easier testing and validation

---

## EPIC 1: Phase 1 - CI-Agnostic Foundation

**Title**: Phase 1 - Establish CI-Agnostic Pipeline Architecture

**Description**:
Establish the foundational CI-agnostic pipeline architecture as described in [`CI_AGNOSTIC_ARCHITECTURE.md`](CI_AGNOSTIC_ARCHITECTURE.md). This phase focuses on creating a working framework with core stages that can run in both Jenkins and local environments, validated on a private Jenkins instance.

**Core Architecture Components**:
- **Code/Config Separation**: ci-adoptium-pipelines (code) + ci-temurin-config (configurations)
- **CI-Agnostic Design**: 90% portable shell scripts, minimal Jenkins-specific code
- **Modular Stages**: Independent, restartable stage scripts
- **Dual Execution**: Framework supports both ci/jenkins and ci/local pipelines
- **Artifact Management**: Clear INPUT_ARTIFACTS_DIR vs TARGET_DIR pattern

**Core Stages Implemented**:
1. **Initialize** - Load configuration, set up environment
2. **Build** - Compile JDK from source
3. **Validate SBOM** - Verify Software Bill of Materials
4. **Reproducible Compare** - Byte-by-byte comparison of builds

**Goals**:
- Create ci-adoptium-pipelines repository with CI-agnostic architecture
- Create ci-temurin-config repository for Temurin configurations
- Implement core pipeline stages as portable shell scripts
- Build local execution framework (run-pipeline.py)
- Build Jenkins execution framework (Jenkinsfile.declarative)
- Implement reproducible build comparison
- Validate on private Jenkins instance with JDK21u Linux x64

**Success Criteria**:
- [ ] Both repositories created with proper structure
- [ ] CI-agnostic architecture documented (CI_AGNOSTIC_ARCHITECTURE.md)
- [ ] Core stages implemented as portable shell scripts
- [ ] Local execution framework (run-pipeline.py) working
- [ ] Jenkins execution framework (Jenkinsfile.declarative) working
- [ ] Artifact directory pattern (INPUT_ARTIFACTS_DIR/TARGET_DIR) implemented
- [ ] Workspace cleanup architecture implemented
- [ ] JDK21u Linux x64 configuration converted to JSON
- [ ] Successful build on private Jenkins instance
- [ ] Reproducible comparison passes (100% match)
- [ ] Local pipeline execution validated
- [ ] Documentation complete

**Timeline**: Weeks 1-4
**Priority**: P0 (Blocker)
**Labels**: `epic`, `phase-1`, `foundation`, `ci-agnostic`

---

### Issue #1.1: Create CI-Agnostic Repository Structure

**Title**: Create ci-adoptium-pipelines repository with CI-agnostic architecture

**Description**:
Create the ci-adoptium-pipelines repository with proper structure to support CI-agnostic pipeline execution in both Jenkins and local environments.

**Tasks**:
- [x] Create ci-adoptium-pipelines repository
  - [x] Create `ci/jenkins/` directory for Jenkins-specific code
  - [x] Create `ci/jenkins/scripts/stages/` for stage scripts
  - [x] Create `ci/jenkins/scripts/lib/` for shared libraries
  - [x] Create `ci/local/` directory for local execution
  - [x] Create `docs/` directory for documentation
  - [x] Create `tools/` directory for utilities
  - [x] Add Jenkinsfile.declarative
  - [x] Add Jenkinsfile.launch (orchestrator)
  - [x] Add comprehensive README.md
- [x] Create ci-temurin-config repository
  - [x] Create `configurations/` directory
  - [x] Add README.md
  - [x] Add .gitignore
- [x] Set up proper file permissions (scripts executable)
- [x] Document CI-agnostic architecture

**Acceptance Criteria**:
- [x] Both repositories created with proper structure
- [x] CI-agnostic separation (ci/jenkins vs ci/local)
- [x] File permissions correct (scripts executable)
- [x] CI_AGNOSTIC_ARCHITECTURE.md created
- [x] CODE_CONFIG_SEPARATION.md created

**Estimated Effort**: 1 day
**Priority**: P0
**Labels**: `phase-1`, `infrastructure`, `setup`
**Assignee**: TBD

---

### Issue #1.2: Implement Core Pipeline Stages

**Title**: Create portable shell scripts for core pipeline stages

**Description**:
Implement the four core pipeline stages as portable shell scripts that work in both Jenkins and local environments.

**Tasks**:
- [x] Create Initialize stage (01-initialize.sh)
  - [x] Load configuration from JSON
  - [x] Set up environment variables
  - [x] Validate prerequisites
- [x] Create Build stage (02-build.sh)
  - [x] Clone temurin-build repository
  - [x] Execute make-adopt-build-farm.sh
  - [x] Archive build artifacts
  - [x] Generate SBOM
- [x] Create Validate SBOM stage (12-validate-sbom.sh)
  - [x] Read SBOM from INPUT_ARTIFACTS_DIR
  - [x] Validate SBOM structure
  - [x] Check for required components
- [x] Create Reproducible Compare stage (20-reproducible-compare.sh)
  - [x] Read built JDK from INPUT_ARTIFACTS_DIR
  - [x] Rebuild JDK with same parameters
  - [x] Compare builds byte-by-byte
  - [x] Generate comparison report

**Acceptance Criteria**:
- [x] All four stages implemented as shell scripts
- [x] Scripts use INPUT_ARTIFACTS_DIR for input
- [x] Scripts use TARGET_DIR for output
- [x] Scripts work in both Jenkins and local environments
- [x] Error handling implemented
- [x] Logging implemented

**Estimated Effort**: 1 week
**Priority**: P0
**Labels**: `phase-1`, `core-stages`, `ci-agnostic`
**Assignee**: TBD

---

### Issue #1.3: Build Jenkins Execution Framework

**Title**: Create Jenkinsfile.declarative with restartable stages

**Description**:
Implement the Jenkins execution framework using declarative pipeline syntax with support for stage-level restart.

**Tasks**:
- [x] Create Jenkinsfile.declarative
  - [x] Implement declarative pipeline structure
  - [x] Add stage definitions (Initialize, Build, Validate SBOM, Reproducible Compare)
  - [x] Implement initializeStage() helper function
  - [x] Add workspace cleanup (cleanWs) pre/post stages
  - [x] Implement artifact copying with copyArtifacts
  - [x] Add INPUT_ARTIFACTS_DIR/TARGET_DIR pattern
- [x] Create helper functions
  - [x] ensureBuildUidHelperLoaded() for build UID integration
  - [x] loadConfiguration() for JSON config loading
- [x] Implement parameter handling
  - [x] CONFIG_REPO_URL (mandatory)
  - [x] CONFIG_REPO_BRANCH (mandatory)
  - [x] CLEAN_WORKSPACE_AFTER_STAGE (optional)
  - [x] Platform-specific parameters

**Acceptance Criteria**:
- [x] Declarative pipeline syntax used
- [x] Stages are independently restartable
- [x] Workspace cleanup works correctly
- [x] Artifact flow managed properly
- [x] Configuration loaded from ci-temurin-config
- [x] Build UID integration working

**Estimated Effort**: 1 week
**Priority**: P0
**Labels**: `phase-1`, `jenkins`, `declarative`
**Assignee**: TBD

---

### Issue #1.4: Build Local Execution Framework

**Title**: Create run-pipeline.py for local pipeline testing

**Description**:
Implement the local execution framework that allows developers to test pipeline stages locally without Jenkins.

**Tasks**:
- [x] Create run-pipeline.py
  - [x] Implement CLI argument parsing
  - [x] Add stage execution methods
  - [x] Implement workspace management
  - [x] Add artifact directory management
  - [x] Set INPUT_ARTIFACTS_DIR/TARGET_DIR environment variables
- [x] Create workspace_manager.py
  - [x] Implement workspace cleanup logic
  - [x] Add pre/post stage cleanup
  - [x] Handle stage workspace isolation
- [x] Create load-json-config.py
  - [x] Load configuration from JSON
  - [x] Convert to environment variables
  - [x] Validate configuration schema

**Acceptance Criteria**:
- [x] Local pipeline execution works
- [x] All four core stages can run locally
- [x] Workspace management works correctly
- [x] Artifact flow matches Jenkins behavior
- [x] Configuration loading works
- [x] Error handling implemented

**Estimated Effort**: 1 week
**Priority**: P0
**Labels**: `phase-1`, `local`, `testing`
**Assignee**: TBD

---

### Issue #1.5: Implement Artifact Directory Pattern

**Title**: Implement INPUT_ARTIFACTS_DIR vs TARGET_DIR pattern

**Description**:
Implement the artifact directory pattern that clearly separates stage inputs from outputs, supporting restartability.

**Tasks**:
- [x] Update all stage scripts to use INPUT_ARTIFACTS_DIR
  - [x] 12-validate-sbom.sh
  - [x] 13-smoke-tests.sh
  - [x] 20-reproducible-compare.sh
  - [x] 06-sign.sh
  - [x] 07-installer.sh
- [x] Update Jenkinsfile.declarative
  - [x] Set INPUT_ARTIFACTS_DIR per stage
  - [x] Set TARGET_DIR per stage
  - [x] Update initializeStage() to accept inputArtifactsDir
  - [x] Update CONFIG_FILE to point to INPUT_ARTIFACTS_DIR
- [x] Update run-pipeline.py
  - [x] Set INPUT_ARTIFACTS_DIR for all stages
  - [x] Keep TARGET_DIR for output
- [x] Document the pattern
  - [x] Create ARTIFACT_DIRECTORY_PATTERN.md

**Acceptance Criteria**:
- [x] All stages use INPUT_ARTIFACTS_DIR for input
- [x] All stages use TARGET_DIR for output
- [x] Pattern works in both Jenkins and local
- [x] Documentation complete
- [x] Examples provided

**Estimated Effort**: 3 days
**Priority**: P0
**Labels**: `phase-1`, `architecture`, `artifacts`
**Assignee**: TBD

---

### Issue #1.6: Implement Workspace Cleanup Architecture

**Title**: Design and implement workspace cleanup for restartable stages

**Description**:
Implement workspace cleanup architecture that supports stage-level restart while maintaining clean workspace state.

**Tasks**:
- [x] Design cleanup architecture
  - [x] Pre-stage cleanup (cleanWs before stage)
  - [x] Post-stage cleanup (optional, controlled by parameter)
  - [x] Stage workspace isolation
- [x] Update Jenkinsfile.declarative
  - [x] Add cleanWs() before each stage
  - [x] Add optional cleanWs() after each stage
  - [x] Add CLEAN_WORKSPACE_AFTER_STAGE parameter
- [x] Update run-pipeline.py
  - [x] Implement workspace_manager.py
  - [x] Add pre/post stage cleanup
- [x] Document cleanup architecture
  - [x] Create WORKSPACE_CLEANUP_ARCHITECTURE.md

**Acceptance Criteria**:
- [x] Workspace cleanup works in Jenkins
- [x] Workspace cleanup works locally
- [x] Stages can be restarted cleanly
- [x] Optional post-stage cleanup works
- [x] Documentation complete

**Estimated Effort**: 3 days
**Priority**: P0
**Labels**: `phase-1`, `architecture`, `workspace`
**Assignee**: TBD

---

### Issue #1.7: Create Configuration Conversion Tool

**Title**: Convert JDK21u Linux x64 configuration to JSON

**Description**:
Create tool to convert existing Groovy configuration to JSON format and convert the pilot platform configuration.

**Tasks**:
- [x] Create convert-groovy-to-json.py
  - [x] Implement Groovy parser
  - [x] Handle nested maps and lists
  - [x] Extract platform configurations
  - [x] Format JSON output
- [x] Convert JDK21u Linux x64 Temurin configuration
- [x] Validate JSON schema
- [x] Commit to ci-temurin-config repository
- [x] Document conversion process

**Acceptance Criteria**:
- [x] Conversion tool works correctly
- [x] JDK21u Linux x64 config converted
- [x] JSON validates correctly
- [x] Configuration committed
- [x] Documentation complete

**Estimated Effort**: 3 days
**Priority**: P0
**Labels**: `phase-1`, `tooling`, `conversion`
**Assignee**: TBD

---

### Issue #1.8: Validate on Private Jenkins Instance

**Title**: Deploy and validate pipeline on private Jenkins instance

**Description**:
Deploy the new pipeline to a private Jenkins instance and validate with JDK21u Linux x64 Temurin build.

**Tasks**:
- [ ] Set up private Jenkins instance
  - [ ] Install required plugins
  - [ ] Configure credentials
  - [ ] Set up build agents
- [ ] Deploy pipeline code
  - [ ] Create seed job
  - [ ] Generate pipeline jobs via Job DSL
  - [ ] Configure job parameters
- [ ] Run test build
  - [ ] Execute full pipeline
  - [ ] Monitor execution
  - [ ] Collect artifacts
- [ ] Run reproducible comparison
  - [ ] Rebuild with same parameters
  - [ ] Compare builds byte-by-byte
  - [ ] Validate 100% match
- [ ] Document results
  - [ ] Build logs
  - [ ] Comparison results
  - [ ] Performance metrics

**Acceptance Criteria**:
- [ ] Private Jenkins instance configured
- [ ] Pipeline deployed successfully
- [ ] JDK21u Linux x64 build completes
- [ ] All four stages execute successfully
- [ ] Reproducible comparison passes (100%)
- [ ] Build artifacts archived
- [ ] Results documented

**Estimated Effort**: 1 week
**Priority**: P0
**Labels**: `phase-1`, `validation`, `jenkins`
**Assignee**: TBD

---

### Issue #1.9: Create Comprehensive Documentation

**Title**: Document Phase 1 architecture and implementation

**Description**:
Create comprehensive documentation covering all aspects of the Phase 1 implementation.

**Tasks**:
- [x] Create CI_AGNOSTIC_ARCHITECTURE.md
- [x] Create CODE_CONFIG_SEPARATION.md
- [x] Create ARTIFACT_DIRECTORY_PATTERN.md
- [x] Create WORKSPACE_CLEANUP_ARCHITECTURE.md
- [x] Create MIGRATION_STRATEGY.md
- [x] Create MIGRATION_IMPLEMENTATION_GUIDE.md
- [x] Update README files
- [ ] Create Phase 1 completion report

**Acceptance Criteria**:
- [x] All architecture documents created
- [x] Implementation guides complete
- [x] Examples provided
- [x] Troubleshooting guides included
- [ ] Phase 1 report written

**Estimated Effort**: 1 week
**Priority**: P1
**Labels**: `phase-1`, `documentation`
**Assignee**: TBD

---

## EPIC 2: Remaining Build Stages Rollout

**Title**: Phase 2 - Complete Build Pipeline for JDK21u (Linux, Windows, Mac)

**Description**:
Implement the remaining build pipeline stages to complete the full build workflow for JDK21u Temurin across Linux x64, Windows x64, and Mac aarch64 platforms. This phase extends Phase 1's foundation (Initialize, Build, Validate SBOM, Reproducible Compare) with the complete signing, assembly, and installer creation workflow.

**Rationale for Multi-Platform Phase 2**:
To properly implement and test the Internal Sign and Assemble stages, we need to build on Windows and Mac platforms since these stages have platform-specific requirements (MSI installers for Windows, PKG installers for Mac, DEB/RPM for Linux). Including all three platforms in Phase 2 ensures the stage implementations are truly portable and work across all major platforms.

**Target Platforms**:
- JDK21u Linux x64 Temurin (from Phase 1)
- JDK21u Windows x64 Temurin (new)
- JDK21u Mac aarch64 Temurin (new)

**Additional Stages to Implement**:
1. **Internal Sign** - Internal artifact signing for testing (platform-specific)
2. **Assemble** - Assemble build artifacts into distribution packages (platform-specific)
3. **Sign Artifacts** - Sign JDK artifacts with production certificates
4. **Build Installers** - Create platform-specific installers (MSI, PKG, DEB, RPM)
5. **Sign Installers** - Sign installer packages (platform-specific)
6. **GPG Sign** - Create GPG signatures for artifacts
7. **Verify Signing** - Validate all signatures are correct

**Goals**:
- Implement all 7 remaining stages as portable shell scripts
- Ensure stages work across Linux, Windows, and Mac platforms
- Integrate stages into Jenkins declarative pipeline
- Add stages to local execution framework
- Maintain INPUT_ARTIFACTS_DIR/TARGET_DIR pattern
- Support stage-level restart for all new stages
- Validate complete pipeline on private Jenkins instance for all three platforms

**Success Criteria**:
- [ ] All 7 stages implemented as shell scripts
- [ ] All stages work on Linux, Windows, and Mac
- [ ] All stages integrated into Jenkinsfile.declarative
- [ ] All stages work in local execution (run-pipeline.py)
- [ ] Artifact flow works correctly between stages
- [ ] Stage restart capability validated
- [ ] Complete pipeline runs successfully on private Jenkins for:
  - [ ] JDK21u Linux x64
  - [ ] JDK21u Windows x64
  - [ ] JDK21u Mac aarch64
- [ ] All artifacts properly signed and verified on all platforms
- [ ] Platform-specific installers created and signed correctly:
  - [ ] DEB/RPM for Linux
  - [ ] MSI for Windows
  - [ ] PKG for Mac
- [ ] Documentation updated

**Timeline**: Weeks 5-8
**Priority**: P0 (Blocker)
**Labels**: `epic`, `phase-2`, `build-stages`, `multi-platform`

---

### Issue #2.1: Implement Internal Sign Stage

**Title**: Create internal signing stage for test artifacts

**Description**:
Implement the Internal Sign stage that signs artifacts with internal/test certificates for validation purposes.

**Tasks**:
- [ ] Create 05-internal-sign.sh script
  - [ ] Read artifacts from INPUT_ARTIFACTS_DIR
  - [ ] Sign with internal certificates
  - [ ] Write signed artifacts to TARGET_DIR
  - [ ] Generate signing report
- [ ] Add stage to Jenkinsfile.declarative
  - [ ] Define stage with proper prerequisites
  - [ ] Set INPUT_ARTIFACTS_DIR and TARGET_DIR
  - [ ] Add artifact archiving
- [ ] Add stage to run-pipeline.py
  - [ ] Implement stage_internal_sign() method
  - [ ] Set environment variables
  - [ ] Handle workspace cleanup
- [ ] Test stage locally
- [ ] Test stage in Jenkins
- [ ] Document stage behavior

**Acceptance Criteria**:
- [ ] Script works in both Jenkins and local
- [ ] Artifacts signed correctly
- [ ] Stage is restartable
- [ ] Documentation complete

**Estimated Effort**: 3 days
**Priority**: P0
**Labels**: `phase-2`, `signing`, `stage-implementation`
**Assignee**: TBD

---

### Issue #2.2: Implement Assemble Stage

**Title**: Create assembly stage for distribution packages

**Description**:
Implement the Assemble stage that packages build artifacts into distribution-ready formats.

**Tasks**:
- [ ] Create 08-assemble.sh script
  - [ ] Read artifacts from INPUT_ARTIFACTS_DIR
  - [ ] Assemble into distribution packages
  - [ ] Create checksums
  - [ ] Write packages to TARGET_DIR
- [ ] Add stage to Jenkinsfile.declarative
  - [ ] Define stage with proper prerequisites
  - [ ] Set INPUT_ARTIFACTS_DIR and TARGET_DIR
  - [ ] Add artifact archiving
- [ ] Add stage to run-pipeline.py
  - [ ] Implement stage_assemble() method
  - [ ] Set environment variables
  - [ ] Handle workspace cleanup
- [ ] Test stage locally
- [ ] Test stage in Jenkins
- [ ] Document stage behavior

**Acceptance Criteria**:
- [ ] Script works in both Jenkins and local
- [ ] Packages assembled correctly
- [ ] Checksums generated
- [ ] Stage is restartable
- [ ] Documentation complete

**Estimated Effort**: 3 days
**Priority**: P0
**Labels**: `phase-2`, `assembly`, `stage-implementation`
**Assignee**: TBD

---

### Issue #2.3: Implement Sign Artifacts Stage

**Title**: Create production artifact signing stage

**Description**:
Implement the Sign Artifacts stage that signs JDK artifacts with production certificates.

**Tasks**:
- [ ] Create 06-sign.sh script (already exists, may need updates)
  - [ ] Read artifacts from INPUT_ARTIFACTS_DIR
  - [ ] Sign with production certificates
  - [ ] Write signed artifacts to TARGET_DIR
  - [ ] Generate signing report
- [ ] Add stage to Jenkinsfile.declarative
  - [ ] Define stage with proper prerequisites
  - [ ] Set INPUT_ARTIFACTS_DIR and TARGET_DIR
  - [ ] Add artifact archiving
  - [ ] Handle signing credentials securely
- [ ] Add stage to run-pipeline.py
  - [ ] Implement stage_sign() method
  - [ ] Set environment variables
  - [ ] Handle workspace cleanup
- [ ] Test stage locally (with test certs)
- [ ] Test stage in Jenkins
- [ ] Document stage behavior

**Acceptance Criteria**:
- [ ] Script works in both Jenkins and local
- [ ] Artifacts signed with production certs
- [ ] Credentials handled securely
- [ ] Stage is restartable
- [ ] Documentation complete

**Estimated Effort**: 4 days
**Priority**: P0
**Labels**: `phase-2`, `signing`, `stage-implementation`
**Assignee**: TBD

---

### Issue #2.4: Implement Build Installers Stage

**Title**: Create installer building stage

**Description**:
Implement the Build Installers stage that creates platform-specific installers (MSI, PKG, DEB, RPM).

**Tasks**:
- [ ] Create 07-installer.sh script (already exists, may need updates)
  - [ ] Read signed JDK from INPUT_ARTIFACTS_DIR
  - [ ] Build platform-specific installers
  - [ ] Write installers to TARGET_DIR
  - [ ] Generate installer metadata
- [ ] Add stage to Jenkinsfile.declarative
  - [ ] Define stage with proper prerequisites
  - [ ] Set INPUT_ARTIFACTS_DIR and TARGET_DIR
  - [ ] Add artifact archiving
- [ ] Add stage to run-pipeline.py
  - [ ] Implement stage_installer() method
  - [ ] Set environment variables
  - [ ] Handle workspace cleanup
- [ ] Test stage locally
- [ ] Test stage in Jenkins
- [ ] Document stage behavior

**Acceptance Criteria**:
- [ ] Script works in both Jenkins and local
- [ ] Installers created correctly
- [ ] All installer types supported
- [ ] Stage is restartable
- [ ] Documentation complete

**Estimated Effort**: 4 days
**Priority**: P0
**Labels**: `phase-2`, `installers`, `stage-implementation`
**Assignee**: TBD

---

### Issue #2.5: Implement Sign Installers Stage

**Title**: Create installer signing stage

**Description**:
Implement the Sign Installers stage that signs installer packages with appropriate certificates.

**Tasks**:
- [ ] Create 09-sign-installers.sh script
  - [ ] Read installers from INPUT_ARTIFACTS_DIR
  - [ ] Sign with platform-specific certificates
  - [ ] Write signed installers to TARGET_DIR
  - [ ] Generate signing report
- [ ] Add stage to Jenkinsfile.declarative
  - [ ] Define stage with proper prerequisites
  - [ ] Set INPUT_ARTIFACTS_DIR and TARGET_DIR
  - [ ] Add artifact archiving
  - [ ] Handle signing credentials securely
- [ ] Add stage to run-pipeline.py
  - [ ] Implement stage_sign_installers() method
  - [ ] Set environment variables
  - [ ] Handle workspace cleanup
- [ ] Test stage locally (with test certs)
- [ ] Test stage in Jenkins
- [ ] Document stage behavior

**Acceptance Criteria**:
- [ ] Script works in both Jenkins and local
- [ ] Installers signed correctly
- [ ] Platform-specific signing handled
- [ ] Stage is restartable
- [ ] Documentation complete

**Estimated Effort**: 4 days
**Priority**: P0
**Labels**: `phase-2`, `signing`, `installers`, `stage-implementation`
**Assignee**: TBD

---

### Issue #2.6: Implement GPG Sign Stage

**Title**: Create GPG signing stage for artifacts

**Description**:
Implement the GPG Sign stage that creates GPG signatures for all artifacts.

**Tasks**:
- [ ] Create 10-gpg-sign.sh script
  - [ ] Read artifacts from INPUT_ARTIFACTS_DIR
  - [ ] Create GPG signatures (.asc files)
  - [ ] Write signatures to TARGET_DIR
  - [ ] Generate signing report
- [ ] Add stage to Jenkinsfile.declarative
  - [ ] Define stage with proper prerequisites
  - [ ] Set INPUT_ARTIFACTS_DIR and TARGET_DIR
  - [ ] Add artifact archiving
  - [ ] Handle GPG keys securely
- [ ] Add stage to run-pipeline.py
  - [ ] Implement stage_gpg_sign() method
  - [ ] Set environment variables
  - [ ] Handle workspace cleanup
- [ ] Test stage locally (with test keys)
- [ ] Test stage in Jenkins
- [ ] Document stage behavior

**Acceptance Criteria**:
- [ ] Script works in both Jenkins and local
- [ ] GPG signatures created correctly
- [ ] Keys handled securely
- [ ] Stage is restartable
- [ ] Documentation complete

**Estimated Effort**: 3 days
**Priority**: P0
**Labels**: `phase-2`, `signing`, `gpg`, `stage-implementation`
**Assignee**: TBD

---

### Issue #2.7: Implement Verify Signing Stage

**Title**: Create signature verification stage

**Description**:
Implement the Verify Signing stage that validates all signatures are correct and complete.

**Tasks**:
- [ ] Create 11-verify-signing.sh script
  - [ ] Read signed artifacts from INPUT_ARTIFACTS_DIR
  - [ ] Verify artifact signatures
  - [ ] Verify installer signatures
  - [ ] Verify GPG signatures
  - [ ] Write verification report to TARGET_DIR
- [ ] Add stage to Jenkinsfile.declarative
  - [ ] Define stage with proper prerequisites
  - [ ] Set INPUT_ARTIFACTS_DIR and TARGET_DIR
  - [ ] Add artifact archiving
- [ ] Add stage to run-pipeline.py
  - [ ] Implement stage_verify_signing() method
  - [ ] Set environment variables
  - [ ] Handle workspace cleanup
- [ ] Test stage locally
- [ ] Test stage in Jenkins
- [ ] Document stage behavior

**Acceptance Criteria**:
- [ ] Script works in both Jenkins and local
- [ ] All signature types verified
- [ ] Verification report generated
- [ ] Stage is restartable
- [ ] Documentation complete

**Estimated Effort**: 3 days
**Priority**: P0
**Labels**: `phase-2`, `verification`, `stage-implementation`
**Assignee**: TBD

---

### Issue #2.8: Integrate All Stages into Pipeline

**Title**: Complete pipeline integration and testing

**Description**:
Integrate all new stages into the complete pipeline and validate end-to-end execution.

**Tasks**:
- [ ] Update Jenkinsfile.declarative
  - [ ] Add all 7 new stages in correct order
  - [ ] Configure stage dependencies
  - [ ] Set up artifact flow between stages
  - [ ] Add conditional execution logic
- [ ] Update run-pipeline.py
  - [ ] Add all 7 new stage methods
  - [ ] Configure stage execution order
  - [ ] Handle artifact flow
- [ ] Test complete pipeline locally
  - [ ] Run all stages sequentially
  - [ ] Verify artifact flow
  - [ ] Test stage restart capability
- [ ] Test complete pipeline in Jenkins
  - [ ] Run full pipeline
  - [ ] Verify all stages execute
  - [ ] Test stage restart
  - [ ] Validate artifacts
- [ ] Performance testing
  - [ ] Measure execution time
  - [ ] Identify bottlenecks
  - [ ] Optimize if needed

**Acceptance Criteria**:
- [ ] All 11 stages integrated (4 from Phase 1 + 7 new)
- [ ] Complete pipeline runs successfully locally
- [ ] Complete pipeline runs successfully in Jenkins
- [ ] All stages are restartable
- [ ] Artifact flow works correctly
- [ ] Performance is acceptable

**Estimated Effort**: 1 week
**Priority**: P0
**Labels**: `phase-2`, `integration`, `testing`
**Assignee**: TBD

---

### Issue #2.9: Update Documentation

**Title**: Document Phase 2 implementation

**Description**:
Update all documentation to reflect the complete pipeline with all stages.

**Tasks**:
- [ ] Update CI_AGNOSTIC_ARCHITECTURE.md
  - [ ] Add all 7 new stages
  - [ ] Update stage flow diagrams
- [ ] Update stage-specific documentation
  - [ ] Document each new stage
  - [ ] Add usage examples
  - [ ] Include troubleshooting
- [ ] Update ARTIFACT_DIRECTORY_PATTERN.md
  - [ ] Add examples for new stages
- [ ] Create Phase 2 completion report
  - [ ] Summary of work completed
  - [ ] Lessons learned
  - [ ] Known issues
- [ ] Update README files
  - [ ] Add complete stage list
  - [ ] Update examples

**Acceptance Criteria**:
- [ ] All documentation updated
- [ ] Examples provided for all stages
- [ ] Phase 2 report complete
- [ ] Team reviewed

**Estimated Effort**: 3 days
**Priority**: P1
**Labels**: `phase-2`, `documentation`
**Assignee**: TBD

---

## EPIC 3: Tier 1 Rollout

**Title**: Tier 1 Platform Rollout (Linux x64 All Versions)

**Description**:
Expand migration to all Tier 1 platforms (Linux x64 for all JDK versions). These are the most common platforms with the highest usage.

**Platforms**:
- Linux x64 JDK21u Temurin ✓ (Pilot)
- Linux x64 JDK17u Temurin
- Linux x64 JDK11u Temurin
- Linux x64 JDK8u Temurin

**Success Criteria**:
- [ ] All Tier 1 platforms migrated
- [ ] 100% comparison success
- [ ] No performance regression
- [ ] Team confident with process

**Timeline**: Weeks 8-9
**Priority**: P0
**Labels**: `epic`, `tier-1`, `phase-3`

---

### Issue #3.1: Migrate Linux x64 JDK17u

**Title**: Migrate Linux x64 JDK17u Temurin to new pipeline

**Description**:
Migrate Linux x64 JDK17u Temurin following the established pilot process.

**Tasks**:
- [ ] Convert configuration
- [ ] Set up parallel execution
- [ ] Run 5 parallel builds
- [ ] Compare results
- [ ] Validate success
- [ ] Document findings

**Acceptance Criteria**:
- Configuration converted
- 5 builds successful
- All comparisons pass
- No issues found

**Estimated Effort**: 3 days
**Priority**: P0
**Labels**: `tier-1`, `migration`
**Assignee**: TBD

---

### Issue #3.2: Migrate Linux x64 JDK11u

**Title**: Migrate Linux x64 JDK11u Temurin to new pipeline

**Description**:
Migrate Linux x64 JDK11u Temurin following the established pilot process.

**Tasks**:
- [ ] Convert configuration
- [ ] Set up parallel execution
- [ ] Run 5 parallel builds
- [ ] Compare results
- [ ] Validate success
- [ ] Document findings

**Acceptance Criteria**:
- Configuration converted
- 5 builds successful
- All comparisons pass
- No issues found

**Estimated Effort**: 3 days
**Priority**: P0
**Labels**: `tier-1`, `migration`
**Assignee**: TBD

---

### Issue #3.3: Migrate Linux x64 JDK8u

**Title**: Migrate Linux x64 JDK8u Temurin to new pipeline

**Description**:
Migrate Linux x64 JDK8u Temurin following the established pilot process. Note: JDK8 may have unique requirements.

**Tasks**:
- [ ] Convert configuration
- [ ] Handle JDK8-specific requirements
- [ ] Set up parallel execution
- [ ] Run 5 parallel builds
- [ ] Compare results
- [ ] Validate success
- [ ] Document JDK8 quirks

**Acceptance Criteria**:
- Configuration converted
- JDK8 requirements handled
- 5 builds successful
- All comparisons pass
- Quirks documented

**Estimated Effort**: 4 days
**Priority**: P0
**Labels**: `tier-1`, `migration`, `jdk8`
**Assignee**: TBD

---

### Issue #3.4: Validate Tier 1 Platforms

**Title**: Final validation of all Tier 1 platforms

**Description**:
Perform final validation across all Tier 1 platforms to ensure consistency and reliability.

**Tasks**:
- [ ] Run simultaneous builds on all Tier 1
- [ ] Compare results across versions
- [ ] Validate performance metrics
- [ ] Check for any regressions
- [ ] Get team sign-off

**Acceptance Criteria**:
- All Tier 1 platforms validated
- No regressions found
- Performance acceptable
- Team sign-off obtained

**Estimated Effort**: 2 days
**Priority**: P0
**Labels**: `tier-1`, `validation`
**Assignee**: TBD

---

## Additional EPICs (Summary)

### EPIC 4: Tier 2 Rollout
- Linux aarch64 platforms
- Mac x64 platforms
- Timeline: Weeks 9-10

**Note**: Mac aarch64 JDK21u and Windows x64 JDK21u moved to Phase 2 (EPIC 2) to support proper implementation and testing of Internal Sign and Assemble stages.

### EPIC 5: Tier 3 Rollout
- Linux aarch64 platforms
- Mac x64 platforms
- AIX platforms
- Linux s390x platforms
- Timeline: Weeks 12-13


### EPIC 7: Edge Cases
- Docker container builds
- Cross-compilation
- Custom build arguments
- Special signing
- Timeline: Weeks 16-17

### EPIC 8: Final Migration
- Complete all platforms
- Cutover execution
- Decommission old pipeline
- Timeline: Weeks 20-25

### EPIC 9: Documentation & Training
- User documentation
- Training materials
- Runbooks
- Timeline: Weeks 20-25

---

## Issue Template

Use this template for creating new migration issues:

```markdown
**Title**: [Platform] Migration to New Pipeline

**Description**:
Migrate [Platform/Version/Variant] to the new modular pipeline architecture.

**Platform Details**:
- OS: [Linux/Mac/Windows/AIX]
- Architecture: [x64/aarch64/ppc64/s390x]
- JDK Version: [jdk8u/jdk11u/jdk17u/jdk21u]
- Variant: Temurin

**Tasks**:
- [ ] Convert configuration to JSON
- [ ] Set up parallel execution job
- [ ] Run 5 parallel builds
- [ ] Compare all artifacts
- [ ] Validate test results
- [ ] Check performance metrics
- [ ] Document any edge cases
- [ ] Get team sign-off

**Acceptance Criteria**:
- [ ] Configuration converted successfully
- [ ] 5 builds completed successfully
- [ ] All artifact comparisons pass (100%)
- [ ] Test results match exactly
- [ ] Performance within acceptable range
- [ ] Edge cases documented
- [ ] Team sign-off obtained

**Estimated Effort**: 3-4 days
**Priority**: [P0/P1/P2]
**Labels**: `migration`, `[tier-1/tier-2/tier-3]`, `[platform]`
**Assignee**: TBD
**Milestone**: [Phase 3 - Gradual Rollout]

**Related Issues**: #[pilot-issue], #[edge-case-issues]
```

---

## Labels to Create

Create these labels in GitHub:

**Priority**:
- `P0` - Critical/Blocker (red)
- `P1` - High Priority (orange)
- `P2` - Medium Priority (yellow)
- `P3` - Low Priority (green)

**Phase**:
- `phase-1` - Foundation (blue)
- `phase-2` - Pilot (blue)
- `phase-3` - Gradual Rollout (blue)
- `phase-4` - Full Migration (blue)

**Type**:
- `epic` - Epic issue (purple)
- `infrastructure` - Infrastructure work (gray)
- `migration` - Platform migration (green)
- `tooling` - Tool development (cyan)
- `documentation` - Documentation (yellow)
- `validation` - Testing/validation (orange)
- `bugfix` - Bug fix (red)

**Platform**:
- `tier-1` - Tier 1 platform (gold)
- `tier-2` - Tier 2 platform (silver)
- `tier-3` - Tier 3 platform (bronze)
- `linux` - Linux platform (blue)
- `mac` - macOS platform (gray)
- `windows` - Windows platform (cyan)
- `aix` - AIX platform (brown)

**Component**:
- `jenkins` - Jenkins-specific (red)
- `dashboard` - Dashboard work (purple)
- `conversion` - Config conversion (green)
- `comparison` - Build comparison (orange)

---

## Milestone Structure

Create these milestones in GitHub:

1. **Phase 1: Foundation** (Weeks 1-3)
   - Due: [3 weeks from start]
   - Description: Establish infrastructure and tooling

2. **Phase 2: Pilot** (Weeks 4-7)
   - Due: [7 weeks from start]
   - Description: Validate approach with pilot platform

3. **Phase 3: Gradual Rollout** (Weeks 8-19)
   - Due: [19 weeks from start]
   - Description: Migrate all platforms incrementally

4. **Phase 4: Full Migration** (Weeks 20-25)
   - Due: [25 weeks from start]
   - Description: Complete migration and decommission old pipeline

---

## Project Board Setup

Create a GitHub Project board with these columns:

1. **Backlog** - Not yet started
2. **Ready** - Ready to work on
3. **In Progress** - Currently being worked on
4. **Review** - Awaiting review
5. **Testing** - In testing phase
6. **Done** - Completed

---

*Document Version: 1.0*
*Last Updated: 2026-05-12*