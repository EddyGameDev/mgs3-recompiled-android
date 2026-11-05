#!/usr/bin/env python3
"""Emulate the MGS3 loader with tracing: find where the null jump comes from."""
import struct
from unicorn import *
from unicorn.mips_const import *

LOADER = r"mgs3-recompiled-android\_game\SLES_820.42;1"
LOAD_VADDR = 0x800000
LOAD_FOFF = 0x1000
PAYLOAD_BASE = 0x100000
PAYLOAD_END = 0x300000

mu = Uc(UC_ARCH_MIPS, UC_MODE_MIPS64 + UC_MODE_LITTLE_ENDIAN)
mu.mem_map(LOAD_VADDR, 0x100000, UC_PROT_ALL)
data = open(LOADER, "rb").read()
mu.mem_write(LOAD_VADDR, data[LOAD_FOFF:LOAD_FOFF + 352144])
mu.mem_map(PAYLOAD_BASE, 0x200000, UC_PROT_ALL)
mu.mem_map(0x01B00000, 0x500000, UC_PROT_ALL)
mu.mem_map(0x00A00000, 0x100000, UC_PROT_ALL)  # bump-allocator arena

entry = None
last_blocks = []      # recent basic-block starts inside the loader
watch_writes = []     # writes near 0x8519a0


def hook_block(mu, address, size, user_data):
    if LOAD_VADDR <= address < LOAD_VADDR + 0x100000:
        last_blocks.append(address)
        if len(last_blocks) > 24:
            last_blocks.pop(0)


def hook_mem_write(mu, access, address, size, value, user_data):
    if 0x851990 <= address < 0x8519b0 or 0x100000 <= address < 0x100040:
        pc = mu.reg_read(UC_MIPS_REG_PC)
        watch_writes.append((pc, address, size, value))


def hook_intr(mu, intno, user_data):
    pc = mu.reg_read(UC_MIPS_REG_PC)
    mu.reg_write(UC_MIPS_REG_PC, pc + 4)
    mu.reg_write(UC_MIPS_REG_V0, 0)
    mu.reg_write(UC_MIPS_REG_A3, 0)


def hook_invalid(mu, access, address, size, value, user_data):
    pc = mu.reg_read(UC_MIPS_REG_PC)
    kind = {1: "READ", 2: "WRITE", 4: "FETCH"}.get(access, str(access))
    print(f"\nINVALID {kind} @ {address:#x} size={size} pc={pc:#x}", flush=True)
    if address < PAYLOAD_BASE and last_blocks:
        print("recent loader blocks:")
        for b in last_blocks[-12:]:
            print(f"   {b:#x}")
    mu.emu_stop()
    return False


mu.hook_add(UC_HOOK_BLOCK, hook_block)
mu.hook_add(UC_HOOK_MEM_WRITE, hook_mem_write, begin=0x851990, end=0x8519b0)
mu.hook_add(UC_HOOK_MEM_WRITE, hook_mem_write, begin=0x100000, end=0x100040)
mu.hook_add(UC_HOOK_INTR, hook_intr)
mu.hook_add(UC_HOOK_MEM_INVALID, hook_invalid)

mu.reg_write(UC_MIPS_REG_SP, 0x01D00000)
mu.reg_write(UC_MIPS_REG_RA, 0x80000000)

print("emulating from 0x852b00 ...", flush=True)
try:
    mu.emu_start(0x852B00, 0x80000000, 0, 2_000_000_000)
except UcError as e:
    print(f"stopped: {e}")

print(f"\nentry into payload: {entry:#x}" if entry else "\nno payload entry")
if watch_writes:
    print("watched writes (pc, addr, size, value):")
    for pc, a, s, v in watch_writes[-40:]:
        print(f"  pc={pc:#x} -> [{a:#x}] {s}B = {v & 0xFFFFFFFF:#010x}")
