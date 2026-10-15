"""Rasterise the battle command labels from the ROM being patched.

The top-screen command menu draws real text - the game's own words, in the game's
own font, pulled out of the ROM at patch time. Nothing is hardcoded per language:
both the strings and the glyphs come from the dump, so a French build says
ATTAQUE / SAC / POKéMON / FUITE and an English one says FIGHT / BAG / POKéMON /
RUN without this file knowing which is which.

Everything here is offline. The hook does no text rendering at runtime - it
memcpys finished 4bpp tiles into the message window. That keeps the resident code
free of heap, font and MsgData plumbing, and lets the output be checked as a PNG
before the ROM is ever booted.

Where the data lives, and how it was confirmed
----------------------------------------------
Strings: NARC `a/0/2/7` (pret's NARC_msgdata_msg = 27), file 197 = msg_0197,
entries 924 FIGHT / 925 BAG / 926 POKEMON / 927 RUN
(src/battle/battle_input.c:1899-1912). Gen-IV message archives obfuscate both the
offset table and the text with the same two LCGs used everywhere in the series.

Font: NARC `a/0/1/6` (NARC_graphic_font = 16), file 1 - fontId 1 is what the
battle message box prints with, `AddTextPrinterParameterized(window, 1, ...)` in
BattleSystem_PrintBattleMessage (src/battle/battle_system.c:1421). ndspy's NARC
reader returns the five font files as empty, so this module parses BTAF/GMIF
itself; the archive's own file table gives 33101 bytes each.

Format (pret's struct FontHeader, src/font_data.c:15):

    u32 headerSize      16
    u32 widthDataStart  32592  == 16 + 509 * 64, which is the whole check
    u32 numGlyphs       509
    u8  fixedWidth, fixedHeight, glyphWidth, glyphHeight    16,16,2,2

so glyphs are 16x16 (GLYPHSHAPE_16x16), 64 bytes each: four 8x8 tiles of 2bpp at
+0x00 +0x10 +0x20 +0x30, placed TL, TR, BL, BR - the neighbour offsets in
DecompressGlyphTiles_FromPreloaded are +0x20 across and +0x40 down. Two bits per
pixel, most significant pair leftmost, high byte of each u16 first. One width byte
per glyph at widthDataStart. Glyph index is the character code minus one
(TryLoadGlyph, src/font_data.c:150).

Pixel values map to the message window's own palette, which is palette 11 of main
BG. Confirmed twice over: dumped live from 0x05000160 in a real battle, and stated
outright by pret's sFontInfos (src/font.c:28) as fgColor 1, bgColor 15,
shadowColor 2.
"""

import struct
import zlib

from . import themes

# --- palette 11 indices, per sFontInfos and the live dump --------------------
FG, SHADOW, PAPER = 1, 2, 15
HILITE = 12                     # 0x62FF, the salmon already in palette 11

# 2bpp glyph value -> palette index. 0 is "outside the glyph box" and 3 is the
# box's own background; both are paper.
VALUE_MAP = {0: PAPER, 1: FG, 2: SHADOW, 3: PAPER}

MSGDATA_NARC = "a/0/2/7"
MSGDATA_FILE = 197
FONT_NARC = "a/0/1/6"
FONT_FILE = 1                   # sFontArcParam[1][0], src/font.c:19
FONT_HEADER_SIZE = 16           # pret's struct FontHeader

# msg_0197 entries, in the order the hook indexes them. This is command order,
# matching BATTLE_INPUT_FIGHT/BAG/POKEMON/RUN.
LABEL_MSGS = (924, 925, 926, 927)

# The generic yes/no pair, from the same archive: 940 and 941. Every two-option
# battle prompt gets these rather than its own wording. The bottom screen phrases
# them per question - "Changer de Pokemon" / "Continuer le combat" - but the
# choice underneath is always binary, and a fixed Oui/Non pair reads faster on a
# scene you are already looking at than a sentence would. Decoded: Oui/Non in
# French, Yes/No in English, so this stays language-neutral like the rest.
YESNO_MSGS = (940, 941)

# The grid, in tiles, inside the battle message window. window[0] is 27 tiles
# wide starting at baseTile 31; we take the right-hand columns, which is the
# blank space the message text never reaches.
#
# 14 columns rather than the 12 first tried. The only message on screen while
# this menu is up is "What will <NAME> do?", whose longest line is the fixed part
# - 14 glyphs at 6px is 84px, under 11 tiles - and the name wraps onto the second
# line below it. 14 columns leaves 13 (104px) for that, a 20px margin, and gives
# the bottom row 22px of slack to space three words with. At 12 columns the slack
# was 6px and BAG/RUN/POKEMON ran together into one word.
GRID_COLS = 14
GRID_ROWS = 4
GRID_BASE_COL = 13
WIN_STRIDE = 27
WIN_BASE_TILE = 31

# The yes/no prompt gets its own, much smaller box. It cannot reuse the command
# grid: the blit paints its whole area, including the paper between the words, so
# a 14-tile-wide box wipes out the right-hand end of a question that is long
# enough to reach it - which is exactly what "Voulez-vous changer de Pokemon?"
# does. Three tiles is enough for Oui/Non/Yes/No (18px at the widest) and leaves
# 24 tiles, 192px, for the question.
YN_COLS = 3
YN_BASE_COL = 24

# Oak's speech asks the only questions in the game that come before you have a
# save file, and it asks them on the same tile rectangle again - dialogWindow is
# GF_BG_LYR_MAIN_0, x=2 y=19, 27x4, from sWindowTemplate_DialogMsg. Only the
# layer underneath differs, for the third time:
#
#              battle window[0]   field dialog box   Oak dialogWindow
#   layer      MAIN_1             MAIN_3             MAIN_0
#   char base  0x06004000         0x06008000         0x06018000
#   base tile  31                 0x237              0x36D
#   palette    11                 12                 6
#
# Oak's char base is GX_BG_CHARBASE_0x18000 in src/oaks_speech.c's own BgTemplate.
# The window is filled with 0xF (FillWindowPixelRect), and pret's sFontInfos
# fixes ink/shadow at 1/2. Oak's native text therefore uses 1/2/15. Selected
# bands use otherwise-unused index 12; the runtime hook fills that entry from
# Oak's live edition palette (blue/silver in SS, gold in HG) and keeps white text
# by applying the same selected-glyph inversion used before.
# The battle message window's own base: GF_BG_LYR_MAIN_1 with charBase 1, and
# engine A's DISPCNT character-base offset is 0 - both dumped live mid-battle.
BATTLE_CHAR_BASE = 0x06004000
FIELD_CHAR_BASE = 0x06008000
FIELD_BASE_TILE = 0x237
OAK_CHAR_BASE = 0x06018000
OAK_BASE_TILE = 0x36D

# Oak's own yes/no, from a different archive to the battle pair: msg_0219
# entries 47 and 48. OUI/NON in French, YES/NO in English.
OAK_MSGDATA_FILE = 219
OAK_YESNO_MSGS = (47, 48)

# The gender question does have words after all - msg_0286 entries 7 and 16, whose
# row ids in the decomp are literally msg_0286_boy and msg_0286_girl. GARCON and
# FILLE in French, BOY and GIRL in English, so this stays language-neutral like
# the rest, and reads better than the charmap's bare male/female symbols.
#
# Laid out side by side rather than stacked, because that is how the game reads
# it: OakSpeech_GenderSelectHandleInput moves on PAD_KEY_LEFT and PAD_KEY_RIGHT,
# unlike the confirmations, which go through the generic multichoice handler on
# UP and DOWN. Stacking them would have implied the wrong keys.
#
# 36px + 30px plus a gap is 74px, so a 10-tile box. That leaves 17 tiles, 136px,
# for the question - "Ou bien une fille?" is about 108px.
GENDER_MSGDATA_FILE = 286
GENDER_MSGS = (7, 16)
GENDER_COLS = 10
GENDER_BASE_COL = 17
GENDER_CELL_W = GENDER_COLS * 8

# The overworld start menu (X), drawn onto the world itself. Unlike every box
# above, there is no window to borrow: the world fills the screen. So this one
# writes a TILEMAP as well as tile pixels, onto GF_BG_LYR_MAIN_3 - priority 0,
# in front of the 3D world, enabled and transparent the whole time you walk
# (src/field/fieldmap.c:464-535, src/gf_3d_render.c:46-48).
#
# Tiles go after the menu's own graphic. Task_StartMenu loads a/0/1/4 file 12 at
# tile 0 of MAIN_3 (src/start_menu.c:468); that file is 4160 bytes uncompressed,
# so 130 tiles, and the map-name window - the only permanently allocated one -
# starts at 0x197. Everything between is scratch belonging to script menus and
# the mart, none of which can be open while the start menu is. Double-booking a
# tile range against UI that never coexists is the game's own habit: script
# yes/no lives at 0x21F, inside the map-name window's range (src/scrcmd_c.c:131).
STARTMENU_MSGDATA_FILE = 196
TRAINER_MSGDATA_FILE = 282
TRAINER_MSG = 5

