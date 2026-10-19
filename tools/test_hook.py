"""Emulated tests for the resident hook.

    python tools/make_payload.py      # builds build/hook.elf as well
    python tools/test_hook.py

Each test builds the game structures a routine walks - with the offsets the full
decompilation gives them (docs/DECOMP.md) - in emulated main RAM, calls the
routine, and checks the result. They prove the pointer walks, the arithmetic and
the agreement between onescreen/labels.py and the hook. They do not prove the
game behaves the way the structures say; only playing it does that.
"""

import pathlib
import struct
import sys
import traceback

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from emu_hook import Hook, signed  # noqa: E402
from onescreen import labels  # noqa: E402

LABEL_MAGIC = 0x424C5331

# Offsets from the decompilation (see docs/DECOMP.md).
FS_BG_CONFIG = 0x08
FS_TASKMAN = 0x10
FS_SAVED_APP_ID = 0x1C
FS_START_MENU_CURSOR = 0xD3
FS_BOTTOM_TASK = 0xD8
FIELD_SYSTEM_SIZE = 0x128
TASK_FUNC, TASK_ENV = 0x04, 0x0C
SM_STATE, SM_INHIBIT = 0x26, 0x34C
SM_SIZE = 0x38C
SCRIPT_MENU_SIZE = 0x2DC
SM_STRBUFS, SM_COUNT = 0x1C, 0x9B
BS_BATTLE_INPUT, BS_GRAPHICS_MODE = 0x19C, 0x23FD
BI_CURMENU, BI_MENU_CURSOR, BI_SIZE = 0x68B, 0x6DC, 0x6F8
START_MENU_TASK = 0x0203BEF1


# --- helpers ----------------------------------------------------------------

def blank_blob(h: Hook) -> int:
    base = h.var("OneScreen_Labels")
    h.w32(base, LABEL_MAGIC)
    return base


def put_list_menus(h: Hook, menus):
    """menus: [(entries, skip)] - write a list header and one record each."""
    base = blank_blob(h)
    head = base + labels.LIST_RECORD_OFF
    h.w8(head + 0x16, len(menus))
    for i, (entries, skip) in enumerate(menus):
        rec = labels._list_menu_record(
            0, 0, len(entries), 1, 1, 1, len(entries),
            [(r, 0) for r in range(len(entries))], entries[0], len(entries[0]),
            labels._menu_hash(entries, skip), skip)
        h.write(head + labels.LIST_RECORD_HEAD + i * labels.LIST_MENU_RECORD, rec)
    return head


def script_menu(h: Hook, entries) -> int:
    menu = h.alloc(SCRIPT_MENU_SIZE)
    for i, codes in enumerate(entries):
        h.w32(menu + SM_STRBUFS + 4 * i, h.string(codes))
    h.w8(menu + SM_COUNT, len(entries))
    return menu


def codes(text):
    return [ord(c) for c in text]


# --- list menus -------------------------------------------------------------

def test_hash_matches_python():
    h = Hook()
    entries = [codes("ACHETER"), codes("VENDRE"), codes("QUITTER"),
               codes("DEUX") + [0xE000] + codes("LIGNES")]
    menu = script_menu(h, entries)
    for skip in (0, 1, 2, 0b1010, 0xF):
        want = labels._menu_hash(entries, skip)
        got = h.call("OneScreen_ListHash", menu, len(entries), skip)
        assert got == want, f"skip {skip:#x}: hook {got:#06x}, python {want:#06x}"


def test_hash_rejects_bad_string_pointer():
    h = Hook()
    menu = script_menu(h, [codes("A"), codes("B")])
    h.w32(menu + SM_STRBUFS + 4, 0x04100000)        # the IPC FIFO
    assert signed(h.call("OneScreen_ListHash", menu, 2, 0)) == -1
    # ...unless that entry is skipped, in which case it is never read
    assert signed(h.call("OneScreen_ListHash", menu, 2, 2)) != -1


def test_match_needs_every_entry():
    h = Hook()
    shop = [codes("ACHETER"), codes("VENDRE"), codes("QUITTER")]
    head = put_list_menus(h, [(shop, 0)])
    rec0 = head + labels.LIST_RECORD_HEAD
    assert h.call("OneScreen_ListMatch", script_menu(h, shop)) == rec0
    dome = [codes("ACHETER"), codes("INFOS"), codes("QUITTER")]
    assert h.call("OneScreen_ListMatch", script_menu(h, dome)) == 0
    assert h.call("OneScreen_ListMatch", script_menu(h, shop[:2])) == 0


def test_match_skips_players_pc_row():
    h = Hook()
    pc = [codes("PC DE LEO"), codes("MON PC"), codes("PANTHEON"), codes("DECO")]
    head = put_list_menus(h, [([codes("Z")], 0), (pc, 0b0010)])
    live = [pc[0], codes("PC DE SACHA"), pc[2], pc[3]]   # your name, at runtime
    got = h.call("OneScreen_ListMatch", script_menu(h, live))
    assert got == head + labels.LIST_RECORD_HEAD + labels.LIST_MENU_RECORD
    live[2] = codes("AUTRE")
    assert h.call("OneScreen_ListMatch", script_menu(h, live)) == 0


def test_match_rejects_bad_menus():
    h = Hook()
    shop = [codes("ACHETER"), codes("VENDRE"), codes("QUITTER")]
    put_list_menus(h, [(shop, 0)])
    assert h.call("OneScreen_ListMatch", 0) == 0
    assert h.call("OneScreen_ListMatch", 0x04000000) == 0
    menu = script_menu(h, shop)
    h.w8(menu + SM_COUNT, 0)
    assert h.call("OneScreen_ListMatch", menu) == 0
    h.w8(menu + SM_COUNT, 200)                       # past LIST_MAX_ENTRIES
    assert h.call("OneScreen_ListMatch", menu) == 0
    h.w32(h.var("OneScreen_Labels"), 0)              # blob never filled in
    assert h.call("OneScreen_ListMatch", script_menu(h, shop)) == 0


def gmm(messages) -> bytes:
    """A Gen-IV message archive holding `messages` (lists of codes), encrypted
    the way labels._decode_raw expects to undo."""
    key = 0x1234
    count = len(messages)
    table, body = bytearray(), bytearray()
    data_off = 4 + count * 8
    for i, msg in enumerate(messages):
        msg = list(msg) + [0xFFFF]
        k = (key * (i + 1) * 0x2FD) & 0xFFFF
        k |= k << 16
        table += struct.pack("<II", (data_off + len(body)) ^ k, len(msg) ^ k)
        k2 = (0x91BD3 * (i + 1)) & 0xFFFF
        for c in msg:
            body += struct.pack("<H", c ^ k2)
            k2 = (k2 + 0x493D) & 0xFFFF
    return struct.pack("<HH", count, key) + bytes(table) + bytes(body)


def fake_font(glyphs=0x200, width=6) -> "labels.Font":
    head = struct.pack("<IIIBBBB", 16, 16 + glyphs * 64, glyphs, 2, 2, 2, 2)
    return labels.Font(head + bytes(glyphs * 64) + bytes([width]) * glyphs)


def a(text):
    """Letters to the game's character codes, with | as the line break."""
    out = []
    for part in text.split("|"):
        if out:
            out.append(labels.NEWLINE)
        out += labels._ascii_codes(part)
    return out


def list_archive():
    msgs = [a("FILLER")] * 330
    named = {321: a("ACHETER"), 322: a("VENDRE"), 323: a("QUITTER"),
             324: a("INFOS"), 62: a("PC DE LEO"), 63: [0xFFFE, 0x0100, 0, 0],
             64: a("PANTHEON"), 66: a("DECONNEXION"), 73: a("BOITE AUX LETTRES"),
             74: a("CAPSULES BALL"), 65: a("ALBUM PHOTO"), 75: a("ETEINDRE"),
             67: a("DEPOSER|POKEMON"), 68: a("RETIRER|POKEMON"),
             69: a("DEPLACER|POKEMON"), 70: a("DEPLACER|OBJETS"), 72: a("SALUT")}
    for i, codes in named.items():
        msgs[i] = codes
    archive = [b""] * 300
    archive[labels.LIST_MSGDATA_FILE] = gmm(msgs)
    archive[labels.TRAINER_MSGDATA_FILE] = gmm([a("DRESSEUR")] * 6)
    return archive


def test_labels_records_match_live_menus():
    """labels._listmenu's records, read by the hook's matcher: the whole
    patch-time to run-time contract for the list menus."""
    h = Hook()
    record, _payload = labels._listmenu(fake_font(), list_archive(), 0, region="F")
    base = blank_blob(h)
    h.write(base + labels.LIST_RECORD_OFF, record)
    head = base + labels.LIST_RECORD_OFF + labels.LIST_RECORD_HEAD
    rec = {name: head + i * labels.LIST_MENU_RECORD
           for i, (name, *_rest) in enumerate(labels.LIST_MENUS)}
    live = {
        "shop": [a("ACHETER"), a("VENDRE"), a("QUITTER")],
        "pc_select": [a("PC DE LEO"), a("PC DE SACHA"), a("PANTHEON"),
                      a("DECONNEXION")],
        "pc_item": [a("BOITE AUX LETTRES"), a("CAPSULES BALL"), a("ALBUM PHOTO"),
                    a("ETEINDRE")],
        "pc_box": [a("DEPOSER|POKEMON"), a("RETIRER|POKEMON"), a("DEPLACER|POKEMON"),
                   a("DEPLACER|OBJETS"), a("SALUT")],
    }
    for name, entries in live.items():
        got = h.call("OneScreen_ListMatch", script_menu(h, entries))
        assert got == rec[name], (name, hex(got))
    # the skip mask leaves your own PC's row out, and only that row
    skip = h.r8(rec["pc_select"] + 52)
    assert skip == 0b0010, skip
    for name, entries in (
            ("dome mart", [a("ACHETER"), a("INFOS"), a("QUITTER")]),
            ("pc_item, no album", [a("BOITE AUX LETTRES"), a("CAPSULES BALL"),
                                   a("ETEINDRE")]),
            ("pc_box, one line", [a("DEPOSER"), a("RETIRER|POKEMON"),
                                  a("DEPLACER|POKEMON"), a("DEPLACER|OBJETS"),
                                  a("SALUT")])):
        assert h.call("OneScreen_ListMatch", script_menu(h, entries)) == 0, name


# --- battle -------------------------------------------------------------------

def battle(h: Hook, menu_id=1, menu_y=0, menu_x=0, graphics_mode=0):
    bs = h.alloc(0x2500)
    bi = h.alloc(BI_SIZE)
    h.w32(bs + BS_BATTLE_INPUT, bi)
    h.w8(bs + BS_GRAPHICS_MODE, graphics_mode)
    h.w8(bi + BI_CURMENU, menu_id)
    h.w8(bi + BI_MENU_CURSOR, 1)                    # enabled
    h.w8(bi + BI_MENU_CURSOR + 1, menu_y)
    h.w8(bi + BI_MENU_CURSOR + 2, menu_x)
    h.w32(h.var("bt_system"), bs)
    return bs, bi


def test_battle_input_needs_graphics_mode_zero():
    h = Hook()
    bs, bi = battle(h)
    assert h.call("OneScreen_BattleInput") == bi
    for mode in (1, 2, 3):
        h.w8(bs + BS_GRAPHICS_MODE, mode)
        assert h.call("OneScreen_BattleInput") == 0, mode
    h.w8(bs + BS_GRAPHICS_MODE, 0)
    h.w32(bs + BS_BATTLE_INPUT, 0x023FFF10)          # runs off the end of RAM
    assert h.call("OneScreen_BattleInput") == 0
    h.w32(h.var("bt_system"), 0)
    assert h.call("OneScreen_BattleInput") == 0


