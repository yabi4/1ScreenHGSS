"""Resolve the addresses the hook needs, per ROM.

Measured across French and US HeartGold:

* ARM9 **code** addresses are **identical**. The same anchors were found at the
  same addresses in both - the display-select helper body at `0x02022D40`, the
  soft-reset check at `0x02000DB8`, the main-loop tail at `0x02000E32` - and the
  name-entry app function at `0x02083140` is byte-identical.
* Only **data, BSS and overlay bases** move, and uniformly: US = FR − 0x20.
  (`static_bss_start`, `bss_end` and every overlay base all shift by the same
  amount, because the US static data section is 0x20 bytes smaller.)

So there is no per-region address table. Everything is derived from the ROM:

* the state block address is read straight out of the main loop's own literal,
  which gives the shift for free;
* the overlay values come from the overlay table.

This means an untested revision either resolves cleanly or fails the sanity
checks - it cannot silently produce a subtly wrong build.
"""

import struct

ARM9_RAM = 0x02000000

# `ldr r4, =<state block>` in the main loop. A CODE address, so identical
# across regions; the literal it points at is what moves.
STATE_BLOCK_LDR = 0x02000DA6
STATE_BLOCK_REG = 4

# What that literal reads in the French ROMs, used only to compute the shift.
FR_STATE_BLOCK = 0x021D112C

PAD_HELD_OFFSET = 0x38          # gSystem.heldKeysRaw
SCREENS_FLIPPED_OFFSET = 0x69   # gSystem.screensFlipped
# A tick counter beside the application slot, running at about twice the
# cinematic's own frame counter. It matters because it keeps counting after
# the intro application has gone, which the scene counters cannot do.
INTRO_CLOCK_OFFSET = 0x2C

# The battle phase signal. Found empirically first, then identified with the
# decomp as pret/pokeheartgold's poke_overlay.c:
#
#     typedef struct PMiLoadedOverlay { FSOverlayID id; BOOL active; };
#     static PMiLoadedOverlay sOverlayRegions[OVY_REGION_NUM][OVY_MAX_PER_REGION];
#
# 3 regions x 8 slots x 8 bytes of BSS. The value the hook reads is main-region
# slot 3's overlay id, which the battle drives as it loads a different overlay
# per phase. Being BSS it cannot be found by shape - but exactly one ARM9
# literal points at the array, at a fixed CODE address, so reading that literal
# yields the per-region base. Measured: FR 0x021D0E10, US 0x021D0DF0.
OVERLAY_REGIONS_LITERAL = 0x0200713C
FR_OVERLAY_REGIONS = 0x021D0E10
BATTLE_OVERLAY_SLOT = 3
LOADED_OVERLAY_SIZE = 8         # sizeof(PMiLoadedOverlay)

# sFieldSysPtr, the file-static in pret's field_system.c holding the live
# FieldSystem. The hook reads FieldSystem.unk1C (+0x1C) through it to tell when
# a script has taken over the bottom screen. Also BSS, also unfindable by shape,
# but six ARM9 literals point at it - at the *same six code addresses* in all
# three ROMs, each holding its own region's value. Measured: FR 0x021D4178,
# US 0x021D4158.
FIELD_SYS_LITERAL = 0x0203DEA0
FR_FIELD_SYS = 0x021D4178

# Task_StartMenu, the overworld menu's task function. ARM9 code, so the address
# does not move between regions - the 24-byte prologue is byte-identical in
# IPGF, IPKF and IPKE - but it is checked rather than trusted, and zeroed if the
# code has changed. Zero simply disables the menu-exit check in the hook.
START_MENU_TASK = 0x0203BEF1
START_MENU_TASK_SIG = bytes.fromhex(
    "70b5061c14f0aafb041c301c14f0a8fb051ce98c142900d9")