# StartMenuAction -> the label we draw for it. The ids are the enum at
# src/start_menu.c:49. msg_0196 entry 3 is the trainer card, but it decodes to a
# bare {STRVAR_1} - the game expands it to the player's name at runtime, which
# patch-time rasterisation cannot know - so that row takes msg_0282 entry 5
# instead: DRESSEUR in French, TRAINER in English, still the ROM's own words.
# Actions with no label of their own (the two registered-item buttons the game
# always appends, and the Union Room pair) fall through to the blank strip.
STARTMENU_LABELS = (
    (0,  STARTMENU_MSGDATA_FILE, 0),        # POKEDEX
    (1,  STARTMENU_MSGDATA_FILE, 1),        # POKEMON
    (2,  STARTMENU_MSGDATA_FILE, 2),        # BAG
    (3,  TRAINER_MSGDATA_FILE, TRAINER_MSG),  # TRAINER_CARD -> DRESSEUR
    (4,  STARTMENU_MSGDATA_FILE, 4),        # SAVE
    (5,  STARTMENU_MSGDATA_FILE, 5),        # OPTIONS
    (6,  STARTMENU_MSGDATA_FILE, 6),        # RUNNING_SHOES is really EXIT
    (8,  STARTMENU_MSGDATA_FILE, 8),        # RETIRE
    (11, STARTMENU_MSGDATA_FILE, 14),       # POKEGEAR
)
SM_ACTIONS = 16                 # the enum runs 0..12; 16 keeps the table aligned

# What lives in each cell, and the inhibit bit that gates it.
#
# This is the grid the touch menu actually uses - ov27_0225CFC8's first row - and
# the important part is that it is FIXED. An entry you have not earned leaves its
# slot EMPTY; the list does not close up. Early in the game the real menu shows
# SAC alone in the left column at row 2, with the trainer card, SAUVER and
# OPTIONS down the right, because POKEDEX, POKEMON and POKEGEAR are missing from
# their own slots rather than absent from a list.
#
# Availability comes from StartMenuTaskData.inhibitIconFlags, which is the gate
# the game itself computes (FieldSystem_GetStartMenuButtonInhibitFlags_Normal,
# src/start_menu.c:288). Bit numbers are StartMenuActionDisable, a DIFFERENT
# enum from StartMenuAction - POKEGEAR is action 11 but disable bit 9.
SM_CELL_PLAN = (
    (0,  0),                    # cell 0  POKEDEX
    (1,  1),                    # cell 1  POKEMON
    (2,  2),                    # cell 2  BAG
    (11, 9),                    # cell 3  POKEGEAR
    (3,  3),                    # cell 4  TRAINER_CARD
    (4,  4),                    # cell 5  SAVE
    (5,  5),                    # cell 6  OPTIONS
    (None, None),               # cell 7  empty in this layout
)

# This plan is the NORMAL layout's, and it is now only the fallback: the hook
# uses it for the few frames the touch app cannot be read, telling the normal
# menu apart by its inhibit flags (SM_NORMAL_MASK in src/hook.s).
#
# Normally the hook reads the touch menu app itself (TouchscreenMenuData,
# src/touchscreen_menu.c), which knows which of the game's seven layouts is up,
# which icons it shows and which slot is selected. The layouts are the game's
# own table, sTouchscreenMenuLayouts - overlay 27 at 0x0225CFC8 in the US ROM -
# one icon per slot, slots 0-3 down the left column and 4-6 down the right:
#
#     0 normal        POKEDEX POKEMON BAG POKEGEAR | TRAINER SAVE OPTIONS
#     1 Safari        RETIRE POKEDEX POKEMON BAG | POKEGEAR TRAINER OPTIONS
#     2 Bug Contest   RETIRE POKEDEX POKEMON POKEGEAR | TRAINER OPTIONS (mon)
#     3 Pal Park      RETIRE POKEDEX POKEMON POKEGEAR | TRAINER OPTIONS (ball)
#     4 Union Room    CHAT POKEDEX POKEMON BAG | LOG TRAINER OPTIONS
#     5 Colosseum     POKEMON BAG TRAINER OPTIONS
#     6 Tower room    POKEMON TRAINER OPTIONS
#
# The patcher checks the table against the ROM's own overlay 27 before using
# it; if it is not there, only the normal layout is drawn.
TOUCH_LAYOUTS = (
    (0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x0D),
    (0x07, 0x00, 0x01, 0x02, 0x03, 0x04, 0x06, 0x08),
    (0x07, 0x00, 0x01, 0x03, 0x04, 0x06, 0x0A, 0x0D),
    (0x07, 0x00, 0x01, 0x03, 0x04, 0x06, 0x09, 0x0D),
    (0x0B, 0x00, 0x01, 0x02, 0x0C, 0x04, 0x06, 0x0D),
    (0x01, 0x02, 0x04, 0x06, 0x0D, 0x0D, 0x0D, 0x0D),
    (0x01, 0x04, 0x06, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D),
)
TOUCH_N_ICONS = 7               # slots that hold a selectable icon
# Touch icon (sTouchscreenMenuIcons) -> the strip that labels it. The icons the
# table marks disabled - the two ball counters and the contest Pokemon - are
# not selectable and get no cell. 11 and 12 are the Union Room's CHAT and LOG.
TOUCH_ICON_LABEL = {0: 0, 1: 1, 2: 2, 3: 11, 4: 3, 5: 4, 6: 5, 7: 8,
                    11: "chat", 12: "log"}
# Labels only the Union Room needs: drawn if they fit the cells the other
# labels already sized, otherwise that one layout swaps instead.
OPTIONAL_LABELS = (("chat", STARTMENU_MSGDATA_FILE, 34),
                   ("log", STARTMENU_MSGDATA_FILE, 35))
SM_N_LAYOUTS = len(TOUCH_LAYOUTS)
SM_PLAN_UNDRAWABLE = 0xFE

# Two columns of four, because that is the grid the D-pad walks: ov27_0225D0B4
# navigates slots 0-3 as the left column and 4-6 as the right, with up/down
# wrapping inside a column and left/right jumping between them. Drawn as a
# single list, DOWN would cycle through the first four entries only.
SM_COLS = 2
SM_ROWS = 4
SM_CELLS = SM_COLS * SM_ROWS
SM_CELL_H = 2                   # tiles - one glyph row
SM_CELL_W_MAX = 9               # refuse rather than clip a long translation

# MAIN_3, from sBgTemplate_3 (src/field/fieldmap.c:479): charBase 0x08000,
# screenBase 0x1000, 256x256 text, 4bpp.
SM_CHAR_BASE = 0x06008000
SM_SCREEN_BASE = 0x06001000
SM_BASE_TILE = 0x84             # clear of the menu's own 130 tiles (0..0x81), and
                                # low enough that the PC box menu's 269 tiles still
                                # end below the map-name window at 0x197
SM_ORIGIN_Y = 0                 # flush into the top-right corner
SM_FRAME = 1                    # tiles of border on every side - the tilemap's minimum
SM_BORDER_PX = 3                # of those 8 pixels, how many are actually grey

# Our own palette rather than one the game loads, so the colours are known
# rather than guessed. Slots 1-5, 7, 8 and 15 are unclaimed in the plain
# overworld; 7 and 8 sit above the ones map_preview_graphic.c would overwrite on
# a route card, which cannot play while the menu is up anyway.
SM_PAL_NORM = 7
SM_PAL_HI = 8
PAL_RAM_MAIN_BG = 0x05000000

_bgr555 = themes.bgr555

# index 0 stays transparent; 1/2/15 are ink, shadow and paper, matching the
# indices the font rasteriser already emits. 3 and 4 are the border, which keeps
# the same colour in both palettes - the frame is drawn once and never
# highlights. The actual values come from the chosen theme; these two names are
# rebound per build by _use_theme() below.
BORDER, BORDER_DK = themes.BORDER, themes.BORDER_DK
SM_PAL_NORM_RGB, SM_PAL_HI_RGB = themes.THEMES[themes.DEFAULT_THEME]["panel"]


