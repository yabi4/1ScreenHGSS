# Using 1ScreenHGSS

## Patching your ROM

### The easy way

Download `1ScreenHGSS.exe`, drop your ROM on the window (or click to browse) and press
**Patch**. Nothing else to install — no Python, no ndspy. The patched file appears next
to your original, which is never modified.

The theme is chosen for you from the game — HeartGold or SoulSilver — and you can pick a
different one before pressing Patch.

### From source

You need [Python 3.9+](https://www.python.org/) and ndspy:

```bash
pip install ndspy
```

Then, from the repository folder:

```bash
python patch.py "Pokemon - Version Argent SoulSilver.nds"
```

This writes `…-1screen.nds` alongside your file. The original is never modified.

Useful flags:

```bash
python patch.py mygame.nds -o soulsilver-1screen.nds   # choose the output name
python patch.py mygame.nds --theme heartgold           # colour scheme (below)
python patch.py mygame.nds --identify                  # just report what the ROM is
python patch.py mygame.nds --no-hook                   # static flips only, no toggle
```

`python patch-gui.py` opens the same window as the .exe, if you would rather run it
from source.

## Colour themes

Everything this patch draws — the menus on the world, and the band behind whichever
choice is selected — takes its colours from one of three themes:

| `--theme` | menus | selected choice |
|---|---|---|
| `classic` | white, like the game's own dialogue box | grey |
| `heartgold` | white with a gold tint and frame | gold |
| `soulsilver` | white with a silver tint and frame | silver |

The theme changes colour and nothing else: no menu moves, and no text changes.

`--no-hook` skips the resident code entirely: you get the screen flips for menus but no
automatic battle swapping, no X-menu handling and no L+R toggle. Only useful for
debugging.


### Save files

Save files are ordinary battery saves and are **not** touched by the patch. Name your
`.sav` to match the patched ROM (`soulsilver-1screen.sav`), and it will work on the
unpatched ROM too — you can switch back and forth whenever you like.

## Controls

| button | what it does |
|---|---|
| **X** | opens the overworld menu **as a panel on the world**; press again to close |
| **B** | closes it |
| **L + R** | swaps the screens manually, any time — except inside the PC box, which holds its own routing every frame; press B to leave first |

Everything else plays normally. You should rarely need L+R: the patch follows the game
rather than your button presses, so pressing X somewhere the menu cannot open (on a
ladder, mid-cutscene) does nothing, and using Dig or an Escape Rope from the menu hands
the screen back to the world by itself.

## What ends up on the top screen

**Automatically, all the time:**

| screen | on top |
|---|---|
| Overworld | the world (unchanged — as it should be) |
| Overworld menu (**X**) | the world, with the menu drawn in the top-right corner (below) |
| Bag | pocket tabs and item grid |
| Party | the Pokémon list |
| Pokédex — species grid | the grid |
| Pokédex — a Pokémon's detail level | **the area map** |
| PC box | the option list **and** the box itself — Pokémon and item storage |
| Field binary questions | the world, with `Yes / No` or `Oui / Non` beside the question |
| Field lists | the world: shops and the PC drawn on it, other NPC lists in the game's own top-screen window |
| Pokégear, main menu, trainer card, options | their UI |
| Name entry | the keyboard |
| New game — Oak's speech | his text, with his questions answered beside it (below) |
| Flying | the flight animation, from the moment you confirm the destination |
| Dig, Escape Rope, Teleport | the world, not the menu you set off from |
| Evolution, and any move it teaches | the Pokémon, the narration and compact `Yes / No` choices |

**In battle**, the scene stays up while you choose. The commands are drawn onto it:

| what is happening | on top |
|---|---|
| a turn is resolving | the battle scene |
| `Que doit faire …?` appears | the scene, with `ATTAQUE / SAC / FUITE / POKéMON` on it |
| you move the **D-pad** | the scene; the highlight moves with you |
| a yes/no question is asked | the scene, with a small `Oui / Non` box |
| you pick `ATTAQUE` | the move list |
| you pick `SAC` or `POKéMON` | the bag or the party |
| you confirm a move | the scene, immediately |

The commands sit in the right-hand end of the message window, which is otherwise empty —
`ATTAQUE` across the top, then `SAC`, `FUITE` and `POKéMON` along the bottom. That is the
arrangement the game's own cursor moves through, so the highlight tracks the D-pad
exactly; it starts on `ATTAQUE` because the game's cursor does.

There is no timing anywhere in this. Nothing steps aside after a delay, and no press
moves the screen out from under you — the screen changes when, and only when, you have
picked something the game draws on the touch screen.

**Binary questions in the overworld** stay on the world too. When Nurse Joy asks whether
to heal your Pokémon, `Oui / Non` or `Yes / No` appears at the right-hand end of her
dialogue. Use **Up / Down** to choose, **A** to confirm, or **B** to decline, exactly as in
the unpatched game. This applies to every field prompt that uses the same two-button
controller. Longer choices are covered below.

**After an evolution**, the questions about forgetting a move and giving up on teaching
it also stay beside the Pokémon. The small `Oui / Non` or `Yes / No` labels follow the
native selection. Use **Up / Down**, **A** and **B** exactly as before; the game still owns
the input and decides which branch to take.

**The overworld menu** is drawn on the world rather than swapped in:

| what is happening | on top |
|---|---|
| you press **X** | the world, with the menu in the top-right corner |
| you move the **D-pad** | the world; the highlight moves with you |
| you pick `SAC`, `POKéMON`, `POKéDEX`… | that screen, exactly as before |
| you come back from one | the world, with the menu still up |
| you press **B** or **X** | the world, menu gone |

It is laid out two columns by four, because that is the grid the game's own cursor walks:
up and down wrap **within a column**, and left and right jump between them. A single list
would have looked like the D-pad was broken, since DOWN only ever reaches four entries.

Entries you have not earned yet leave their slot **empty**, exactly as they do on the touch
screen — early in the game `SAC` sits alone in the left column with `DRESSEUR`, `SAUVER` and
`OPTIONS` down the right, and `POKéDEX`, `POKéMON` and `POKéMATOS` appear in their own
places as you unlock them. The list never shuffles.

**The Safari Zone, the Bug Contest, Pal Park and the Union Room** have their own menus, with
`ABANDON` first, or `CHAT` and `LOG` added, and it is drawn the way each of them arranges
it. The ball counts and the contest Pokémon that the touch screen shows beside it are not
drawn; they are not choices.

One difference from the touch screen: the trainer-card row reads `DRESSEUR` rather than
your name. The game fills that in at runtime from a placeholder, and the labels here are
rasterised when you patch, long before there is a save file to read it from.

**Shops and the PC** draw their menus in the top-right corner instead of taking the screen:

| where | on top |
|---|---|
| a shop clerk | the shop, with `ACHETER / VENDRE / QUITTER` on it |
| the PC, choosing which | `PC DE LEO / MON PC / PANTHEON / DECONNEXION` |
| your own PC | `BOITE AUX LETTRES / CAPSULES BALL / ALBUM PHOTO / ETEINDRE` |
| the storage system | `DEPOSER` / `RETIRER` / `DEPLACER POKéMON`, `DEPLACER OBJETS`, `SALUT!` |
| you pick any of them | that screen, exactly as before |

The storage menu is drawn as the 2×3 grid it actually is, two lines to an entry, so the
D-pad moves through it the way it looks.

`MON PC` is the one place the patch supplies a word of its own: the touch screen shows your
name there, and the game only builds that at runtime, long after the labels are rasterised.

**Every other list menu** — the day-care, the Name Rater, move tutors, fossil revival, the
apricorn juice stand and the many one-off NPC choices — opens in the **game's own top-screen
list window** over the world, with its own cursor, scrolling and help text. HGSS still has
the window Diamond and Pearl used for these, and it reads the same menu the touch screen
does, so the words are always the game's. **B** behaves as on the touch screen.

Lists whose entries are two lines tall — the Battle Frontier prize shops, the Game Corner's
TMs, the rankings, Pokéathlon course selection — still swap to the touch screen, because
the top-screen window draws one line per entry. To keep **every** list on the touch screen
as before, patch with `--touch-lists` (or tick *Old-style NPC lists* in the window).

**Starting a new game**, Oak's questions are answered on his own screen:

| what is happening | on top |
|---|---|
| Oak talking | Oak, as always |
| the tutorial menu (three options) | the menu — this one still swaps |
| `Es-tu un garçon?` | Oak, with `GARÇON` and `FILLE` beside the text, left/right |
| confirming your gender | Oak, with `OUI / NON` stacked, up/down |
| entering your name | the keyboard — the one deliberate swap |
| confirming your name | Oak, with `OUI / NON` |

The gender options sit side by side and the confirmations stack, because that is how the
game reads them: the gender question moves on left and right, the confirmations on up and
down. The highlight follows whichever the game's own cursor is on. Its selected band uses
the intro's own blue/silver colour in SoulSilver and gold in HeartGold. The small "look at
the bottom screen" indicator embedded in Oak's question text is suppressed, so it does not
flash immediately before the custom choices appear.

**L + R** still works during a battle. It holds until the menu you are on changes, so
backing out of the move list hands control back to the patch.

## Emulator setup (melonDS)

- `Config → Screen sizing → **Top only**`
- Turn integer scaling **off** so the single screen fills the panel
- Map **L** and **R** somewhere reachable — you should rarely need them, but they are the
  manual override
- Optionally bind melonDS's own `HK_SwapScreens` to a spare button as a second escape
  hatch; it works independently of the in-ROM toggle

On a Steam Deck, EmuDeck's melonDS works well with the same settings.

## Known limitations

- **Touch is physically the lower LCD.** Anything shown on the top screen cannot be
  tapped, so everything must be done with buttons. That is fine for battles, bag, party
  and menus, which are all button-navigable.
- **Three screens deliberately stay on the bottom** because they genuinely need the
  stylus: the trainer-card signature, the Ruins of Alph sliding puzzles, and the
  Pokéathlon. Press L+R to reach them.
- A **source-level** audit against the decompilation found the Alph puzzle to be the only
  genuinely touch-only screen it covers, and cleared everything else it covers as
  button-navigable. But 75 of 119 code overlays are still raw assembly there, including
  the bag, the party menu and the PC box, so that audit is a lower bound rather than a
  clearance — see [AUDIT.md](AUDIT.md).
- **19 applications set no display routing of their own** and simply inherit whatever is
  current. Most are fine; three of them (Oak's speech, the evolution scene, the fly map)
  turned out not to be and are now handled explicitly. The rest are listed in
  [AUDIT.md](AUDIT.md) and are the likeliest place for a remaining wrong screen.
- If a screen is on the wrong side, **L+R always works** as an escape hatch.

## Troubleshooting

**The patcher says my ROM is unrecognised.** Only the French dumps have been tested. The
patch still applies — it locates code by instruction shape, not fixed offsets — but please
report whether it worked.

**A screen is on the wrong side.** Press L+R, then please open an issue. Two things make
it far quicker to fix, and both are cheap:

1. a **screenshot** of both screens at the bad moment;
2. a **melonDS savestate** taken there.

With a savestate the cause is usually identifiable without guessing:

```bash
python tools/savestate.py hook mystate.mln
```

That prints the patch's own variables — which latch is set, what the game's task manager
is running — and it is how most of the awkward bugs in this project were actually found.
Reasoning without it produced several confident wrong answers.

**The game does not boot.** Check you patched a clean, un-trimmed dump — run
`python patch.py yourrom.nds --identify` and compare the SHA-1 with the README table.
