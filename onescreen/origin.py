"""Origin HeartGold (起源心金) v4.0.3 + English patch 1.0.0-rc8 - specifics.

Origin HeartGold is not a retail HeartGold build: it is the Chinese hack
"起源心金", rebuilt by Alex on **hg-engine** over the *Japanese* HeartGold. Its
header is a real Japanese HeartGold's (`IPKJ` rev 0) and none of the retail
layout holds:

* 120 overlays instead of 129, at other addresses and with other numbers;
* a decompressed ARM9 of its own - hg-engine's C code is linked into it;
* its own battle engine, so the retail `BattleSystem`/`BattleContext` are not
  there in the shape the retail patch expects.

What *did* survive, and what this module relies on:

* `struct System` (gSystem) keeps the retail layout byte for byte -
  `heldKeysRaw` at +0x38, `screensFlipped` at +0x69 - because hg-engine copied
  it from the decomp. Only its address moved: 0x021D0094 here.
* The main loop keeps the retail's shape, and even its addresses: the loop head
  is at 0x02000D90 and the two calls the patcher hooks are still at 0x02000DB0
  and 0x02000DB4. Only the *targets* differ, because hg-engine rewrote the
  loop body and the key reader in C.
* The shared display-select helper (the one that applies POWCNT1 bit 15 and is
  called ~75 times) is at 0x020233FC; its POWCNT1 literal is at 0x020233FE.
  It must NOT be flipped - flipping it inverts the overworld.
* The boot-time graphics init is at 0x0201AA9A and must not be flipped either.
* The battle is overlay **14** here (its template sits at 0x020F70B8 with the
  thin ARM9 wrappers the retail battle also has), not the retail's 12.
* The script command table is at 0x020F793C with **843** entries, not 853.

Every address in this module was measured against the ROM itself; the probe
that found them is `tools/probe_origin.py` in this project's parent folder.
"""

import struct

from . import inject, labels, regions, themes

ARM9_RAM = 0x02000000

SHA1 = "a54a647599d59ed0060dfc4375c289d6e041318a"
GAME_CODE = "IPKJ"
TITLE = "Pokemon Origin HeartGold"

# --- gSystem -----------------------------------------------------------------
# The main loop's `ldr r4, =gSystem` is at 0x02000D8A and its literal pool
# word sits at 0x02000E30.
GSYSTEM_LDR = 0x02000D8A
GSYSTEM_POOL = 0x02000E30
GSYSTEM = 0x021D0094

# Retail offsets inside `struct System`, unchanged by hg-engine.
PAD_HELD_OFFSET = 0x38
SCREENS_FLIPPED_OFFSET = 0x69
INTRO_CLOCK_OFFSET = 0x2C

# --- ARM9 hook sites ---------------------------------------------------------
# The main loop: 0x02000D90 is the loop head, the back-edge `b` is at
# 0x02000E10. hg-engine rewrote the loop body, so the call the retail patch
# displaces is not there any more:
#
#     0x02000D90  bl 0x02000F2C   the app-state dispatcher, every frame
#     0x02000D94  bl 0x020010C4   the pad reader
#     0x02000D98  bl 0x0201ACFC   the pad and touch reader
#     0x02000D9C  ...             the soft-reset key check
#     0x02000DB0  bl 0x02000F5C   the SOFT RESET itself - only when the player
#                                  holds L+R+START+SELECT; it clears both
#                                  screens, so it must not be displaced
#     0x02000DB4  bl 0x02035FE4   hg-engine's key reader; its RESULT is read
#                                  by the loop, so the hook must hand it back
#
# The hook therefore displaces the call at 0x02000D98, the last call before the
# key reader - the same place in the frame as in the retail build - and runs
# 0x0201ACFC itself.
MAIN_LOOP_SITE = 0x02000D98
ORIG_LOOP_FN = 0x0201ACFC
KEY_READ_SITE = 0x02000DB4
ORIG_KEY_READ_FN = 0x02035FE4

# The retail patcher also re-applies the game's own "L is A" button mode after
# hiding L+R from the game, by calling ApplyButtonModeToInput. hg-engine folded
# that into its C key reader, so there is no separate function to call: the
# button mode is applied by the original reader and simply not repeated.
BUTTON_MODE_CALL = 0
BUTTON_MODE_FN = 0

# The evolution scene's main-queue task. hg-engine moved the evolution code in
# the ARM9, but it kept it: the app callback and the task are retail's own
# functions, byte for byte, only at other addresses.
#
# The task is started by a pointer literal - the word that holds the task
# callback and is handed to SysTask_CreateOnMainQueue. In retail that word sits
# at 0x02075D04, in Origin at 0x020743BC; both are found by the same shape:
# exactly one `ldr r0, [pc, #imm]` in the ARM9 resolves to the pool word that
# holds the callback, and the callback's own code is the retail one.
EVOLUTION_TASK_LITERAL = 0x020743BC
EVOLUTION_TASK_ORIG = 0x020743C1

