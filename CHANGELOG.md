# Changelog

## Unreleased

### Origin HeartGold

- **Origin HeartGold is supported.** 起源心金 v4.0.3 with the English patch
  1.0.0-rc8 is not a retail HeartGold build: hg-engine rebuilt it over the
  Japanese one, with its own overlays, its own battle engine and its own ARM9.
  The patcher now recognises it and patches it like any other build.
  `onescreen/origin.py` holds everything that is specific to that ROM, and
  every address in it is checked against the ROM being patched.
- **The battle commands are drawn on the scene, in the message window's right-hand
  columns.** Origin prints its prompt on one line where retail wraps onto two,
  so the window's right-hand columns are free - and that is where the commands
  go, in the same arrangement as in the retail build: FIGHT across the top line,
  BAG / RUN / POKéMON along the bottom. Origin moves its cursor in the same 2×3
  grid, so "up" from BAG lands on FIGHT above it, and the words mirror the
  touch buttons the player presses.
- **The highlight follows the game's own cursor.** Origin drives its command
  menu itself, with the D-Pad and A, and draws its own touch buttons on the
  bottom screen - so the hook does not drive anything and synthesises no
  input. It reads the cursor the game keeps and bands the word it points at.
- **The band behind the selected command no longer blinks out.** The band is
  palette 11's colour 12 - the salmon the battle scene keeps there - and the
  scene's own palette blink animates that colour through white every few
  frames, which hid the band about once a second. The hook puts the colour
  back every frame the menu is up.
- **The battle scene stays on the top screen while the commands are up.** Origin puts it
  there itself, so the battle overlay is not flipped and the hook never swaps the screens
  during the command menu. The words go onto the scene rather than replacing it.
- **The battle's touch UI takes the top screen, as it does in retail.** The move list, the
  bag and the party are drawn on engine B, and the retail build hands the screen over to
  them as soon as they open. Origin's battle overlay holds no display-routing site at all,
  so the game never swaps by itself and the hook does it: the moment the move list or the
  bag opens, the lower screen moves to the top, and the scene comes back when it closes.
- **The battle scene comes back after an item is used.** Using an item in a battle - a
  Poke Ball - used to leave the screen on engine B for the rest of the fight: the top
  screen kept showing the ball's throw animation while the battle scene lay on the
  bottom one. Origin keeps a flag for "a battle screen owns the screen", and it stays
  set after an item is used - the game throws the ball with the flag still up - so the
  hook believed it and never gave the screen back. The hook asks the battle's own state
  first now, and believes the flag only while there is no state to ask.
- **The field's yes/no prompts are drawn on the top screen, as in retail.** The two words
  YES and NO are mirrored into the world's message box on the upper screen, and the band
  follows the game's own selection. Origin keeps the retail offsets in the choice
  controller - measured live: the state byte, the FieldSystem pointer and the selected
  choice all answer where retail has them, and the choice menu's app id is 3 here as
  well. Verified against the unpatched ROM, which leaves the two boxes the game draws
  there empty.
- **The touch menu's special layouts are found.** Safari, Bug Contest, Pal Park, Union
  Room, Colosseum and Battle Tower are the game's own table, and Origin kept it byte for
  byte - but in overlay 28 rather than the retail build's 27, so the patcher did not see
  it and drew the normal layout alone. It is now looked for by its content, and all
  seven layouts are drawn.
- **The onboarding keeps the screen with the text on top.** In Origin the
  content warning, the intro text, the intro menu, Oak's dialog and the name
  entry draw their text on engine A, and the application that starts the
  onboarding raises engine A. The blanket flip inverted that one site, and the
  whole onboarding came up with the text on the touch screen. The site is now
  kept, so the onboarding runs at POWCNT1 `0x820F` - exactly as the unpatched
  build does - and the text is on the top screen from the content warning to
  the name entry.
- **Oak's questions are drawn in his own window, as in retail.** The three
  prompts the opening asks for - BOY / GIRL at the outfit picker, YES / NO
  under "So... you're a boy then?" and YES / NO under "Your name is ...?" -
  get their words drawn into Oak's dialog box on the top screen, in the same
  arrangement as in the retail build: BOY and GIRL side by side, YES and NO one
  above the other, and the band on the word the game's own cursor points at.
  Origin's Oak is not retail's Oak: it is the intro application of overlay 49,
  its exec is a data word inside that overlay rather than an ARM9 template, and
  its app object is eight bytes longer in front. The state numbers are the
  retail ones - 65 for the outfit picker, 69 for the confirmation - except the
  name question, which hg-engine pushed from 98 to 102.
  The window is retail's too, down to the tile it starts at: the same 27 tiles
  of MAIN_0, the same base tile 0x36D, the same character base 0x06018000 -
  measured live, the window's first glyph sits at 0x06018000 + 0x36D * 32 and
  paints the very first letter of Oak's line. The only difference is that
  Origin keeps its second line of text on screen while the outfit picker is
  up, so the boy/girl words stop after the first line instead of covering the
  whole window.
- **The name entry comes up on the top screen.** hg-engine rewrote the name
  entry: the list of outfits is an overlay application of its own, and the
  keyboard behind it is an ARM9 routine that is not retail's either - retail's
  name entry is a single ARM9 routine, and that routine is what the retail app
  table already sends to the top screen. The Origin app table now does the same
  for both of hg-engine's pieces: the outfit list with the name field, and the
  keyboard behind it, with the name field at the bottom of the screen and the
  keyboard on top, exactly where the retail build puts it.