def test_battle_menu_id_and_cursor():
    h = Hook()
    bs, bi = battle(h, menu_id=3)
    assert signed(h.call("OneScreen_BattleMenuId")) == 3
    h.w8(bi + BI_CURMENU, 0xFF)
    assert signed(h.call("OneScreen_BattleMenuId")) == -1
    h.w8(bs + BS_GRAPHICS_MODE, 3)                  # the bag: BattleInput freed
    assert signed(h.call("OneScreen_BattleMenuId")) == -1
    h.w8(bs + BS_GRAPHICS_MODE, 0)
    # sCursorArrayMainMenu: top row FIGHT; bottom row BAG, RUN, POKEMON
    for (y, x), image in {(0, 0): 0, (0, 2): 0, (1, 0): 1, (1, 1): 3,
                          (1, 2): 2}.items():
        h.w8(bi + BI_MENU_CURSOR + 1, y)
        h.w8(bi + BI_MENU_CURSOR + 2, x)
        assert h.call("OneScreen_BattleCursor") == image, (y, x)
    h.w8(bi + BI_MENU_CURSOR + 1, 1)
    yn_set = 1 << 4
    assert h.call("OneScreen_BattleYesNo") == yn_set | 1
    h.w8(bi + BI_MENU_CURSOR + 1, 0)
    assert h.call("OneScreen_BattleYesNo") == yn_set | 0


def test_battle_exec_publishes_only_in_battle_main():
    h = Hook()
    bs, _bi = battle(h, menu_id=0)
    orig = 0x0203E3AD
    state = {"next": 9}

    def exec_stub(hook, manager, proc_state, _r2, _r3):
        hook.w32(proc_state, state["next"])
        return 0

    h.stub(orig, exec_stub)
    h.w32(h.var("cfg_battle_exec_orig"), orig)
    manager = h.alloc(0x40)
    proc = manager + 0x14
    h.w32(proc + 8, bs)                              # manager->data
    for st, want in ((9, bs), (2, 0), (10, 0), (13, 0), (9, bs)):
        state["next"] = st
        h.w32(h.var("bt_system"), 0xDEAD)
        h.call("OneScreen_BattleExec", manager, proc)
        assert h.r32(h.var("bt_system")) == want, (st, hex(h.r32(h.var("bt_system"))))


# --- the selected band in a scene that pushes its palette buffer --------------

BAND = 0x1234                    # a theme colour no palette below starts with
SALMON, WHITE = 0x62FF, 0x7FFF   # the font palette's colour 12, and its paper
BAND_ENTRY = 11 * 32 + 12 * 2    # palette 11, colour 12, in bytes
BAND_HW = 0x05000000 + BAND_ENTRY
BS_PALETTE, BS_MSG_ICON = 0x28, 0x1B0
EVO_PLTT, EVO_BLINK = 0x14, 0x58
BLINK_STATE = 0x4E


def palette_data(h: Hook, colour12=SALMON, size=0x200):
    """A PaletteData whose main-BG buffers hold `colour12` at palette 11."""
    pd = h.alloc(0x120)
    opaque, faded = h.alloc(0x200), h.alloc(0x200)
    h.w32(pd + 0x00, opaque)
    h.w32(pd + 0x04, faded)
    h.w32(pd + 0x08, size)
    h.w16(opaque + BAND_ENTRY, colour12)
    h.w16(faded + BAND_ENTRY, colour12)
    return pd, opaque, faded


def palette_blink(h: Hook, pd, state=1, **kw):
    b = h.alloc(0x50)
    h.w32(b + 0x08, kw.get("pltt", pd))
    h.w8(b + 0x4C, kw.get("screen", 0))
    h.w8(b + 0x4D, kw.get("palette", 11))
    h.w8(b + BLINK_STATE, state)
    h.w8(b + 0x4F, kw.get("timer", 5))
    return b


def inked_font(glyphs=0x200, width=6) -> "labels.Font":
    """A font whose glyphs have ink, shadow and paper in them, so a band laid
    under a word has something to go around."""
    head = struct.pack("<IIIBBBB", 16, 16 + glyphs * 64, glyphs, 2, 2, 2, 2)
    body = bytes((0x1B + 37 * i) & 0xFF for i in range(glyphs * 64))
    return labels.Font(head + body + bytes([width]) * glyphs)


COMMAND_WORDS = {                      # geometry -> words, in command order
    0: ["ATTAQUE", "SAC", "POKEMON", "FUITE"],
    5: ["ATTAQUE", "SAC", "POKEMON", "ANNULER"],
    6: ["BALL", "APPAT", "BOUE", "FUITE"],
    7: ["ATTAQUE", "BALL", "POKEMON", "FUITE"],
    8: ["BALL", "FUITE"],
    9: ["ATTAQUE"],
}


def command_layout(font, geo):
    words = [a(w) for w in COMMAND_WORDS[geo]]
    if geo in (8, 9):
        return labels._layout_sparse(font, *words)
    return labels._layout(font, words)


def geo_record_addr(base, geo):
    if geo < labels.GEO_HEAD_COUNT:
        return base + 8 + geo * labels.GEO_RECORD
    return base + labels.EXTRA_GEO_OFF + (geo - labels.GEO_HEAD_COUNT) * labels.GEO_RECORD


def put_command_sets(h: Hook, font=None, leave_out=()):
    """The command box's banded sets and the battle yes/no set, as build()
    writes them, into the payload's blob. Returns (font, battle rows)."""
    font = font or inked_font()
    base = blank_blob(h)
    h.w8(base + 4, labels.GRID_ROWS)
    h.w8(base + 5, labels.GEO_COUNT)
    rows = labels._row_addrs(labels.BATTLE_CHAR_BASE, labels.WIN_BASE_TILE,
                             labels.GRID_BASE_COL)
    off = labels.BLOB_HEADER
    for geo in COMMAND_WORDS:
        rec = geo_record_addr(base, geo)
        if geo in leave_out:
            h.write(rec, struct.pack("<IIHH4I", 0, 0, labels.CMD_ROW_BYTES, 0, *rows))
            continue
        plain, rects = labels._banded_set(font, command_layout(font, geo),
                                          labels.CELL_W, labels.GRID_COLS)
        h.write(base + off, plain + rects)
        h.write(rec, struct.pack("<IIHH4I", off, len(plain), labels.CMD_ROW_BYTES,
                                 5 | labels.BANDED, *rows))
        off += len(plain) + len(rects)
    yn = labels._layout_yesno(font, [a("OUI"), a("NON")])
    yn_rows = labels._row_addrs(labels.BATTLE_CHAR_BASE, labels.WIN_BASE_TILE,
                                labels.YN_BASE_COL)
    data = b"".join(labels._to_tiles(labels._render(font, yn, s, labels.YN_CELL_W),
                                     labels.YN_COLS) for s in range(2))
    h.write(base + off, data)
    h.write(geo_record_addr(base, 1), struct.pack(
        "<IIHH4I", off, labels.YN_IMAGE_BYTES, labels.YN_ROW_BYTES, 3, *yn_rows))
    return font, rows


def drawn_box(h: Hook, rows, row_bytes=labels.CMD_ROW_BYTES):
    return b"".join(h.read(r, row_bytes) for r in rows)


def test_banded_images_match_the_renderer():
    """Every choice of every banded set, drawn by the hook - plain image, then
    OneScreen_BandRect - is byte for byte what labels._render makes of it."""
    h = Hook()
    font, rows = put_command_sets(h)
    for geo in COMMAND_WORDS:
        placed = command_layout(font, geo)
        for sel in range(4):
            if not placed[sel][2]:
                continue                               # a hidden slot
            h.call("OneScreen_BattleMenu", (geo << 4) | sel)
            want = labels._to_tiles(labels._render(font, placed, sel, labels.CELL_W),
                                    labels.GRID_COLS)
            assert drawn_box(h, rows) == want, (geo, sel)
        h.call("OneScreen_BattleMenu", (geo << 4) | 4)  # the wipe
        assert drawn_box(h, rows) == b"\xff" * len(want), geo
        assert h.call("OneScreen_BattleWipe", geo) == (geo << 4) | 4, geo
    # out of range: past the choices, past the records - nothing written
    h.write(rows[0], b"\x5a" * 4)
    for code in ((0 << 4) | 5, (10 << 4) | 0, (12 << 4) | 0):
        h.call("OneScreen_BattleMenu", code)
        assert h.read(rows[0], 4) == b"\x5a" * 4, hex(code)
    assert signed(h.call("OneScreen_BattleWipe", 12)) == -1


def test_battle_image_picks_the_words_the_game_shows():
    SAFARI, PARK, BUG = 0x20, 0x200, 0x1000
    cases = [  # menu, battle type, cancelShown, menuY, menuX -> image
        (1, 0, 0, 0, 0, 0x00), (3, 0, 0, 1, 1, 0x03), (4, 0, 0, 1, 2, 0x02),
        (2, 2, 1, 1, 1, 0x53),                      # a double's second battler
        (7, SAFARI, 0, 1, 0, 0x61), (1, SAFARI, 0, 0, 1, 0x60),
        (19, BUG, 0, 1, 0, 0x71), (20, BUG, 0, 1, 2, 0x72),
        (9, PARK, 0, 0, 0, 0x80), (10, PARK, 0, 1, 0, 0x83),
        (5, 0, 0, 1, 2, 0x90), (6, 0, 0, 0, 0, 0x90),
        (14, 0, 0, 1, 0, 0x11),                     # yes/no, as before
        (3, PARK, 0, 0, 0, -1),                     # the park's words on 3x2
        (11, 0, 0, 0, 0, -1), (12, 0, 0, 0, 0, -1), (0, 0, 0, 0, 0, -1),
        (0xFF, 0, 0, 0, 0, -1), (21, 0, 0, 0, 0, -1),
    ]
    for menu, btype, cancel, y, x, want in cases:
        h = Hook()
        put_command_sets(h)
        bs, bi = battle(h, menu_id=menu, menu_y=y, menu_x=x)
        h.w32(bs + 0x2C, btype)
        h.w8(bi + 0x68F, cancel)
        got = signed(h.call("OneScreen_BattleImage", signed(menu if menu < 0x80 else menu - 0x100)))
        assert got == want, (menu, btype, cancel, hex(got))
    # a set the blob does not hold swaps, as every special menu used to
    h = Hook()
    put_command_sets(h, leave_out=(6,))
    bs, _bi = battle(h, menu_id=7)
    h.w32(bs + 0x2C, SAFARI)
    assert signed(h.call("OneScreen_BattleImage", 7)) == -1
    # and no blob at all: every menu swaps rather than being drawn as nothing
    h = Hook()
    battle(h, menu_id=1)
    assert signed(h.call("OneScreen_BattleImage", 1)) == -1
    # nor anything once the bag has freed BattleInput
    h = Hook()
    put_command_sets(h)
    bs, _bi = battle(h, menu_id=1, graphics_mode=3)
    assert signed(h.call("OneScreen_BattleImage", 1)) == -1


def battle_with_palette(h: Hook, theme=BAND, blink_state=1, **blink):
    put_command_sets(h)
    bs, bi = battle(h, menu_id=1)
    pd, opaque, faded = palette_data(h)
    b = palette_blink(h, pd, blink_state, **blink)
    h.w32(bs + BS_PALETTE, pd)
    h.w32(bs + BS_MSG_ICON, b)
    h.w32(h.var("cfg_theme_band"), theme)
    return bs, bi, faded, b


def test_battle_band_goes_into_the_pushed_buffer():
    """The battle's VBlank callback copies the faded buffer over palette RAM
    every frame, so the band has to be in that buffer to stay on screen."""
    h = Hook()
    bs, bi, faded, b = battle_with_palette(h)
    for _ in range(2):
        h.call("OneScreen_BattleDraw", 1)
        assert h.r16(faded + BAND_ENTRY) == BAND
        assert h.r16(BAND_HW) == BAND
        assert h.r8(b + BLINK_STATE) == 2              # held still
    h.w16(faded + BAND_ENTRY, WHITE)                   # the blink got in first
    h.call("OneScreen_BattleDraw", 14)                 # a yes/no prompt
    assert h.r16(faded + BAND_ENTRY) == BAND
    # into the move list: the game's colour comes back, and the blink restarts
    h.w8(bi + BI_CURMENU, 11)
    h.call("OneScreen_BattleDraw", 11)
    assert h.r16(faded + BAND_ENTRY) == SALMON
    assert h.r8(b + BLINK_STATE) == 0
    assert h.r32(h.var("bt_band")) == 0
    h.w8(b + BLINK_STATE, 1)                           # the game's next tick
    h.w16(faded + BAND_ENTRY, WHITE)                   # and its white phase
    h.call("OneScreen_BattleDraw", 11)                 # nothing left to undo
    assert h.r16(faded + BAND_ENTRY) == WHITE
    assert h.r8(b + BLINK_STATE) == 1