# --- display routing ---------------------------------------------------------
# The shared display-select helper: reads gSystem.screensFlipped and applies
# POWCNT1 bit 15. 75 call sites (14 in the ARM9, 61 in overlays).
DISPLAY_HELPER_SITE = 0x020233FE
DISPLAY_HELPER_FN = 0x020233FC
# The boot-time graphics init, called once from NitroMain.
BOOT_INIT_SITE = 0x0201AA9A

# --- overlays ----------------------------------------------------------------
FIELD_OVERLAY = 1
BATTLE_OVERLAY = 14
# Live while the battle renderer owns either engine. The battle template's
# exit callback can run an evolution with this renderer already torn down.
BATTLE_VBLANK = 0x02227895
BATTLE_VBLANK_SIG = bytes.fromhex("10b5041ca06be1f58bfdf9f555fae5f58ff9")

# The post-battle scan calls Party_GetMonByIndex for all six slots. It must
# leave the loop when it reaches the end of the occupied party.
EVOLUTION_PARTY_CALL = 0x02214DFA
EVOLUTION_PARTY_GET_MON = 0x0207339D
EVOLUTION_SCAN_DONE = 0x02214E2F
EVOLUTION_SCAN_TAIL = bytes.fromhex("0629e4db0020f8bd")
# The Pokédex app, the PC box and the flight map. hg-engine renumbered the
# overlays, so a retail number means a different app here - the numbers below
# were found by data, not by guesswork: hg-engine rewrote the overlay CODE but
# kept the big data tables, so the overlay that still holds a retail overlay's
# bytes is that app. tools/ov_map_all.py prints the whole map; the pairs that
# matter here are
#
#   retail ov18 (the Pokédex)  ->  Origin ov5
#   retail ov101 (the fly map) ->  Origin ov92
#   retail ov14 (the PC box)   ->  Origin ov16
#   retail ov53 (Oak's speech) ->  Origin ov49 (live-verified, and hooked by
#                                 content rather than by template)
#
# The Pokedex and the fly map are taken over through their OverlayManagerTemplate,
# which the patcher finds by shape; so is the PC box, whose application is retail's
# overlay 14 - the same size (80512 against 81248 bytes) and the same data blocks.
# The PC box has not been reached in the emulator yet, so that take-over rests on
# the data alone.
POKEDEX_OVERLAY = 5
PC_OVERLAY = 16
MAP_OVERLAY = 92

# Origin's Oak speech app is not reached through an ARM9 template: its exec
# callback is a data word inside the overlay that holds the app. The word
# 0x021E4C59 occurs exactly once in that overlay - at file offset 0x250 - so
# the patcher can put the hook there and remember the original.
#
# This app is the one the retail build hooks as "overlay 53"; in Origin it is
# overlay 49. The retail Oak hook is therefore NOT installed here: it expects
# the retail OakSpeechData layout, and Origin's overlay 53 is a different app
# (retail's overlay 57), where that hook would touch a stranger's data.
OAK_APP_OVERLAY = 49
OAK_EXEC_ORIG = 0x021E4C59
OAK_EXEC_PTR_OFF = 0x250

# The name entry app, which hg-engine rewrote: its exec is a three-instruction
# stub in overlay 58 that hands its own +0x04 to the ARM9 routine at 0x0201F6E4.
# The bytes are unique in that overlay, which is what the app table needs.
NAME_ENTRY_OVERLAY = 58
NAME_ENTRY_SIG = bytes.fromhex("014b40681847c046")
NAME_ENTRY_MASK = bytes.fromhex("ffffffffffffffff")

# The name entry's keyboard: an ARM9 routine, the way retail's is - retail's
# sits at 0x02083141 and does the same work - and the way the retail app table
# treats it. It draws the keyboard on engine A and routes that engine to the
# bottom screen; the app table's swap 0 puts the keyboard on the top screen,
# which is the retail build's own answer for the same routine.
#
# Measured live: the callback is 0x02081e0d while the keyboard is up, and the
# routine has retail's shape - a push, four literal loads, the task's data at
# +0x168, the callback and its argument written into the task.
NAME_KEYBOARD_CALLBACK = 0x02081E0D
NAME_KEYBOARD_SIG = bytes.fromhex("08b59ef79dff89f7d7f903")

# Origin's Oak dialog box is retail's, down to the tile it starts at: the same
# 27 tiles of MAIN_0, the same base tile 0x36D, the same character base
# 0x06018000 - measured live, the window's first glyph sits at
# 0x06018000 + 0x36D * 32 and paints the very first letter of Oak's line.
#
# One thing differs. Retail's boy/girl words cover all four rows of the window,
# because retail's window has nothing else on it while they are up. Origin keeps
# its second line of text on screen while the outfit picker is up - "Won't you
# please tell me?" is still there - so Origin's words stop after the first line.
OAK_GENDER_ROWS = 2

# The battle's OverlayManagerTemplate: init/exec/exit are thin ARM9 wrappers
# (eight bytes apart), exactly as in the retail build.
BATTLE_TEMPLATE = 0x020F70B8

# --- globals -----------------------------------------------------------------
# sFieldSysPtr - the file-static holding the live FieldSystem.
FIELD_SYS = 0x021D31F4
# Task_StartMenu, the overworld menu's task function. hg-engine grew its
# StartMenu struct by four bytes, so the retail prologue no longer matches and
# the address has to be given rather than derived.
START_MENU_TASK = 0x0203B3E9