# app_table in src/hook.s. These are ARM9 *code* addresses, so they do not move
# between regions - but rather than trust that, the patcher checks the bytes at
# each one against the routine it expects and refuses to use an address whose
# code has changed. Each entry is (name, callback, swap, signature).
#
# Name entry is not an OverlayManager application; this is the small routine
# that raises the display flag at 0x021D1195 and calls the shared helper. Its
# 24-byte prologue was measured byte-identical in IPGF, IPKF and IPKE.
# The evolution scene is the same shape: ARM9 code, no POWCNT1 site of its own,
# so it keeps whatever routing it inherits - the menu's, when the evolution was
# triggered from the bag. Its Pokemon and text are on engine A.
# The move relearner is the same shape again, but it lives in an OVERLAY rather
# than in ARM9, so its entry names one: overlay 68, MoveRelearner_Main. It has no
# static OverlayManagerTemplate to take over - launch_application.c builds that on
# the stack - so it is matched on the live exec pointer instead.
#
# Overlay code MOVES between regions, unlike ARM9 code, so the address is found by
# searching the overlay rather than written down: US loads overlay 68 0x20 lower
# and the function sits at 0x021E5B6C instead of 0x021E5B8C. Three of the twelve
# halfwords are BL instructions, whose encodings are target-relative, so those are
# masked out of the comparison. Exactly one match in IPGF, IPKF and IPKE.
#
# swap=1 rather than the 0 used by name entry and the evolution scene, which draw
# on engine A: the relearner's move list is engine B. Without an entry it keeps
# whatever routing it inherits, and since field prompts now hold the world on top,
# that left the move list on the bottom screen.
#
#   push {r4,lr} / mov r4,r0 / ldr r0,[r4,#4] / BL / movs r0,#0x56 /
#   lsls r0,r0,#2 / ldr r0,[r4,r0] / BL / BL
RELEARNER_SIG = bytes.fromhex("10b5041c606839f68ff956208000205823f63cfc3af63cfd")
RELEARNER_MASK = bytes.fromhex("ffffffffffff00000000ffffffffffff0000000000000000")

APP_TABLE = [
    ("name entry", 0x02083141, 0,
     bytes.fromhex("08b59df76bfa88f76df8034b034901205a581043585008bd"), None, None),
    ("evolution", 0x02077271, 0,
     bytes.fromhex("38b5041c75300278201c73300178201c72300078ff231b02"), None, None),
    ("move relearner", None, 1, RELEARNER_SIG, 68, RELEARNER_MASK),
]


def _find_masked(data: bytes, base: int, sig: bytes, mask: bytes):
    """Addresses where `sig` matches `data`, ignoring bytes `mask` zeroes out."""
    out = []
    for i in range(0, len(data) - len(sig), 2):
        if all((data[i + k] & mask[k]) == (sig[k] & mask[k]) for k in range(len(sig))):
            out.append(base + i)
    return out


def check_app_table(arm9: bytes, overlays=None):
    """Return [(name, callback, swap, ok), ...] for the app_table entries.

    An entry whose code no longer matches, or whose address cannot be resolved
    uniquely, comes back with ok=False and is written as a terminator - the app
    then keeps whatever routing it inherits, which is how it behaved before.
    """
    out = []
    for name, callback, swap, sig, ovy_id, mask in APP_TABLE:
        if ovy_id is None:
            off = (callback & ~1) - ARM9_RAM
            ok = 0 <= off and arm9[off:off + len(sig)] == sig
            out.append((name, callback, swap, ok))
            continue
        ov = (overlays or {}).get(ovy_id)
        found = []
        if ov is not None:
            try:
                found = _find_masked(ov.data, ov.ramAddress, sig, mask)
            except Exception:                   # noqa: BLE001
                found = []
        if len(found) == 1:
            out.append((name, found[0] | 1, swap, True))
        else:
            out.append((name, callback or 0, swap, False))
    return out


