#!/usr/bin/env python3
"""Resolve the MGS3 game entry point with hard data. v2 (fixed offsets)."""
import struct, zlib
from capstone import Cs, CS_MODE_MIPS64, CS_ARCH_MIPS

ROOT = r"F:\Game Recomp Into a Native Android Port\Metal Gear Solid 3 Native OpenGLES3 Android Port Recompiled with a Launcher not embed\mgs3-recompiled-android"
GAME = ROOT + r"\_game"

loader = open(GAME + r"\SLES_820.42;1", "rb").read()
payload = open(GAME + r"\mgs3_main_payload.bin", "rb").read()

md = Cs(CS_ARCH_MIPS, CS_MODE_MIPS64)
md.detail = False

def w2s(w):
    """Decode one word, return mnemonic string or '<invalid>'."""
    b = struct.pack("<I", w)
    for i in md.disasm(b, 0):
        return f"{i.mnemonic} {i.op_str}"
    return "<invalid>"

print("=== payload head as words + decode ===")
for off in range(0, 0x80, 4):
    w = struct.unpack_from("<I", payload, off)[0]
    print(f"  +0x{off:02x} = 0x{w:08x}  {w2s(w)}")

print("\n=== zlib stream from file offset 0x1004 ===")
stream = loader[0x1004:0x1004 + 0x5199d]
d = zlib.decompressobj()
try:
    out = d.decompress(stream)
    print(f"decompressed = {len(out)} bytes (payload file = {len(payload)})")
    print(f"match payload: {out == payload}")
    print(f"unused_data = {len(d.unused_data)} bytes: {d.unused_data[:48].hex(' ')}")
    for i in range(0, min(len(d.unused_data), 48), 4):
        w = struct.unpack_from("<I", d.unused_data, i)[0]
        print(f"  trailer+0x{i:02x} = 0x{w:08x}")
except zlib.error as e:
    print("zlib error:", e)
    # try to find the real stream length by scanning
    for n in (0x5199c, 0x5199d, 0x519a0):
        dd = zlib.decompressobj()
        try:
            o = dd.decompress(loader[0x1004:0x1004 + n])
            print(f"  len 0x{n:x}: OK, {len(o)} bytes, unused={len(dd.unused_data)}")
        except zlib.error as e2:
            print(f"  len 0x{n:x}: {e2}")

print("\n=== loader bytes around stream end (vaddr 0x851960..0x851a80) ===")
def v2f(v): return v - 0x800000 + 0x1000
seg = loader[v2f(0x851960):v2f(0x851a80)]
for i in range(0, len(seg), 16):
    va = 0x851960 + i
    row = seg[i:i+16]
    words = " ".join(f"{struct.unpack_from('<I', row, k)[0]:08x}" for k in range(0, len(row) - len(row) % 4, 4))
    print(f"  {va:08x}: {row.hex(' '):<48} {words}")