# The two fields of that struct the hook reads, at their Origin offsets. The
# struct grew by four bytes at the front, so both sit four bytes further on
# than in the retail build - measured live, not guessed: the state reads 3
# (START_MENU_STATE_HANDLE_INPUT) at +0x2A while the menu is up, and the
# inhibit flags read 0x180 (the normal layout's own set) at +0x350.
#
# Everything else about the field is still the retail layout, which is what
# makes the overworld menu drawable at all: sFieldSysPtr, the task manager,
# the touch menu app and its data all answer at their retail offsets.
START_MENU_STATE_OFF = 0x2A
START_MENU_INHIBIT_OFF = 0x350

# The script command table: 843 Thumb pointers, the first two being the
# do-nothing stubs, at 0x020F793C.
SCRIPT_TABLE = 0x020F793C
SCRIPT_CMD_COUNT = 843
SCRCMD_LIST_MENU_EXEC = 71
SCRCMD_TUTOR_CHOOSE_MOVE = 653
SCRCMD_MENU_EXEC = 752

# The functions those two commands call, read out of their own literal pools
# (their retail addresses moved with the rest of the ARM9).
MENU_EXEC_HELP = 0x02046F69
WAIT_MENU_EXEC = 0x02046F31
WAIT_MULTICHOICE = 0x02040FF1

# The app table entries the patcher verifies. The evolution scene's entry
# survived with its retail bytes; name entry was rewritten by hg-engine and is
# found in its own overlay instead, by a signature of its own code. The move
# relearner, the Pal Pad and the rankings viewer did keep their retail code -
# hg-engine renumbered the overlays, so they live in different ones.
#
# The name entry's swap is 0, the retail value: the app draws its screen on
# engine A - the dressing room with the outfit list and the name field - and
# the game wants that engine on the bottom screen. Putting engine A on top
# moves the whole name entry to the upper screen, which is what the retail
# build's app table asks for as well.
APP_TABLE = [
    ("name entry", 0, 0, NAME_ENTRY_SIG, NAME_ENTRY_OVERLAY, NAME_ENTRY_MASK),
    ("evolution", 0x020759A5, 0,
     bytes.fromhex("38b5041c75300278201c73300178201c72300078ff231b02"), None, None),
    ("move relearner", None, 1, regions.RELEARNER_SIG, 65, regions.RELEARNER_MASK),
    ("Pal Pad", None, 0, regions.PALPAD_SIG, 44, regions.PALPAD_MASK),
    ("rankings", None, 0, regions.RANKINGS_SIG, 113, regions.RANKINGS_MASK),
    # The last slot, the one the retail table does not have: the keyboard behind
    # the outfit list is an ARM9 routine of hg-engine's own.
    ("name keyboard", NAME_KEYBOARD_CALLBACK, 0, NAME_KEYBOARD_SIG, None, None),
]

# The touch menu's own layout table - sTouchscreenMenuLayouts - is the game's
# data, and Origin kept it byte for byte, because hg-engine took the table
# from the decomp rather than writing its own. It sits in overlay 28 here
# instead of the retail build's 27, though: hg-engine renumbered the overlays.
TOUCH_LAYOUT_OVERLAY = 28


def touch_layout_overlays(overlays):
    """The overlays that hold the touch menu's layout table.

    Origin keeps the table byte for byte, so it is looked for by its content
    rather than by its overlay number - the number is only known for this one
    build, and the content is what the patcher actually needs.
    """
    return labels.touch_layout_overlay_ids(overlays, sorted(overlays))

# --- message and font archives ------------------------------------------------
# Origin's message archive was rebuilt from a Japanese base with a Chinese text,
# so its files sit at other positions than retail's msg_XXXX names. What does
# NOT move are the message indices INSIDE a file: Origin's file 195 holds
# exactly what retail's msg_0197 holds, at exactly the same indices - 924 FIGHT,
# 925 BAG, 926 POKéMON, 927 RUN, 940 Yes, 941 No, 931 BALL, 932 BAIT, 933 MUD.
#
#   retail 197 (battle text)   -> 195
#   retail 196 (start menu)    -> 194
#   retail 191 (script lists)  -> 189
#   retail 219 (Oak's speech)  -> 216
#   retail 282 (trainer card)  -> 275
#   retail 286 (name entry)    -> 279
MSG_FILES = {197: 195, 196: 194, 191: 189, 219: 216, 282: 275, 286: 279}

# The font archive holds thirteen files. Five of them are the standard fonts -
# file 1 is the one the battle message box prints with, exactly as in retail -
# and they all keep the retail charmap: the character code minus one is the
# glyph slot, so code 299 ('A') is slot 298, where the Latin letters live.
#
# The odd one out is file 3: a 509-glyph font in the old retail shape that
# holds the hack's Chinese glyphs, not Latin ones. Its width table says so:
# every letter in it is 8 to 12 pixels wide, where file 1's Latin letters are
# 6 - and the battle menu's three lower words come to 132 pixels in it, which
# does not fit the space the menu has.
FONT_FILE = 1


