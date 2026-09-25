/*
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
/**
 * Default Core Implementation: 14-aqa-tests
 *
 * Triggers the downstream AQA_Test_Pipeline job (or AQA_Test_Pipeline_RELEASE
 * for release builds) with the JDK archive URL and associated test-image and
 * SBOM URLs derived from the archived JDK filename.
 *
 * Equivalent to the legacy runAQATests(jdkFileName) function in
 * openjdk_build_pipeline.groovy.
 *
 * The downstream job is fired with wait:false / waitForStart:true — it runs
 * asynchronously and a link is appended to the build description. Failures to
 * trigger are caught and set the build result to FAILURE without throwing, so
 * the pipeline can continue to subsequent stages.
 *
 * Gate condition (enforced by stageCondition in 14-aqa-tests.params.json):
 *   - RUN_TESTS must be true
 *
 * Environment Variables (set by StageScriptRunner.run() via withEnv, and
 * ConfigHelper.generatePipelineConfig()):
 *   INPUT_ARTIFACTS_DIR  - Directory containing archived JDK artifacts
 *   BUILD_URL            - URL of the current Jenkins build
 *   RELEASE_TYPE         - NIGHTLY | WEEKLY | RELEASE
 *   SCM_REF              - Source tag/ref used for this build
 *   AQA_REF              - (stage param) aqa-tests branch override; falls back to CONFIG_AQA_REF
 *   CONFIG_AQA_REF       - aqa-tests branch from config repo defaults
 *   CONFIG_VARIANT       - JDK variant (temurin, …)
 *   CONFIG_TARGET_OS     - Target OS (linux, windows, mac, …)
 *   CONFIG_ARCHITECTURE  - Architecture (x64, aarch64, …)
 *   CONFIG_JAVA_TO_BUILD - Java version string (jdk21, jdk8u, …)
 */

/**
 * Entry point called by StageScriptRunner._dispatch():
 *   def script = load(found.path)
 *   exitCode = script(config) ?: EXIT_SUCCESS
 */
