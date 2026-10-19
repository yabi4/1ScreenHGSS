# The full decompilation, and what it changed

In October 2026 a complete decompilation of HeartGold/SoulSilver appeared:
[ctrl-cheeb-del/pokeheartgold](https://github.com/ctrl-cheeb-del/pokeheartgold). Every
overlay is C, and both US ROMs rebuild from it byte-for-byte. This patch was reverse-engineered
from retail ROMs before it existed, using pret's partial decompilation where it could. This page
records what the full one confirmed, what it corrected, and how its numbers were checked.

## How it is used here

- **As a map, not a build base.** It builds the US 1.0 English ROMs only, and needs the
  proprietary MWCC compiler and NitroSDK tools. This patch works on any language's retail dump
  by finding what it needs by shape, and stays that way.
- **Reference only.** The repository has no licence file, so nothing is copied from it. Names,
  offsets and file paths are cited; the code here is this project's own.
- **Trust the layout, not the names.** It is byte-matching, so its struct layouts and code are
  exactly what the compiler produced. Its names were written by LLM agents and are hypotheses —
  several fields are still `unk_XX`, and some names are wrong. Everything below was checked
  against the code that uses it, not against its name.
- **Pinned.** Citations are to commit `77565981` (2026-10-15). The project was renaming
  functions daily at the time; a path or name here may have moved since.

## How the offsets were checked

Three independent sources, and a value is only used when they agree:

1. **The decompilation's own headers, compiled.** `arm-none-eabi-gcc` with
   `-mabi=apcs-gnu -mstructure-size-boundary=8 -fno-short-enums` lays structs out the way MWCC
   does (64-bit values aligned to 4, no padding of small structs, `int`-sized enums), and
   `offsetof` gives the answer directly instead of counting fields by hand. It reproduced every
   offset this project had already measured in the game — `FieldSystem` `+0x1C`, `+0xD3`,
   `+0xD8`, `BattleSystem` `+0x19C`, `BattleInput` `+0x68B` — before it was trusted for new ones.
   One known limitation: gcc may place a bitfield's storage unit a byte earlier than MWCC
   (`TouchscreenMenuData.layout`), so bitfields are confirmed from retail code instead.
2. **pret's retail assembly.** Overlays pret had not decompiled (27, 14, 15, much of 1) are
   instruction-level dumps with retail US addresses, so an offset can be read off a real
   `ldr`/`str`.
3. **What the hook measured from savestates**, which is what shipped and was play-tested.

`tools/test_hook.py` then runs the assembled hook against synthetic structs built with these
offsets, under an ARM emulator — see [DEVELOPMENT.md](DEVELOPMENT.md#verifying-a-change).

## Cross-reference

Offsets are identical in every region; only data and overlay addresses move.

### `gSystem` (`struct System`, `include/system.h`)

| hook | offset | field | status |
|---|---|---|---|
| `DEF_APP_CALLBACK` | `+0x00` | `vBlankIntr` | confirmed |
| `cfg_app_callback`+4 reads | `+0x04` | `vBlankIntrArg` | confirmed |
| `DEF_PAD_HELD` | `+0x38` | `heldKeysRaw` | confirmed |
| `DEF_SCREENS_FLIP` | `+0x69` | `screensFlipped` | confirmed |

### The field

| hook | offset | field | status |
|---|---|---|---|
| `BGCONFIG_OFF` | `FieldSystem+0x08` | `bgConfig` | confirmed |
| `FS_TASKMAN_OFF` | `+0x10` | `taskman` | confirmed |
| `FS_BOTTOM_TYPE_OFF` | `+0x18` | `bottomScreenType` | new: 1 overworld, 3 Union Room |
| `FS_SAVED_APP_ID_OFF` (was `unk1C`) | `+0x1C` | `savedBottomScreenAppId` | confirmed, renamed |
| `FS_START_MENU_CURSOR_OFF` | `+0xD3` | `startMenuCursorPos` | confirmed |
| `FS_BOTTOM_TASK_OFF` | `+0xD8` | `bottomScreenTask` | confirmed |
| `FIELD_SYSTEM_SIZE` | `0x128` | `sizeof(FieldSystem)` | new, for range checks |
| `TASK_FUNC_OFF`, `TASK_ENV_OFF` | `TaskManager+0x04/+0x0C` | `func`, `env` | confirmed |
| `STARTMENU_STATE_OFF` | `StartMenuTaskData+0x26` | `state` (u16) | confirmed |
| `SM_INHIBIT_OFF` | `+0x34C` | `inhibitIconFlags` | confirmed |
| `START_MENU_DATA_SIZE` | `0x38C` | `sizeof(StartMenuTaskData)` | new |
| `DEF_START_MENU_TASK` | `0x0203BEF1` | `Task_StartMenu` (`src/start_menu.c`) | confirmed: the signature decodes to its prologue and 21-state switch |
| `SYS_TASK_DATA_OFF` | `SysTask+0x10` | `data` | confirmed |

The bottom-screen app manager (`src/field/bottom_screen_app.c`), which the hook walks to reach
the touch controllers:

| hook | offset | field |
|---|---|---|
| `BSAPP_ID_OFF` | `+0x00` | `appId` — 0 the icon bar / X menu, 3 the choice menu |
| `BSAPP_STATE_OFF` | `+0x01` | `state` — 1 running, 2..7 switching and fading |
| `BSAPP_NEXT_ID_OFF` | `+0x02` | `nextAppId` |
| `BSAPP_APP_OFF` | `+0x04` | `app`, the app's own SysTask |
| `BSAPP_FS_OFF` | `+0x08` | `fieldSystem` |

The touch menu app itself (`TouchscreenMenuData`, `src/touchscreen_menu.c`, overlay 27,
`0x540` bytes), which the X-menu panel reads from v0.3 on. Every offset here is also in pret's
retail assembly of overlay 27 (`ov27_02259F80`, `ov27_0225C170`, `ov27_0225C1AC`):

| hook | offset | field |
|---|---|---|
| `TSM_FS_OFF` | `+0x10` | `fieldSystem` |
| `TSM_SELECTION_OFF` | `+0x14` | `selection`, the selected slot 0..6 |
| `TSM_ICONS_OFF` | `+0x470` | `icons[7]`, `{u8 shown; String *label}` |
| `TSM_LAYOUT_OFF` | `+0x51C` | `layout:4`, bits 1-4 — gcc puts this unit a byte early; retail code reads `0x51C` |

Its layouts are `sTouchscreenMenuLayouts` (US `0x0225CFC8`), embedded in `labels.py` as
`TOUCH_LAYOUTS` and checked against the ROM's own overlay 27 at patch time.

### Script menus (`TouchscreenChoiceMenuData`, `src/touchscreen_choice_menu.c`; `ScriptMenu`, `src/field/script_menu.c`)

| hook | offset | field | status |
|---|---|---|---|
| `CHOICE_STATE_OFF` | `+0x00` | `state` | confirmed; 3..5 yes/no, 7..10 list, 11 cancel |
| `CHOICE_RESULT_OFF` | `+0x04` | `result`, the var the list writes | new: `OneScreen_TutorExec` puts it back after taking the tutors' list |
| `CHOICE_MENU_OFF` | `+0x0C` | `menu`, the slot `ScrCmd_MenuInit` fills | **new — the hook now reads this** |
| `CHOICE_FS_OFF` | `+0x24` | `fieldSystem` | confirmed |
| `LIST_CURSOR_OFF` | `+0x394` | `selection` | confirmed |
| — | `+0x39C` | `selectionCallback` = `MenuExec_PrintItemHelp` | explains the "ARM9 code address" in FINDINGS |
| `CHOICE_CALLBACK_ARG_OFF` (was `LIST_MENU_OFF`) | `+0x3A0` | `selectionCallbackArg` | **was read as the menu**; only a copy, and stale for the move tutor |
| `SCRIPT_MENU_STRBUFS_OFF` | `ScriptMenu+0x1C` | `strbufs[28]` | confirmed |
| `SCRIPT_MENU_COUNT_OFF` | `+0x9B` | `count` | confirmed |
| `SCRIPT_MENU_Y_OFF` | `+0x99` | `y` | new: the hook moves an anchored-bottom list up itself now |
| `STRING_MAXSIZE_OFF`, `STRING_MAGIC_OFF` | `String+0x00`, `+0x04` | `maxsize`, `magic` (`0xB6F8D2EC`) | new: `ScriptMenu_Init` gives every entry `String_New(80)`; `String_c_str` asserts the magic in the retail build |

The script command table and the functions the native lists use, found by the patcher
from table entries 752 and 71 (`regions.resolve_native_lists`):

| what | where | how it is found |
|---|---|---|
| `gScriptCmdTable` | ARM9 `.rodata`, 853 Thumb pointers | shape; entries 0 and 1 are `movs r0,#0; bx lr` |
| `ScrCmd_MenuExec` | table[752] | five calls; pool holds `0x02047909`, `0x020478D1` |
| `ScrCmd_ScriptListMenuExec` | table[71] | three calls; pool holds `0x020418B5` |
| `SetupNativeScript` | last call of both | must agree |
| `ScriptMenu_ShowList` | second call of table[71], overlay 1 | retail prologue (pret `ov01_021EDFA4`); exactly two calls |
| `ScriptMenu_GetListItemsWidth` | first call of `ShowList` | retail code up to its one call (pret `ov01_021EE2E4`) |
| `ScriptMenu_OpenListWindow` | second call of `ShowList` | retail prologue (pret `ov01_021EE01C`); `ShowListWithWidth` right before it is `ldr r3, =OpenListWindow; bx r3`; `0x3D9` in its pool |
| `FontID_String_GetWidth` | the one call of `GetListItemsWidth`, ARM9 | the whole retail function (pret `sub_02002F30`); its second call, `String_c_str`, has the String magic in its pool |
| `ScrCmd_MoveTutorChooseMove` | table[653], overlay 1 | retail prologue (pret `ScrCmd_MoveTutorChooseMove`, before `scrcmd_move_tutor.c`); first call is `MenuExec`'s menu-slot getter; ends `SetTouchscreenChoiceMenuState(fs, 3, 7, var)`, `SetupNativeScript` - both `MenuExec`'s - with a wait whose pool holds `0xEEEE`; `0xFFFD` and `0xFFFE` in its pool. Optional |
| `ScriptMenu.x`, `.ret_p`, `.items` | `+0x98`, `+0xA0`, `+0x1C4` | the source's own offset comments, and the helper |

### Battle (`include/battle/battle.h`, `include/battle/battle_input.h`)

| hook | offset | field | status |
|---|---|---|---|
| `BATTLE_INPUT_OFF` | `BattleSystem+0x19C` | `battleInput` | confirmed |
| `BS_GRAPHICS_MODE_OFF` | `+0x23FD` | `graphicsMode` — 3 while the bag or party is up | **new**: `battleInput` is freed unless it is 0 |
| — | `+0x2445` | `trainerAIOverlayLoaded` | new: 1 for exactly the command-selection phase |
| `BI_CURMENU_OFF` | `BattleInput+0x68B` | `curMenuId` (s8) | confirmed |
| `BI_MENU_CURSOR_OFF` | `+0x6DC` | `menuCursor` {enabled, menuY, menuX} | **corrected** from a learned value starting at `0x6D4` (`scrollXEnd`) |
| `BATTLE_INPUT_SIZE` | `0x6F8` | `sizeof(BattleInput)` | new |
| `BSTATE_BATTLE_MAIN` | `9` | `Battle_Run` state while the `BattleSystem` lives | new |
| `BS_PALETTE_OFF` | `BattleSystem+0x28` | `palette`, a `PaletteData` with `autoTransparent` set | **new**: its VBlank callback pushes the main-BG buffer every frame |
| `BS_MSG_ICON_OFF` | `+0x1B0` | `msgIcon`, a `PaletteBlink` on top-screen palette 11 | **new** |

pret labels this region of `BattleInput` with offsets that are `0x20` to `0x28` too low; its
*layout* is the same as the full decompilation's. Only the names drifted.

### Oak's speech (`include/oaks_speech_internal.h`, `src/palette_blink.c`)

| hook | offset | field | status |
|---|---|---|---|
| `OAK_STATE_OFF` | `OakSpeechData+0x0C` | `state` | confirmed |
| `OAK_PRINT_STATE_OFF` | `+0x104` | `printDialogMsgState` | confirmed |
| `OAK_STRING_OFF` | `+0x110` | `string` | confirmed |
| `OAK_BLINK_OFF` | `+0x114` | `paletteBlink` | **new** |
| `OAK_NUMOPTS_OFF`, `OAK_CURSOR_OFF` | `+0x161`, `+0x163` | `menuData.numOptions`, `.cursorPos` | confirmed |
| `BLINK_BYTES_OFF` | `PaletteBlink+0x4C` | `screen`, `palette`, `state`, `timer` | **new**; state 0 RESTART, 1 RUN, 2 PAUSE, 3 END |
| `BLINK_APPLY_MAIN_BG` | `0x020165A5` | `PaletteBlink_LoadMainBgPltt` | pret `sub_020165A4`, the `apply` for a top-screen hardware blink |

### The selected band's palette (`include/palette.h`, `src/evolution_scene.c`)

| hook | offset | field | status |
|---|---|---|---|
| `PLTT_OPAQUE_OFF`, `PLTT_FADED_OFF`, `PLTT_SIZE_OFF` | `PaletteData+0x00`, `+0x04`, `+0x08` | `buffers[PLTTBUF_MAIN_BG]`: `opaque`, `transparent`, `size` | **new**; `transparent` is what `PaletteData_PushTransparentBuffers` loads |
| `EVOLUTION_PLTT_OFF` | `EvolutionTaskData+0x14` | `paletteData` | **new** |
| `EVOLUTION_BLINK_OFF` | `+0x58` | `paletteBlink`, on top-screen palette 11 | **new**; paused by the game itself from `EVO_STATE_WAIT_CRY` on |

`PaletteBlink_SetState` takes a command, not a state: 0 restarts it, 1 **pauses** it and 2
ends it. A blink built over a `PaletteData` writes both of its buffers, so it is checked by its
`plttData` matching the scene's own rather than by its `apply` pointer.

## What it corrected

- **The battle cursor** was at `+0x6DC`, not the `+0x6D4` the hook started from. The hook
  learned the real value at runtime, so play was right, but the learner kept running while the
  bag was open and read freed memory. Fixed at `0x6DC`; the learner is gone.
- **Freed battle input.** The bag, the party and the catch naming screen free `BattleInput` and
  leave the pointer behind. The hook read `curMenuId` out of the freed block, which is why the
  bag seemed to "leave the menu on the root". Every read now requires `graphicsMode == 0`, and
  the `BattleSystem` itself is only used while `Battle_Run` is in `BSTATE_BATTLE_MAIN` — during
  the link stages `manager->data` is something else, and after the battle it is freed.
- **Menu ids 5..8 are not the ordinary command menu.** 5/6 are the first rival battle (FIGHT
  only) and 7/8 the Safari Zone (BALL / BAIT / MUD / RUN), which were drawn as
  FIGHT / BAG / POKéMON / RUN. They now swap, like the Bug Contest's 19/20 already did.
- **The X menu in the special zones** was thought unreachable: the layout lives in the touch
  app's own data. The decompilation names that data and the path to it, so the panel now
  draws the game's own grid in all seven layouts, and its "normal layout" test - the RETIRE
  bit alone, which also passed in the Union Room, Colosseum and Battle Tower partner room -
  is only a fallback, and an exact one.
- **A Pokéathlon mart menu** (BUY / INFO / SEE YA, `scr_seq_0003_056`/`_060`) matches the
  shop's first-entry key and would be drawn as the shop; nothing seems to call it, but menus
  are now matched on every predictable entry.
- **The list menu pointer** is `+0x0C`, the menu's own slot; `+0x3A0` is a callback argument
  that the move tutor never sets.
- **Overlay identities.** Overlay 5 is the link battle's preview/VS screens, not the party menu
  (which is ARM9 static). Overlay 10 is the trainer AI — but it is resident for exactly the
  command-selection phase, which is why the overlay-slot proxy works. Berry pots are an app in
  16 running its UI in 17. The overlays pret left unnamed are named in [AUDIT.md](AUDIT.md).
- **Oak's flashing band** was a `PaletteBlink` on the dialog's palette rewriting all sixteen
  colours twice a second, not a race with the text printer. It is paused while his questions
  are up. The same research found the hook erasing the ends of his longer US lines.
- **The band in battles and the evolution scene** was written to palette RAM, which both
  scenes overwrite from their `PaletteData` every frame, and both run a `PaletteBlink` on the
  same palette. The evolution scene pauses its own wherever the cycle happens to be, which can
  leave colour 12 white for the rest of the scene. The band now goes into the pushed buffer.
- **`start_menu.c` writes the X-menu cursor** on a touch, not only reads it; the touch overlay
  writes it on every D-pad move.
