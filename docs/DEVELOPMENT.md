# Development

Everything needed to rebuild, extend or debug the patch. Read
[FINDINGS.md](FINDINGS.md) alongside this — it holds the reverse-engineering results
(addresses, what each one is, and the dead ends) — and [DECOMP.md](DECOMP.md), which maps
every offset the hook uses onto the full decompilation.

## Layout

```
patch.py              user-facing CLI
patch-gui.py          user-facing window (tkinter); tools/build_exe.py freezes it
onescreen/            the patcher itself - no devkitARM needed
  sites.py            finds and rewrites POWCNT1 display-routing sites
  table.py            which sites to flip, which to leave alone
  inject.py           ITCM autoload block + checked main/evolution task hooks
  rom.py              load / verify / patch / repack
  payload/            pre-assembled hook.bin + hook.json (generated)
src/hook.s            the resident ARM/Thumb hook source
tools/                development toolchain - needs devkitARM, melonDS
docs/
```

The patcher ships a **pre-assembled** payload so end users need only Python. Rebuild it
after any change to `src/hook.s`:

```bash
python tools/make_payload.py
```

That regenerates `onescreen/payload/hook.bin` **and** `hook.json`. Never hand-edit the
JSON — an early hand-conversion put the load address 0xA00 bytes off, which silently
loaded the payload to the wrong place.

### The config block

The hook does not hardcode the addresses it reads. `OneScreen_Config` at the top of
`src/hook.s` holds them, and the patcher fills it in from the ROM being patched
(`onescreen/regions.py` → `inject.fill_config`). The defaults compiled into the payload
are the French values, so an unconfigured payload still works there.

The resident code is entered from two fixed ARM9 sites, and from pointers the patcher
finds by shape: the exec slots of five `OverlayManagerTemplate`s (Pokédex, PC box, fly map,
Oak, battle) and script commands 752, `ScrCmd_MenuExec`, and 653,
`ScrCmd_MoveTutorChooseMove`. The main-loop call at `0x02000DB0`
drives global routing, while the callback literal at `0x02075D04` wraps the evolution
SysTask so its mirrored Yes/No highlight is drawn after native input in the same frame.
`inject.py` checks the displaced call/pointer before changing either fixed site.

**If you add or reorder a field, update `CONFIG_FIELDS` in `onescreen/inject.py` to
match** — the two are positional, and only `tools/test_hook.py`
(`test_config_fields_match_the_hook`) checks them against each other.

To confirm it landed, read the block over the GDB stub after patching; it sits at the
`OneScreen_Config` address in `hook.json`:

```bash
powershell -File tools/probe.ps1 -Addrs "0x01FF8628:24w"
```

## Prerequisites