def test_battle_band_leaves_the_bag_its_own_pause():
    """The bag pauses the blink before its fade and restarts it on the way out;
    once it owns the screen, a pause is not ours to undo."""
    h = Hook()
    bs, _bi, faded, b = battle_with_palette(h)
    h.call("OneScreen_BattleDraw", 1)
    assert h.r8(b + BLINK_STATE) == 2
    h.w8(bs + BS_GRAPHICS_MODE, 3)                     # the bag freed BattleInput
    h.call("OneScreen_BattleDraw", -1 & 0xFFFFFFFF)
    assert h.r8(b + BLINK_STATE) == 2
    assert h.r16(faded + BAND_ENTRY) == SALMON
    assert h.r32(h.var("bt_band")) == 0


def test_battle_band_without_a_theme_changes_nothing():
    h = Hook()
    _bs, _bi, faded, b = battle_with_palette(h, theme=0)
    h.call("OneScreen_BattleDraw", 1)
    h.call("OneScreen_BattleDraw", 11)
    assert h.r16(faded + BAND_ENTRY) == SALMON
    assert h.r8(b + BLINK_STATE) == 1
    assert h.r32(h.var("bt_band")) == 0


def test_battle_band_validation():
    # a blink that is not this battle's palette-11 blink is never touched,
    # though the buffer still gets the band
    for bad in (dict(pltt=0x02100000), dict(screen=1), dict(palette=6),
                dict(timer=40)):
        h = Hook()
        _bs, _bi, faded, b = battle_with_palette(h, **bad)
        h.call("OneScreen_BattleDraw", 1)
        assert h.r8(b + BLINK_STATE) == 1, bad
        assert h.r16(faded + BAND_ENTRY) == BAND, bad
    # a buffer too small for palette 11, or out of RAM, is never written
    h = Hook()
    bs, _bi, faded, b = battle_with_palette(h)
    h.w32(h.r32(bs + BS_PALETTE) + 0x08, 0x100)
    h.call("OneScreen_BattleDraw", 1)
    assert h.r16(faded + BAND_ENTRY) == SALMON
    h = Hook()
    bs, _bi, faded, b = battle_with_palette(h)
    h.w32(h.r32(bs + BS_PALETTE) + 0x04, 0x023FFF00)
    h.call("OneScreen_BattleDraw", 1)
    assert h.r8(b + BLINK_STATE) == 2                  # the blink is still checked
    h = Hook()
    bs, _bi, faded, b = battle_with_palette(h)
    h.w32(bs + BS_PALETTE, 0x04000000)
    h.w32(bs + BS_MSG_ICON, 0x027FFFF0)
    h.call("OneScreen_BattleDraw", 1)
    assert h.r16(BAND_HW) == BAND                      # palette RAM, as before


def test_battle_band_is_forgotten_with_the_battle():
    """Out of BSTATE_BATTLE_MAIN the BattleSystem may be gone: drop the claim
    without writing anything."""
    h = Hook()
    bs, _bi, faded, b = battle_with_palette(h)
    h.call("OneScreen_BattleDraw", 1)
    assert h.r32(h.var("bt_band")) == 3
    orig = 0x0203E3AD
    h.stub(orig, lambda hook, m, p, *_: hook.w32(p, 10) or 0)
    h.w32(h.var("cfg_battle_exec_orig"), orig)
    manager = h.alloc(0x40)
    h.w32(manager + 0x14 + 8, bs)
    h.call("OneScreen_BattleExec", manager, manager + 0x14)
    assert h.r32(h.var("bt_band")) == 0
    assert h.r16(faded + BAND_ENTRY) == BAND           # untouched: may be freed
    assert h.r8(b + BLINK_STATE) == 2


def evolution(h: Hook, state=21, choice=1, blink_state=2, colour12=WHITE):
    """The evolution scene mid move-learning prompt. Its blink was paused by the
    game itself at the start of the evolution, here in its white phase."""
    callback = 0x02077271
    h.w32(h.var("evolution_app"), callback)
    gsys = h.alloc(0x80)
    h.w32(h.var("cfg_app_callback"), gsys)
    data = h.alloc(0xBC)
    h.w32(gsys, callback)
    h.w32(gsys + 4, data)
    bg = h.alloc(0x40)
    win = h.alloc(0x10)
    h.w32(data + 0x00, bg)
    h.w32(data + 0x04, win)
    h.w32(win + 0x00, bg)
    h.w32(win + 0x04, 0x1B130201)
    h.w32(win + 0x08, 0x001F0B04)
    h.w32(win + 0x0C, h.alloc(0x40))
    h.w8(data + 0x64, state)
    h.w8(data + 0x8A, 0)
    h.w8(data + 0x8B, choice)
    pd, opaque, faded = palette_data(h, colour12)
    b = palette_blink(h, pd, blink_state)
    h.w32(data + EVO_PLTT, pd)
    h.w32(data + EVO_BLINK, b)
    h.w32(h.var("cfg_theme_band"), BAND)
    return gsys, data, faded, b


def test_evolution_band_survives_a_blink_stuck_on_white():
    h = Hook()
    gsys, data, faded, b = evolution(h)
    h.call("OneScreen_EvolutionPrompt")
    assert h.r16(faded + BAND_ENTRY) == BAND
    assert h.r16(BAND_HW) == BAND
    assert h.r8(b + BLINK_STATE) == 2                  # the game's pause, kept
    assert h.r32(h.var("evo_band")) == 1
    h.w8(data + 0x64, 22)                              # the prompt is answered
    h.call("OneScreen_EvolutionPrompt")
    assert h.r16(faded + BAND_ENTRY) == WHITE          # the scene's own colour
    assert h.r8(b + BLINK_STATE) == 2                  # not ours to restart
    assert h.r32(h.var("evo_band")) == 0
    # the app leaves mid-prompt: forget the band without touching its memory
    h.w8(data + 0x64, 35)
    h.call("OneScreen_EvolutionPrompt")
    assert h.r32(h.var("evo_band")) == 1
    h.w32(gsys, 0x02000001)                            # another app's VBlank
    h.call("OneScreen_EvolutionPrompt")
    assert h.r32(h.var("evo_band")) == 0
    assert h.r16(faded + BAND_ENTRY) == BAND


def test_evolution_band_holds_a_running_blink():
    h = Hook()
    _gsys, data, faded, b = evolution(h, blink_state=1, colour12=SALMON)
    h.call("OneScreen_EvolutionPrompt")
    assert h.r8(b + BLINK_STATE) == 2
    h.w8(data + 0x64, 22)
    h.call("OneScreen_EvolutionPrompt")
    assert h.r8(b + BLINK_STATE) == 0
    assert h.r16(faded + BAND_ENTRY) == SALMON


# --- apps matched on their VBlank callback ------------------------------------

POWCNT1 = 0x04000304
PALPAD_CB, RANKINGS_CB, RELEARNER_CB = 0x0222A169, 0x021E5F51, 0x021E5B8D


def app_table_hook(entries):
    """A payload whose app_table the patcher filled from `entries`."""
    from onescreen import inject
    h = Hook()
    payload = h.read(h.load, h.meta["size"])
    filled = inject.fill_app_table(payload, h.var("OneScreen_AppTable"), h.load,
                                   entries, h.var("OneScreen_AppTableEnd"))
    h = Hook(payload=filled)
    gsys = h.alloc(0x80)
    h.w32(h.var("cfg_app_callback"), gsys)
    return h, gsys


def test_app_table_puts_pal_pad_and_rankings_on_top():
    """Both send engine A - every window they have - to the touch screen
    through the shared helper; their entry puts it back on top."""
    entries = [("name entry", 0x02083141, 0, True), ("evolution", 0x02077271, 0, True),
               ("move relearner", RELEARNER_CB, 1, True),
               ("Pal Pad", PALPAD_CB, 0, True), ("rankings", RANKINGS_CB, 0, True)]
    for cb in (PALPAD_CB, RANKINGS_CB):
        h, gsys = app_table_hook(entries)
        h.w32(gsys, cb)
        h.w16(POWCNT1, 0x020F)                         # as the helper left it
        h.call("OneScreen_AppIntent")
        assert h.r16(POWCNT1) & 0x8000, hex(cb)        # engine A on top
        h.w16(POWCNT1, 0x020F)
        h.call("OneScreen_AppIntent")                  # same app: one-shot only
        assert h.r16(POWCNT1) == 0x020F


def test_app_table_survives_an_entry_that_failed():
    """An unverified entry must not take the ones after it down with it, nor
    move the evolution scene out of the slot the hook reads by name."""
    from onescreen import inject
    entries = [("name entry", 0x02083141, 0, True), ("evolution", 0x02077271, 0, True),
               ("move relearner", RELEARNER_CB, 1, False),
               ("Pal Pad", PALPAD_CB, 0, True), ("rankings", RANKINGS_CB, 0, False)]
    h, gsys = app_table_hook(entries)
    table = h.var("OneScreen_AppTable")
    words = [h.r32(table + 4 * i) for i in range(12)]
    assert words == [0x02083141, 0, 0x02077271, 0, inject.NEVER_CALLBACK, 0,
                     PALPAD_CB, 0, inject.NEVER_CALLBACK, 0, 0, 0], [hex(w) for w in words]
    assert h.r32(h.var("evolution_app")) == 0x02077271
    for cb, swaps in ((RELEARNER_CB, False), (PALPAD_CB, True), (RANKINGS_CB, False)):
        h.w32(gsys, cb)
        h.w32(h.var("last_app"), 0)
        h.w16(POWCNT1, 0x020F)
        h.call("OneScreen_AppIntent")
        assert bool(h.r16(POWCNT1) & 0x8000) == swaps, hex(cb)


def test_app_table_signatures_need_exactly_one_match():
    from onescreen import regions

    class Ov:
        def __init__(self, data, ram):
            self.data, self.ramAddress = data, ram

    def check(name, blob, ram):
        ovy = {"Pal Pad": 43, "rankings": 121}[name]
        out = regions.check_app_table(bytes(0x100000), {ovy: Ov(blob, ram)})
        return next(e for e in out if e[0] == name)

    for name, sig in (("Pal Pad", regions.PALPAD_SIG), ("rankings", regions.RANKINGS_SIG)):
        blob = bytes(0x40) + sig + bytes(0x40)
        assert check(name, blob, 0x02200000) == (name, 0x02200041, 0, True), name
        twice = blob + sig
        assert check(name, twice, 0x02200000)[3] is False, name
        broken = bytearray(blob)
        broken[0x40 + 1] ^= 0xFF                       # a fixed byte changed
        assert check(name, bytes(broken), 0x02200000)[3] is False, name


# --- the field ----------------------------------------------------------------

def field(h: Hook, task_func=START_MENU_TASK, state=3, inhibit=0x180):
    fs = h.alloc(FIELD_SYSTEM_SIZE)
    ptr = h.alloc(4)
    h.w32(ptr, fs)
    h.w32(h.var("cfg_field_sys"), ptr)
    h.w32(h.var("cfg_start_menu_task"), START_MENU_TASK)
    tm = h.alloc(0x20)
    h.w32(fs + FS_TASKMAN, tm)
    h.w32(tm + TASK_FUNC, task_func)
    sm = h.alloc(SM_SIZE)
    h.w32(tm + TASK_ENV, sm)
    h.w16(sm + SM_STATE, state)
    h.w32(sm + SM_INHIBIT, inhibit)
    return fs, tm, sm


