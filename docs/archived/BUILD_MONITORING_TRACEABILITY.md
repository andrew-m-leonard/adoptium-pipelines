# Build Monitoring and Traceability Architecture

## Overview

This document describes the challenge of monitoring complex multi-platform release builds in Jenkins and proposes a solution using Release UUID traceability integrated with the Test Result Summary Service (TRSS) to provide comprehensive release-level build monitoring.

## Problem Statement

### The Scale Challenge

When submitting a new JDK release build, the pipeline orchestration creates a complex hierarchy:

```
Release Build Submission (e.g., JDK 21.0.5+11)
    │
    ├─ Triggers 12 Platform BUILD Pipelines
    │   ├─ Linux x64 Build Pipeline
    │   ├─ Linux aarch64 Build Pipeline
    │   ├─ Mac x64 Build Pipeline
    │   ├─ Mac aarch64 Build Pipeline
    │   ├─ Windows x64 Build Pipeline
    │   ├─ Windows x86-32 Build Pipeline
    │   ├─ AIX ppc64 Build Pipeline
    │   ├─ Solaris x64 Build Pipeline
    │   ├─ Alpine Linux x64 Build Pipeline
    │   ├─ Alpine Linux aarch64 Build Pipeline
    │   ├─ Linux ppc64le Build Pipeline
    │   └─ Linux s390x Build Pipeline
    │
    └─ Each Build Pipeline Triggers 12 AQA TEST Pipelines
        ├─ Sanity Tests
        ├─ Extended Tests
        ├─ Special Tests
        ├─ Functional Tests
        ├─ Performance Tests
        ├─ JCK Tests
        ├─ External Tests
        ├─ System Tests
        ├─ OpenJ9 Tests
        ├─ Perf Tests
        └─ ... (additional test suites)

Total: 1 Release + 12 Builds + 144 Test Pipelines = 157 Pipeline Executions
```

### Jenkins UI Limitations

**Jenkins is optimized for viewing:**
- ✅ Individual Jobs (pipeline definitions)
- ✅ Individual Pipeline Runs (single execution)
- ✅ Job-level build history

**Jenkins struggles with:**
- ❌ **Release-level aggregation**: Cannot easily view all builds for a specific release
- ❌ **Cross-pipeline correlation**: No native way to link related builds across different pipelines
- ❌ **Rebuild tracking**: When a platform is rebuilt, hard to track which builds belong to the same release attempt
- ❌ **Test re-run tracking**: When tests are re-run, difficult to associate with the original build
- ❌ **Live release dashboard**: No single view showing status of all components for a release

### Real-World Scenario

```
Scenario: JDK 21.0.5+11 Release Build

Initial Submission:
├─ 12 platform builds triggered
├─ 10 builds succeed
├─ 2 builds fail (Mac x64, Windows x64)
└─ 120 test pipelines triggered (10 platforms × 12 test suites)

Rebuild Actions:
├─ Mac x64 rebuilt (attempt #2)
├─ Windows x64 rebuilt (attempt #2)
└─ Windows x64 rebuilt again (attempt #3)

Test Re-runs:
├─ Linux x64: 3 test suites re-run due to infrastructure issues
├─ Mac aarch64: 1 test suite re-run due to flaky test
└─ AIX ppc64: 2 test suites re-run due to timeout

Question: Which builds and tests are part of the final release?
Answer: Extremely difficult to determine in Jenkins UI
```

### Navigation Complexity

**To track a single release in Jenkins UI, you must:**

1. Remember or note down the initial release trigger build number
2. Navigate to each of 12 platform build pipelines
3. For each platform, identify which build number corresponds to this release
4. Check if that build was successful or if a rebuild was needed
5. If rebuilt, find the rebuild build number
6. For each successful build, navigate to 12 test pipeline jobs
7. For each test pipeline, identify which build number corresponds to this release's build
8. Check if tests were re-run and find the latest test build number
9. Repeat for all 144 test pipeline executions

**Total navigation steps: 157+ separate Jenkins pages to view**

## Current State: TRSS (Test Result Summary Service)

### What is TRSS?

TRSS is an external tool used by the Adoptium project that:
- Collates build and test results from Jenkins pipelines
- Provides aggregated views of test results
- Offers widget capabilities for custom dashboards
- Stores historical test data for trend analysis

