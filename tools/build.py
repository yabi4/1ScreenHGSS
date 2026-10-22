"""Development build: like patch.py, but with control over which sites flip.

Useful for bisecting a misbehaving screen - build with only one module flipped
and see what moves.

    python tools/build.py --rom roms/ipgf.nds --flip default
    python tools/build.py --rom roms/ipgf.nds --flip none      --tag vanilla
    python tools/build.py --rom roms/ipgf.nds --flip all       --tag flipall
    python tools/build.py --rom roms/ipgf.nds --flip ov074,arm9@0x02052da6

For ordinary use prefer `patch.py`, which always applies the shipped table.
"""

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import ndspy.code                                    # noqa: E402
import ndspy.codeCompression                         # noqa: E402
import ndspy.rom                                     # noqa: E402

from onescreen import inject, sites, table           # noqa: E402
from onescreen.rom import load_payload               # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


def select(found, spec):
    if spec in (None, "", "none"):
        return []
    if spec == "all":
        return found
    if spec == "default":
        keep = []
        for s in found:
            if table.intent_for(s["module"], s["addr"]) == table.FLIP:
                keep.append(s)
            else:
                print(f"  skip {s['module']:<7} {s['addr']:#010x} "
                      f"[{table.intent_for(s['module'], s['addr'])}] "
                      f"{table.describe(s['module'])}")
        return keep
    keep = []
    for token in spec.split(","):
        token = token.strip()
        if "@" in token:
            mod, addr = token.split("@")
            keep += [s for s in found
                     if s["module"] == mod and s["addr"] == int(addr, 0)]
        else:
            keep += [s for s in found if s["module"] == token]
    return keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rom", required=True)
    ap.add_argument("--flip", default="default")
    ap.add_argument("--tag", default=None)
    ap.add_argument("--no-inject", action="store_true")
    args = ap.parse_args()

    src = pathlib.Path(args.rom)
    rom = ndspy.rom.NintendoDSRom(src.read_bytes())
    code = bytes(rom.idCode).decode("ascii")
    tag = args.tag or args.flip.replace(",", "_").replace("@", "")
    dst = ROOT / "out" / f"{code.lower()}-{tag}.nds"
    dst.parent.mkdir(parents=True, exist_ok=True)

    arm9 = bytearray(ndspy.codeCompression.decompress(rom.arm9))
    inject.check_module_params(arm9)

    overlays = rom.loadArm9Overlays()
    modules = [("arm9", 0x02000000, bytes(arm9))]
    ov_data = {}
    for ovid, ov in sorted(overlays.items()):
        ov_data[ovid] = bytearray(ov.data)
        modules.append((f"ov{ovid:03d}", ov.ramAddress, bytes(ov_data[ovid])))

    found = sites.find(modules)
    chosen = select(found, args.flip)
    by_module = {}
    for s in chosen:
        by_module.setdefault(s["module"], []).append(s)

    sites.apply(arm9, by_module.get("arm9", []))
    inject.set_uncompressed(arm9)

    if not args.no_inject:
        payload, meta = load_payload()
        inject.patch_main_loop(arm9, meta["symbols"]["OneScreen_Frame"])
        inject.patch_key_read(arm9, meta["symbols"]["OneScreen_ReadKeys"])
        inject.patch_evolution_task(
            arm9, meta["symbols"]["OneScreen_EvolutionTask"])
        arm9 = inject.add_autoload_block(arm9, payload, meta["load_addr"])
    rom.arm9 = bytes(arm9)

    touched = []
    for ovid, ov in sorted(overlays.items()):
        picks = by_module.get(f"ov{ovid:03d}")
        if not picks:
            continue
        buf = ov_data[ovid]
        sites.apply(buf, picks)
        ov.data = bytes(buf)
        ov.compressed = False
        rom.files[ov.fileID] = ov.save(compress=False)
        touched.append(f"ov{ovid:03d}")
    rom.arm9OverlayTable = ndspy.code.saveOverlayTable(overlays)

    out = rom.save()
    dst.write_bytes(out)
    print(f"{code}: {len(found)} sites found, {len(chosen)} flipped "
          f"({', '.join(touched) if touched else 'arm9 only'})")
    print(f"  -> {dst}  ({len(out):,} bytes)")


if __name__ == "__main__":
    main()
