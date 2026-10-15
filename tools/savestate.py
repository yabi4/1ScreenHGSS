"""Read and diff melonDS savestates.

A savestate contains the full 4 MB of DS main RAM, which lets us compare two
game states offline - no emulator driving, no GDB one-connection limit, and no
heap-pointer drift between runs.

We don't parse melonDS's chunk format. Instead we locate the main-RAM block by
searching the file for the first bytes of the ARM9 image, which we already have
extracted. Main RAM starts at 0x02000000 and the ARM9 static section is loaded
there verbatim, so that match pins the block.

    python scripts/savestate.py locate  state.mln
    python scripts/savestate.py diff    a.mln b.mln
    python scripts/savestate.py read    a.mln 0x022C0294 64
    python scripts/savestate.py hook    a.mln

`hook` dumps the injected payload's OWN variables. They live in ITCM, which is
not part of the main-RAM block, but the payload starts with the ASCII signature
"1SGS" so it can be found by searching the raw savestate file. That is how the
flying bug was diagnosed: it showed menu_swapped stuck at 1 for the whole flight,
which no amount of reading game state would have revealed.
"""

import argparse
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

MAIN_RAM_BASE = 0x02000000
MAIN_RAM_SIZE = 0x400000


def arm9_head(code="ipgf", n=128):
    return (ROOT / "build" / code / "arm9_dec.bin").read_bytes()[:n]


def locate(path: pathlib.Path, code="ipgf") -> int:
    """File offset where DS main RAM begins."""
    data = path.read_bytes()
    needle = arm9_head(code)
    idx = data.find(needle)
    if idx < 0:
        raise SystemExit(
            "could not find the ARM9 image inside the savestate - is this a state "
            "for a different ROM? (build/<code>/arm9_dec.bin must match)")
    if data.find(needle, idx + 1) >= 0:
        print("note: ARM9 head appears more than once; using the first match",
              file=sys.stderr)
    if idx + MAIN_RAM_SIZE > len(data):
        raise SystemExit("main RAM block would run past the end of the file")
    return idx


def load_ram(path: pathlib.Path, code="ipgf") -> bytes:
    off = locate(path, code)
    return path.read_bytes()[off:off + MAIN_RAM_SIZE]


def cmd_locate(args):
    p = pathlib.Path(args.state)
    off = locate(p, args.code)
    print(f"{p.name}: {p.stat().st_size:,} bytes, main RAM at file offset {off:#x}")


def cmd_read(args):
    ram = load_ram(pathlib.Path(args.state), args.code)
    addr, n = int(args.addr, 0), args.count
    for i in range(0, n, 4):
        a = addr + i * 4
        words = [struct.unpack_from("<I", ram, a - MAIN_RAM_BASE + j * 4)[0]
                 for j in range(min(4, n - i))]
        print(f"{a:#010x}:  " + "  ".join(f"{w:#010x}" for w in words))


def cmd_diff(args):
    a = load_ram(pathlib.Path(args.a), args.code)
    b = load_ram(pathlib.Path(args.b), args.code)
    lo = int(args.lo, 0) - MAIN_RAM_BASE
    hi = int(args.hi, 0) - MAIN_RAM_BASE

    diffs = [i for i in range(lo, hi) if a[i] != b[i]]
    print(f"{len(diffs):,} differing bytes in "
          f"{int(args.lo, 0):#x}..{int(args.hi, 0):#x}\n")

    # Group into runs so large churn (sprite/animation buffers) is obvious and
    # small isolated changes - which is what a state variable looks like - stand out.
    runs, start, prev = [], None, None
    for i in diffs:
        if start is None:
            start = prev = i
        elif i - prev <= args.gap:
            prev = i
        else:
            runs.append((start, prev - start + 1))
            start = prev = i
    if start is not None:
        runs.append((start, prev - start + 1))

    small = [r for r in runs if r[1] <= args.max_run]
    print(f"{len(runs)} change regions; {len(small)} of them <= {args.max_run} bytes\n")
    print(f"{'address':>12} {'len':>5}   before -> after")
    for off, length in small[:args.top]:
        addr = off + MAIN_RAM_BASE
        av = " ".join(f"{a[off + k]:02x}" for k in range(min(length, 8)))
        bv = " ".join(f"{b[off + k]:02x}" for k in range(min(length, 8)))
        print(f"  {addr:#010x} {length:>5}   {av} -> {bv}")