# The opening cinematic, overlay 60. Four scene functions run in sequence, and
# two of them show on the wrong screen. They are found the same way the move
# relearner is - by masked search inside the overlay, because overlay code moves
# between regions: US loads overlay 60 0x20 lower and both functions shift with
# it (A 0x021E7A05 -> 0x021E79E5, B 0x021E8C39 -> 0x021E8C19).
#
# The prologues are mostly BL instructions, whose encodings are target-relative,
# so a 28-byte window leaves too few fixed bytes to be unique - scene B matched
# twice. 64 bytes gives 28 fixed bytes and exactly one hit for each, in IPGF,
# IPKF and IPKE alike.
INTRO_OVERLAY = 60
INTRO_A_SIG = bytes.fromhex(
    "08b5fff74ffe37f653fa23f609fc08bd70b5051c0c1cfff745fe061c39f652fe"
    "3af608fe0f48012141723bf685f9281c00f034f9281cfff741fe0b48291c32f6")
INTRO_A_MASK = bytes.fromhex(
    "ffff000000000000000000000000ffffffffffffffff00000000ffff00000000"
    "00000000ffffffffffff00000000ffff00000000ffff00000000ffffffffffff")
INTRO_B_SIG = bytes.fromhex(
    "08b5fef735fd36f639f922f6effa08bd70b582b0051c0c1cfef72afd061c38f6"
    "37fd39f6edfc1e48002141723af66af8281c00f079fc281cfef726fd1948291c")
INTRO_B_MASK = bytes.fromhex(
    "ffff000000000000000000000000ffffffffffffffffffff00000000ffff0000"
    "0000000000000000ffffffffffff00000000ffff00000000ffff00000000ffffffff"[:128])


INTRO_C_SIG = bytes.fromhex(
    "08b5fdf7adfc35f6b1f821f667fa08bd70b582b0051c0c1cfdf7a2fc061c37f6"
    "affc38f665fc37480121417238f6e2ff0020011c25f63aff0120002125f636ff")
INTRO_C_MASK = bytes.fromhex(
    "ffff000000000000000000000000ffffffffffffffffffff00000000ffff0000"
    "000000000000000000000000000000000000ffffffff00000000ffffffff0000")


def find_intro_scenes(overlays):
    """Return (scene_a, scene_b, scene_c) exec addresses, 0 where unsure."""
    ov = (overlays or {}).get(INTRO_OVERLAY)
    if ov is None:
        return 0, 0, 0
    try:
        data = ov.data
    except Exception:                           # noqa: BLE001
        return 0, 0, 0
    out = []
    for sig, mask in ((INTRO_A_SIG, INTRO_A_MASK), (INTRO_B_SIG, INTRO_B_MASK),
                      (INTRO_C_SIG, INTRO_C_MASK)):
        hits = _find_masked(data, ov.ramAddress, sig, mask)
        out.append((hits[0] | 1) if len(hits) == 1 else 0)
    return tuple(out)


def _checked(arm9: bytes, addr: int, sig: bytes) -> int:
    """Return addr if the code there still matches, else 0."""
    off = (addr & ~1) - ARM9_RAM
    return addr if 0 <= off and arm9[off:off + len(sig)] == sig else 0


def _read_literal(arm9: bytes, ldr_addr: int, want_reg=None) -> int:
    off = ldr_addr - ARM9_RAM
    h = struct.unpack_from("<H", arm9, off)[0]
    if (h & 0xF800) != 0x4800:
        raise ValueError(f"{ldr_addr:#010x} is not a Thumb LDR-literal "
                         f"(found {h:#06x}) - unexpected ROM layout")
    if want_reg is not None and ((h >> 8) & 7) != want_reg:
        raise ValueError(f"{ldr_addr:#010x} loads r{(h >> 8) & 7}, expected "
                         f"r{want_reg} - unexpected ROM layout")
    lit = ((off + 4) & ~3) + (h & 0xFF) * 4
    return struct.unpack_from("<I", arm9, lit)[0]


