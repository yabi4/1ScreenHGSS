"""Put resident code into the DS's unused ITCM.

HGSS's ARM9 autoload list has exactly two blocks:

    0x01FF8000 (ITCM) size 0x620    0x027E0000 (DTCM) size 0x60, bss 0x20

ITCM is 32 KB and the game uses 1568 bytes of it. The remaining ~31 KB is
resident from boot, never unloaded, outside the BSS clear, and reachable by a
Thumb BL from ARM9 (~173 KB away) and from every overlay (~2.5 MB) - both well
inside the +/-4 MB branch range.

We claim it by appending a third autoload entry: the code image goes after the
existing autoload images, the autoload list moves after it, and
`autoload_list` / `autoload_list_end` in MODULE_PARAMS are repointed. This is
safe because the existing ITCM/DTCM images already live at
`autoload_start == static_bss_start`, which proves the loader processes autoload
blocks *before* clearing BSS.
"""

import struct

ARM9_RAM = 0x02000000

ITCM_BASE = 0x01FF8000
ITCM_END = 0x02000000
ITCM_USED = 0x620
PAYLOAD_ADDR = ITCM_BASE + ITCM_USED          # 0x01FF8620

MODPARAMS_OFF = 0xBA0
AUTOLOAD_LIST = MODPARAMS_OFF + 0x00
AUTOLOAD_LIST_END = MODPARAMS_OFF + 0x04
COMPRESSED_STATIC_END = MODPARAMS_OFF + 0x14
NITROCODE_OFF = MODPARAMS_OFF + 0x1C
NITROCODE = 0xDEC00621

# The main loop's `bl 0x0200110C` at 0x02000DB0 (loop head; the back-edge is the
# `b` at 0x02000E46). We replace it with a call to OneScreen_Frame, which runs
# the original and then our per-frame work. The displaced call takes no
# arguments and its return value is unused by the loop.
MAIN_LOOP_SITE = 0x02000DB0
MAIN_LOOP_OFF = MAIN_LOOP_SITE - ARM9_RAM
ORIG_LOOP_FN = 0x0200110C

# The call after it, `bl ReadKeypadAndTouchpad` at 0x02000DB4. OneScreen_ReadKeys
# runs it and then keeps L+R, the manual swap, from reaching the game; it also
# re-runs ApplyButtonModeToInput, which ReadKeypadAndTouchpad calls from
# 0x0201A556 - checked too, since the hook calls it by address.
KEY_READ_SITE = 0x02000DB4
KEY_READ_OFF = KEY_READ_SITE - ARM9_RAM
ORIG_KEY_READ_FN = 0x0201A4DC
BUTTON_MODE_CALL = 0x0201A556
BUTTON_MODE_FN = 0x0201A5E8

# sub_02075A7C passes this literal to SysTask_CreateOnMainQueue. Replacing the
# verified callback pointer lets the resident wrapper run immediately after the
# native evolution task, when its binary selection and window are authoritative.
EVOLUTION_TASK_LITERAL = 0x02075D04
EVOLUTION_TASK_LITERAL_OFF = EVOLUTION_TASK_LITERAL - ARM9_RAM
EVOLUTION_TASK_ORIG = 0x02075D09


# Order must match OneScreen_Config in src/hook.s. The two are positional and
# only tools/test_hook.py checks them against each other, so append only, and
# append to both.
CONFIG_FIELDS = ("pad_held", "app_callback", "field_callback",
                 "ov12_lo", "ov12_hi", "battle_state", "dex_exec_orig",
                 "pc_exec_orig", "field_sys", "screens_flipped",
                 "map_exec_orig", "start_menu_task", "oak_exec_orig",
                 "battle_exec_orig", "intro_a_exec", "intro_b_exec",
                 "intro_c_exec", "intro_clock",
                 "theme_band", "menu_exec_orig", "open_list",
                 "string_width", "setup_native", "tutor_exec_orig",
                 # The functions the hook calls on the game's behalf. They are
                 # the same in every retail region, but a ROM whose main loop
                 # or key reader was rewritten in C has its own.
                 "orig_loop_fn", "read_keys_orig", "apply_button_mode",
                 # The battle engine, for a build that runs its own: the mode
                 # word and the addresses the hook reads its command menu
                 # from. All zero in a retail build.
                 "battle_mode", "origin_menu_ptr", "origin_menu_flag",
                 "origin_cursor", "origin_state", "origin_battle_data",
                 # The start menu's own struct, whose offsets a build that grew
                 # that struct moves: the retail values are the defaults.
                 "startmenu_state_off", "startmenu_inhibit_off",
                 # Origin's Oak speech app, whose exec pointer lives in the
                 # overlay's own data rather than in an ARM9 template.
                 "origin_oak_exec_orig",
                 # The evolution scene's main-queue task. The hook calls the
                 # game's own task through this, and a ROM whose ARM9 moved the
                 # evolution code has it somewhere else.
                 "evolution_task_orig",
                 # The two-option prompt's own cursor, and the byte in the menu
                 # object that says the command menu belongs to the player's
                 # second battler - the CANCEL variant of the words.
                 "origin_prompt_cursor", "origin_cancel_flag",
                 "origin_battle_vblank", "origin_evo_get_mon", "origin_evo_done")


