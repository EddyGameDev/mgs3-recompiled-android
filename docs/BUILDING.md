# Building the MGS3 Native Android Port

Complete pipeline: host tools → analysis → recompilation → integration →
Android APK. **No step of this pipeline commits game data anywhere.**

## Prerequisites

- **Host tools build**: CMake ≥ 3.21, Ninja, a C++20 compiler (LLVM-MinGW /
  MSVC / clang / gcc all work).
- **Android**: JDK 17+, Android SDK with platform 35, CMake 3.22.1, NDK
  28.2.13676358, Gradle 8.10+ (AGP 8.7.x). Gradle downloads AGP/Kotlin and
  FetchContent dependencies (raylib, etc.) on first run.
- **Python 3** for the helper scripts.
- Your own dump of **Metal Gear Solid 3: Subsistence (Europe) Disc 1**
  (Redump-verified ISO recommended).

## 1. Host recompilation tools

```bash
git submodule update --init --recursive
cmake -S third_party/PS2Recomp -B build-host -G Ninja \
      -DCMAKE_BUILD_TYPE=Release \
      -DPS2X_BUILD_RUNTIME=OFF -DPS2X_BUILD_TEST=OFF \
      -DPS2X_BUILD_STUDIO=OFF
cmake --build build-host
```

Produces `build-host/ps2xAnalyzer/ps2_analyzer` and
`build-host/ps2xRecomp/ps2_recomp`.

## 2. Extract your disc

```bash
python scripts/extract_iso.py "/path/to/MGS3 Subsistence Disc 1.iso" _extract_out
```

This writes `SYSTEM.CNF`, the packed boot executable (`SLES_820.42;1`) and a
disc listing into `_extract_out/`. Keep all of it out of version control.

## 3. Build the analysis ELF

The retail boot executable is a packed loader (zlib payload + MIPS loader
stub). The recompiler targets the *unpacked* EE payload, and booting that
payload directly on device bypasses the loader entirely (it self-initialises
all registers):

```bash
cp _extract_out/SLES_820.42';'1 _game/SLES_820.42';'1
python scripts/make_analysis_elf.py
```

`scripts/make_analysis_elf.py` inflates the zlib stream at file offset
`0x1004` (→ 1,084,340 bytes), verifies the size, and writes
`_game/MGS3_analysis.elf` (single RWX PT_LOAD at `0x100000`, entry
`0x100024`, `e_flags` mirrored from the boot ELF).

## 4. Analyse + recompile

```bash
build-host/ps2xAnalyzer/ps2_analyzer _game/MGS3_analysis.elf mgs3.toml
```

Tune `mgs3.toml` (this repo's run used `low_memory_mode = true`,
`output_worker_threads = 8`), then:

```bash
build-host/ps2xRecomp/ps2_recomp mgs3.toml
```

Output (~1,950 files, ~66 MB) lands in the configured `output` directory:
`sub_*.cpp` / `entry_*.cpp` function bodies, `ps2_recompiled_functions.h`,
`ps2_recompiled_stubs.h`, and the dense `register_functions.cpp` table
(base `0x100024`, end `0x208bb4`, 271,076 slots).

> Trailing `unhandled-instruction` errors at the very end of the image
> (`sub_002073C0`) are ASCII string data misread as a function — harmless.

## 5. Integrate into the runtime

```bash
cp output/ps2_recompiled_functions.h output/ps2_recompiled_stubs.h \
   third_party/PS2Recomp/ps2xRuntime/include/
cp output/*.cpp third_party/PS2Recomp/ps2xRuntime/src/runner/
```

This replaces the stock placeholder `register_functions.cpp`. The runner
target globs `src/runner/*.cpp`, and the PCH automatically picks up the two
generated headers from `include/`.

Apply the runtime patches (Android boot path, CD image pickup, touch
overlay):

```bash
git -C third_party/PS2Recomp apply ../../patches/ps2recomp-mgs3-android.patch
```

## 6. Build the APK

```bash
cd android
# local.properties: sdk.dir=/path/to/android-sdk
./gradlew assembleRelease
```

Notes:

- `-DPS2X_ENABLE_RUNNER_UNITY_BUILD=OFF` is mandatory — the generated code
  contains multi-megabyte translation units that OOM under a unity build.
- `arm64-v8a` only by default; add `x86_64` to `abiFilters` for emulators.
- First build compiles ~1,960 translation units — expect a long build.

`app/build/outputs/apk/release/app-release.apk` (debug-signed) is the
installable artifact.

## 7. On device

1. Install the APK, launch **MGS3 Recompiled**.
2. Tap **Select game disc image**, choose your ISO (SAF picker).
3. Wait for the copy + extraction + inflation pipeline (progress shown).
4. Tap **Play**.

The disc image lives in the app's external-files dir as `game/disc.iso` and
is streamed in place for `sceCdRead`; saves go to `game/mc0/`.

## Troubleshooting

- **Windows: `ninja: error: manifest 'build.ninja' still dirty after 100
  tries` during CMake configure** (or `CMAKE_OBJECT_PATH_MAX` warnings) —
  your checkout path is too long. Map a short drive letter and build from
  there:

  ```bat
  subst X: "C:\long\path\to\mgs3-recompiled-android"
  cd /d X:\android
  gradlew assembleRelease
  ```

  Every path then stays well under the ~200 characters where ninja's
  manifest stat/mtime handling becomes flaky. Remove later with
  `subst X: /D`.

  Additionally pass a FetchContent base directory **outside the repository**
  (git-for-windows sees through subst drives and dies with
  `fatal: '$GIT_DIR' too big` when cloning dependencies from inside a repo
  whose real path is long):

  ```gradle
  // android/app/build.gradle, cmake arguments:
  '-DFETCHCONTENT_BASE_DIR=C:/fcdeps/mgs3',
  ```

- **Game breaks after boot** — the analyzer emitted 30 speculative
  self-modifying-code patches (`[patches].instructions` in the TOML). Try
  disabling that section and re-running the recompiler.
- **`sceCdRead` unresolved** — the runtime falls back through several
  register layouts; check logcat for `[sceCdRead]` traces. Files resolved via
  `sceCdSearchFile` use pseudo-LBNs starting at sector `0x00100000`; if a
  real LBN in the upper DVD half collides, raise
  `kCdPseudoLbnStart` in `Support.h`.
- **OOM during build** — keep unity build OFF, raise Gradle's
  `-Xmx`, and build one ABI at a time.
