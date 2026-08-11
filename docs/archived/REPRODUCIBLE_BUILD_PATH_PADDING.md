# Reproducible Build Path Padding

## Overview

This document describes the path padding feature implemented in the build stage to ensure reproducible builds across different workspace directory structures. This feature is critical for achieving byte-for-byte identical builds, particularly on macOS where filesystem path lengths affect UUID generation.

## Problem Statement

When building JDK binaries locally using `--compare-build`, the resulting binaries may differ from upstream Adoptium builds due to differences in workspace directory path lengths. This is particularly problematic on macOS where:

1. The Mach-O binary format includes an `LC_UUID` load command
2. The UUID is calculated based on the binary's content and metadata
3. Filesystem paths embedded during compilation affect the UUID calculation
4. Different path lengths result in different UUIDs, even if the code is identical

## Solution: Path Padding

The build stage now supports automatic path padding when `compareBuild` is enabled in the pipeline configuration. This ensures that the local workspace directory path length matches the upstream build's workspace directory path length.

### How It Works

1. **SBOM Download**: When `compareBuild: true`, the build stage downloads the SBOM (Software Bill of Materials) from the Adoptium API for the target version
2. **Path Extraction**: Extracts the `Build Workspace Directory` property from the SBOM
3. **Length Calculation**: Compares the upstream workspace path length with the local workspace path
4. **Padding Application**: If needed, creates a padded subdirectory to match the upstream path length
5. **Build Execution**: Runs the build in the padded workspace directory

### Path Padding Algorithm

The padding algorithm follows this logic:

```bash
# Target path from SBOM: /home/jenkins/workspace/build-scripts/jobs/jdk21u/jdk21u-linux-x64-temurin
# Local workspace: /Users/anleonar/workspace/ci-adoptium-pipelines
# Build folder: workspace/build/src

# Calculate full local path
local_full_path = /Users/anleonar/workspace/ci-adoptium-pipelines/workspace/build/src

# Calculate padding needed
padding_length = len(target_path) - len(local_full_path)

# If padding needed, create subdirectory with 'P' characters
if padding_length > 1:
    padding = "P" * (padding_length - 1)
    padded_workspace = /Users/anleonar/workspace/ci-adoptium-pipelines/{padding}
```

### Example

**Upstream Build:**
- Workspace: `/home/jenkins/workspace/build-scripts/jobs/jdk21u/jdk21u-linux-x64-temurin`
- Full build path: `/home/jenkins/workspace/build-scripts/jobs/jdk21u/jdk21u-linux-x64-temurin/workspace/build/src`
- Path length: 95 characters

**Local Build (without padding):**
- Workspace: `/Users/anleonar/workspace/ci-adoptium-pipelines`
- Full build path: `/Users/anleonar/workspace/ci-adoptium-pipelines/workspace/build/src`
- Path length: 72 characters
- **Difference: 23 characters shorter**

**Local Build (with padding):**
- Workspace: `/Users/anleonar/workspace/ci-adoptium-pipelines/PPPPPPPPPPPPPPPPPPPPPP`
- Full build path: `/Users/anleonar/workspace/ci-adoptium-pipelines/PPPPPPPPPPPPPPPPPPPPPP/workspace/build/src`
- Path length: 95 characters
- **Difference: 0 characters (matches upstream!)**

## Configuration

### Enabling Path Padding

Add the `compareBuild` parameter to your pipeline configuration:

```json
{
  "buildConfig": {
    "JAVA_TO_BUILD": "jdk21u",
    "TARGET_OS": "mac",
    "ARCHITECTURE": "aarch64",
    "VARIANT": "temurin"
  },
  "parameters": {
    "compareBuild": true,
    "release": false
  },
  "refs": {
    "scmRef": "jdk-21.0.2+13"
  }
}
```

### Required Configuration Values

For path padding to work, the following must be configured:

1. **`compareBuild`**: Set to `true` to enable path padding
2. **`scmRef`**: The git tag/ref for the build (e.g., `jdk-21.0.2+13`)
3. **`release`**: Boolean indicating if this is a release build (affects API URL construction)
4. **`TARGET_OS`**: Operating system (mac, linux, windows, aix)
5. **`ARCHITECTURE`**: CPU architecture (aarch64, x64, ppc64le, s390x, etc.)

## Implementation Details

### Code Location

The path padding implementation is in [`scripts/stages/02-build.sh`](../scripts/stages/02-build.sh):

- **`resolve_path()`** (lines 197-221): Resolves canonical paths by handling `.` and `..` components
- **`pad_build_dir_to_same_length()`** (lines 223-247): Calculates and creates padded directory
- **`setup_reproducible_build_padding()`** (lines 249-346): Main function that orchestrates the padding process

### Execution Flow

```
main()
  ├─ Load configuration
  ├─ Extract compareBuild parameter
  ├─ setup_temurin_build()
  ├─ IF compareBuild == true:
  │   └─ setup_reproducible_build_padding()
  │       ├─ Construct SBOM API URL
  │       ├─ Download SBOM
  │       ├─ Extract BUILD_WORKSPACE_DIRECTORY
  │       ├─ Calculate padding needed
  │       ├─ Create padded directory
  │       └─ Update WORKSPACE environment variable
  ├─ prepare_workspace()
  ├─ execute_build()
  └─ organize_build_outputs()
```

### SBOM API URL Construction

The SBOM is fetched from the Adoptium API using this URL pattern:

```
https://api.adoptium.net/v3/binary/version/{version}/{os}/{arch}/sbom/hotspot/normal/eclipse?project=jdk
```