def find_overlay_template(arm9: bytes, overlays, ovy_id: int,
                          arm9_resident: bool = False):
    """Locate an OverlayManagerTemplate in ARM9 static data, by shape.

    pret/pokeheartgold:

        struct OverlayManagerTemplate { OverlayFunction init, exec, exit;
                                        FSOverlayID ovy_id; };

    so it is three pointers followed by the overlay number. Found structurally
    rather than by address, which makes it region-independent (measured:
    FR 0x020FA268, US 0x020FA284 - exactly one match in each ROM).

    Most applications put init/exec/exit *inside* the overlay they name, which is
    what the default search requires. The battle is the exception: its three
    functions are thin ARM9 wrappers (pret's src/launch_application.c), so its
    template holds ARM9 pointers next to `ovy_id == 12`. Pass arm9_resident for
    that shape. Thumb bit required, which is what keeps the ARM9 variant from
    matching arbitrary triples of data pointers - measured exactly one hit in
    IPGF, IPKF and IPKE (FR 0x020FA468, US 0x020FA484, identical code pointers
    0x0203E3A9 / 0x0203E3AD / 0x0203E3C1 in all three).

    Returns (template_address, init, exec, exit) or None.
    """
    if arm9_resident:
        lo, hi = ARM9_RAM, ARM9_RAM + len(arm9)

        def ok(x):
            return (x & 1) and lo <= (x & ~1) < hi
    else:
        ov = overlays[ovy_id]
        lo, hi = ov.ramAddress, ov.ramAddress + ov.ramSize

        def ok(x):
            return lo <= (x & ~1) < hi

    hits = []
    for off in range(0, len(arm9) - 16, 4):
        w = struct.unpack_from("<4I", arm9, off)
        if w[3] != ovy_id:
            continue
        if all(ok(x) for x in w[:3]):
            hits.append((ARM9_RAM + off, w[0], w[1], w[2]))
    if len(hits) != 1:
        return None
    return hits[0]


def resolve(arm9: bytes, overlays) -> tuple[dict, int]:
    """Return (config values, delta) for this ROM."""
    state_block = _read_literal(arm9, STATE_BLOCK_LDR, STATE_BLOCK_REG)
    delta = state_block - FR_STATE_BLOCK

    if not 0x02100000 <= state_block < 0x02200000:
        raise ValueError(f"main-loop state block {state_block:#010x} is out of "
                         "the expected range - unexpected ROM layout")
    if abs(delta) > 0x1000:
        raise ValueError(f"region delta {delta:#x} is implausibly large; refusing "
                         "rather than emit a subtly wrong build")

    # A second, independent measurement of the same shift. Both are BSS, so they
    # must move together; if they disagree the layout is not what we think it is.
    regions_base = struct.unpack_from(
        "<I", arm9, OVERLAY_REGIONS_LITERAL - ARM9_RAM)[0]
    if regions_base - FR_OVERLAY_REGIONS != delta:
        raise ValueError(
            f"sOverlayRegions at {regions_base:#010x} implies a shift of "
            f"{regions_base - FR_OVERLAY_REGIONS:#x}, but the state block implies "
            f"{delta:#x}. Refusing rather than emit a subtly wrong build.")

    field_sys = struct.unpack_from("<I", arm9, FIELD_SYS_LITERAL - ARM9_RAM)[0]
    if field_sys - FR_FIELD_SYS != delta:
        raise ValueError(
            f"sFieldSysPtr at {field_sys:#010x} implies a shift of "
            f"{field_sys - FR_FIELD_SYS:#x}, but the state block implies "
            f"{delta:#x}. Refusing rather than emit a subtly wrong build.")

    ov1, ov12 = overlays[1], overlays[12]
    return {
        "pad_held": state_block + PAD_HELD_OFFSET,
        "app_callback": state_block,
        "field_callback": ov1.ramAddress | 1,          # Thumb
        "ov12_lo": ov12.ramAddress,
        "ov12_hi": ov12.ramAddress + ov12.ramSize,
        "battle_state": regions_base + BATTLE_OVERLAY_SLOT * LOADED_OVERLAY_SIZE,
        "field_sys": field_sys,
        "screens_flipped": state_block + SCREENS_FLIPPED_OFFSET,
        "intro_clock": state_block + INTRO_CLOCK_OFFSET,
        "start_menu_task": _checked(arm9, START_MENU_TASK, START_MENU_TASK_SIG),
    }, delta


