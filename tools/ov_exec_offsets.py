"""Compare the overlays the patcher takes over between two ROMs.

The overlays share a RAM region, so an address alone says nothing. But the
OverlayManagerTemplate's init/exec/exit pointers are offsets into their own
overlay, and those offsets mean the same thing in both ROMs if the overlay is
the same application - the entry points of the same program sit at the same
places.

So for every application the patcher takes over, this prints the three offsets
of the retail overlay and of the Origin overlay. Equal offsets are the proof
that the Origin overlay is the same application, and they are independent of
the data-block comparison in tools/ov_map_all.py.

Usage: py ov_exec_offsets.py <origin rom> <retail rom>
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import ndspy.code                                                    # noqa: E402
import ndspy.codeCompression                                         # noqa: E402
import ndspy.rom                                                     # noqa: E402

from onescreen import regions                                        # noqa: E402

# (label, retail overlay, origin overlay)
PAIRS = (
    ("Pokedex", 18, 5),
    ("PC box", 14, 16),
    ("Fly map", 101, 92),
    ("Oak intro", 53, 49),
)


def load(rom_path):
    rom = ndspy.rom.NintendoDSRom(pathlib.Path(rom_path).read_bytes())
    arm9 = ndspy.codeCompression.decompress(rom.arm9)
    return arm9, rom.loadArm9Overlays()


def offsets(arm9, overlays, oid):
    """Return (init, exec, exit) as offsets into the overlay, and its size."""
    tmpl = regions.find_overlay_template(arm9, overlays, oid)
    if not tmpl:
        return None
    _addr, init, exec_, exit_ = tmpl
    base = overlays[oid].ramAddress
    return (init - base, exec_ - base, exit_ - base), len(overlays[oid].data)


def main():
    origin_path, retail_path = sys.argv[1], sys.argv[2]
    o_arm9, o_ov = load(origin_path)
    r_arm9, r_ov = load(retail_path)

    print(f"{'application':<12} {'retail':<28} {'origin':<28} match")
    for label, r_oid, o_oid in PAIRS:
        r = offsets(r_arm9, r_ov, r_oid)
        o = offsets(o_arm9, o_ov, o_oid)
        if not r or not o:
            print(f"{label:<12} ov{r_oid:03d}: no template   "
                  f"ov{o_oid:03d}: {'no template' if not o else 'ok'}")
            continue
        (ri, re_, rx), rsz = r
        (oi, oe, ox), osz = o
        same = (ri, re_, rx) == (oi, oe, ox)
        print(f"{label:<12} ov{r_oid:03d} {ri:#06x},{re_:#06x},{rx:#06x} "
              f"sz {rsz:<6} ov{o_oid:03d} {oi:#06x},{oe:#06x},{ox:#06x} "
              f"sz {osz:<6} {'YES' if same else 'no'}")


if __name__ == "__main__":
    main()