def cmd_triangulate(args):
    """Find bytes that track a state rather than just time.

    With A and C in the same state (e.g. two action-select menus on different
    turns) and B in the other (turn resolution), a real state variable satisfies
    A == C and B != A. Anything that merely counts, accumulates or animates will
    differ between A and C too, and is filtered out.
    """
    a = load_ram(pathlib.Path(args.a), args.code)
    b = load_ram(pathlib.Path(args.b), args.code)
    c = load_ram(pathlib.Path(args.c), args.code)
    lo = int(args.lo, 0) - MAIN_RAM_BASE
    hi = int(args.hi, 0) - MAIN_RAM_BASE

    hits = [i for i in range(lo, hi) if a[i] == c[i] and b[i] != a[i]]
    print(f"{len(hits):,} byte(s) where A==C and B differs "
          f"({int(args.lo, 0):#x}..{int(args.hi, 0):#x})\n")

    runs, start, prev = [], None, None
    for i in hits:
        if start is None:
            start = prev = i
        elif i - prev <= args.gap:
            prev = i
        else:
            runs.append((start, prev - start + 1))
            start = prev = i
    if start is not None:
        runs.append((start, prev - start + 1))

    runs.sort(key=lambda r: r[1])
    print(f"{len(runs)} region(s); showing the smallest {min(len(runs), args.top)}\n")
    print(f"{'address':>12} {'len':>4}   A(sel)      B(res)      C(sel)")
    for off, length in runs[:args.top]:
        addr = off + MAIN_RAM_BASE
        n = min(length, 6)
        fmt = lambda buf: " ".join(f"{buf[off + k]:02x}" for k in range(n))
        print(f"  {addr:#010x} {length:>4}   {fmt(a):<11} {fmt(b):<11} {fmt(c)}")


def cmd_intersect(args):
    """Find bytes that separate two GROUPS of states, across several battles.

    Triangulating a single battle leaves tens of thousands of coincidences. A
    real state variable must hold the same value in EVERY "waiting for the
    player" state, the same value in EVERY "turn executing" state, and differ
    between the two - across different battles, opponents and turns. Each extra
    battle roughly squares the odds against a coincidence surviving.
    """
    menus = [load_ram(pathlib.Path(p), args.code) for p in args.menu]
    execs = [load_ram(pathlib.Path(p), args.code) for p in args.exec_]
    lo = int(args.lo, 0) - MAIN_RAM_BASE
    hi = int(args.hi, 0) - MAIN_RAM_BASE

    print(f"{len(menus)} menu state(s), {len(execs)} executing state(s)")
    m0, e0 = menus[0], execs[0]
    hits = []
    for i in range(lo, hi):
        v = m0[i]
        if e0[i] == v:
            continue
        if any(m[i] != v for m in menus[1:]):
            continue
        w = e0[i]
        if any(e[i] != w for e in execs[1:]):
            continue
        hits.append((i, v, w))

    print(f"\n{len(hits):,} byte(s) constant within each group and different between")

    # Most of those are heap: whole blocks read as fill (0xAB/0xBB/0xFF) while
    # idle and as allocated data mid-turn. That correlates perfectly with the
    # battle phase but is useless. A state variable is a small enum, and it sits
    # alone rather than inside a contiguous block of changes.
    small = [(o, v, w) for o, v, w in hits
             if v <= args.max_value and w <= args.max_value]
    print(f"{len(small):,} with both values <= {args.max_value}")

    addrs = {o for o, _, _ in hits}
    isolated = [(o, v, w) for o, v, w in small
                if not any((o + d) in addrs for d in range(-args.isolate, args.isolate + 1) if d)]
    print(f"{len(isolated):,} of those isolated (no other hit within "
          f"{args.isolate} bytes)\n")

    print(f"{'address':>12}   menu  exec")
    for off, v, w in isolated[:args.top]:
        print(f"  {off + MAIN_RAM_BASE:#010x}    {v:#04x}  {w:#04x}")
    if len(isolated) > args.top:
        print(f"  ... and {len(isolated) - args.top} more")