# --- the battle command menu -------------------------------------------------
#
# Origin runs its own battle engine, so the retail plumbing - a BattleSystem
# with a menu id, a BattleInput with a cursor - is not there at all. What the
# game does have, measured live in this ROM:
#
#   MENU_PTR   the address of a pointer to the battle's menu object. It is 0
#              while there is no menu, and points at a heap block once one is
#              up - the same block for every menu the battle shows.
#   MENU_FLAG  the offset of that object's own "it is open" flag inside it.
#   MENU_STATE the offset of the battle scene's state in the same object:
#              0 outside a battle, 1 while the battle intro plays, 2 while the
#              command menu is up. It is what tells the hook that this menu is
#              the battle's and not some other screen's.
#   CURSOR     the address of the selected entry, which the game writes as its
#              own command id:
#              0 FIGHT, 1 BAG, 2 POKEMON, 3 RUN, 4 INFO
#
# The game moves that cursor with the D-Pad and confirms it with A, and it
# draws its own touch buttons on the bottom screen - so the hook only mirrors
# it: the words go on the top screen, in the battle message window, and the
# band follows the cursor. Nothing is synthesised and nothing is driven.
#
# The three addresses live in the shared menu struct at 0x02255B90: the pointer
# at +0x04 and the cursor at +0x0C.
BATTLE_MODE = 1
MENU_PTR = 0x02255B94
MENU_FLAG = 0x1B1
MENU_STATE = 0x3D0
CURSOR = 0x02255B9C

# The live engine data holds the active sub-overlay at +0x26C. The native
# switch routine at 0x02215914 stores it after loading the overlay.
BATTLE_DATA_PTR = 0x02255BAC

# Phases 1, 2, 3 and 4 are command, move selection, target selection and a
# two-option question. See src/hook.s for the native menu lifetime checks.

# The shared menu struct at 0x02255B90 keeps one cursor per screen, four bytes
# apart. Screen 1 is the command menu - the hook already reads its cursor -
# and screen 4 is the two-option prompt: the trainer's "will you switch your
# Pokémon?". Its cursor is the answer, 0 for YES and 1 for NO.
#
# Measured in this ROM's own battle code (overlay 14): the ask routine at
# 0x02213040 clears it, the prompt worker at 0x022131A4 writes the answer into
# it, and the prompt's own key handler at 0x02213118 moves it.
PROMPT_CURSOR = 0x02255BA8

# The menu object has a byte that says which of the player's two battlers the
# command menu belongs to. The game writes it when it creates the menu: it is
# not zero when the menu is the second battler's - the partner of a double
# battle, who cannot run and is shown CANCEL where RUN usually is. That is
# this build's answer to the retail BattleInput.cancelShown.
#
# Measured in overlay 14: the command menu's creator at 0x0221429C stores it,
# and the only reader, 0x022144C4, picks a different battle message for it.
CANCEL_FLAG = 0x1B3


def read_pool_word(arm9: bytes, addr: int) -> int:
    off = addr - ARM9_RAM
    if not 0 <= off <= len(arm9) - 4:
        raise ValueError(f"{addr:#010x} is outside the ARM9")
    return struct.unpack_from("<I", arm9, off)[0]


def ldr_literal_target(arm9: bytes, addr: int):
    """(register, pool address) if `addr` holds a Thumb LDR-literal."""
    off = addr - ARM9_RAM
    if not 0 <= off <= len(arm9) - 2:
        return None
    h = struct.unpack_from("<H", arm9, off)[0]
    if (h & 0xF800) != 0x4800:
        return None
    reg = (h >> 8) & 7
    pool = ((off + 4) & ~3) + (h & 0xFF) * 4
    return reg, ARM9_RAM + pool


def check(arm9: bytes, log=print):
    """Verify every anchor this module relies on. Raises on a mismatch."""
    problems = []

    def want(label, got, expected):
        if got != expected:
            problems.append(f"{label}: expected {expected:#010x}, found {got:#010x}")

    # gSystem, straight out of the main loop's own literal pool.
    reg, pool = ldr_literal_target(arm9, GSYSTEM_LDR) or (None, None)
    want("the main loop's gSystem load", reg, 4)
    want("the main loop's gSystem pool", pool, GSYSTEM_POOL)
    want("gSystem", read_pool_word(arm9, GSYSTEM_POOL), GSYSTEM)

    # The two calls the patcher replaces.
    for site, target, label in ((MAIN_LOOP_SITE, ORIG_LOOP_FN, "the loop call"),
                                (KEY_READ_SITE, ORIG_KEY_READ_FN, "the key read")):
        off = site - ARM9_RAM
        h = struct.unpack_from("<H", arm9, off)[0]
        h2 = struct.unpack_from("<H", arm9, off + 2)[0]
        disp = ((h & 0x7FF) << 12) | ((h2 & 0x7FF) << 1)
        if disp & 0x400000:
            disp -= 0x800000
        want(label, ARM9_RAM + off + 4 + disp, target)

    # The display helper's POWCNT1 write and the boot init.
    for site, label in ((DISPLAY_HELPER_SITE, "the display helper"),
                        (BOOT_INIT_SITE, "the boot-time graphics init")):
        off = site - ARM9_RAM
        h = struct.unpack_from("<H", arm9, off)[0]
        if (h & 0xF800) != 0x4800:
            problems.append(f"{label} at {site:#010x} is not a literal load")

    # The battle's template.
    off = BATTLE_TEMPLATE - ARM9_RAM
    init, ex, exi, oid = struct.unpack_from("<4I", arm9, off)
    want("the battle template's overlay id", oid, BATTLE_OVERLAY)
    if not all(x & 1 for x in (init, ex, exi)):
        problems.append("the battle template's functions are not Thumb")
    if not (init & ~1) < (ex & ~1) < (exi & ~1):
        problems.append("the battle template's functions are not in order")

    if problems:
        raise ValueError("this ROM is not the Origin HeartGold build the "
                         "anchors were measured on:\n  - "
                         + "\n  - ".join(problems))
    return True