### Current TRSS Capabilities

**Strengths:**
- ✅ Aggregates test results across multiple test runs
- ✅ Provides historical trend analysis
- ✅ Offers customizable widgets for dashboards
- ✅ Better test result visualization than Jenkins

**Current Limitations:**
- ❌ Views are organized by **pipeline/job**, not by **release**
- ❌ Cannot easily filter "all builds for JDK 21.0.5+11"
- ❌ No correlation between related builds across platforms
- ❌ Difficult to distinguish original builds from rebuilds
- ❌ No live "release dashboard" showing all components

### TRSS Architecture Constraint

**Important:** TRSS is a **read-only** system from Jenkins' perspective. Jenkins pipelines cannot push data to TRSS. Instead, TRSS must **poll** Jenkins APIs to discover and index build information.

## Proposed Solution: Release UUID Traceability

### Core Concept

Introduce a **Release UUID** (Universally Unique Identifier) that:
1. Is generated at release submission time
2. Is passed as a **build parameter** to all downstream build pipelines
3. Is passed from build pipelines to all test pipelines as a **build parameter**
4. Is stored in Jenkins build metadata (via parameters)
5. Is discoverable by TRSS via Jenkins API polling

**Note:** The term "Release UUID" is more accurate than "Build UUID" because it identifies a release across all its builds and tests.

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Release Submission                                          │
│ ┌─────────────────────────────────────────────────────┐   │
│ │ Generate Release UUID                               │   │
│ │ UUID: "550e8400-e29b-41d4-a716-446655440000"       │   │
│ │ Release: "JDK 21.0.5+11"                           │   │
│ │ Timestamp: "2024-01-15T10:30:00Z"                  │   │
│ └─────────────────────────────────────────────────────┘   │
└────────┬────────────────────────────────────────────────────┘
         │
         │ Pass UUID as build parameter to all platform builds
         │
         ├──────────┬──────────┬──────────┬──────────┐
         ▼          ▼          ▼          ▼          ▼
    ┌─────────────────────────────────────────────────────┐
    │ Platform Build Pipeline (e.g., Linux x64)           │
    │ ┌─────────────────────────────────────────────┐   │
    │ │ Receive RELEASE_UUID as build parameter     │   │
    │ │ UUID: "550e8400-e29b-41d4-a716-446655440000"│   │
    │ │ Platform: "linux-x64"                       │   │
    │ │ Build Number: #1234                         │   │
    │ └─────────────────────────────────────────────┘   │
    │                                                     │
    │ UUID stored in Jenkins build parameters             │
    │ (automatically indexed by Jenkins)                  │
    │                                                     │
    │ Pass UUID to test pipelines as parameter           │
    │         │                                           │
    └─────────┼───────────────────────────────────────────┘
              │
              ├──────────┬──────────┬──────────┐
              ▼          ▼          ▼          ▼
         ┌─────────────────────────────────────────────┐
         │ AQA Test Pipeline (e.g., Sanity Tests)      │
         │ ┌─────────────────────────────────────┐   │
         │ │ Receive RELEASE_UUID as parameter   │   │
         │ │ UUID: "550e8400-..."                │   │
         │ │ Platform: "linux-x64"               │   │
         │ │ Test Suite: "sanity"                │   │
         │ │ Test Build Number: #5678            │   │
         │ └─────────────────────────────────────┘   │
         │                                             │
         │ UUID stored in Jenkins build parameters     │
         └─────────────────────────────────────────────┘
                        │
                        │ TRSS polls Jenkins API
                        ▼
         ┌─────────────────────────────────────────────┐
         │ TRSS Polling Service                        │
         │                                             │
         │ 1. Query Jenkins API for recent builds     │
         │    (last 14 days)                          │
         │ 2. Extract RELEASE_UUID from parameters    │
         │ 3. Index builds by RELEASE_UUID            │
         │ 4. Cache indexed builds (don't re-query)   │
         │ 5. Provide dashboard views                 │
         └─────────────────────────────────────────────┘
```

### UUID Propagation Flow

```
1. Release Submission
   └─ Generate UUID: "550e8400-e29b-41d4-a716-446655440000"
   └─ Metadata: { release: "JDK 21.0.5+11", timestamp: "2024-01-15T10:30:00Z" }

2. Trigger Platform Builds (12 pipelines)
   └─ Pass UUID as parameter: RELEASE_UUID="550e8400-..."
   └─ Each platform receives UUID as build parameter

3. Platform Build Execution
   └─ UUID automatically stored in Jenkins build parameters
   └─ UUID visible in Jenkins UI (build parameters section)
   └─ On success, trigger test pipelines with same UUID

4. Test Pipeline Execution
   └─ Receive UUID as build parameter from build pipeline
   └─ UUID automatically stored in Jenkins build parameters

5. TRSS Polling
   └─ Periodically query Jenkins API for recent builds
   └─ Extract RELEASE_UUID from build parameters
   └─ Index builds in TRSS database
   └─ Provide dashboard views by RELEASE_UUID

6. Rebuild Scenario
   └─ Same UUID used for rebuild
   └─ TRSS tracks: original build + rebuild(s)
   └─ Latest build with same UUID = current state

7. Test Re-run Scenario
   └─ Same UUID used for test re-run
   └─ TRSS tracks: original test + re-run(s)
   └─ Latest test with same UUID = current state
```

## Implementation Details

### 1. UUID Generation in Release Pipeline

```groovy
// Jenkinsfile for release trigger pipeline
pipeline {
    agent any

    environment {
        // Generate UUID at pipeline start
        RELEASE_UUID = sh(
            script: 'uuidgen',
            returnStdout: true
        ).trim()

        RELEASE_VERSION = "JDK 21.0.5+11"
        RELEASE_TIMESTAMP = sh(
            script: 'date -u +"%Y-%m-%dT%H:%M:%SZ"',
            returnStdout: true
        ).trim()
    }

    stages {
        stage('Initialize Release') {
            steps {
                script {
                    echo "Release UUID: ${RELEASE_UUID}"
                    echo "Release Version: ${RELEASE_VERSION}"
                    echo "Release Timestamp: ${RELEASE_TIMESTAMP}"

                    // Store in Jenkins build description for easy viewing
                    currentBuild.description = """
                        UUID: ${RELEASE_UUID}
                        Release: ${RELEASE_VERSION}
                    """.stripIndent()

                    // Store in artifact metadata file
                    writeJSON file: 'release-metadata.json', json: [
                        releaseUuid: env.RELEASE_UUID,
                        releaseVersion: env.RELEASE_VERSION,
                        releaseTimestamp: env.RELEASE_TIMESTAMP
                    ]

                    // Archive metadata
                    archiveArtifacts artifacts: 'release-metadata.json'
                }
            }
        }

        stage('Trigger Platform Builds') {
            steps {
                script {
                    def platforms = [
                        'linux-x64', 'linux-aarch64', 'mac-x64',
                        'mac-aarch64', 'windows-x64', 'windows-x86-32',
                        'aix-ppc64', 'solaris-x64', 'alpine-linux-x64',
                        'alpine-linux-aarch64', 'linux-ppc64le', 'linux-s390x'
                    ]

                    platforms.each { platform ->
                        build job: "build-${platform}",
                              parameters: [
                                  string(name: 'RELEASE_UUID', value: env.RELEASE_UUID),
                                  string(name: 'RELEASE_VERSION', value: env.RELEASE_VERSION),
                                  string(name: 'PLATFORM', value: platform)
                              ],
                              wait: false  // Trigger all in parallel
                    }
                }
            }
        }
    }
}
```

### 2. UUID Storage in Platform Build Pipeline

```groovy
// Platform build pipeline
pipeline {
    agent any

    parameters {
        string(name: 'RELEASE_UUID', description: 'Release UUID for this build')
        string(name: 'RELEASE_VERSION', description: 'Release Version (e.g., JDK 21.0.5+11)')
        string(name: 'PLATFORM', description: 'Build Platform (e.g., linux-x64)')
    }

    stages {
        stage('Initialize') {
            steps {
                script {
                    echo "Release UUID: ${params.RELEASE_UUID}"
                    echo "Release: ${params.RELEASE_VERSION}"
                    echo "Platform: ${params.PLATFORM}"

                    // Store in build description for easy viewing
                    currentBuild.description = """
                        UUID: ${params.RELEASE_UUID}
                        Release: ${params.RELEASE_VERSION}
                        Platform: ${params.PLATFORM}
                    """.stripIndent()

                    // UUID is automatically stored in build parameters
                    // and is queryable via Jenkins API
                }
            }
        }

        stage('Build') {
            steps {
                script {
                    // Build stages...

                    // Store UUID in artifact metadata
                    writeJSON file: 'artifacts/metadata.json', json: [
                        releaseUuid: params.RELEASE_UUID,
                        releaseVersion: params.RELEASE_VERSION,
                        platform: params.PLATFORM,
                        jenkinsBuildNumber: env.BUILD_NUMBER,
                        jenkinsBuildUrl: env.BUILD_URL,
                        buildTimestamp: sh(
                            script: 'date -u +"%Y-%m-%dT%H:%M:%SZ"',
                            returnStdout: true
                        ).trim()
                    ]

                    archiveArtifacts artifacts: 'artifacts/metadata.json'
                }
            }
        }

        stage('Trigger Tests') {
            steps {
                script {
                    def testSuites = [
                        'sanity', 'extended', 'special', 'functional',
                        'performance', 'jck', 'external', 'system',
                        'openjdk', 'perf', 'stress', 'integration'
                    ]

                    testSuites.each { suite ->
                        build job: "test-${params.PLATFORM}-${suite}",
                              parameters: [
                                  string(name: 'RELEASE_UUID', value: params.RELEASE_UUID),
                                  string(name: 'RELEASE_VERSION', value: params.RELEASE_VERSION),
                                  string(name: 'PLATFORM', value: params.PLATFORM),
                                  string(name: 'TEST_SUITE', value: suite),
                                  string(name: 'BUILD_NUMBER', value: env.BUILD_NUMBER)
                              ],
                              wait: false
                    }
                }
            }
        }
    }
}
```

### 3. UUID Storage in Test Pipeline

```groovy
// Test pipeline
pipeline {
    agent any

    parameters {
        string(name: 'RELEASE_UUID', description: 'Release UUID')
        string(name: 'RELEASE_VERSION', description: 'Release Version')
        string(name: 'PLATFORM', description: 'Build Platform')
        string(name: 'TEST_SUITE', description: 'Test Suite Name')
        string(name: 'BUILD_NUMBER', description: 'Build Pipeline Build Number')
    }

    stages {
        stage('Initialize') {
            steps {
                script {
                    currentBuild.description = """
                        UUID: ${params.RELEASE_UUID}
                        Release: ${params.RELEASE_VERSION}
                        Platform: ${params.PLATFORM}
                        Suite: ${params.TEST_SUITE}
                        Build: #${params.BUILD_NUMBER}
                    """.stripIndent()

                    // UUID automatically stored in build parameters
                }
            }
        }

        stage('Run Tests') {
            steps {
                script {
                    // Run tests...
                }
            }
        }
    }
}
```

## TRSS Polling Strategy

### Overview

Since TRSS is read-only and cannot receive push notifications from Jenkins, it must poll the Jenkins API to discover builds with Release UUIDs. However, this can be optimized using several strategies:

### Optimization Strategies

1. **Time Window Filtering**: Only query builds from last 14 days
2. **Job Name Patterns**: Use naming conventions to identify relevant jobs
3. **Caching**: Don't re-query builds already indexed
4. **Incremental Updates**: Only query new builds since last poll
5. **Batch Processing**: Query multiple jobs in parallel

### TRSS Polling Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ TRSS Polling Service (runs every 5-15 minutes)             │
│                                                             │
│ 1. Get list of relevant Jenkins jobs                       │
│    └─ Pattern: build-*, test-*                            │
│                                                             │
│ 2. For each job, query recent builds                       │
│    └─ Filter: builds from last 14 days                    │
│    └─ Filter: builds not yet indexed                      │
│                                                             │
│ 3. Extract RELEASE_UUID from build parameters              │
│    └─ Skip builds without RELEASE_UUID                    │
│                                                             │
│ 4. Store in TRSS database                                  │
│    └─ Index by RELEASE_UUID                               │
│    └─ Mark build as indexed (don't query again)           │
│                                                             │
│ 5. Update release dashboard                                │
│    └─ Aggregate builds by RELEASE_UUID                    │
└─────────────────────────────────────────────────────────────┘
```

### Implementation: TRSS Polling Service

```python
import requests
import json
from datetime import datetime, timedelta
from typing import List, Dict, Set
import time

class JenkinsPoller:
    def __init__(self, jenkins_url: str, auth: tuple, trss_db):
        self.jenkins_url = jenkins_url
        self.auth = auth
        self.trss_db = trss_db
        self.indexed_builds: Set[str] = set()  # Cache of indexed builds

    def get_relevant_jobs(self) -> List[str]:
        """
        Get list of jobs that might contain RELEASE_UUID.
        Uses naming conventions to filter.
        """
        api_url = f"{self.jenkins_url}/api/json?tree=jobs[name]"
        response = requests.get(api_url, auth=self.auth)
        response.raise_for_status()

        all_jobs = response.json()['jobs']

        # Filter by naming convention
        relevant_jobs = [
            job['name'] for job in all_jobs
            if job['name'].startswith('build-') or
               job['name'].startswith('test-') or
               job['name'].startswith('release-')
        ]

        return relevant_jobs

    def get_recent_builds(
        self,
        job_name: str,
        days: int = 14
    ) -> List[Dict]:
        """
        Get builds from last N days that haven't been indexed yet.
        """
        cutoff_timestamp = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

        # Query builds with parameters
        api_url = f"{self.jenkins_url}/job/{job_name}/api/json"
        params = {
            'tree': 'builds[number,timestamp,result,url,actions[parameters[name,value]]]'
        }

        response = requests.get(api_url, params=params, auth=self.auth)
        response.raise_for_status()

        all_builds = response.json().get('builds', [])

        # Filter by timestamp and indexed status
        recent_builds = []
        for build in all_builds:
            # Check timestamp
            if build['timestamp'] < cutoff_timestamp:
                continue

            # Check if already indexed
            build_key = f"{job_name}#{build['number']}"
            if build_key in self.indexed_builds:
                continue

            recent_builds.append(build)

        return recent_builds

    def extract_release_uuid(self, build: Dict) -> str:
        """
        Extract RELEASE_UUID from build parameters.
        Returns None if not found.
        """
        for action in build.get('actions', []):
            parameters = action.get('parameters', [])
            for param in parameters:
                if param.get('name') == 'RELEASE_UUID':
                    return param.get('value')
        return None

    def index_build(self, job_name: str, build: Dict, release_uuid: str):
        """
        Store build information in TRSS database.
        """
        build_data = {
            'release_uuid': release_uuid,
            'job_name': job_name,
            'build_number': build['number'],
            'jenkins_url': build['url'],
            'status': build.get('result', 'RUNNING'),
            'timestamp': datetime.fromtimestamp(build['timestamp'] / 1000),
            'indexed_at': datetime.now()
        }

        # Store in database
        self.trss_db.insert_build(build_data)

        # Mark as indexed
        build_key = f"{job_name}#{build['number']}"
        self.indexed_builds.add(build_key)

    def poll_once(self):
        """
        Perform one polling cycle.
        """
        print(f"[{datetime.now()}] Starting polling cycle...")

        # Get relevant jobs
        jobs = self.get_relevant_jobs()
        print(f"Found {len(jobs)} relevant jobs")

        total_builds_found = 0
        total_builds_indexed = 0

        # Process each job
        for job_name in jobs:
            try:
                # Get recent builds
                builds = self.get_recent_builds(job_name, days=14)
                total_builds_found += len(builds)

                # Process each build
                for build in builds:
                    # Extract RELEASE_UUID
                    release_uuid = self.extract_release_uuid(build)

                    if release_uuid:
                        # Index this build
                        self.index_build(job_name, build, release_uuid)
                        total_builds_indexed += 1
                        print(f"  Indexed: {job_name} #{build['number']} -> {release_uuid[:8]}...")

            except Exception as e:
                print(f"  Error processing {job_name}: {e}")
                continue

        print(f"Polling complete: {total_builds_indexed}/{total_builds_found} builds indexed")

    def run_continuous(self, interval_minutes: int = 10):
        """
        Run polling service continuously.
        """
        print(f"Starting continuous polling (every {interval_minutes} minutes)...")

        while True:
            try:
                self.poll_once()
            except Exception as e:
                print(f"Error in polling cycle: {e}")

            # Wait before next poll
            time.sleep(interval_minutes * 60)

# Usage
if __name__ == '__main__':
    from trss_database import TRSSDatabase

    db = TRSSDatabase(connection_string="postgresql://...")

    poller = JenkinsPoller(
        jenkins_url="https://ci.adoptium.net",
        auth=("username", "api_token"),
        trss_db=db
    )

    # Run continuous polling every 10 minutes
    poller.run_continuous(interval_minutes=10)
```

### Performance Analysis

**Polling Efficiency:**

```
Assumptions:
- 50 relevant jobs (build-* and test-*)
- Average 20 builds per job in last 14 days
- Total: 1000 builds to check

Polling Cycle:
1. Get job list: ~1 second
2. Query 50 jobs (parallel): ~5-10 seconds
3. Extract parameters: ~1 second
4. Database inserts: ~2 seconds
Total: ~10-15 seconds per cycle

With 10-minute polling interval:
- Responsiveness: New builds discovered within 10 minutes
- API load: 6 polling cycles per hour
- Network bandwidth: ~5 MB per cycle = 30 MB/hour

Optimization with caching:
- First poll: Index all 1000 builds (~15 seconds)
- Subsequent polls: Only new builds (~2-5 seconds)
- Steady state: ~10-20 new builds per cycle
```

**Scalability:**

```
For 100 jobs with 50 builds each (5000 total builds):
- First poll: ~30-45 seconds
- Subsequent polls: ~5-10 seconds
- Still very manageable
```

### TRSS Database Schema

```sql
-- Builds table
CREATE TABLE builds (
    id SERIAL PRIMARY KEY,
    release_uuid UUID NOT NULL,
    release_version VARCHAR(50),
    job_name VARCHAR(255) NOT NULL,
    platform VARCHAR(50),
    build_number INTEGER NOT NULL,
    jenkins_url TEXT NOT NULL,
    status VARCHAR(20) NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    indexed_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(job_name, build_number)  -- Prevent duplicate indexing
);

-- Indexes for fast UUID lookups
CREATE INDEX idx_builds_release_uuid ON builds(release_uuid);
CREATE INDEX idx_builds_release_uuid_platform ON builds(release_uuid, platform);
CREATE INDEX idx_builds_timestamp ON builds(timestamp DESC);
CREATE INDEX idx_builds_indexed_at ON builds(indexed_at DESC);

-- Test results table
CREATE TABLE test_results (
    id SERIAL PRIMARY KEY,
    release_uuid UUID NOT NULL,
    release_version VARCHAR(50),
    platform VARCHAR(50) NOT NULL,
    test_suite VARCHAR(100) NOT NULL,
    build_number INTEGER NOT NULL,
    test_build_number INTEGER NOT NULL,
    jenkins_url TEXT NOT NULL,
    status VARCHAR(20) NOT NULL,
    total_tests INTEGER,
    passed_tests INTEGER,
    failed_tests INTEGER,
    skipped_tests INTEGER,
    timestamp TIMESTAMP NOT NULL,
    indexed_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(platform, test_suite, test_build_number)
);

-- Indexes for test results
CREATE INDEX idx_test_results_release_uuid ON test_results(release_uuid);
CREATE INDEX idx_test_results_release_uuid_platform ON test_results(release_uuid, platform);
```

### TRSS Query API

```python
class TRSSQueryAPI:
    def __init__(self, db):
        self.db = db

    def get_builds_by_release_uuid(self, release_uuid: str) -> List[Dict]:
        """
        Get all builds for a release.
        Fast: Uses database index on release_uuid.
        """
        query = """
            SELECT * FROM builds
            WHERE release_uuid = %s
            ORDER BY timestamp DESC
        """
        return self.db.execute(query, (release_uuid,))

    def get_latest_build_per_platform(self, release_uuid: str) -> Dict[str, Dict]:
        """
        Get the most recent build for each platform.
        Handles rebuilds automatically.
        """
        query = """
            SELECT DISTINCT ON (platform)
                platform, build_number, status, jenkins_url, timestamp
            FROM builds
            WHERE release_uuid = %s
            ORDER BY platform, timestamp DESC
        """
        results = self.db.execute(query, (release_uuid,))

        return {row['platform']: row for row in results}

    def get_release_status(self, release_uuid: str) -> Dict:
        """
        Get complete release status.
        """
        # Get builds
        builds = self.get_builds_by_release_uuid(release_uuid)
        latest_builds = self.get_latest_build_per_platform(release_uuid)

        # Get tests
        tests_query = """
            SELECT * FROM test_results
            WHERE release_uuid = %s
            ORDER BY timestamp DESC
        """
        tests = self.db.execute(tests_query, (release_uuid,))

        # Aggregate status
        return {
            'releaseUuid': release_uuid,
            'releaseVersion': builds[0]['release_version'] if builds else None,
            'totalBuilds': len(latest_builds),
            'successfulBuilds': sum(1 for b in latest_builds.values() if b['status'] == 'SUCCESS'),
            'failedBuilds': sum(1 for b in latest_builds.values() if b['status'] == 'FAILURE'),
            'runningBuilds': sum(1 for b in latest_builds.values() if b['status'] is None),
            'totalTests': len(tests),
            'passedTests': sum(t['passed_tests'] for t in tests),
            'failedTests': sum(t['failed_tests'] for t in tests),
            'builds': latest_builds,
            'tests': tests
        }

# REST API endpoint
from flask import Flask, jsonify, request

app = Flask(__name__)
api = TRSSQueryAPI(db)

@app.route('/api/releases/<release_uuid>')
def get_release(release_uuid):
    """
    Get complete release status.
    Example: GET /api/releases/550e8400-e29b-41d4-a716-446655440000
    """
    status = api.get_release_status(release_uuid)
    return jsonify(status)

@app.route('/api/builds')
def get_builds():
    """
    Query builds by release UUID.
    Example: GET /api/builds?releaseUuid=550e8400-...
    """
    release_uuid = request.args.get('releaseUuid')
    builds = api.get_builds_by_release_uuid(release_uuid)
    return jsonify(builds)
```

## Enhanced TRSS Dashboard

### Release Dashboard View

**URL:** `https://trss.adoptium.net/release/{RELEASE_UUID}`

**Dashboard Features:**

1. **Release Overview**
   - Release UUID
   - Release version (e.g., JDK 21.0.5+11)
   - Start timestamp
   - Overall status (IN PROGRESS, COMPLETE, FAILED)
   - Progress: X/12 builds complete, Y/144 tests complete

2. **Platform Builds Table**
   - Platform name
   - Build status (SUCCESS, FAILURE, RUNNING)
   - Build number (with link to Jenkins)
   - Rebuild indicator (if applicable)
   - Test progress (X/12 tests complete)
   - Actions (View details, View in Jenkins)

3. **Test Summary**
   - Total tests run
   - Pass rate
   - Failed tests (with links)
   - Running tests

4. **Timeline**
   - Chronological view of all events
   - Build starts/completions
   - Rebuild events
   - Test starts/completions
   - Test re-run events

5. **Auto-refresh**
   - Dashboard auto-refreshes every 30-60 seconds
   - Shows live updates as builds complete

### Query Performance

```
Database Query Performance:
- Get all builds for release: ~10-20ms (indexed)
- Get latest build per platform: ~15-25ms (indexed)
- Get all tests for release: ~20-30ms (indexed)
- Complete release status: ~50-100ms (single query)

Dashboard Load Time:
- Initial load: ~500ms-1s
- Auto-refresh: ~100-200ms (cached data)
```

## Benefits

### 1. Unified Release View

**Before:**
- Navigate 157+ Jenkins pages to understand release status
- Manual tracking of which builds belong to which release
- Difficult to identify rebuilds vs original builds

**After:**
- Single dashboard shows entire release status
- Automatic correlation of all related builds
- Clear visibility of rebuilds and re-runs

### 2. Rebuild Tracking

**Before:**
```
Question: Which Mac x64 build is part of the release?
Answer: Must manually check Jenkins history and timestamps
```

**After:**
```
Query: SELECT * FROM builds WHERE release_uuid='550e8400-...' AND platform='mac-x64'
Result:
  - Build #1236 (FAILED, attempt 1, 11:45)
  - Build #1237 (SUCCESS, attempt 2, 12:15) ← This is the one
```

### 3. No Jenkins Push Required

**Advantage:**
- TRSS remains read-only (no security concerns)
- No changes to Jenkins security model
- No risk of Jenkins being overwhelmed by push requests
- TRSS can be restarted/rebuilt without affecting Jenkins

### 4. Efficient Polling

**Optimizations:**
- Only query builds from last 14 days (not entire history)
- Cache indexed builds (don't re-query)
- Use job naming conventions to filter relevant jobs
- Parallel job queries for speed
- 10-minute polling interval provides good responsiveness

### 5. Scalability

**Performance:**
- Polling cycle: 10-15 seconds for 1000 builds
- Database queries: 50-100ms for complete release status
- Dashboard load: < 1 second
- Scales to millions of historical builds

## Implementation Phases

### Phase 1: Jenkins Pipeline Updates (Week 1-2)

**Tasks:**
1. Update release trigger pipeline to generate RELEASE_UUID
2. Update platform build pipelines to accept RELEASE_UUID parameter
3. Update test pipelines to accept RELEASE_UUID parameter
4. Store UUID in build descriptions for visibility
5. Test with pilot release

**Deliverables:**
- All pipelines propagate RELEASE_UUID
- UUID visible in Jenkins UI
- UUID stored in build parameters

### Phase 2: TRSS Polling Service (Week 3-4)

**Tasks:**
1. Implement Jenkins API polling service
2. Create TRSS database schema
3. Implement build indexing logic
4. Add caching and optimization
5. Deploy polling service

**Deliverables:**
- Polling service running continuously
- Builds indexed in TRSS database
- API endpoints for querying by RELEASE_UUID

### Phase 3: TRSS Dashboard (Week 5-8)

**Tasks:**
1. Design release dashboard UI
2. Implement release overview page
3. Implement platform builds table
4. Implement test summary section
5. Add timeline visualization
6. Add auto-refresh capability

**Deliverables:**
- Release dashboard accessible via URL
- Real-time status updates
- Drill-down to platform and test details

### Phase 4: Optimization & Monitoring (Week 9-10)

**Tasks:**
1. Optimize database queries
2. Add monitoring for polling service
3. Add alerting for polling failures
4. Performance testing
5. Documentation

**Deliverables:**
- Optimized query performance
- Monitoring dashboards
- Complete documentation

## Success Metrics

### Operational Metrics

**Before Implementation:**
- Time to understand release status: 30-60 minutes
- Time to identify current builds: 15-30 minutes
- Time to find failed tests: 20-40 minutes
- Number of pages to view: 157+

**After Implementation:**
- Time to understand release status: 30 seconds
- Time to identify current builds: Instant
- Time to find failed tests: 5 seconds
- Number of pages to view: 1

**Improvement:**
- 98% reduction in time to understand release status
- 100% reduction in manual tracking effort
- Single source of truth for release status

### Technical Metrics

**Targets:**
- Polling cycle time: < 15 seconds
- Build discovery latency: < 10 minutes
- Database query time: < 100ms
- Dashboard load time: < 1 second

## Conclusion

The Release UUID traceability system with TRSS polling provides an efficient solution for monitoring complex multi-platform releases:

**Key Advantages:**

1. **Simple Implementation**: Uses standard Jenkins build parameters
2. **No Security Changes**: TRSS remains read-only
3. **Efficient Polling**: Optimized with caching and time windows
4. **Fast Queries**: Database indexes provide sub-100ms queries
5. **Scalable**: Handles millions of builds
6. **Unified View**: Single dashboard for entire release

**Trade-offs:**

- **Polling Latency**: 10-minute delay vs real-time push (acceptable for release monitoring)
- **API Load**: Minimal (one poll every 10 minutes)
- **Complexity**: Polling service adds one component (manageable)

This solution transforms release monitoring from a painful manual process into a streamlined experience with a single, auto-updating dashboard.

---

**Related Documentation:**
- [Pipeline Orchestration Architecture](./PIPELINE_ORCHESTRATION_ARCHITECTURE.md) - Independent build and test pipelines
- [CI-Agnostic Architecture](../CI_AGNOSTIC_ARCHITECTURE.md) - Overall architecture design
- [Restartability Guide](./RESTARTABILITY_GUIDE.md) - Stage restart implementation