def _use_theme(name):
    """Point the panel palettes at one theme, and return it.

    Module-level rather than threaded through every call because the palettes
    are read from a dozen places - the two pool builders and the PNG preview -
    and a build only ever uses one theme.
    """
    global SM_PAL_NORM_RGB, SM_PAL_HI_RGB
    theme = themes.get(name)
    SM_PAL_NORM_RGB, SM_PAL_HI_RGB = theme["panel"]
    return theme

# --- the script list menus: the shop's and the PC's ---------------------------
#
# One mechanism covers them all, because they are all the same object: a script
# builds a menu (ScrCmd_064/066), overlay 27's touch controller renders it, and
# the controller keeps a pointer straight back to it. Verified across five
# savestates - the shop, both PC lists and the PC box menu all arrive here.
#
# The menu cannot be recognised by message id: ScriptMenu_AppendListItem reads
# each id into a string and throws the id away. What survives is the expanded
# text, so a menu is identified by its entry COUNT, the characters of its FIRST
# entry, and a hash of the rest (see OneScreen_ListMatch). Every menu here has a
# first entry free of placeholders, which matters - the player's own PC row
# expands to their name and could never be matched, so it is left out of the
# hash. The first entry alone was not enough: the Pokeathlon Dome's marts read
# BUY / INFO / SEE YA and were drawn as the shop.
LIST_MSGDATA_FILE = 191
LIST_KEY_MAX = 16               # codes COMPARED; the full length is checked too,
                                # so a longer first entry still identifies exactly
LIST_MAX_ENTRIES = 8
LIST_MENU_RECORD = 56
LIST_CELL_H = 2                 # tiles per entry - one glyph row
LIST_FRAME_TILES = 9            # the border, shared with the X menu's frame

# The one label in this file that is NOT the ROM's own words. The game builds
# your own PC's row from a placeholder and your name, so there is nothing to
# extract - it has to be written out. Only the play-tested languages are listed;
# anything else falls back to the trainer card's word, which does come from the
# ROM and so stays correct in every language.
SELF_PC = None                  # sentinel for that entry in LIST_MENUS
SELF_PC_TEXT = {
    "F": "MON PC",
    "E": "MY PC",
}


def _ascii_codes(text: str):
    """Letters and spaces to the game's own character codes."""
    out = []
    for ch in text:
        if ch == " ":
            out.append(478)
        elif "A" <= ch <= "Z":
            out.append(299 + ord(ch) - ord("A"))
        else:
            raise LabelError(f"{ch!r} has no code in this charmap")
    return out


def _menu_hash(entries, skip: int) -> int:
    """The hash OneScreen_ListHash computes over a live menu's Strings.

    h = h * 31 + code per character, then once more with 0xFFFF between entries,
    kept to 16 bits, over every entry whose bit in `skip` is clear.
    """
    h = 0
    for i, codes in enumerate(entries):
        if skip >> i & 1:
            continue
        for code in codes:
            h = (h * 31 + code) & 0xFFFF
        h = (h * 31 + 0xFFFF) & 0xFFFF
    return h


# Each menu: a name, its entries as (msgdata file, index) in screen order, and
# how many text lines an entry takes. The first entry is the identifying key, so
# it must never hold a placeholder.
#
# `layout` is where each entry sits, as (row, column); None means a plain single
# column. Only the PC box menu needs one - it is a 2x3 grid with SALUT! alone in
# the right of the bottom row, which is where its cursor expects to find it.
LIST_MENUS = (
    # ACHETER / VENDRE / QUITTER
    ("shop", ((LIST_MSGDATA_FILE, 321), (LIST_MSGDATA_FILE, 322),
              (LIST_MSGDATA_FILE, 323)), 1, None),
    # PC DE LEO / <your PC> / PANTHEON / DECONNEXION. The second entry is
    # msg_0191 63, which expands to the player's name at runtime and cannot be
    # rasterised, so it uses the written-out MON PC / MY PC instead.
    # 66 and 75 are easy to swap: French reads them DECONNEXION and ETEINDRE,
    # English SWITCH OFF and LOG OUT - the pairing is inverted between the two.
    # The indices below are the ones the game itself uses, taken from screenshots
    # of both menus rather than from what the English words suggest.
    ("pc_select", ((LIST_MSGDATA_FILE, 62), (SELF_PC, 0),
                   (LIST_MSGDATA_FILE, 64), (LIST_MSGDATA_FILE, 66)), 1, None),
    # BOITE AUX LETTRES / CAPSULES BALL / ALBUM PHOTO / ETEINDRE
    ("pc_item", ((LIST_MSGDATA_FILE, 73), (LIST_MSGDATA_FILE, 74),
                 (LIST_MSGDATA_FILE, 65), (LIST_MSGDATA_FILE, 75)), 1, None),
    # DEPOSER / RETIRER / DEPLACER POKeMON, DEPLACER OBJETS, SALUT! - the only
    # menu here whose entries are two lines, and the only one that is a grid.
    ("pc_box", ((LIST_MSGDATA_FILE, 67), (LIST_MSGDATA_FILE, 68),
                (LIST_MSGDATA_FILE, 69), (LIST_MSGDATA_FILE, 70),
                (LIST_MSGDATA_FILE, 72)), 2,
     ((0, 0), (0, 1), (1, 0), (1, 1), (2, 1))),
)

CELL_H = GRID_ROWS * 8          # 32 px
ROW_H = 16                      # one glyph tall
CELL_W = GRID_COLS * 8          # 112 px
YN_CELL_W = YN_COLS * 8         # 24 px

BLOB_MAGIC = b"1SLB"

# Four unique sets of images, referenced by five geometry records in the blob
# header so the hook carries no dimensions of its own:
#
#   set 0, 14 tiles wide   0..3 the root command menu, one per command
#                          4    all paper, to take the menu down
#   set 1, 3 tiles wide    0,1  the two-option prompt, top and bottom
#                          2    all paper
#
# The battle and field yes/no geometries both reference set 1. Their tile data
# is identical, but their rows live in different MAIN BG character bases.
#
# The wipe is the last image of each set rather than a special case, so taking a
# menu down is the same code path as putting one up - and each set wipes only its
# own area, which is what keeps the narrow prompt from clearing the question.
CMD_IMAGES = 5
YN_IMAGES = 3

# Byte offset from the main-engine BG character base to each tile row of a box.
# Precomputed so the resident code is a pair of copy loops with no
# multiplication: a window row is contiguous but strides by the whole 27-tile
# window width to reach the next one.
def _row_addrs(char_base, base_tile, base_col):
    """Absolute VRAM address of each tile row of a box.

    Absolute rather than an offset from one base, because the three boxes sit on
    three different character bases - the hook holds no address of its own and
    simply copies where it is told.
    """
    return tuple((char_base + (base_tile + r * WIN_STRIDE + base_col) * 32)
                 for r in range(GRID_ROWS))


OAK_IMAGES = 3                  # yes/no pair, wipe
GENDER_IMAGES = 3               # the two options, wipe
GEO_RECORD = 28                 # data_off, image_bytes, row_bytes, images, 4 row addrs
GEO_COUNT = 5                   # command, battle yes/no, Oak, gender, field yes/no
SM_PLANS_OFF = 528              # u8 strip[8] per touch layout; see _startmenu
BLOB_HEADER = SM_PLANS_OFF + 8 * len(TOUCH_LAYOUTS)

# The start menu's record does not fit the shape above - it describes a pool of
# tiles and a tilemap rather than finished images - so it gets its own block at a
# fixed offset, immediately after the five 28-byte records that end at 148.
#
#   +0x00 u32  tiles_off        blob offset of the strip pool
#   +0x04 u32  tiles_bytes
#   +0x08 u32  tiles_dest       VRAM address for the pool
#   +0x0C u32  pal_off          blob offset of the two 32-byte palettes
#   +0x10 u32  pal_dest         palette RAM address of the normal palette
#   +0x14 u16  base_tile        tile index the pool loads at
#   +0x16 u8   strip_tiles      tiles in one label strip
#   +0x17 u8   cell_w           tiles across one cell
#   +0x18 u8   cell_h           tile rows in one cell
#   +0x19 u8   n_cells
#   +0x1A u8   pal_norm
#   +0x1B u8   pal_hi
#   +0x1C u8   n_labels
#   +0x1D u8   blank             index of the all-paper strip
#   +0x20 u8   cell_label[8]     strip per cell, 0xFF if the cell is never used
#   +0x28 u8   cell_bit[8]       inhibit bit gating it, 0xFF if never inhibited
#   +0x30 u32  cell_rows[16]     absolute tilemap address, n_cells x cell_h
#   +0x70 u32  frame_off         blob offset of the border's tilemap
#   +0x74 u32  frame_base        tilemap address of the border's top-left cell
#   +0x78 u8   frame_rows
#   +0x79 u8   frame_cols
SM_RECORD_OFF = 148
SM_RECORD_SIZE = 0x7C

