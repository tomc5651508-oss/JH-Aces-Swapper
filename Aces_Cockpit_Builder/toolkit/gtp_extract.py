"""List / extract IL-2 Great Battles .gtp archives (format reversed 2026-10-11, see MODLOG.md).

Layout: "S16R" header (0x20) | "STRMFAT?" (0x20, u32 @0x3C = FAT end) | FAT records | STRMFILE blocks.
  DIR!  u32 ver, u64 id, u64 hash, u64 name_len(+NUL), name
  FILE  u32 ver, u32 blk_off, u32 size, u64 hash, u64 name_len(+NUL), name
  STRMFILE @blk_off: u32 size, ..., u32 data_off @+0x1C
usage: python -P -E gtp_extract.py list <gtp> [filter]
       python -P -E gtp_extract.py extract <gtp> <out_dir> [filter]
"""
import sys, struct, zlib
from pathlib import Path

def read_fat(f):
    head = f.read(0x40)
    assert head[:4] == b"S16R" and head[0x20:0x28] == b"STRMFAT?", "not a gtp"
    fat_end = struct.unpack_from("<I", head, 0x3C)[0]
    fat = f.read(fat_end - 0x40)
    dirs, files, p = [], [], 0
    while p < len(fat):
        tag = fat[p:p + 4]
        if tag == b"DIR!":
            ver, rid, h, ln = struct.unpack_from("<IQQQ", fat, p + 4)
            dirs.append((rid, h, fat[p + 32:p + 32 + ln - 1].decode("latin-1"))); p += 32 + ln
        elif tag == b"FILE":
            ver, off, size, h, ln = struct.unpack_from("<IIIQQ", fat, p + 4)
            files.append((off, size, h, fat[p + 32:p + 32 + ln - 1].decode("latin-1"))); p += 32 + ln
        else:
            raise ValueError(f"unknown record {tag!r} at {0x40 + p:#x}")
    return dirs, files

def file_data(f, off, size):
    f.seek(off)
    blk = f.read(0x20)
    assert blk[:8] == b"STRMFILE", f"no STRMFILE at {off:#x}"
    bsize, data_off = struct.unpack_from("<I", blk, 8)[0], struct.unpack_from("<I", blk, 0x1C)[0]
    flags = blk[0x0C:0x1C]
    f.seek(data_off)
    data = f.read(bsize)
    if any(flags) or bsize != size:
        return data, f"flags={flags.hex()} blk={bsize} fat={size}"
    return data, None

def main():
    mode, gtp = sys.argv[1], Path(sys.argv[2])
    out = Path(sys.argv[3]) if mode == "extract" else None
    rest = sys.argv[4:] if mode == "extract" else sys.argv[3:]
    flt = rest[0].lower() if rest else ""
    with open(gtp, "rb") as f:
        dirs, files = read_fat(f)
        print(f"{gtp.name}: {len(dirs)} dirs, {len(files)} files, {sum(x[1] for x in files):,} bytes")
        odd = 0
        for off, size, h, name in files:
            if flt and flt not in name.lower(): continue
            if mode == "list": print(f"{size:>12,}  {name}"); continue
            data, note = file_data(f, off, size)
            if note: odd += 1; print("  note:", name, note) if odd <= 10 else None
            p = out / name.lstrip("/")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        if mode == "extract": print(f"done, {odd} files with unusual block headers")

if __name__ == "__main__":
    main()