# What each mapped message file must hold for the mapping to be believable: the
# message indices the retail build reads from it, and how many messages the
# file must have for those indices to exist.
MSG_EXPECT = {
    197: ((924, 925, 926, 927, 940, 941), 1280),   # battle commands, yes/no
    196: ((0, 1, 2, 4, 5, 8, 14), 15),             # start menu
    191: ((62, 64, 66, 73, 75, 321), 322),         # script list menus
    219: ((47, 48), 49),                           # Oak's yes/no
    282: ((5,), 6),                                # trainer card
    286: ((7, 16), 17),                            # name entry
}


def check_messages(rom):
    """Verify the message-archive mapping against this ROM's own content.

    Raises labels.LabelError if a mapped file does not hold the messages the
    retail build reads from it, so a wrong file number shows up as "labels not
    built" rather than as the wrong words on the top screen.

    The check is language-independent: it asks that the entries decode to
    something, that the four battle commands are four DIFFERENT words and the
    two answers two different ones, and that each file is long enough for the
    indices used.
    """
    try:
        msg_id = rom.filenames.idOf(labels.MSGDATA_NARC)
        font_id = rom.filenames.idOf(labels.FONT_NARC)
    except Exception as exc:                        # noqa: BLE001
        raise labels.LabelError(f"cannot resolve the archives: {exc}") from exc
    if msg_id is None or font_id is None:
        raise labels.LabelError("the message or font archive is missing")

    archive = labels._narc_files(bytes(rom.files[msg_id]))
    for retail_id, (indices, minimum) in MSG_EXPECT.items():
        file_id = MSG_FILES[retail_id]
        if file_id >= len(archive):
            raise labels.LabelError(
                f"the message archive has no file {file_id} (retail {retail_id})")
        src = archive[file_id]
        count = struct.unpack_from("<H", src, 0)[0]
        if count < minimum:
            raise labels.LabelError(
                f"message file {file_id} holds {count} messages, fewer than the "
                f"{minimum} retail {retail_id} needs")
        decoded = []
        for index in indices:
            try:
                codes = labels._decode_message(src, index)
            except labels.LabelError as exc:
                raise labels.LabelError(
                    f"message file {file_id}: {exc}") from exc
            if not codes:
                raise labels.LabelError(
                    f"message file {file_id}: message {index} decoded to nothing")
            decoded.append(tuple(codes))
        if retail_id == 197:
            commands = decoded[:4]
            if len(set(commands)) != 4:
                raise labels.LabelError(
                    "message file 195 does not hold four different battle "
                    "commands - this is not the battle text file")
            if decoded[4] == decoded[5]:
                raise labels.LabelError(
                    "message file 195 holds the same word twice for the "
                    "yes/no pair")
        if retail_id == 219 and decoded[0] == decoded[1]:
            raise labels.LabelError(
                "message file 216 holds the same word twice for Oak's yes/no")

    fonts = labels._narc_files(bytes(rom.files[font_id]))
    if FONT_FILE >= len(fonts):
        raise labels.LabelError(f"the font archive has no file {FONT_FILE}")
    try:
        labels.Font(fonts[FONT_FILE])
    except labels.LabelError as exc:
        raise labels.LabelError(f"the font file is not the expected one: {exc}") from exc
    return True


# ---------------------------------------------------------------------------
# The config values the hook needs
# ---------------------------------------------------------------------------

def _script_table(arm9: bytes):
    """The script command table, or None."""
    off = SCRIPT_TABLE - ARM9_RAM
    if off < 0 or off + 4 * SCRIPT_CMD_COUNT > len(arm9):
        return None
    # the first two entries are the do-nothing commands
    for i in (0, 1):
        target = struct.unpack_from("<I", arm9, off + 4 * i)[0]
        t_off = (target & ~1) - ARM9_RAM
        if not 0 <= t_off <= len(arm9) - 4:
            return None
        if arm9[t_off:t_off + 4] != regions.SCRCMD_NOP:
            return None
    # and the last entry is still a Thumb function
    last = struct.unpack_from("<I", arm9, off + 4 * (SCRIPT_CMD_COUNT - 1))[0]
    if not last & 1:
        return None
    return SCRIPT_TABLE


