#!/usr/bin/env python3
"""Extract the boot ELF and file listing from a PS2 DVD image (ISO9660).

Usage:
  python extract_iso.py <game.iso> <output_dir> [--all]

Extracts:
  - SYSTEM.CNF            (boot configuration)
  - the boot ELF          (e.g. SLES_543.30)
  - with --all: every file on the disc into <output_dir>/disc/

No game data produced by this script is ever committed to the repository.
"""
import os
import struct
import sys

SECTOR = 2048


class Iso9660:
    def __init__(self, path):
        self.f = open(path, "rb")
        self.f.seek(0, 2)
        self.size = self.f.tell()
        # Primary Volume Descriptor is at sector 16
        self.f.seek(16 * SECTOR)
        pvd = self.f.read(SECTOR)
        if pvd[1:6] != b"CD001":
            raise SystemExit("Not a valid ISO9660 image")
        self.root_record = self._parse_dir_record(pvd[156:190], is_root=True)

    def _parse_dir_record(self, rec, is_root=False):
        if not rec or rec[0] == 0:
            return None
        extent = struct.unpack_from("<I", rec, 2)[0]
        size = struct.unpack_from("<I", rec, 10)[0]
        flags = rec[25]
        name_len = rec[32]
        name = rec[33 : 33 + name_len]
        if name_len == 1 and name in (b"\x00", b"\x01"):
            name = b"." if name == b"\x00" else b".."
        return {
            "extent": extent,
            "size": size,
            "is_dir": bool(flags & 2),
            "name": name.decode("ascii", "replace"),
        }

    def read_sectors(self, extent, size):
        self.f.seek(extent * SECTOR)
        return self.f.read(size)

    def read_dir(self, extent, size):
        data = self.read_sectors(extent, size)
        entries = []
        pos = 0
        while pos < len(data):
            rec_len = data[pos]
            if rec_len == 0:
                # advance to next sector boundary
                pos = ((pos // SECTOR) + 1) * SECTOR
                continue
            rec = self._parse_dir_record(data[pos : pos + rec_len])
            pos += rec_len
            if rec:
                entries.append(rec)
        return entries

    def walk(self, node=None, path=""):
        if node is None:
            node = self.root_record
        for entry in self.read_dir(node["extent"], node["size"]):
            if entry["name"] in (".", ".."):
                continue
            full = f"{path}/{entry['name']}" if path else entry["name"]
            if entry["is_dir"]:
                yield from self.walk(entry, full)
            else:
                yield full, entry

    def lookup(self, path):
        parts = [p.upper() for p in path.replace("\\", "/").split("/") if p]
        node = self.root_record
        for i, part in enumerate(parts):
            found = None
            for entry in self.read_dir(node["extent"], node["size"]):
                if entry["name"].upper() == part or entry["name"].upper().startswith(part + ";"):
                    found = entry
                    break
            if not found:
                return None
            node = found
        return node

    def extract(self, entry, dest):
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        self.f.seek(entry["extent"] * SECTOR)
        remaining = entry["size"]
        with open(dest, "wb") as out:
            while remaining > 0:
                chunk = self.f.read(min(1 << 20, remaining))
                if not chunk:
                    break
                out.write(chunk)
                remaining -= len(chunk)


def parse_system_cnf(data: bytes):
    text = data.decode("ascii", "replace")
    boot2 = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("BOOT2"):
            boot2 = line.split("=", 1)[1].strip().rstrip(";").strip()
    return boot2, text


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    iso_path, out_dir = sys.argv[1], sys.argv[2]
    extract_all = "--all" in sys.argv[3:]

    os.makedirs(out_dir, exist_ok=True)
    iso = Iso9660(iso_path)

    cnf = iso.lookup("SYSTEM.CNF")
    if not cnf:
        raise SystemExit("SYSTEM.CNF not found - not a PS2 disc image?")
    cnf_data = iso.read_sectors(cnf["extent"], cnf["size"])
    with open(os.path.join(out_dir, "SYSTEM.CNF"), "wb") as f:
        f.write(cnf_data)
    boot2, cnf_text = parse_system_cnf(cnf_data)
    print("SYSTEM.CNF:")
    print(cnf_text)
    if not boot2:
        raise SystemExit("BOOT2 line missing from SYSTEM.CNF")

    boot_path = boot2.replace("cdrom0:\\", "").replace("cdrom0:/", "").rstrip(";")
    boot = iso.lookup(boot_path)
    if not boot:
        raise SystemExit(f"Boot file {boot_path} not found on disc")
    elf_dest = os.path.join(out_dir, os.path.basename(boot_path))
    iso.extract(boot, elf_dest)
    print(f"Extracted boot ELF: {boot_path} -> {elf_dest} ({boot['size']} bytes)")

    # ELF header sanity check
    with open(elf_dest, "rb") as f:
        ident = f.read(20)
    if ident[:4] != b"\x7fELF":
        raise SystemExit("Boot file is not an ELF!")
    ei_class = ident[4]
    ei_data = ident[5]
    print(f"ELF class={ {1:'ELF32',2:'ELF64'}.get(ei_class, ei_class) } "
          f"data={ {1:'LE',2:'BE'}.get(ei_data, ei_data) } type={struct.unpack_from('<H', ident, 16)[0]:#06x}")

    listing_path = os.path.join(out_dir, "disc_listing.txt")
    with open(listing_path, "w", encoding="utf-8") as listing:
        total = 0
        for full, entry in iso.walk():
            listing.write(f"{entry['extent']:>10} {entry['size']:>12} {full}\n")
            total += 1
    print(f"Wrote disc listing ({total} files) -> {listing_path}")

    if extract_all:
        disc_dir = os.path.join(out_dir, "disc")
        os.makedirs(disc_dir, exist_ok=True)
        for full, entry in iso.walk():
            dest = os.path.join(disc_dir, full.replace("/", os.sep))
            iso.extract(entry, dest)
        print(f"Extracted full disc tree -> {disc_dir}")


if __name__ == "__main__":
    main()
