#!/usr/bin/env python3
"""Apply the 1ScreenHGSS patch to your own Pokémon HeartGold/SoulSilver dump.

    python patch.py "Pokemon - Version Argent SoulSilver.nds"
    python patch.py mygame.nds -o soulsilver-1screen.nds

The patch is applied to a copy; your original file is never modified. Nothing is
downloaded and no ROM data ships with this tool - you supply your own dump of a
game you own.
"""

import argparse
import pathlib
import sys

try:
    import ndspy.rom  # noqa: F401
except ImportError:
    sys.exit("ndspy is required.  pip install ndspy")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from onescreen import rom as onescreen_rom  # noqa: E402
from onescreen import themes  # noqa: E402
from onescreen import __version__  # noqa: E402


def main():
    ap = argparse.ArgumentParser(
        description="Patch Pokemon HeartGold/SoulSilver for single-screen play.")
    ap.add_argument("rom", help="your .nds dump")
    ap.add_argument("-o", "--output", help="output file (default: <name>-1screen.nds)")
    ap.add_argument("--no-hook", action="store_true",
                    help="static screen flips only: no ITCM code, no automatic "
                         "battle swapping and no L+R toggle")
    ap.add_argument("--theme", default=themes.DEFAULT_THEME,
                    choices=sorted(themes.THEMES),
                    help="colour scheme for the menus this patch draws")
    ap.add_argument("--version", action="version",
                    version=f"1ScreenHGSS {__version__}")
    ap.add_argument("--identify", action="store_true",
                    help="report what the ROM is and exit without patching")
    args = ap.parse_args()

    src = pathlib.Path(args.rom)
    if not src.is_file():
        sys.exit(f"not found: {src}")

    data = src.read_bytes()

    if args.identify:
        code, title, known, sha1 = onescreen_rom.identify(data)
        print(f"{title}  [{code}]\nsha1 {sha1}")
        print(f"known: {known[0]}" if known else "known: no (untested dump)")
        return

    dst = pathlib.Path(args.output) if args.output else \
        src.with_name(src.stem + "-1screen.nds")
    if dst.resolve() == src.resolve():
        sys.exit("refusing to overwrite the source ROM; choose another -o")

    print(f"1ScreenHGSS - patching {src.name}")
    out = onescreen_rom.patch(data, auto_battle=not args.no_hook,
                              theme=args.theme)
    dst.write_bytes(out)
    print(f"  Written  : {dst}  ({len(out):,} bytes)")
    print("\nDone. Put your .sav next to it with a matching name, and set your\n"
          "emulator to show only the top screen. See docs/USAGE.md.")


if __name__ == "__main__":
    main()