def resolve_native_lists(arm9: bytes, overlays):
    """The script-list plumbing, Origin edition.

    The retail version recognises ScriptMenu_ShowList by its exact retail
    prologue. hg-engine rewrote the script commands in C, so that prologue is
    gone - but the two functions it calls are untouched, and they are what the
    hook actually uses: the check is therefore anchored on them instead, which
    is just as tight.

    Returns ({config values}, [(table entry, hook symbol)], detail) or
    (None, [], why).
    """
    table = _script_table(arm9)
    if table is None:
        return None, [], "the script command table is not where it was measured"

    def entry(k):
        return struct.unpack_from("<I", arm9, table - ARM9_RAM + 4 * k)[0]

    menu_exec = entry(SCRCMD_MENU_EXEC)
    list_exec = entry(SCRCMD_LIST_MENU_EXEC)

    ov1 = overlays.get(1)
    if ov1 is None:
        return None, [], "overlay 1 is not available"
    ov1_lo = ov1.ramAddress
    ov1_hi = ov1_lo + len(ov1.data)
    data = bytes(ov1.data)

    def in_ov1(a):
        return ov1_lo <= a < ov1_hi

    try:
        m_calls, m_lits, m_half = regions._thumb_calls(arm9, ARM9_RAM, menu_exec)
        l_calls, l_lits, _l_half = regions._thumb_calls(arm9, ARM9_RAM, list_exec)
    except ValueError as exc:
        return None, [], str(exc)

    if len(m_calls) != 5 or MENU_EXEC_HELP not in m_lits or WAIT_MENU_EXEC not in m_lits:
        return None, [], f"command {SCRCMD_MENU_EXEC} is not ScrCmd_MenuExec"
    if 0x2103 not in m_half or 0x2207 not in m_half or not in_ov1(m_calls[0]):
        return None, [], f"command {SCRCMD_MENU_EXEC} does not set the list state"
    if len(l_calls) != 3 or WAIT_MULTICHOICE not in l_lits:
        return None, [], f"command {SCRCMD_LIST_MENU_EXEC} is not the list command"
    setup_native = m_calls[4]
    if l_calls[2] != setup_native:
        return None, [], "the two commands disagree on SetupNativeScript"

    show_list = l_calls[1]
    if not in_ov1(show_list):
        return None, [], "ScriptMenu_ShowList is not in overlay 1"
    s_calls, _s_lits, _s_half = regions._thumb_calls(data, ov1_lo, show_list)
    if len(s_calls) != 2 or not all(in_ov1(a) for a in s_calls):
        return None, [], "ScriptMenu_ShowList does not make its two calls"
    get_width, open_list = s_calls

    # ScriptMenu_OpenListWindow: its prologue, ShowListWithWidth's pointer at
    # it, and the frame tile in its pool.
    off = open_list - ov1_lo
    if data[off:off + len(regions.OPEN_LIST_SIG)] != regions.OPEN_LIST_SIG:
        return None, [], "ScriptMenu_OpenListWindow does not match its retail prologue"
    if off < 8 or data[off - 8:off - 4] != regions.SHOW_LIST_WITH_WIDTH or \
            struct.unpack_from("<I", data, off - 4)[0] != open_list | 1:
        return None, [], "ScriptMenu_ShowListWithWidth does not lead to OpenListWindow"
    _o_calls, o_lits, _o_half = regions._thumb_calls(data, ov1_lo, open_list, limit=0x100)
    if regions.LIST_FRAME_TILE not in o_lits:
        return None, [], "ScriptMenu_OpenListWindow does not draw the list frame"

    # FontID_String_GetWidth, through ScriptMenu_GetListItemsWidth's one call.
    if not regions._masked_match(data, get_width - ov1_lo, regions.GET_WIDTH_SIG,
                                 regions.GET_WIDTH_MASK):
        return None, [], "ScriptMenu_GetListItemsWidth does not match its retail code"
    g_calls, _g_lits, _g_half = regions._thumb_calls(data, ov1_lo, get_width)
    if len(g_calls) != 1:
        return None, [], "ScriptMenu_GetListItemsWidth makes more than its one call"
    string_width = g_calls[0]
    if not regions._masked_match(arm9, string_width - ARM9_RAM,
                                 regions.STRING_WIDTH_SIG, regions.STRING_WIDTH_MASK):
        return None, [], "FontID_String_GetWidth does not match its retail code"
    w_calls, _w_lits, _w_half = regions._thumb_calls(arm9, ARM9_RAM, string_width)
    try:
        _c_calls, c_lits, _c_half = regions._thumb_calls(arm9, ARM9_RAM, w_calls[1])
    except (IndexError, ValueError):
        c_lits = []
    if len(w_calls) != 3 or regions.STRING_MAGIC not in c_lits:
        return None, [], "FontID_String_GetWidth does not take a String"

    values = {"menu_exec_orig": menu_exec, "open_list": open_list | 1,
              "string_width": string_width | 1, "setup_native": setup_native | 1,
              "tutor_exec_orig": 0}
    redirects = [(table + 4 * SCRCMD_MENU_EXEC, "OneScreen_MenuExec")]
    detail = (f"table {table:#010x}, MenuExec {menu_exec:#010x}, "
              f"OpenListWindow {open_list:#010x}; the move tutors keep the "
              f"touch screen")
    return values, redirects, detail


