"""Print the overlay map of a rewritten ROM: which overlay is which now.

hg-engine renumbered the overlays of Origin HeartGold, so a number that means
the Pokedex in a retail ROM means a different application there - and the
overlay CODE was rewritten in C, so the code identifies nothing. The large DATA
tables were kept, though, and those are the same bytes in both ROMs: the
overlay that still holds a retail overlay's blocks is that application. The
number of 32-byte blocks two overlays share separates the real matches from
the noise by an order of magnitude.

Usage: py ov_map_all.py [origin rom] [retail rom] [min-percent]

    py ov_map_all.py "Origin_HeartGold.nds" "Pokemon - HeartGold Version (USA).nds"
"""

import collections
import sys

import ndspy.rom

BLOCK = 32


def blocks(data):
    c = collections.Counter()
    for i in range(0, len(data) - BLOCK, BLOCK):
        c[data[i:i + BLOCK]] += 1
    return c


def main():
    args = [a for a in sys.argv[1:] if not a.endswith("%")]
    min_percent = 2.0
    if args and args[-1].endswith("%"):
        min_percent = float(args.pop()[:-1])
    origin = args[0] if len(args) > 0 else "Origin_HeartGold.nds"
    retail = args[1] if len(args) > 1 else "Pokemon - HeartGold Version (USA).nds"

    o_rom = ndspy.rom.NintendoDSRom.fromFile(origin)
    r_rom = ndspy.rom.NintendoDSRom.fromFile(retail)
    o_ovs = o_rom.loadArm9Overlays()
    r_ovs = r_rom.loadArm9Overlays()

    o_blocks = {oid: blocks(bytes(ov.data)) for oid, ov in o_ovs.items()}
    r_blocks = {rid: blocks(bytes(ov.data)) for rid, ov in r_ovs.items()}

    print(f"{'origin':>7} {'size':>7}  {'retail':>6} {'size':>7}  {'blocks':>6}  share")
    for oid in sorted(o_blocks):
        ob = o_blocks[oid]
        best = (0.0, 0, None)
        for rid, rb in r_blocks.items():
            common = sum(min(n, rb.get(b, 0)) for b, n in ob.items())
            denom = min(sum(ob.values()), sum(rb.values())) or 1
            frac = common / denom
            if frac > best[0]:
                best = (frac, common, rid)
        frac, common, rid = best
        if frac * 100 < min_percent or rid is None:
            continue
        print(f"{oid:>7} {len(o_ovs[oid].data):>7}  {rid:>6} {len(r_ovs[rid].data):>7}  "
              f"{common:>6}  {frac * 100:5.1f}%")


if __name__ == "__main__":
    main()