def fill_config(payload: bytes, config_addr: int, load_addr: int,
                values: dict) -> bytes:
    """Write the resolved addresses into the payload's config block."""
    off = config_addr - load_addr
    if off < 0 or off + 4 * len(CONFIG_FIELDS) > len(payload):
        raise ValueError("config block lies outside the payload")
    buf = bytearray(payload)
    for i, name in enumerate(CONFIG_FIELDS):
        struct.pack_into("<I", buf, off + i * 4, values[name])
    return bytes(buf)


# Written for an app_table entry the patcher could not verify. Odd, so it reads
# as Thumb code, but no function lives at address 1: the current VBlank callback
# is never equal to it, while it is not 0, which would end the table.
NEVER_CALLBACK = 1


def fill_app_table(payload: bytes, table_addr: int, load_addr: int,
                   entries, table_end: int = 0) -> bytes:
    """Write validated {callback, swap} pairs into the payload's app_table.

    `entries` is what regions.check_app_table returned. An entry that failed its
    signature check is written with the callback NEVER_CALLBACK, which can never
    equal a live VBlank callback, so the hook leaves that app alone rather than
    acting on an address we cannot vouch for - and the entries after it, and the
    slots the hook reads by name (evolution_app), stay where they are. A zero
    callback would have ended the table there and taken every later app with it.
    """
    off = table_addr - load_addr
    need = 8 * (len(entries) + 1)          # every entry, plus the terminator
    if off < 0 or off + need > len(payload):
        raise ValueError("app_table lies outside the payload")
    # Bounded by the table's OWN end, not merely by the payload. Writing one
    # entry too many silently overwrote the code that follows - OneScreen_SetSwap
    # - and black-screened the game on boot, with nothing to show for it.
    if table_end and off + need > table_end - load_addr:
        raise ValueError(
            f"app_table holds {(table_end - table_addr) // 8 - 1} entries but "
            f"{len(entries)} were given; add a slot in src/hook.s")
    buf = bytearray(payload)
    # The assembled payload contains French defaults for development builds.
    # Clear every record first, the terminator included, so no default address
    # survives that the checks below did not vouch for.
    for i in range(len(entries) + 1):
        struct.pack_into("<II", buf, off + i * 8, 0, 0)
    for i, (_name, callback, swap, ok) in enumerate(entries):
        struct.pack_into("<II", buf, off + i * 8,
                         callback if ok else NEVER_CALLBACK, swap if ok else 0)
    return bytes(buf)


def fill_labels(payload: bytes, blob_addr: int, load_addr: int,
                blob: bytes) -> bytes:
    """Write the rasterised command labels into the payload's reserved space.

    The blob is built from the ROM being patched (see onescreen/labels.py), so
    unlike the rest of the payload it cannot be assembled ahead of time. The hook
    reserves a fixed `.space` for it and reads its geometry out of the blob's own
    header, which keeps the two from drifting apart.
    """
    off = blob_addr - load_addr
    if off < 0 or off + len(blob) > len(payload):
        raise ValueError(
            f"the label blob ({len(blob)} bytes) does not fit the space "
            f"reserved at {blob_addr:#010x}; raise LABEL_BLOB_SIZE in src/hook.s")
    buf = bytearray(payload)
    buf[off:off + len(blob)] = blob
    return bytes(buf)


def thumb_bl(site: int, target: int) -> bytes:
    off = (target & ~1) - (site + 4)
    if not -(1 << 22) <= off < (1 << 22):
        raise ValueError(f"BL out of range: {site:#x} -> {target:#x}")
    return struct.pack("<HH", 0xF000 | ((off >> 12) & 0x7FF),
                       0xF800 | ((off >> 1) & 0x7FF))


def check_module_params(arm9: bytes) -> None:
    magic = struct.unpack_from("<I", arm9, NITROCODE_OFF)[0]
    if magic != NITROCODE:
        raise ValueError(f"MODULE_PARAMS magic not found (got {magic:#x}) - "
                         "this does not look like an HGSS ARM9")


def set_uncompressed(arm9: bytearray) -> None:
    """Tell the loader the ARM9 is stored decompressed."""
    struct.pack_into("<I", arm9, COMPRESSED_STATIC_END, 0)


