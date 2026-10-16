@ 1ScreenHGSS - resident hook code, injected into unused ITCM.
@
@ HGSS's ARM9 autoload list puts only 0x620 bytes into ITCM (32 KB at
@ 0x01FF8000), leaving ~31 KB free. We claim it with a third autoload entry, so
@ this code is resident from boot, never unloaded, and never touched by the BSS
@ clear. Thumb BL reaches it from ARM9 and from every overlay.

    .cpu    arm946e-s
    .syntax unified
    .thumb
    .section .text
    .align  2

POWCNT1     = 0x04000304
SWAP_BIT    = 0x8000            @ bit 15: 1 = engine A -> top LCD

@ --- Region-resolved addresses ---------------------------------------------
@ ARM9 *code* addresses are identical across HGSS regions - verified by finding
@ the same anchors at the same addresses in French and US HeartGold. Only data,
@ BSS and overlay bases move, uniformly (US = FR - 0x20).
@
@ So rather than ship one payload per region, the six address-valued constants
@ live in OneScreen_Config below, which the patcher fills in from the ROM it is
@ patching. The DEF_ values are the French ones, so an unconfigured payload is
@ still correct for French.
@ The "state block" is pret's `struct System gSystem` (include/system.h), at
@ 0x021D112C in the French ROMs. Every address below is a field of it, and the
@ layout cross-checks perfectly against what was measured empirically:
@     +0x00  GFIntrCB vBlankIntr    each app installs its own, so it identifies
@                                   the running app - what we call app_callback
@     +0x38  int heldKeysRaw        the pad, before button-mode remapping
@     +0x48  int newKeys            (unused here; we derive edges ourselves)
@     +0x69  u8  screensFlipped     the game's OWN routing flag - see the note
@                                   at the top of OneScreen_SetSwap
DEF_PAD_HELD       = 0x021D1164 @ gSystem.heldKeysRaw
DEF_APP_CALLBACK   = 0x021D112C @ gSystem.vBlankIntr
DEF_FIELD_CALLBACK = 0x021E5921 @ overlay 1 base + 1 (Thumb)
DEF_OV12_LO        = 0x022378E0 @ overlay 12 (battle system) RAM range
DEF_OV12_HI        = 0x0226EC60
DEF_BATTLE_STATE   = 0x021D0E28 @ see the note below
DEF_DEX_EXEC_ORIG  = 0x021E5B81 @ the Pokedex app's real exec function
DEF_PC_EXEC_ORIG   = 0x021E598D @ the PC box app's real exec function
DEF_FIELD_SYS      = 0x021D4178 @ sFieldSysPtr - see OneScreen_ScriptMenu
DEF_SCREENS_FLIP   = 0x021D1195 @ gSystem.screensFlipped (gSystem + 0x69)
DEF_MAP_EXEC_ORIG  = 0x021ED8D5 @ the fly / town map app's real exec function
DEF_START_MENU_TASK = 0x0203BEF1 @ Task_StartMenu; 0 if the patcher cannot vouch
DEF_OAK_EXEC_ORIG  = 0x021E59B5 @ Oak's speech (overlay 53) real exec function
DEF_BATTLE_EXEC_ORIG = 0x0203E3AD @ Battle_Main - see OneScreen_BattleExec
DEF_INTRO_A_EXEC = 0            @ opening cinematic, overlay 60; the patcher
DEF_INTRO_B_EXEC = 0            @ finds them by signature, 0 = leave it alone
DEF_INTRO_C_EXEC = 0
DEF_INTRO_CLOCK = 0
DEF_THEME_BAND = 0              @ BGR555 for a selected band, 0 = leave the
                                @ game's own palettes untouched
DEF_MENU_EXEC_ORIG = 0          @ ScrCmd_MenuExec and the three game functions
DEF_SHOW_LIST = 0               @ the native list needs; the patcher finds them
DEF_LIST_ITEMS_WIDTH = 0        @ through the script command table, 0 = leave
DEF_SETUP_NATIVE = 0            @ every script menu exactly as it was

KEY_A       = 0x001
KEY_B       = 0x002
KEY_R       = 0x100
KEY_L       = 0x200
KEY_X       = 0x400
DPAD_MASK   = 0x0F0             @ right | left | up | down
TOGGLE_MASK = (KEY_L | KEY_R)   @ L+R together; unused by HGSS gameplay

@ The field callback is overlay 1's first function (+1 for Thumb). Measured
@ identical in the plain overworld and with the X menu open - the menu is drawn
@ *inside* the field app, so there is no app transition to hook and no POWCNT1
@ write of its own.
@
@ Battle phase. The game has no "is the player choosing?" flag, so this reads a
@ proxy, found empirically by savestate intersection and only later identified
@ with the decomp. It is pret's poke_overlay.c:
@
@     typedef struct PMiLoadedOverlay { FSOverlayID id; BOOL active; };
@     static PMiLoadedOverlay sOverlayRegions[OVY_REGION_NUM][OVY_MAX_PER_REGION];
@
@ and specifically main-region slot 3's overlay id. The battle loads a different
@ overlay for each phase, so that one word tracks the phase:
@     0x0A  overlay 10 - the trainer AI, which the battle loads for exactly
@           the command-selection phase (BattleSystem_SetTrainerAIOverlayLoaded)
@     0x08  overlay 8  - a sub-screen (bag category, item list, party)
@     0x07  overlay 7  - the turn is executing
@     0x1B  a stale id left over from before the battle; the slot is inactive
@ Testing NEGATIVELY - awaiting a command unless it reads 0x07 - covers every
@ waiting sub-state including ones we never enumerated, and it flips the instant
@ the turn machinery loads overlay 7, so the swap is not late.
@
@ Rejected on the way: 0x02111930 reads 0x06 both when a command has been
@ confirmed AND while a sub-screen is up, so it threw the scene back on top the
@ moment you went a level deeper into the bag. 0x021E17C4 and 0x02134F15 lag -
@ they only change once the turn is already under way, which looks late.
@
@ The caveat that matters: this says which overlay is RESIDENT, not whether the
@ menu is accepting input. Overlay 10 is already loaded while the battle intro
@ text is still playing, so "awaiting a command" goes true early. See the A
@ handling in OneScreen_AutoBattle, which is what stops that mattering.
BATTLE_STATE_EXEC = 0x07
BATTLE_STATE_SUB  = 0x08        @ bag category, item list, party

@ --- The top-screen command menu -------------------------------------------
@ Offsets into the live battle structs, all reached from the BattleSystem the
@ battle app's exec trampoline hands us. Every one is now fixed by the full
@ decompilation (include/battle/battle.h, include/battle/battle_input.h; see
@ docs/DECOMP.md), and each agrees with what was measured from the retail ROM:
@
@   struct BattleSystem
@       +0x04   BgConfig *bgConfig      \ both confirmed independently in the retail
@       +0x08   Window   *window        / ov12: `ldr r0,[r4,#4]` / `ldr r1,[r4,#8]`
@       +0x19C  BattleInput *battleInput
@       +0x23FD u8 graphicsMode         0 normal; 3 while the bag or party owns
@                                       engine B; 1/2 around the catch naming
@                                       screen. battleInput is FREED unless 0.
@
@   struct BattleInput                  (sizeof 0x6F8)
@       +0x68B  s8 curMenuId
@       +0x6D8  BattleCursor *cursor    the sprite cursor
@       +0x6DC  BattleMenuCursor menuCursor { u8 enabled; s8 menuY; s8 menuX; }
@
@ pret's battle_input.h names its fields after offsets that are 0x20 to 0x28
@ low in this region ("my counting was off"), which is why both of these were
@ first measured out of the ROM rather than read off the header. The measuring
@ was right; only pret's labels drifted. Offsets this large cannot be reached by
@ a Thumb immediate, so every access loads the offset from a literal pool, and a
@ census of ov12's word-aligned literals in [0x500,0x800) reads:
@
@     0x68a x9   0x68b x6   0x68c x5   0x68d x1   0x68e x3   0x68f x2
@
@ six consecutive single-byte fields, battlerType .. cancelShown, with 0x688 and
@ 0x689 (two unused bytes) absent. The census also showed 0x6d8 x8 and 0x6dc x7,
@ which are `cursor` and `&menuCursor`.
@
@ The cursor used to be LEARNED at runtime from a starting guess of 0x6D4 -
@ which is BattleInput.scrollXEnd - by watching which byte moved on UP/DOWN. The
@ decompilation settles it at 0x6DC, the same place the learner's own test (an
@ `enabled` byte of 1, then menuY 0/1, then menuX <= 2) converges on. Fixing it
@ also removes a hazard: the learner kept running while the bag was open, when
@ battleInput is freed and the window it diffed was reused heap.
@
@ Identical in IPGF, IPKF and IPKE - these are code-derived, so unlike data they
@ do not move between regions.
BATTLE_INPUT_OFF  = 0x19C       @ BattleSystem.battleInput
BS_GRAPHICS_MODE_OFF = 0x23FD   @ BattleSystem.graphicsMode
BI_CURMENU_OFF    = 0x68B       @ BattleInput.curMenuId
BI_MENU_CURSOR_OFF = 0x6DC      @ BattleInput.menuCursor
BATTLE_INPUT_SIZE = 0x6F8       @ sizeof(BattleInput), for the range check
BSTATE_BATTLE_MAIN = 9          @ Battle_Run's state while BattleSystem lives

@ enum BattleMenuID (include/constants/battle_menu.h). sBattleMenuTemplates
@ (src/battle/battle_input.c) gives the main-menu cursor to ten ids, but only
@ four of them show FIGHT / BAG / POKEMON / RUN:
@
@     1 MAIN_INITIAL, 2 MAIN      the first opening this battle (1 for the
@                                 first battler, 2 for the second in a double)
@     3, 4                        every later opening - backing out of the move
@                                 list or the bag lands here
@     5, 6                        the first rival battle: FIGHT alone, a 1x1
@                                 cursor
@     7, 8                        the Safari Zone: BALL / BAIT / MUD / RUN
@     19, 20                      the Bug Contest: BALL in place of BAG
@
@ The patch only has FIGHT/BAG/POKEMON/RUN pixels, and drawing them over a
@ Safari or first-rival menu would label choices the game is not offering -
@ worse than swapping. So 5..8 and 19/20 swap like any other menu. 9/10 are
@ Pal Park (BALL / RUN), 11 the move list and 12 target select. 0 is
@ BATTLE_MENU_0, the blank menu that is up while the intro text plays and while
@ the turn runs; -1 (NONE) only exists inside the game's own menu change.
BATTLE_MENU_ROOT_LO = 1
BATTLE_MENU_ROOT_HI = 4

@ 13..17 are the binary prompts - YES_NO, KEEP_FORGET_MOVE, GIVE_UP_ON_MOVE,
@ SWITCH_OR_FLEE, SWITCH_OR_KEEP. sBattleMenuTemplates gives all five
@ BattleInput_CursorMove_TwoOptionsMenu, whose cursor is one column by two rows
@ (BattleCursor_CheckKeyInput(cursor, 1, 2, ...)), so menuY alone picks the
@ answer. The bottom screen words them differently each time - "Changer de
@ Pokemon" against "Continuer le combat" - but the choice underneath is always
@ the same shape, so they all get the one Oui/Non pair, stacked to match the way
@ the D-pad moves.
BATTLE_MENU_TWO_LO = 13
BATTLE_MENU_TWO_HI = 17