# The script list menus get their own record, after the start menu's. Unlike the
# X menu this one carries almost no addresses: the entry count is not known until
# a menu opens, so the panel is sized at runtime and the hook works the tilemap
# addresses out for itself.
#
#   +0x00 u32  tiles_off      blob offset of the pool: 9 frame tiles, then strips
#   +0x04 u32  tiles_dest     VRAM address the pool loads at
#   +0x08 u32  pal_off        blob offset of the two palettes
#   +0x0C u32  pal_dest       palette RAM address of the normal one
#   +0x10 u32  screen_base    MAIN_3 tilemap origin
#   +0x14 u16  base_tile
#   +0x16 u8   n_menus
#   +0x17 u8   pal_norm
#   +0x18 u8   pal_hi
#   +0x1C      menu[n_menus], LIST_MENU_RECORD bytes each:
#                +0x00 u16 strip_off    byte offset of its strips within the pool
#                +0x02 u16 strip_tiles  tiles in one entry's strip
#                +0x04 u8  n_entries
#                +0x05 u8  cell_w
#                +0x06 u8  cell_h
#                +0x07 u8  key_len      codes in the identifying first entry
#                +0x08 u8  n_cols, +0x09 u8 n_rows
#                +0x0A u16 key[LIST_KEY_MAX]
#                +0x2A u8  pos[LIST_MAX_ENTRIES]
#                +0x32 u16 hash         _menu_hash over the entries not skipped
#                +0x34 u8  skip         bit i = entry i is not in the hash
LIST_RECORD_OFF = 272
LIST_RECORD_HEAD = 0x1C
CMD_ROW_BYTES = GRID_COLS * 32
CMD_IMAGE_BYTES = CMD_ROW_BYTES * GRID_ROWS
YN_ROW_BYTES = YN_COLS * 32
YN_IMAGE_BYTES = YN_ROW_BYTES * GRID_ROWS
GENDER_ROW_BYTES = GENDER_COLS * 32
GENDER_IMAGE_BYTES = GENDER_ROW_BYTES * GRID_ROWS
BLOB_SIZE = (BLOB_HEADER + CMD_IMAGES * CMD_IMAGE_BYTES
             + (YN_IMAGES + OAK_IMAGES) * YN_IMAGE_BYTES
             + GENDER_IMAGES * GENDER_IMAGE_BYTES)


class LabelError(Exception):
    """The labels could not be built from this ROM."""


# ---------------------------------------------------------------------------
# Archive reading
# ---------------------------------------------------------------------------

def _narc_files(data: bytes):
    """Return the subfiles of a NARC, by parsing BTAF and GMIF directly.

    ndspy is used everywhere else, but it hands back empty buffers for the font
    archive's first five files, which the archive's own FAT says are 33101 bytes
    each. Reading the table ourselves is a dozen lines and removes the doubt.
    """
    if data[:4] != b"NARC":
        raise LabelError("not a NARC archive")
    off = struct.unpack_from("<H", data, 12)[0]         # header size
    magic, block, count = struct.unpack_from("<4sII", data, off)
    if magic != b"BTAF":
        raise LabelError(f"expected BTAF, found {magic!r}")
    fat = [struct.unpack_from("<II", data, off + 12 + i * 8) for i in range(count)]
    off += block
    off += struct.unpack_from("<I", data, off + 4)[0]   # skip BTNF
    magic = data[off:off + 4]
    if magic != b"GMIF":
        raise LabelError(f"expected GMIF, found {magic!r}")
    base = off + 8
    return [data[base + s:base + e] for s, e in fat]


NEWLINE = 0xE000                # the line break inside a two-line menu entry


def _decode_raw(archive: bytes, index: int):
    """Return one message from a Gen-IV .gmm exactly as stored, control codes
    and terminator included."""
    count, key = struct.unpack_from("<HH", archive, 0)
    if not 0 <= index < count:
        raise LabelError(f"message {index} out of range (archive holds {count})")
    k = (key * (index + 1) * 0x2FD) & 0xFFFF
    k |= k << 16
    off, length = struct.unpack_from("<II", archive, 4 + index * 8)
    off ^= k
    length ^= k
    if off + length * 2 > len(archive):
        raise LabelError(f"message {index} runs past the end of the archive")
    k2 = (0x91BD3 * (index + 1)) & 0xFFFF
    out = []
    for j in range(length):
        out.append(struct.unpack_from("<H", archive, off + j * 2)[0] ^ k2)
        k2 = (k2 + 0x493D) & 0xFFFF
    return out


def _decode_message(archive: bytes, index: int, keep_break: bool = False):
    """Return one message from a Gen-IV .gmm as raw character codes."""
    out = _decode_raw(archive, index)
    # Messages are terminated by 0xFFFF; control codes start at 0xE000. Most
    # labels contain none, but the PC box menu's entries are two lines and the
    # break between them is 0xE000 itself, so that one asks to keep it.
    if keep_break:
        return [c for c in out if c < 0xE000 or c == NEWLINE]
    return [c for c in out if c < 0xE000]


# ---------------------------------------------------------------------------
# Font
# ---------------------------------------------------------------------------

class Font:
    def __init__(self, blob: bytes):
        (self.header_size, self.width_start, self.num_glyphs,
         _fw, _fh, gw, gh) = struct.unpack_from("<IIIBBBB", blob, 0)
        if self.header_size != FONT_HEADER_SIZE or (gw, gh) != (2, 2):
            raise LabelError(
                f"unexpected font shape: headerSize={self.header_size} "
                f"glyph={gw}x{gh} tiles (wanted 16 and 2x2)")
        self.glyph_size = gw * gh * 16
        expect = self.header_size + self.num_glyphs * self.glyph_size
        if expect != self.width_start:
            raise LabelError(
                f"font header is inconsistent: {self.num_glyphs} glyphs of "
                f"{self.glyph_size} bytes after a {self.header_size}-byte header "
                f"ends at {expect}, but widthDataStart says {self.width_start}")
        if len(blob) < self.width_start + self.num_glyphs:
            raise LabelError("font file is shorter than its own width table")
        self.blob = blob

    def _index(self, code: int) -> int:
        if not 1 <= code <= self.num_glyphs:
            raise LabelError(f"character {code:#06x} is not in this font")
        return code - 1

    def width(self, code: int) -> int:
        return self.blob[self.width_start + self._index(code)]

    def glyph(self, code: int):
        """Return a 16x16 grid of palette indices."""
        base = self.header_size + self._index(code) * self.glyph_size
        px = [[PAPER] * 16 for _ in range(16)]
        for tile, (ox, oy) in enumerate(((0, 0), (8, 0), (0, 8), (8, 8))):
            top = base + tile * 16
            for row in range(8):
                half = struct.unpack_from("<H", self.blob, top + row * 2)[0]
                for bi, byte in enumerate(((half >> 8) & 0xFF, half & 0xFF)):
                    for p in range(4):
                        v = (byte >> (6 - 2 * p)) & 3
                        px[oy + row][ox + bi * 4 + p] = VALUE_MAP[v]
        return px


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def _text_width(font: Font, codes) -> int:
    return sum(font.width(c) for c in codes)