def test_field_walk_validates_every_link():
    h = Hook()
    fs, tm, sm = field(h)
    assert h.call("OneScreen_FieldSys") == fs
    assert h.call("OneScreen_TaskMan") == tm
    assert h.call("OneScreen_StartMenuEnv", tm) == sm
    assert h.call("OneScreen_MenuTaking") == 1
    h.w16(sm + SM_STATE, 6)
    assert h.call("OneScreen_MenuTaking") == 0
    h.w32(tm + TASK_FUNC, 0x0203C001)                # some other field task
    assert h.call("OneScreen_StartMenuEnv", tm) == 0
    h.w32(tm + TASK_FUNC, START_MENU_TASK)
    h.w32(tm + TASK_ENV, 0x023FFE00)                 # too close to the end of RAM
    assert h.call("OneScreen_StartMenuEnv", tm) == 0
    h.w32(fs + FS_TASKMAN, 0x04100000)
    assert h.call("OneScreen_TaskMan") == 0
    h.w32(h.r32(h.var("cfg_field_sys")), 0x027FFF00)
    assert h.call("OneScreen_FieldSys") == 0
    assert h.call("OneScreen_TaskMan") == 0


def test_menu_gone():
    h = Hook()
    _fs, tm, sm = field(h)
    h.w32(h.var("cfg_field_callback"), 0x021E5921)
    assert h.call("OneScreen_MenuGone") == 0         # the menu, taking input
    h.w16(sm + SM_STATE, 12)
    assert h.call("OneScreen_MenuGone") == 1         # its exit fade
    h.w32(tm + TASK_FUNC, 0x021F0001)                # an overlay task: a script
    assert h.call("OneScreen_MenuGone") == 1


# --- the X menu ---------------------------------------------------------------

def startmenu_archive(chat="CHAT", log="LOG"):
    msgs = [a("X")] * 40
    for i, word in {0: "POKEDEX", 1: "POKEMON", 2: "SAC", 4: "SAUVER",
                    5: "OPTIONS", 6: "RETOUR", 8: "ABANDON", 14: "POKEGEAR",
                    34: chat, 35: log}.items():
        msgs[i] = a(word)
    archive = [b""] * 300
    archive[labels.STARTMENU_MSGDATA_FILE] = gmm(msgs)
    archive[labels.TRAINER_MSGDATA_FILE] = gmm([a("DRESSEUR")] * 6)
    return archive


def put_startmenu(h: Hook, layouts_ok=True, **words):
    """Write a real _startmenu record, payload and plans into the blob."""
    base = blank_blob(h)
    record, payload, plans = labels._startmenu(
        fake_font(), startmenu_archive(**words), labels.BLOB_HEADER, layouts_ok)
    h.write(base + labels.SM_RECORD_OFF, record)
    h.write(base + labels.SM_PLANS_OFF, plans)
    h.write(base + labels.BLOB_HEADER, payload)
    strip_tiles = record[0x16]
    strips = [k for k, _c in labels._startmenu_labels(startmenu_archive(**words))]
    strips += [k for k, _c in labels._optional_labels(
        fake_font(), startmenu_archive(**words), record[0x17])]
    rows = struct.unpack_from("<16I", record, 0x30)
    return {"strip_tiles": strip_tiles, "strips": strips, "rows": rows,
            "blank": record[0x1D], "plans": plans}


def touch_menu(h: Hook, fs, layout=0, shown=(1,) * 7, selection=0, app_state=1):
    """The bottom-screen manager and TouchscreenMenuData behind FieldSystem."""
    h.w32(fs + 0x18, 3 if layout == 4 else 1)        # bottomScreenType
    outer = h.alloc(0x1C)
    h.w32(fs + FS_BOTTOM_TASK, outer)
    mgr = h.alloc(0x10)
    h.w32(outer + 0x10, mgr)
    app = h.alloc(0x1C)
    h.w8(mgr + 0, 0)                                  # appId: the touch menu
    h.w8(mgr + 1, app_state)
    h.w32(mgr + 4, app)
    h.w32(mgr + 8, fs)
    tsm = h.alloc(0x540)
    h.w32(app + 0x10, tsm)
    h.w32(tsm + 0x08, app)
    h.w32(tsm + 0x10, fs)
    h.w32(tsm + 0x14, selection)
    for i, flag in enumerate(shown):
        h.w8(tsm + 0x470 + 8 * i, flag)
    h.w32(tsm + 0x51C, (layout << 1) | 1)            # buttonsActive set too
    return mgr, tsm


def cells_drawn(h: Hook, info):
    """Read back what each of the eight cells shows: (strip key, highlighted)."""
    out = []
    for cell in range(8):
        entry = h.r16(info["rows"][cell * 2])
        tile, pal = entry & 0x3FF, entry >> 12
        strip = (tile - labels.SM_BASE_TILE) // info["strip_tiles"]
        key = None if strip == info["blank"] else info["strips"][strip]
        out.append((key, pal == labels.SM_PAL_HI))
    return out


def lit(cells):
    return [i for i, (_k, hi) in enumerate(cells) if hi]


def test_startmenu_plans():
    plans = labels._startmenu(fake_font(), startmenu_archive(), 0)[2]
    strips = [k for k, _c in labels._startmenu_labels(startmenu_archive())] + ["chat", "log"]
    rows = [[None if b == 0xFF else strips[b] for b in plans[i * 8:i * 8 + 8]]
            for i in range(7)]
    assert rows[0] == [0, 1, 2, 11, 3, 4, 5, None]              # normal
    assert rows[1] == [8, 0, 1, 2, 11, 3, 5, None]              # Safari
    assert rows[2] == [8, 0, 1, 11, 3, 5, None, None]           # Bug Contest
    assert rows[3] == rows[2]                                   # Pal Park
    assert rows[4] == ["chat", 0, 1, 2, "log", 3, 5, None]      # Union Room
    assert rows[5] == [1, 2, 3, 5, None, None, None, None]      # Colosseum
    assert rows[6] == [1, 3, 5, None, None, None, None, None]   # Tower room
    unchecked = labels._startmenu(fake_font(), startmenu_archive(), 0, False)[2]
    assert unchecked[:8] == plans[:8]
    for i in range(1, 7):
        assert unchecked[i * 8] == labels.SM_PLAN_UNDRAWABLE
    wide = labels._startmenu(fake_font(), startmenu_archive(chat="W" * 40), 0)[2]
    assert wide[4 * 8] == labels.SM_PLAN_UNDRAWABLE              # CHAT will not fit
    assert wide[1 * 8] != labels.SM_PLAN_UNDRAWABLE


def test_startmenu_draws_the_live_layout():
    h = Hook()
    info = put_startmenu(h)
    fs, _tm, _sm = field(h, inhibit=0x090)           # Safari's inhibit flags
    touch_menu(h, fs, layout=1, selection=0)
    assert h.call("OneScreen_StartMenu") == 1
    got = cells_drawn(h, info)
    assert [k for k, _ in got] == [8, 0, 1, 2, 11, 3, 5, None], got
    assert lit(got) == [0]                           # RETIRE selected
    # early-game normal menu: only the bag and the right column exist
    h = Hook()
    info = put_startmenu(h)
    fs, _tm, _sm = field(h)
    touch_menu(h, fs, layout=0, shown=(0, 0, 1, 0, 1, 1, 1), selection=5)
    assert h.call("OneScreen_StartMenu") == 1
    got = cells_drawn(h, info)
    assert [k for k, _ in got] == [None, None, 2, None, 3, 4, 5, None], got
    assert lit(got) == [5]


def test_startmenu_union_room():
    h = Hook()
    info = put_startmenu(h)
    fs, _tm, _sm = field(h, inhibit=0x110)
    touch_menu(h, fs, layout=4, selection=4)
    assert h.call("OneScreen_StartMenu") == 1
    got = cells_drawn(h, info)
    assert [k for k, _ in got] == ["chat", 0, 1, 2, "log", 3, 5, None], got
    assert lit(got) == [4]
    h = Hook()
    put_startmenu(h, chat="W" * 40)                  # CHAT too wide: swap instead
    fs, _tm, _sm = field(h, inhibit=0x110)
    touch_menu(h, fs, layout=4)
    assert h.call("OneScreen_StartMenu") == 0


def test_startmenu_fallback_when_touch_app_is_switching():
    h = Hook()
    info = put_startmenu(h)
    fs, _tm, _sm = field(h, inhibit=0x180)
    h.w8(fs + FS_START_MENU_CURSOR, 2)               # the third entry you own
    touch_menu(h, fs, layout=0, app_state=2)         # mid-switch: not trusted
    assert h.call("OneScreen_StartMenu") == 1
    got = cells_drawn(h, info)
    assert [k for k, _ in got] == [0, 1, 2, 11, 3, 4, 5, None], got
    assert lit(got) == [2]
    h = Hook()
    put_startmenu(h)
    fs, _tm, _sm = field(h, inhibit=0x090)           # Safari, no live data
    touch_menu(h, fs, layout=1, app_state=2)
    assert h.call("OneScreen_StartMenu") == 0
    for inhibit in (0x110, 0x391, 0x395, 0x094):     # never the normal grid
        h = Hook()
        put_startmenu(h)
        fs, _tm, _sm = field(h, inhibit=inhibit)
        assert h.call("OneScreen_StartMenu") == 0, hex(inhibit)


def test_touch_menu_walk():
    h = Hook()
    fs, _tm, _sm = field(h)
    mgr, tsm = touch_menu(h, fs)
    assert h.call("OneScreen_TouchMenu", fs) == tsm
    h.w8(mgr + 0, 3)                                 # the choice menu is up instead
    assert h.call("OneScreen_TouchMenu", fs) == 0
    h.w8(mgr + 0, 0)
    h.w32(tsm + 0x10, fs + 4)                        # someone else's
    assert h.call("OneScreen_TouchMenu", fs) == 0
    h.w32(tsm + 0x10, fs)
    h.w32(fs + 0x18, 6)                              # a photo viewer's task
    assert h.call("OneScreen_TouchMenu", fs) == 0
    h.w32(fs + 0x18, 1)
    h.w32(mgr + 8, 0)
    assert h.call("OneScreen_TouchMenu", fs) == 0


def test_startmenu_layout_must_agree_with_inhibit_flags():
    h = Hook()
    info = put_startmenu(h)
    fs, _tm, _sm = field(h, inhibit=0x180)            # the start menu says normal
    touch_menu(h, fs, layout=1)                        # a stale Safari touch app
    assert h.call("OneScreen_StartMenu") == 1          # falls back to the flags
    assert [k for k, _ in cells_drawn(h, info)] == [0, 1, 2, 11, 3, 4, 5, None]
    h = Hook()
    put_startmenu(h)
    fs, _tm, _sm = field(h, inhibit=0x094)            # Bug Contest flags
    touch_menu(h, fs, layout=0)                        # with a normal touch app
    assert h.call("OneScreen_StartMenu") == 0


POWCNT1, SWAP_BIT = 0x04000304, 0x8000


def poll_in_field(h: Hook, fs):
    """Run OneScreen_Poll as if a frame passed in the overworld, no keys."""
    gsys = h.alloc(0x80)
    field_cb = 0x021E5921
    h.w32(gsys, field_cb)
    h.w32(h.var("cfg_app_callback"), gsys)
    h.w32(h.var("cfg_field_callback"), field_cb)
    h.w32(h.var("pad_held"), 0)
    h.w32(h.var("pad_new"), 0)
    h.w32(fs + FS_SAVED_APP_ID, 0)
    h.call("OneScreen_Poll")
    return h.r16(POWCNT1) & SWAP_BIT


def test_retire_keeps_the_world_on_top():
    """RETIRE jumps from the menu to the script runner, an ARM9 task. The panel
    goes, and the world stays up for the script's question."""
    h = Hook()
    put_startmenu(h)
    fs, tm, _sm = field(h, inhibit=0x090)
    touch_menu(h, fs, layout=1)
    h.w32(h.var("menu_swapped"), 1)
    h.w32(tm + TASK_FUNC, 0x0203F001)                  # not Task_StartMenu
    h.w16(POWCNT1, 0)
    assert poll_in_field(h, fs) == SWAP_BIT            # engine A, the world, on top
    assert h.r32(h.var("sm_shown")) == 0