# Payload variables, in the order they are declared in src/hook.s after the
# signature (4 bytes) + version (4) + the config block.
HOOK_VARS = ["pad_held", "pad_new", "prev_pad", "menu_swapped", "last_app",
             "bt_phase", "bt_menu_last", "bt_manual", "bt_system", "bt_drawn",
             "bt_lock",
             "oak_drawn", "oak_data", "oak_state",
             "dex_last", "dex_mode", "pc_frames", "script_menu", "field_yn_drawn",
             "evolution_drawn", "field_restore",
             "map_frames", "map_pending", "prev_task", "sm_drawn",
             "sm_shown", "list_ctrl", "list_drawn", "list_rect", "list_hold"]


def cmd_hook(args):
    import json
    sys.path.insert(0, str(ROOT))
    from onescreen import inject
    meta = json.loads((ROOT / "onescreen" / "payload" / "hook.json").read_text())
    data = pathlib.Path(args.state).read_bytes()
    i = data.find(b"1SGS")
    if i < 0:
        raise SystemExit("payload signature not found - is this state from a "
                         "patched ROM?")
    version = struct.unpack_from("<I", data, i + 4)[0]
    n_cfg = args.config_words or len(inject.CONFIG_FIELDS)
    if not args.config_words and version != meta["payload_version"]:
        print(f"warning: state holds payload v{version} but the tree builds "
              f"v{meta['payload_version']}; the variable offsets below assume "
              f"the current layout. Pass --config-words for an older state.",
              file=sys.stderr)
    print(f"payload v{version} at file offset {i:#x}")
    base = i + 8 + n_cfg * 4
    for k, name in enumerate(HOOK_VARS):
        (v,) = struct.unpack_from("<i", data, base + k * 4)
        print(f"  {name:<14} {v:<12} {v & 0xFFFFFFFF:#010x}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", default="ipgf")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("locate"); p.add_argument("state"); p.set_defaults(fn=cmd_locate)

    p = sub.add_parser("read")
    p.add_argument("state"); p.add_argument("addr"); p.add_argument("count", type=int, nargs="?", default=16)
    p.set_defaults(fn=cmd_read)

    p = sub.add_parser("hook", help="dump the injected payload's own variables")
    p.add_argument("state")
    p.add_argument("--config-words", type=int, default=0,
                   help="config block size for states from an older payload")
    p.set_defaults(fn=cmd_hook)

    p = sub.add_parser("diff")
    p.add_argument("a"); p.add_argument("b")
    p.add_argument("--lo", default=hex(MAIN_RAM_BASE))
    p.add_argument("--hi", default=hex(MAIN_RAM_BASE + MAIN_RAM_SIZE))
    p.add_argument("--gap", type=int, default=8, help="bytes of sameness that end a run")
    p.add_argument("--max-run", type=int, default=16, help="only show runs this small")
    p.add_argument("--top", type=int, default=60)
    p.set_defaults(fn=cmd_diff)

    p = sub.add_parser("triangulate", help="A and C in one state, B in the other")
    p.add_argument("a"); p.add_argument("b"); p.add_argument("c")
    p.add_argument("--lo", default=hex(MAIN_RAM_BASE))
    p.add_argument("--hi", default=hex(MAIN_RAM_BASE + MAIN_RAM_SIZE))
    p.add_argument("--gap", type=int, default=4)
    p.add_argument("--top", type=int, default=40)
    p.set_defaults(fn=cmd_triangulate)

    p = sub.add_parser("intersect", help="separate two groups of states")
    p.add_argument("--menu", nargs="+", required=True, help="states waiting for input")
    p.add_argument("--exec", nargs="+", required=True, dest="exec_", help="states mid-turn")
    p.add_argument("--lo", default=hex(MAIN_RAM_BASE))
    p.add_argument("--hi", default=hex(MAIN_RAM_BASE + MAIN_RAM_SIZE))
    p.add_argument("--top", type=int, default=60)
    p.add_argument("--max-value", type=int, default=32,
                   help="both values must be <= this (state enums are small)")
    p.add_argument("--isolate", type=int, default=8,
                   help="reject bytes with another hit this close (heap blocks)")
    p.set_defaults(fn=cmd_intersect)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