| tool | why |
|---|---|
| Python 3.9+ and `ndspy` | ROM/overlay handling, BLZ (de)compression |
| [devkitARM](https://devkitpro.org/), or any `arm-none-eabi` binutils | assembling `src/hook.s` |
| [unicorn](https://www.unicorn-engine.org/) (`pip install unicorn`) | `tools/test_hook.py`, the emulated tests |
| [melonDS](https://melonds.kuribo64.net/) | testing, and its GDB stub for live probing |

`tools/*.ps1` are Windows PowerShell helpers; the Python tools are portable.
`tools/make_payload.py` uses `$DEVKITARM/bin` if set, then `arm-none-eabi-*` on `PATH`, then
the default Windows devkitPro location, and refuses a payload that would overrun ITCM.

## Verifying a change

Without a ROM, the emulated tests are the first check. They build the game structures a
routine walks in emulated RAM - at the offsets in [DECOMP.md](DECOMP.md) - call the
routine out of the assembled payload, and check what it returns:

```bash
python tools/make_payload.py
python tools/test_hook.py
```

A change that only renames or re-comments must leave `onescreen/payload/hook.bin`
byte-identical; compare it before committing.

With a ROM, the patcher is deterministic, so the strongest check is that it reproduces a
known-good build byte-for-byte:

```bash
python patch.py roms/ipgf.nds -o build/check.nds
# compare SHA-1 against a build you have already tested in-game
```

Both `IPGF` and `IPKF` were verified this way against the tested v15 builds.

## Standalone builds

`tools/build_exe.py` freezes the window - or, with `--cli`, `patch.py` - with PyInstaller,
for the system it runs on: a one-file `.exe` on Windows, an `.app` bundle and a `.zip` of it
on macOS, a one-file binary and a `.tar.gz` of it on Linux (the archive keeps the executable
bit, which downloads lose). PyInstaller cannot cross-build, so
`.github/workflows/release.yml` runs it on Windows, Ubuntu, and macOS on both Apple silicon
and Intel; run it from the Actions tab for the builds, or push a `v*` tag to also get them
in a draft release.

```bash
pip install -r requirements-build.txt
python tools/build_exe.py          # the window
python tools/build_exe.py --cli    # the command line
```

Use a Python with **Tk 8.6**. Apple's `/usr/bin/python3` has the deprecated Tk 8.5, and
recent standalone Python builds have Tk 9, under which tkinterdnd2's library - compiled for
Tcl 8 - does not load: the window still opens, without drag and drop. The python.org
installers, the ones `actions/setup-python` uses, have Tk 8.6. On macOS the build makes its
`.icns` from the committed PNG with `sips` and `iconutil`, sets the bundle's version, and
signs it ad hoc again after editing its `Info.plist`; it is not signed with a developer ID.

## Play-test saves

`tools/testsaves/` turns a complete save into one that reaches a test in seconds rather
than hours. Today it builds the evolution test: Caterpie, Weedle and Wurmple at level 6 and
Kricketot at 9, one EXP point short, each with four moves - so each evolution teaches a
move it cannot fit (Harden, Fury Cutter) and asks the move-learning questions the evolution
scene's band is drawn on. The four party Pokémon they replace go to the first empty PC
slots. A complete save already has the money, coins and BP every other test needs.

It uses [PKHeX.Core](https://github.com/kwsch/PKHeX) (`.NET 10`), then `fixsave.py`:

```bash
dotnet run --project tools/testsaves -- roms/complete.sav build/evolution-pkhex.sav
python tools/testsaves/fixsave.py roms/complete.sav build/evolution-pkhex.sav out/evolution.sav
```

The second step matters. PKHeX rewrites the day of the save's RTC record
(`SysInfo.rtc_info.date`, general block +0x1C) as a value no month has, and reports a
perfectly good save as having a bad checksum. `fixsave.py` puts the RTC record back and
re-checksums every block with the game's own CRC - CRC-16-CCITT from 0xFFFF over the block
less its 16-byte footer (`SaveArray_CalcCRC16MinusFooter`, `src/save.c`) - and lists every
byte range that changed, which should be the party, the PC slots and the two checksums.

## Development toolchain (`tools/`)

Most of these expect an unpacked ROM tree, produced by:

```bash
python tools/unpack.py roms/ipgf.nds     # -> build/ipgf/{arm9_dec.bin,overlays/,modules.json}
```

| tool | what it is for |
|---|---|
| `unpack.py` | extract + BLZ-decompress ARM9 and all 129 overlays |
| `build.py` | bisecting build with flip selection flags; injects the unconfigured payload (French defaults; no labels, app-table check, or template and script-table redirects), so use `patch.py` for a real build |
| `find_powcnt.py` | scan and classify every POWCNT1 reference |
| `xrefs.py` / `crossrefs.py` | who calls an address; calls that cross module boundaries |
| `peek.py` / `whichov.py` | read words by RAM address; identify which overlay is resident |
| `savestate.py` | **read and diff melonDS savestates** — see below |
| `compare_modules.py` | diff every module between two ROMs (how HG/SS similarity was measured) |
| `emu_hook.py`, `test_hook.py` | run routines from the assembled payload under an ARM emulator; the tests |
| `freespace.py`, `deadcode.py`, `checkfree.py` | free-space hunting (kept for the record; ITCM made them moot) |
| `find_template.py`, `find_loader.py` | OverlayManager templates, overlay loader hunting |
| `melonds_config.py` | bind melonDS keys, screen sizing, enable the GDB stub |
| `shot.ps1` | launch melonDS, send input, screenshot the window |
| `probe.ps1` | read DS memory over the GDB stub |
| `zoom.ps1`, `compare.ps1` | crop/scale captures, build before/after images |

### Live memory probing

```bash
python tools/melonds_config.py --keys --gdb true
powershell -File tools/probe.ps1 -Addrs "0x021D112C:2w,0x04000304:1w"
```

**The melonDS GDB stub accepts exactly one connection per emulator launch.** Reconnecting
always fails with `vMustReplyEmpty: timeout`. Drive the game to the state you want, then
probe once.

### Savestate diffing

Far more powerful than the GDB stub, and how the battle-phase variable was found.
`savestate.py` locates the 4 MB main-RAM block inside a melonDS savestate by searching for
the start of `arm9_dec.bin`, so no format parsing is needed.

```bash
python tools/savestate.py read  state.mln 0x021D112C 4
python tools/savestate.py diff  a.mln b.mln
python tools/savestate.py triangulate a.mln b.mln c.mln    # A and C alike, B different
python tools/savestate.py intersect --menu m1.mln m2.mln --exec e1.mln e2.mln
```

`intersect` is the one that works. **Two or three savestates from a single battle is not
evidence** — 68,535 bytes passed that test once and the cleanest-looking candidate was
still a coincidence. Use several *different* battles, and let the built-in filters drop
heap churn (values must be small, and the byte must be isolated rather than part of a
changing block).

## Adding a screen that lands on the wrong side

In rough order of preference:

1. **It has its own POWCNT1 site** — the scanner already found it; just decide its intent
   in `onescreen/table.py` (`FLIP`, `KEEP`, or `TOUCH`).
2. **It is a distinct app that sets routing on entry** — add
   `(name, callback, swap, signature, overlay, mask)` to `APP_TABLE` in
   `onescreen/regions.py`, and a spare slot to `app_table` in `src/hook.s` if it is full;
   the patcher writes only the entries whose code it can verify. Find the callback by
   probing `0x021D112C` while the screen is up.
3. **It is drawn inside another app** (like the overworld X menu) — there is no transition
   to detect, so drive it from the buttons the player already presses.

## Gotchas worth knowing

- Overlays share RAM bases, so a memory dump alone cannot tell you which one is loaded —
  use `whichov.py`.
- `0x02022D3E` must never be flipped: it is inside the game's shared display-select
  helper, so flipping it inverts the overworld too.
- Sub-screens opened from the battle menu re-assert the routing themselves, so a one-shot
  swap does not survive; the hook re-applies it every frame while the menu is up.
- Emulator input needs a real hold (~100 ms). Synthetic presses shorter than a frame are
  missed entirely, and a lost key-up leaves a direction stuck down forever.