def test_save_box_still_takes_the_screen():
    h = Hook()
    put_startmenu(h)
    fs, _tm, sm = field(h)
    touch_menu(h, fs)
    h.w32(h.var("menu_swapped"), 1)
    h.w16(sm + SM_STATE, 6)                            # START_MENU_STATE_SAVE
    h.w16(POWCNT1, SWAP_BIT)
    assert poll_in_field(h, fs) == 0                   # engine B, the save box
    h.w16(sm + SM_STATE, 3)                            # back to the menu
    assert poll_in_field(h, fs) == SWAP_BIT
    assert h.r32(h.var("sm_shown")) == 1


# --- native top-screen lists ---------------------------------------------------

CHOICE_STATE, CHOICE_RESULT, CHOICE_MENU, CHOICE_FS = 0x00, 0x04, 0x0C, 0x24
SM_X, SM_Y, SM_FLAGS, SM_RET, SM_ITEMS = 0x98, 0x99, 0x97, 0xA0, 0x1C4
FS_BGCONFIG, BG3_BUFFER = 0x08, 0x8C
LIST_SCREEN_BASE = 16                                 # in the list record
STUB_ORIG, STUB_OPEN, STUB_WIDTH, STUB_SETUP = 0x02000101, 0x02000111, 0x02000121, 0x02000131
STUB_TUTOR = 0x02000141
STRING_MAGIC = 0xB6F8D2EC
LF, SP, CTRL, EOS = 0xE000, 0x01DE, 0xFFFE, 0xFFFF
GLYPH = 6                                             # every test glyph is 6 px wide


def cursor_x(x):
    return [CTRL, 0x0203, 1, x]


def string_width(h: Hook, font, s, spacing):
    """FontID_String_GetWidth as src/font.c and src/font_data.c have it: String_c_str
    (which checks the magic), then GetStringWidth - the glyph widths up to the EOS,
    control codes skipped by their own argument count."""
    assert font == 0 and spacing == 0, (font, spacing)
    assert h.r32(s + 4) == STRING_MAGIC, "String_c_str would assert"
    i, total = s + 8, 0
    while True:
        c = h.r16(i)
        if c == EOS:
            return total
        if c == CTRL:
            i += 2 * (3 + h.r16(i + 4))
            continue
        total += GLYPH
        i += 2


def entry(h: Hook, menu, i):
    """Entry i's String as the hook left it: (size, codes up to the EOS)."""
    s = h.r32(menu + SM_STRBUFS + 4 * i)
    size = h.r16(s + 2)
    data = [h.r16(s + 8 + 2 * k) for k in range(size + 1)]
    assert data[-1] == EOS, data
    return size, data[:-1]


def native_lists(h: Hook, entries, values=None, x=1, y=1, choice_state=1):
    """A script mid-MenuInit: the choice app up and idle, a ScriptMenu built,
    and MAIN_3's tilemap buffer empty."""
    fs, _tm, _sm = field(h, task_func=0)
    h.w32(fs + 0x18, 1)
    bg = h.alloc(0x100)
    h.w32(fs + FS_BGCONFIG, bg)
    tilemap = h.alloc(32 * 32 * 2)
    h.w32(bg + BG3_BUFFER, tilemap)
    outer = h.alloc(0x1C)
    h.w32(fs + FS_BOTTOM_TASK, outer)
    mgr = h.alloc(0x10)
    h.w32(outer + 0x10, mgr)
    app = h.alloc(0x1C)
    h.w8(mgr + 0, 3)                                  # the choice menu
    h.w8(mgr + 1, 1)
    h.w32(mgr + 4, app)
    h.w32(mgr + 8, fs)
    ctrl = h.alloc(0x3A4)
    h.w32(app + 0x10, ctrl)
    h.w32(ctrl + CHOICE_STATE, choice_state)
    h.w32(ctrl + CHOICE_FS, fs)
    menu = script_menu(h, entries)
    h.w32(ctrl + CHOICE_MENU, menu)
    for i, v in enumerate(values or range(len(entries))):
        h.w32(menu + SM_ITEMS + 8 * i, h.r32(menu + SM_STRBUFS + 4 * i))
        h.w32(menu + SM_ITEMS + 8 * i + 4, v)
    var = h.alloc(4)
    h.w16(var, 0x1234)
    h.w32(menu + SM_RET, var)
    h.w8(menu + SM_X, x)
    h.w8(menu + SM_Y, y)
    calls = []
    h.stub(STUB_ORIG, lambda hk, *r: calls.append(("orig", r[0])) or 0x55)
    h.stub(STUB_OPEN, lambda hk, *r: calls.append(("open", r[0], r[1])) or 0)
    h.stub(STUB_WIDTH, lambda hk, *r: string_width(hk, *r[:3]))
    h.stub(STUB_SETUP, lambda hk, *r: calls.append(("setup", r[0], r[1])) or 0)
    for name, addr in (("cfg_menu_exec_orig", STUB_ORIG), ("cfg_open_list", STUB_OPEN),
                       ("cfg_string_width", STUB_WIDTH),
                       ("cfg_setup_native", STUB_SETUP)):
        h.w32(h.var(name), addr)
    ctx = h.alloc(0x100)
    return {"ctx": ctx, "menu": menu, "var": var, "calls": calls, "ctrl": ctrl,
            "bg": bg, "tilemap": tilemap, "fs": fs}


def put_window(h: Hook, tilemap, x, y, w, rows, first_tile, palette=13):
    """A window as the game draws one on MAIN_3: its own character tiles, one per
    cell from first_tile, framed by the user frame from 0x3D9."""
    entry = lambda tile: (palette << 12) | tile
    for r in range(rows):
        for c in range(w):
            h.w16(tilemap + 2 * (32 * (y + r) + x + c), entry(first_tile + r * w + c))
    for c in range(x - 1, x + w + 1):
        h.w16(tilemap + 2 * (32 * (y - 1) + c), entry(0x3D9))
        h.w16(tilemap + 2 * (32 * (y + rows) + c), entry(0x3D9))
    for r in range(y, y + rows):
        h.w16(tilemap + 2 * (32 * r + x - 1), entry(0x3DA))
        h.w16(tilemap + 2 * (32 * r + x + w), entry(0x3DA))


