# Jenkins Node Label Schema

This document is the canonical reference for the Jenkins node-label schema used by
this CI project.  The schema is aligned with the
[aqa-tests label schema](https://github.com/adoptium/aqa-tests/blob/master/docs/pages/LabelSchema.md)
so that build and test agents can share a single, consistent labelling convention.

---

## Overview

Labels are organised under three top-level namespace roots:

| Root  | Meaning                    | Examples                              |
|-------|----------------------------|---------------------------------------|
| `hw`  | Hardware attributes        | `hw.arch.x86`, `hw.bits.64`           |
| `sw`  | Software / OS attributes   | `sw.os.linux`, `sw.tool.docker`       |
| `ci`  | CI role / sponsor metadata | `ci.role.build`, `ci.role.test`       |

Labels within each root follow a dotted hierarchy, e.g.  
`sw.os.windows.2022` means *software → operating system → Windows → version 2022*.

---

## `ci.role` — Agent Role

Specifies the primary function of an agent in the CI pipeline.

| Label              | Usage                                     |
|--------------------|-------------------------------------------|
| `ci.role.build`    | Agent used for compilation / build stages |
| `ci.role.test`     | Agent used for test stages (aqa-tests)    |
| `ci.role.sign`     | Agent used for code-signing               |
| `ci.role.publish`  | Agent used for artifact publishing        |
| `ci.role.worker`   | Generic utility / orchestration agent     |

> **Migration note:** the legacy bare label `build` is replaced by `ci.role.build`,
> and `worker` is replaced by `ci.role.worker`.

---

## `sw.os` — Operating System

Specifies the operating system running on the agent.

| Label                  | Operating System                      |
|------------------------|---------------------------------------|
| `sw.os.linux`          | Any Linux distribution                |
| `sw.os.alpine-linux`   | Alpine Linux (musl libc)              |
| `sw.os.mac`            | macOS (any version)                   |
| `sw.os.windows`        | Windows (any version)                 |
| `sw.os.aix`            | IBM AIX                               |
| `sw.os.solaris`        | Oracle Solaris                        |
| `sw.os.zos`            | IBM z/OS                              |

Version-qualified variants — the version component follows the same convention:
dots within a version number become underscores, dots remain as namespace
separators only.

| Label                    | Version                   |
|--------------------------|---------------------------|
| `sw.os.mac.10_14`        | macOS 10.14 Mojave        |
| `sw.os.mac.11`           | macOS 11 (Big Sur)        |
| `sw.os.mac.12`           | macOS 12 (Monterey)       |
| `sw.os.mac.14`           | macOS 14 (Sonoma)         |
| `sw.os.windows.2012`     | Windows Server 2012       |
| `sw.os.windows.2019`     | Windows Server 2019       |
| `sw.os.windows.2022`     | Windows Server 2022       |
| `sw.os.aix.7_1`          | AIX 7.1                   |
| `sw.os.aix.7_2`          | AIX 7.2                   |
| `sw.os.aix.7_3`          | AIX 7.3                   |

> **Important:** the `os` and `arch` fields *inside* `jdkNN_pipeline_config.json`
> retain their existing temurin-build values (e.g. `"os": "mac"`, `"arch": "x64"`).
> The label schema values are used *only* for Jenkins agent selection (node labels and
> `stageAgentLabels` templates in `jenkins_job_config.json`).

---

## `hw.arch` — CPU Architecture

Specifies the hardware architecture of the agent.

| Label              | Architecture                         |
|--------------------|--------------------------------------|
| `hw.arch.x86`      | x86 family (32-bit and 64-bit/amd64) |
| `hw.arch.aarch64`  | ARM 64-bit (AArch64)                 |
| `hw.arch.aarch32`  | ARM 32-bit (AArch32 / armv7)         |
| `hw.arch.ppc64`    | IBM POWER 64-bit big-endian          |
| `hw.arch.ppc64le`  | IBM POWER 64-bit little-endian       |
| `hw.arch.s390x`    | IBM Z (s390x) 64-bit                 |
| `hw.arch.riscv`    | RISC-V (any bitness)                 |
| `hw.arch.sparcv9`  | SPARC v9 64-bit                      |

> **Migration note:** the legacy arch token in `stageAgentLabels` was the raw
> temurin-build `arch` value (e.g. `x64`).  It must be replaced with the
> appropriate `hw.arch.*` label (see mapping table below).  Note that both `x64`
> (64-bit) and `x86-32` (32-bit) map to `hw.arch.x86` — the aqa-tests schema
> uses `hw.arch.x86` for the whole x86 family.

---

## `sw.tool` — Software Tools

Identifies specific tools or compiler toolchains installed on the agent.

**Version convention:** dots (`.`) are used exclusively as namespace
separators between label segments.  Version numbers that contain dots in their
legacy form have those dots replaced with underscores (`_`) in the schema
label, e.g. `sw.tool.xcode.15_0_1`.  Non-digit prefix characters between a
tool name and its version number (e.g. the `v` in `armv8.2`) are stripped.

### Compilers / IDEs

| Label                     | Tool                                     |
|---------------------------|------------------------------------------|
| `sw.tool.xcode.11_7`      | Xcode 11.7                               |
| `sw.tool.xcode.15_0_1`    | Xcode 15.0.1                             |
| `sw.tool.vs.2017`         | Visual Studio 2017 / MSVC 2017           |
| `sw.tool.vs.2019`         | Visual Studio 2019 / MSVC 2019           |
| `sw.tool.vs.2022`         | Visual Studio 2022 / MSVC 2022           |
| `sw.tool.xlc.13`          | IBM XL C/C++ 13                          |
| `sw.tool.xlc.16`          | IBM XL C/C++ 16                          |
| `sw.tool.openxl.17`       | IBM Open XL C/C++ 17                     |

### Container Runtimes

| Label                  | Tool                                     |
|------------------------|------------------------------------------|
| `sw.tool.docker`       | Docker container runtime                 |
| `sw.tool.podman`       | Podman container runtime                 |

### Other

| Label                  | Tool                                     |
|------------------------|------------------------------------------|
| `sw.tool.arm.8_2`      | ARMv8.2 instruction set support          |

---

## Platform-to-Label Mapping

This table maps each `buildConfigurations` platform key used in
`jdkNN_pipeline_config.json` to the corresponding aqa-tests `PLATFORM_MAP` key
and the agent label expression used for Jenkins node selection.

| Config key (old camelCase) | New aqa-aligned key      | `sw.os.*` label        | `hw.arch.*` label    |
|----------------------------|--------------------------|------------------------|----------------------|
| `x64Linux`                 | `x86-64_linux`           | `sw.os.linux`          | `hw.arch.x86`        |
| `x64Mac`                   | `x86-64_mac`             | `sw.os.mac`            | `hw.arch.x86`        |
| `x64Windows`               | `x86-64_windows`         | `sw.os.windows`        | `hw.arch.x86`        |
| `x64AlpineLinux`           | `x86-64_alpine-linux`    | `sw.os.alpine-linux`   | `hw.arch.x86`        |
| `x32Windows`               | `x86-32_windows`         | `sw.os.windows`        | `hw.arch.x86`        |
| `aarch64Linux`             | `aarch64_linux`          | `sw.os.linux`          | `hw.arch.aarch64`    |
| `aarch64Mac`               | `aarch64_mac`            | `sw.os.mac`            | `hw.arch.aarch64`    |
| `aarch64Windows`           | `aarch64_windows`        | `sw.os.windows`        | `hw.arch.aarch64`    |
| `aarch64AlpineLinux`       | `aarch64_alpine-linux`   | `sw.os.alpine-linux`   | `hw.arch.aarch64`    |
| `arm32Linux`               | `arm_linux`              | `sw.os.linux`          | `hw.arch.aarch32`    |
| `ppc64Aix`                 | `ppc64_aix`              | `sw.os.aix`            | `hw.arch.ppc64`      |
| `ppc64leLinux`             | `ppc64le_linux`          | `sw.os.linux`          | `hw.arch.ppc64le`    |
| `s390xLinux`               | `s390x_linux`            | `sw.os.linux`          | `hw.arch.s390x`      |
| `riscv64Linux`             | `riscv64_linux`          | `sw.os.linux`          | `hw.arch.riscv`      |
| `sparcv9Solaris`           | `sparcv9_solaris`        | `sw.os.solaris`        | `hw.arch.sparcv9`    |
| `x64Solaris`               | `x86-64_solaris`         | `sw.os.solaris`        | `hw.arch.x86`        |

> The `os` and `arch` field values inside each platform entry **do not change** —
> they remain the temurin-build values (`mac`, `linux`, `x64`, `aarch64`, etc.).
> Only the map *key* is renamed to the aqa-aligned format.

---

## `additionalNodeLabels` Migration

The `additionalNodeLabels` field in `jdkNN_pipeline_config.json` carries
extra label constraints ANDed onto the base agent selector.  Legacy bare tokens
must be migrated to the schema.  The migration tool (`migrate-groovy-pipeline-configs.py`)
applies these transformations automatically using pattern-based rules, so any
version number is handled generically — not just the specific examples listed here.

### Migration rules (applied in order, first match wins)

The migration tool uses **pattern-based** rules so any version number is handled
generically.  The `_v()` helper replaces dots within a version string with
underscores before embedding it in the label.

| Pattern                             | Produces                             | Example input → output                            |
|-------------------------------------|--------------------------------------|---------------------------------------------------|
| `^build$`                           | `ci.role.build`                      | `build` → `ci.role.build`                         |
| `^worker$`                          | `ci.role.worker`                     | `worker` → `ci.role.worker`                       |
| `^test$`                            | `ci.role.test`                       | `test` → `ci.role.test`                           |
| `^xcode[^\d]*<ver>$`                | `sw.tool.xcode._v(ver)`              | `xcode15.0.1` → `sw.tool.xcode.15_0_1`            |
| `^vs<4-digit-year>$`                | `sw.tool.vs.<year>`                  | `vs2022` → `sw.tool.vs.2022`                      |
| `^xlc<ver>$`                        | `sw.tool.xlc._v(ver)`                | `xlc16` → `sw.tool.xlc.16`                        |
| `^openxl<ver>$`                     | `sw.tool.openxl._v(ver)`             | `openxl17` → `sw.tool.openxl.17`                  |
| `^arm[^\d]*<ver>$`                  | `sw.tool.arm._v(ver)`                | `armv8.2` → `sw.tool.arm.8_2`                     |
| `^x86-(32\|64)$`                    | `hw.arch.x86`                        | `x86-32` → `hw.arch.x86`                          |
| `^win<4-digit-year>$`               | `sw.os.windows.<year>`               | `win2022` → `sw.os.windows.2022`                  |
| `^macos<ver>$`                      | `sw.os.mac._v(ver)`                  | `macos10.14` → `sw.os.mac.10_14`                  |
| `^aix<3-digit-stream>$`             | `sw.os.aix.<maj>_<min>`              | `aix720` → `sw.os.aix.7_2`                        |
| `^(centos\|rhel\|ubuntu\|…)<ver>$`  | `sw.os.<distro>._v(ver)`             | `centos7` → `sw.os.centos.7`                      |
| starts with `hw.`, `sw.`, or `ci.`  | passed through unchanged             | `sw.tool.docker` → `sw.tool.docker`               |
| no rule matched                     | passed through unchanged             | `build-macstadium-macos1010-1` → (unchanged)      |

### Legacy token reference table

| Legacy token   | New schema label              | Meaning                              |
|----------------|-------------------------------|--------------------------------------|
| `xcode11.7`    | `sw.tool.xcode.11_7`          | Xcode 11.7                           |
| `xcode15.0.1`  | `sw.tool.xcode.15_0_1`        | Xcode 15.0.1                         |
| `vs2017`       | `sw.tool.vs.2017`             | Visual Studio 2017                   |
| `vs2019`       | `sw.tool.vs.2019`             | Visual Studio 2019                   |
| `vs2022`       | `sw.tool.vs.2022`             | Visual Studio 2022                   |
| `win2012`      | `sw.os.windows.2012`          | Windows Server 2012 host             |
| `win2022`      | `sw.os.windows.2022`          | Windows Server 2022 host             |
| `macos10.14`   | `sw.os.mac.10_14`             | macOS 10.14 Mojave host              |
| `macos11`      | `sw.os.mac.11`                | macOS 11 Big Sur host                |
| `aix710`       | `sw.os.aix.7_1`               | AIX 7.1 host                         |
| `aix715`       | `sw.os.aix.7_1`               | AIX 7.1 (7.1.5) host                 |
| `aix720`       | `sw.os.aix.7_2`               | AIX 7.2 host                         |
| `xlc13`        | `sw.tool.xlc.13`              | IBM XL C/C++ 13                      |
| `xlc16`        | `sw.tool.xlc.16`              | IBM XL C/C++ 16                      |
| `openxl17`     | `sw.tool.openxl.17`           | IBM Open XL C/C++ 17                 |
| `centos7`      | `sw.os.centos.7`              | CentOS 7 host (bare-metal builds)    |
| `armv8.2`      | `sw.tool.arm.8_2`             | ARMv8.2 instruction set support      |
| `build`        | `ci.role.build`               | Build-role agent                     |
| `worker`       | `ci.role.worker`              | Worker / orchestration agent         |

---

## `stageAgentLabels` Templates

The `stageAgentLabels` map in `jenkins_job_config.json` controls which Jenkins
agent each pipeline stage runs on.  Templates use `sw.os.{os}` and
`hw.arch.{arch}` — the `{os}` and `{arch}` placeholders are substituted with
the **suffix only** (the part after the final `.`), derived from the platform
entry's `os` and `arch` fields.  The `sw.os.` and `hw.arch.` prefixes are
written literally in the template.

### os → `{os}` suffix mapping

| `os` value in config | `{os}` substituted with |
|----------------------|-------------------------|
| `linux`              | `linux`                 |
| `alpine-linux`       | `alpine-linux`          |
| `mac`                | `mac`                   |
| `windows`            | `windows`               |
| `aix`                | `aix`                   |
| `solaris`            | `solaris`               |
| `zos`                | `zos`                   |

### arch → `{arch}` suffix mapping

| `arch` value in config | `{arch}` substituted with |
|------------------------|---------------------------|
| `x64`                  | `x86`                     |
| `x86-32`               | `x86`                     |
| `aarch64`              | `aarch64`                 |
| `arm`                  | `aarch32`                 |
| `ppc64`                | `ppc64`                   |
| `ppc64le`              | `ppc64le`                 |
| `s390x`                | `s390x`                   |
| `riscv64`              | `riscv`                   |
| `sparcv9`              | `sparcv9`                 |

### Example resolved labels

For a build with `"os": "mac"`, `"arch": "aarch64"`:

| Stage          | Template                                    | Resolved                                          |
|----------------|---------------------------------------------|---------------------------------------------------|
| Build          | `ci.role.build&&sw.os.{os}&&hw.arch.{arch}` | `ci.role.build&&sw.os.mac&&hw.arch.aarch64`       |
| Smoke Tests    | `ci.role.build&&sw.os.{os}&&hw.arch.{arch}` | `ci.role.build&&sw.os.mac&&hw.arch.aarch64`       |
| AQA Tests      | `ci.role.test&&hw.arch.{arch}`              | `ci.role.test&&hw.arch.aarch64`                   |
| Initialize     | `ci.role.worker`                            | `ci.role.worker`                                  |

---

## References

- [aqa-tests Label Schema](https://github.com/adoptium/aqa-tests/blob/master/docs/pages/LabelSchema.md)
- [aqa-tests PLATFORM_MAP](https://github.com/adoptium/aqa-tests/blob/master/buildenv/jenkins/openjdk_tests)
- [`CONFIG_SCHEMA.md`](./CONFIG_SCHEMA.md) — full config file schema reference