- **The evolution prompt comes up on the top screen.** hg-engine moved the
  evolution code in the ARM9, but it kept it: the application's vBlank callback
  and the main-queue task that runs the move-learning screen are retail's own
  functions, byte for byte, at other addresses (the task at 0x020743C0, the
  pointer literal that starts it at 0x020743BC). The retail build takes that
  task over by replacing the literal, and so does this one - the address is a
  config field now, so the same payload serves both builds.
- **The overlay numbers are not the retail ones.** hg-engine renumbered the
  overlays: the Pokedex is overlay 5 here (retail: 18), the PC box is overlay 16
  (retail: 14), the flight map is overlay 92 (retail: 101) and Oak's application
  is overlay 49 (retail: 53). The numbers are not guessed - hg-engine rewrote the
  overlay code but kept the large data tables, so the overlay that still holds a
  retail overlay's bytes is that application, and `tools/ov_map_all.py` prints the
  whole map. A second, independent proof comes from the entry points: an
  `OverlayManagerTemplate`'s init/exec/exit pointers are offsets into their own
  overlay, and the same program keeps them in the same places - retail's PC box
  and Origin's have the very same three (`+0x0001`, `+0x006D`, `+0x0089`).
  `tools/ov_exec_offsets.py` prints that comparison. Origin's overlay 53 is
  retail's overlay 57, a different application, so the retail Oak hook is no
  longer installed here: it expects retail's `OakSpeechData` layout and would
  read a stranger's data.
- **The emulated tests run again.** The payload the repository ships listed
  only the routines whose name starts with `OneScreen_`, so the tests could not
  find the words they drive - they write the game's key state into the pad
  word, point the app callback at a test structure and read back what the hook
  made of it. Forty-five of the fifty-eight tests died on a missing symbol
  before they ran a single instruction. Every global symbol is in the symbol
  table now, and the words the tests poke are exported: all 58 pass - 57 with a
  stock Python, and the one that needs the ARM assembler on `PATH` in the Linux
  CI.
- **The field dialogue and the Pokemon Center work in Origin too.** The nurse's
  dialogue and her YES / NO question are on the top screen in the Pokemon
  Center as well, and the application the counter's machine starts comes up on
  the top screen with this patch and on the bottom screen without it - checked
  against the unpatched ROM with the same walk.
- **The PC box works in Origin too.** The box in the Pokemon Center opens on the
  top screen, with its option list and its grid where the retail build puts
  them. hg-engine renumbered the overlays, so the take-over that used retail's
  overlay 14 now points at Origin's overlay 16 - the same application, proved
  twice: by the data blocks the two overlays share and by the entry points of
  their `OverlayManagerTemplate` (`tools/ov_exec_offsets.py`).

## `V0.3`

Built against the full decompilation of HeartGold/SoulSilver
([ctrl-cheeb-del/pokeheartgold](https://github.com/ctrl-cheeb-del/pokeheartgold)), which
appeared after v0.2b. It confirmed almost every offset this patch had measured from the game,
and corrected a handful. `docs/DECOMP.md` has the cross-reference.

### Battles

- **The Safari Zone, the Bug Contest, Pal Park and the first rival battle draw their own
  commands on the scene** - BALL / BAIT / MUD / RUN, BALL in place of BAG, BALL above RUN,
  and FIGHT alone - in the game's own words, where they used to be drawn as
  FIGHT / BAG / POKéMON / RUN (Safari, first rival) or handed to the touch screen. The words
  are chosen the way the game chooses them, by battle type.
- **A double battle's second Pokémon shows CANCEL**, as the touch screen does, instead of
  RUN.
- To make room, the command images are stored once, plain, with a rectangle per choice:
  the hook lays the band under the selected word itself. Every image it draws was checked
  byte for byte against the patcher's own rendering. A ROM whose words for one of these
  menus cannot be read just leaves that menu to the touch screen.
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
  savings) keeps the touch screen.
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

### L + R

- **L + R no longer lets one shoulder through to the game** (payload v36). The two keys
  rarely go down in the same frame, so the game acted on whichever came first, alone: a
  pocket change in the bag, a page in the Pokédex, and - under the *L=A* button mode - an A
  press, which in a battle chose FIGHT before the screens swapped. The patch now looks at
  the pad straight after the game reads it. A lone L or R is held back for three frames,
  about a tenth of a second: if the other arrives in that time it is the swap, and the game
  sees neither key until both are up; if not, the press goes through then, or at once if
  the key is let go first. Nothing else about the pad changes.
- The yes/no answers and Oak's gender question are stored like the battle commands now, one
  plain image and a band per choice, which made the room in ITCM this needed.

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
- `tools/testsaves/` builds play-test saves from a complete one with PKHeX.Core - today the
  evolution test - and puts back the RTC date PKHeX rewrites, re-checksumming the game's way.
- **The standalone patcher builds on macOS and Linux too** - an `.app` and a Linux binary
  beside the Windows `.exe` - each with a command-line build of `patch.py`.
  `.github/workflows/release.yml` builds all of them, for both kinds of Mac, and drafts a
  release for a `v*` tag, with `docs/release-notes/<tag>.md` as its text and every file's
  SHA-256 under it. The window no longer fails to open when tkinterdnd2 imports but
  its library cannot load (any Tk 9 Python): it opens without drag and drop.
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
