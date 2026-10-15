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