int call(Map config) {

    // ── Gate check ────────────────────────────────────────────────────────────
    String runTests = env.RUN_TESTS ?: ''
    if (runTests.toLowerCase() != 'true') {
        echo "ℹ️  14-aqa-tests: RUN_TESTS='${runTests}' is not true — skipping"
        return 0
    }

    // ── Resolve build context ─────────────────────────────────────────────────
    String releaseType  = (env.RELEASE_TYPE ?: 'NIGHTLY').toUpperCase()
    String scmRef       = env.SCM_REF        ?: ''
    String variant      = env.CONFIG_VARIANT ?: ''
    String targetOs     = env.CONFIG_TARGET_OS ?: ''
    String architecture = env.CONFIG_ARCHITECTURE ?: ''
    String javaToBuild  = (env.CONFIG_JAVA_TO_BUILD ?: '').trim().toUpperCase()
    String buildUrl     = env.BUILD_URL ?: ''
    String inputDir     = env.INPUT_ARTIFACTS_DIR ?: env.WORKSPACE

    // ── Derive JDK version number from CONFIG_JAVA_TO_BUILD (e.g. "JDK21" → "21") ──
    String jdkVersion = javaToBuild.replaceAll(/[^0-9]/, '')

    // ── Map architecture to AQA naming convention ─────────────────────────────
    String arch = architecture
    if (arch == 'x64') {
        arch = 'x86-64'
    }
    String archOsList = "${arch}_${targetOs}"

    // ── Resolve AQA branch — stage param takes precedence over config default ──
    String aqaBranch = env.AQA_REF?.trim() ?: env.CONFIG_AQA_REF?.trim() ?: 'master'

    // ── Determine build_type and job name from RELEASE_TYPE ───────────────────
    String buildType = 'nightly'
    String releaseAppendix = ''
    if (releaseType == 'RELEASE') {
        buildType = 'release'
        if (scmRef && aqaBranch != 'master') {
            releaseAppendix = '_RELEASE'
        }
    } else if (releaseType == 'WEEKLY') {
        buildType = 'weekly'
    }
    String aqaJobName = "AQA_Test_Pipeline${releaseAppendix}"

    // ── Find the JDK archive in INPUT_ARTIFACTS_DIR ───────────────────────────
    // Extension is .zip on Windows, .tar.gz everywhere else.
    String extension = (targetOs == 'windows') ? 'zip' : 'tar.gz'
    String jdkFileName = sh(
        script: "find '${inputDir}' -maxdepth 1 -name 'OpenJDK*-jdk_*.${extension}' -printf '%f\\n' 2>/dev/null | head -1 || true",
        returnStdout: true
    ).trim()

    if (!jdkFileName) {
        echo "❌ 14-aqa-tests: no JDK archive (OpenJDK*-jdk_*.${extension}) found in ${inputDir}"
        currentBuild.result = 'FAILURE'
        return 1
    }

    // ── Build CUSTOMIZED_SDK_URL — JDK archive + test image (if not JDK 8 temurin) ──
    String sdkUrl = "${buildUrl}artifact/workspace/target/${jdkFileName}"

    boolean isJdk8Temurin = (jdkVersion == '8' && variant == 'temurin')
    if (!isJdk8Temurin) {
        String testImageName = jdkFileName.replace('-jdk_', '-testimage_')
        sdkUrl += " ${buildUrl}artifact/workspace/target/${testImageName}"
    }

    // Append SBOM URL when CREATE_SBOM is enabled (required by the special.system reproducible test)
    String createSbom = env.CREATE_SBOM ?: ''
    if (createSbom.toLowerCase() == 'true') {
        String sbomName = jdkFileName.replace('-jdk_', '-sbom_')
        sbomName = (targetOs == 'windows')
            ? sbomName.replace('.zip',   '.json')
            : sbomName.replace('.tar.gz', '.json')
        sdkUrl += " ${buildUrl}artifact/workspace/target/${sbomName}"
    }

    // ── Log resolved parameters ───────────────────────────────────────────────
    echo "=== AQA Test Stage ==="
    echo "  Job              : ${aqaJobName}"
    echo "  JDK_VERSIONS     : ${jdkVersion}"
    echo "  BUILD_TYPE       : ${buildType}"
    echo "  VARIANT          : ${variant == 'temurin' ? 'hotspot' : variant}"
    echo "  PLATFORMS        : ${archOsList}"
    echo "  ADOPTOPENJDK_BRANCH: ${aqaBranch}"
    echo "  CUSTOMIZED_SDK_URL : ${sdkUrl}"

    // ── Trigger AQA_Test_Pipeline (fire-and-forget) ───────────────────────────
    try {
        String displayName = "jdk${jdkVersion} : ${scmRef}${releaseAppendix} : ${archOsList}"
        echo "Triggering ${aqaJobName} : ${displayName}"

        def aqaJob = build(
            job: aqaJobName,
            parameters: [
                string(name: 'SDK_RESOURCE',          value: 'customized'),
                string(name: 'CUSTOMIZED_SDK_URL',    value: sdkUrl),
                string(name: 'ADOPTOPENJDK_BRANCH',   value: aqaBranch),
                string(name: 'JDK_VERSIONS',          value: jdkVersion),
                string(name: 'BUILD_TYPE',            value: buildType),
                string(name: 'VARIANT',               value: variant == 'temurin' ? 'hotspot' : variant),
                string(name: 'PLATFORMS',             value: archOsList),
                string(name: 'PIPELINE_DISPLAY_NAME', value: displayName),
            ],
            wait:         false,
            waitForStart: true
        )

        String link
        if (aqaJob?.absoluteUrl && aqaJob?.number) {
            link = "<a href='${aqaJob.absoluteUrl}'>${aqaJobName} #${aqaJob.number}</a>"
        } else {
            link = "<a href='${env.JENKINS_URL}job/${aqaJobName}/'>${aqaJobName} (no build number available)</a>"
        }
        currentBuild.description = (currentBuild.description ?: '') + "<br>${link}"

    } catch (Exception e) {
        echo "❌ Failed to trigger AQA tests: ${e.message}"
        currentBuild.result = 'FAILURE'
        return 1
    }

    echo "✅ AQA test pipeline triggered"
    return 0
}

return this