def patch_oak_exec(ov_data, overlays, meta, log=print, take_over=True):
    """Put the hook in front of Origin's Oak speech app.

    The app's exec callback is a data word inside overlay 49 rather than an
    entry of an ARM9 template, so this writes the word itself. The original is
    remembered in the config, and the overlay is stored uncompressed afterwards
    (see onescreen/rom.py).

    Returns the overlay ids whose data changed.
    """
    ov = overlays.get(OAK_APP_OVERLAY)
    if ov is None:
        log(f"  Oak      : overlay {OAK_APP_OVERLAY} is missing; the opening "
            "speech keeps its own routing")
        return []
    buf = ov_data[OAK_APP_OVERLAY]
    off = OAK_EXEC_PTR_OFF
    found = struct.unpack_from("<I", buf, off)[0]
    if found != OAK_EXEC_ORIG:
        log(f"  Oak      : overlay {OAK_APP_OVERLAY} does not hold "
            f"{OAK_EXEC_ORIG:#010x} at offset {off:#x} (found {found:#010x}); "
            "the opening speech keeps its own routing")
        return []
    if take_over:
        struct.pack_into("<I", buf, off, meta["symbols"]["OneScreen_OriginOakExec"] | 1)
        log(f"  Oak      : overlay {OAK_APP_OVERLAY} offset {off:#x}, exec "
            f"{found:#010x} -> OneScreen_OriginOakExec")
    else:
        log(f"  Oak      : overlay {OAK_APP_OVERLAY} offset {off:#x}, exec "
            f"{found:#010x} left alone")
    return [OAK_APP_OVERLAY]


def patch_evolution_party(data, base, target):
    """Guard the native evolution scan's party lookup in overlay 14."""
    call = EVOLUTION_PARTY_CALL - base
    tail = (EVOLUTION_SCAN_DONE & ~1) - base - 4
    if (call < 0 or tail < 0
            or not data.startswith(inject.thumb_bl(EVOLUTION_PARTY_CALL,
                                                   EVOLUTION_PARTY_GET_MON), call)
            or not data.startswith(EVOLUTION_SCAN_TAIL, tail)):
        raise ValueError("Origin's post-battle evolution scan does not match")
    data[call:call + 4] = inject.thumb_bl(EVOLUTION_PARTY_CALL, target)


