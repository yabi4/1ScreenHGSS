# Changelog

## Unreleased — `V0.3`

Built against the full decompilation of HeartGold/SoulSilver
([ctrl-cheeb-del/pokeheartgold](https://github.com/ctrl-cheeb-del/pokeheartgold)), which
appeared after v0.2b. It confirmed almost every offset this patch had measured from the game,
and corrected a handful. `docs/DECOMP.md` has the cross-reference.

### Battles

- **Safari Zone and first-rival battles swap instead of mislabelling.** Their command menus
  are BALL / BAIT / MUD / RUN and FIGHT alone, and were drawn as FIGHT / BAG / POKéMON /
  RUN. Until there are labels for them they get the touch screen, as the Bug Contest's
  already did.
- **The highlight's position is fixed, not learned.** The hook used to discover where the
  game keeps its cursor by watching it move, starting from a wrong guess. The decompilation
  says where it is, so the guess and the learning are gone.
- **The selected band holds its colour in battles and after an evolution.** Both scenes copy
  their own palette buffer over palette RAM every frame, so the theme's colour, written
  only to palette RAM, lasted until the next copy and the band could flicker back to the
  game's salmon or white. The colour now goes into that buffer as well, and the battle's
  message-icon blink, which rewrites the same colours twice a second, is held still while
  the commands or a yes/no box are up. The evolution scene pauses its own blink wherever it
  happens to be, which could leave the band white behind *Oui / Non* for the rest of the
  scene; that is covered by the same buffer write.
- **No more reads from freed memory.** The bag, the party and the catch naming screen free
  the structure the command menu lives in; the hook now checks the game's own
  `graphicsMode` before reading it, and only uses the battle's data while the battle proper
  is running.

### Oak's speech

- **The band behind Oak's selected answer no longer flashes.** The full decompilation
  showed the cause: a palette blink animating the bottom-screen icon rewrites the dialog
  window's whole palette twice a second, after this patch has written its colour. It is
  held still while his three questions are up - the icon it animates is hidden there - and
  restarted afterwards.
- **The ends of Oak's longest lines are no longer erased.** The patch painted over the
  right-hand corner of his dialog box on every frame, believing text never reached it; in
  English five of his lines do. It now only takes its own box down when a question ends.

### Menus

- **NPC list menus open on the top screen, in the game's own list window.** HGSS kept the
  top-screen list it inherited from Diamond and Pearl - `ScriptMenu_ShowList`, the same
  menu object the touch list reads - so the NPC lists the patch does not draw itself
  (fossils, the apricorn juice stand, the Pokéathlon Dome's counters, most one-off NPC
  choices...) are handed to it instead of taking the screen. B answers the way the touch
  list does. A list that would land on a box the script already has up there (Mom's
  savings) keeps the touch screen. `--touch-lists` (or *Old-style NPC lists* in the window)
  keeps all of them there.
- **Formatted lists and the move tutors open there too** (payload v33). Entries laid out in
  two lines on the touch screen - Battle Frontier prize shops, *DEPOSIT / POKéMON*,
  Pokéathlon courses - are folded onto one line, an indented second line becoming a price
  column shared by the whole list; entries that already have a `CURSOR_X` column (drink
  machines, the Game Corner's coins, the day-care's levels) get a window wide enough for
  it, which the game's own sizing, skipping the column, came up short of. The Battle
  Frontier move tutors build their list with a command of their own (653); the patch lets
  it run, then takes its list back before the touch screen shows it. An entry with any
  other formatting keeps the touch screen, and nothing about a list is changed unless it
  does open on top.
- **List menus are recognised by every entry, not just the first.** The script corpus has
  a Pokéathlon mart menu, BUY / INFO / SEE YA, that shares the shop's first entry and would
  have been drawn as the shop's words. Nothing in the decompilation seems to call it; the
  Dome's own counters read PRIZE EXCHANGE / INFO / SEE YA! and now get the game's own
  top-screen list.
- **The X menu is drawn in the Safari Zone, the Bug Contest, Pal Park and the Union Room**,
  in each one's own arrangement, instead of taking the screen. The panel now reads the touch
  menu's own data - which layout is up, which icons it shows and which is selected -
  rather than reconstructing it, so it matches the touch screen everywhere. The Union Room
  used to be drawn with the normal grid, without CHAT and with LOG labelled POKéGEAR.
- **Choosing RETIRE keeps the world on top** for the question that follows, instead of
  handing the screen to the touch menu. RETIRE jumps straight from the menu to a script, and
  the screen is now only handed over while the menu itself is what is showing something
  the patch cannot draw - the save box.
- Every pointer the X menu walks is range-checked against the size of what it points at.

### Screens nobody had played

- **The Pal Pad and the rankings viewer open on the top screen.** Both draw every window
  they have on engine A and then send engine A to the touch screen through the game's
  shared display helper, which the static flips cannot reach. They now have app-table
  entries, like name entry and the move relearner.
- **The Union Room's group drawing stays on the touch screen**, as the trainer-card
  signature does: its canvas is drawn on with the stylus, and the default flip had put it
  on top, where it cannot be tapped.
- The rest of the 19 screens that set no routing of their own were checked against the
  decompilation; `docs/AUDIT.md` gives the verdict for each.
- An app-table entry whose code does not match no longer switches off the entries after
  it, and the overlay search no longer misses a match that ends exactly at the end of an
  overlay - which could have let a duplicate through the one-match rule.

### Development

- `tools/test_hook.py` runs routines from the assembled hook against synthetic game
  structures under an ARM emulator (`pip install unicorn`). It also checks that
  `CONFIG_FIELDS` in `onescreen/inject.py` still lines up with the hook's config block.
- `tools/make_payload.py` finds `arm-none-eabi` binutils on `PATH` or `$DEVKITARM`, and
  refuses a payload that would not fit in ITCM.
- `docs/AUDIT.md` corrects overlay 5 (the link battle screens, not the party menu) and names
  the overlays pret left unnamed.
- The patch log names every overlay it touches after the decompilation's linker spec;
  four of the old names were wrong (57, 59, 70 and 72 are the Ball Capsule editor, the
  apricorn box, the GTS and the Wi-Fi connection screen, not battle code).
- A GitHub Actions workflow (`.github/workflows/payload.yml`) rebuilds the payload, checks
  it is byte-identical to the committed one, and runs the emulated tests on every push.

## `V0.2b`

### Colour themes

Everything the patch draws now takes its colours from one of three schemes, chosen when you
patch: the menus drawn on the world, and the band behind whichever choice is selected.

| theme | menus | selected choice |
|---|---|---|
| `classic` | white, like the game's own dialogue box | grey |
| `heartgold` | white with a gold tint and frame | gold `#fbd392` |
| `soulsilver` | white with a silver tint and frame | silver `#9abafb` |

The panels cost nothing to theme — their palettes were already a fixed 64 bytes in the
label blob, so every offset and size is identical whichever theme is chosen.

The selected band was a different matter. Every prompt paints it with palette index 12, and
the patch never wrote that entry: it borrowed whatever the game happened to keep there,
which is why a highlight was salmon in battle and grey elsewhere. Theming it means writing
palettes the patch had not written before, per frame while a prompt is drawn — never
unconditionally, since palette memory is shared and colouring it outside a prompt would
recolour whatever else was using that entry.

Oak's questions used to borrow the intro's own edition colour for their band. A chosen
theme supersedes that; picking HeartGold or SoulSilver reproduces roughly what it did.

They also used to invert their selected text — white ink, no shadow — because that band was
whatever saturated colour Oak's intro happened to be showing, and dark text vanished into
it. A theme picks a light colour deliberately, so his selected choice came out white while
every other prompt's came out black. It no longer inverts.

One thing is **not** fixed: the band behind Oak's selected choice still alternates with the
game's own red. That predates themes — the earlier version flashed the same way — and it is
a race with a print task that runs later in the frame than this patch does.
`docs/FINDINGS.md` records what was ruled out and what the next step would be.

### A windowed patcher

`1ScreenHGSS.exe` — drop a ROM on it or click to browse and press Patch. No Python, no
ndspy, nothing to install. The theme is chosen from the game, HeartGold or SoulSilver,
unless you pick one yourself. `python patch-gui.py` opens the same window from
source, and `patch.py` gains `--theme` and `--version`.

The window checks the file itself before handing it to the ROM library, which validates
almost nothing — it pads anything short with zeros, so a five-byte file would otherwise
"identify" perfectly well and fail much later with a traceback.


### The opening cinematic plays on the top screen

Three of its scenes showed their content on the lower LCD. They are identified inside
overlay 60 by their own code, so the fix carries across regions, and each carries its own
correction — two of them want one engine raised, the third the other.

This is the one place in the patch driven by elapsed time: the halves of a scene that need
different screens are separated by nothing but a frame counter. The changeovers are taken
on frames where the screen is black, so being a frame either side cannot be seen.
Play-tested on US HeartGold as well as French SoulSilver.

### The move relearner opens on the top screen

The Blackthorn tutor's move list set no routing of its own and inherited whatever was
current — which, since field prompts began holding the world on top, meant the bottom
screen. It is the first application handled that lives in an **overlay** rather than in
ARM9, so it is found by searching that overlay for its own code: overlay addresses move
between regions, and a written-down one would have worked on French alone.

### Saving from the X menu behaves

The save box now takes the screen, and the menu comes back afterwards — drawn, and
following the D-pad — whether you save or cancel. Saving is the one menu entry that does
not start an application, so several guards that key off an application change did nothing
for it. See `docs/FINDINGS.md`.

### Notes

- Adding an entry to the application table is now bounded by the table's own end. It was
  previously checked only against the size of the payload, so one entry too many overwrote
  the code that follows and black-screened the game on boot with nothing to show for it.

## Unreleased — `beta-ui`

Going deeper into single-screen play than rerouting alone allows: compact choices now
appear beside the question instead of taking the other screen.

### The battle command menu is drawn on the battle scene

`ATTAQUE / SAC / FUITE / POKéMON` now sit in the right-hand end of the battle message
window, which is otherwise empty. The scene never leaves the top screen while you choose,
the highlight follows the D-pad, and the screen only changes once you have picked
something the game draws on the touch screen — the move list, the bag, the party.

Binary prompts ("… changer de Pokémon?") get a small `Oui / Non` box in the same window
instead of taking the screen.

**The ~1 s timeout is gone**, along with the D-pad/A trigger that raised the menu and the
guessing about intent that came with it. Nothing is timed any more.

### The labels are the game's own words

Pulled out of the ROM being patched and rasterised at patch time
(`onescreen/labels.py`) — `msg_0197` for the strings, the game's own font for the glyphs.
A French build says ATTAQUE / SAC / POKéMON / FUITE, an English one FIGHT / BAG / POKéMON
/ RUN, from the same code. At runtime the hook only copies finished tiles into VRAM the
game has already allocated: no font, no heap, no call into game code.

### Field yes/no questions stay on the world

Nurse Joy's offer, and every other field script that uses the shared green two-button
controller, now keeps the overworld on the top screen. `Oui / Non` or `Yes / No` appears
in the right-hand end of the existing dialogue window and follows the game's live
selection; the game still owns Up, Down, A, B and the result passed back to the script.

This controller also owns longer lists. Only its binary states are drawn: setup and
teardown keep the world visible, while PC options, shops and multichoice states still
raise their full lower-screen UI. Every pointer in the controller chain is range-checked
and verified through two `FieldSystem` back-references; an unexpected layout falls back
to the old screen swap instead of drawing or dereferencing arbitrary memory.

The field prompt aliases the existing language-neutral battle yes/no tiles, so it adds a
new layout without storing another copy of the images.

### Post-evolution move questions stay beside the Pokémon

The two-button screen shown after an evolution asks first whether to forget a move and,
when necessary, whether to stop trying to teach it. Both questions now keep the evolution
scene on top and draw the same localized `Oui / Non` or `Yes / No` labels in the existing
dialogue window.

This is not the field controller: it is an ARM9 state machine owned by the evolution task.
The patch validates the active VBlank callback, its task-data argument, the `BgConfig`, the
live `Window` and its exact 27×4 geometry before drawing. Setup defaults to Yes; active and
confirmation frames mirror the native 1/2 selection. Any unexpected pointer, geometry,
state or selection fails closed without writing VRAM.

Up, Down, A and B remain entirely native, including B selecting and confirming No. The
new layout aliases the battle yes/no geometry and image data, so no translated strings or
tiles are duplicated.

### Oak's speech answers on his own screen

The questions at the start of a new game no longer take the screen. **GARÇON / FILLE**
appears beside Oak's text for the gender question, **OUI / NON** for the gender and name
confirmations, and the highlight follows the game's own cursor.

Laid out the way each question is actually read: the gender options side by side, because
`OakSpeech_GenderSelectHandleInput` moves on left and right, and the confirmations stacked,
because they go through the generic multichoice handler on up and down.

The words come from the ROM like the battle ones — `msg_0286` for boy and girl, `msg_0219`
for Oak's own yes and no — so this stays language-neutral.

The selected band is no longer neutral grey. While a question is active, palette index 12
of Oak's dialogue borrows the intro's own edition colour: blue/silver in SoulSilver and
gold in HeartGold. Normal text retains Oak's original ink, shadow and paper indices.

The brief lower-screen indicator flash before each custom prompt is also fixed. Oak's
messages contain a `{YESNO 0}` text control, and the asynchronous text printer used to
render it after the hook's VRAM wipe. The hook now suppresses that exact control in Oak's
validated live message string before it reaches the printer; tutorial text and other text
controls are untouched.

Only two swaps remain in the intro: the naming keyboard, which genuinely needs the touch
screen, and the tutorial menu, whose three options of running text will not fit beside the
question. The gender flow used to swap for its whole state range, which flipped the screen
back and forth through the fades between prompts; that is gone.

### The overworld menu is drawn on the world

**X** no longer takes the screen away. The menu appears as a panel in the top-right corner
of the world — two columns of four, the same grid the touch menu uses — and the highlight
follows the D-pad, including left and right jumping between the columns. Sub-menus are
unchanged: pick `SAC` and the bag opens on the top screen exactly as before.

The grid is fixed and entries you have not earned leave their slot **empty**, which is what
the touch menu does — early on, `SAC` sits alone in the left column with `DRESSEUR`,
`SAUVER` and `OPTIONS` down the right. Availability comes from `inhibitIconFlags`, the
game's own answer, so the panel matches the touch screen entry for entry.

The Safari Zone, the Bug Contest and Pal Park use a different arrangement that cannot be
reproduced from outside the touch overlay; those are detected and still swap the screen,
rather than being drawn wrong.

`DRESSEUR` stands in for the trainer-card row, which on the touch screen shows your name:
the game expands that at runtime from a placeholder, and patch-time rasterisation cannot
know it. The word is still the ROM's own — `msg_0282` entry 5, `TRAINER` in English.

This is the first thing the patch draws with **no window to borrow**. Battles and Oak's
speech both wrote into a message window the game had already created; the overworld has
none, so this writes a tilemap as well as pixels. It needs no display registers touched at
all, because `MAIN_3` is already priority 0 and the 3D world is BG0 at priority 1.

Highlighting costs no pixels either — the selected cell's tilemap entries are written with
a different palette number, the same trick `ov27_0225B398` uses on the touch screen. One
finished image per highlighted entry would have been 32 KB against 11 KB of free ITCM.

### The shop and the PC menus are drawn on the world

Four menus now appear as a panel in the top-right corner instead of taking the screen,
and the screen only changes when you pick something:

| menu | entries |
|---|---|
| Shop | `ACHETER / VENDRE / QUITTER` |
| PC — which PC | `PC DE LEO / MON PC / PANTHEON / DECONNEXION` |
| PC — your own | `BOITE AUX LETTRES / CAPSULES BALL / ALBUM PHOTO / ETEINDRE` |
| PC — storage | `DEPOSER / RETIRER / DEPLACER POKéMON`, `DEPLACER OBJETS`, `SALUT!` |

They are all the same object underneath, so one renderer covers them: a script builds the
menu, the touch controller renders it, and the controller points back at it. The storage
menu is drawn as the 2×3 grid it really is, two lines to an entry, rather than as a list.

`MON PC` is the one label in the patch that is not the ROM's own words — the game builds
that row from a placeholder and your name, so there is nothing to extract. French and
English are written out; any other language falls back to the trainer card's word, which
does come from the ROM.

### The tile pool is compressed

Everything drawn now travels through an LZ77 variant that works in 32-bit words, so the
decompressor writes VRAM with plain word stores — DS VRAM ignores byte writes, and a
byte-granular decoder would have had to buffer half-written halfwords and read its own
output back.

It more than pays for itself: the label blob went from 24936 bytes with three menus to
18256 with four, and the payload is now **smaller than before any of this work started**
while doing considerably more. The all-paper "wipe" images are no longer stored either —
3840 bytes of `0xFF` that the hook now fills.

A menu is only drawn if the patch **recognises** it, by its entry count and the characters
of its first entry — message ids do not survive to runtime. Anything else swaps, as it
always did, so an NPC choice the patch has never seen can never come up with the wrong
words on it. `docs/FINDINGS.md` lists the other menus that could be added the same way.

### Behaviour fixed along the way

- The bag and party open on the top screen the first time, not the second — they run as
  overlay 8 and leave the menu id on the root menu, so the overlay id is checked first.
- The highlight no longer flashes back to `ATTAQUE` when you confirm, or after a trip
  into the bag: it is frozen at the moment you press A.
- Mashing A through the battle intro no longer pins the menu, because the game's menu id
  says no menu is open yet.
- Oak's obsolete lower-screen focus indicator no longer flashes immediately before the
  custom gender and confirmation choices.
- **L + R** in battle holds until the menu you are on changes, rather than being undone
  on the next frame.

### Notes

- Region-neutral like the rest: every address is derived from the ROM, and the struct
  offsets are code-derived so they do not move between regions. Verified against IPGF,
  IPKF and IPKE.
- Payload grows from 1452 to 26248 bytes of the ~31 KB of free ITCM.
- The X menu's panel sizes itself: the cell width comes from the widest translated label,
  so the French build is 18 tiles across and the English one 16, and the patcher refuses
  rather than clipping a language whose words do not fit.
- The earlier field yes/no attempt followed `ListMenu2D` and was abandoned. Tracing
  `GetMenuChoice` into overlay 27 exposed the real custom controller; the failed paths and
  the resolution are both preserved in `docs/FINDINGS.md`.

## v0.1b — first public release

Playable start to finish on French SoulSilver and HeartGold.

### What the patch does

- **80 of 87 display-routing sites** rewritten so menus and UI land on the top screen.
  The seven left alone are deliberate: two shared ARM9 helpers, the battle system's own
  site, and the four belonging to the stylus-only screens.
- A **resident hook in unused ITCM** (~1.4 KB of the 31 KB free) for everything that has
  to change while you play.

### Behaviour

- **Battles** — the scene keeps the screen so you can read what happened; the command menu
  comes up on the D-pad or A, steps aside after ~1 s, stays put once you have selected
  something, and hands the screen back the instant you confirm a move. Item lists, the
  party list and the bag sub-screens follow.
- **Overworld menu** — X brings it up, B or X puts the world back. Presses the game
  ignores (on a ladder, mid-cutscene) no longer swap the screen.
- **Field script menus** — shop lists, NPC choices and the PC option list.
- **Pokédex** — the species grid, and the area map on a Pokémon's detail level.
- **PC box** — the option list and the box itself, for both Pokémon and items.
- **Flying, Dig, Escape Rope** — the animation is on screen from the moment you confirm.
- **Evolution** and any move it teaches.
- **New game** — Oak's speech, the tutorial menu and the gender picker.
- **Name entry** — the keyboard.
- **L + R** swaps manually anywhere, as an escape hatch.

### Compatibility

Region support is derived from the ROM rather than tabulated: the patcher finds code by
instruction shape, reads the addresses it needs out of the ROM's own literals, measures the
region shift twice from independent places, and refuses to build if they disagree. Every
hardcoded ARM9 address is checked against a byte signature and dropped if the code does not
match.

| game code | game | status |
|---|---|---|
| `IPGF` | SoulSilver (France) | play-tested |
| `IPKF` | HeartGold (France) | play-tested |
| `IPKE` | HeartGold (USA) | resolves correctly; battles not play-tested |

### Known limitations

- The trainer-card signature, the Ruins of Alph puzzles and the Pokéathlon stay on the
  touch screen. They genuinely need the stylus and cannot be fixed by rerouting.
- 19 applications inherit their routing rather than setting it; three were wrong and are
  handled, the rest are untested. See `docs/AUDIT.md`.
- US battles have not been played.
