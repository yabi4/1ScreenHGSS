"""Undo PKHeX's rewrite of the RTC save date and re-checksum, the game's way.
   fixsave.py <original.sav> <pkhex.sav> <out.sav>"""
import struct, sys
GEN, BIG_OFF, BIG = 0xF628, 0xF700, 0x12310
RTC = slice(0x10, 0x30)          # SysInfo.rtc_info: initialized, date, time

def crc16(data, crc=0xFFFF):
    for x in data:
        crc ^= x << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc

def blocks(d):
    for base in (0, 0x40000):
        for name, off, size in (("general", 0, GEN), ("storage", BIG_OFF, BIG)):
            yield base, name, base + off, size

orig = open(sys.argv[1], "rb").read()
new = bytearray(open(sys.argv[2], "rb").read())
for base in (0, 0x40000):
    a, b = base + RTC.start, base + RTC.stop
    if new[a:b] != orig[a:b]:
        print(f"restoring the RTC record at {a:#x}: {new[a:b].hex()} -> {orig[a:b].hex()}")
        new[a:b] = orig[a:b]
for base, name, start, size in blocks(new):
    blk = new[start:start + size]
    crc = crc16(blk[:size - 0x10])
    struct.pack_into("<H", new, start + size - 2, crc)
for base, name, start, size in blocks(new):
    count, sz, magic, _id, crc = struct.unpack_from("<IIIHH", new, start + size - 0x10)
    ok = crc == crc16(new[start:start + size - 0x10])
    print(f"copy@{base:#07x} {name:8s} count {count} magic {magic:#x} crc {'OK' if ok else 'BAD'}")
# where did it change?
runs, i = [], 0
while i < len(new):
    if new[i] != orig[i]:
        j = i
        while j < len(new) and (new[j] != orig[j] or (j + 1 < len(new) and new[j + 1] != orig[j + 1])):
            j += 1
        runs.append((i, j)); i = j
    i += 1
print("changed:", ", ".join(f"{a:#x}-{b:#x}" for a, b in runs))
open(sys.argv[3], "wb").write(new)