# --- the script command table, for the native top-screen lists ---------------
#
# ScrCmd_MenuExec (command 752) shows a script-built list on the touch screen.
# The hook replaces it with OneScreen_MenuExec, which hands lists it does not
# draw itself to the game's own top-screen renderer instead - the one
# ScrCmd_ScriptListMenuExec (command 71) uses. Everything it needs is found from
# those two table entries, not from addresses:
#
#   gScriptCmdTable   853 Thumb pointers in ARM9 .rodata, entries 0 and 1 being
#                     the do-nothing commands (`movs r0, #0; bx lr`)
#   table[752]        ScrCmd_MenuExec, five calls; its literal pool holds
#                     MenuExec_PrintItemHelp and NativeScript_WaitMenuExec
#   table[71]         ScrCmd_ScriptListMenuExec, three calls:
#                     FieldSysGetAttrAddr, ScriptMenu_ShowList, SetupNativeScript;
#                     its pool holds NativeScript_WaitMultichoice
#   ShowList's first call is ScriptMenu_GetListItemsWidth.
#
# The pool values are ARM9 code addresses, which do not move between regions
# (pret names them sub_02047908, sub_020478D0 and sub_020418B4). ShowList is in
# overlay 1, so it is checked against its retail prologue rather than an address.
SCRIPT_CMD_COUNT = 853
SCRCMD_LIST_MENU_EXEC = 71
SCRCMD_MENU_EXEC = 752
MENU_EXEC_HELP = 0x02047909          # MenuExec_PrintItemHelp | 1
WAIT_MENU_EXEC = 0x020478D1          # NativeScript_WaitMenuExec | 1
WAIT_MULTICHOICE = 0x020418B5        # NativeScript_WaitMultichoice | 1
SCRCMD_NOP = bytes.fromhex("00207047")   # movs r0, #0; bx lr

# ScriptMenu_ShowList, pret ov01_021EDFA4: push {r4,lr}; mov r4,r0; BL width;
# then the tile rounding and the anchorRight test on +0x97 / +0x98.
SHOW_LIST_SIG = bytes.fromhex(
    "10b5041c00f000f8072101420 1d1c108 01e0c008 411c201c 9730 0078 4006 c00f"
    .replace(" ", ""))
SHOW_LIST_MASK = bytes.fromhex(
    "ffffffff00000000ffffffffffffffffffffffffffffffffffffffffffffffff")


def _thumb_calls(code: bytes, base: int, addr: int, limit: int = 0x80):
    """Decode a small Thumb function: (BL targets, literal-pool words, halfwords).

    Walks from `addr` until the first `pop {..., pc}` or `bx lr`. Only plain BL
    pairs count as calls; a BLX would be a call into ARM code, which none of the
    functions read here make.
    """
    off = (addr & ~1) - base
    if off < 0 or off + 4 > len(code):
        raise ValueError(f"{addr:#010x} is outside the module")
    calls, literals, halfwords = [], [], []
    i = off
    while i < min(off + limit, len(code) - 2):
        h = struct.unpack_from("<H", code, i)[0]
        halfwords.append(h)
        if (h & 0xF800) == 0xF000 and i + 4 <= len(code):
            h2 = struct.unpack_from("<H", code, i + 2)[0]
            if (h2 & 0xF800) == 0xF800:
                disp = ((h & 0x7FF) << 12) | ((h2 & 0x7FF) << 1)
                if disp & 0x400000:
                    disp -= 0x800000
                calls.append(base + i + 4 + disp)
                halfwords.append(h2)
                i += 4
                continue
        if (h & 0xF800) == 0x4800:                     # ldr rX, [pc, #imm]
            lit = ((base + i + 4) & ~3) + (h & 0xFF) * 4 - base
            if 0 <= lit <= len(code) - 4:
                literals.append(struct.unpack_from("<I", code, lit)[0])
        if (h & 0xFF00) == 0xBD00 or h == 0x4770:      # pop {.., pc} / bx lr
            break
        i += 2
    return calls, literals, halfwords