def _layout(font: Font, labels):
    """Place the four labels and return [(x, y, codes, rect), ...].

    The arrangement follows the game's own cursor grid rather than a free choice
    (sCursorArrayMainMenu, src/battle/battle_input.c:281):

        { FIGHT, FIGHT, FIGHT }
        { BAG,   RUN,   POKEMON }

    FIGHT spans the top, the other three sit along the bottom in that order. The
    hook mirrors the game's cursor instead of driving it, so drawing any other
    arrangement would make the D-pad appear to move diagonally. It is also the
    layout of the touch menu the player already knows.
    """
    fight, bag, pokemon, run = labels
    out = []

    # Top row: FIGHT centred across the full width.
    w = _text_width(font, fight)
    out.append(((CELL_W - w) // 2, 0, fight, (0, 0, CELL_W, ROW_H)))

    # Bottom row: BAG, RUN, POKEMON left to right, gaps shared evenly.
    bottom = [bag, run, pokemon]
    widths = [_text_width(font, c) for c in bottom]
    slack = CELL_W - sum(widths)
    if slack < 0:
        raise LabelError(
            f"the bottom row needs {sum(widths)}px but only {CELL_W}px are "
            f"available; widen GRID_COLS or shorten the labels")
    gap = slack // (len(bottom) + 1)
    x = gap + (slack - gap * (len(bottom) + 1)) // 2
    for codes, w in zip(bottom, widths):
        out.append((x, ROW_H, codes, (x - gap // 2, ROW_H,
                                      w + gap, ROW_H)))
        x += w + gap
    # Reorder to command order: FIGHT, BAG, POKEMON, RUN.
    top, b_bag, b_run, b_pokemon = out
    return [top, b_bag, b_pokemon, b_run]


def _layout_yesno(font: Font, choices):
    """Place the two-option prompt: one choice above the other, both centred.

    The cursor for these menus is 1 wide and 2 tall
    (BattleCursor_CheckKeyInput(cursor, 1, 2, ...) in
    BattleInput_CursorMove_TwoOptionsMenu), so menuY alone picks the answer and
    stacking them matches how the D-pad moves.
    """
    out = []
    for i, codes in enumerate(choices):
        w = _text_width(font, codes)
        y = i * ROW_H
        out.append((((YN_CELL_W - w) // 2, y, codes, (0, y, YN_CELL_W, ROW_H))))
    return out


def _inside(rect, x, y):
    x0, y0, w, h = rect
    return x0 <= x < x0 + w and y0 <= y < y0 + h


def _layout_row(font: Font, items, cell_w):
    """Place two options side by side, centred, for a left/right choice."""
    widths = [_text_width(font, c) for c in items]
    gap = 8
    total = sum(widths) + gap * (len(items) - 1)
    if total > cell_w:
        raise LabelError(f"the row needs {total}px but only {cell_w}px are available")
    x = (cell_w - total) // 2
    out = []
    for codes, w in zip(items, widths):
        out.append((x, 0, codes, (x - gap // 2, 0, w + gap, ROW_H)))
        x += w + gap
    return out


def _render(font: Font, placed, selected, width=CELL_W, invert=False):
    """Return a `width` x CELL_H grid of palette indices.

    `invert` makes selected ink white and suppresses its shadow. Every selected
    band uses index 12: battle/field already load their accent there, while the
    runtime Oak hook copies the edition-specific intro colour into palette 6/12.
    """
    band = HILITE
    sel_rect = placed[selected][3] if selected is not None else None
    canvas = [[PAPER] * width for _ in range(CELL_H)]
    if sel_rect is not None:
        x0, y0, w, h = sel_rect
        for y in range(y0, min(y0 + h, CELL_H)):
            for x in range(max(x0, 0), min(x0 + w, width)):
                canvas[y][x] = band
    for x, y, codes, _rect in placed:
        for code in codes:
            glyph = font.glyph(code)
            w = font.width(code)
            for gy in range(16):
                ty = y + gy
                if not 0 <= ty < CELL_H:
                    continue
                for gx in range(w):
                    tx = x + gx
                    if not 0 <= tx < width:
                        continue
                    v = glyph[gy][gx]
                    if v == PAPER:          # keep the highlight showing through
                        continue
                    if invert and sel_rect is not None and _inside(sel_rect, tx, ty):
                        if v != FG:
                            continue        # the shadow vanishes into the band
                        v = PAPER           # and the ink reads as paper on it
                    canvas[ty][tx] = v
            x += w
    return canvas


def _render_strip(font: Font, codes, width, height):
    """Return one label on its own paper, centred - a menu cell.

    No selected/unselected variants: the panel highlights by pointing the cell's
    tilemap entries at a different palette, so one set of pixels serves both.
    A 0xE000 in `codes` breaks the label onto a second line, which is how the PC
    box menu's entries are written.
    """
    lines = [[]]
    for code in codes:
        if code == NEWLINE:
            lines.append([])
        else:
            lines[-1].append(code)
    lines = [ln for ln in lines if ln] or [[]]

    canvas = [[PAPER] * width for _ in range(height)]
    top = (height - ROW_H * len(lines)) // 2
    for row, line in enumerate(lines):
        x = (width - _text_width(font, line)) // 2
        y = top + row * ROW_H
        for code in line:
            glyph = font.glyph(code)
            w = font.width(code)
            for gy in range(ROW_H):
                ty = y + gy
                if not 0 <= ty < height:
                    continue
                for gx in range(w):
                    tx = x + gx
                    if 0 <= tx < width and glyph[gy][gx] != PAPER:
                        canvas[ty][tx] = glyph[gy][gx]
            x += w
    return canvas


def _to_tiles(canvas, cols=GRID_COLS, rows=GRID_ROWS) -> bytes:
    """Pack a pixel grid into 4bpp DS tiles, row-major by tile."""
    out = bytearray()
    for trow in range(rows):
        for tcol in range(cols):
            for y in range(8):
                row = canvas[trow * 8 + y]
                for x in range(0, 8, 2):
                    lo = row[tcol * 8 + x] & 0xF
                    hi = row[tcol * 8 + x + 1] & 0xF
                    out.append(lo | (hi << 4))
    return bytes(out)


PACK_MAXLEN = 18                # 4-bit length field, +3
PACK_MAXDISP = 4096             # 12-bit displacement, +1


def _pack(data: bytes) -> bytes:
    """LZ77 over 32-bit WORDS, so every write the hook makes is a word store.

    Byte-granular LZ77 compresses these tiles better (about 25% against 34%) but
    DS VRAM ignores byte writes, so a byte decoder would have to buffer a pending
    half of each halfword and read its own output back to resolve matches. Working
    in words removes that entirely: literals and matches are whole words, matches
    read back with `ldr` and write with `str`, and the decoder is a few dozen
    instructions with nothing subtle in it.

    Stream: u32 output word count, then groups of one flag byte and eight units,
    MSB first. A clear flag is a literal word; a set flag is a two-byte token,
    length = (t >> 12) + 3 words and displacement = (t & 0xFFF) + 1 words.
    Overlapping matches are intended - copying forward one word at a time repeats
    the source, which is how runs of paper encode so small.
    """
    if len(data) % 4:
        raise LabelError("packed data must be a whole number of words")
    words = [struct.unpack_from("<I", data, i)[0] for i in range(0, len(data), 4)]
    out = bytearray(struct.pack("<I", len(words)))
    i = 0
    while i < len(words):
        flags = 0
        chunk = bytearray()
        for unit in range(8):
            if i >= len(words):
                break
            best_len, best_disp = 0, 0
            for disp in range(1, min(PACK_MAXDISP, i) + 1):
                start = i - disp
                length = 0
                while (length < PACK_MAXLEN and i + length < len(words)
                       and words[start + length % disp] == words[i + length]):
                    length += 1
                if length > best_len:
                    best_len, best_disp = length, disp
                if best_len >= PACK_MAXLEN:
                    break
            if best_len >= 3:
                chunk += struct.pack("<H", ((best_len - 3) << 12) | (best_disp - 1))
                flags |= 0x80 >> unit
                i += best_len
            else:
                chunk += struct.pack("<I", words[i])
                i += 1
        out.append(flags)
        out += chunk
    return bytes(out)


def _palette(mapping) -> bytes:
    return b"".join(struct.pack("<H", mapping.get(i, 0)) for i in range(16))


def _frame_tile(top=False, bottom=False, left=False, right=False):
    """One 8x8 border tile.

    The ring is a whole tile wide because a tilemap has no finer unit, but only
    the outer SM_BORDER_PX pixels are grey and the rest is panel paper - so the
    border reads as a thin line with a little padding inside it, not a slab.
    A pixel is grey if it is close to any edge this tile faces outward on, which
    gives the corners their L shape without a separate case.
    """
    px = [[PAPER] * 8 for _ in range(8)]
    for y in range(8):
        for x in range(8):
            edges = []
            if top:
                edges.append(y)
            if bottom:
                edges.append(7 - y)
            if left:
                edges.append(x)
            if right:
                edges.append(7 - x)
            if not edges:
                continue
            depth = min(edges)
            if depth < SM_BORDER_PX:
                px[y][x] = BORDER_DK if depth == 0 else BORDER
    return px


# The nine tiles of a frame, in reading order: corners, edges, and the middle -
# which is never seen, since the cells are drawn over it.
FRAME_SHAPES = (
    dict(top=True, left=True),   dict(top=True),    dict(top=True, right=True),
    dict(left=True),             dict(),            dict(right=True),
    dict(bottom=True, left=True), dict(bottom=True), dict(bottom=True, right=True),
)


def _startmenu_labels(archive):
    """Decode the start menu's words, in blob-slot order."""
    out = []
    for action, file_id, msg in STARTMENU_LABELS:
        if file_id >= len(archive):
            raise LabelError(f"{MSGDATA_NARC} has no file {file_id}")
        codes = _decode_message(archive[file_id], msg)
        if not codes:
            raise LabelError(f"start menu message {file_id}#{msg} decoded to nothing")
        out.append((action, codes))
    return out


def _startmenu_cell_w(font: Font, labels) -> int:
    widest = max(_text_width(font, codes) for _a, codes in labels)
    cell_w = (widest + 8 + 7) // 8          # 4px of margin either side
    if cell_w > SM_CELL_W_MAX:
        raise LabelError(
            f"the widest start menu label is {widest}px and needs {cell_w} tiles, "
            f"more than the {SM_CELL_W_MAX} the panel allows")
    return cell_w


def _optional_labels(font: Font, archive, cell_w: int):
    """The Union Room's CHAT / LOG, each only if it fits a cell as already sized.

    They are never allowed to widen the panel - the cells are sized by the
    labels every menu shows - and a missing one simply leaves the Union Room to
    swap, which is what it did before.
    """
    out = []
    for key, file_id, msg in OPTIONAL_LABELS:
        if file_id >= len(archive):
            continue
        try:
            codes = _decode_message(archive[file_id], msg)
        except LabelError:
            continue
        if codes and (_text_width(font, codes) + 8 + 7) // 8 <= cell_w:
            out.append((key, codes))
    return out


def _touch_plans(labels, layouts_ok: bool) -> bytes:
    """One row of eight strip indices per touch layout, for OneScreen_StartMenu.

    0xFF leaves a cell empty. A layout whose labels are not all available - or
    every special layout, when the ROM's own table could not be confirmed - is
    marked SM_PLAN_UNDRAWABLE in its first cell, and the hook swaps for it.
    """
    strip_of = {key: i for i, (key, _codes) in enumerate(labels)}
    out = bytearray()
    for layout, icons in enumerate(TOUCH_LAYOUTS):
        row = bytearray([0xFF]) * SM_CELLS
        ok = layouts_ok or layout == 0
        for slot, icon in enumerate(icons[:TOUCH_N_ICONS]):
            key = TOUCH_ICON_LABEL.get(icon)
            if key is None:
                continue
            if key not in strip_of:
                ok = False
                break
            row[slot] = strip_of[key]
        if not ok:
            row = bytearray([SM_PLAN_UNDRAWABLE]) + bytearray([0xFF]) * (SM_CELLS - 1)
        out += row
    return bytes(out)


def touch_layouts_in(overlays) -> bool:
    """Is the game's own layout table in this ROM's overlay 27, as expected?"""
    try:
        data = bytes(overlays[27].data)
    except Exception:                                   # noqa: BLE001
        return False
    return bytes(b for row in TOUCH_LAYOUTS for b in row) in data


def _startmenu(font: Font, archive, off: int, layouts_ok: bool = True):
    """Return (record, payload, plans) for the overworld menu panel.

    One tile strip per label rather than one finished panel image, because the
    entry list is dynamic - POKEDEX and POKEGEAR only appear once you own them.
    The hook reads the game's own inhibitIconFlags and points each cell's
    tilemap entries at the matching strip, leaving a gap where the touch menu
    leaves one.
    """
    labels = _startmenu_labels(archive)
    cell_w = _startmenu_cell_w(font, labels)
    strip_tiles = cell_w * SM_CELL_H
    # The Union Room's two only if the tile budget below 0x197 still holds with
    # them: the base strips, the blank one, the frame, and these.
    optional = _optional_labels(font, archive, cell_w)
    budget = (0x197 - SM_BASE_TILE - len(FRAME_SHAPES)) // strip_tiles
    if len(labels) + len(optional) + 1 > budget:
        optional = []
    labels = labels + optional
    strip_bytes = strip_tiles * 32

    frame_cols = SM_COLS * cell_w + 2 * SM_FRAME
    frame_rows = SM_ROWS * SM_CELL_H + 2 * SM_FRAME
    frame_x = 32 - frame_cols               # flush into the top-right corner
    frame_y = SM_ORIGIN_Y
    if frame_x < 0 or frame_y + frame_rows > 24:
        raise LabelError(f"the panel is {frame_cols}x{frame_rows} tiles, "
                         f"which does not fit the screen at ({frame_x}, {frame_y})")
    origin_x = frame_x + SM_FRAME
    origin_y = frame_y + SM_FRAME

    pool = bytearray()
    for _action, codes in labels:
        pool += _to_tiles(_render_strip(font, codes, cell_w * 8, SM_CELL_H * 8),
                          cell_w, SM_CELL_H)
    blank = len(labels)                     # the all-paper strip, for empty cells
    pool += bytes([PAPER | (PAPER << 4)]) * strip_bytes
    frame_tile = SM_BASE_TILE + len(pool) // 32
    for shape in FRAME_SHAPES:
        pool += _to_tiles(_frame_tile(**shape), 1, 1)

    if SM_PAL_HI != SM_PAL_NORM + 1:
        raise LabelError("the two palettes must be adjacent: the hook sends both "
                         "in one 64-byte copy from pal_dest")
    pals = _palette(SM_PAL_NORM_RGB) + _palette(SM_PAL_HI_RGB)

    # The border's own tilemap, ready to blit. Its interior entries are included
    # and then overwritten by the cells, which keeps the hook to two flat loops.
    frame_map = bytearray()
    for r in range(frame_rows):
        ry = 0 if r == 0 else (2 if r == frame_rows - 1 else 1)
        for c in range(frame_cols):
            cx = 0 if c == 0 else (2 if c == frame_cols - 1 else 1)
            frame_map += struct.pack(
                "<H", (frame_tile + ry * 3 + cx) | (SM_PAL_NORM << 12))

    slot_of = {action: slot for slot, (action, _codes) in enumerate(labels)}
    cell_label = bytearray([0xFF]) * SM_CELLS       # 0xFF: this cell is never used
    cell_bit = bytearray([0xFF]) * SM_CELLS         # 0xFF: never inhibited
    for cell, (action, bit) in enumerate(SM_CELL_PLAN):
        if action is None:
            continue
        if action not in slot_of:
            raise LabelError(f"cell {cell} wants action {action}, which has no label")
        cell_label[cell] = slot_of[action]
        cell_bit[cell] = bit

    rows = []
    for cell in range(SM_CELLS):
        col, row = cell // SM_ROWS, cell % SM_ROWS
        for r in range(SM_CELL_H):
            ty = origin_y + row * SM_CELL_H + r
            tx = origin_x + col * cell_w
            rows.append(SM_SCREEN_BASE + (ty * 32 + tx) * 2)
    rows += [0] * (16 - len(rows))

    packed = _pack(bytes(pool))
    packed += b"\0" * (-len(packed) % 4)         # keep what follows word-aligned
    record = struct.pack(
        "<IIIIIHBBBBBBBBH", off, len(packed), SM_CHAR_BASE + SM_BASE_TILE * 32,
        off + len(packed), PAL_RAM_MAIN_BG + SM_PAL_NORM * 32,
        SM_BASE_TILE, strip_tiles, cell_w, SM_CELL_H, SM_CELLS,
        SM_PAL_NORM, SM_PAL_HI, len(labels), blank, 0)
    record += bytes(cell_label) + bytes(cell_bit)
    record += struct.pack("<16I", *rows)
    record += struct.pack(
        "<IIBBH", off + len(packed) + len(pals),
        SM_SCREEN_BASE + (frame_y * 32 + frame_x) * 2, frame_rows, frame_cols, 0)
    if len(record) != SM_RECORD_SIZE:
        raise LabelError(f"start menu record is {len(record)} bytes, "
                         f"expected {SM_RECORD_SIZE}")

    last = SM_BASE_TILE + len(pool) // 32
    if last > 0x197:
        raise LabelError(
            f"the panel would end at tile {last:#x}, past the map-name window at 0x197")
    return (bytes(record), packed + pals + bytes(frame_map),
            _touch_plans(labels, layouts_ok))


def _self_pc_codes(archive, region: str):
    """"MON PC" / "MY PC", or the trainer card's word where that is unknown."""
    text = SELF_PC_TEXT.get(region)
    if text is not None:
        return _ascii_codes(text)
    return _decode_message(archive[TRAINER_MSGDATA_FILE], TRAINER_MSG)


def _list_menu_record(strip_off, strip_tiles, n, cell_w, cell_h, n_cols, n_rows,
                      layout, key, key_full, menu_hash, skip) -> bytes:
    """One LIST_MENU_RECORD, in the layout OneScreen_ListMatch reads."""
    if key_full > 0xFF:
        raise LabelError("a first entry longer than 255 characters cannot be keyed")
    key = list(key)[:LIST_KEY_MAX]
    # key_full is the WHOLE length; the hook compares only the first
    # LIST_KEY_MAX codes but checks this too, so a 17-character entry is
    # still identified exactly rather than failing to match at all.
    rec = struct.pack("<HHBBBBBB", strip_off, strip_tiles, n, cell_w,
                      cell_h, key_full, n_cols, n_rows)
    rec += struct.pack(f"<{LIST_KEY_MAX}H", *(key + [0] * (LIST_KEY_MAX - len(key))))
    pos = [(r << 4) | c for r, c in layout]
    rec += bytes(pos + [0] * (LIST_MAX_ENTRIES - len(pos)))
    rec += struct.pack("<HB", menu_hash, skip)
    rec += b"\0" * (LIST_MENU_RECORD - len(rec))
    if len(rec) != LIST_MENU_RECORD:
        raise LabelError(f"list menu record is {len(rec)}, expected {LIST_MENU_RECORD}")
    return rec


def _listmenu(font: Font, archive, off: int, region: str = ""):
    """Return (record, payload) for the script list menus.

    The pool is the nine border tiles followed by every supported menu's label
    strips. Only one menu's strips are ever uploaded - they all load at the same
    base tile, because two of these can never be open at once, and that is what
    keeps the panel inside the tiles free on MAIN_3.
    """
    if LIST_MSGDATA_FILE >= len(archive):
        raise LabelError(f"{MSGDATA_NARC} has no file {LIST_MSGDATA_FILE}")
    src = archive[LIST_MSGDATA_FILE]

    # The border and each menu are packed SEPARATELY: only one menu's strips are
    # ever sent, and a single stream could not be decoded from the middle.
    frame = bytearray()
    for shape in FRAME_SHAPES:
        frame += _to_tiles(_frame_tile(**shape), 1, 1)
    pool = bytearray(_pack(bytes(frame)))
    pool += b"\0" * (-len(pool) % 4)

    menus = []
    for name, msgs, lines, layout in LIST_MENUS:
        cell_h = lines * LIST_CELL_H
        if layout is None:
            layout = tuple((i, 0) for i in range(len(msgs)))
        if len(layout) != len(msgs):
            raise LabelError(f"list menu {name}: layout covers {len(layout)} of "
                             f"{len(msgs)} entries")
        if len(layout) > LIST_MAX_ENTRIES:
            raise LabelError(f"list menu {name} has {len(layout)} entries, over "
                             f"the {LIST_MAX_ENTRIES} the record holds")
        n_rows = max(r for r, _c in layout) + 1
        n_cols = max(c for _r, c in layout) + 1
        entries = []
        # Entries whose live text the patcher cannot know are left out of the
        # identifying hash: your own PC's row (your name), and any message with
        # a control code the game expands at runtime. The line break of a
        # two-line entry is kept in the String as-is, so it is not one of them.
        skip = 0
        for i, (file_id, msg) in enumerate(msgs):
            if file_id is SELF_PC:
                entries.append(_self_pc_codes(archive, region))
                skip |= 1 << i
                continue
            if file_id >= len(archive):
                raise LabelError(f"{MSGDATA_NARC} has no file {file_id}")
            codes = _decode_message(archive[file_id], msg, keep_break=lines > 1)
            if not codes:
                raise LabelError(f"list menu {name}: message {msg} decoded to nothing")
            raw = [c for c in _decode_raw(archive[file_id], msg) if c != 0xFFFF]
            if any(c >= 0xE000 and not (lines > 1 and c == NEWLINE) for c in raw):
                if i == 0:
                    raise LabelError(f"list menu {name}: its first entry holds a "
                                     "control code and cannot identify it")
                skip |= 1 << i
            entries.append(codes)
        # A two-line entry is only as wide as its widest line, not the whole run.
        widest = 0
        for codes in entries:
            run = []
            for code in list(codes) + [NEWLINE]:
                if code == NEWLINE:
                    widest = max(widest, _text_width(font, run))
                    run = []
                else:
                    run.append(code)
        cell_w = (widest + 8 + 7) // 8
        if cell_w + 2 > 32:
            raise LabelError(f"list menu {name} needs {cell_w + 2} tiles, wider than the screen")
        key = entries[0]
        if len(key) > LIST_KEY_MAX:
            key = key[:LIST_KEY_MAX]
        strip_off = len(pool)
        strips = bytearray()
        for codes in entries:
            strips += _to_tiles(_render_strip(font, codes, cell_w * 8, cell_h * 8),
                                cell_w, cell_h)
        pool += _pack(bytes(strips))
        pool += b"\0" * (-len(pool) % 4)
        menus.append((name, strip_off, cell_w * cell_h, len(entries), cell_w, cell_h,
                      n_cols, n_rows, layout,
                      key, len(entries[0]), _menu_hash(entries, skip), skip))

    pals = _palette(SM_PAL_NORM_RGB) + _palette(SM_PAL_HI_RGB)
    record = struct.pack(
        "<IIIIIHBBBBBB", off, SM_CHAR_BASE + SM_BASE_TILE * 32, off + len(pool),
        PAL_RAM_MAIN_BG + SM_PAL_NORM * 32, SM_SCREEN_BASE,
        SM_BASE_TILE, len(menus), SM_PAL_NORM, SM_PAL_HI, 0, 0, 0)
    if len(record) != LIST_RECORD_HEAD:
        raise LabelError(f"list header is {len(record)} bytes, expected {LIST_RECORD_HEAD}")
    for (_name, strip_off, strip_tiles, n, cell_w, cell_h, n_cols, n_rows,
         layout, key, key_full, menu_hash, skip) in menus:
        record += _list_menu_record(strip_off, strip_tiles, n, cell_w, cell_h,
                                    n_cols, n_rows, layout, key, key_full,
                                    menu_hash, skip)

    # Every menu loads at the same base, so only the largest has to fit.
    worst = LIST_FRAME_TILES + max(m[3] * m[2] for m in menus)
    if SM_BASE_TILE + worst > 0x197:
        raise LabelError(
            f"the widest list panel ends at tile {SM_BASE_TILE + worst:#x}, "
            f"past the map-name window at 0x197")
    return bytes(record), bytes(pool) + pals


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build(rom, log=print, theme=themes.DEFAULT_THEME, overlays=None) -> bytes:
    """Return the label blob for this ROM.

    `rom` is an ndspy NintendoDSRom. Raises LabelError if anything about the
    ROM's message or font data is not what this module expects, rather than
    emitting tiles that would draw as garbage on the top screen.

    `theme` only changes colour: the panels' two palettes are a fixed 64 bytes
    in the blob, so every offset, size and record field is identical whichever
    one is chosen.
    """
    chosen = _use_theme(theme)
    try:
        msg_id = rom.filenames.idOf(MSGDATA_NARC)
        font_id = rom.filenames.idOf(FONT_NARC)
    except Exception as exc:                        # noqa: BLE001
        raise LabelError(f"cannot resolve the archives: {exc}") from exc
    if msg_id is None or font_id is None:
        raise LabelError(f"{MSGDATA_NARC} or {FONT_NARC} is missing")

    archive = _narc_files(bytes(rom.files[msg_id]))
    if MSGDATA_FILE >= len(archive):
        raise LabelError(f"{MSGDATA_NARC} has no file {MSGDATA_FILE}")
    labels = [_decode_message(archive[MSGDATA_FILE], m) for m in LABEL_MSGS]
    choices = [_decode_message(archive[MSGDATA_FILE], m) for m in YESNO_MSGS]
    if OAK_MSGDATA_FILE >= len(archive):
        raise LabelError(f"{MSGDATA_NARC} has no file {OAK_MSGDATA_FILE}")
    oak = [_decode_message(archive[OAK_MSGDATA_FILE], m) for m in OAK_YESNO_MSGS]
    if GENDER_MSGDATA_FILE >= len(archive):
        raise LabelError(f"{MSGDATA_NARC} has no file {GENDER_MSGDATA_FILE}")
    gender = [_decode_message(archive[GENDER_MSGDATA_FILE], m) for m in GENDER_MSGS]
    for msg, codes in zip(LABEL_MSGS + YESNO_MSGS + OAK_YESNO_MSGS + GENDER_MSGS,
                          labels + choices + oak + gender):
        if not codes:
            raise LabelError(f"message {msg} decoded to nothing")

    fonts = _narc_files(bytes(rom.files[font_id]))
    if FONT_FILE >= len(fonts):
        raise LabelError(f"{FONT_NARC} has no file {FONT_FILE}")
    font = Font(fonts[FONT_FILE])

    # Each image set: its layout, how many highlighted variants, pixel width and
    # tile width. A geometry then pairs one of those sets with its destination
    # rows. Keeping those concepts separate lets the field yes/no geometry alias
    # the battle yes/no images without copying them into the blob a second time.
    sets = [
        (_layout(font, labels), 4, CELL_W, GRID_COLS, False),
        (_layout_yesno(font, choices), 2, YN_CELL_W, YN_COLS, False),
        # Oak's two prompts used to invert - white ink, no shadow - because the
        # band was whatever saturated colour his intro happened to be using, and
        # dark text vanished into it. A theme picks that colour now, and picks a
        # light one, so ordinary dark ink is both legible and consistent with
        # every other prompt. Inverting here is what made his selected choice
        # come out white while the rest came out black.
        (_layout_yesno(font, oak), 2, YN_CELL_W, YN_COLS, False),
        (_layout_row(font, gender, GENDER_CELL_W), 2, GENDER_CELL_W, GENDER_COLS,
         False),
    ]

    geometries = [
        (0, _row_addrs(BATTLE_CHAR_BASE, WIN_BASE_TILE, GRID_BASE_COL)),
        (1, _row_addrs(BATTLE_CHAR_BASE, WIN_BASE_TILE, YN_BASE_COL)),
        (2, _row_addrs(OAK_CHAR_BASE, OAK_BASE_TILE, YN_BASE_COL)),
        (3, _row_addrs(OAK_CHAR_BASE, OAK_BASE_TILE, GENDER_BASE_COL)),
        (1, _row_addrs(FIELD_CHAR_BASE, FIELD_BASE_TILE, YN_BASE_COL)),
    ]
    if len(geometries) != GEO_COUNT:
        raise LabelError(
            f"there are {len(geometries)} geometries, expected {GEO_COUNT}")

    # Allocate offsets only for unique image sets. Geometry 4 deliberately gets
    # the same offset as geometry 1, while retaining its own destination rows.
    off = BLOB_HEADER
    set_offsets = []
    for _placed, variants, _w, cols, _inv in sets:
        row_bytes = cols * 32
        image_bytes = row_bytes * GRID_ROWS
        set_offsets.append(off)
        # The wipe is NOT stored. It is one image of solid paper per set, and
        # four of them came to 3840 bytes of 0xFF in a blob with no room to
        # spare, so the hook fills instead of copying when asked for the last
        # image. The records still count it, so nothing that asks for a wipe
        # changed.
        off += variants * image_bytes

    blob = bytearray(struct.pack("<4sBBH", BLOB_MAGIC, GRID_ROWS,
                                 len(geometries), 0))
    for set_id, addrs in geometries:
        if not 0 <= set_id < len(sets):
            raise LabelError(f"geometry references missing image set {set_id}")
        _placed, variants, _width, cols, _invert = sets[set_id]
        row_bytes = cols * 32
        image_bytes = row_bytes * GRID_ROWS
        blob += struct.pack("<IIHH", set_offsets[set_id], image_bytes,
                            row_bytes, variants + 1)
        blob += struct.pack(f"<{GRID_ROWS}I", *addrs)
    if len(blob) > SM_RECORD_OFF:
        raise LabelError(f"the geometry records reach {len(blob)}, over the start "
                         f"menu record at {SM_RECORD_OFF}")

    # `off` now points past the last image, which is where the panel's own data
    # goes, so the record can carry absolute blob offsets like the others.
    layouts_ok = overlays is not None and touch_layouts_in(overlays)
    sm_record, sm_payload, sm_plans = _startmenu(font, archive, off, layouts_ok)
    # The fourth letter of the game code is the region, which is the only thing
    # that decides your own PC's row - the one label not taken from the ROM.
    try:
        region = bytes(rom.idCode)[3:4].decode("ascii", "ignore")
    except Exception:                                   # noqa: BLE001
        region = ""
    list_record, list_payload = _listmenu(
        font, archive, off + len(sm_payload), region)
    blob += b"\0" * (SM_RECORD_OFF - len(blob))
    blob += sm_record
    blob += b"\0" * (LIST_RECORD_OFF - len(blob))
    blob += list_record
    if len(blob) > SM_PLANS_OFF:
        raise LabelError(f"the list records reach {len(blob)}, over the layout "
                         f"plans at {SM_PLANS_OFF}")
    blob += b"\0" * (SM_PLANS_OFF - len(blob))
    blob += sm_plans
    blob += b"\0" * (BLOB_HEADER - len(blob))
    if len(blob) != BLOB_HEADER:
        raise LabelError(f"header is {len(blob)} bytes, expected {BLOB_HEADER}")

    images_bytes = 0
    for placed_set, variants, width, cols, invert in sets:
        for sel in range(variants):
            blob += _to_tiles(
                _render(font, placed_set, sel, width, invert), cols)
        images_bytes += variants * cols * 32 * GRID_ROWS
    blob += sm_payload
    blob += list_payload
    expect = BLOB_HEADER + images_bytes + len(sm_payload) + len(list_payload)
    if len(blob) != expect:
        raise LabelError(f"blob is {len(blob)} bytes, expected {expect}")

    fmt = lambda xs: [_text_width(font, c) for c in xs]
    sm_labels = _startmenu_labels(archive)
    log(f"  Labels   : commands {fmt(labels)} px, battle yes/no {fmt(choices)} px, "
        f"field alias, Oak yes/no {fmt(oak)} px, gender {fmt(gender)} px, "
        f"{len(blob)} bytes")
    log(f"  Theme    : {chosen['label']}, panel paper "
        f"{SM_PAL_NORM_RGB[PAPER]:#06x}, band {chosen['band']:#06x}")
    log(f"  X menu   : {len(sm_labels)} labels, widest "
        f"{max(_text_width(font, c) for _a, c in sm_labels)} px, "
        f"{_startmenu_cell_w(font, sm_labels)}x{SM_CELL_H} tile cells")
    drawn = [i for i in range(SM_N_LAYOUTS)
             if sm_plans[i * SM_CELLS] != SM_PLAN_UNDRAWABLE]
    log(f"  X menu   : touch layouts "
        + ("confirmed in overlay 27" if layouts_ok else "NOT found - normal menu only")
        + f", drawn for {drawn}")
    return bytes(blob)


def preview(rom, path):
    """Write a PNG of all four selection states, for eyeballing a build."""
    archive = _narc_files(bytes(rom.files[rom.filenames.idOf(MSGDATA_NARC)]))
    labels = [_decode_message(archive[MSGDATA_FILE], m) for m in LABEL_MSGS]
    choices = [_decode_message(archive[MSGDATA_FILE], m) for m in YESNO_MSGS]
    oak = [_decode_message(archive[OAK_MSGDATA_FILE], m) for m in OAK_YESNO_MSGS]
    gender = [_decode_message(archive[GENDER_MSGDATA_FILE], m) for m in GENDER_MSGS]
    font = Font(_narc_files(bytes(rom.files[rom.filenames.idOf(FONT_NARC)]))[FONT_FILE])
    placed = _layout(font, labels)
    placed_yn = _layout_yesno(font, choices)
    placed_oak = _layout_yesno(font, oak)
    placed_gender = _layout_row(font, gender, GENDER_CELL_W)

    colours = {FG: (56, 56, 72), SHADOW: (168, 168, 176),
               PAPER: (255, 255, 255), HILITE: (255, 190, 190)}
    gap = (200, 200, 200)
    rows = []
    plates = ([(placed, i, CELL_W) for i in range(4)]
              + [(placed_yn, i, YN_CELL_W) for i in range(2)])
    for which, sel, width in plates:
        # Narrow plates are drawn at their real size and padded, so the preview
        # shows how little of the message window the prompt actually covers.
        for line in _render(font, which, sel, width):
            px = [colours.get(v, (255, 0, 255)) for v in line]
            px += [gap] * (CELL_W - width)
            rows.append(b"\0" + bytes(b for c in px for b in c))
        rows.append(b"\0" + bytes([220, 220, 220] * CELL_W))

    def chunk(tag, data):
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    height = len(rows)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", CELL_W, height, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
           + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(png)
    return path