def resolve(arm9: bytearray, overlays, meta, log=print,
            theme=themes.DEFAULT_THEME, take_over=True,
            battle_take_over=True):
    """Return (config values, delta) for this ROM.

    `meta` is the payload's symbol table: the apps the hook takes over have
    their OverlayManagerTemplate's exec pointer rewritten to the hook's own
    routine, and the original is remembered in the config.

    `take_over=False` resolves everything but leaves the templates alone - a
    bisect aid, and the safe answer for a ROM whose templates cannot be
    vouched for.

    `battle_take_over=False` leaves only the BATTLE's template alone. The
    battle is the one template whose exec pointer the game calls every frame
    while the battle runs, so it is also the one that can break the battle
    outright - this flag isolates it from the other take-overs.
    """
    check(bytes(arm9), log=log)

    ov1 = overlays.get(FIELD_OVERLAY)
    ov14 = overlays.get(BATTLE_OVERLAY)
    if ov1 is None or ov14 is None:
        raise ValueError("the field or the battle overlay is missing")
    vblank_off = (BATTLE_VBLANK & ~1) - ov14.ramAddress
    if vblank_off < 0 or not ov14.data.startswith(BATTLE_VBLANK_SIG, vblank_off):
        raise ValueError("Origin's battle VBlank callback does not match the supported build")

    # The battle's OverlayManagerTemplate, read straight out of the ARM9. Its
    # init/exec/exit are thin ARM9 wrappers, as in the retail build, so the
    # exec pointer is replaced with the hook's own: that is what hands the hook
    # the live BattleSystem every frame, which the command menu is built on.
    off = BATTLE_TEMPLATE - ARM9_RAM
    init, battle_exec, exit_, oid = struct.unpack_from("<4I", arm9, off)
    if oid != BATTLE_OVERLAY:
        raise ValueError("the battle template does not name the battle overlay")
    if take_over and battle_take_over:
        struct.pack_into("<I", arm9, off + 4, meta["symbols"]["OneScreen_BattleExec"] | 1)
        log(f"  {'Battle':<9}: template {BATTLE_TEMPLATE:#010x}, exec "
            f"{battle_exec:#010x} -> OneScreen_BattleExec")
    else:
        log(f"  {'Battle':<9}: template {BATTLE_TEMPLATE:#010x}, exec "
            f"{battle_exec:#010x} left alone")

    values = {
        "pad_held": GSYSTEM + PAD_HELD_OFFSET,
        "app_callback": GSYSTEM,
        "field_callback": ov1.ramAddress | 1,
        "ov12_lo": ov14.ramAddress,
        "ov12_hi": ov14.ramAddress + ov14.ramSize,
        # No loaded-overlay table in this ROM, so the hook takes the battle's
        # phase from the command menu instead (see src/hook.s).
        "battle_state": 0,
        "field_sys": FIELD_SYS,
        "screens_flipped": GSYSTEM + SCREENS_FLIPPED_OFFSET,
        "start_menu_task": START_MENU_TASK,
        "battle_exec_orig": battle_exec,
        "intro_a_exec": 0,
        "intro_b_exec": 0,
        "intro_c_exec": 0,
        "intro_clock": GSYSTEM + INTRO_CLOCK_OFFSET,
        "theme_band": themes.get(theme)["band"],
        "dex_exec_orig": 0,
        "pc_exec_orig": 0,
        "map_exec_orig": 0,
        "oak_exec_orig": 0,
        # Origin's Oak speech app: the hook calls its exec and then routes on
        # the app's own state byte. The original is written into the overlay
        # by patch_oak_exec; see there for why it is not a template.
        "origin_oak_exec_orig": OAK_EXEC_ORIG,
        "menu_exec_orig": 0,
        "open_list": 0,
        "string_width": 0,
        "setup_native": 0,
        "tutor_exec_orig": 0,
        # The functions the hook calls on the game's behalf.
        "orig_loop_fn": ORIG_LOOP_FN | 1,
        "read_keys_orig": ORIG_KEY_READ_FN | 1,
        "apply_button_mode": BUTTON_MODE_FN,
        # The battle menu, which this build runs itself.
        "battle_mode": BATTLE_MODE,
        "origin_menu_ptr": MENU_PTR,
        "origin_menu_flag": MENU_FLAG,
        "origin_cursor": CURSOR,
        "origin_state": MENU_STATE,
        "origin_battle_data": BATTLE_DATA_PTR,
        # The two-option prompt's own cursor, and the byte that says the
        # command menu belongs to the player's second battler.
        "origin_prompt_cursor": PROMPT_CURSOR,
        "origin_cancel_flag": CANCEL_FLAG,
        "origin_battle_vblank": BATTLE_VBLANK,
        "origin_evo_get_mon": EVOLUTION_PARTY_GET_MON,
        "origin_evo_done": EVOLUTION_SCAN_DONE,
        # The start menu's struct, four bytes further on than in retail.
        "startmenu_state_off": START_MENU_STATE_OFF,
        "startmenu_inhibit_off": START_MENU_INHIBIT_OFF,
    }

    # The apps the hook takes over, each found by the shape of its
    # OverlayManagerTemplate. hg-engine renumbered the overlays, so the numbers
    # are the ones this ROM was measured with, and each one is checked.
    for label, ovy_id, field, symbol, effect in (
            ("Pokedex", POKEDEX_OVERLAY, "dex_exec_orig", "OneScreen_DexExec",
             "the area map will stay on the bottom screen"),
            ("PC box", PC_OVERLAY, "pc_exec_orig", "OneScreen_PcExec",
             "the box screens will stay on the bottom screen"),
            ("Fly map", MAP_OVERLAY, "map_exec_orig", "OneScreen_MapExec",
             "the flight animation will stay on the bottom screen")):
        tmpl = regions.find_overlay_template(arm9, overlays, ovy_id)
        if tmpl:
            addr, _init, orig_exec, _exit = tmpl
            values[field] = orig_exec
            if take_over:
                struct.pack_into("<I", arm9, (addr + 4) - ARM9_RAM,
                                 meta["symbols"][symbol] | 1)
            log(f"  {label:<9}: template {addr:#010x}, exec "
                f"{orig_exec:#010x} -> {symbol}")
        else:
            log(f"  {label:<9}: template not found; {effect}")

    native, redirects, detail = resolve_native_lists(arm9, overlays)
    if native:
        values.update(native)
        for site, symbol in redirects:
            if take_over:
                struct.pack_into("<I", arm9, site - ARM9_RAM,
                                 meta["symbols"][symbol] | 1)
        log(f"  Lists    : the game's top-screen list; {detail}")
    else:
        log(f"  Lists    : {detail}; script lists keep the touch screen")

    return values, 0


def app_table(arm9: bytes, overlays):
    """The app table entries, Origin edition.

    Only the evolution scene's entry still carries its retail bytes; name entry
    was rewritten by hg-engine and is left out, which makes the hook leave that
    app alone.
    """
    out = []
    for name, callback, swap, sig, ovy_id, mask in APP_TABLE:
        if ovy_id is None:
            if not callback:
                out.append((name, 0, swap, False))
                continue
            off = (callback & ~1) - ARM9_RAM
            ok = 0 <= off and arm9[off:off + len(sig)] == sig
            out.append((name, callback, swap, ok))
            continue
        ov = overlays.get(ovy_id)
        found = []
        if ov is not None:
            found = regions._find_masked(ov.data, ov.ramAddress, sig, mask) \
                if sig else []
        if len(found) == 1:
            out.append((name, found[0] | 1, swap, True))
        else:
            out.append((name, callback or 0, swap, False))
    return out