def find_script_table(arm9: bytes):
    """Address of gScriptCmdTable in a decompressed ARM9, or None."""
    n = len(arm9) // 4
    words = struct.unpack_from(f"<{n}I", arm9, 0)
    lo, hi = ARM9_RAM, ARM9_RAM + 0x400000
    run = [0] * (n + 1)
    for i in range(n - 1, -1, -1):
        w = words[i]
        run[i] = run[i + 1] + 1 if (w & 1) and lo <= w < hi else 0
    hits = []
    for i in range(n):
        if run[i] < SCRIPT_CMD_COUNT:
            continue
        nops = []
        for w in words[i:i + 2]:
            off = (w & ~1) - ARM9_RAM
            nops.append(0 <= off <= len(arm9) - 4 and arm9[off:off + 4] == SCRCMD_NOP)
        if all(nops):
            hits.append(ARM9_RAM + i * 4)
    return hits[0] if len(hits) == 1 else None


def resolve_native_lists(arm9: bytes, overlays):
    """Return ({config values}, table_entry_address, log) or (None, None, why).

    Every check has to pass; anything unexpected and the script lists stay on
    the touch screen, which is what every earlier build did.
    """
    table = find_script_table(arm9)
    if table is None:
        return None, None, "script command table not found"
    entry = lambda k: struct.unpack_from("<I", arm9, table - ARM9_RAM + 4 * k)[0]
    menu_exec, list_exec = entry(SCRCMD_MENU_EXEC), entry(SCRCMD_LIST_MENU_EXEC)
    ov1 = overlays.get(1) if overlays else None
    if ov1 is None:
        return None, None, "overlay 1 not available"
    ov1_lo, ov1_hi = ov1.ramAddress, ov1.ramAddress + len(ov1.data)
    in_ov1 = lambda a: ov1_lo <= a < ov1_hi
    try:
        m_calls, m_lits, m_half = _thumb_calls(arm9, ARM9_RAM, menu_exec)
        l_calls, l_lits, _l_half = _thumb_calls(arm9, ARM9_RAM, list_exec)
    except ValueError as exc:
        return None, None, str(exc)
    if len(m_calls) != 5 or MENU_EXEC_HELP not in m_lits or WAIT_MENU_EXEC not in m_lits:
        return None, None, f"command {SCRCMD_MENU_EXEC} is not ScrCmd_MenuExec"
    if 0x2103 not in m_half or 0x2207 not in m_half or not in_ov1(m_calls[0]):
        return None, None, f"command {SCRCMD_MENU_EXEC} does not set the list state"
    if len(l_calls) != 3 or WAIT_MULTICHOICE not in l_lits:
        return None, None, f"command {SCRCMD_LIST_MENU_EXEC} is not the list command"
    setup_native = m_calls[4]
    if l_calls[2] != setup_native:
        return None, None, "the two commands disagree on SetupNativeScript"
    show_list = l_calls[1]
    if not in_ov1(show_list):
        return None, None, "ScriptMenu_ShowList is not in overlay 1"
    data = bytes(ov1.data)
    off = show_list - ov1.ramAddress
    window = data[off:off + len(SHOW_LIST_SIG)]
    if len(window) != len(SHOW_LIST_SIG) or any(
            (a & m) != (b & m) for a, b, m in zip(window, SHOW_LIST_SIG, SHOW_LIST_MASK)):
        return None, None, "ScriptMenu_ShowList does not match its retail prologue"
    w_calls, _w_lits, _w_half = _thumb_calls(data, ov1.ramAddress, show_list)
    if not w_calls or not in_ov1(w_calls[0]):
        return None, None, "ScriptMenu_GetListItemsWidth not found"
    values = {"menu_exec_orig": menu_exec, "show_list": show_list | 1,
              "list_items_width": w_calls[0] | 1, "setup_native": setup_native | 1}
    return values, table + 4 * SCRCMD_MENU_EXEC, (
        f"table {table:#010x}, MenuExec {menu_exec:#010x}, ShowList {show_list:#010x}")
