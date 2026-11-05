#!/usr/bin/env python3
"""Full loader tail disassembly + jalr scan + payload table extent."""
import struct
from capstone import Cs, CS_MODE_MIPS64, CS_ARCH_MIPS

ROOT = r"F:\Game Recomp Into a Native Android Port\Metal Gear Solid 3 Native OpenGLES3 Android Port Recompiled with a Launcher not embed\mgs3-recompiled-android"
GAME = ROOT + r"\_game"

loader = open(GAME + r"\SLES_820.42;1", "rb").read()
payload = open(GAME + r"\mgs3_main_payload.bin", "rb").read()

md = Cs(CS_ARCH_MIPS, CS_MODE_MIPS64)
def v2f(v): return v - 0x800000 + 0x1000
def f2v(f): return f + 0x800000 - 0x1000

# ---- 1. scan whole loader for jr/jalr (SPECIAL funct 8/9) ----
print("=== jr/jalr scan across loader ===")
n_words = len(loader) // 4
for i in range(n_words):
    w = struct.unpack_from("<I", loader, i * 4)[0]
    if (w & 0xFC00003F) in (0x00000008, 0x00000009):
        va = f2v(i * 4)
        if va >= 0x852000:  # only tail region of interest
            rs = (w >> 21) & 31
            rd = (w >> 11) & 31
            kind = "jr" if (w & 0x3F) == 8 else "jalr"
            print(f"  0x{va:08x}: {kind} r{rd}, r{rs}  (0x{w:08x})")

# ---- 2. full tail disasm to file ----
start_v = 0x852ab0
data = loader[v2f(start_v):]
lines = []
for ins in md.disasm(data, start_v):
    lines.append(f"0x{ins.address:08x}: {ins.bytes.hex():<12} {ins.mnemonic} {ins.op_str}")
out = ROOT + r"\_game\loader_tail_disasm.txt"
open(out, "w").write("\n".join(lines))
print(f"\ntail disasm: {len(lines)} instructions -> {out}")

# ---- 3. payload: where does the 0x7000xxxx table end? ----
print("\n=== payload words 0x80..0x300 ===")
for off in range(0x80, 0x300, 4):
    w = struct.unpack_from("<I", payload, off)[0]
    tag = ""
    if (w >> 16) == 0x7000: tag = "<-- 0x7000 table"
    if w == 0: tag = "zero"
    print(f"  +0x{off:03x} = 0x{w:08x}  {tag}")