Where:
- **`{version}`**: SCM ref with optional `-ea-beta` suffix for EA builds
- **`{os}`**: Operating system (mac, linux, windows, aix)
- **`{arch}`**: Architecture (aarch64, x64, ppc64le, s390x, etc.)

Example:
```
https://api.adoptium.net/v3/binary/version/jdk-21.0.2+13/mac/aarch64/sbom/hotspot/normal/eclipse?project=jdk
```

### SBOM Structure

The SBOM contains the `Build Workspace Directory` property:

```json
{
  "components": [
    {
      "properties": [
        {
          "name": "Build Workspace Directory",
          "value": "/home/jenkins/workspace/build-scripts/jobs/jdk21u/jdk21u-linux-x64-temurin"
        }
      ]
    }
  ]
}
```

## Cross-Platform Support

The path padding logic works across all platforms:

- **macOS**: Ensures LC_UUID matches by maintaining consistent path lengths
- **Linux**: Helps with reproducibility of debug symbols and embedded paths
- **Windows**: Supports path padding for Windows builds
- **AIX**: Compatible with AIX filesystem structures

## Error Handling

The implementation includes robust error handling:

1. **SBOM Download Failure**: Logs warning and continues without padding
2. **Missing BUILD_WORKSPACE_DIRECTORY**: Logs warning and skips padding
3. **Insufficient Padding Space**: Logs warning if padding cannot be applied
4. **API Errors**: Gracefully handles API unavailability

## Logging

The path padding process provides detailed logging:

```
[INFO] Setting up reproducible build path padding
[INFO] SCM_REF for API: jdk-21.0.2+13
[INFO] Fetching SBOM from: https://api.adoptium.net/v3/binary/version/...
[INFO] SBOM downloaded successfully
[INFO] Found BUILD_WORKSPACE_DIRECTORY in SBOM: /home/jenkins/workspace/...
[INFO] Padded /Users/anleonar/workspace/ci-adoptium-pipelines with sub-folder to /Users/anleonar/workspace/ci-adoptium-pipelines/PPPPPPPPPPPPPPPPPPPPPP
[INFO] Applying workspace padding for reproducible build
[INFO] Original WORKSPACE: /Users/anleonar/workspace/ci-adoptium-pipelines
[INFO] Padded WORKSPACE: /Users/anleonar/workspace/ci-adoptium-pipelines/PPPPPPPPPPPPPPPPPPPPPP
[INFO] WORKSPACE updated to: /Users/anleonar/workspace/ci-adoptium-pipelines/PPPPPPPPPPPPPPPPPPPPPP
[INFO] Reproducible build path padding setup complete
```

## Testing

### Local Testing

To test path padding locally:

1. Create a pipeline configuration with `compareBuild: true`:
   ```bash
   cat > pipeline-config.json <<EOF
   {
     "buildConfig": {
       "JAVA_TO_BUILD": "jdk21u",
       "TARGET_OS": "mac",
       "ARCHITECTURE": "aarch64",
       "VARIANT": "temurin"
     },
     "parameters": {
       "compareBuild": true,
       "release": false
     },
     "refs": {
       "scmRef": "jdk-21.0.2+13",
       "buildRef": "master"
     }
   }
   EOF
   ```

2. Run the build stage:
   ```bash
   export WORKSPACE=$(pwd)
   export CONFIG_FILE=pipeline-config.json
   export TARGET_DIR=$(pwd)/target
   export BUILD_NUMBER=local

   ./scripts/stages/02-build.sh
   ```

3. Verify padding in logs:
   ```bash
   grep "Padded" build.log
   grep "WORKSPACE updated" build.log
   ```

### Verification

After building with path padding:

1. **Check workspace structure**:
   ```bash
   ls -la ${WORKSPACE}/
   # Should show padded directory with 'P' characters
   ```

2. **Verify build artifacts**:
   ```bash
   ls -la ${TARGET_DIR}/
   # Should contain JDK artifacts
   ```

3. **Compare with upstream** (macOS):
   ```bash
   # Extract LC_UUID from local build
   otool -l ${TARGET_DIR}/jdk-*/Contents/Home/lib/server/libjvm.dylib | grep uuid

   # Extract LC_UUID from upstream build
   otool -l upstream-jdk/jdk-*/Contents/Home/lib/server/libjvm.dylib | grep uuid

   # UUIDs should match
   ```

## Limitations

1. **Minimum Padding**: Cannot pad if the difference is less than 2 characters
2. **Longer Local Paths**: Cannot pad if local path is longer than upstream path
3. **SBOM Availability**: Requires SBOM to be available in Adoptium API
4. **Network Dependency**: Requires network access to download SBOM

## Related Documentation

- [Reproducible Build Comparison](./REPRODUCIBLE_BUILD_COMPARISON.md) - Stage 20 comparison process
- [Build Stage](./BUILD_STAGE.md) - Complete build stage documentation
- [Pipeline Configuration](./PIPELINE_CONFIGURATION.md) - Configuration reference

## References

- [Adoptium API Documentation](https://api.adoptium.net/q/swagger-ui/)
- [SBOM Specification](https://cyclonedx.org/)
- [Mach-O File Format](https://developer.apple.com/documentation/kernel/mach-o_file_format)
- [Reproducible Builds](https://reproducible-builds.org/)

## Changelog

### 2026-06-17
- Initial implementation of path padding feature
- Added `compareBuild` parameter support
- Integrated SBOM download and parsing
- Implemented cross-platform path padding algorithm