def patch_main_loop(arm9: bytearray, frame_addr: int,
                    site: int = MAIN_LOOP_SITE, orig_fn: int = ORIG_LOOP_FN) -> None:
    expected = thumb_bl(site, orig_fn)
    actual = bytes(arm9[site - ARM9_RAM:site - ARM9_RAM + 4])
    if actual != expected:
        raise ValueError(
            f"main loop hook site {site:#x} does not hold the expected "
            f"`bl {orig_fn:#x}` (found {actual.hex()}, wanted {expected.hex()})")
    arm9[site - ARM9_RAM:site - ARM9_RAM + 4] = thumb_bl(site, frame_addr)


def patch_key_read(arm9: bytearray, read_keys_addr: int,
                   site: int = KEY_READ_SITE, orig_fn: int = ORIG_KEY_READ_FN,
                   button_call: int = BUTTON_MODE_CALL,
                   button_fn: int = BUTTON_MODE_FN) -> None:
    """Route the main loop's keypad read through OneScreen_ReadKeys."""
    checks = [(site, orig_fn, "keypad read")]
    if button_call:
        checks.append((button_call, button_fn, "button-mode call"))
    for where, target, what in checks:
        off = where - ARM9_RAM
        expected = thumb_bl(where, target)
        actual = bytes(arm9[off:off + 4])
        if actual != expected:
            raise ValueError(
                f"{what} at {where:#x} does not hold the expected `bl {target:#x}` "
                f"(found {actual.hex()}, wanted {expected.hex()})")
    arm9[site - ARM9_RAM:site - ARM9_RAM + 4] = thumb_bl(site, read_keys_addr)


def patch_evolution_task(arm9: bytearray, task_addr: int,
                         literal: int = EVOLUTION_TASK_LITERAL,
                         orig: int = EVOLUTION_TASK_ORIG) -> None:
    """Wrap the post-evolution main-queue task at its checked pointer literal.

    A ROM whose evolution code was rewritten has no such literal; the caller
    passes literal=0 and the hook simply does not take the task over.
    """
    if not literal:
        return
    off = literal - ARM9_RAM
    actual = struct.unpack_from("<I", arm9, off)[0]
    if actual != orig:
        raise ValueError(
            f"evolution task literal {literal:#x} does not hold "
            f"the expected {orig:#x} (found {actual:#x})")
    struct.pack_into("<I", arm9, off, task_addr | 1)


def add_autoload_block(arm9: bytearray, payload: bytes,
                       dest: int = PAYLOAD_ADDR) -> bytearray:
    """Return a new ARM9 image with `payload` added as an extra autoload block."""
    list_addr = struct.unpack_from("<I", arm9, AUTOLOAD_LIST)[0]
    list_end = struct.unpack_from("<I", arm9, AUTOLOAD_LIST_END)[0]
    list_off, list_off_end = list_addr - ARM9_RAM, list_end - ARM9_RAM

    old_list = bytes(arm9[list_off:list_off_end])
    if len(old_list) % 12:
        raise ValueError("autoload list is not a whole number of entries")

    payload = payload + b"\0" * (-len(payload) % 4)
    if dest + len(payload) > ITCM_END:
        raise ValueError(f"payload of {len(payload)} bytes does not fit in free ITCM")

    # The payload must not land on top of an image the game already loads. The
    # retail ARM9 uses 0x620 bytes of ITCM, so the payload goes at 0x01FF8620;
    # a ROM whose own code takes more of the ITCM needs its own address, and
    # pointing the payload at the retail one silently overwrote the game's code
    # with ours - the game booted to a white screen with nothing to show for it.
    for i in range(len(old_list) // 12):
        block_dest, block_size, _bss = struct.unpack_from("<III", old_list, 12 * i)
        if block_dest < dest < block_dest + block_size:
            raise ValueError(
                f"the payload at {dest:#010x} overlaps the autoload block at "
                f"{block_dest:#010x} ({block_size:#x} bytes)")
    if dest < ITCM_BASE:
        raise ValueError(f"the payload at {dest:#010x} is below the ITCM")

    head = bytes(arm9[:list_off])                 # static + existing images
    tail = bytes(arm9[list_off_end:])
    new_entry = struct.pack("<III", dest, len(payload), 0)

    out = bytearray(head + payload + old_list + new_entry + tail)
    new_list_addr = ARM9_RAM + len(head) + len(payload)
    struct.pack_into("<I", out, AUTOLOAD_LIST, new_list_addr)
    struct.pack_into("<I", out, AUTOLOAD_LIST_END, new_list_addr + len(old_list) + 12)
    return out
