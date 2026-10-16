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

# sub_02075A7C passes this literal to SysTask_CreateOnMainQueue. Replacing the
# verified callback pointer lets the resident wrapper run immediately after the
# native evolution task, when its binary selection and window are authoritative.
EVOLUTION_TASK_LITERAL = 0x02075D04
EVOLUTION_TASK_LITERAL_OFF = EVOLUTION_TASK_LITERAL - ARM9_RAM
EVOLUTION_TASK_ORIG = 0x02075D09


# Order must match OneScreen_Config in src/hook.s. The two are positional and
# nothing checks them against each other, so append only, and append to both.
CONFIG_FIELDS = ("pad_held", "app_callback", "field_callback",
                 "ov12_lo", "ov12_hi", "battle_state", "dex_exec_orig",
                 "pc_exec_orig", "field_sys", "screens_flipped",
                 "map_exec_orig", "start_menu_task", "oak_exec_orig",
                 "battle_exec_orig", "intro_a_exec", "intro_b_exec",
                 "intro_c_exec", "intro_clock",
                 "theme_band", "menu_exec_orig", "show_list",
                 "list_items_width", "setup_native")


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


def fill_app_table(payload: bytes, table_addr: int, load_addr: int,
                   entries, table_end: int = 0) -> bytes:
    """Write validated {callback, swap} pairs into the payload's app_table.

    `entries` is what regions.check_app_table returned. An entry that failed its
    signature check is written as a zero terminator, so the hook stops there and
    leaves that app alone rather than acting on an address we cannot vouch for.
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
    # Clear every runtime record first so a failed earlier signature cannot
    # leave a later default address reachable outside the terminated table.
    for i in range(len(entries) + 1):
        struct.pack_into("<II", buf, off + i * 8, 0, 0)
    for i, (_name, callback, swap, ok) in enumerate(entries):
        if not ok:
            break
        struct.pack_into("<II", buf, off + i * 8, callback, swap)
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


def patch_main_loop(arm9: bytearray, frame_addr: int) -> None:
    expected = thumb_bl(MAIN_LOOP_SITE, ORIG_LOOP_FN)
    actual = bytes(arm9[MAIN_LOOP_OFF:MAIN_LOOP_OFF + 4])
    if actual != expected:
        raise ValueError(
            f"main loop hook site {MAIN_LOOP_SITE:#x} does not hold the expected "
            f"`bl {ORIG_LOOP_FN:#x}` (found {actual.hex()}, wanted {expected.hex()})")
    arm9[MAIN_LOOP_OFF:MAIN_LOOP_OFF + 4] = thumb_bl(MAIN_LOOP_SITE, frame_addr)


def patch_evolution_task(arm9: bytearray, task_addr: int) -> None:
    """Wrap the post-evolution main-queue task at its checked pointer literal."""
    actual = struct.unpack_from("<I", arm9, EVOLUTION_TASK_LITERAL_OFF)[0]
    if actual != EVOLUTION_TASK_ORIG:
        raise ValueError(
            f"evolution task literal {EVOLUTION_TASK_LITERAL:#x} does not hold "
            f"the expected {EVOLUTION_TASK_ORIG:#x} (found {actual:#x})")
    struct.pack_into("<I", arm9, EVOLUTION_TASK_LITERAL_OFF, task_addr | 1)


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

    head = bytes(arm9[:list_off])                 # static + existing images
    tail = bytes(arm9[list_off_end:])
    new_entry = struct.pack("<III", dest, len(payload), 0)

    out = bytearray(head + payload + old_list + new_entry + tail)
    new_list_addr = ARM9_RAM + len(head) + len(payload)
    struct.pack_into("<I", out, AUTOLOAD_LIST, new_list_addr)
    struct.pack_into("<I", out, AUTOLOAD_LIST_END, new_list_addr + len(old_list) + 12)
    return out