@ Where the boxes live is not stated here at all - the blob carries an absolute
@ destination address per tile row, because the battle message window and Oak's
@ dialog box sit on different character bases (BG1 charBase 1 at 0x06004000,
@ Oak's MAIN_0 at 0x06018000). Confirmed for the battle side by dumping BG1CNT
@ and engine A's DISPCNT live mid-battle; Oak's comes from its own BgTemplate.
LABEL_MAGIC  = 0x424C5331       @ "1SLB"

@ The blob holds image sets with geometry records at +8. Each 28-byte record is:
@ data offset, bytes per image, bytes per tile row, image count, then four
@ absolute destination addresses. More than one geometry can point at the same
@ image data: the battle and field Oui/Non boxes use the same pixels at different
@ MAIN-engine character addresses. The hook carries no dimensions of its own,
@ so moving or resizing a box is a change to onescreen/labels.py alone.
@
@ An image is named by a single byte, (set << 4) | index, which is what bt_drawn
@ and bt_lock hold. The last image of each set is all paper and takes that box
@ down - a separate box for the yes/no prompt is the whole point, because the
@ blit paints everything in its area and a wide one erases the right-hand end of
@ any question long enough to reach it.
LABEL_GEO_SIZE = 28
LABEL_GEO_YN   = 1              @ (1 << 4) | 0 = top choice, | 1 = bottom
LABEL_GEO_OAK    = 2            @ Oak's yes/no, stacked - the generic multichoice
                                @ handler moves on UP and DOWN
LABEL_GEO_GENDER = 3            @ boy/girl, side by side - the gender handler moves
                                @ on LEFT and RIGHT, so stacking implied wrong keys
LABEL_GEO_FIELD  = 4            @ field-dialog Oui/Non; aliases LABEL_GEO_YN pixels
LABEL_GEO_COUNT  = 5
@ Reserved space for the label images; the patcher refuses rather than overrun it.
@ The five geometry records, start-menu record and four unique localized image
@ sets fit here with headroom. The field geometry aliases the battle Yes/No set.
LABEL_BLOB_SIZE = 19456         @ reserved; the patcher refuses rather than overrun it

@ The main-loop call we displace: `bl 0x0200110C` at 0x02000DB0.
ORIG_LOOP_FN = 0x0200110C + 1   @ +1 = Thumb

@ Pokedex area map. The species grid and the per-Pokemon detail level share one
@ app callback and the same POWCNT1 value, so neither app_table nor a scan for a
@ sub-state byte could separate them - two candidates were tried from savestate
@ diffs and both turned out to be noise.
@
@ pret/pokeheartgold settled it. The Pokedex is an OverlayManager application:
@
@     struct OverlayManager { OverlayManagerTemplate template;  // init/exec/exit/ovy_id
@                             int exec_state;                   // +0x10
@                             int proc_state;                   // +0x14
@                             void *args; void *data; ... };
@
@ and the framework calls template.exec(manager, &manager->proc_state) every
@ frame. So instead of hunting for the state in RAM, we take over that exec
@ pointer: r1 arrives holding &proc_state, which IS the screen level. Measured
@ across four savestates covering two different Pokemon:
@     11  species grid
@     69  detail level, where the area map is on engine B (the bottom screen)
@ 69 also has its own struct in the decomp (PokedexAppData_UnkSub0868_State69),
@ which corroborates it being a real distinct screen.
@
@ Swapping on 69 alone made the map fade in on the BOTTOM screen and then jump
@ across once it was fully visible. The decomp shows why: 69 is not where the map
@ is built. PokedexApp_MainSeq_68 builds it, starts a fade in from black, and
@ hands off to MainSeq_03 - the shared "wait for the palette fade" state, which
@ returns to whatever unk_085C names. Only when the fade has finished does 68
@ return 69. So the whole visible fade-in happens under states 68 and 03.
@
@ Two consequences for the rule below:
@   * the map screen is a RANGE of states, not just 69. 69 is the idle screen,
@     70 fades back out, and 71..75 handle scrolling between maps and the
@     sub-interactions - all of them return to 69.
@   * states 02 and 03 are the shared fade waits, entered from BOTH sides, so
@     they say nothing about which screen we are on and must not be treated as
@     "not the map". They hold the current routing instead.
@
@ Acting during the build also makes the swap invisible: the map fades in FROM
@ black, so the previous screen has already faded out and both engines are black
@ at the moment we flip. Same reason the menus never flashed.
@
@ Which state does the building depends on how you got there, and this is what a
@ first attempt at 68 alone still flashed on:
@
@     from another tab   91 (or 78 / 81) fades out -> 03 -> returns 68
@     from the species grid              64 / 15   -> 03 -> returns 66
@
@ and MainSeq_66 sets up and then **tail-calls PokedexApp_MainSeq_68 directly**:
@
@     static int PokedexApp_MainSeq_66(PokedexAppData *app) {
@         ...
@         return PokedexApp_MainSeq_68(app);
@     }
@
@ so on that path the map is built and the fade started while proc_state still
@ reads 66, and the value 68 is never seen until the fade has already finished.
@ Hence the range starts at 66. Both routes into 66 come after a fade to black
@ (one of them also calls ZeroPalettesByBitmask), so swapping there is invisible.
@
@ 67 is the shared "fade this tab out and go back to the list" state, reached
@ from whichever tab was open, so like 02/03 it must hold rather than pick a
@ side - otherwise leaving the map threw it to the bottom before it faded.
DEX_MAP_LO  = 66
DEX_MAP_HI  = 75
DEX_FADE_LO = 2                 @ MainSeq_02 / MainSeq_03: wait for a fade
DEX_FADE_HI = 3
DEX_TAB_FADE = 67               @ MainSeq_67: fade the open tab out

NO_STATE = 0xFF                 @ "not in a battle" sentinel

@ Frames the PC box routing is held after each call into the app. Two is enough
@ to cover the main loop running our hook before the app's exec rather than
@ after, without outliving the app by anything a player could see.
PC_HOLD_FRAMES = 2

@ Flying. Selecting a destination on the Town Map used to leave the whole flight
@ animation on the bottom screen, and it only came back after the player walked
@ around at the far end. Savestates through the sequence show why:
@
@     before pressing A   Town Map app live, overlay 101, exec_state 2
@     just after A        same manager, exec_state 3 - the app is EXITING
@     mid-animation       app gone; gSystem.vBlankIntr is the field again
@     arrived / fixed     identical field state in both - only POWCNT1 differs
@
@ So the flight animation is drawn by the FIELD, after the Town Map app tears
@ down, and nothing restores the field's own routing when that happens: the
@ Town Map's layout is simply left in place. Nothing in FieldSystem distinguishes
@ "arrived but wrong" from "arrived and correct" - the two savestates match
@ field for field - which is the proof that no state flag can drive this. It has
@ to be the app transition.
@
@ So when an application hands the field back, put the world on top for a few
@ frames. Gated behind the X-menu latch and the script-menu check, so coming back
@ from the bag into an open menu, or into a shop list, is unaffected.
@
@ That gate was also why a first attempt at this changed nothing. Reading the
@ hook's own variables back out of the savestates - the payload signature "1SGS"
@ makes them easy to find in ITCM - showed menu_swapped stuck at 1 for the whole
@ flight and only 0 once it had corrected itself. Flying is reached THROUGH the X
@ menu, and the latch is deliberately kept across sub-apps so that a trip into
@ the bag and back leaves the menu on top. But flying does not come back to the
@ menu, it comes back to the world, so the latch has to be dropped - and Poll was
@ re-applying "menu on top" every frame, which is what put the flight animation
@ on the bottom screen in the first place.
FIELD_RESTORE_FRAMES = 30

@ The cinematic's frame counter, and the frame its first scene stops being
@ correct. Measured from savestates either side of the changeover: 102 is a
@ frame where both screens are black, so the switch cannot be seen.
INTRO_COUNTER_OFF = 4
INTRO_A_FROM = 102

@ Scene B is not uniform either, which the first attempt got wrong by swapping
@ the whole of it: its earlier part is already correct and only its tail belongs
@ on the other engine. As in scene A there is nothing but the counter separating
@ the two halves, and 1090 is the frame the changeover actually happens on,
@ captured rather than interpolated - the first guess of 1100 was 10 frames late.
INTRO_B_FROM = 1090

@ And the last scene, which is correct until 1867 and wrong after it. Its
@ sequence runs to the end of the intro - the savestate taken at the end has
@ no application registered at all - so it needs no upper bound.
INTRO_C_FROM = 1867

@ The last sequence outlives the application that starts it: at its final
@ frame nothing is registered in the application slot at all, so there is no
@ scene counter left to test. It is held instead on the tick counter beside
@ that slot, which keeps running - measured 3728 at the first frame and 3972
@ at the last, so 244 ticks, about two seconds.
INTRO_C_HOLD = 244

@ Frames the fly map's exit is waited for. Two is enough to notice the app has
@ stopped calling the trampoline.
MAP_LAPSE_FRAMES = 2

@ ...and then how long to wait for the FIELD to pick up. This is the part a
@ first attempt got wrong: it tested "is the field running?" once, on the frame
@ the app lapsed, and gave up for good if not. But gSystem.vBlankIntr reads 0
@ for a stretch right after the town map tears down - the savestate taken just
@ after confirming a destination shows exactly that - so the single test always
@ landed in the gap and never fired. Wait for the field instead, and cancel if
@ some other application takes over rather than the field.
MAP_PENDING_FRAMES = 180        @ ~3 s, far longer than the handover needs

@ FieldSystem.taskman - the field's running task, see OneScreen_MenuGone.
FS_TASKMAN_OFF = 0x10           @ FieldSystem.taskman
TASK_FUNC_OFF = 0x04            @ TaskManager.func
TASK_ENV_OFF = 0x0C             @ TaskManager.env
FIELD_SYSTEM_SIZE = 0x128       @ sizeof(FieldSystem)
TASK_MANAGER_SIZE = 0x20        @ sizeof(TaskManager)
START_MENU_DATA_SIZE = 0x38C    @ sizeof(StartMenuTaskData)

@ StartMenuTaskData.state (include/start_menu.h), the menu's own state machine.
@ Its exit path is what shows the menu for a moment after choosing Dig or an
@ Escape Rope: 12 pauses the map and starts a fade, 13 waits for the fade then
@ jumps to the exit task and frees the menu. Measured across the flash -
@
@     just before, on black   func Task_StartMenu, state 12
@     during the flash        func Task_StartMenu, state 13
@     after                   an overlay script task
@
@ - against state 3 (HANDLE_INPUT) for a menu that is genuinely up and taking
@ input. So the menu really is running during the flash, with the same task and
@ the same env; only this field separates "up" from "on its way out".
STARTMENU_STATE_OFF = 0x26
STARTMENU_EXIT_LO = 12          @ START_MENU_STATE_12: fade out
STARTMENU_EXIT_HI = 13          @ START_MENU_STATE_13: jump to the exit task

@ Choosing SAUVER does not start an application - the task stays alive in
@ START_MENU_STATE_SAVE while the save confirmation runs on the bottom screen
@ (src/start_menu.c:1131, then 6 and 7 in its own switch). So app_callback is
@ still the field, the X menu path still runs, and the panel went on holding the
@ world on top while the save box sat underneath it. Drawing stops for these two
@ states and the caller swaps instead.
STARTMENU_TAKING = 3            @ START_MENU_STATE_HANDLE_INPUT
STARTMENU_SAVE_LO = 6
STARTMENU_SAVE_HI = 7

@ Drawing that menu onto the world instead of swapping to it. Three fields carry
@ everything needed, and all three were read out of a live savestate with the
@ menu open (out/beta-ui.ml1) rather than trusted from the decomp alone:
@
@   FieldSystem +0xD3   the cursor, FieldSystem.startMenuCursorPos. NOT in
@                       StartMenuTaskData - the touch overlay owns it
@                       (TouchscreenMenu_HandleDpadInput, ov27_0225B404 in pret,
@                       writes it on every D-pad move); start_menu.c reads it, and
@                       writes it only for a touch. Read 0 with POKEDEX lit. It
@                       counts only the entries you HAVE, so it is an index into
@                       the compacted list, not a grid slot.
@   StartMenuTaskData +0x34C  inhibitIconFlags, the game's own answer to which
@                       entries exist, computed once when the menu opens
@                       (src/start_menu.c:288). This is what the panel is built
@                       from. selectionToAction[] at +0x3A looks like the obvious
@                       source and is a trap: past the real entries it holds
@                       zeros, which read as POKEDEX and drew that word twice.
FS_START_MENU_CURSOR_OFF = 0xD3 @ FieldSystem.startMenuCursorPos
SM_INHIBIT_OFF = 0x34C          @ StartMenuTaskData.inhibitIconFlags
SM_NORMAL_MASK = 0x190          @ DISABLE_RETIRE | DISABLE_7 | DISABLE_SAVE
SM_NORMAL_BITS = 0x180          @ what the normal layout sets of those three

@ The touch menu app's own data, TouchscreenMenuData (src/touchscreen_menu.c,
@ overlay 27, 0x540 bytes). It is the menu: the start menu task only handles A
@ and B, and every D-pad move goes through TouchscreenMenu_HandleDpadInput,
@ which writes `selection` and then FieldSystem.startMenuCursorPos together.
@ All four offsets are confirmed in pret's retail assembly of overlay 27 as
@ well as computed from the decompilation:
@
@     +0x10  FieldSystem *fieldSystem     ldr r1,[r4,#0x10] in TouchscreenMenu_Create
@     +0x14  int selection, a slot 0..6   str r0,[r4,#0x14] after the slot lookup
@     +0x470 TouchscreenMenuIcon icons[7] {u8 shown; String *label}, stride 8
@     +0x51C u32 flags                    layout is bits 1-4: `lsl #27; lsr #28`
@
@ layout, from TouchscreenMenu_GetLayout: 0 normal, 1 Safari, 2 Bug Contest,
@ 3 Pal Park, 4 Union Room, 5 Colosseum, 6 Battle Tower partner room.
BSAPP_TOUCH_MENU   = 0          @ BOTTOM_SCREEN_APP_TOUCHSCREEN_MENU
TOUCH_MENU_SIZE    = 0x540
TSM_FS_OFF         = 0x10
TSM_SELECTION_OFF  = 0x14
TSM_ICONS_OFF      = 0x470
TSM_N_ICONS        = 7
TSM_LAYOUT_OFF     = 0x51C
TSM_LAYOUT_SHIFT   = 1
TSM_LAYOUT_MASK    = 0xF
SM_N_LAYOUTS       = 7
SM_PLANS_OFF       = 528        @ in the label blob: u8 strip[8] per layout
SM_PLAN_UNDRAWABLE = 0xFE       @ cell 0 of a layout the patcher cannot label
SM_CELLS           = 8
SM_SP_CELLS        = 16         @ OneScreen_StartMenu's frame: the cell plan,
SM_SP_HI           = 24         @ the highlighted cell,
SM_FRAME_SP        = 28         @ and the frame's size

@ The panel's record in the label blob, and the offsets inside it. Written by
@ onescreen/labels.py::_startmenu; the layout is documented there.
SM_RECORD_OFF = 148
SM_TILES_OFF = 0                @ u32 blob offset of the strip pool
SM_TILES_BYTES = 4
SM_TILES_DEST = 8
SM_PAL_OFF = 12
SM_PAL_DEST = 16
SM_BASE_TILE = 20               @ u16
SM_STRIP_TILES = 22             @ u8
SM_CELL_W = 23
SM_CELL_H = 24
SM_N_CELLS = 25
SM_PAL_NORM = 26
SM_PAL_HI = 27
SM_CELL_LABEL = 32              @ u8 cell_label[8], 0xFF where nothing lives
SM_CELL_BIT = 40                @ u8 cell_bit[8], the inhibit bit gating each
SM_ROWS_OFF = 48                @ u32 cell_rows[16], absolute tilemap addresses
SM_BLANK = 29                   @ u8 index of the all-paper strip
SM_PAL_BYTES = 64               @ both palettes, which the builder keeps adjacent
SM_FRAME_OFF = 0x70             @ u32 blob offset of the border's tilemap
SM_FRAME_BASE = 0x74            @ u32 tilemap address of its top-left cell
SM_FRAME_ROWS = 0x78            @ u8; past ldrb's immediate, so loaded by register
SM_FRAME_COLS = 0x79
SM_MAP_STRIDE = 64              @ bytes per tilemap row: 32 entries of 2
SM_SCREEN_BASE = 0x06001000     @ MAIN_3's tilemap, from sBgTemplate_3

@ The script list menus - the shop's ACHETER/VENDRE/QUITTER and the PC's lists.
@ All of them are the same object: a script builds a menu, overlay 27's touch
@ controller renders it, and the controller points straight back at it. Every
@ offset below was read out of evolution-oak-ipgf.ml1..ml5 rather than inferred.
@
@   controller +0x394  the cursor. Already known here as CHOICE_SELECTION_OFF,
@                      which was thought to be the binary-prompt choice only -
@                      it is the list cursor too, proved by ml1 vs ml2 reading
@                      0 then 1 as the shop cursor moved ACHETER -> VENDRE.
@   controller +0x3A0  the menu itself. NOT +0x39C, which holds an ARM9 code
@                      address - reading the count through that gave 255 and the
@                      panel silently never matched. The decompilation explains
@                      both: +0x39C is selectionCallback, which ScrCmd_MenuExec
@                      sets to MenuExec_PrintItemHelp, and +0x3A0 its argument,
@                      the menu. The menu's own slot is +0x0C.
@       +0x9B  u8   entry count. Read 3 / 4 / 4 / 5 for the shop, both PC lists
@                   and the PC box menu. ScriptMenu.count.
@       +0x1C  String* per entry, stride 4. ScriptMenu.strbufs[28].
@
@ A String is {u16 maxsize, u16 size, u32 magic, u16 codes[]}. The codes are the
@ game's own character set, the same numbers labels.py rasterises from - ACHETER
@ reads [299,301,306,303,318,303,316] in both places, which is what makes
@ identifying a menu by its text sound.
LIST_CURSOR_OFF = 0x394         @ TouchscreenChoiceMenuData.selection
CHOICE_MENU_OFF = 0x0C          @ TouchscreenChoiceMenuData.menu, the menu's own slot
CHOICE_CALLBACK_ARG_OFF = 0x3A0 @ TouchscreenChoiceMenuData.selectionCallbackArg
SCRIPT_MENU_COUNT_OFF = 0x9B    @ ScriptMenu.count
SCRIPT_MENU_FLAGS_OFF = 0x97    @ ScriptMenu: cancellable bit 0 .. anchorRight bit 6
SCRIPT_MENU_X_OFF = 0x98        @ ScriptMenu.x
SCRIPT_MENU_RET_OFF = 0xA0      @ ScriptMenu.ret_p, the script's result var
SCRIPT_MENU_ITEMS_OFF = 0x1C4   @ ScriptMenu.items[28], ListMenuItem {text, value}
SCRIPT_MENU_SIZE = 0x2E0        @ sizeof(ScriptMenu)
SCRIPT_MENU_MAX = 28
ANCHOR_RIGHT_BIT = 0x40
ANCHOR_BOTTOM_BIT = 0x80
LIST_WINDOW_TILE = 0x3D         @ ScriptMenu list windows' first character tile
LIST_SCAN_CELLS = 32 * 24       @ the visible part of a 32x32 tilemap
CHOICE_IDLE = 1                 @ TOUCHSCREEN_CHOICE_MENU_STATE_IDLE
LIST_NONE = 0xEEEE              @ the script's "nothing chosen yet"
LIST_CANCEL = 0xFFFE            @ ScriptMenu_ListTask's B
LIST_RIGHT_EDGE = 31            @ last tile column a list window may reach
SCRIPT_MENU_STRBUFS_OFF = 0x1C  @ ScriptMenu.strbufs
STRING_SIZE_OFF = 2
STRING_DATA_OFF = 8

@ The panel's record, written by onescreen/labels.py::_listmenu.
LIST_RECORD_OFF = 272
LIST_TILES_OFF = 0
LIST_TILES_DEST = 4
LIST_PAL_OFF = 8
LIST_PAL_DEST = 12
LIST_SCREEN_BASE = 16
LIST_BASE_TILE = 20             @ u16
LIST_N_MENUS = 22               @ u8
LIST_PAL_NORM = 23
LIST_PAL_HI = 24
LIST_MENUS_OFF = 0x1C           @ first per-menu record
LIST_MENU_RECORD = 56
LIST_M_STRIP_OFF = 0            @ u16, byte offset of its strips in the pool
LIST_M_STRIP_TILES = 2          @ u16
LIST_M_ENTRIES = 4              @ u8
LIST_M_CELL_W = 5
LIST_M_CELL_H = 6
LIST_M_KEY_FULL = 7             @ the first entry's WHOLE length, not the clamped
                                @ comparison length - BOITE AUX LETTRES is 17
                                @ characters, and checking 17 against the 16 we
                                @ store made that menu never match at all
LIST_M_COLS = 8
LIST_M_ROWS = 9
LIST_M_KEY = 10                 @ u16 key[16]
LIST_M_POS = 42                 @ u8 pos[8], (row << 4) | column per entry
LIST_M_HASH = 50                @ u16 hash of every entry not in the skip mask
LIST_M_SKIP = 52                @ u8, bit i = entry i is left out of the hash
LIST_MAX_ENTRIES = 8
LIST_KEY_MAX = 16
LIST_FRAME_TILES = 9
LIST_HOLD_FRAMES = 8            @ ~0.13s; long enough to bridge a reprint, short
                                @ enough that a real close is not visibly delayed

@ The panel has to go into the game's OWN tilemap buffer as well as VRAM.
@
@ The game keeps a shadow copy of each layer's map and commits it wholesale
@ whenever its contents change - reprinting a menu option's description does
@ exactly that. Cells written straight to VRAM are not in that copy, so every
@ reprint erased the panel and it reappeared a frame later. Read out of
@ beta-ui.ml1 while the PC box menu was open: the buffer held zeros across the
@ whole panel rectangle, which is what the commit was writing over us.
@
@ FieldSystem +0x08 -> BgConfig; its Background array starts at +8 and each entry
@ is 44 bytes, so MAIN_3's buffer pointer is at +8 + 3*44.
BGCONFIG_OFF = 0x08
BG3_BUFFER_OFF = 0x8C
BG_BUFFER_SIZE = 0x800

@ Oak's speech, overlay 53. One of the applications that sets POWCNT1 nowhere at
@ all, so it simply inherits whatever routing it starts with - which left the
@ whole opening monologue inverted: the "TOUCHER" prompt on top and Oak's text
@ on the bottom, where a top-only setup cannot see it.
@
@ Its OverlayManager proc_state only counts 0..5; the real screen is
@ OakSpeechData.state (include/oaks_speech_internal.h), reached through
@ manager->data. The enum is fully named in the decomp, so the boundaries need
@ no guessing:
@
@     ...60  TELL_ME_ABOUT_YOURSELF        Oak and the text  -> engine A on top
@     61     ARE_YOU_A_GENDER              still Oak talking
@     62     WAIT_FADE_OUT_TO_ASK_GENDER   the fade INTO the picker
@     63-65  SETUP / WAIT_FADE_IN / HANDLE_INPUT of the gender menu
@     66-72  ASK_CONFIRM_GENDER and its yes/no
@     93     CONFIRM_GENDER_YES
@     94+    PROMPT_NAME...                 back to Oak, then the naming screen,
@                                           which app_table already handles
@
@ Swapping over 62..93 puts the boy/girl cards up while leaving the speech
@ itself alone, and starting at 62 rather than 63 means the flip happens during
@ the game's own fade-out - the same rule the Pokedex map needed.
@ The opening tutorial menu - INFOS COMMANDES / INFOS AVENTURE / NON MERCI -
@ needs the same treatment, and the window templates say so outright:
@
@     sMultichoiceMenuButtonWindowTemplates[][].bgId = GF_BG_LYR_SUB_0
@     sFullScreenMsgWindowTemplate.bgId             = GF_BG_LYR_MAIN_0
@
@ The three buttons are on engine B, and the INFOS pages they lead to are on
@ engine A. So the menu swaps and the pages do not, which is exactly the split
@ that was wanted. States 0..7 cover it: 1..3 raise and run the menu, 4..6 fade
@ it out into a topic, and 7 fades it back in when the topic returns.
@ Oak's own two-option prompts. OakSpeechData is decompiled
@ (include/oaks_speech_internal.h), and its OakSpeechMultichoice sits inline at
@ +0x160 - anchored by filler_148[0x18] immediately before it, and by unk_080 and
@ unk_114 earlier in the struct, all three named after their own offsets:
@
@     +0x160 unk_0        +0x161 numOptions
@     +0x162 inPadMode    +0x163 cursorPos
@
@ so the count and the live selection are one struct away from the pointer the
@ exec trampoline is already handed every frame. That pairing is what the field
@ prompt never had, and it is why this one is tractable.
@
@ The states come from the enum in src/oaks_speech.c, and only the three that
@ actually take input are drawn on - the setup and fade states around them would
@ otherwise flash a prompt the player cannot answer yet.
OAK_MENU_OFF     = 0x160
OAK_NUMOPTS_OFF  = 0x161
OAK_CURSOR_OFF   = 0x163
OAK_GENDER_PICK    = 65         @ GENDER_SELECT_MENU_HANDLE_INPUT
OAK_CONFIRM_GENDER = 69         @ CONFIRM_GENDER_YESNO_HANDLE_INPUT
OAK_CONFIRM_NAME   = 98         @ CONFIRM_NAME_YESNO_HANDLE_INPUT

@ The states that lead into each of those. The game has already drawn the dialog
@ box by then, complete with the "look at the bottom screen" icon in the corner
@ our prompt is about to occupy - so without this the icon gets a few frames to
@ itself and visibly flashes before the prompt lands. Blitting the box's own
@ all-paper image through the lead-in covers it, without showing a prompt the
@ player cannot answer yet.
@
@     61 ARE_YOU_A_GENDER            .. 64 WAIT_FADE_IN_GENDER_SELECT_MENU
@     66 PREPARE_ASK_CONFIRM_GENDER  .. 68 CONFIRM_GENDER_YESNO_INIT_MENU
@     96 PROMPT_NAME_RESTORE_GRAPHICS .. 97 CONFIRM_NAME_YESNO_INIT_MENU
OAK_GENDER_PRE_LO  = 61
OAK_GENDER_PRE_HI  = 64
OAK_CONFIRM_PRE_LO = 66
OAK_CONFIRM_PRE_HI = 68
OAK_NAME_PRE_LO    = 96
OAK_NAME_PRE_HI    = 97

@ The small DS focus indicator is the {YESNO 0} text control, not a separate
@ menu. RunTextPrinter consumes it from the print-task queue after this exec hook
@ returns, so an extra blit here cannot win the ordering race. In only the three
@ question states, OneScreen_OakSuppressFocus changes that live String's control
@ id from 0x0200 to unused 0x0209 before the printer sees it. The normal generic
@ control-code path then skips the same one argument without drawing the icon.
@
@ Oak's selected band uses palette index 12, unused by its native dialog text.
@ While a prompt is live the draw copies Oak's own edition-specific backdrop
@ colour (MAIN BG palette 1 index 1) there: blue/silver in SoulSilver, gold in
@ HeartGold. Ordinary text remains on indices 1/2/15.
OAK_THEME_SOURCE = 0x05000022
OAK_THEME_DEST   = 0x050000D8

@ A selected band is always palette index 12, but of whichever palette the box
@ it sits in belongs to. Stock, the patch WRITES none of these - it borrows the
@ salmon the game happens to keep in palette 11. A theme has to write them:
@
@   palette 6   Oak's dialogWindow          0x05000000 + 6*32 + 12*2
@   palette 11  battle message window, and the evolution prompt that shares it
@   palette 12  the field dialogue box
@
@ Written per frame while a prompt is drawn, never unconditionally: palette RAM
@ is shared, and colouring 11 and 12 outside a prompt would recolour whatever
@ else happens to be using index 12 at the time.
BAND_DEST_OAK    = 0x050000D8
BAND_DEST_BATTLE = 0x05000178
BAND_DEST_FIELD  = 0x05000198

OAK_STATE_OFF = 0x0C            @ OakSpeechData.state
OAK_DATA_OFF = 0x08             @ manager->data, from &proc_state (+0x14)
OAK_TUTORIAL_HI = 7             @ 0..7: the tutorial menu
OAK_FOCUS_GENDER         = 61   @ ARE_YOU_A_GENDER
OAK_FOCUS_CONFIRM_GENDER = 67   @ ASK_CONFIRM_GENDER
OAK_FOCUS_CONFIRM_NAME   = 97   @ CONFIRM_NAME_YESNO_INIT_MENU
OAK_PRINT_STATE_OFF = 0x104     @ OakSpeechData.printDialogMsgState
OAK_STRING_OFF      = 0x110     @ OakSpeechData.string
OAK_STRING_LAST_OFF = 0x808     @ String_New(0x400) allocation, conservatively
OAK_STRING_MAX      = 0x400
OAK_STRING_MAGIC    = 0xB6F8D2EC
OAK_CONTROL_MARK    = 0xFFFE
OAK_FOCUS_CONTROL   = 0x0200
OAK_IGNORE_CONTROL  = 0x0209

@ Why the band behind Oak's selected choice used to flash, from the full
@ decompilation. OakSpeech_InitMsgPrinter starts a PaletteBlink on top-screen
@ BG palette 6 - the dialog window's own palette - to animate the "look at the
@ bottom screen" icon, colours 11-14 (src/palette_blink.c). It runs on the main
@ SysTask queue, after this exec trampoline, and on ticks 0 and 24 of its
@ 32-tick cycle it writes ALL SIXTEEN colours of palette 6 back to palette RAM
@ from its own copy. Our band is palette 6 colour 12, so once a cycle the
@ game's 0x62FF salmon came back for a frame, and once it went white.
@
@ The icon is suppressed in exactly the states that draw a band, so the blink
@ has nothing to show there: hold it still (PALETTE_BLINK_PAUSE) while 65, 69
@ or 98 is up, and RESTART it afterwards - only if we were the ones who paused
@ it, and never END it, which would destroy its task.
@
@     struct PaletteBlink { SysTask *task; ApplyFunc apply; PaletteData *pltt;
@                           u16 source[16], current[16];
@                           u8 screen, palette, state, timer; };   // 0x50
@
@ apply is checked against PaletteBlink_LoadMainBgPltt - ARM9 code, the same
@ address in every region (pret's sub_020165A4) - so this only ever touches the
@ hardware-palette blink of the top screen it expects.
OAK_BLINK_OFF       = 0x114     @ OakSpeechData.paletteBlink
BLINK_SIZE          = 0x50
BLINK_APPLY_OFF     = 0x04
BLINK_PLTT_OFF      = 0x08
BLINK_BYTES_OFF     = 0x4C      @ screen, palette, state, timer
BLINK_APPLY_MAIN_BG = 0x020165A5 @ PaletteBlink_LoadMainBgPltt, Thumb
BLINK_RESTART       = 0
BLINK_RUN           = 1
BLINK_PAUSE         = 2
BLINK_PALETTE_OAK   = 6

@ Field script menus - the PC option list, shop lists, NPC yes/no choices. All
@ of these are drawn on the touch screen by the running script, inside the field
@ app, so there is no app transition to detect and no POWCNT1 write of our own
@ to catch. The signal is in FieldSystem (include/field_system.h):
@
@     struct FieldSystem { FieldProcessManager *processManager;  // +0x00
@                          ... ; int bottomScreenType;           // +0x18
@                          int savedBottomScreenAppId; ... };    // +0x1C
@
@ ScrCmd_TouchscreenMenuHide parks the bottom screen on app 3 (the choice menu)
@ and leaves 3 here; ScrCmd_TouchscreenMenuShow puts 0 back for the icon bar.
@ pret called this unk1C; the full decompilation names it - see docs/DECOMP.md.
@ Read through sFieldSysPtr, the file-static in field_system.c.
@
@ Confirmed on both sides, which is the rule that caught every bad candidate
@ before this: 3 in all seven PC savestates, and 0 in six out-of-sample states
@ from different sessions AND different builds (Pokedex, battle, overworld, name
@ entry). Exactly one stable ARM9-BSS pointer in the whole image fits, and the
@ struct it points at is unmistakable - six heap pointers, then these two ints.
@
@ Tested non-zero rather than == 3: any non-default mode means a script has put
@ something on the bottom screen that the player needs to see.
FS_SAVED_APP_ID_OFF = 0x1C      @ FieldSystem.savedBottomScreenAppId
@ Mode 3 is refined at runtime: binary states stay on the world, list states swap.
FS_BOTTOM_TASK_OFF = 0xD8       @ FieldSystem.bottomScreenTask
FS_BOTTOM_TYPE_OFF = 0x18       @ FieldSystem.bottomScreenType
FS_BOTTOM_TYPE_FIELD = 1        @ the overworld, Safari and friends
FS_BOTTOM_TYPE_UNION = 3        @ the Union Room
SYS_TASK_DATA_OFF = 0x10        @ SysTask.data

@ The bottom-screen app manager (src/field/bottom_screen_app.c), the SysTask
@ that owns which touch app is up and the fades between them:
@
@     struct BottomScreenAppManager { u8 appId; u8 state; u8 nextAppId;
@                                     void *app; FieldSystem *fieldSystem;
@                                     void *args; };
@
@ For the apps this hook reads, `app` is the app's own SysTask and its data is
@ at SysTask.data. App 0 is the icon bar / X menu, app 3 the choice menu.
BSAPP_ID_OFF  = 0x00            @ .appId
BSAPP_STATE_OFF = 0x01          @ .state
BSAPP_NEXT_ID_OFF  = 0x02       @ .nextAppId
BSAPP_APP_OFF = 0x04            @ .app
BSAPP_FS_OFF    = 0x08          @ .fieldSystem
BSAPP_LAST_OFF  = 0x0C          @ .args, the last field in the block
BSAPP_RUNNING      = 1
BSAPP_SWITCH_REQUESTED  = 2     @ 2..7 are the switch and its fades
BSAPP_FADE_IN  = 7
BSAPP_CHOICE_MENU      = 3      @ BOTTOM_SCREEN_APP_CHOICE_MENU

@ App 3's data is TouchscreenChoiceMenuData (src/touchscreen_choice_menu.c),
@ the green Yes/No and list controller. GetMenuChoice selects state 3
@ (SHOW_YES_NO); MenuExec selects state 7 (SHOW_LIST). The live choice is its
@ `selection` word, not the ListMenu2D field the abandoned experiment followed.
CHOICE_STATE_OFF = 0x00         @ .state
CHOICE_FS_OFF    = 0x24         @ .fieldSystem
CHOICE_SELECTION_OFF = 0x394    @ .selection
CHOICE_SHOW_YES_NO = 3          @ 3..5 SHOW_YES_NO, YES_NO_INPUT, YES_NO_END
CHOICE_YES_NO_END = 5
CHOICE_DONE = 6                 @ DONE: hides the cursor, back to IDLE (1)
CHOICE_SHOW_LIST   = 7          @ 7..10 SHOW_LIST .. LIST_WRITE_RESULT
CHOICE_STATE_LAST  = 11         @ CANCEL_YES_NO, the last state

@ Evolution's post-scene move-learning prompt. sub_02075A7C allocates a 0xBC-byte
@ task data block and installs sub_02077270 as VBlank with that block as its
@ callback argument (gSystem + 4). Its two-option controller is local ARM9 code,
@ not overlay 27 or BattleInput. Both prompts share these fields and the same
@ MAIN_1 27x4 dialog geometry as the battle Yes/No box.
EVOLUTION_DATA_LAST_OFF = 0xB8
EVOLUTION_BG_OFF        = 0x00
EVOLUTION_WINDOW_OFF    = 0x04
EVOLUTION_STATE_OFF     = 0x64
EVOLUTION_SUBSTATE_OFF  = 0x8A
EVOLUTION_CHOICE_OFF    = 0x8B
EVOLUTION_WINDOW_LAST_OFF = 0x0C
EVOLUTION_WINDOW_GEOM0  = 0x1B130201 @ bg 1, x 2, y 19, width 27
EVOLUTION_WINDOW_GEOM1  = 0x001F0B04 @ height 4, palette 11, base tile 31
EVOLUTION_FORGET_SETUP  = 20
EVOLUTION_FORGET_INPUT  = 21
EVOLUTION_GIVEUP_SETUP  = 34
EVOLUTION_GIVEUP_INPUT  = 35
EVOLUTION_STATE_HI      = 45
EVOLUTION_TASK_ORIG     = 0x02075D09 @ sub_02075D08, Thumb


@ --------------------------------------------------------------------------
@ Data. ITCM is RAM, so all of this is writable at runtime.
@ --------------------------------------------------------------------------
    .global OneScreen_Signature
OneScreen_Signature:
    .ascii  "1SGS"
    .word   0x0000001F          @ payload version

@ Filled in by the patcher from the ROM being patched. Defaults are French, so
@ an unconfigured payload still works there. Keep the field order in step with
@ CONFIG_FIELDS in onescreen/inject.py.
    .global OneScreen_Config
OneScreen_Config:
cfg_pad_held:       .word DEF_PAD_HELD
cfg_app_callback:   .word DEF_APP_CALLBACK
cfg_field_callback: .word DEF_FIELD_CALLBACK
cfg_ov12_lo:        .word DEF_OV12_LO
cfg_ov12_hi:        .word DEF_OV12_HI
cfg_battle_state:   .word DEF_BATTLE_STATE
cfg_dex_exec_orig:  .word DEF_DEX_EXEC_ORIG
cfg_pc_exec_orig:   .word DEF_PC_EXEC_ORIG
cfg_field_sys:      .word DEF_FIELD_SYS
cfg_screens_flip:   .word DEF_SCREENS_FLIP
cfg_map_exec_orig:  .word DEF_MAP_EXEC_ORIG
cfg_start_menu_task: .word DEF_START_MENU_TASK
cfg_oak_exec_orig:  .word DEF_OAK_EXEC_ORIG
cfg_battle_exec_orig: .word DEF_BATTLE_EXEC_ORIG
cfg_intro_a_exec:   .word DEF_INTRO_A_EXEC
cfg_intro_b_exec:   .word DEF_INTRO_B_EXEC
cfg_intro_c_exec:   .word DEF_INTRO_C_EXEC
cfg_intro_clock:    .word DEF_INTRO_CLOCK
cfg_theme_band:     .word DEF_THEME_BAND
cfg_menu_exec_orig: .word DEF_MENU_EXEC_ORIG
cfg_show_list:      .word DEF_SHOW_LIST
cfg_list_items_width: .word DEF_LIST_ITEMS_WIDTH
cfg_setup_native:   .word DEF_SETUP_NATIVE

pad_held:       .word 0
pad_new:        .word 0         @ newly pressed this frame
prev_pad:       .word 0

menu_swapped:   .word 0         @ 1 while WE swapped for the overworld X menu
last_app:       .word 0

bt_phase:       .word NO_STATE  @ last battle phase acted on
bt_menu_last:   .word NO_STATE  @ last menu id acted on, for edge detection
bt_manual:      .word 0         @ 1 while an L+R override is holding, in battle
bt_system:      .word 0         @ live BattleSystem*, or 0 outside a battle
bt_drawn:       .word -1        @ label image currently blitted, -1 = nothing
bt_lock:        .word -1        @ image frozen at the moment A was pressed, -1 = free
oak_drawn:      .word -1        @ prompt image in Oak's dialog box, -1 = none
oak_data:       .word 0         @ diagnostics: OakSpeechData, its state,
oak_state:      .word -1

dex_last:       .word -1        @ last Pokedex proc_state acted on
dex_mode:       .word 0         @ 0 = grid/info side, 1 = the area map
pc_frames:      .word 0         @ frames left to hold the PC box routing
script_menu:    .word 0         @ 1 while we own routing for a field script menu
field_yn_drawn: .word -1        @ field choice copied into MAIN_3, -1 = nothing
evolution_drawn: .word -1       @ evolution Oui/Non copied into MAIN_1
field_restore:  .word 0         @ frames left to force the world back on top
map_frames:     .word 0         @ counts down once the fly map stops running
map_pending:    .word 0         @ frames left waiting for the field to pick up
prev_task:      .word 0         @ last frame's fieldSystem->taskman
sm_drawn:       .word 0         @ 1 once the X menu's tiles and palettes are in VRAM
sm_shown:       .word 0         @ 1 while a panel is actually ON SCREEN. Separate from
                                @ sm_drawn on purpose: that one means "the tiles are
                                @ uploaded" and gets cleared to force a re-upload, and
                                @ when the wipe was gated on it too, clearing it left
                                @ the panel on screen with nothing willing to remove it
list_ctrl:      .word 0         @ overlay 27's touch controller, or 0 - see FieldMode3
list_drawn:     .word 0         @ 1 once a list menu's pool is in VRAM
list_rect:      .word 0         @ x | cols<<8 | rows<<16 of the panel last drawn
list_hold:      .word 0         @ frames left to keep a panel that stopped confirming
intro_hold_until: .word 0       @ tick the last intro sequence stops, 0 = idle
wl_ret:         .word 0         @ the result var of the list OneScreen_MenuExec opened
wl_last:        .word 0         @ that list's last value, which B stands for
oak_blink_held: .word 0         @ 1 while we hold Oak's palette blink paused

@ Kept below the word variables above, not among them: tools/savestate.py reads
@ that run as a flat array of words and a six-byte table in the middle of it
@ would silently shift every name after it.
@
@ sCursorArrayMainMenu (src/battle/battle_input.c:281) flattened to
@ [menuY*3 + menuX], mapping the game's 2x3 cursor grid onto our four label
@ images. FIGHT spans the whole top row; the bottom row is BAG, RUN, POKEMON
@ left to right - which is why the labels are drawn in that arrangement rather
@ than a 2x2. Values are image indices: 0 FIGHT, 1 BAG, 2 POKEMON, 3 RUN.
cursor_cmd:
    .byte   0, 0, 0
    .byte   1, 3, 2
    .align  2

@ What each touch layout's start menu sets of SM_NORMAL_MASK (SAVE | 7 | RETIRE)
@ in its inhibit flags - FieldSystem_GetStartMenuButtonInhibitFlags_* in
@ src/start_menu.c: normal, Safari, Bug Contest, Pal Park, Union Room,
@ Colosseum, Battle Tower partner room.
sm_layout_class:
    .hword  0x180, 0x090, 0x090, 0x090, 0x110, 0x190, 0x190
    .align  2



@ Apps that route the wrong engine to the top and never write POWCNT1 in a way
@ our static site flips can catch. Pairs of {callback, swap}, terminated by 0.
@   swap 0 = engine A to the top   (use when the app draws its UI on engine A)
@   swap 1 = engine B to the top   (use when its UI is on engine B)
@
@ The patcher fills the callback addresses in, after checking that the code at
@ each one still matches the routine we expect - see regions.check_app_table. An
@ entry it cannot vouch for is zeroed, which ends the table early and simply
@ leaves that app alone rather than swapping on a wrong address. The values
@ assembled here are the French ones, so an unconfigured payload still works.
    .global OneScreen_AppTable
OneScreen_AppTable:
app_table:
    @ Name entry (rival/player/Pokémon nicknames). Not an OverlayManager app -
    @ this is the small ARM9 routine that sets the global flag at 0x021D1195 and
    @ calls the shared display helper, which puts its keyboard (drawn on engine
    @ A) on the bottom screen. Measured byte-identical in IPGF, IPKF and IPKE.
    .word   0x02083141, 0

    @ The evolution scene, and the move it teaches afterwards. Not an
    @ OverlayManager application and not part of the battle - it is ARM9 code
    @ driven from wherever the evolution was triggered, and it sets POWCNT1
    @ nowhere, so it simply keeps whatever routing it inherits. Coming from the
    @ bag that is the menu's, which put the narration on the bottom screen. It
    @ draws its Pokemon and text on engine A, so 0.
evolution_app:
    .word   0x02077271, 0

    @ The move relearner - overlay 68's MoveRelearner_Main. Unlike the two above
    @ it is not ARM9 code, so the patcher finds it by searching the overlay and
    @ fills this slot in; overlay code moves between regions and a fixed address
    @ would only ever be right for one of them. Its move list is on engine B, so
    @ 1 rather than 0.
relearner_app:
    .word   0, 0

    @ Terminator. Every slot above is rewritten at patch time, and
    @ OneScreen_AppTableEnd bounds that write - one entry too many used to run
    @ straight into OneScreen_SetSwap below and black-screen the game on boot.
    .word   0, 0
    .global OneScreen_AppTableEnd
OneScreen_AppTableEnd:


@ ---------------------------------------------------------------------------
@ void OneScreen_SetSwap(int swapped)
@   r0 == 0 -> engine A to the TOP screen
@   r0 != 0 -> engine A to the BOTTOM, engine B to the top
@
@ Note what this does NOT mean. It is tempting to read r0 = 1 as "bring the touch
@ UI up", and that is true for most apps only because they happen to draw their
@ touch UI on engine B. The PC box is the counter-example: stock HGSS runs
@ `POWCNT1 &= ~0x8000` there, putting engine B on TOP, which means its box grid
@ is on engine A. Passing 1 for the PC shoved the grid back down and undid the
@ static flip that had already put it on top. Always establish which engine an
@ app actually draws on before choosing a value.
@
@ This writes POWCNT1 directly, which is why callers have to re-apply it every
@ frame while a menu is up. The game routes screens through
@
@     void GfGfx_SwapDisplay(void) {          // src/gf_gfx_planes.c
@         if (gSystem.screensFlipped == 0) GX_SetDispSelect(GX_DISP_SELECT_MAIN_SUB);
@         else                             GX_SetDispSelect(GX_DISP_SELECT_SUB_MAIN);
@     }
@
@ so any app that calls it stamps its own idea of the routing back over ours -
@ exactly the "sub-screens re-assert the routing" behaviour worked around below.
@ Setting gSystem.screensFlipped (+0x69) instead would be the game-native way to
@ do this and would not need re-applying. Not changed here because the current
@ approach is tested and shipping; see docs/AUDIT.md before reworking it.
@ ---------------------------------------------------------------------------
    .global OneScreen_SetSwap
    .thumb_func
OneScreen_SetSwap:
    ldr     r2, =POWCNT1
    ldrh    r1, [r2]
    lsrs    r3, r2, #11             @ 0x04000304 >> 11 == 0x8000
    cmp     r0, #0
    beq     1f
    bics    r1, r3                  @ clear bit 15 -> UI on top
    b       2f
1:  orrs    r1, r3                  @ set bit 15 -> engine A on top
2:  strh    r1, [r2]
    bx      lr
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ void OneScreen_Toggle(void)
@ ---------------------------------------------------------------------------
    .global OneScreen_Toggle
    .thumb_func
OneScreen_Toggle:
    ldr     r2, =POWCNT1
    ldrh    r1, [r2]
    lsrs    r0, r2, #11
    eors    r1, r0
    strh    r1, [r2]
    bx      lr
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ void OneScreen_UpdatePad(void)
@ Sample the pad once per frame and derive the newly-pressed edges, so every
@ other routine works from the same snapshot.
@ ---------------------------------------------------------------------------
    .global OneScreen_UpdatePad
    .thumb_func
OneScreen_UpdatePad:
    ldr     r0, =cfg_pad_held
    ldr     r0, [r0]
    ldr     r0, [r0]
    ldr     r1, =prev_pad
    ldr     r2, [r1]
    str     r0, [r1]
    mvns    r2, r2
    ands    r2, r0                  @ newly pressed = held & ~prev
    ldr     r1, =pad_held
    str     r0, [r1]
    ldr     r1, =pad_new
    str     r2, [r1]
    bx      lr
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ void OneScreen_AutoBattle(void)
@
@ The screen no longer moves while you are choosing. The four commands are drawn
@ onto the battle scene itself (OneScreen_BattleDraw), so there is nothing to
@ raise and nothing to time out - the routing only changes once you have actually
@ picked something and the game needs a screen we cannot draw on.
@
@   turn executing              -> battle scene on top
@   root command menu (1..4)    -> battle scene on top, commands drawn over it
@   a yes/no prompt (13..17)    -> battle scene on top, Oui/Non drawn over it
@   bag or party (overlay 8)    -> hand the screen over, every frame
@   any other menu (5..12, 19..) -> hand the screen over, every frame
@   no menu yet (-1 / 0)        -> leave the scene alone; the intro is playing
@
@ What this replaces: the menu used to come up on a D-pad or A press and step
@ aside after ~1 s of stillness, which meant guessing at intent from the pad. The
@ game's own menu id says what is happening, so none of that guessing survives.
@
@ Gated on the running app living inside overlay 12, so none of this can affect
@ the overworld or any menu - those are handled by the static site flips.
@ ---------------------------------------------------------------------------
    .global OneScreen_AutoBattle
    .thumb_func
OneScreen_AutoBattle:
    push    {r4, r5, lr}
    ldr     r4, =bt_phase

    ldr     r0, =cfg_app_callback
    ldr     r0, [r0]
    ldr     r0, [r0]
    ldr     r1, =cfg_ov12_lo
    ldr     r1, [r1]
    cmp     r0, r1
    blo     29f
    ldr     r1, =cfg_ov12_hi
    ldr     r1, [r1]
    cmp     r0, r1
    bhs     29f

    @ Collapse the raw state to a single bit first. It takes several values while
    @ awaiting a command (0x0A menu, 0x08 sub-screen), and treating each of those
    @ as a transition would reset the interaction state - dropping the menu as
    @ soon as you opened the bag.
    @ The slot's `active` flag, not just its id. Battle_Run keeps running after
    @ the fight is over - BSTATE_EVOLUTION_INIT and friends are part of the same
    @ application - so the battle logic was still live during an evolution and
    @ the move it teaches. Mashing A through that text raised the command menu,
    @ which put the narration on the bottom screen.
    @
    @ A stale id in a released slot reads the same as a live one, so the id alone
    @ cannot tell the difference; `active` can. Measured 1 in three mid-battle
    @ savestates, so requiring it cannot stop a real battle from swapping.
    ldr     r0, =cfg_battle_state
    ldr     r0, [r0]
    ldr     r1, [r0, #4]            @ sOverlayRegions[OVY_REGION_MAIN][3].active
    cmp     r1, #0
    beq     29f                     @ released: the battle proper has ended
    ldrb    r0, [r0]
    movs    r5, #0
    cmp     r0, #BATTLE_STATE_EXEC
    bne     20f
    movs    r5, #1                  @ executing
20: ldr     r1, [r4]
    cmp     r5, r1
    beq     21f                     @ same phase as last frame

    @ --- phase changed: reset the interaction state ---
    str     r5, [r4]
    bl      OneScreen_ResetBattleUi
    cmp     r5, #0
    beq     28f                     @ entering "awaiting command": do NOT swap
    movs    r0, #0                  @ turn executing -> battle scene on top
    bl      OneScreen_SetSwap
    b       28f

21: cmp     r5, #0
    bne     28f                     @ mid-turn: nothing to do

    @ --- awaiting a command: the menu id decides everything ---
    @ The old rule watched the pad and guessed at intent - a D-pad or A press
    @ raised the whole menu, and ~1 s of stillness dropped it again. It no longer
    @ has to guess, because the labels are on the battle scene itself: the screen
    @ only changes when the player has actually chosen something, and the game
    @ says when that happened by moving off its root menu.
    @
    @ Reading the menu id also retires the battle-intro problem for free. The
    @ phase proxy reads "awaiting a command" from the moment overlay 10 loads,
    @ which is while the intro text is still playing - but curMenuId is
    @ BATTLE_MENU_0 until the menu actually opens, so mashing A through the
    @ intro now does nothing instead of pinning the menu for the rest of the
    @ fight.
    bl      OneScreen_BattleMenuId
    movs    r5, r0

    @ An L+R override holds until the menu you are on changes - moving into the
    @ move list, or backing out of it, hands control back to us. Without this the
    @ escape hatch would be useless in battle, since the routing is now
    @ re-asserted every frame rather than once.
    ldr     r0, =bt_menu_last
    ldr     r1, [r0]
    cmp     r1, r5
    beq     27f
    str     r5, [r0]
    ldr     r0, =bt_manual
    movs    r1, #0
    str     r1, [r0]
27: ldr     r0, =bt_manual
    ldr     r0, [r0]
    cmp     r0, #0
    bne     28f                     @ the player has taken the screen; leave it

    @ The bag and the party are their own overlay, and they do not move
    @ curMenuId off the root menu while they are up - so going by the menu id
    @ alone left them drawing on the bottom screen the first time they opened.
    @ The overlay id says it outright, and it is the same signal the old timeout
    @ logic used for exactly this case.
    bl      OneScreen_BattleSubOpen
    cmp     r0, #0
    bne     25f

    subs    r0, r5, #BATTLE_MENU_ROOT_LO
    cmp     r0, #(BATTLE_MENU_ROOT_HI - BATTLE_MENU_ROOT_LO)
    bls     26f                     @ 1..4: the root command menu
    movs    r0, r5                  @ 3-bit immediate cannot reach 13
    subs    r0, #BATTLE_MENU_TWO_LO
    cmp     r0, #(BATTLE_MENU_TWO_HI - BATTLE_MENU_TWO_LO)
    bls     26f                     @ 13..17: a yes/no prompt, drawn on the scene
    cmp     r5, #0
    ble     28f                     @ -1 / 0: no menu is up, leave the scene alone

    @ A submenu is open - the move list, target select. That is drawn on engine
    @ B, so hand the screen over, and keep handing it over: these sub-screens
    @ re-assert the routing themselves as they open, so a one-shot swap gets
    @ undone the moment you go a level deeper.
25: movs    r0, #1
    bl      OneScreen_SetSwap
    b       28f

    @ The root command menu. Keep the battle scene on the top screen - the four
    @ commands are drawn onto it rather than replacing it.
26: movs    r0, #0
    bl      OneScreen_SetSwap
    b       28f

29: movs    r0, #NO_STATE           @ not in a battle: re-arm for next time
    str     r0, [r4]
    movs    r0, #0                  @ drop the BattleSystem: the heap it lives
    ldr     r1, =bt_system          @ in is freed when the battle ends
    str     r0, [r1]
    bl      OneScreen_ResetBattleUi
28: pop     {r4, r5, pc}
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ BattleInput *OneScreen_BattleInput(void) -> the live BattleInput, or 0.
@
@ The one place the battle structs are dereferenced, so every reader gets the
@ same checks. battleInput is only valid while BattleSystem.graphicsMode is 0:
@ the bag and the party (3) and the catch naming screen (1/2) free it and leave
@ the pointer behind, and the hook used to read curMenuId out of that freed
@ block - which is why the bag appeared to "leave curMenuId on the root menu".
@ bt_system itself is only published while Battle_Run is in BSTATE_BATTLE_MAIN;
@ see OneScreen_BattleExec.
@ ---------------------------------------------------------------------------
    .thumb_func
OneScreen_BattleInput:
    push    {r4, lr}
    ldr     r0, =bt_system
    ldr     r4, [r0]
    movs    r0, r4
    ldr     r1, =(BS_GRAPHICS_MODE_OFF + 1)
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     31f
    ldr     r0, =BS_GRAPHICS_MODE_OFF
    ldrb    r0, [r4, r0]
    cmp     r0, #0
    bne     31f                     @ a sub-screen owns the input: freed
    ldr     r1, =BATTLE_INPUT_OFF
    ldr     r4, [r4, r1]
    movs    r0, r4
    ldr     r1, =BATTLE_INPUT_SIZE
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     31f
    movs    r0, r4
    pop     {r4, pc}
31: movs    r0, #0
    pop     {r4, pc}
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ int OneScreen_BattleMenuId(void)
@   -> r0 = battleInput->curMenuId, or BATTLE_MENU_NONE (-1) if there is no
@      live battle to read it from.
@
@ Returning -1 for "cannot tell" is deliberate: the caller treats every id <= 0
@ as "no menu is up" - leave the battle scene alone and draw nothing.
@ ---------------------------------------------------------------------------
    .thumb_func
OneScreen_BattleMenuId:
    push    {r3, lr}
    bl      OneScreen_BattleInput
    cmp     r0, #0
    beq     31f
    ldr     r1, =BI_CURMENU_OFF
    ldrsb   r0, [r0, r1]
    pop     {r3, pc}
31: movs    r0, #0
    mvns    r0, r0                  @ -1
    pop     {r3, pc}
    .align  2
    .pool

@ int OneScreen_BattleSubOpen(void) -> 1 while a battle sub-screen owns engine B
@ (bag category, item list, party). This is the overlay id, not the menu id: the
@ bag and party run as overlay 8, and the BattleInput the menu id lives in is
@ freed while they are up.
    .thumb_func
OneScreen_BattleSubOpen:
    ldr     r0, =cfg_battle_state
    ldr     r0, [r0]
    ldrb    r0, [r0]
    cmp     r0, #BATTLE_STATE_SUB
    beq     63f
    movs    r0, #0
    bx      lr
63: movs    r0, #1
    bx      lr
    .align  2
    .pool

@ int OneScreen_BattleYesNo(void) -> the label image for a two-option prompt.
@ One column, two rows, so menuY alone is the answer.
    .thumb_func
OneScreen_BattleYesNo:
    push    {r3, lr}
    bl      OneScreen_BattleInput
    cmp     r0, #0
    beq     64f
    ldr     r1, =BI_MENU_CURSOR_OFF
    adds    r0, r0, r1
    ldrb    r0, [r0, #1]            @ menuY
    cmp     r0, #1
    bls     65f
64: movs    r0, #0
65: adds    r0, #(LABEL_GEO_YN << 4)
    pop     {r3, pc}
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ int OneScreen_BattleCursor(void)
@   -> r0 = which command is highlighted, as a label image index 0..3.
@
@ Read from the game's own BattleMenuCursor rather than tracked here. The game
@ already moves this on the D-pad (BattleInput_CursorMove_MainMenu), remembers it
@ per battler between turns, and applies its own wrap rules at the edges; keeping
@ a second copy in the hook would only be a second thing to drift.
@
@ menuY/menuX are clamped rather than trusted, so a surprise in the struct still
@ returns a valid image instead of indexing off the end of a six-byte table.
@ ---------------------------------------------------------------------------
    .thumb_func
OneScreen_BattleCursor:
    push    {r3, lr}
    bl      OneScreen_BattleInput
    cmp     r0, #0
    beq     34f
    ldr     r1, =BI_MENU_CURSOR_OFF
    adds    r0, r0, r1
    ldrb    r1, [r0, #1]            @ menuY
    ldrb    r2, [r0, #2]            @ menuX
    cmp     r1, #1
    bls     32f
    movs    r1, #0
32: cmp     r2, #2
    bls     33f
    movs    r2, #0
33: lsls    r0, r1, #1
    adds    r0, r0, r1              @ menuY * 3
    adds    r0, r0, r2
    ldr     r1, =cursor_cmd
    ldrb    r0, [r1, r0]
    pop     {r3, pc}
34: movs    r0, #0                  @ no cursor to read: show FIGHT selected
    pop     {r3, pc}
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ void OneScreen_BattleMenu(int image)
@
@ Blit one of the label images into the battle message window. This is the whole
@ renderer: the labels were rasterised from the ROM's own strings and font at
@ patch time, so at runtime there is no font, no heap and no call into game code
@ - just tiles copied into VRAM the game has already allocated, mapped and
@ palettised for its own message box.
@
@ The destination is window[0] on GF_BG_LYR_MAIN_1, whose tiles are contiguous
@ per row and stride by the full 27-tile window width between rows. Those row
@ offsets are precomputed in the blob header, so this is four flat copies.
@
@ Called every frame while the menu is up, for the same reason SetSwap is: the
@ game rewrites this window whenever it prints, so the last write in the frame
@ has to be ours. 1792 bytes a frame.
@ ---------------------------------------------------------------------------
    .global OneScreen_BattleMenu
    .thumb_func
OneScreen_BattleMenu:
    push    {r4, r5, r6, r7, lr}
    ldr     r7, =OneScreen_Labels
    ldr     r1, [r7]
    ldr     r2, =LABEL_MAGIC
    cmp     r1, r2
    bne     39f                     @ blob never filled in: draw nothing at all
    ldrb    r6, [r7, #4]            @ rows

    lsrs    r1, r0, #4              @ which set
    ldrb    r2, [r7, #5]            @ number of geometry records
    cmp     r1, r2
    bhs     39f                     @ bad image code: stay inside the header
    movs    r2, #LABEL_GEO_SIZE
    muls    r1, r2
    adds    r1, #8
    adds    r1, r7, r1              @ -> its geometry record
    movs    r2, #15
    ands    r0, r2                  @ index within the set
    ldrh    r2, [r1, #10]           @ images in this set, including its wipe
    cmp     r0, r2
    bhs     39f                     @ bad index: stay inside its image data

    ldr     r3, [r1, #4]            @ bytes per image
    muls    r3, r0
    ldr     r2, [r1]                @ where this set's images start
    adds    r3, r3, r2
    adds    r4, r7, r3              @ src
    ldrh    r5, [r1, #8]            @ bytes per tile row

    @ The last image of every set is the wipe: solid paper, and not stored. Four
    @ of them was 3840 bytes of 0xFF in a blob that had none to spare, so it is
    @ filled here instead. Asking for it is unchanged - the records still count it.
    ldrh    r2, [r1, #10]           @ images, wipe included
    subs    r2, #1
    cmp     r0, r2
    bne     34f
    movs    r4, #0                  @ 0 = fill, and r4 is the source otherwise
34: movs    r7, r1                  @ 3-bit immediate cannot reach 12
    adds    r7, #12                 @ -> the row address table

    movs    r3, #0
35: cmp     r3, r6
    bhs     39f
    lsls    r0, r3, #2
    ldr     r0, [r7, r0]            @ absolute destination; the boxes sit on
    movs    r2, r5                  @ different character bases
    cmp     r4, #0
    beq     37f
36: ldmia   r4!, {r1}
    stmia   r0!, {r1}
    subs    r2, #4
    bne     36b
    b       38f
37: movs    r1, #0                  @ all-paper: every nibble 0xF
    subs    r1, #1
33: stmia   r0!, {r1}
    subs    r2, #4
    bne     33b
38: adds    r3, #1
    b       35b
39: pop     {r4, r5, r6, r7, pc}
    .align  2
    .pool

@ int OneScreen_BattleWipe(int set) -> the image code that blanks that set's box.
@ The all-paper image is the last one of each set, so this is read from the blob
@ rather than known here.
    .thumb_func
OneScreen_BattleWipe:
    lsls    r3, r0, #4
    ldr     r1, =OneScreen_Labels
    ldrb    r2, [r1, #5]
    cmp     r0, r2
    bhs     38f                     @ missing geometry: return an invalid code
    movs    r2, #LABEL_GEO_SIZE
    muls    r0, r2
    adds    r0, #8
    adds    r0, r1, r0
    ldrh    r0, [r0, #10]           @ images in the set
    subs    r0, #1
    orrs    r0, r3
    bx      lr
38: movs    r0, #0
    mvns    r0, r0                  @ blitter's set-count check rejects -1
    bx      lr
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ void OneScreen_BattleDraw(int menu_id)
@
@ Only the root command menu draws labels, and it redraws them EVERY frame: the
@ game rewrites window[0] whenever the message printer runs, so a one-shot blit
@ gets painted over. This is the same rule the display routing already lives by.
@
@ Coming down is the opposite - wipe exactly ONCE, on the transition. Blitting
@ paper every frame would keep clearing the right-hand end of the message window
@ for the whole turn, which is where a long battle message goes. bt_drawn is what
@ separates the two: it holds the image on screen, or -1 for "we have taken our
@ labels down and the window is the game's again".
@ ---------------------------------------------------------------------------
    .thumb_func
OneScreen_BattleDraw:
    push    {r4, r5, lr}
    movs    r5, r0
    bl      OneScreen_BattleSubOpen
    cmp     r0, #0
    bne     41f                     @ the bag or party owns the screen
    subs    r1, r5, #BATTLE_MENU_ROOT_LO
    cmp     r1, #(BATTLE_MENU_ROOT_HI - BATTLE_MENU_ROOT_LO)
    bls     40f
    movs    r1, r5                  @ 3-bit immediate cannot reach 13
    subs    r1, #BATTLE_MENU_TWO_LO
    cmp     r1, #(BATTLE_MENU_TWO_HI - BATTLE_MENU_TWO_LO)
    bls     44f

    @ Nothing of ours belongs on screen: take down whichever box is up. The lock
    @ deliberately SURVIVES this. Going into the bag and back out is not a phase
    @ change, so without the lock the root menu would be redrawn from a cursor the
    @ game has not restored yet and ATTAQUE would flash. Holding the image the
    @ player last confirmed is also simply correct - the game restores the cursor
    @ to that same choice. ResetBattleUi drops it when the turn actually runs.
41: ldr     r0, =bt_drawn
    ldr     r1, [r0]
    adds    r2, r1, #1
    beq     42f                     @ was -1: nothing of ours on screen
    movs    r2, #0
    mvns    r2, r2
    str     r2, [r0]
    lsrs    r0, r1, #4              @ the set that is currently up
    bl      OneScreen_BattleWipe
    bl      OneScreen_BattleMenu
    b       42f

40: bl      OneScreen_BattleCursor
    b       45f
44: bl      OneScreen_BattleYesNo
45: movs    r4, r0

    @ Confirming a choice resets the game's cursor before the menu id changes, so
    @ for a frame or two the highlight would snap back to FIGHT and be visible as
    @ a flash on the way out. Freeze the image the player was actually looking at
    @ when they pressed A, and hold it until the menu changes or they move again.
    ldr     r0, =pad_new
    ldr     r0, [r0]
    ldr     r1, =DPAD_MASK
    ands    r1, r0
    cmp     r1, #0
    beq     46f
    ldr     r1, =bt_lock            @ moved: the lock is stale
    movs    r2, #0
    mvns    r2, r2
    str     r2, [r1]
46: ldr     r1, =bt_lock
    ldr     r2, [r1]
    adds    r3, r2, #1
    beq     47f
    lsrs    r3, r2, #4              @ a lock only holds within its own box:
    lsrs    r5, r4, #4              @ a command image means nothing to a yes/no
    cmp     r3, r5                  @ prompt, and would index the wrong set
    bne     47f
    movs    r4, r2                  @ locked: keep showing it
    b       48f
47: movs    r2, #KEY_A
    ands    r0, r2
    cmp     r0, #0
    beq     48f
    ldr     r0, =bt_drawn
    ldr     r0, [r0]
    adds    r2, r0, #1
    beq     48f                     @ nothing on screen yet to freeze
    str     r0, [r1]
    movs    r4, r0
48: ldr     r0, =bt_drawn
    str     r4, [r0]
    ldr     r0, =BAND_DEST_BATTLE   @ colour the selected band before drawing on it
    bl      OneScreen_BandTheme
    movs    r0, r4
    bl      OneScreen_BattleMenu
42: pop     {r4, r5, pc}
    .align  2
    .pool

@ void OneScreen_ResetBattleUi(void) - forget what is on screen, so nothing is
@ wiped on the way out of a battle whose window has already gone, and drop any
@ L+R override so the next battle does not start out of our hands.
    .thumb_func
OneScreen_ResetBattleUi:
    movs    r1, #0
    mvns    r1, r1
    ldr     r0, =bt_drawn
    str     r1, [r0]
    ldr     r0, =bt_menu_last
    str     r1, [r0]
    movs    r1, #0
    ldr     r0, =bt_manual
    str     r1, [r0]
    movs    r1, #0                  @ the frozen highlight belongs to the last turn
    mvns    r1, r1
    ldr     r0, =bt_lock
    str     r1, [r0]
    bx      lr
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ int OneScreen_BattleExec(OverlayManager *manager, int *proc_state)
@
@ Installed in place of the battle application's exec pointer, the same trick
@ the Pokedex, PC box, fly map and Oak's speech already use. The battle is the
@ awkward one to find: every other application puts init/exec/exit *inside* the
@ overlay they name, but the battle's three are thin ARM9 wrappers (pret's
@ src/launch_application.c), so regions.find_overlay_template needs its
@ arm9_resident shape - three Thumb ARM9 pointers followed by `ovy_id == 12`.
@ Exactly one match in IPGF, IPKF and IPKE (FR/HG-FR 0x020FA468, US 0x020FA484),
@ with identical code pointers in all three, so this is region-neutral like the
@ rest.
@
@ What it is for: manager->data is the live BattleSystem, which is the root for
@ everything the top-screen command menu needs - the window it draws into, the
@ menu the player is on, and the cursor cell to highlight. Reading it here beats
@ hunting for it in RAM: the framework hands us the manager every frame.
@
@ Ordering follows OneScreen_OakExec: run the app's real exec FIRST, then read
@ manager->data. Two reasons - the pointer does not exist until Battle_Init has
@ run, and anything we draw has to land after the game's own window redraw for
@ the frame, or it gets painted over. `docs/AUDIT.md:133` calls that failure
@ class 4, and it is the reason the PC box needed a hold.
@
@ manager->data is only a BattleSystem while Battle_Run is in
@ BSTATE_BATTLE_MAIN (src/battle/battle_022378C0.c): during the link stages it
@ is the link work area, and once the battle ends it is freed while the same
@ application runs the evolution and the move it teaches. So the pointer is
@ published only in that state, read after the real exec has had its say.
@ ---------------------------------------------------------------------------
BATTLE_DATA_OFF = 0x08          @ manager->data, from &proc_state (+0x14)

    .global OneScreen_BattleExec
    .thumb_func
OneScreen_BattleExec:
    push    {r4, r5, lr}
    movs    r4, r1                  @ &proc_state, to survive the call
    ldr     r3, =cfg_battle_exec_orig
    ldr     r3, [r3]
    blx     r3
    movs    r5, r0                  @ keep its return value
    ldr     r0, [r4]                @ proc_state, after this frame's transition
    cmp     r0, #BSTATE_BATTLE_MAIN
    bne     44f
    ldr     r4, [r4, #BATTLE_DATA_OFF]
    b       46f
44: movs    r4, #0                  @ no BattleSystem to speak of
46: ldr     r0, =bt_system
    str     r4, [r0]

    @ Draw here rather than from the main-loop hook, because here we are AFTER
    @ the battle app has run for this frame - so whatever it printed into the
    @ message window is already down, and our labels go on top of it instead of
    @ under it. That is failure class 4 in docs/AUDIT.md, the one that cost the
    @ PC box a hold.
    cmp     r4, #0
    beq     45f
    bl      OneScreen_BattleMenuId
    bl      OneScreen_BattleDraw
45: movs    r0, r5
    pop     {r4, r5, pc}
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ int OneScreen_DexExec(OverlayManager *manager, int *proc_state)
@
@ Installed in place of the Pokedex application's exec pointer, in the
@ OverlayManagerTemplate that lives in ARM9 static data. The framework hands us
@ r1 = &manager->proc_state, i.e. the current screen level, then we tail-call
@ the real exec so the app is unaffected.
@
@ Edge-triggered on the level changing, so a manual L+R is not fought while you
@ sit on a screen - but re-applied on every change, not only when the side
@ flips, because the app reconfigures the display as it builds each screen.
@ ---------------------------------------------------------------------------
    .global OneScreen_DexExec
    .thumb_func
OneScreen_DexExec:
    push    {r0, r1, lr}
    ldr     r2, [r1]                @ proc_state = the screen level
    ldr     r3, =dex_last
    ldr     r0, [r3]
    cmp     r0, r2
    beq     53f                     @ same level as last frame
    str     r2, [r3]

    @ A fade wait tells us nothing about which side we are on: hold.
    movs    r0, r2
    subs    r0, #DEX_FADE_LO
    cmp     r0, #(DEX_FADE_HI - DEX_FADE_LO)
    bls     52f
    cmp     r2, #DEX_TAB_FADE
    beq     52f

    movs    r0, r2
    subs    r0, #DEX_MAP_LO
    cmp     r0, #(DEX_MAP_HI - DEX_MAP_LO)
    bhi     50f
    movs    r0, #1                  @ the area map -> engine B on top
    b       51f
50: movs    r0, #0                  @ anything else -> engine A on top
51: ldr     r3, =dex_mode
    str     r0, [r3]

52: ldr     r3, =dex_mode
    ldr     r0, [r3]
    bl      OneScreen_SetSwap
53: pop     {r0, r1}
    pop     {r2}
    mov     lr, r2
    ldr     r3, =cfg_dex_exec_orig
    ldr     r3, [r3]
    bx      r3                      @ tail-call the app's real exec

    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ int OneScreen_PcExec(OverlayManager *manager, int *proc_state)
@
@ The PC box (overlay 14), installed the same way as the Pokedex trampoline.
@
@ Overlay 14 is one of the 75 the decomp has not reached, so there is no state
@ machine to read - the screen levels came from savestates instead. Reading
@ proc_state out of the live manager at each of them:
@
@     inside a box, cursor on a Pokemon    81
@     inside a box, holding a Pokemon     115
@     item storage                        117
@     fading in / fading out                0   (exec_state 2 / 3)
@
@ and, the useful part, the PC option list ("DEPOT POKEMON" / "MON PC" / ...)
@ has NO overlay-14 manager at all - checked both before entering and after
@ backing out. That list is a field menu; the app only exists once you are
@ inside. So the whole of overlay 14 is "managing the box", and every screen in
@ it wants engine B on top. There is nothing to distinguish, and no per-state
@ rule to get wrong.
@
@ The direction here was wrong twice before it was measured properly. Overlay 14
@ has exactly one POWCNT1 site, and disassembling it in the stock ROM settles
@ which engine the box is on:
@
@     stock     ldr r0,=0xFFFF7FFF ; ands r0,r1 ; strh   ->  clears bit 15
@     patched   ldr r0,=0x00008000 ; orrs r0,r1 ; strh   ->  sets   bit 15
@
@ So stock HGSS puts engine B on the TOP screen for the PC, which means the box
@ grid - the half you actually operate - is drawn on engine A. The static site
@ flip already turns that into "engine A on top", i.e. the grid on top, and it
@ needs no help. Forcing r0 = 1 here, on the assumption that the touch UI must
@ be on engine B like everywhere else, pushed the grid straight back down and
@ undid the flip.
@
@ What remains is only insurance against something re-routing later in the
@ frame: run the app first, then re-assert the SAME direction the flipped site
@ already chose, and arm a countdown so OneScreen_Frame keeps doing it from
@ where the battle logic writes from. Everything now agrees - the flipped site,
@ GfGfx_SwapDisplay with screensFlipped = 0, and us.
@
@ Coming out is self-healing: the countdown lapses and the field re-asserts.
@ ---------------------------------------------------------------------------
    .global OneScreen_PcExec
    .thumb_func
OneScreen_PcExec:
    push    {r4, lr}
    ldr     r3, =cfg_pc_exec_orig
    ldr     r3, [r3]
    blx     r3                      @ let the app run and route as it likes
    movs    r4, r0                  @ keep its return value
    ldr     r0, =pc_frames
    movs    r1, #PC_HOLD_FRAMES
    str     r1, [r0]
    movs    r0, #0                  @ ...then hold engine A on top, which is
    bl      OneScreen_SetFlipped    @ where the box grid is drawn
    movs    r0, #0
    bl      OneScreen_SetSwap
    movs    r0, r4
    pop     {r4, pc}

    .align  2
    .pool

@ void OneScreen_PcHold(void) - re-apply the PC routing from the main loop, for
@ as long as the trampoline keeps re-arming it, and hand the screens back one
@ frame after the app stops calling us.
    .thumb_func
OneScreen_PcHold:
    push    {lr}
    ldr     r1, =pc_frames
    ldr     r0, [r1]
    cmp     r0, #0
    beq     41f
    subs    r0, #1
    str     r0, [r1]
    cmp     r0, #0
    beq     41f                     @ just lapsed: leave it to the field
    movs    r0, #0
    bl      OneScreen_SetFlipped
    movs    r0, #0
    bl      OneScreen_SetSwap
41: pop     {pc}
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ int OneScreen_MapExec(OverlayManager *manager, int *proc_state)
@
@ The fly / town map application, overlay 101. Hooked not for its own routing
@ but for the moment it STOPS running, which is the frame after you confirm a
@ destination - exactly where the swap was asked for.
@
@ Savestates through a flight show the app live with exec_state 2 before the
@ press, exec_state 3 immediately after, and gone by mid-animation with the field
@ running again. The animation is drawn by the FIELD, so there is no app of ours
@ left to hook by then; and the arrived-but-wrong and arrived-and-correct states
@ are identical field for field, differing only in POWCNT1, so no state flag can
@ drive it either. The app going away is the only edge available.
@ ---------------------------------------------------------------------------
    .global OneScreen_MapExec
    .thumb_func
OneScreen_MapExec:
    push    {r4, lr}
    ldr     r3, =cfg_map_exec_orig
    ldr     r3, [r3]
    blx     r3
    movs    r4, r0
    ldr     r0, =map_frames
    movs    r1, #MAP_LAPSE_FRAMES
    str     r1, [r0]
    movs    r0, r4
    pop     {r4, pc}
    .align  2
    .pool

@ void OneScreen_MapHold(void) - notice the fly map going away, then wait for
@ the field to pick up and hand it the screen.
    .thumb_func
OneScreen_MapHold:
    push    {lr}
    ldr     r1, =map_frames
    ldr     r0, [r1]
    cmp     r0, #0
    beq     46f
    subs    r0, #1
    str     r0, [r1]
    cmp     r0, #0
    bne     47f                     @ still running
    ldr     r1, =map_pending        @ it has gone: start waiting for the field
    movs    r0, #MAP_PENDING_FRAMES
    str     r0, [r1]
    b       47f

46: ldr     r1, =map_pending
    ldr     r0, [r1]
    cmp     r0, #0
    beq     47f
    subs    r0, #1
    str     r0, [r1]

    ldr     r0, =cfg_app_callback
    ldr     r0, [r0]
    ldr     r0, [r0]
    cmp     r0, #0
    beq     47f                     @ still handing over; keep waiting
    ldr     r2, =cfg_field_callback
    ldr     r2, [r2]
    cmp     r0, r2
    beq     48f
    movs    r0, #0                  @ some OTHER app took over - backing out of
    str     r0, [r1]                @ the town map into the Pokegear. Cancel.
    b       47f

48: movs    r0, #0                  @ the field has it: this was a flight, which
    str     r0, [r1]                @ returns to the world and not to the menu
    ldr     r1, =menu_swapped
    str     r0, [r1]
    ldr     r1, =field_restore
    movs    r0, #FIELD_RESTORE_FRAMES
    str     r0, [r1]
    movs    r0, #0
    bl      OneScreen_SetSwap       @ and put the world up right now
47: pop     {pc}
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ void OneScreen_SetFlipped(int value)
@ Write gSystem.screensFlipped, the game's OWN routing flag.
@
@ Writing POWCNT1 ourselves is not enough for every app. GfGfx_SwapDisplay reads
@ this byte and re-derives the routing from it, and it can be reached from a
@ VBlank callback - i.e. after everything the main loop does - so a direct
@ POWCNT1 write can be undone later in the same frame no matter where we put it.
@ Overlay 14 has only ONE POWCNT1 site of its own, and gSystem.screensFlipped
@ reads 0 in every PC savestate, so that is exactly what was happening: forcing
@ POWCNT1 every frame from two different places still lost.
@
@ Setting the flag instead makes the game route the way we want on its own, from
@ wherever it re-asserts. Every entry in sMapLoadModes has switchScreens = FALSE,
@ so the game only ever drives this to 0; nothing else fights us for it, and a
@ map change will reset it for free.
@ ---------------------------------------------------------------------------
    .global OneScreen_SetFlipped
    .thumb_func
OneScreen_SetFlipped:
    ldr     r1, =cfg_screens_flip
    ldr     r1, [r1]
    cmp     r1, #0
    beq     45f
    strb    r0, [r1]
45: bx      lr
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ void OneScreen_AppIntent(void)
@ Apply app_table whenever the running app changes. Edge-triggered, so it does
@ not fight a manual L+R and costs a table walk only on transitions.
@ ---------------------------------------------------------------------------
    .global OneScreen_AppIntent
    .thumb_func
OneScreen_AppIntent:
    push    {r4, lr}
    ldr     r0, =cfg_app_callback
    ldr     r0, [r0]
    ldr     r0, [r0]
    ldr     r1, =last_app
    ldr     r2, [r1]
    cmp     r0, r2
    beq     33f                     @ same app as last frame
    str     r0, [r1]

    @ An application just handed the field back (flying is the case that needs
    @ this): arm a short window to put the world on top. Poll consumes it.
    ldr     r1, =cfg_field_callback
    ldr     r1, [r1]
    cmp     r0, r1
    bne     34f
    ldr     r1, =field_restore
    movs    r2, #FIELD_RESTORE_FRAMES
    str     r2, [r1]

34: ldr     r4, =app_table
30: ldr     r2, [r4]
    cmp     r2, #0
    beq     33f                     @ end of table: not listed
    cmp     r2, r0
    beq     32f
    adds    r4, #8
    b       30b
32: ldr     r0, [r4, #4]
    bl      OneScreen_SetSwap
33: pop     {r4, pc}
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ Classify the post-evolution move-learning controller.
@
@ Returns 0 if this is not the verified evolution app or any pointer/geometry is
@ wrong, 1/2 for Yes/No, and 3 for a valid evolution frame with no binary prompt.
@ The native controller remains authoritative; this only mirrors its selection.
@ ---------------------------------------------------------------------------
    .thumb_func
OneScreen_EvolutionChoice:
    push    {r4, r5, r6, lr}
    ldr     r4, =cfg_app_callback
    ldr     r4, [r4]                @ &gSystem.vBlankIntr
    ldr     r0, [r4]
    ldr     r1, =evolution_app
    ldr     r1, [r1]                @ patcher-validated callback, or zero
    cmp     r0, r1
    bne     .Levolution_invalid
    cmp     r1, #0
    beq     .Levolution_invalid

    ldr     r4, [r4, #4]            @ gSystem.vBlankIntrArg -> EvolutionTaskData
    movs    r0, r4
    ldr     r1, =EVOLUTION_DATA_LAST_OFF
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     .Levolution_invalid

    ldr     r5, [r4, #EVOLUTION_BG_OFF]
    movs    r0, r5
    movs    r1, #0
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     .Levolution_invalid
    ldr     r6, [r4, #EVOLUTION_WINDOW_OFF]
    movs    r0, r6
    movs    r1, #EVOLUTION_WINDOW_LAST_OFF
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     .Levolution_invalid
    ldr     r0, [r6]
    cmp     r0, r5                  @ Window belongs to this BgConfig
    bne     .Levolution_invalid
    ldr     r0, [r6, #4]
    ldr     r1, =EVOLUTION_WINDOW_GEOM0
    cmp     r0, r1
    bne     .Levolution_invalid
    ldr     r0, [r6, #8]
    ldr     r1, =EVOLUTION_WINDOW_GEOM1
    cmp     r0, r1
    bne     .Levolution_invalid
    ldr     r0, [r6, #12]           @ pixel buffer must still be live as well
    movs    r1, #0
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     .Levolution_invalid

    movs    r1, #EVOLUTION_STATE_OFF
    ldrb    r0, [r4, r1]
    cmp     r0, #EVOLUTION_STATE_HI
    bhi     .Levolution_invalid
    cmp     r0, #EVOLUTION_FORGET_SETUP
    beq     .Levolution_yes
    cmp     r0, #EVOLUTION_GIVEUP_SETUP
    beq     .Levolution_yes
    cmp     r0, #EVOLUTION_FORGET_INPUT
    beq     .Levolution_live
    cmp     r0, #EVOLUTION_GIVEUP_INPUT
    bne     .Levolution_idle

.Levolution_live:
    movs    r1, #EVOLUTION_SUBSTATE_OFF
    ldrb    r0, [r4, r1]
    cmp     r0, #1                  @ 0 input, 1 confirmation animation
    bhi     .Levolution_invalid
    movs    r1, #EVOLUTION_CHOICE_OFF
    ldrb    r0, [r4, r1]
    cmp     r0, #1
    blo     .Levolution_invalid
    cmp     r0, #2
    bhi     .Levolution_invalid
    b       .Levolution_return      @ native 1/2 already means Yes/No

.Levolution_yes:
    movs    r0, #1
    b       .Levolution_return
.Levolution_idle:
    movs    r0, #3
    b       .Levolution_return
.Levolution_invalid:
    movs    r0, #0
.Levolution_return:
    pop     {r4, r5, r6, pc}
    .align  2
    .pool

@ Draw the compact localized Yes/No in the evolution dialog. Both the first
@ keep/forget prompt and the later give-up/continue prompt use this controller
@ and retain their original inputs.
    .thumb_func
OneScreen_EvolutionPrompt:
    push    {r4, lr}
    bl      OneScreen_EvolutionChoice
    movs    r4, r0
    cmp     r4, #0
    beq     .Levolution_reset       @ never write VRAM through an invalid chain
    cmp     r4, #3
    beq     .Levolution_wipe

    subs    r4, #1                  @ native 1/2 -> image index 0/1
    movs    r0, r4
    adds    r0, #(LABEL_GEO_YN << 4)
    ldr     r1, =evolution_drawn
    str     r0, [r1]
    push    {r0}
    ldr     r0, =BAND_DEST_BATTLE   @ the evolution prompt borrows that window
    bl      OneScreen_BandTheme
    pop     {r0}
    bl      OneScreen_BattleMenu    @ redraw after the evolution frame work
    movs    r0, #0
    bl      OneScreen_SetSwap       @ keep the question and labels on the top LCD
    b       .Levolution_done

.Levolution_wipe:
    ldr     r4, =evolution_drawn
    ldr     r0, [r4]
    adds    r0, #1
    beq     .Levolution_done        @ already absent
    movs    r0, #0
    mvns    r0, r0
    str     r0, [r4]
    movs    r0, #LABEL_GEO_YN
    bl      OneScreen_BattleWipe
    bl      OneScreen_BattleMenu    @ exact window was validated above
    b       .Levolution_done

.Levolution_reset:
    ldr     r1, =evolution_drawn
    movs    r0, #0
    mvns    r0, r0
    str     r0, [r1]                @ app left: no write into its successor's VRAM
.Levolution_done:
    pop     {r4, pc}
    .align  2
    .pool

@ The patcher replaces sub_02075A7C's verified SysTask callback literal with
@ this wrapper. Running after the real task makes the mirrored highlight track
@ Up/Down/A/B in the same displayed frame and lets teardown wipe exactly once.
    .global OneScreen_EvolutionTask
    .thumb_func
OneScreen_EvolutionTask:
    push    {r3, r4, r5, lr}        @ keep SP 8-byte aligned across both calls
    movs    r4, r0                  @ SysTask *
    movs    r5, r1                  @ EvolutionTaskData *
    ldr     r3, =EVOLUTION_TASK_ORIG
    blx     r3
    bl      OneScreen_EvolutionPrompt
    movs    r0, r4                  @ preserve the callback ABI defensively
    movs    r1, r5
    pop     {r3, r4, r5, pc}
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ int OneScreen_OakExec(OverlayManager *manager, int *proc_state)
@ Oak's opening speech - see the OAK_ constants above for the state map.
@ Runs the app first, then routes, so ours is the last word for the frame.
@ ---------------------------------------------------------------------------
@ void OneScreen_OakSuppressFocus(OakSpeechData *data)
@
@ Oak's prompt messages finish with {YESNO 0}. The extended 0x0200 control only
@ draws the three-tile DS focus indicator; the actual custom menu and native
@ input controller are separate. Replace that id in the live expanded String
@ before the print-task queue can render it. Every pointer and String invariant
@ is checked first, and the scan is bounded by String.size.
    .thumb_func
OneScreen_OakSuppressFocus:
    push    {r3, r4, r5, r6, r7, lr} @ preserve 8-byte stack alignment for calls
    movs    r4, r0
    movs    r0, r4
    ldr     r1, =OAK_STRING_OFF
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     .Loak_focus_done

    ldr     r1, =OAK_PRINT_STATE_OFF
    ldr     r0, [r4, r1]
    cmp     r0, #1                  @ state 2 has already freed data->string
    bne     .Loak_focus_done
    ldr     r1, =OAK_STRING_OFF
    ldr     r4, [r4, r1]
    movs    r0, r4
    ldr     r1, =OAK_STRING_LAST_OFF
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     .Loak_focus_done

    ldrh    r0, [r4]
    ldr     r1, =OAK_STRING_MAX
    cmp     r0, r1
    bne     .Loak_focus_done
    ldrh    r5, [r4, #2]
    cmp     r5, r1
    bhs     .Loak_focus_done         @ size must leave room for EOS
    ldr     r0, [r4, #4]
    ldr     r1, =OAK_STRING_MAGIC
    cmp     r0, r1
    bne     .Loak_focus_done
    cmp     r5, #4
    blo     .Loak_focus_done

    movs    r6, r4
    adds    r6, #8                  @ String.data
    ldr     r7, =OAK_CONTROL_MARK
.Loak_focus_scan:
    ldrh    r0, [r6]
    cmp     r0, r7
    bne     .Loak_focus_next
    ldrh    r0, [r6, #2]
    ldr     r1, =OAK_FOCUS_CONTROL
    cmp     r0, r1
    bne     .Loak_focus_next
    ldrh    r0, [r6, #4]
    cmp     r0, #1                  @ one control-code argument
    bne     .Loak_focus_next
    ldrh    r0, [r6, #6]
    cmp     r0, #0                  @ focus target 0
    bne     .Loak_focus_next
    ldr     r0, =OAK_IGNORE_CONTROL
    strh    r0, [r6, #2]            @ generic parser skips it, drawing nothing
    b       .Loak_focus_done

.Loak_focus_next:
    adds    r6, #2
    subs    r5, #1
    cmp     r5, #4
    bhs     .Loak_focus_scan
.Loak_focus_done:
    pop     {r3, r4, r5, r6, r7, pc}
    .align  2
    .pool

@ void OneScreen_OakBlink(r0 = OakSpeechData *, r1 = 1 to hold it, 0 to let go)
@ See the note at OAK_BLINK_OFF. Every field is checked before one byte is
@ written; anything unexpected and the blink is left exactly as the game has it.
    .thumb_func
OneScreen_OakBlink:
    push    {r4, r5, r6, lr}
    movs    r6, r1
    ldr     r1, =OAK_BLINK_OFF
    ldr     r4, [r0, r1]
    movs    r0, r4
    movs    r1, #BLINK_SIZE
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     89f
    ldr     r0, [r4, #BLINK_APPLY_OFF]
    ldr     r1, =BLINK_APPLY_MAIN_BG
    cmp     r0, r1
    bne     89f                     @ not the top screen's hardware blink
    ldr     r0, [r4, #BLINK_PLTT_OFF]
    cmp     r0, #0
    bne     89f
    movs    r5, #BLINK_BYTES_OFF
    adds    r5, r4, r5              @ -> screen, palette, state, timer
    ldrb    r0, [r5]
    cmp     r0, #0
    bne     89f                     @ PM_LCD_TOP
    ldrb    r0, [r5, #1]
    cmp     r0, #BLINK_PALETTE_OAK
    bne     89f
    ldrb    r0, [r5, #3]
    cmp     r0, #32
    bhs     89f
    ldrb    r0, [r5, #2]            @ the state
    ldr     r1, =oak_blink_held
    cmp     r6, #0
    beq     88f
    cmp     r0, #BLINK_RUN          @ hold: only a running blink, so a RESTART
    bne     89f                     @ in progress is caught next frame instead
    movs    r0, #BLINK_PAUSE
    strb    r0, [r5, #2]
    movs    r0, #1
    str     r0, [r1]
    b       89f
88: ldr     r2, [r1]                @ let go: only one we are holding
    cmp     r2, #0
    beq     89f
    movs    r2, #0
    str     r2, [r1]
    cmp     r0, #BLINK_PAUSE
    bne     89f
    movs    r0, #BLINK_RESTART
    strb    r0, [r5, #2]
89: pop     {r4, r5, r6, pc}
    .align  2
    .pool

@ Put Oak's live edition backdrop colour into the otherwise-unused selected-band
@ entry of the dialog palette. The source is gold in HG and blue/silver in SS.
    .thumb_func
OneScreen_OakTheme:
    ldr     r0, =cfg_theme_band
    ldr     r1, [r0]
    cmp     r1, #0
    bne     84f
    ldr     r0, =OAK_THEME_SOURCE   @ no theme chosen: keep the old behaviour and
    ldrh    r1, [r0]                @ borrow the edition's own intro colour
84: ldr     r0, =BAND_DEST_OAK
    strh    r1, [r0]
    bx      lr
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ void OneScreen_BandTheme(r0 = palette-entry address)
@ Put the chosen band colour into one index-12 entry. Does nothing at all when
@ no theme is set, which leaves every prompt looking exactly as it did.
@ ---------------------------------------------------------------------------
    .global OneScreen_BandTheme
    .thumb_func
OneScreen_BandTheme:
    ldr     r1, =cfg_theme_band
    ldr     r1, [r1]
    cmp     r1, #0
    beq     83f
    strh    r1, [r0]
83: bx      lr
    .align  2
    .pool

@ void OneScreen_OakDraw(int code) - put a prompt in Oak's dialog box, or pass a
@ negative code to take it down. Active prompts are redrawn every frame after
@ Oak's own work so the custom labels remain authoritative in the shared window.
    .thumb_func
OneScreen_OakDraw:
    push    {r4, lr}
    ldr     r4, =oak_drawn
    ldr     r1, [r4]
    cmp     r0, #0
    bge     68f
    adds    r0, r1, #1
    beq     69f                     @ already down
    lsrs    r0, r1, #4              @ the set that is up - the gender box is ten
    movs    r2, #0                  @ tiles wide and the yes/no one three, so
    mvns    r2, r2                  @ wiping the wrong one leaves labels behind
    str     r2, [r4]
    bl      OneScreen_BattleWipe
    bl      OneScreen_BattleMenu
    b       69f
68: str     r0, [r4]                @ redraw every frame - Oak repaints this window
    bl      OneScreen_BattleMenu    @ as he builds each state, and a draw-once
                                    @ would simply be painted over
69: pop     {r4, pc}
    .align  2
    .pool

    .global OneScreen_OakExec
    .thumb_func
OneScreen_OakExec:
    push    {r3, r4, r5, lr}        @ normal callback entry; keep calls 8-aligned
    movs    r4, r1                  @ &proc_state, to survive the call
    ldr     r3, =cfg_oak_exec_orig
    ldr     r3, [r3]
    blx     r3
    movs    r5, r0                  @ keep its return value
    ldr     r4, [r4, #OAK_DATA_OFF] @ manager->data, read after so it exists
    cmp     r4, #0
    beq     61f
    ldr     r0, =oak_data
    str     r4, [r0]
    ldr     r0, [r4, #OAK_STATE_OFF]
    ldr     r1, =oak_state
    str     r0, [r1]

    @ Oak temporarily runs the naming overlay inside its own manager while its
    @ data->state remains 96. Only touch Oak's VRAM when its own VBlank argument
    @ proves the graphics have been restored.
    ldr     r1, =cfg_app_callback
    ldr     r1, [r1]
    ldr     r1, [r1, #4]
    cmp     r1, r4
    bne     61f

    @ The printer runs later in the main loop, so neutralize the focus-indicator
    @ control while the freshly-created String is still live. Tutorial messages
    @ use the same control but run in other states and remain completely native.
    cmp     r0, #OAK_FOCUS_GENDER
    beq     .Loak_suppress_focus
    cmp     r0, #OAK_FOCUS_CONFIRM_GENDER
    beq     .Loak_suppress_focus
    cmp     r0, #OAK_FOCUS_CONFIRM_NAME
    bne     .Loak_focus_checked
.Loak_suppress_focus:
    movs    r0, r4
    bl      OneScreen_OakSuppressFocus
.Loak_focus_checked:
    ldr     r0, [r4, #OAK_STATE_OFF]
    movs    r1, #1                  @ hold the blink still in the three
    cmp     r0, #OAK_GENDER_PICK    @ states that draw a band
    beq     78f
    cmp     r0, #OAK_CONFIRM_GENDER
    beq     78f
    cmp     r0, #OAK_CONFIRM_NAME
    beq     78f
    movs    r1, #0
78: movs    r0, r4
    bl      OneScreen_OakBlink
    ldr     r0, [r4, #OAK_STATE_OFF]

    @ The three prompts that take input get drawn on Oak's own screen instead of
    @ handing the screen over. Gender picks between two symbols, the two
    @ confirmations between yes and no.
    cmp     r0, #OAK_GENDER_PICK
    beq     64f
    cmp     r0, #OAK_CONFIRM_GENDER
    beq     65f
    cmp     r0, #OAK_CONFIRM_NAME
    beq     65f

    @ Lead-in states: pre-wipe the box the prompt is about to use.
    movs    r1, r0
    subs    r1, #OAK_GENDER_PRE_LO
    cmp     r1, #(OAK_GENDER_PRE_HI - OAK_GENDER_PRE_LO)
    bls     73f
    movs    r1, r0
    subs    r1, #OAK_CONFIRM_PRE_LO
    cmp     r1, #(OAK_CONFIRM_PRE_HI - OAK_CONFIRM_PRE_LO)
    bls     73f                     @ gender box: wider, and still showing
                                    @ GARCON/FILLE that must be cleared
    movs    r1, r0
    subs    r1, #OAK_NAME_PRE_LO
    cmp     r1, #(OAK_NAME_PRE_HI - OAK_NAME_PRE_LO)
    bls     74f

    @ Not a prompt: take down whatever of ours is still up, once. This used to
    @ hold an all-paper image over the corner the icon occupies on EVERY frame,
    @ on the belief that text never reaches those three tiles. Only messages
    @ with the {YESNO} icon keep clear of them; with the US text, five of Oak's
    @ lines run past x = 192 and lost their last letters once printing paused,
    @ and the tutorial's own icon was painted out too. The icon is handled by
    @ OneScreen_OakSuppressFocus in the states that would show it.
    push    {r0, r2}
    movs    r0, #0
    mvns    r0, r0                  @ -1: take our box down, if one is up
    bl      OneScreen_OakDraw
    pop     {r0, r2}

    @ Then route.
    @
    @ The gender flow no longer hands the screen over at all. It used to swap for
    @ the whole of 62..93 while the three prompts above kept Oak, which flipped
    @ the screen back and forth through the fades and setup states between them.
    @ Only the tutorial menu still swaps: three options of running French text
    @ will not fit beside the question the way two words do.
    cmp     r0, #OAK_TUTORIAL_HI
    bhi     60f
    movs    r0, #1
    b       62f
60: movs    r0, #0                  @ everything else keeps Oak's own screen
62: bl      OneScreen_SetSwap
61: movs    r0, r5
    pop     {r3, r4, r5, pc}

73: movs    r0, #LABEL_GEO_GENDER
    b       75f
74: movs    r0, #LABEL_GEO_OAK
75: bl      OneScreen_BattleWipe
    bl      OneScreen_OakDraw
    movs    r0, #0                  @ Oak keeps the screen through the lead-in
    bl      OneScreen_SetSwap
    movs    r0, r5
    pop     {r3, r4, r5, pc}

64: movs    r0, #(LABEL_GEO_GENDER << 4)
    b       66f
65: movs    r0, #(LABEL_GEO_OAK << 4)
66: push    {r0, r2}
    bl      OneScreen_OakTheme       @ palette is loaded by the real exec above
    ldr     r1, =OAK_NUMOPTS_OFF
    ldrb    r1, [r4, r1]
    cmp     r1, #2
    bne     67f                     @ not the two-option menu we expect
    ldr     r1, =OAK_CURSOR_OFF
    ldrb    r1, [r4, r1]
    cmp     r1, #1
    bhi     67f
    pop     {r0, r2}
    adds    r0, r0, r1
    bl      OneScreen_OakDraw
    movs    r0, #0                  @ Oak keeps the screen
    bl      OneScreen_SetSwap
    movs    r0, r5
    pop     {r3, r4, r5, pc}
67: pop     {r0, r2}
    movs    r0, #0
    bl      OneScreen_SetSwap
    movs    r0, r5
    pop     {r3, r4, r5, pc}
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ The field's running task. pret:
@
@     struct TaskManager { TaskManager *prev; TaskFunc func; u32 state;
@                          void *env; u32 unk10; void *unk14;
@                          FieldSystem *fieldSystem; ... };
@
@ reached as sFieldSysPtr -> fieldSystem->taskman (+0x10). The struct confirms
@ itself: +0x18 reads back the FieldSystem pointer we started from.
@
@ Measured across three savestates:
@     X menu open   taskman 0x022C01D8, func 0x0203BEF1  <- ARM9: Task_StartMenu
@     no menu       taskman NULL
@     after Dig     taskman 0x022C01D8, func 0x0224C3CD  <- an OVERLAY: a script
@
@ Two facts are used, and only these two:
@
@   * taskman == NULL means the field is idle, so a press of X will actually
@     open the menu. That is the game's own gate, which is why a ladder swallows
@     the press.
@   * an OVERLAY-resident task means a script owns the field. Scripts live in
@     overlays; the menu lives in ARM9.
@
@ What is NOT safe is the converse - reading "func is in ARM9" as "the menu is
@ open". That was tried and broke several things at once: the cave-name card and
@ the flight sequence are ARM9 field tasks too, so the menu was forced over both.
@ ARM9 means "not a script", nothing more.
@ ---------------------------------------------------------------------------
    .thumb_func
OneScreen_TaskMan:                  @ -> r0 = fieldSystem->taskman, or 0
    push    {r4, lr}
    bl      OneScreen_FieldSys
    cmp     r0, #0
    beq     55f
    ldr     r4, [r0, #FS_TASKMAN_OFF]
    movs    r0, r4
    movs    r1, #TASK_MANAGER_SIZE
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     55f
    movs    r0, r4
    pop     {r4, pc}
55: movs    r0, #0
    pop     {r4, pc}
    .align  2
    .pool

@ FieldSystem *OneScreen_FieldSys(void) -> *sFieldSysPtr if it points at a whole
@ FieldSystem in main RAM, else 0. Every walk that starts at the field starts
@ here, so a stale or half-built pointer fails closed in one place.
    .thumb_func
OneScreen_FieldSys:
    push    {r4, lr}
    ldr     r0, =cfg_field_sys
    ldr     r0, [r0]
    cmp     r0, #0
    beq     54f
    ldr     r4, [r0]                @ sFieldSysPtr
    movs    r0, r4
    ldr     r1, =FIELD_SYSTEM_SIZE
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     54f
    movs    r0, r4
    pop     {r4, pc}
54: movs    r0, #0
    pop     {r4, pc}
    .align  2
    .pool

@ void *OneScreen_BottomApp(r0 = FieldSystem *, r1 = app id)
@   -> that bottom-screen app's own data, if it is the one up and RUNNING, or 0.
@
@ FieldSystem.bottomScreenTask -> SysTask.data is the BottomScreenAppManager,
@ whose `app` is the app's own SysTask. bottomScreenTask only holds a manager
@ while bottomScreenType is 1 (the overworld and its special zones) or 3 (the
@ Union Room) - type 6 parks a photo viewer there - and the manager must point
@ back at this FieldSystem. Every link is range-checked. A switching manager
@ returns 0: its `app` may be the outgoing one.
    .thumb_func
OneScreen_BottomApp:
    push    {r4, r5, r6, lr}
    movs    r4, r0                  @ FieldSystem
    movs    r6, r1                  @ wanted app id
    ldr     r0, [r4, #FS_BOTTOM_TYPE_OFF]
    cmp     r0, #FS_BOTTOM_TYPE_FIELD
    beq     91f
    cmp     r0, #FS_BOTTOM_TYPE_UNION
    bne     99f
91: movs    r0, #FS_BOTTOM_TASK_OFF
    ldr     r5, [r4, r0]
    movs    r0, r5
    movs    r1, #(SYS_TASK_DATA_OFF + 4)
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     99f
    ldr     r5, [r5, #SYS_TASK_DATA_OFF]    @ -> BottomScreenAppManager
    movs    r0, r5
    movs    r1, #(BSAPP_LAST_OFF + 4)
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     99f
    ldr     r0, [r5, #BSAPP_FS_OFF]
    cmp     r0, r4
    bne     99f                     @ not this FieldSystem's manager
    ldrb    r0, [r5, #BSAPP_STATE_OFF]
    cmp     r0, #BSAPP_RUNNING
    bne     99f
    ldrb    r0, [r5, #BSAPP_ID_OFF]
    cmp     r0, r6
    bne     99f
    ldr     r5, [r5, #BSAPP_APP_OFF]        @ -> the app's SysTask
    movs    r0, r5
    movs    r1, #(SYS_TASK_DATA_OFF + 4)
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     99f
    ldr     r0, [r5, #SYS_TASK_DATA_OFF]
    pop     {r4, r5, r6, pc}
99: movs    r0, #0
    pop     {r4, r5, r6, pc}

@ TouchscreenMenuData *OneScreen_TouchMenu(r0 = FieldSystem *) -> it, or 0.
    .thumb_func
OneScreen_TouchMenu:
    push    {r4, r5, r6, lr}
    movs    r4, r0
    movs    r1, #BSAPP_TOUCH_MENU
    bl      OneScreen_BottomApp
    movs    r5, r0
    ldr     r1, =TOUCH_MENU_SIZE
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     98f
    ldr     r0, [r5, #TSM_FS_OFF]
    cmp     r0, r4
    bne     98f                     @ a stale menu from another field
    movs    r0, r5
    pop     {r4, r5, r6, pc}
98: movs    r0, #0
    pop     {r4, r5, r6, pc}
    .align  2
    .pool

@ StartMenuTaskData *OneScreen_StartMenuEnv(r0 = TaskManager *, or 0)
@   -> the start menu's own data if that task is Task_StartMenu, else 0.
    .thumb_func
OneScreen_StartMenuEnv:
    push    {r4, lr}
    cmp     r0, #0
    beq     53f
    ldr     r1, [r0, #TASK_FUNC_OFF]
    ldr     r2, =cfg_start_menu_task
    ldr     r2, [r2]
    cmp     r2, #0
    beq     53f                     @ the patcher could not vouch for the task
    cmp     r1, r2
    bne     53f                     @ something else owns the field right now
    ldr     r4, [r0, #TASK_ENV_OFF]
    movs    r0, r4
    ldr     r1, =START_MENU_DATA_SIZE
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     53f
    movs    r0, r4
    pop     {r4, pc}
53: movs    r0, #0
    pop     {r4, pc}
    .align  2
    .pool

@ int OneScreen_MenuGone(void) - 1 when the menu certainly is NOT on screen.
@
@ Deliberately one-sided. It answers "definitely gone", never "definitely open",
@ so it can only ever lower the latch. Two grounds, both sound:
@     no task at all   - the menu is a task, so no task means no menu
@     an overlay task  - a script owns the field; scripts live in overlays
@ ARM9 tasks return 0 here, i.e. "don't know", which is the honest answer and
@ the one v28 got wrong by reading them as "the menu is open".
    .thumb_func
OneScreen_MenuGone:
    push    {r4, lr}
    bl      OneScreen_TaskMan
    cmp     r0, #0
    beq     58f                     @ no task running: the menu cannot be up
    movs    r4, r0
    ldr     r0, [r4, #TASK_FUNC_OFF]
    ldr     r1, =cfg_field_callback
    ldr     r1, [r1]
    subs    r1, #1                  @ overlay 1's base = where overlay RAM starts
    cmp     r0, r1
    bhs     58f                     @ an overlay task: a script owns the field

    @ It is an ARM9 task, so we cannot tell from the address alone. But if it is
    @ Task_StartMenu we can ask the menu itself, and its exit states say it is
    @ leaving even though it is still on screen - the Dig / Escape Rope flash.
    movs    r0, r4
    bl      OneScreen_StartMenuEnv  @ the StartMenuTaskData, if it is the menu
    cmp     r0, #0
    beq     57f
    ldrh    r0, [r0, #STARTMENU_STATE_OFF]
    subs    r0, #STARTMENU_EXIT_LO
    cmp     r0, #(STARTMENU_EXIT_HI - STARTMENU_EXIT_LO)
    bhi     57f
58: movs    r0, #1
    pop     {r4, pc}
57: movs    r0, #0
    pop     {r4, pc}
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ void OneScreen_StartMenu(void)
@ Draw the overworld menu onto the world itself, on GF_BG_LYR_MAIN_3.
@
@ Every other box this patch draws borrows a message window the game has already
@ created, so the tiles are allocated, mapped and palettised and drawing is a
@ memcpy. The overworld has no such window - the world fills the screen - so this
@ is the one place that writes a TILEMAP as well as pixels.
@
@ It needs no display registers touched at all: MAIN_3 is priority 0 and the 3D
@ world is BG0 at priority 1 (initializeSimple3DVramManager, gf_3d_render.c:46),
@ so the panel is already in front. The strips sit at tile 0x84 - clear of the
@ 130 tiles the menu loads for itself at tile 0, and far below the map-name
@ window at 0x197, the only permanently allocated window on this layer.
@
@ They are re-uploaded on every open rather than once, because a script list menu
@ parks its own tiles at 0x3D..0xDD and eats into ours while the menu is shut.
@ 5 KB once per press of X is nothing, and it removes a whole class of bug.
@
@ Highlighting costs no pixels: the selected cell's tilemap entries are written
@ with a different palette number. That is how the game's own menu does it too -
@ ov27_0225B398 reloads a palette rather than moving a cursor sprite - and it is
@ what keeps this affordable, since one finished image per highlighted entry
@ would have been 32 KB against 11 KB of free ITCM.
@ ---------------------------------------------------------------------------
    .global OneScreen_StartMenu
    .thumb_func
OneScreen_StartMenu:
    push    {r4, r5, r6, r7, lr}
    sub     sp, #SM_FRAME_SP
    ldr     r7, =OneScreen_Labels
    ldr     r0, [r7]
    ldr     r1, =LABEL_MAGIC
    cmp     r0, r1
    bne     57f                     @ blob never filled in: draw nothing at all

    @ Every pointer checked, against the size of what it points at. A stale one
    @ reaching the IPC FIFO at 0x04100000 is what hung the ARM9 during the
    @ field-prompt attempt, and this walks the same kind of chain.
    bl      OneScreen_FieldSys
    movs    r6, r0                  @ -> FieldSystem
    beq     57f
    bl      OneScreen_TaskMan
    bl      OneScreen_StartMenuEnv
    movs    r4, r0                  @ -> StartMenuTaskData
    beq     57f
    ldrh    r0, [r4, #STARTMENU_STATE_OFF]
    subs    r0, #STARTMENU_SAVE_LO
    cmp     r0, #(STARTMENU_SAVE_HI - STARTMENU_SAVE_LO)
    bhi     36f
    @ Saving. Let the caller show the save box instead - and forget the upload,
    @ because that screen takes these tiles and this palette for itself. Without
    @ this the panel came back BLANK afterwards rather than garbled: the tilemap
    @ still pointed at tiles the save screen had since cleared. Every other entry
    @ on this menu is a separate application, so Poll's own app change already
    @ cleared the flag for those - which is why only SAUVER showed it.
    ldr     r0, =sm_drawn
    movs    r1, #0
    str     r1, [r0]
    b       57f
36:

    movs    r0, #SM_RECORD_OFF
    adds    r7, r7, r0              @ -> the panel's record

    @ Decide what every cell holds BEFORE drawing anything: a strip index per
    @ cell in sp[SM_SP_CELLS..+8] (0xFF = leave it empty) and the highlighted
    @ cell in sp[SM_SP_HI]. Two ways to get there.
    @
    @ The live one. The touch app on the bottom screen IS the menu - the start
    @ menu task only takes A and B - and its data says everything directly:
    @ which of the game's layouts it is (normal, Safari, Bug Contest, Pal Park,
    @ Union Room, Colosseum, Battle Tower), which icons it shows, and which slot
    @ is selected. Cells are its slots, so the panel matches the touch screen
    @ in every context, including the ones that used to swap.
    movs    r0, r6
    bl      OneScreen_TouchMenu
    cmp     r0, #0
    beq     50f                     @ not reachable this frame: fall back
    movs    r5, r0                  @ -> TouchscreenMenuData
    ldr     r1, =TSM_LAYOUT_OFF
    ldrb    r1, [r5, r1]
    lsrs    r1, r1, #TSM_LAYOUT_SHIFT
    movs    r2, #TSM_LAYOUT_MASK
    ands    r1, r2                  @ layout:4 (bits 1-4 of the word at +0x51C)
    cmp     r1, #SM_N_LAYOUTS
    bhs     57f
    @ The touch app computed its layout when it was created; the start menu
    @ computed its inhibit flags when X was pressed. They come from the same save
    @ flags, so they agree - check it anyway, and trust neither if they do not.
    lsls    r0, r1, #1
    ldr     r2, =sm_layout_class
    ldrh    r2, [r2, r0]
    ldr     r0, =SM_INHIBIT_OFF
    ldr     r0, [r4, r0]
    ldr     r3, =SM_NORMAL_MASK
    ands    r0, r3
    cmp     r0, r2
    bne     50f
    lsls    r1, r1, #3
    ldr     r0, =(OneScreen_Labels + SM_PLANS_OFF)
    adds    r0, r0, r1              @ -> this layout's eight cells
    ldrb    r1, [r0]
    cmp     r1, #SM_PLAN_UNDRAWABLE
    beq     57f                     @ a layout the patcher could not label
    ldr     r4, =TSM_ICONS_OFF
    adds    r4, r5, r4              @ -> icons[0].shown, stride 8
    movs    r2, #0
51: ldrb    r1, [r0, r2]
    cmp     r2, #TSM_N_ICONS
    bhs     52f                     @ past the last icon: nothing lives here
    lsls    r3, r2, #3
    ldrb    r3, [r4, r3]
    cmp     r3, #0
    bne     53f                     @ shown: keep its label
52: movs    r1, #0xFF
53: add     r3, sp, #SM_SP_CELLS
    strb    r1, [r3, r2]
    adds    r2, #1
    cmp     r2, #SM_CELLS
    blo     51b
    ldr     r0, [r5, #TSM_SELECTION_OFF]
    str     r0, [sp, #SM_SP_HI]     @ the selected slot is the selected cell
    b       56f

    @ The fallback, for the frames when the touch app is switching and its data
    @ cannot be vouched for: the normal layout from the start menu's own
    @ inhibit flags, as every build before v0.3 did. The game picks those flags
    @ with one function per variant (src/start_menu.c), and they separate
    @ cleanly:
    @
    @     Normal      always DISABLE_7 | DISABLE_RETIRE, never DISABLE_SAVE
    @     Safari      SAVE | 7                        0x090
    @     Bug Contest, Pal Park   BAG | SAVE | 7      0x094
    @     Union Room  RETIRE | 4 (SAVE)               0x110
    @     Colosseum, Battle Tower partner room        0x391 / 0x395
    @
    @ so normal is exactly (flags & (SAVE | 7 | RETIRE)) == (7 | RETIRE); anything
    @ else returns 0 here and the caller swaps for that frame.
50: ldr     r0, =SM_INHIBIT_OFF
    ldr     r0, [r4, r0]
    str     r0, [sp, #8]
    ldr     r1, =SM_NORMAL_MASK
    ands    r1, r0
    ldr     r2, =SM_NORMAL_BITS
    cmp     r1, r2
    bne     57f
    movs    r0, #FS_START_MENU_CURSOR_OFF      @ 0xD3 is out of reach of ldrb's immediate
    ldrb    r5, [r6, r0]            @ the live cursor
    movs    r0, #0xFF
    str     r0, [sp, #SM_SP_HI]
    movs    r0, #0
    str     r0, [sp, #12]           @ enabled cells seen so far
    movs    r6, #0                  @ cell index
    @ What belongs in this cell, and have you earned it? A cell you have not is
    @ left EMPTY rather than closing the list up, because that is what the touch
    @ menu does - the slots are fixed and missing entries leave gaps.
65: movs    r0, #SM_CELL_LABEL
    adds    r0, r7, r0
    ldrb    r0, [r0, r6]
    cmp     r0, #0xFF
    beq     67f                     @ nothing ever lives here
    movs    r1, #SM_CELL_BIT
    adds    r1, r7, r1
    ldrb    r1, [r1, r6]
    cmp     r1, #0xFF
    beq     66f                     @ never inhibited
    ldr     r2, [sp, #8]
    lsrs    r2, r2, r1
    movs    r1, #1
    ands    r2, r1
    cmp     r2, #0
    beq     66f
    movs    r0, #0xFF               @ not earned yet: leave the gap
    b       67f
    @ The cursor counts only the entries you have, so its index is this cell's
    @ position among the enabled ones - not the cell number.
66: ldr     r1, [sp, #12]
    adds    r2, r1, #1
    str     r2, [sp, #12]
    cmp     r1, r5
    bne     67f
    str     r6, [sp, #SM_SP_HI]
67: add     r1, sp, #SM_SP_CELLS
    strb    r0, [r1, r6]
    adds    r6, #1
    cmp     r6, #SM_CELLS
    blo     65b
    b       56f
57: b       79f                     @ trampoline: the exit is past a conditional
56:                                 @ branch's 256-byte reach from the checks
    ldr     r0, =sm_drawn
    ldr     r0, [r0]
    cmp     r0, #0
    bne     74f                     @ strips are already in VRAM
    ldr     r0, =OneScreen_Labels   @ the strips are packed; see OneScreen_Unpack
    ldr     r1, [r7, #SM_TILES_OFF]
    adds    r0, r0, r1
    ldr     r1, [r7, #SM_TILES_DEST]
    bl      OneScreen_Unpack
    ldr     r0, =OneScreen_Labels   @ both palettes at once; the builder keeps
    ldr     r1, [r7, #SM_PAL_OFF]   @ the highlighted one immediately after
    adds    r1, r0, r1
    ldr     r2, [r7, #SM_PAL_DEST]
    movs    r3, #SM_PAL_BYTES
73: ldmia   r1!, {r0}
    stmia   r2!, {r0}
    subs    r3, #4
    bne     73b
    ldr     r0, =sm_drawn
    movs    r1, #1
    str     r1, [r0]

74: ldrb    r0, [r7, #SM_CELL_W]    @ spilled: the inner loops need every register
    str     r0, [sp]
    ldrb    r0, [r7, #SM_CELL_H]
    str     r0, [sp, #4]

    @ The grey border, blitted whole - interior included, since the cells are
    @ drawn over it straight after. Two flat loops beat working out which cells
    @ are edges at runtime.
    ldr     r0, =OneScreen_Labels
    ldr     r1, [r7, #SM_FRAME_OFF]
    adds    r1, r0, r1
    ldr     r2, [r7, #SM_FRAME_BASE]
    movs    r3, #SM_FRAME_ROWS
    ldrb    r0, [r7, r3]
64: cmp     r0, #0
    beq     63f
    push    {r0, r2}
    movs    r3, #SM_FRAME_COLS
    ldrb    r3, [r7, r3]
62: ldrh    r0, [r1]
    strh    r0, [r2]
    adds    r1, #2
    adds    r2, #2
    subs    r3, #1
    bne     62b
    pop     {r0, r2}
    movs    r3, #SM_MAP_STRIDE
    adds    r2, r2, r3              @ down one tilemap row
    subs    r0, #1
    b       64b

63: movs    r6, #0                  @ cell index
75: ldrb    r0, [r7, #SM_N_CELLS]
    cmp     r6, r0
    bhs     59f
    ldrb    r3, [r7, #SM_BLANK]     @ assume empty
    add     r0, sp, #SM_SP_CELLS
    ldrb    r0, [r0, r6]
    cmp     r0, #0xFF
    beq     76f
    movs    r3, r0                  @ draw this label
76: movs    r4, #0
    ldr     r0, [sp, #SM_SP_HI]
    cmp     r0, r6
    bne     77f
    movs    r4, #1                  @ the highlighted cell

77: ldrb    r0, [r7, #SM_STRIP_TILES]
    muls    r3, r0
    ldrh    r0, [r7, #SM_BASE_TILE]
    adds    r3, r3, r0              @ first tile of that strip

    ldrb    r2, [r7, #SM_PAL_NORM]
    cmp     r4, #0
    beq     78f
    ldrb    r2, [r7, #SM_PAL_HI]
78: lsls    r2, r2, #12
    orrs    r3, r2                  @ a finished tilemap entry

    movs    r0, #0                  @ row within the cell
70: ldr     r2, [sp, #4]
    cmp     r0, r2
    bhs     68f
    ldr     r2, [sp, #4]
    muls    r2, r6
    adds    r2, r2, r0
    lsls    r2, r2, #2
    movs    r1, #SM_ROWS_OFF
    adds    r1, r7, r1
    ldr     r1, [r1, r2]            @ absolute tilemap address for this row
    ldr     r2, [sp]                @ cell_w, counted down
71: strh    r3, [r1]
    adds    r1, #2
    adds    r3, #1                  @ a strip's tiles are consecutive, so the
    subs    r2, #1                  @ entry simply walks forward across rows too
    bne     71b
    adds    r0, #1
    b       70b
68: adds    r6, #1
    b       75b

59: ldr     r0, =sm_shown               @ a panel is on screen from here until wiped
    movs    r1, #1
    str     r1, [r0]
    ldr     r0, [r7, #SM_FRAME_BASE]    @ into the game's shadow tilemap too, or
    movs    r1, #SM_FRAME_ROWS          @ its next commit erases the panel
    ldrb    r1, [r7, r1]
    movs    r2, #SM_FRAME_COLS
    ldrb    r2, [r7, r2]
    bl      OneScreen_MirrorRect
    movs    r0, #1                  @ drawn: the caller leaves the screen alone
    b       58f
79: movs    r0, #0                  @ not a layout we can reproduce
58: add     sp, #SM_FRAME_SP
    pop     {r4, r5, r6, r7, pc}
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ void OneScreen_Unpack(r0 = packed stream, r1 = destination)
@
@ LZ77 over 32-bit words, the format onescreen/labels.py::_pack writes. Words
@ rather than bytes because DS VRAM ignores byte writes: a byte decoder would
@ have to hold a pending half of each halfword and read its own output back to
@ resolve matches. In words every literal and every match is a `str`, and matches
@ read back with `ldr` - nothing subtle, which matters for the only routine here
@ that writes VRAM from a variable-length input.
@
@ Literals are assembled from four `ldrb`. The stream is byte-packed, so a
@ literal word is rarely 4-byte aligned, and an `ldr` on a misaligned address
@ rotates rather than faults - it would silently read the right bytes in the
@ wrong order.
@
@ Overlapping matches are deliberate: a displacement of one word copied forward
@ repeats that word, which is how runs of paper cost two bytes per 72.
@ ---------------------------------------------------------------------------
@ ---------------------------------------------------------------------------
@ void OneScreen_MirrorRect(r0 = tilemap address, r1 = rows, r2 = columns)
@
@ Copy a rectangle of MAIN_3's tilemap out of VRAM and into the game's own
@ shadow copy of it, so the next time the game commits that copy it repaints what
@ we drew instead of erasing it. See "Who owns the VRAM you just drew into".
@
@ Done as a copy after the fact rather than by writing both destinations inside
@ the drawing loops: those loops have no spare registers, and this leaves code
@ that has already been play-tested completely untouched.
@ ---------------------------------------------------------------------------
    .global OneScreen_MirrorRect
    .thumb_func
OneScreen_MirrorRect:
    push    {r4, r5, r6, r7, lr}
    movs    r4, r0
    movs    r5, r1
    movs    r6, r2
    bl      OneScreen_MapBuffer
    cmp     r0, #0
    beq     89f                     @ no buffer resolved: VRAM alone, as before
    ldr     r1, =SM_SCREEN_BASE
    subs    r0, r0, r1              @ buffer - screen base
87: cmp     r5, #0
    beq     89f
    movs    r1, r4
    adds    r2, r1, r0
    movs    r3, r6
86: ldrh    r7, [r1]
    strh    r7, [r2]
    adds    r1, #2
    adds    r2, #2
    subs    r3, #1
    bne     86b
    movs    r3, #SM_MAP_STRIDE
    adds    r4, r4, r3
    subs    r5, #1
    b       87b
89: pop     {r4, r5, r6, r7, pc}
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ void *OneScreen_MapBuffer(void) - the game's own MAIN_3 tilemap buffer, or 0.
@ Everything drawn on that layer is written here as well as to VRAM, so the
@ game's next commit repaints the panel instead of erasing it.
@ ---------------------------------------------------------------------------
    .global OneScreen_MapBuffer
    .thumb_func
OneScreen_MapBuffer:
    push    {r4, lr}
    ldr     r0, =cfg_field_sys
    ldr     r0, [r0]
    cmp     r0, #0
    beq     9f
    ldr     r0, [r0]                @ sFieldSysPtr
    cmp     r0, #0
    beq     9f
    ldr     r0, [r0, #BGCONFIG_OFF]
    movs    r1, #BG3_BUFFER_OFF
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     9f
    ldr     r0, =cfg_field_sys
    ldr     r0, [r0]
    ldr     r0, [r0]
    ldr     r0, [r0, #BGCONFIG_OFF]
    movs    r1, #BG3_BUFFER_OFF
    ldr     r4, [r0, r1]
    movs    r0, r4
    ldr     r1, =BG_BUFFER_SIZE
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     9f
    movs    r0, r4
    pop     {r4, pc}
9:  movs    r0, #0
    pop     {r4, pc}
    .align  2
    .pool

    .global OneScreen_Unpack
    .thumb_func
OneScreen_Unpack:
    push    {r4, r5, r6, r7, lr}
    ldr     r2, [r0]                @ words of output
    adds    r0, #4
10: cmp     r2, #0
    beq     19f
    ldrb    r4, [r0]                @ eight flags, MSB first
    adds    r0, #1
    movs    r5, #8
11: cmp     r5, #0
    beq     10b
    cmp     r2, #0
    beq     19f
    movs    r6, #0x80
    tst     r4, r6
    beq     13f

    ldrb    r6, [r0]                @ match: a two-byte token
    ldrb    r7, [r0, #1]
    adds    r0, #2
    lsls    r7, r7, #8
    orrs    r6, r7
    movs    r7, r6
    lsrs    r7, r7, #12
    adds    r7, #3                  @ length in words
    ldr     r3, =0xFFF
    ands    r3, r6
    adds    r3, #1
    lsls    r3, r3, #2              @ displacement in bytes
    movs    r6, r1
    subs    r6, r6, r3
15: cmp     r7, #0
    beq     17f
    ldr     r3, [r6]
    str     r3, [r1]
    adds    r6, #4
    adds    r1, #4
    subs    r7, #1
    subs    r2, #1
    beq     19f
    b       15b

13: ldrb    r6, [r0]                @ literal: assembled byte by byte
    ldrb    r3, [r0, #1]
    lsls    r3, r3, #8
    orrs    r6, r3
    ldrb    r3, [r0, #2]
    lsls    r3, r3, #16
    orrs    r6, r3
    ldrb    r3, [r0, #3]
    lsls    r3, r3, #24
    orrs    r6, r3
    str     r6, [r1]
    adds    r0, #4
    adds    r1, #4
    subs    r2, #1
17: lsls    r4, r4, #1
    subs    r5, #1
    b       11b
19: pop     {r4, r5, r6, r7, pc}
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ int OneScreen_ListMenu(void)
@ Draw a script list menu - the shop's, the PC's - onto the world. 1 if drawn.
@
@ Same surface and the same palette-swap highlight as the X menu, but the panel
@ is sized here rather than by the patcher: the entry count is not known until a
@ menu opens, so the frame is built a tile at a time from the nine border tiles.
@
@ Which menu this is is OneScreen_ListMatch's question. Anything unrecognised
@ returns 0 and the caller swaps the screen, exactly as before, so an NPC choice
@ this knows nothing about is never drawn with the wrong words.
@ ---------------------------------------------------------------------------
    .global OneScreen_ListMenu
    .thumb_func
OneScreen_ListMenu:
    push    {r4, r5, r6, r7, lr}
    sub     sp, #24                 @ six slots; must match the add at the exit
    ldr     r7, =OneScreen_Labels
    ldr     r0, [r7]
    ldr     r1, =LABEL_MAGIC
    cmp     r0, r1
    bne     29f
    ldr     r0, =LIST_RECORD_OFF
    adds    r7, r7, r0              @ -> the panel's record

    @ If no panel was up recently, forget the upload: whatever ran in between -
    @ the photo album, the mailbox - may have taken these tiles and this palette
    @ for itself. Cheaper and more reliable than trying to recognise every app
    @ that might, and it costs one re-upload on the way back in.
    ldr     r0, =list_hold
    ldr     r0, [r0]
    cmp     r0, #0
    bne     37f
    ldr     r0, =list_drawn
    movs    r1, #0
    str     r1, [r0]

37: ldr     r0, =list_ctrl
    ldr     r4, [r0]
    cmp     r4, #0
    beq     29f                     @ no validated controller this frame
    movs    r0, r4                  @ FieldMode3 only vouched for it as far as
    ldr     r1, =(LIST_CURSOR_OFF + 4)  @ its back-pointer; the cursor sits past that
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     29f
    ldr     r0, =LIST_CURSOR_OFF
    ldr     r0, [r4, r0]
    str     r0, [sp, #8]            @ the live cursor
    ldr     r0, [r4, #CHOICE_MENU_OFF]
    bl      OneScreen_ListMatch
    cmp     r0, #0
    beq     29f                     @ nothing we know: let the caller swap
    str     r0, [sp, #16]
    b       26f

29: movs    r0, #0
    b       28f

    @ Upload once per open: the frame tiles then this menu's strips.
    @ Upload when the menu CHANGES, not merely once. A single flag meant that
    @ stepping from the PC's list into its box menu kept the previous menu's
    @ strips in VRAM and drew the new tilemap over them - garbled words, and the
    @ old menu's at that.
26: ldr     r0, =list_drawn
    ldr     r0, [r0]
    ldr     r1, [sp, #16]
    cmp     r0, r1
    beq     27f
    @ A DIFFERENT menu. Clear the last one's rectangle first: panels are not all
    @ the same size, so stepping from the PC's box menu back to its list left the
    @ taller panel's edges on screen with the smaller one drawn inside them.
    bl      OneScreen_ListMenuWipe
    ldr     r0, =OneScreen_Labels   @ the border, its own packed stream
    ldr     r1, [r7, #LIST_TILES_OFF]
    adds    r0, r0, r1
    ldr     r1, [r7, #LIST_TILES_DEST]
    bl      OneScreen_Unpack
    ldr     r0, =OneScreen_Labels   @ then this menu's strips, after the border
    ldr     r1, [r7, #LIST_TILES_OFF]
    adds    r0, r0, r1
    ldr     r1, [sp, #16]
    ldrh    r1, [r1, #LIST_M_STRIP_OFF]
    adds    r0, r0, r1
    ldr     r1, [r7, #LIST_TILES_DEST]
    movs    r2, #LIST_FRAME_TILES
    lsls    r2, r2, #5
    adds    r1, r1, r2
    bl      OneScreen_Unpack
    ldr     r0, =OneScreen_Labels
    ldr     r1, [r7, #LIST_PAL_OFF]
    adds    r1, r0, r1
    ldr     r2, [r7, #LIST_PAL_DEST]
    movs    r3, #SM_PAL_BYTES
32: ldmia   r1!, {r0}
    stmia   r2!, {r0}
    subs    r3, #4
    bne     32b
    ldr     r0, =list_drawn
    ldr     r1, [sp, #16]
    str     r1, [r0]

27: ldr     r0, [sp, #16]
    ldr     r1, [sp, #8]
    ldr     r2, [r7, #LIST_SCREEN_BASE]
    bl      OneScreen_ListDraw
    bl      OneScreen_MapBuffer     @ and into the game's own copy, so its next
    cmp     r0, #0                  @ commit repaints the panel instead of
    beq     36f                     @ erasing it
    movs    r2, r0
    ldr     r0, [sp, #16]
    ldr     r1, [sp, #8]
    bl      OneScreen_ListDraw
36: movs    r0, #1
28: add     sp, #24
    pop     {r4, r5, r6, r7, pc}
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ void *OneScreen_ListMatch(r0 = ScriptMenu *) -> r0 = its panel record, or 0
@
@ The message ids are gone by the time a menu is up - ScriptMenu_AppendListItem
@ reads each into a string and keeps only the text - so a menu is recognised by
@ what survives, read live and compared against text rasterised at patch time:
@
@   * its entry COUNT (ScriptMenu.count)
@   * the CHARACTERS of its first entry, up to 16, and that entry's full length
@   * a 16-bit hash over every other entry the patcher could know in advance
@
@ The hash is what the first entry alone was missing. The Pokeathlon Dome's
@ marts are ACHETER / INFOS / QUITTER - three entries, the same first entry as
@ the shop - and used to be drawn as the shop. Entries the patcher cannot
@ predict (your own PC's row, which holds your name) are left out of the hash
@ by the record's skip mask rather than written out.
@
@ Also called from OneScreen_MenuExec, so the menus drawn here and the menus left
@ to the game's own top-screen list are decided by one test.
@ ---------------------------------------------------------------------------
    .thumb_func
OneScreen_ListMatch:
    push    {r4, r5, r6, r7, lr}
    sub     sp, #16
    movs    r5, r0                  @ menu
    ldr     r7, =OneScreen_Labels
    ldr     r0, [r7]
    ldr     r1, =LABEL_MAGIC
    cmp     r0, r1
    bne     39f
    ldr     r0, =LIST_RECORD_OFF
    adds    r7, r7, r0              @ -> the list header
    movs    r0, r5
    movs    r1, #(SCRIPT_MENU_COUNT_OFF + 1)
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     39f                     @ never dereference a stale menu pointer
    movs    r0, #SCRIPT_MENU_COUNT_OFF
    ldrb    r0, [r5, r0]
    cmp     r0, #0
    beq     39f
    cmp     r0, #LIST_MAX_ENTRIES
    bhi     39f                     @ longer than any menu we draw
    str     r0, [sp]                @ entry count
    ldr     r0, [r5, #SCRIPT_MENU_STRBUFS_OFF]  @ the first entry's String
    str     r0, [sp, #4]
    movs    r1, #STRING_DATA_OFF
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     39f
    ldr     r0, [sp, #4]
    ldrh    r1, [r0, #STRING_SIZE_OFF]
    lsls    r1, r1, #1
    adds    r1, #STRING_DATA_OFF
    bl      OneScreen_MainRamRange  @ and all of its characters
    cmp     r0, #0
    beq     39f

    movs    r6, #0                  @ record index
30: ldrb    r1, [r7, #LIST_N_MENUS]
    cmp     r6, r1
    bhs     39f
    movs    r4, #LIST_MENU_RECORD
    muls    r4, r6
    adds    r4, #LIST_MENUS_OFF
    adds    r4, r7, r4              @ -> this menu's record
    ldrb    r0, [r4, #LIST_M_ENTRIES]
    ldr     r1, [sp]
    cmp     r0, r1
    bne     38f
    ldr     r2, [sp, #4]
    ldrh    r3, [r2, #STRING_SIZE_OFF]
    ldrb    r0, [r4, #LIST_M_KEY_FULL]
    cmp     r3, r0
    bne     38f
    cmp     r0, #LIST_KEY_MAX       @ only the first 16 are stored; the full
    bls     31f                     @ length above has already been checked
    movs    r0, #LIST_KEY_MAX
31: str     r0, [sp, #8]
    movs    r3, #0
32: ldr     r0, [sp, #8]
    cmp     r3, r0
    bhs     33f
    lsls    r1, r3, #1
    adds    r0, r2, r1
    ldrh    r0, [r0, #STRING_DATA_OFF]
    adds    r1, #LIST_M_KEY
    ldrh    r1, [r4, r1]
    cmp     r0, r1
    bne     38f
    adds    r3, #1
    b       32b
33: movs    r0, r5                  @ the first entry matches; now the rest
    ldr     r1, [sp]
    movs    r2, #LIST_M_SKIP        @ past ldrb's immediate reach
    ldrb    r2, [r4, r2]
    bl      OneScreen_ListHash
    adds    r1, r0, #1
    beq     39f                     @ an entry pointer was bad: no match at all
    ldrh    r1, [r4, #LIST_M_HASH]
    cmp     r0, r1
    bne     38f
    movs    r0, r4                  @ matched
    b       37f
38: adds    r6, #1
    b       30b
39: movs    r0, #0
37: add     sp, #16
    pop     {r4, r5, r6, r7, pc}
    .align  2
    .pool

@ int OneScreen_ListHash(r0 = ScriptMenu *, r1 = count, r2 = skip mask)
@   -> r0 = the menu's hash, or -1 if any entry's String is not in main RAM.
@
@ h = h * 31 + code over each entry's characters, then once more with 0xFFFF
@ between entries, all kept to 16 bits. onescreen/labels.py::_menu_hash is the
@ same function, applied to the ROM's own messages.
    .thumb_func
OneScreen_ListHash:
    push    {r4, r5, r6, r7, lr}
    sub     sp, #8
    movs    r4, r0                  @ menu
    movs    r5, r1                  @ count
    movs    r6, r2                  @ skip mask
    movs    r7, #0                  @ h
    movs    r0, #0
    str     r0, [sp]                @ entry index
40: ldr     r0, [sp]
    cmp     r0, r5
    bhs     48f
    movs    r1, r6
    lsrs    r1, r0
    movs    r2, #1
    tst     r1, r2
    bne     46f                     @ left out on purpose
    lsls    r1, r0, #2
    adds    r1, r4, r1
    ldr     r0, [r1, #SCRIPT_MENU_STRBUFS_OFF]
    str     r0, [sp, #4]
    movs    r1, #STRING_DATA_OFF
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     49f
    ldr     r0, [sp, #4]
    ldrh    r1, [r0, #STRING_SIZE_OFF]
    lsls    r1, r1, #1
    adds    r1, #STRING_DATA_OFF
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     49f
    ldr     r2, [sp, #4]
    ldrh    r3, [r2, #STRING_SIZE_OFF]
    adds    r2, #STRING_DATA_OFF
42: cmp     r3, #0
    beq     45f
    ldrh    r0, [r2]
    adds    r2, #2
    lsls    r1, r7, #5
    subs    r1, r1, r7              @ h * 31
    adds    r7, r1, r0
    lsls    r7, r7, #16
    lsrs    r7, r7, #16
    subs    r3, #1
    b       42b
45: lsls    r1, r7, #5              @ the separator
    subs    r1, r1, r7
    ldr     r0, =0xFFFF
    adds    r7, r1, r0
    lsls    r7, r7, #16
    lsrs    r7, r7, #16
46: ldr     r0, [sp]
    adds    r0, #1
    str     r0, [sp]
    b       40b
48: movs    r0, r7
    b       47f
49: movs    r0, #0
    mvns    r0, r0
47: add     sp, #8
    pop     {r4, r5, r6, r7, pc}
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ BOOL OneScreen_MenuExec(ScriptContext *ctx)
@
@ Installed in the script command table in place of ScrCmd_MenuExec (command
@ 752), the command that shows a script-built list on the TOUCH screen. HGSS
@ also has the top-screen list it inherited from Diamond and Pearl -
@ ScriptMenu_ShowList, what ScrCmd_ScriptListMenuExec (command 71) uses - and
@ both read the same ScriptMenu, built by the same MenuInit / MenuItemAdd
@ commands. So a list this patch cannot draw itself is handed to the game's own
@ top-screen renderer instead of taking the screen: the window, the cursor,
@ scrolling past eight entries and the help text are all the game's.
@
@ Recognised menus (the shop, the PC) go to the original command, so they keep
@ the themed panel OneScreen_ListMenu draws. So does anything this cannot vouch
@ for: the choice app not up and idle, a menu pointer it cannot follow, an
@ entry holding a line break or a control code, which the touch list lays out
@ in two lines and the top-screen list cannot, or a list that would land on a
@ window the script already has on the top screen (OneScreen_ListRoom).
@
@ The two paths differ in exactly one result: the touch list's B picks the last
@ entry, ScriptMenu_ListTask's B writes 0xFFFE. Scripts are written for the
@ touch list - the apricorn juice, the rankings and the fossil menus all treat
@ "not one of the values" as the last choice - so OneScreen_WaitList maps 0xFFFE
@ to the last entry's value before the script sees it.
@ ---------------------------------------------------------------------------
    .global OneScreen_MenuExec
    .thumb_func
OneScreen_MenuExec:
    push    {r4, r5, r6, r7, lr}
    sub     sp, #8                  @ [sp] tiles across, [sp, #4] tile rows
    movs    r7, r0                  @ ScriptContext
    ldr     r0, =cfg_show_list
    ldr     r0, [r0]
    cmp     r0, #0
    beq     59f
    ldr     r0, =cfg_setup_native
    ldr     r0, [r0]
    cmp     r0, #0
    beq     59f
    bl      OneScreen_FieldSys
    movs    r6, r0                  @ FieldSystem
    beq     59f
    movs    r1, #BSAPP_CHOICE_MENU
    bl      OneScreen_BottomApp
    movs    r5, r0                  @ TouchscreenChoiceMenuData
    ldr     r1, =(CHOICE_SELECTION_OFF + 4)
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     70f
    ldr     r0, [r5, #CHOICE_FS_OFF]
    cmp     r0, r6
    bne     70f
    ldr     r0, [r5, #CHOICE_STATE_OFF]
    cmp     r0, #CHOICE_IDLE
    bne     70f
    ldr     r4, [r5, #CHOICE_MENU_OFF]  @ the ScriptMenu MenuInit built
    movs    r0, r4
    ldr     r1, =SCRIPT_MENU_SIZE
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     70f
    movs    r0, #SCRIPT_MENU_COUNT_OFF
    ldrb    r5, [r4, r0]            @ count
    cmp     r5, #0
    beq     70f
    cmp     r5, #SCRIPT_MENU_MAX
    bhi     70f
    movs    r0, r4
    bl      OneScreen_ListMatch
    cmp     r0, #0
    bne     70f                     @ ours: the themed panel draws it
    movs    r0, r4
    movs    r1, r5
    bl      OneScreen_ListPlain
    cmp     r0, #0
    beq     70f                     @ two-line or formatted entries
    ldr     r0, =SCRIPT_MENU_RET_OFF
    ldr     r6, [r4, r0]            @ ret_p, a u16 in the script's vars
    ldr     r0, =0x02000000
    cmp     r6, r0
    blo     70f
    ldr     r0, =0x023FFFFE
    cmp     r6, r0
    bhs     70f
    lsls    r0, r6, #31
    bne     70f                     @ not halfword-aligned
    b       58f
59: b       70f                     @ in reach of the guards at the top
58:

    @ Size the window the way ScriptMenu_OpenListWindow will: the widest entry
    @ in tiles across, and two tile rows per entry up to a page of eight.
    ldr     r3, =cfg_list_items_width
    ldr     r3, [r3]
    cmp     r3, #0
    beq     70f                     @ cannot size it: cannot check its room
    movs    r0, r4
    blx     r3                      @ widest entry + 12, in pixels
    adds    r0, #7
    lsrs    r0, r0, #3
    str     r0, [sp]                @ tiles across
    movs    r1, r5
    cmp     r1, #8
    bls     68f
    movs    r1, #8
68: lsls    r1, r1, #1
    str     r1, [sp, #4]            @ tile rows

    @ Keep the window on the screen. The script's x and y were written for the
    @ touch list, which ignores them; they are always clear of the dialogue box,
    @ but a long translation in a right-hand menu could run past column 31.
    movs    r1, #SCRIPT_MENU_FLAGS_OFF
    ldrb    r1, [r4, r1]
    movs    r2, #ANCHOR_RIGHT_BIT
    tst     r1, r2
    bne     69f                     @ anchored: ShowList places it itself
    movs    r1, #SCRIPT_MENU_X_OFF
    ldrb    r2, [r4, r1]
    adds    r3, r2, r0
    cmp     r3, #LIST_RIGHT_EDGE
    bls     69f
    movs    r2, #LIST_RIGHT_EDGE
    subs    r2, r2, r0
    cmp     r2, #1
    bge     71f
    movs    r2, #1
71: strb    r2, [r4, r1]

    @ A recognised panel may still be up from the menu before this one. It is
    @ over - the script has moved on to this one - and it sits in the game's copy
    @ of the layer, so it goes before the room check below would trip on it.
69: bl      OneScreen_ListMenuWipe
    ldr     r0, =list_hold
    movs    r1, #0
    str     r1, [r0]
    ldr     r0, =list_drawn
    str     r1, [r0]

    @ Is there room? A script may have its own window up on this layer - Mom's
    @ savings box is 16x8 tiles at (1, 1), drawn from tile 1, and her menu then
    @ asks for a list at (1, 1) too, whose window takes tiles from 0x3D. On the
    @ touch screen that never mattered. If anything already on MAIN_3 sits where
    @ the list would, or uses the tiles it would take, keep the touch list.
    movs    r1, #SCRIPT_MENU_X_OFF
    ldrb    r0, [r4, r1]            @ x
    adds    r1, #1
    ldrb    r1, [r4, r1]            @ y
    movs    r2, #SCRIPT_MENU_FLAGS_OFF
    ldrb    r2, [r4, r2]
    movs    r3, #ANCHOR_RIGHT_BIT
    tst     r2, r3
    beq     67f
    ldr     r3, [sp]
    subs    r0, r0, r3              @ ShowList moves an anchored list left...
67: movs    r3, #ANCHOR_BOTTOM_BIT
    tst     r2, r3
    beq     66f
    ldr     r3, [sp, #4]
    subs    r1, r1, r3              @ ...or up, by its own size
66: ldr     r2, [sp]
    ldr     r3, [sp, #4]
    bl      OneScreen_ListRoom
    cmp     r0, #0
    beq     70f                     @ something is in the way: the touch list

    @ From here on the list is the game's.
    ldr     r0, =wl_ret
    str     r6, [r0]
    ldr     r0, =LIST_NONE
    strh    r0, [r6]
    subs    r0, r5, #1
    lsls    r0, r0, #3
    ldr     r1, =(SCRIPT_MENU_ITEMS_OFF + 4)
    adds    r0, r0, r1
    ldr     r0, [r4, r0]            @ items[count - 1].value
    ldr     r1, =wl_last
    str     r0, [r1]

    movs    r0, r4
    ldr     r3, =cfg_show_list
    ldr     r3, [r3]
    blx     r3                      @ ScriptMenu_ShowList(menu)
    movs    r0, r7
    ldr     r1, =OneScreen_WaitList
    ldr     r3, =cfg_setup_native
    ldr     r3, [r3]
    blx     r3                      @ SetupNativeScript(ctx, OneScreen_WaitList)
    movs    r0, #1
    add     sp, #8
    pop     {r4, r5, r6, r7, pc}

70: movs    r0, r7                  @ anything else: exactly as before
    ldr     r3, =cfg_menu_exec_orig
    ldr     r3, [r3]
    blx     r3
    add     sp, #8
    pop     {r4, r5, r6, r7, pc}
    .align  2
    .pool

@ int OneScreen_ListRoom(r0 = x, r1 = y, r2 = tiles across, r3 = tile rows)
@   -> 1 if a ScriptMenu list window would land on an empty part of MAIN_3.
@
@ Reads the layer's own tilemap buffer, which is what the game commits to the
@ screen, so it sees every window drawn there: any entry inside the list's
@ rectangle (plus the one-tile frame around it), or any entry anywhere using a
@ character tile the list's window would be given (0x3D onwards), means no.
@ x and y are signed: an anchored list can be moved off the left or top edge.
    .thumb_func
OneScreen_ListRoom:
    push    {r4, r5, r6, r7, lr}
    sub     sp, #16
    subs    r0, #1
    str     r0, [sp]                @ left edge of the frame
    adds    r0, r0, r2
    adds    r0, #1
    str     r0, [sp, #4]            @ right edge of the frame, inclusive
    subs    r1, #1
    str     r1, [sp, #8]            @ top edge
    adds    r1, r1, r3
    adds    r1, #1
    str     r1, [sp, #12]           @ bottom edge, inclusive
    muls    r2, r3                  @ the window's character tiles
    movs    r6, #LIST_WINDOW_TILE
    adds    r7, r6, r2              @ [r6, r7) is what it will take
    bl      OneScreen_MapBuffer
    cmp     r0, #0
    beq     65f                     @ cannot see the layer: assume no room
    movs    r4, r0
    movs    r5, #0                  @ entry index, row-major, 32 a row
60: ldrh    r0, [r4]
    adds    r4, #2
    cmp     r0, #0
    beq     63f                     @ an empty cell
    lsls    r1, r0, #22
    lsrs    r1, r1, #22             @ its character tile
    cmp     r1, r6
    blo     61f
    cmp     r1, r7
    blo     65f                     @ one of the tiles the list would take
61: movs    r1, #31
    ands    r1, r5                  @ column
    ldr     r2, [sp]
    cmp     r1, r2
    blt     63f
    ldr     r2, [sp, #4]
    cmp     r1, r2
    bgt     63f
    lsrs    r1, r5, #5              @ row
    ldr     r2, [sp, #8]
    cmp     r1, r2
    blt     63f
    ldr     r2, [sp, #12]
    cmp     r1, r2
    ble     65f                     @ inside where the list would sit
63: adds    r5, #1
    ldr     r0, =LIST_SCAN_CELLS
    cmp     r5, r0
    blo     60b
    movs    r0, #1
    b       64f
65: movs    r0, #0
64: add     sp, #16
    pop     {r4, r5, r6, r7, pc}
    .align  2
    .pool

@ BOOL OneScreen_WaitList(ScriptContext *) - the native-script wait for a list
@ OneScreen_MenuExec opened: FALSE until ScriptMenu_ListTask writes a result,
@ with B turned into the last entry's value, which is what the touch list gives.
    .global OneScreen_WaitList
    .thumb_func
OneScreen_WaitList:
    ldr     r1, =wl_ret
    ldr     r1, [r1]
    ldrh    r0, [r1]
    ldr     r2, =LIST_NONE
    cmp     r0, r2
    beq     73f
    ldr     r2, =LIST_CANCEL
    cmp     r0, r2
    bne     74f
    ldr     r0, =wl_last
    ldr     r0, [r0]
    strh    r0, [r1]
74: movs    r0, #1
    bx      lr
73: movs    r0, #0
    bx      lr
    .align  2
    .pool

@ int OneScreen_ListPlain(r0 = ScriptMenu *, r1 = count) -> 1 if every entry
@ is plain text: readable, and with no code at or above 0xE000 (a line break or
@ a formatting control), which the top-screen list would draw wrong.
    .thumb_func
OneScreen_ListPlain:
    push    {r4, r5, r6, lr}
    movs    r4, r0
    movs    r5, r1
    movs    r6, #0
75: cmp     r6, r5
    bhs     78f
    lsls    r0, r6, #2
    adds    r0, r4, r0
    ldr     r0, [r0, #SCRIPT_MENU_STRBUFS_OFF]
    push    {r0}
    movs    r1, #STRING_DATA_OFF
    bl      OneScreen_MainRamRange
    pop     {r2}
    cmp     r0, #0
    beq     79f
    ldrh    r3, [r2, #STRING_SIZE_OFF]
    push    {r2, r3}
    movs    r0, r2
    lsls    r1, r3, #1
    adds    r1, #STRING_DATA_OFF
    bl      OneScreen_MainRamRange
    pop     {r2, r3}
    cmp     r0, #0
    beq     79f
    adds    r2, #STRING_DATA_OFF
    ldr     r1, =0xE000
76: cmp     r3, #0
    beq     77f
    ldrh    r0, [r2]
    cmp     r0, r1
    bhs     79f
    adds    r2, #2
    subs    r3, #1
    b       76b
77: adds    r6, #1
    b       75b
78: movs    r0, #1
    pop     {r4, r5, r6, pc}
79: movs    r0, #0
    pop     {r4, r5, r6, pc}
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ void OneScreen_ListDraw(r0 = matched menu record, r1 = cursor)
@ Build the panel: the border a tile at a time, then one strip per entry with
@ the cursor's row pointed at the highlight palette.
@ ---------------------------------------------------------------------------
    .thumb_func
OneScreen_ListDraw:
    push    {r4, r5, r6, r7, lr}
    sub     sp, #40
    str     r0, [sp]
    str     r1, [sp, #4]
    movs    r6, r2                  @ destination base
    ldr     r7, =OneScreen_Labels
    ldr     r2, =LIST_RECORD_OFF
    adds    r7, r7, r2
    ldrb    r2, [r0, #LIST_M_CELL_W]
    str     r2, [sp, #8]
    ldrb    r2, [r0, #LIST_M_CELL_H]
    str     r2, [sp, #12]
    ldrb    r2, [r0, #LIST_M_ENTRIES]
    str     r2, [sp, #32]
    ldrb    r2, [r0, #LIST_M_ROWS]  @ the PC box menu is a grid, not a column, so
    ldr     r3, [sp, #12]           @ the panel is sized by rows and columns and
    muls    r2, r3                  @ not by the entry count
    adds    r2, #2                  @ frame_rows
    str     r2, [sp, #16]
    ldrb    r2, [r0, #LIST_M_COLS]
    ldr     r3, [sp, #8]
    muls    r2, r3
    adds    r2, #2                  @ frame_cols
    str     r2, [sp, #20]
    movs    r3, #32
    subs    r3, r3, r2              @ flush to the right edge
    str     r3, [sp, #24]
    str     r6, [sp, #28]           @ where to paint: VRAM, or the game's buffer

    @ Remember the rectangle so the wipe can clear it without the record.
    ldr     r0, [sp, #16]
    lsls    r0, r0, #16
    ldr     r1, [sp, #20]
    lsls    r1, r1, #8
    orrs    r0, r1
    ldr     r1, [sp, #24]
    orrs    r0, r1
    ldr     r1, =list_rect
    str     r0, [r1]

    movs    r4, #0                  @ frame row
40: ldr     r0, [sp, #16]
    cmp     r4, r0
    bhs     45f
    cmp     r4, #0
    bne     41f
    movs    r5, #0
    b       43f
41: subs    r0, #1
    cmp     r4, r0
    bne     42f
    movs    r5, #2
    b       43f
42: movs    r5, #1
43: movs    r6, #0                  @ frame column
44: ldr     r0, [sp, #20]
    cmp     r6, r0
    bhs     46f
    cmp     r6, #0
    bne     47f
    movs    r0, #0
    b       49f
47: ldr     r0, [sp, #20]
    subs    r0, #1
    cmp     r6, r0
    bne     48f
    movs    r0, #2
    b       49f
48: movs    r0, #1
49: movs    r1, #3
    muls    r1, r5
    adds    r0, r0, r1
    ldrh    r1, [r7, #LIST_BASE_TILE]
    adds    r0, r0, r1
    ldrb    r1, [r7, #LIST_PAL_NORM]
    lsls    r1, r1, #12
    orrs    r0, r1
    lsls    r1, r4, #5
    ldr     r2, [sp, #24]
    adds    r1, r1, r2
    adds    r1, r1, r6
    lsls    r1, r1, #1
    ldr     r2, [sp, #28]
    adds    r1, r2, r1
    strh    r0, [r1]
    adds    r6, #1
    b       44b
46: adds    r4, #1
    b       40b

45: movs    r4, #0                  @ entry
50: ldr     r0, [sp, #32]
    cmp     r4, r0
    bhs     55f
    ldr     r0, [sp]
    ldrh    r0, [r0, #LIST_M_STRIP_TILES]
    muls    r0, r4
    ldrh    r1, [r7, #LIST_BASE_TILE]
    adds    r0, r0, r1
    adds    r0, #LIST_FRAME_TILES   @ the strips sit after the border tiles
    ldrb    r1, [r7, #LIST_PAL_NORM]
    ldr     r2, [sp, #4]
    cmp     r4, r2
    bne     51f
    ldrb    r1, [r7, #LIST_PAL_HI]
51: lsls    r1, r1, #12
    orrs    r0, r1
    movs    r5, #0                  @ row within the cell
52: ldr     r1, [sp, #12]
    cmp     r5, r1
    bhs     54f
    ldr     r1, [sp]                @ this entry's (row << 4) | column
    movs    r2, #LIST_M_POS
    adds    r1, r1, r2
    ldrb    r1, [r1, r4]
    movs    r2, r1
    lsrs    r2, r2, #4              @ row
    ldr     r6, [sp, #12]
    muls    r2, r6
    adds    r2, r2, r5
    adds    r2, #1                  @ past the border's top row
    lsls    r2, r2, #5
    movs    r6, #15
    ands    r1, r6                  @ column
    ldr     r6, [sp, #8]
    muls    r1, r6
    adds    r2, r2, r1
    ldr     r1, [sp, #24]
    adds    r2, r2, r1
    adds    r2, #1                  @ and its left column
    lsls    r2, r2, #1
    ldr     r1, [sp, #28]
    adds    r1, r1, r2
    ldr     r2, [sp, #8]            @ cell_w, counted down
53: strh    r0, [r1]
    adds    r1, #2
    adds    r0, #1
    subs    r2, #1
    bne     53b
    adds    r5, #1
    b       52b
54: adds    r4, #1
    b       50b

55: add     sp, #40
    pop     {r4, r5, r6, r7, pc}
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ void OneScreen_ListClear(void)
@ Blank the rectangle the panel last occupied, from list_rect.
@ ---------------------------------------------------------------------------
    .thumb_func
OneScreen_ListClear:
    push    {r4, r5, r6, r7, lr}
    movs    r7, r0                  @ destination base
    ldr     r0, =list_rect
    ldr     r0, [r0]
    cmp     r0, #0
    beq     18f
    movs    r1, #0xFF
    movs    r4, r0
    ands    r4, r1                  @ x
    lsrs    r5, r0, #8
    ands    r5, r1                  @ cols
    lsrs    r6, r0, #16
    ands    r6, r1                  @ rows
    movs    r0, #0                  @ row
17: cmp     r0, r6
    bhs     18f
    lsls    r1, r0, #5
    adds    r1, r1, r4
    lsls    r1, r1, #1
    adds    r1, r7, r1
    movs    r2, r5
    movs    r3, #0
16: strh    r3, [r1]
    adds    r1, #2
    subs    r2, #1
    bne     16b
    adds    r0, #1
    b       17b
18: pop     {r4, r5, r6, r7, pc}
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ void OneScreen_ListMenuWipe(void)
@ Clear the panel and forget the upload, so the next menu re-sends its strips.
@ ---------------------------------------------------------------------------
    .global OneScreen_ListMenuWipe
    .thumb_func
OneScreen_ListMenuWipe:
    push    {r4, lr}
    ldr     r0, =list_drawn
    ldr     r1, [r0]
    cmp     r1, #0
    beq     19f
    movs    r1, #0
    str     r1, [r0]
    ldr     r0, =OneScreen_Labels
    ldr     r1, =LIST_RECORD_OFF
    adds    r0, r0, r1
    ldr     r0, [r0, #LIST_SCREEN_BASE]
    bl      OneScreen_ListClear
    bl      OneScreen_MapBuffer     @ clear the game's copy too, or its next
    cmp     r0, #0                  @ commit puts the panel back
    beq     19f
    bl      OneScreen_ListClear
19: pop     {r4, pc}
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ void OneScreen_StartMenuWipe(void)
@ Take the panel down and forget the upload, so the next open re-sends the
@ strips. The game clears this whole layer when the menu tears down properly
@ (sub_0203C38C), but not on every path that ends it - Dig and Escape Rope jump
@ straight to an exit task - so the panel clears itself rather than trusting it.
@ ---------------------------------------------------------------------------
    .global OneScreen_StartMenuWipe
    .thumb_func
OneScreen_StartMenuWipe:
    push    {r4, r5, r6, r7, lr}
    ldr     r7, =OneScreen_Labels
    ldr     r0, [r7]
    ldr     r1, =LABEL_MAGIC
    cmp     r0, r1
    bne     67f
    ldr     r0, =sm_shown
    ldr     r1, [r0]
    cmp     r1, #0
    beq     67f                     @ nothing of ours is on screen
    movs    r1, #0
    str     r1, [r0]
    ldr     r0, =sm_drawn           @ and re-upload next time: whatever ran in
    str     r1, [r0]                @ between may have taken these tiles
    movs    r0, #SM_RECORD_OFF
    adds    r7, r7, r0
    ldr     r1, [r7, #SM_FRAME_BASE]    @ the border's rect covers the cells too
    movs    r0, #SM_FRAME_ROWS
    ldrb    r4, [r7, r0]
66: cmp     r4, #0
    beq     68f
    movs    r0, #SM_FRAME_COLS
    ldrb    r2, [r7, r0]
    movs    r5, r1                  @ keep the row start
    movs    r3, #0
65: strh    r3, [r1]
    adds    r1, #2
    subs    r2, #1
    bne     65b
    movs    r1, r5
    movs    r3, #SM_MAP_STRIDE
    adds    r1, r1, r3
    subs    r4, #1
    b       66b
68: ldr     r0, [r7, #SM_FRAME_BASE]    @ clear it from the shadow copy as well,
    movs    r1, #SM_FRAME_ROWS          @ or the next commit puts the panel back
    ldrb    r1, [r7, r1]
    movs    r2, #SM_FRAME_COLS
    ldrb    r2, [r7, r2]
    bl      OneScreen_MirrorRect
67: pop     {r4, r5, r6, r7, pc}
    .align  2
    .pool

@ int OneScreen_MainRamRange(void *ptr, u32 last_word_off)
@ Accept only aligned pointers whose last word is still in the DS's 4 MB main
@ RAM. Every link in the field-controller chain passes through here before it is
@ read: a non-null stale pointer once reached the IPC FIFO and hung ARM9.
    .thumb_func
OneScreen_MainRamRange:
    movs    r2, #3
    tst     r0, r2
    bne     40f
    ldr     r2, =0x02000000
    cmp     r0, r2
    blo     40f
    ldr     r2, =0x02400000
    cmp     r0, r2
    bhs     40f
    adds    r1, r0, r1
    bcs     40f                     @ reject 32-bit wraparound as well
    cmp     r1, r2
    bhs     40f
    movs    r0, #1
    bx      lr
40: movs    r0, #0
    bx      lr
    .align  2
    .pool

@ Classify the stable overlay-27 mode-3 controller behind FieldSystem.
@   0 invalid (fail closed to the native lower screen)
@   1 transition/setup/idle/binary teardown (keep the world)
@   2 binary prompt, Yes selected
@   3 binary prompt, No selected
@   4 non-mirrored native states 7..11 (lists at 7..10; cleanup at 11)
    .thumb_func
OneScreen_FieldMode3:
    push    {r3, r4, r5, r6, r7, lr}
    movs    r4, r0                  @ FieldSystem
    ldr     r1, =list_ctrl          @ forget last frame's controller; it is only
    movs    r0, #0                  @ republished below once revalidated
    str     r0, [r1]
    movs    r0, r4

    movs    r1, #FS_BOTTOM_TASK_OFF
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     49f
    movs    r0, #FS_BOTTOM_TASK_OFF
    ldr     r5, [r4, r0]
    movs    r0, r5
    movs    r1, #SYS_TASK_DATA_OFF
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     49f
    ldr     r6, [r5, #SYS_TASK_DATA_OFF]
    movs    r0, r6
    movs    r1, #BSAPP_LAST_OFF
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     49f
    ldr     r0, [r6, #BSAPP_FS_OFF]
    cmp     r0, r4
    bne     49f                     @ not this FieldSystem's manager

    ldrb    r0, [r6, #BSAPP_STATE_OFF]
    cmp     r0, #BSAPP_RUNNING
    beq     43f

    @ While the outer manager changes modes, its child can still be the outgoing
    @ task. Validate the transition but deliberately do not follow that pointer.
    cmp     r0, #BSAPP_SWITCH_REQUESTED
    blo     49f
    cmp     r0, #BSAPP_FADE_IN
    bhi     49f
    ldrb    r0, [r6, #BSAPP_NEXT_ID_OFF]
    cmp     r0, #BSAPP_CHOICE_MENU
    bne     49f
    movs    r0, #1
    b       48f

43: ldrb    r0, [r6, #BSAPP_ID_OFF]
    cmp     r0, #BSAPP_CHOICE_MENU
    bne     49f
    ldr     r5, [r6, #BSAPP_APP_OFF]
    movs    r0, r5
    movs    r1, #SYS_TASK_DATA_OFF
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     49f
    ldr     r7, [r5, #SYS_TASK_DATA_OFF]
    movs    r0, r7
    ldr     r1, =CHOICE_SELECTION_OFF
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     49f
    ldr     r0, [r7, #CHOICE_FS_OFF]
    cmp     r0, r4
    bne     49f                     @ stale controller from another field
    ldr     r0, =list_ctrl          @ fully validated: OneScreen_ListMenu can use it
    str     r7, [r0]

    ldr     r5, [r7, #CHOICE_STATE_OFF]
    cmp     r5, #CHOICE_STATE_LAST
    bhi     49f
    cmp     r5, #CHOICE_SHOW_LIST
    blo     44f
    movs    r0, #4                  @ native list/cleanup state
    b       48f
44: cmp     r5, #CHOICE_SHOW_YES_NO
    blo     47f                     @ setup/idle
    cmp     r5, #CHOICE_DONE
    beq     47f                     @ result delivered
    cmp     r5, #CHOICE_SHOW_YES_NO
    bne     45f
    movs    r0, #2                  @ state 3 initializes Yes
    b       48f
45: ldr     r1, =CHOICE_SELECTION_OFF
    ldr     r0, [r7, r1]
    cmp     r0, #1
    bhi     49f
    adds    r0, #2                  @ 0/1 -> Yes/No classification 2/3
    b       48f
47: movs    r0, #1
48: pop     {r3, r4, r5, r6, r7, pc}
49: movs    r0, #0
    b       48b
    .align  2
    .pool

@ Wipe the field labels once, and only while the field app still owns MAIN_3.
@ `field_yn_drawn` is reset without a VRAM write on app exit below.
    .thumb_func
OneScreen_FieldYesNoWipe:
    push    {r3, lr}
    ldr     r1, =field_yn_drawn
    ldr     r0, [r1]
    adds    r0, #1
    beq     51f                     @ already absent
    movs    r0, #0
    mvns    r0, r0
    str     r0, [r1]
    movs    r0, #LABEL_GEO_FIELD
    bl      OneScreen_BattleWipe
    bl      OneScreen_BattleMenu
51: pop     {r3, pc}
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ int OneScreen_MenuTaking(void)
@ 1 when the game's own start menu task is up and TAKING INPUT.
@
@ Deliberately narrower than "the menu exists". START_MENU_STATE_HANDLE_INPUT is
@ the only state where the panel should be on screen: pressing X or B moves the
@ menu to its close state in the same frame the game reads the press, so testing
@ for it cannot re-open a menu the player just dismissed.
@ ---------------------------------------------------------------------------
    .thumb_func
OneScreen_MenuTaking:
    push    {r4, lr}
    bl      OneScreen_TaskMan
    bl      OneScreen_StartMenuEnv
    cmp     r0, #0
    beq     86f
    ldrh    r0, [r0, #STARTMENU_STATE_OFF]
    cmp     r0, #STARTMENU_TAKING
    bne     86f
    movs    r0, #1
    pop     {r4, pc}
86: movs    r0, #0
    pop     {r4, pc}
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ int OneScreen_ScriptMenu(void)
@ Route field-owned lower modes. Binary mode-3 prompts are mirrored into the
@ world's MAIN_3 dialog; real lists and every other mode retain native routing.
@ ---------------------------------------------------------------------------
    .global OneScreen_ScriptMenu
    .thumb_func
OneScreen_ScriptMenu:
    push    {r3, r4, r5, lr}
    ldr     r0, =cfg_field_sys
    ldr     r0, [r0]
    cmp     r0, #0
    beq     59f
    ldr     r4, [r0]                @ FieldSystem through sFieldSysPtr
    cmp     r4, #0
    beq     59f                     @ no field system yet (boot, menus)
    movs    r0, r4
    movs    r1, #FS_BOTTOM_TASK_OFF
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     59f                     @ do not dereference a stale FieldSystem
    ldr     r5, [r4, #FS_SAVED_APP_ID_OFF]
    cmp     r5, #0
    beq     57f
    cmp     r5, #BSAPP_CHOICE_MENU
    bne     56f                     @ other field modes show their native UI

    movs    r0, r4
    bl      OneScreen_FieldMode3
    movs    r5, r0
    cmp     r5, #0
    beq     56f                     @ invalid chain: fail closed
    cmp     r5, #4
    beq     56f                     @ native list/cleanup state
    cmp     r5, #1
    beq     53f                     @ transition/setup/teardown

    @ Binary selection 2/3 -> image index 0/1. A missing or old blob also fails
    @ closed, so an unrenderable prompt always leaves the native choices visible.
    ldr     r0, =OneScreen_Labels
    ldr     r1, [r0]
    ldr     r2, =LABEL_MAGIC
    cmp     r1, r2
    bne     56f
    ldrb    r1, [r0, #5]
    cmp     r1, #LABEL_GEO_COUNT
    blo     56f
    subs    r5, #2
    ldr     r1, =field_yn_drawn
    str     r5, [r1]
    movs    r0, r5
    adds    r0, #(LABEL_GEO_FIELD << 4)
    push    {r0}
    ldr     r0, =BAND_DEST_FIELD
    bl      OneScreen_BandTheme
    pop     {r0}
    bl      OneScreen_BattleMenu    @ redraw after the game's message work
    b       54f

53: bl      OneScreen_FieldYesNoWipe
54: ldr     r1, =script_menu
    movs    r0, #1
    str     r0, [r1]
    movs    r0, #0                  @ engine A: world + dialog on upper LCD
    bl      OneScreen_SetSwap
    movs    r0, #1
    pop     {r3, r4, r5, pc}

56: bl      OneScreen_FieldYesNoWipe
    ldr     r1, =script_menu
    movs    r0, #1
    str     r0, [r1]

    @ A list menu we can reproduce is drawn on the world; anything else - an NPC
    @ choice whose words we never rasterised - swaps, exactly as before.
    bl      OneScreen_ListMenu
    cmp     r0, #0
    beq     55f
    ldr     r1, =list_hold
    movs    r0, #LIST_HOLD_FRAMES
    str     r0, [r1]
    movs    r0, #0                  @ engine A: keep the world, panel drawn on it
    bl      OneScreen_SetSwap
    movs    r0, #1
    pop     {r3, r4, r5, pc}

    @ It did not confirm this frame. If a panel was up a moment ago, hold it
    @ rather than tearing it down: the controller passes through states that fail
    @ these checks while it reprints an option's description, and wiping on every
    @ one of those made the whole panel blink as the cursor moved.
55: ldr     r1, =list_hold
    ldr     r0, [r1]
    cmp     r0, #0
    beq     51f
    subs    r0, #1
    str     r0, [r1]
    movs    r0, #0
    bl      OneScreen_SetSwap
    movs    r0, #1
    pop     {r3, r4, r5, pc}
51: bl      OneScreen_ListMenuWipe
    movs    r0, #1
    bl      OneScreen_SetSwap       @ engine B: native list/fallback on upper LCD
    movs    r0, #1
    pop     {r3, r4, r5, pc}

57: bl      OneScreen_FieldYesNoWipe
    bl      OneScreen_ListMenuWipe
    ldr     r4, =script_menu
    ldr     r0, [r4]
    cmp     r0, #0
    beq     59f                     @ it was never ours
    movs    r0, #0                  @ menu closed: put the world back
    str     r0, [r4]
    bl      OneScreen_SetSwap
59: movs    r0, #0
    pop     {r3, r4, r5, pc}
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ void OneScreen_Poll(void)
@ L+R swaps the screens anywhere. In the overworld, X brings the menu up with it
@ and B puts the world back - the field app draws that menu itself without
@ touching POWCNT1, so there is no transition to detect and it is driven from
@ the buttons the player already presses.
@ ---------------------------------------------------------------------------
    .global OneScreen_Poll
    .thumb_func
OneScreen_Poll:
    push    {r4, r5, r6, lr}
    ldr     r6, =pad_held
    ldr     r6, [r6]
    ldr     r4, =pad_new
    ldr     r4, [r4]

    @ --- L+R: manual swap, available everywhere ---
    ldr     r1, =TOGGLE_MASK
    movs    r0, r6
    ands    r0, r1
    cmp     r0, r1
    bne     10f                     @ not both held
    movs    r0, r4
    ands    r0, r1
    cmp     r0, #0
    beq     10f                     @ neither is new: still held from before
    bl      OneScreen_Toggle
    ldr     r0, =bt_manual          @ stop the battle logic re-asserting, so a
    movs    r1, #1                  @ manual override sticks until the menu you
    str     r1, [r0]                @ are on changes, or the phase does

10: ldr     r5, =menu_swapped
    ldr     r0, =cfg_app_callback
    ldr     r0, [r0]
    ldr     r0, [r0]
    ldr     r1, =cfg_field_callback
    ldr     r1, [r1]
    cmp     r0, r1
    beq     11f
    @ Not the overworld. KEEP the latch, so a trip into the bag/party/Pokédex and
    @ back leaves the menu drawn where you left it. Drop the latch only in
    @ battle, where the battle logic owns the screens.
    @
    @ Forget the upload, though: those apps reuse this layer's VRAM, so the
    @ strips will not have survived. Clearing the flag makes the next draw send
    @ them again rather than pointing the tilemap at whatever is there now.
    ldr     r0, =sm_drawn
    movs    r1, #0
    str     r1, [r0]
    @ Same for a list menu's pool. Stepping into ALBUM PHOTO and back left the
    @ tilemap pointing at tiles - and a palette - that application had since
    @ reused, which drew the panel as a solid black box.
    ldr     r0, =list_drawn
    movs    r1, #0
    str     r1, [r0]
    @ An app may reuse MAIN_3 immediately. Forget field labels without wiping
    @ here; the field-only path above is the sole safe place to touch that VRAM.
    ldr     r0, =field_yn_drawn
    movs    r1, #0
    mvns    r1, r1
    str     r1, [r0]
    ldr     r0, =cfg_app_callback
    ldr     r0, [r0]
    ldr     r0, [r0]
    ldr     r1, =cfg_ov12_lo
    ldr     r1, [r1]
    cmp     r0, r1
    blo     19f
    ldr     r1, =cfg_ov12_hi
    ldr     r1, [r1]
    cmp     r0, r1
    bhs     19f
    movs    r0, #0
    str     r0, [r5]
    b       19f

    @ A script owns the bottom screen (PC option list, shop, NPC choice): it
    @ holds the routing for as long as it is up, and puts the world back after.
11: bl      OneScreen_ScriptMenu
    cmp     r0, #0
    bne     19f

    @ X opens the menu - but only if the field was idle. On a ladder, mid script
    @ or during a cutscene the game discards the press and no menu appears, and
    @ we used to swap anyway. prev_task is LAST frame's taskman, so this does not
    @ race the same frame's handling of the press.
    ldr     r1, =KEY_X
    movs    r0, r4
    ands    r0, r1
    cmp     r0, #0
    beq     12f
    ldr     r0, [r5]
    cmp     r0, #0
    bne     13f                     @ the menu is UP: X closes it, always allow.
                                    @ Gating this was wrong - with the menu open
                                    @ a task is by definition running, so the
                                    @ idle test below rejected every close and X
                                    @ had to be pressed twice.
    ldr     r0, =prev_task
    ldr     r0, [r0]
    cmp     r0, #0
    bne     19f                     @ the field was busy: no menu will open
    ldr     r0, [r5]
13: movs    r1, #1
    eors    r0, r1                  @ X toggles
    str     r0, [r5]
    cmp     r0, #0
    bne     19f                     @ opening: the draw below picks it up
    bl      OneScreen_StartMenuWipe @ closing: take the panel off the world
    movs    r0, #0                  @ and undo the swap, if this was a grid we
    bl      OneScreen_SetSwap       @ could not draw and swapped for instead
    b       19f

12: movs    r0, r4
    movs    r1, #KEY_B
    ands    r0, r1
    cmp     r0, #0
    beq     15f
    ldr     r0, [r5]
    cmp     r0, #0
    beq     15f                     @ no menu of ours is up: leave B alone
    movs    r0, #0
    str     r0, [r5]
    bl      OneScreen_StartMenuWipe @ B closed the menu
    movs    r0, #0
    bl      OneScreen_SetSwap
    b       19f

    @ Keep the panel on the world while the menu is open. Drawn every frame, not
    @ once: the field redraws underneath it, and coming back from a sub-app
    @ rebuilds the menu task entirely.
    @ Re-arm from the game's own state. Saving tears the menu down and builds it
    @ again, which cleared this latch and left the panel gone for the rest of the
    @ menu's life - saving looked fine only because the menu closes afterwards
    @ anyway, while cancelling came back to a menu we had stopped drawing.
    @
    @ This has to sit AFTER the label: the B path above branches to 15 rather
    @ than falling through, so the first version of it was never reached at all.
15: bl      OneScreen_MenuTaking
    cmp     r0, #0
    beq     18f
    movs    r0, #1
    str     r0, [r5]

18: ldr     r0, [r5]
    cmp     r0, #0
    beq     16f

    @ ...unless the menu is demonstrably gone: a script took the field over, the
    @ way Dig and Escape Rope do, or no task is running at all. Either way nobody
    @ pressed B but the menu has ended. This only ever CLEARS the latch - nothing
    @ here can raise it - so it cannot put the menu over a cave card or a flight,
    @ which is what testing "any ARM9 task" did.
    bl      OneScreen_MenuGone
    cmp     r0, #0
    beq     14f
    movs    r0, #0
    str     r0, [r5]
    bl      OneScreen_StartMenuWipe
    ldr     r1, =field_restore
    movs    r0, #FIELD_RESTORE_FRAMES
    str     r0, [r1]
    b       16f

14: ldr     r1, =field_restore      @ the menu is up: drop any pending restore so
    movs    r0, #0                  @ it cannot fire underneath the panel
    str     r0, [r1]
    bl      OneScreen_StartMenu     @ draw it onto the world; no swap at all
    cmp     r0, #0
    beq     17f
    movs    r0, #0                  @ the panel is on engine A - hold it there,
    bl      OneScreen_SetSwap       @ so coming back from SAUVER returns here
    b       19f
    @ Not drawn. If the start menu itself is still the field's task, it is up
    @ but showing something we do not draw - the save box, or a layout the
    @ patcher could not label - so show the touch screen. If it is not, the menu
    @ has handed the field to something else: RETIRE in the Safari Zone jumps
    @ straight to the script runner, which prints its question on the world
    @ before it takes the bottom screen. Keep the world for that, and take the
    @ panel down.
17: bl      OneScreen_TaskMan
    bl      OneScreen_StartMenuEnv
    cmp     r0, #0
    beq     20f
    movs    r0, #1
    bl      OneScreen_SetSwap
    b       19f
20: bl      OneScreen_StartMenuWipe
    movs    r0, #0
    bl      OneScreen_SetSwap
    b       19f

    @ No menu of ours is up. If an app just handed the field back, the layout it
    @ left behind is still in place - put the world on top.
16: ldr     r1, =field_restore
    ldr     r0, [r1]
    cmp     r0, #0
    beq     19f
    subs    r0, #1
    str     r0, [r1]
    movs    r0, #0
    bl      OneScreen_SetSwap

    @ Sample the field's task for next frame, so the X gate above reads the
    @ state BEFORE the press rather than after the game has handled it.
19: bl      OneScreen_TaskMan
    ldr     r1, =prev_task
    str     r0, [r1]
    pop     {r4, r5, r6, pc}
    .align  2
    .pool


@ ---------------------------------------------------------------------------
@ void OneScreen_Intro(void)
@ Put the opening cinematic's two misrouted scenes on the right screen.
@
@ The intro is overlay 60 running four scene functions in turn. Two of them show
@ their content on the lower LCD, and they need OPPOSITE corrections - scene B
@ wants engine B raised, the tail of scene A wants engine A raised - so each
@ carries its own value rather than a shared "swap".
@
@ Scene A is the awkward one. Its first half is correct and its second half is
@ not, and the two are indistinguishable: diffing the whole 512-byte scene block
@ between a good frame and a bad one leaves exactly ONE differing byte, a frame
@ counter. So this is the one place in the patch driven by elapsed time. That is
@ defensible for a cinematic, whose scenes really are defined by time rather than
@ by state, but it is a hardcoded number and worth knowing about. The changeover
@ is taken on a frame where both screens are black, so being a frame out either
@ way is invisible.
@
@ Everything fails closed: no resolved address, no data pointer, or a pointer
@ outside main RAM, and the intro simply plays as it did before.
@ ---------------------------------------------------------------------------
    .global OneScreen_Intro
    .thumb_func
OneScreen_Intro:
    push    {r4, r5, r6, lr}
    ldr     r0, =cfg_app_callback
    ldr     r4, [r0]
    cmp     r4, #0
    beq     99f

    @ The tick counter beside the application slot. The last sequence runs past
    @ the end of the intro application, so it is held on this rather than on a
    @ scene counter - by then there is no scene left to ask.
    movs    r6, #0
    ldr     r0, =cfg_intro_clock
    ldr     r0, [r0]
    cmp     r0, #0
    beq     90f
    ldr     r6, [r0]
    ldr     r0, =intro_hold_until
    ldr     r1, [r0]
    cmp     r1, #0
    beq     90f
    ldr     r2, =cfg_field_sys      @ the game has started: the intro is long over
    ldr     r2, [r2]
    cmp     r2, #0
    beq     88f
    ldr     r2, [r2]
    cmp     r2, #0
    bne     89f
88: cmp     r6, r1
    bhs     89f
    movs    r0, #0                  @ still inside it: hold engine A up
    bl      OneScreen_SetSwap
    b       99f
89: movs    r1, #0
    str     r1, [r0]                @ expired

90: ldr     r5, [r4]                @ the scene function running now
    cmp     r5, #0
    beq     99f

    ldr     r0, =cfg_intro_a_exec
    ldr     r0, [r0]
    cmp     r0, #0
    beq     91f
    cmp     r5, r0
    bne     91f
    ldr     r1, =INTRO_A_FROM
    bl      OneScreen_IntroPast
    cmp     r0, #0
    beq     99f
    movs    r0, #0                  @ raise engine A
    bl      OneScreen_SetSwap
    b       99f

91: ldr     r0, =cfg_intro_b_exec
    ldr     r0, [r0]
    cmp     r0, #0
    beq     92f
    cmp     r5, r0
    bne     92f
    ldr     r1, =INTRO_B_FROM
    bl      OneScreen_IntroPast
    cmp     r0, #0
    beq     99f
    movs    r0, #1                  @ raise engine B
    bl      OneScreen_SetSwap
    b       99f

92: ldr     r0, =cfg_intro_c_exec
    ldr     r0, [r0]
    cmp     r0, #0
    beq     99f
    cmp     r5, r0
    bne     99f                     @ not a scene we correct: leave it alone
    ldr     r1, =INTRO_C_FROM
    bl      OneScreen_IntroPast
    cmp     r0, #0
    beq     99f
    cmp     r6, #0
    beq     93f                     @ no clock: correct the scene, but no hold
    ldr     r0, =intro_hold_until   @ arm the hold, so the sequence keeps the
    ldr     r1, =INTRO_C_HOLD       @ screen after the application has gone
    adds    r1, r6, r1
    str     r1, [r0]
93: movs    r0, #0                  @ raise engine A
    bl      OneScreen_SetSwap
99: pop     {r4, r5, r6, pc}
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ int OneScreen_IntroPast(r1 = frame) - 1 once this scene has run that far.
@ r4 must hold the application slot. Fails closed on any unusable pointer.
@ ---------------------------------------------------------------------------
    .thumb_func
OneScreen_IntroPast:
    push    {r4, r5, lr}
    movs    r5, r1
    ldr     r0, [r4, #4]            @ the scene's own data block
    movs    r1, #INTRO_COUNTER_OFF
    bl      OneScreen_MainRamRange
    cmp     r0, #0
    beq     87f
    ldr     r0, [r4, #4]
    ldr     r0, [r0, #INTRO_COUNTER_OFF]
    cmp     r0, r5
    blo     87f
    movs    r0, #1
    pop     {r4, r5, pc}
87: movs    r0, #0
    pop     {r4, r5, pc}
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ void OneScreen_Frame(void)
@ Replaces `bl 0x0200110C` at 0x02000DB0 in the main loop: run the original
@ call, then our per-frame work. The displaced call takes no arguments and its
@ return value is unused by the loop, so wrapping it is safe.
@ ---------------------------------------------------------------------------
    .global OneScreen_Frame
    .thumb_func
OneScreen_Frame:
    push    {lr}
    ldr     r3, =ORIG_LOOP_FN
    blx     r3
    bl      OneScreen_UpdatePad
    bl      OneScreen_Intro
    bl      OneScreen_AppIntent
.ifndef DISABLE_AUTO_BATTLE
    bl      OneScreen_AutoBattle
.endif
    bl      OneScreen_Poll
    bl      OneScreen_MapHold
    bl      OneScreen_PcHold        @ last word on routing, after Poll
    pop     {pc}
    .align  2
    .pool

@ ---------------------------------------------------------------------------
@ The command labels, rasterised from the ROM's own strings and font at patch
@ time by onescreen/labels.py and written in here by inject.fill_labels. Kept
@ last in the payload so adding to it never moves any code.
@
@ The header (BLOB_HEADER in labels.py) holds five geometry records, the
@ start-menu record and the list-menu records. Four unique localized 4bpp image
@ sets follow it; the field-dialog geometry aliases
@ the battle Yes/No pixels. The hook reads the recorded geometry rather than
@ repeating it, so the layout cannot drift away from the rasteriser's.
@
@ An unfilled blob reads as zeroes, whose magic does not match, and
@ OneScreen_BattleMenu draws nothing at all rather than garbage.
@ ---------------------------------------------------------------------------
    .align  2
    .global OneScreen_Labels
OneScreen_Labels:
    .space  LABEL_BLOB_SIZE
