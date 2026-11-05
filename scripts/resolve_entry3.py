#!/usr/bin/env python3
"""Decisive entry-point verification (R5900-aware)."""
import struct
import rabbitizer

ROOT = r"F:\Game Recomp Into a Native Android Port\Metal Gear Solid 3 Native OpenGLES3 Android Port Recompiled with a Launcher not embed\mgs3-recompiled-android"
GAME = ROOT + r"\_game"
loader = open(GAME + r"\SLES_820.42;1", "rb").read()
payload = open(GAME + r"\mgs3_main_payload.bin", "rb").read()

def dec(w, vram=0):
    ins = rabbitizer.Instruction(w, vram, rabbitizer.InstrCategory.R5900)
    if not ins.isValid():
        return f"<invalid 0x{w:08x}>"
    s = ins.disassemble()
    return s

print("=== 1. payload head decoded (EE/R5900) ===")
for off in range(0, 0x140, 4):
    w = struct.unpack_from("<I", payload, off)[0]
    print(f"  0x{0x100000+off:06x}: 0x{w:08x}  {dec(w, 0x100000+off)}")

print("\n=== 2. checksum recompute + payload[4] decrypt ===")
words = struct.unpack_from(f"<{(0x56b20-0x53af8)//4}I", loader, 0x53af8)
csum = sum(words) & 0xFFFFFFFF
print(f"  checksum = 0x{csum:08x}   (prior session claimed 0x259ff0b6)")
w4 = struct.unpack_from("<I", payload, 4)[0]
d4 = w4 ^ csum
print(f"  payload[4] 0x{w4:08x} ^ csum = 0x{d4:08x}  ->  {dec(d4, 0x100004)}")
if (d4 >> 26) in (4, 6, 7, 1):
    off16 = (d4 & 0xFFFF) - 0x10000 if (d4 & 0xFFFF) >= 0x8000 else (d4 & 0xFFFF)
    tgt = (0x100004 + 4 + off16 * 4) & 0xFFFFFFFF
    print(f"  branch target = 0x{tgt:08x}")

print("\n=== 3. MMI funct histogram in code region (0x138..0x10000) ===")
from collections import Counter
functs = Counter()
for off in range(0x138, 0x10000, 4):
    w = struct.unpack_from("<I", payload, off)[0]
    if (w >> 26) == 0x1C:
        functs[w & 0x3F] += 1
print("  ", dict(sorted(functs.items())))
