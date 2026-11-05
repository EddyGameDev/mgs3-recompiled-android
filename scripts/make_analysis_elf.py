#!/usr/bin/env python3
"""Wrap mgs3_main_payload.bin as a minimal PS2-style ELF32 (LSB, EM_MIPS) so
PS2Recomp's analyzer/recompiler can consume it directly.

Layout mirrors the retail loader ELF's header fields (e_flags etc. copied from
SLES_820.42;1). Single PT_LOAD at vaddr 0x100000, entry 0x100024.
"""
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAME = ROOT / "_game"

PAYLOAD = GAME / "mgs3_main_payload.bin"
BOOT = GAME / "SLES_820.42;1"
OUT = GAME / "MGS3_analysis.elf"

VADDR = 0x100000
ENTRY = 0x100024

PT_LOAD = 1
PF_X, PF_W, PF_R = 1, 2, 4
SHT_NULL, SHT_PROGBITS, SHT_STRTAB = 0, 1, 3

def main():
    data = PAYLOAD.read_bytes()
    size = len(data)
    print(f"payload: {size} bytes (0x{size:x}) -> vaddr 0x{VADDR:x}..0x{VADDR+size:x}")

    # Mirror header fields from the retail boot ELF for authenticity.
    boot = BOOT.read_bytes()
    (b_flags,) = struct.unpack_from("<I", boot, 36)
    print(f"boot ELF e_flags = 0x{b_flags:08x}")

    ehsize, phentsize, phnum = 52, 32, 1
    shentsize = 40
    shnum = 3  # NULL, .text, .shstrtab
    phoff = ehsize
    data_off = phoff + phnum * phentsize
    shstrtab_off = data_off + size
    shstrtab = b"\0.text\0.shstrtab\0"
    shoff = shstrtab_off + len(shstrtab)
    # align shoff to 4
    pad = (4 - (shoff & 3)) & 3
    shoff += pad

    eh = struct.pack(
        "<4s5B7BHHIIIIIHHHHHH",
        b"\x7fELF",          # magic
        1, 1, 1, 0, 0,       # class=32, data=LSB, version=1, osabi=0, abiversion=0
        0, 0, 0, 0, 0, 0, 0, # padding
        2,                   # e_type = ET_EXEC
        8,                   # e_machine = EM_MIPS
        1,                   # e_version
        ENTRY,               # e_entry
        phoff,               # e_phoff
        shoff,               # e_shoff
        b_flags,             # e_flags (copied from boot ELF)
        ehsize, phentsize, phnum,
        shentsize, shnum,
        2,                   # e_shstrndx = .shstrtab
    )
    assert len(eh) == 52

    ph = struct.pack(
        "<IIIIIIII",
        PT_LOAD,
        0,          # p_offset (payload starts right after phdrs)
        VADDR,      # p_vaddr
        VADDR,      # p_paddr
        size,       # p_filesz
        size,       # p_memsz (image has no separate BSS segment here)
        PF_R | PF_W | PF_X,
        0x1000,     # p_align
    )
    assert len(ph) == 32

    # Section headers: NULL, .text (whole image), .shstrtab
    shstrndx_off_in_tab = 2 * shentsize + 4  # not used, computed inline below
    sh_null = b"\0" * shentsize
    # .text: sh_name points to ".text" in shstrtab (offset 1)
    sh_text = struct.pack(
        "<IIIIIIIIII",
        1,                    # sh_name -> ".text"
        SHT_PROGBITS,
        0x6,                  # SHF_ALLOC | SHF_EXECINSTR
        VADDR,
        data_off,             # sh_offset
        size,
        0, 4, 0, 0,
    )
    # .shstrtab: sh_name -> ".shstrtab" (offset 7)
    sh_str = struct.pack(
        "<IIIIIIIIII",
        7,
        SHT_STRTAB,
        0,
        0,
        shstrtab_off,
        len(shstrtab),
        0, 1, 0, 0,
    )

    blob = bytearray()
    blob += eh
    blob += ph
    assert len(blob) == data_off, len(blob)
    blob += data
    blob += shstrtab
    blob += b"\0" * pad
    blob += sh_null
    blob += sh_text
    blob += sh_str
    assert len(blob) == shoff + shnum * shentsize, (len(blob), shoff + shnum * shentsize)

    OUT.write_bytes(blob)
    print(f"wrote {OUT} ({len(blob)} bytes), entry 0x{ENTRY:x}, load 0x{VADDR:x}")

if __name__ == "__main__":
    main()
