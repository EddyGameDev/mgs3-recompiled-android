#!/usr/bin/env python3
"""Disassemble regions of the MGS3 Subsistence loader (SLES_820.42).

The loader maps one PT_LOAD segment: file offset 0x1000 -> vaddr 0x800000.
"""
import sys
from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS64

LOADER = r"mgs3-recompiled-android\_game\SLES_820.42;1"


def v2f(v):
    return v - 0x800000 + 0x1000


def disasm(start, end):
    data = open(LOADER, "rb").read()
    md = Cs(CS_ARCH_MIPS, CS_MODE_MIPS64)  # EE is MIPS III: sd/ld are used
    code = data[v2f(start):v2f(end)]
    for ins in md.disasm(code, start):
        print(f"{ins.address:08x}: {ins.bytes.hex(' '):14s} {ins.mnemonic:10s} {ins.op_str}")


if __name__ == "__main__":
    a, b = int(sys.argv[1], 16), int(sys.argv[2], 16)
    disasm(a, b)
