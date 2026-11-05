# Metal Gear Solid 3 — Native Android Port (Static Recompilation)

A native Android port of **Metal Gear Solid 3: Subsistence** (PS2, PAL `SLES-820.42`,
Disc 1) built with [ran-j/PS2Recomp](https://github.com/ran-j/PS2Recomp) static
recompilation and a Kotlin launcher app.

> **No game data is included in this repository.** No ISO, no BIOS, no boot
> executables, no recompiled game code. You must supply a dump of your own
> legally obtained disc. The launcher imports it at runtime.

---

## How it works

1. **Static recompilation** — the game's EE (MIPS R5900) code is recompiled
   once, on a PC, into native C functions by `ps2_analyzer` + `ps2_recomp`.
2. **Runtime** — the [PS2Recomp](https://github.com/ran-j/PS2Recomp) runtime
   (raylib GLES renderer, EE scheduler, IOP host, GS emulation) executes the
   recompiled code natively on the device.
3. **Launcher (Kotlin)** — the Android app contains **zero game data**:
   - You pick your disc image (SAF file picker).
   - It is copied into the app's private storage and used **in place** for
     real-LBN sector streaming (`sceCdRead` reads straight from the ISO).
   - The launcher extracts the packed boot executable (`SYSTEM.CNF` →
     `BOOT2` → `SLES_820.42;1`), inflates the zlib stream embedded at offset
     `0x1004` to recover the real EE payload (1,084,340 bytes), and wraps it
     in a minimal ELF32 image (`MGS3_analysis.elf`, load address `0x100000`,
     entry `0x100024`).
   - Booting the *unpacked* payload directly bypasses the disc loader stub
     completely — the payload self-initialises (zeroes all GPRs/FPRs), so no
     loader register state is needed.
4. **Touch controls** — when no physical gamepad is connected, a translucent
   DualShock-style overlay is drawn on screen: left stick (bottom-left),
   right stick / camera (bottom-middle-right), D-pad, face buttons, L1/R1,
   L2/R2, START/SELECT. Multi-touch supported.

## Repository layout

```
android/            Kotlin launcher app (this is what you build & install)
patches/            Runtime modifications applied on top of PS2Recomp
scripts/            Host-side pipeline scripts (Python)
third_party/PS2Recomp  Pinned toolchain submodule (ran-j/PS2Recomp @ e563698)
docs/BUILDING.md    Full build instructions
```

The runtime patches (see `patches/ps2recomp-mgs3-android.patch`) add:

- `ps2xRuntime/src/main.cpp` — Android boot-path resolution via
  `/proc/self/cmdline` → app-storage `game/MGS3_analysis.elf`
- `ps2xRuntime/src/lib/ps2_runtime.cpp` — picks up `disc.iso` next to the
  boot ELF as the CD image for real-LBN sector reads; frame-loop hook that
  draws the touch overlay
- `ps2xRuntime/src/lib/ps2_pad.cpp` — full touch → DualShock overlay
  (input + on-screen rendering)

## Build (summary)

See [docs/BUILDING.md](docs/BUILDING.md) for the complete pipeline.

```bash
# 1. Host tools (once, on a PC)
cmake -S third_party/PS2Recomp -B build-host -G Ninja \
      -DPS2X_BUILD_RUNTIME=OFF -DPS2X_BUILD_TEST=OFF -DPS2X_BUILD_STUDIO=OFF
cmake --build build-host

# 2. Analyse + recompile from YOUR disc's boot executable
python scripts/extract_iso.py "<your disc.iso>" _extract_out
python scripts/make_analysis_elf.py          # wraps the unpacked payload
build-host/ps2xAnalyzer/ps2_analyzer  _game/MGS3_analysis.elf mgs3.toml
build-host/ps2xRecomp/ps2_recomp      mgs3.toml

# 3. Integrate generated code + patches (see docs/BUILDING.md)

# 4. Android app
cd android && ./gradlew assembleRelease
```

## Controls (touch)

| Zone | Action |
|---|---|
| Bottom-left circle | Left stick (movement / Snake camouflage) |
| Bottom-middle-right circle | Right stick (camera / slash) |
| Top-left cluster | D-pad (items / radio) |
| Bottom-right cluster | △ □ ✕ ○ |
| Top corners | L1 / R1 (weapons / items), L2 / R2 below |
| Bottom centre | START / SELECT |

A physical gamepad (Bluetooth/USB) is used automatically when connected and
the overlay hides itself.

## Legal

This repository contains only toolchain glue, build scripts and a launcher —
none of which contain copyrighted game content. You must own the game and
provide your own disc image. Metal Gear Solid 3 is a trademark of Konami;
this project is not affiliated with or endorsed by Konami.

## License

Build scripts and launcher: GPL-3.0 (to match the upstream toolchain).
PS2Recomp itself is GPL-3.0 — see `third_party/PS2Recomp/LICENSE`.
