# Reproducible Build Comparison

## Overview

The reproducible build comparison stage validates that locally built JDK binaries are byte-for-byte identical to production Adoptium binaries. This ensures build reproducibility and helps identify any non-deterministic build issues.

## How It Works

1. **Clean Workspace**: Removes any existing comparison workspace to prevent pollution from previous runs
2. **Clone temurin-build**: Clones the temurin-build repository to access the comparison tools
3. **Download Production Binary**: Fetches the official Adoptium JDK binary from the Adoptium API using the specified SCM reference
4. **Download SBOM**: Retrieves the Software Bill of Materials (SBOM) for the production binary
5. **Unpack Both JDKs**: Extracts both the production binary and the locally built JDK
6. **Run Comparison**: Uses the `repro_compare.sh` tool from temurin-build to perform byte-by-byte comparison
7. **Report Results**: Outputs detailed comparison results showing any differences

## Usage

### Basic Usage

```bash
python3 ci/local/run-pipeline.py \
    --jdk-version jdk21u \
    --variant temurin \
    --target-os mac \
    --architecture aarch64 \
    --scm-ref jdk-21.0.2+13 \
    --release \
    --compare-build
```

### EA (Early Access) Builds

For EA builds, omit the `--release` flag:

```bash
python3 ci/local/run-pipeline.py \
    --jdk-version jdk21u \
    --variant temurin \
    --target-os linux \
    --architecture x64 \
    --scm-ref jdk-21.0.3+9 \
    --compare-build
```

The script automatically appends `-ea-beta` to the SCM reference when querying the Adoptium API for EA builds.

### Run Only Comparison Stage

If you already have a built JDK and want to run only the comparison:

```bash
python3 ci/local/run-pipeline.py \
    --jdk-version jdk21u \
    --variant temurin \
    --target-os mac \
    --architecture aarch64 \
    --scm-ref jdk-21.0.2+13 \
    --release \
    --start-from-stage reproducible-compare \
    --compare-build
```

## Requirements

### Mandatory Parameters

- `--scm-ref`: The exact SCM reference (e.g., `jdk-21.0.2+13`) used to build the JDK
  - This must match a production release available on the Adoptium API
  - For EA builds, do not include the `-ea-beta` suffix (it's added automatically)

- `--compare-build`: Enables the reproducible comparison stage

### Optional Parameters

- `--build-repo-url`: Custom temurin-build repository URL (default: `https://github.com/adoptium/temurin-build.git`)
- `--build-ref`: Custom temurin-build branch/tag (default: `master`)

## Environment Variables

The stage script uses the following environment variables:

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `WORKSPACE` | Pipeline workspace directory | Yes | - |
| `CONFIG_FILE` | Path to pipeline configuration JSON | Yes | - |
| `TARGET_DIR` | Shared artifact directory | Yes | - |
| `SCM_REF` | OpenJDK source reference | Yes | - |
| `RELEASE` | Whether this is a release build | Yes | `false` |
| `BUILD_REPO_URL` | temurin-build repository URL | No | `https://github.com/adoptium/temurin-build.git` |
| `BUILD_REF` | temurin-build branch/tag | No | `master` |

## Output

The comparison results are written to:
```
${WORKSPACE}/reproducible-compare/
├── temurin-build/          # Cloned temurin-build repository
├── jdk-upstream/           # Unpacked production JDK
├── jdk-built/              # Unpacked locally built JDK
├── upstream.tar.gz         # Downloaded production binary
├── upstream.json           # Downloaded SBOM
└── comparison-results.txt  # Detailed comparison output
```

**Note**: The comparison workspace is automatically cleaned before each run to ensure a fresh start and prevent pollution from previous comparisons.

## Adoptium API Integration

### API Endpoint Format

The stage constructs API URLs based on the build type:

**Release builds:**
```
https://api.adoptium.net/v3/binary/version/{scm_ref}/{os}/{arch}/jdk/hotspot/normal/eclipse?project=jdk
```

**EA builds:**
```
https://api.adoptium.net/v3/binary/version/{scm_ref}-ea-beta/{os}/{arch}/jdk/hotspot/normal/eclipse?project=jdk
```

### SCM Reference Handling

1. **Strip `_adopt` suffix**: If the SCM reference contains `_adopt` (e.g., `jdk-21.0.2+13_adopt`), it's removed before querying the API
2. **Add EA suffix**: For non-release builds, `-ea-beta` is appended to the SCM reference

### Platform Mapping

| Pipeline OS | API OS | Notes |
|-------------|--------|-------|
| `mac` | `mac` | macOS builds |
| `linux` | `linux` | Linux builds |
| `windows` | `windows` | Windows builds |
| `aix` | `aix` | AIX builds |

| Pipeline Arch | API Arch | Notes |
|---------------|----------|-------|
| `aarch64` | `aarch64` | ARM 64-bit |
| `x64` | `x64` | Intel/AMD 64-bit |
| `x32` | `x32` | 32-bit x86 |
| `ppc64` | `ppc64le` | PowerPC 64-bit LE |
| `s390x` | `s390x` | IBM Z Systems |

## Comparison Tool

The stage uses `repro_compare.sh` from the temurin-build repository, which:

- Compares file structures
- Performs byte-by-byte comparison of binaries
- Identifies differences in metadata, timestamps, and signatures
- Generates detailed reports of any discrepancies

## Troubleshooting

### Error: "Production binary not found"

**Cause**: The specified SCM reference doesn't exist in the Adoptium API

**Solution**:
- Verify the SCM reference is correct
- Check if it's a release or EA build and adjust the `--release` flag accordingly
- Visit https://api.adoptium.net/v3/info/available_releases to see available versions

### Error: "Local JDK tarball not found"

**Cause**: The build stage didn't complete successfully or the tarball is in an unexpected location

**Solution**:
- Ensure the build stage completed successfully
- Check that `${TARGET_DIR}` contains the expected JDK tarball
- Verify the tarball naming matches the expected pattern

### Error: "Comparison failed with differences"

**Cause**: The locally built JDK differs from the production binary

**Solution**:
- Review the comparison results in `${TARGET_DIR}/reproducible-compare/comparison-results.txt`
- Check for non-deterministic build issues (timestamps, random values, etc.)
- Verify build environment matches production (compiler versions, build flags, etc.)

## Integration with Jenkins

To add this stage to the Jenkins declarative pipeline:

```groovy
stage('Reproducible Compare') {
    when {
        expression { params.COMPARE_BUILD == true }
    }
    steps {
        script {
            sh """
                export TARGET_DIR="${WORKSPACE}/workspace/target"
                export SCM_REF="${params.SCM_REF}"
                export RELEASE="${params.RELEASE}"
                bash scripts/stages/20-reproducible-compare.sh
            """
        }
    }
}
```

Add the corresponding parameter:

```groovy
booleanParam(
    name: 'COMPARE_BUILD',
    defaultValue: false,
    description: 'Enable reproducible build comparison against production binaries'
)
```

## References

- [Adoptium API Documentation](https://api.adoptium.net/q/swagger-ui/)
- [temurin-build Repository](https://github.com/adoptium/temurin-build)
- [Reproducible Builds Project](https://reproducible-builds.org/)