def wide(px):
    """A plain entry whose text ends `px` pixels into the window (item_X is 12)."""
    assert (px - 12) % GLYPH == 0
    return codes("A" * ((px - 12) // GLYPH))


def opened(t):
    """The tiles across the hook opened its window with, or None for the touch list."""
    for c in t["calls"]:
        if c[0] == "open":
            return c[2]
    return None


def test_menu_exec_hands_unknown_lists_to_the_game():
    h = Hook()
    put_list_menus(h, [([codes("ACHETER"), codes("VENDRE"), codes("QUITTER")], 0)])
    t = native_lists(h, [codes("OUI"), codes("NON"), codes("PEUT-ETRE")],
                     values=[7, 8, 9])
    assert h.call("OneScreen_MenuExec", t["ctx"]) == 1
    wait = h.var("OneScreen_WaitList") | 1
    # PEUT-ETRE: 12 + 9 * 6 = 66 px, nine tiles - what ShowList would have opened
    assert t["calls"] == [("open", t["menu"], 9), ("setup", t["ctx"], wait)], t["calls"]
    assert h.r16(t["var"]) == 0xEEEE
    assert h.r32(h.var("wl_last")) == 9
    # the wait: nothing yet, then a pick, then B standing for the last entry
    assert h.call("OneScreen_WaitList", t["ctx"]) == 0
    h.w16(t["var"], 8)
    assert h.call("OneScreen_WaitList", t["ctx"]) == 1 and h.r16(t["var"]) == 8
    h.w16(t["var"], 0xFFFE)
    assert h.call("OneScreen_WaitList", t["ctx"]) == 1 and h.r16(t["var"]) == 9


def controller_slot(h: Hook, t):
    """Where the choice app's SysTask keeps its data pointer, the controller."""
    mgr = h.r32(h.r32(t["fs"] + FS_BOTTOM_TASK) + 0x10)
    return h.r32(mgr + 4) + 0x10


def twenty_nine(h: Hook, t):
    """Every one of the 28 slots filled, and a 29th entry that would otherwise pass
    for one: the words past strbufs[] and items[] (msgData, msgIds) made to hold a
    String as well."""
    for i in range(29):
        if h.r32(t["menu"] + SM_STRBUFS + 4 * i) == 0:
            s = h.string(codes("Z"))
            h.w32(t["menu"] + SM_STRBUFS + 4 * i, s)
            h.w32(t["menu"] + SM_ITEMS + 8 * i, s)
    h.w8(t["menu"] + SM_COUNT, 29)


def test_menu_exec_keeps_what_it_should_not_touch():
    shop = [codes("ACHETER"), codes("VENDRE"), codes("QUITTER")]
    cases = {
        "recognised": dict(entries=shop),
        "control code": dict(entries=[codes("PRIX") + [CTRL, 0x0100, 1, 0], codes("NON")]),
        "not idle": dict(entries=[codes("A"), codes("B")], choice_state=7),
    }
    for name, kw in cases.items():
        h = Hook()
        put_list_menus(h, [(shop, 0)])
        t = native_lists(h, **kw)
        assert h.call("OneScreen_MenuExec", t["ctx"]) == 0x55, name
        assert t["calls"] == [("orig", t["ctx"])], (name, t["calls"])
    for name in ("cfg_open_list", "cfg_string_width", "cfg_setup_native"):
        h = Hook()
        put_list_menus(h, [(shop, 0)])
        t = native_lists(h, [codes("A"), codes("B")])
        h.w32(h.var(name), 0)                         # the patcher found nothing
        assert h.call("OneScreen_MenuExec", t["ctx"]) == 0x55, name
        assert t["calls"] == [("orig", t["ctx"])], (name, t["calls"])
    tampered = {
        "another field's controller":
            lambda h, t: h.w32(t["ctrl"] + CHOICE_FS, h.alloc(FIELD_SYSTEM_SIZE)),
        "no field": lambda h, t: h.w32(h.var("cfg_field_sys"), 0),
        "controller off the end of RAM": lambda h, t: h.w32(controller_slot(h, t), 0x023FFE00),
        "controller at the IPC FIFO": lambda h, t: h.w32(controller_slot(h, t), 0x04100000),
        "menu off the end of RAM": lambda h, t: h.w32(t["ctrl"] + CHOICE_MENU, 0x023FFF00),
        "menu at the IPC FIFO": lambda h, t: h.w32(t["ctrl"] + CHOICE_MENU, 0x04100000),
        "no entries": lambda h, t: h.w8(t["menu"] + SM_COUNT, 0),
        "too many entries": twenty_nine,
        "result var below RAM": lambda h, t: h.w32(t["menu"] + SM_RET, 0x01FFFFFE),
        "result var past RAM": lambda h, t: h.w32(t["menu"] + SM_RET, 0x023FFFFE),
        "result var odd": lambda h, t: h.w32(t["menu"] + SM_RET, 0x02100001),
    }
    for name, fn in tampered.items():
        h = Hook()
        put_list_menus(h, [(shop, 0)])
        t = native_lists(h, [codes("A"), codes("B")])
        fn(h, t)
        assert h.call("OneScreen_MenuExec", t["ctx"]) == 0x55, name
        assert t["calls"] == [("orig", t["ctx"])], (name, t["calls"])


def test_menu_exec_keeps_the_window_on_screen():
    for x, width_px, want in ((1, 60, 1), (24, 102, 18), (21, 60, 21), (12, 300, 1)):
        h = Hook()
        put_list_menus(h, [([codes("Z")], 0)])
        t = native_lists(h, [wide(width_px), codes("B")], x=x)
        h.call("OneScreen_MenuExec", t["ctx"])
        assert h.r8(t["menu"] + SM_X) == want, (x, width_px, h.r8(t["menu"] + SM_X))
    # anchored: moved left and up by its own size, as ScriptMenu_ShowList does
    h = Hook()
    put_list_menus(h, [([codes("Z")], 0)])
    t = native_lists(h, [wide(102), codes("B")], x=24, y=20)
    h.w8(t["menu"] + SM_FLAGS, 0xC0)
    h.call("OneScreen_MenuExec", t["ctx"])
    assert opened(t) == 13
    assert (h.r8(t["menu"] + SM_X), h.r8(t["menu"] + SM_Y)) == (11, 16)
    h = Hook()
    put_list_menus(h, [([codes("Z")], 0)])
    t = native_lists(h, [codes("A")] * 10, x=5, y=18)
    h.w8(t["menu"] + SM_FLAGS, 0x80)                  # ten entries: a page of 16 rows
    h.call("OneScreen_MenuExec", t["ctx"])
    assert (h.r8(t["menu"] + SM_X), h.r8(t["menu"] + SM_Y)) == (5, 2)


def test_menu_exec_leaves_room_for_script_windows():
    """The top-screen list goes where the script said, on MAIN_3. A window the
    script already has there - Mom's savings box - keeps the touch list."""
    a_b = [wide(60), codes("B")]                      # 60 px: 8 tiles x 4 rows

    def run(setup, x=1, y=1, flags=0):
        h = Hook()
        head = put_list_menus(h, [([codes("Z")], 0)])
        t = native_lists(h, a_b, x=x, y=y)
        t["head"] = head
        h.w8(t["menu"] + SM_FLAGS, flags)
        setup(h, t)
        h.call("OneScreen_MenuExec", t["ctx"])
        return t["calls"][0][0]

    nothing = lambda h, t: None
    assert run(nothing) == "open"
    # ShowSavingsBox 1,1: 16x8 at (1, 1) from tile 1, then a list at (1, 1)
    savings = lambda h, t: put_window(h, t["tilemap"], 1, 1, 16, 8, 1)
    assert run(savings) == "orig"
    # the money box, 10x4 from tile 1, across the screen: no overlap, no shared tiles
    money = lambda h, t: put_window(h, t["tilemap"], 20, 1, 10, 4, 1)
    assert run(money) == "open"
    # the dialogue box below: tiles from 0x237, rows 19-22, framed 18-23
    talk = lambda h, t: put_window(h, t["tilemap"], 2, 19, 27, 4, 0x237)
    assert run(talk) == "open"
    # frame to frame is still a collision: the list's frame is column 9
    assert run(lambda h, t: put_window(h, t["tilemap"], 10, 1, 4, 2, 0x300)) == "orig"
    assert run(lambda h, t: put_window(h, t["tilemap"], 11, 1, 4, 2, 0x300)) == "open"
    # far away, but holding a tile the list's window would be given
    assert run(lambda h, t: h.w16(t["tilemap"] + 2 * (32 * 15 + 28), 0x3D + 31)) == "orig"
    assert run(lambda h, t: h.w16(t["tilemap"] + 2 * (32 * 15 + 28), 0x3D + 32)) == "open"
    # anchored bottom-right: the list is moved up and left by its own size first
    corner = lambda h, t: put_window(h, t["tilemap"], 2, 2, 4, 2, 0x300)
    assert run(corner, x=17, y=11, flags=0xC0) == "open"     # lands at (9, 7)
    assert run(corner, x=15, y=9, flags=0xC0) == "orig"      # lands at (7, 5)
    # no layer to look at: keep the touch list
    assert run(lambda h, t: h.w32(t["bg"] + BG3_BUFFER, 0)) == "orig"
    # a panel of ours from the menu before is ours to clear, not in the way
    def held_panel(h, t):
        h.w32(h.var("list_drawn"), 1)
        h.w32(h.var("list_hold"), 3)
        h.w32(t["head"] + LIST_SCREEN_BASE, 0x06000000)
        h.w32(h.var("list_rect"), 0 | 14 << 8 | 8 << 16)
        put_window(h, t["tilemap"], 1, 1, 12, 6, 0x3D)
    assert run(held_panel) == "open"


# --- formatted entries --------------------------------------------------------

def show(entries, **kw):
    """Run OneScreen_MenuExec on a list of these entries; the test state back."""
    h = Hook()
    put_list_menus(h, [([codes("Z")], 0)])
    t = native_lists(h, entries, **kw)
    t["h"] = h
    t["ret"] = h.call("OneScreen_MenuExec", t["ctx"])
    return t


def test_format_measures_to_the_cursor_x_column():
    """The drink machines: GetListItemsWidth skips the CURSOR_X and counts
    WATER$200 as nine characters, 66 px. The price really ends at 80 + 24."""
    water = codes("WATER") + cursor_x(80) + codes("$200")
    t = show([water, codes("SODA") + cursor_x(80) + codes("$300"), codes("NO THANKS")])
    assert t["ret"] == 1 and opened(t) == 13, t["calls"]       # 104 px
    assert entry(t["h"], t["menu"], 0) == (len(water), water)  # left as it was
    # a column further right than the names reach widens the window with it
    t = show([codes("AB") + cursor_x(150) + codes("C"), codes("D")])
    assert opened(t) == 20                                     # 156 px
    # and two columns in one entry: the pen follows both
    t = show([codes("A") + cursor_x(40) + codes("BB") + cursor_x(90) + codes("CCC")])
    assert opened(t) == 14                                     # 90 + 18 = 108 px


def test_format_turns_down_a_column_over_its_text():
    """A translation longer than the column it sits before would print over itself."""
    long = codes("VERYLONGNAME") + cursor_x(80) + codes("$1")  # 12 + 72 = 84 > 80
    t = show([long, codes("NO")])
    assert t["ret"] == 0x55 and t["calls"] == [("orig", t["ctx"])]
    assert entry(t["h"], t["menu"], 0) == (len(long), long)
    t = show([codes("VERYLONGNAM") + cursor_x(80) + codes("$1"), codes("NO")])
    assert opened(t) == 12                                     # 12 + 66 = 78: fits


def test_format_folds_a_wrapped_line_onto_one():
    """'DEPOSIT\\nPOKEMON' lays out in two lines on the touch screen; a ListMenu
    row is one line high. A wrapped line becomes a space."""
    t = show([codes("DEPOSIT") + [LF] + codes("POKEMON"),
              codes("MOVE") + [LF, SP] + codes("POKEMON"),
              codes("SEE") + [LF, SP, SP] + codes("YA")])
    h, menu = t["h"], t["menu"]
    assert t["ret"] == 1
    assert entry(h, menu, 0) == (15, codes("DEPOSIT") + [SP] + codes("POKEMON"))
    assert entry(h, menu, 1) == (12, codes("MOVE") + [SP] + codes("POKEMON"))
    assert entry(h, menu, 2) == (6, codes("SEE") + [SP] + codes("YA"))
    assert opened(t) == 13                                     # 12 + 15 * 6 = 102 px
    # the mulch shop: a CURSOR_X then a break - the price lands in the column
    mulch = codes("GROWTH") + cursor_x(90) + [LF] + codes("$200")
    t = show([mulch, codes("NO")])
    assert entry(t["h"], t["menu"], 0)[1] == codes("GROWTH") + cursor_x(90) + [SP] + codes("$200")
    assert opened(t) == 15                                     # 90 + 5 * 6 = 120 px


def test_format_lines_up_indented_second_lines():
    """The move tutors' '{move}\\n           {cost} BP': an indented second line
    becomes a column shared by the whole list, FMT_GAP past the longest move."""
    pad = [SP] * 11
    t = show([codes("DIVE") + [LF] + pad + codes("40 BP"),
              codes("MUD-SLAP") + [LF] + pad + codes("32 BP"),
              codes("QUIT")])
    h, menu = t["h"], t["menu"]
    col = 12 + 8 * GLYPH + 8                                   # 68
    assert entry(h, menu, 0) == (13, codes("DIVE") + cursor_x(col) + codes("40 BP"))
    assert entry(h, menu, 1) == (17, codes("MUD-SLAP") + cursor_x(col) + codes("32 BP"))
    assert entry(h, menu, 2) == (4, codes("QUIT"))
    assert opened(t) == 13                                     # 68 + 30 = 98 px
    # three spaces are an indent; two are a wrapped line with stray spaces
    t = show([codes("A") + [LF, SP, SP, SP] + codes("B")])
    assert entry(t["h"], t["menu"], 0)[1] == codes("A") + cursor_x(12 + 6 + 8) + codes("B")
    t = show([codes("A") + [LF, SP, SP] + codes("B")])
    assert entry(t["h"], t["menu"], 0)[1] == codes("A") + [SP] + codes("B")
    # narrow spaces count as spaces
    t = show([codes("A") + [LF] + [0x01E2] * 3 + codes("B")])
    assert entry(t["h"], t["menu"], 0)[1] == codes("A") + cursor_x(26) + codes("B")


def test_format_turns_down_what_it_cannot_lay_out():
    bad = {
        "two breaks": codes("A") + [LF] + codes("B") + [LF] + codes("C"),
        "colour": [CTRL, 0xFF00, 1, 2] + codes("RED"),
        "focus icon": codes("A") + [CTRL, 0x0200, 1, 0],
        "centring": [CTRL, 0x0205, 0] + codes("A"),
        "cursor_y, shaped like a column": codes("A") + [CTRL, 0x0204, 1, 100] + codes("B"),
        "a stray code before a column's body": codes("A") + [0xF000, 0x0203, 1, 100],
        "cursor_x, no x": codes("A") + [CTRL, 0x0203, 0] + codes("B"),
        "arguments past the end": codes("A") + [CTRL, 0x0203, 5, 80],
        "cut-off control": codes("A") + [CTRL, 0x0203],
        "skip code": codes("A") + [0xF0FD, 1] + codes("B"),
        "an EOS inside": codes("A") + [EOS] + codes("B"),
    }
    for name, codes_ in bad.items():
        t = show([codes_, codes("NO")])
        assert t["ret"] == 0x55 and t["calls"] == [("orig", t["ctx"])], (name, t["calls"])
        assert entry(t["h"], t["menu"], 0) == (len(codes_), codes_), name

    def tamper(fn):
        h = Hook()
        put_list_menus(h, [([codes("Z")], 0)])
        t = native_lists(h, [codes("A") + [LF] + codes("B"), codes("NO")])
        fn(h, t, h.r32(t["menu"] + SM_STRBUFS))
        return h.call("OneScreen_MenuExec", t["ctx"]), t

    for name, fn in {
        "size past maxsize": lambda h, t, s: h.w16(s, 2),
        "longer than String_New(80)": lambda h, t, s: h.w16(s, 81),
        "entry pointer off the end of RAM": lambda h, t, s: (
            h.w32(t["menu"] + SM_STRBUFS, 0x023FFFFC), h.w32(t["menu"] + SM_ITEMS, 0x023FFFFC)),
        "entry pointer at the IPC FIFO": lambda h, t, s: (
            h.w32(t["menu"] + SM_STRBUFS, 0x04100000), h.w32(t["menu"] + SM_ITEMS, 0x04100000)),
        "characters past the end of RAM": lambda h, t, s: (
            h.write(0x023FFFF0, struct.pack("<HHI", 40, 40, STRING_MAGIC) + bytes(8)),
            h.w32(t["menu"] + SM_STRBUFS, 0x023FFFF0), h.w32(t["menu"] + SM_ITEMS, 0x023FFFF0)),
        "items[] not the strbufs": lambda h, t, s: h.w32(t["menu"] + SM_ITEMS, h.string(codes("X"))),
    }.items():
        ret, t = tamper(fn)
        assert ret == 0x55 and t["calls"] == [("orig", t["ctx"])], (name, t["calls"])
    ret, t = tamper(lambda h, t, s: h.w16(s, 80))     # a maxsize of 80 is fine
    assert ret == 1


def test_format_changes_nothing_unless_the_list_opens():
    """The fold is measured on a copy, and written back only once the room check
    has passed: a list that falls back shows the touch list its own text."""
    two = codes("DEPOSIT") + [LF] + codes("POKEMON")
    tutor = codes("DIVE") + [LF] + [SP] * 11 + codes("40 BP")
    h = Hook()
    put_list_menus(h, [([codes("Z")], 0)])
    t = native_lists(h, [two, tutor])
    put_window(h, t["tilemap"], 1, 1, 16, 8, 1)       # the savings box
    assert h.call("OneScreen_MenuExec", t["ctx"]) == 0x55
    assert entry(h, t["menu"], 0) == (len(two), two)
    assert entry(h, t["menu"], 1) == (len(tutor), tutor)
    assert h.r8(t["menu"] + SM_X) == 1 and h.r16(t["var"]) == 0x1234


# --- the move tutors (command 653) -------------------------------------------

def tutor(h: Hook, entries, values, before_state=1, after=None):
    """The choice app idle, then ScrCmd_MoveTutorChooseMove: it has built `entries`
    (in the controller's menu slot, as FieldSystem_GetTouchscreenChoiceMenuList
    hands it over) and asks for the touch list - state 7 and its result var."""
    t = native_lists(h, entries, values=values, choice_state=before_state)
    prev = h.alloc(4)
    h.w32(t["ctrl"] + CHOICE_RESULT, prev)
    t["prev"] = prev

    def real(hk, ctx, *_):
        t["calls"].append(("tutor", ctx))
        hk.w32(t["ctrl"] + CHOICE_STATE, 7)
        hk.w32(t["ctrl"] + CHOICE_RESULT, t["var"])
        if after:
            after(hk, t)
        return 1
    h.stub(STUB_TUTOR, real)
    h.w32(h.var("cfg_tutor_exec_orig"), STUB_TUTOR)
    return t


TUTOR = [codes("DIVE") + [LF] + [SP] * 11 + codes("40 BP"),
         codes("MUD-SLAP") + [LF] + [SP] * 11 + codes("32 BP"),
         codes("ICY WIND") + [LF] + [SP] * 11 + codes("48 BP"),
         codes("NEXT"), codes("QUIT")]
TUTOR_VALUES = [291, 189, 196, 0xFFFD, 0xFFFE]


def test_tutor_list_opens_on_top():
    h = Hook()
    t = tutor(h, TUTOR, TUTOR_VALUES)
    assert h.call("OneScreen_TutorExec", t["ctx"]) == 1
    wait = h.var("OneScreen_WaitList") | 1
    assert t["calls"] == [("tutor", t["ctx"]), ("open", t["menu"], 13),
                          ("setup", t["ctx"], wait)], t["calls"]
    # the touch list taken back before its task could see state 7
    assert h.r32(t["ctrl"] + CHOICE_STATE) == 1
    assert h.r32(t["ctrl"] + CHOICE_RESULT) == t["prev"]
    assert entry(h, t["menu"], 2)[1] == codes("ICY WIND") + cursor_x(68) + codes("48 BP")
    assert h.r16(t["var"]) == 0xEEEE
    assert h.r32(h.var("wl_last")) == 0xFFFE
    # B is QUIT; a move is a move
    h.w16(t["var"], 0xFFFE)
    assert h.call("OneScreen_WaitList", t["ctx"]) == 1 and h.r16(t["var"]) == 0xFFFE
    h.w16(t["var"], 189)
    assert h.call("OneScreen_WaitList", t["ctx"]) == 1 and h.r16(t["var"]) == 189


def test_tutor_keeps_the_touch_list_when_it_cannot_vouch():
    def other_field(h, t):
        h.w32(t["ctrl"] + CHOICE_FS, h.alloc(FIELD_SYSTEM_SIZE))

    cases = {
        "not idle before": dict(before_state=3),
        "another field's controller": dict(before_hook=other_field),
        "no field": dict(before_hook=lambda h, t: h.w32(h.var("cfg_field_sys"), 0)),
        "no list asked for": dict(after=lambda h, t: h.w32(t["ctrl"] + CHOICE_STATE, 3)),
        "another result var": dict(after=lambda h, t: h.w32(t["ctrl"] + CHOICE_RESULT, t["prev"])),
        "controller at the IPC FIFO": dict(before_hook=lambda h, t: h.w32(controller_slot(h, t), 0x04100000)),
        "menu off the end of RAM": dict(after=lambda h, t: h.w32(t["ctrl"] + CHOICE_MENU, 0x023FFF00)),
        "menu at the IPC FIFO": dict(after=lambda h, t: h.w32(t["ctrl"] + CHOICE_MENU, 0x04100000)),
        "no entries": dict(after=lambda h, t: h.w8(t["menu"] + SM_COUNT, 0)),
        "too many entries": dict(after=twenty_nine),
        "the savings box": dict(after=lambda h, t: put_window(h, t["tilemap"], 1, 1, 16, 8, 1)),
        "no window function": dict(before_hook=lambda h, t: h.w32(h.var("cfg_open_list"), 0)),
        "an entry it cannot fold": dict(entries=[codes("A") + [LF, LF]] + TUTOR[1:]),
    }
    for name, kw in cases.items():
        h = Hook()
        before_hook = kw.pop("before_hook", None)
        entries = kw.pop("entries", TUTOR)
        t = tutor(h, entries, TUTOR_VALUES, **kw)
        if before_hook:
            before_hook(h, t)
        assert h.call("OneScreen_TutorExec", t["ctx"]) == 1, name
        assert t["calls"] == [("tutor", t["ctx"])], (name, t["calls"])
        # whatever the real command left is left alone: the touch list goes up
        if name not in ("no list asked for",):
            assert h.r32(t["ctrl"] + CHOICE_STATE) == 7, name
        if name not in ("another result var",):
            assert h.r32(t["ctrl"] + CHOICE_RESULT) == t["var"], name
        assert h.r16(t["var"]) == 0x1234, name
        for i, e in enumerate(entries):
            assert entry(h, t["menu"], i) == (len(e), e), (name, i)


# --- the patcher's script-table finder ------------------------------------------

def assemble(src: str, base: int, defs: dict) -> bytes:
    """Assemble Thumb source at `base` with absolute symbols, return the bytes."""
    import shutil
    import subprocess
    import tempfile
    tools = {t: shutil.which(f"arm-none-eabi-{t}") for t in ("as", "ld", "objcopy")}
    if None in tools.values():
        raise RuntimeError("arm-none-eabi binutils are needed for this test")
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        # Targets are declared Thumb functions, so the linker calls them with a
        # plain BL rather than routing through an interworking veneer.
        decls = "".join(f".thumb_set {k}, {v & ~1:#x}\n" for k, v in defs.items())
        (d / "a.s").write_text(".syntax unified\n.thumb\n.text\n.balign 4\n" + decls + src)
        subprocess.run([tools["as"], "-mcpu=arm946e-s", "-mthumb", "-o", d / "a.o",
                        d / "a.s"], check=True)
        subprocess.run([tools["ld"], f"-Ttext={base:#x}", "-o", d / "a.elf",
                        d / "a.o"], check=True, capture_output=True)
        subprocess.run([tools["objcopy"], "-O", "binary", d / "a.elf", d / "a.bin"],
                       check=True)
        return (d / "a.bin").read_bytes()


class FakeOverlay:
    def __init__(self, ram, data):
        self.ramAddress, self.data = ram, data


def fake_rom_for_lists(break_check=None):
    """An ARM9 and an overlay 1 holding the functions resolve_native_lists walks,
    each written to the shape pret's matching disassembly gives the retail one.
    `break_check` damages one of them, the way a different build might."""
    from onescreen import regions
    b = break_check
    ov1_base = 0x021E5900
    defs = {"GetList": ov1_base + 0x11, "SetState": ov1_base + 0x21,
            "SetCb": ov1_base + 0x31, "ShowList": ov1_base + 0x101,
            "OpenList": ov1_base + 0x201, "Width": ov1_base + 0x301,
            "Tutor": ov1_base + 0x401, "Wait": ov1_base + 0x501,
            "Create": ov1_base + 0x41, "AddItem": ov1_base + 0x51, "Frame": ov1_base + 0x61,
            "GetVar": 0x02000301, "Setup": 0x02000311, "Attr": 0x02000321,
            "AssertFail": 0x02000331, "GetStringWidth": 0x02000341,
            "CStr": 0x02002001, "StrWidth": 0x02002F31}
    ov1 = bytearray(0x600)

    def put(off, src):
        code = assemble(src, ov1_base + off, defs)
        ov1[off:off + len(code)] = code

    # ScriptMenu_ShowList: the retail prologue, then OpenListWindow
    put(0x100, f"push {{r4, lr}}\nadds r4, r0, #0\nbl Width\n"
               f"movs r1, #{7 if b != 'show list' else 6}\ntst r1, r0\n"
               "bne 1f\nlsrs r1, r0, #3\nb 2f\n1: lsrs r0, r0, #3\nadds r1, r0, #1\n"
               "2: adds r0, r4, #0\nadds r0, #0x97\nldrb r0, [r0]\n"
               "lsls r0, r0, #0x19\nlsrs r0, r0, #0x1f\nadds r0, r4, #0\n"
               + ("bl Frame\n" if b == "show list calls" else "") +
               "bl OpenList\npop {r4, pc}\n")
    # ScriptMenu_ShowListWithWidth, then ScriptMenu_OpenListWindow right after it
    if b != "with width":
        put(0x1F8, "ldr r3, [pc, #0]\nbx r3\n.word OpenList + 1\n")
    put(0x200, f"""
        push {{r3, r4, lr}}
        sub sp, #0x14
        adds r4, r0, #0
        adds r0, #0x9b
        ldrb r2, [r0]
        cmp r2, #{8 if b != "open list" else 7}
        ldr r2, ={0x3D9 if b != "frame" else 0x3DA}
        bl Frame
        add sp, #0x14
        pop {{r3, r4, pc}}
        .pool
    """)
    # ScriptMenu_GetListItemsWidth
    put(0x300, f"""
        push {{r3, r4, r5, r6, r7, lr}}
        adds r7, r0, #0
        adds r0, #0x9b
        ldrb r0, [r0]
        movs r6, #0
        adds r4, r6, #0
        cmp r0, #0
        ble 3f
        adds r5, r7, #0
    1:  movs r0, #{0x71 if b != "width" else 0x70}
        lsls r0, r0, #2
        ldr r1, [r5, r0]
        cmp r1, #0
        beq 3f
        movs r0, #0
        adds r2, r0, #0
        bl StrWidth
        cmp r6, r0
        bhs 2f
        adds r6, r0, #0
        {"bl Frame" if b == "width calls" else ""}
    2:  adds r0, r7, #0
        adds r0, #0x9b
        ldrb r0, [r0]
        adds r4, r4, #1
        adds r5, #8
        cmp r4, r0
        blt 1b
    3:  adds r6, #0xc
        adds r0, r6, #0
        pop {{r3, r4, r5, r6, r7, pc}}
    """)
    # ScrCmd_MoveTutorChooseMove, its calls cut down to the ones that matter
    put(0x400, f"""
        push {{r4, r5, r6, r7, lr}}
        sub sp, #{0x6c if b != "tutor prologue" else 0x70}
        str r0, [sp, #0x14]
        adds r0, #0x80
        ldr r0, [r0]
        str r0, [sp, #0x28]
        bl {"GetList" if b != "tutor slot" else "Attr"}
        bl Attr
        bl GetVar
        bl Create
        bl AddItem
        ldr r3, =0xFFFD
        bl AddItem
        ldr r3, =0xFFFE
        bl AddItem
        bl GetVar
        adds r3, r0, #0
        ldr r0, [sp, #0x28]
        movs r1, #3
        movs r2, #{7 if b != "tutor state" else 3}
        bl {"SetState" if b != "tutor setter" else "SetCb"}
        ldr r0, [sp, #0x14]
        ldr r1, =Wait + 1
        bl Setup
        bl GetVar
        movs r0, #1
        add sp, #0x6c
        pop {{r4, r5, r6, r7, pc}}
        .pool
    """)
    # NativeScript_WaitMoveTutorMenu
    put(0x500, f"""
        push {{r4, r5, r6, lr}}
        adds r5, r0, #0
        adds r0, #0x80
        ldr r6, [r0]
        adds r0, r6, #0
        bl GetList
        bl GetVar
        ldrh r1, [r0]
        ldr r0, ={0xEEEE if b != "tutor wait" else 0xEEEF}
        cmp r1, r0
        bne 1f
        movs r0, #0
        pop {{r4, r5, r6, pc}}
    1:  movs r0, #1
        pop {{r4, r5, r6, pc}}
        .pool
    """)
    menu_exec = assemble(f"""
        push {{r3, r4, r5, lr}}
        adds r4, r0, #0
        adds r0, #0x80
        ldr r5, [r0]
        adds r0, r5, #0
        bl GetList
        ldr r1, [r4, #0x64]
        bl GetVar
        adds r3, r0, #0
        movs r1, #3
        movs r2, #{7 if b != "state" else 6}
        adds r0, r5, #0
        bl SetState
        ldr r1, =0x02047909
        adds r0, r5, #0
        bl SetCb
        ldr r1, ={0x020478D1 if b != "pool" else 0x020478D5}
        adds r0, r4, #0
        bl Setup
        movs r0, #1
        pop {{r3, r4, r5, pc}}
        .pool
    """, 0x02001000, defs)
    list_exec = assemble(f"""
        push {{r4, lr}}
        adds r4, r0, #0
        adds r0, #0x80
        ldr r0, [r0]
        movs r1, #0
        bl Attr
        ldr r0, [r0]
        bl ShowList
        ldr r1, ={0x020418B5 if b != "list pool" else 0x020418B9}
        adds r0, r4, #0
        bl {"Setup" if b != "list setup" else "GetVar"}
        movs r0, #1
        pop {{r4, pc}}
        .pool
    """, 0x02001100, defs)
    # String_c_str and FontID_String_GetWidth (pret sub_02002F30)
    cstr = assemble(f"""
        push {{r4, lr}}
        adds r4, r0, #0
        bne 1f
        bl AssertFail
    1:  ldr r1, [r4, #4]
        ldr r0, ={0xB6F8D2EC if b != "magic" else 0xB6F8D2ED}
        cmp r1, r0
        beq 2f
        bl AssertFail
    2:  adds r4, #8
        adds r0, r4, #0
        pop {{r4, pc}}
        .pool
    """, 0x02002000, defs)
    str_width = assemble(f"""
        push {{r4, r5, r6, lr}}
        lsls r4, r0, #2
        ldr r0, =0x0211188C
        adds r5, r1, #0
        ldr r0, [r0]
        adds r6, r2, #0
        adds r0, r0, r4
        adds r0, #{0x9c if b != "font" else 0x98}
        ldr r0, [r0]
        cmp r0, #0
        bne 1f
        bl AssertFail
    1:  adds r0, r5, #0
        bl CStr
        adds r1, r0, #0
        ldr r0, =0x0211188C
        adds r2, r6, #0
        ldr r0, [r0]
        adds r0, r0, r4
        adds r0, #0x9c
        ldr r0, [r0]
        bl GetStringWidth
        pop {{r4, r5, r6, pc}}
        .pool
    """, 0x02002F30, defs)
    arm9 = bytearray(0x8000)
    arm9[0x200:0x204] = bytes.fromhex("00207047")    # the do-nothing command
    arm9[0x1000:0x1000 + len(menu_exec)] = menu_exec
    arm9[0x1100:0x1100 + len(list_exec)] = list_exec
    arm9[0x2000:0x2000 + len(cstr)] = cstr
    arm9[0x2F30:0x2F30 + len(str_width)] = str_width
    table = 0x4000
    for k in range(regions.SCRIPT_CMD_COUNT):
        struct.pack_into("<I", arm9, table + 4 * k, 0x02000201)
    struct.pack_into("<I", arm9, table + 4 * 71, 0x02001101)
    struct.pack_into("<I", arm9, table + 4 * 653,
                     defs["Tutor"] if b != "tutor elsewhere" else 0x02001001)
    struct.pack_into("<I", arm9, table + 4 * 752, 0x02001001)
    overlays = {1: FakeOverlay(ov1_base, bytes(ov1))} if b != "no overlay 1" else {}
    return bytes(arm9), overlays, defs


def test_patcher_finds_the_native_list_functions():
    from onescreen import regions
    arm9, overlays, defs = fake_rom_for_lists()
    values, redirects, detail = regions.resolve_native_lists(arm9, overlays)
    assert values == {"menu_exec_orig": 0x02001001, "open_list": defs["OpenList"],
                      "string_width": defs["StrWidth"], "setup_native": defs["Setup"],
                      "tutor_exec_orig": defs["Tutor"]}, (values, detail)
    assert redirects == [(0x02004000 + 4 * 752, "OneScreen_MenuExec"),
                         (0x02004000 + 4 * 653, "OneScreen_TutorExec")], redirects
    # the lists' own functions: any of them off and nothing is redirected
    for broken in ("state", "pool", "list pool", "list setup", "show list",
                   "show list calls", "with width", "open list", "frame", "width",
                   "width calls", "font", "magic", "no overlay 1"):
        arm9, overlays, _defs = fake_rom_for_lists(broken)
        values, redirects, why = regions.resolve_native_lists(arm9, overlays)
        assert values is None and redirects == [], (broken, values)
    # the tutors' command: off and only the tutors keep the touch screen
    for broken in ("tutor prologue", "tutor slot", "tutor state", "tutor setter",
                   "tutor wait", "tutor elsewhere"):
        arm9, overlays, _defs = fake_rom_for_lists(broken)
        values, redirects, why = regions.resolve_native_lists(arm9, overlays)
        assert values is not None and values["tutor_exec_orig"] == 0, (broken, values)
        assert redirects == [(0x02004000 + 4 * 752, "OneScreen_MenuExec")], broken
        assert "tutors keep the touch screen" in why, why
    arm9, overlays, _defs = fake_rom_for_lists()
    damaged = bytearray(arm9)
    damaged[0x4000 + 4 * 400] = 0                     # a gap in the table
    assert regions.find_script_table(bytes(damaged)) is None
    assert regions.resolve_native_lists(bytes(damaged), overlays)[:2] == (None, [])


def test_config_fields_match_the_hook():
    """CONFIG_FIELDS and OneScreen_Config are positional; nothing else ties them."""
    from onescreen import inject
    h = Hook()
    base = h.var("OneScreen_Config")
    labels = {"screens_flipped": "cfg_screens_flip"}
    for i, name in enumerate(inject.CONFIG_FIELDS):
        assert h.var(labels.get(name, f"cfg_{name}")) == base + 4 * i, name
    assert h.var("pad_held") == base + 4 * len(inject.CONFIG_FIELDS)


# --- Oak's speech ---------------------------------------------------------------

OAK_STATE, OAK_BLINK = 0x0C, 0x114
BLINK_APPLY = 0x020165A5


def oak(h: Hook, state=46, blink_state=1, **blink):
    data = h.alloc(0x180)
    h.w32(data + OAK_STATE, state)
    b = h.alloc(0x50)
    h.w32(data + OAK_BLINK, b)
    h.w32(b + 0x04, blink.get("apply", BLINK_APPLY))
    h.w32(b + 0x08, blink.get("pltt", 0))
    h.w8(b + 0x4C, blink.get("screen", 0))
    h.w8(b + 0x4D, blink.get("palette", 6))
    h.w8(b + 0x4E, blink_state)
    h.w8(b + 0x4F, blink.get("timer", 5))
    return data, b


def test_oak_blink_held_only_while_a_band_is_up():
    h = Hook()
    data, b = oak(h)
    h.call("OneScreen_OakBlink", data, 1)
    assert h.r8(b + 0x4E) == 2                        # paused
    h.call("OneScreen_OakBlink", data, 1)
    assert h.r8(b + 0x4E) == 2
    h.call("OneScreen_OakBlink", data, 0)
    assert h.r8(b + 0x4E) == 0                        # restarted, from tick 0
    h.call("OneScreen_OakBlink", data, 0)
    assert h.r8(b + 0x4E) == 0                        # and left alone after
    # a pause we did not make is not ours to undo
    data, b = oak(h, blink_state=2)
    h.call("OneScreen_OakBlink", data, 0)
    assert h.r8(b + 0x4E) == 2
    # a blink mid-RESTART is caught the next frame, not forced
    data, b = oak(h, blink_state=0)
    h.call("OneScreen_OakBlink", data, 1)
    assert h.r8(b + 0x4E) == 0


def test_oak_blink_validation():
    for bad in (dict(apply=0x020165BD), dict(pltt=0x02100000), dict(screen=1),
                dict(palette=11), dict(timer=40)):
        h = Hook()
        data, b = oak(h, **bad)
        h.call("OneScreen_OakBlink", data, 1)
        assert h.r8(b + 0x4E) == 1, bad                # untouched
    h = Hook()
    data, _b = oak(h)
    h.w32(data + OAK_BLINK, 0x027FFFF0)               # not in main RAM
    h.call("OneScreen_OakBlink", data, 1)


def test_oak_monologue_text_is_not_painted_over():
    """Outside the three prompts, nothing of ours is blitted into Oak's dialog
    window - the per-frame paper over columns 24-26 erased the ends of long
    lines."""
    h = Hook()
    base = blank_blob(h)
    oak_char, oak_tile, col = 0x06018000, 0x36D, 24
    rows = [oak_char + (oak_tile + r * 27 + col) * 32 for r in range(4)]
    geo = struct.pack("<IIHH", labels.BLOB_HEADER, 3 * 32 * 4, 3 * 32, 3) + \
        struct.pack("<4I", *rows)
    h.w8(base + 4, 4)                                  # tile rows per box
    h.w8(base + 5, labels.GEO_COUNT)                   # geometries in the blob
    h.write(base + 8 + 28 * 2, geo)                   # LABEL_GEO_OAK
    for r in rows:
        h.write(r, bytes([0x11]) * 96)                # "text" in those tiles
    data, _b = oak(h, state=46)
    gsys = h.alloc(0x80)
    h.w32(gsys + 4, data)
    h.w32(h.var("cfg_app_callback"), gsys)
    orig = 0x02000141
    h.stub(orig, lambda hk, *r: 0)
    h.w32(h.var("cfg_oak_exec_orig"), orig)
    manager = h.alloc(0x40)
    h.w32(manager + 0x14 + 8, data)
    for _ in range(3):
        h.call("OneScreen_OakExec", manager, manager + 0x14)
    for r in rows:
        assert h.read(r, 96) == bytes([0x11]) * 96, hex(r)


def test_oak_exec_pauses_the_blink_for_its_prompts():
    h = Hook()
    blank_blob(h)
    data, b = oak(h, state=64)
    gsys = h.alloc(0x80)
    h.w32(gsys + 4, data)
    h.w32(h.var("cfg_app_callback"), gsys)
    h.stub(0x02000151, lambda hk, *r: 0)
    h.w32(h.var("cfg_oak_exec_orig"), 0x02000151)
    manager = h.alloc(0x40)
    h.w32(manager + 0x14 + 8, data)
    seen = []
    for state in (64, 65, 65, 66, 69, 70, 98, 99):
        h.w32(data + OAK_STATE, state)
        h.call("OneScreen_OakExec", manager, manager + 0x14)
        seen.append(h.r8(b + 0x4E))
        if seen[-1] == 0:                              # the game's next tick
            h.w8(b + 0x4E, 1)
    assert seen == [1, 2, 2, 0, 2, 0, 2, 0], seen


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


def main():
    failed = 0
    for test in TESTS:
        try:
            test()
            print(f"  ok    {test.__name__}")
        except Exception:                           # noqa: BLE001
            failed += 1
            print(f"  FAIL  {test.__name__}")
            traceback.print_exc()
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
