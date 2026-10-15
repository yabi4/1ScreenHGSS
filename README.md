# 1ScreenHGSS

Play **Pokémon HeartGold / SoulSilver** on a single screen.

![The overworld menu drawn onto the world, in the HeartGold theme](docs/img/menu.png)

*The top screen on its own. The menu is **drawn onto the world**, in the game's own words
and font — nothing is swapped in from the touch screen — and takes its colours from the
theme you choose when patching.*

> **v0.2b** — playable start to finish on French SoulSilver and HeartGold, and
> play-tested on US HeartGold. See
> [Compatibility](#compatibility) and [Status](#status).

The DS puts half of HGSS on the touch screen — the bag, the party, the Pokédex, and
critically the battle command menu. That makes the game awkward on a handheld like the
Steam Deck, where you want one screen filling the panel. This patch reroutes the game so
that whatever you actually need is on the **top** screen, automatically.

Mostly this is rerouting, not redrawing. The DS has two independent 2D engines, and
`POWCNT1` bit 15 decides which one drives the upper LCD; the patch rewrites the ~87 places
the game sets that, and adds a small resident hook for the cases that need to change while
you play.

The exceptions are the battle command menu, binary questions in the overworld, the
questions Oak asks at the start of a new game, the overworld menu, and the shop and PC
menus. They are drawn onto the scene rather than swapped in. Even there nothing is
replaced: the labels are the
game's own words in the game's own font, pulled out of the ROM you supply and rasterised
at patch time, so a French build says ATTAQUE / SAC / POKéMON / FUITE and an English one
FIGHT / BAG / POKéMON / RUN without the patcher knowing which is which.

|  | on the top screen |
|---|---|
| Overworld | the world (unchanged) |
| Bag, party, Pokégear, main menu, trainer card, options | their UI |
| Pokédex | the species grid, and the **area map** on a Pokémon's detail level |
| PC box | the box itself — moving Pokémon, item storage |
| Shops and the PC | their menus **drawn on the world**; the screen only moves when you choose |
| Field binary questions | the world, with **Yes / No** drawn in the dialogue window |
| Field lists | longer NPC choices — their UI |
| Overworld menu (**X**) | the world, with the menu **drawn on it**; **B** closes it |
| Name entry | the keyboard |
| New game | Oak's speech, with his questions answered on his own screen |
| Flying, Dig, Escape Rope | the animation, from the moment you confirm |
| Evolution | the Pokémon, its move-learning text, and compact **Yes / No** choices |
| **Battles** | the scene, with the commands drawn on it; the screen only moves once you choose |

Battles are the interesting part. The scene never leaves the top screen while you are
choosing: **FIGHT / BAG / POKéMON / RUN are drawn onto it**, laid out the way the game's
own cursor moves, and the highlight follows the D-pad. The screen only changes once you
have actually picked something — the move list, the bag and the party come up then, and
the scene returns the instant the turn starts. Binary prompts ("… changer de Pokémon?")
get a small **Oui / Non** box in the same message window instead of taking the screen.

Nothing is timed: there is no delay to wait through and no press that moves the screen
out from under you.

Binary questions in the overworld work the same way. Nurse Joy's offer, and every other
field prompt that uses the shared two-button controller, keeps the world visible and puts
**Yes / No** or **Oui / Non** in the right-hand end of the dialogue window. Up and down
move the game's own selection; A and B keep their normal meanings. Longer lists such as
the PC options, shops and multichoice questions still take the screen because they need
the room.

The move-learning questions after an evolution use a separate controller, but receive the
same treatment. When the game asks whether to forget a move, or later whether to stop
trying to teach it, the Pokémon remains visible and the existing localized **Yes / No**
tiles mirror the game's own selection. The patch does not handle the buttons or result.

The overworld menu works the same way: **X** draws it in the top-right corner of the world
instead of taking the screen, laid out two columns by four because that is the grid the
game's own cursor walks. Picking an entry opens it on the top screen exactly as before.

**Shops and the PC** are drawn the same way — the clerk's `ACHETER / VENDRE / QUITTER`, and
all three of the PC's menus including its 2×3 storage grid. These are the same object
underneath, so one renderer covers them, but a menu is only drawn if the patch **recognises
it by its own words**. Anything it has not seen swaps as before, which is what keeps an
unknown NPC choice from ever appearing with the wrong labels on it.

Starting a new game works the same way. **GARÇON / FILLE** for the gender question and
**OUI / NON** for the confirmations are drawn beside Oak's text, so the screen stays on him
throughout — it only changes for the naming keyboard, which genuinely needs the touch
screen. The selected band takes the theme's colour, and the obsolete lower-screen
indicator is suppressed before it can flash.
The tutorial menu still swaps: three options of running text will not fit beside the
question the way two words do.

**L + R** swaps the screens manually at any time, as an escape hatch.

## Themes

Everything the patch draws takes its colours from one of three schemes — the menus on the
world, and the band behind whichever choice is selected:

| `--theme` | menus | selected choice |
|---|---|---|
| `classic` | white, like the game's own dialogue box | grey |
| `heartgold` | white with a gold tint and frame | gold |
| `soulsilver` | white with a silver tint and frame | silver |

![The three colour themes](docs/img/themes.png)

Colour only: nothing moves and no wording changes. The patcher picks the theme matching
your game, and you can override it.

## Requirements

- Your own dump of Pokémon HeartGold or SoulSilver (**French versions are the tested
  ones** — see [Compatibility](#compatibility))
- Nothing else, if you use `1ScreenHGSS.exe`
- To run from source: [Python 3.9+](https://www.python.org/) and
  [ndspy](https://github.com/RoadrunnerWMC/ndspy) — `pip install ndspy`

## Use

**Windows:** download `1ScreenHGSS.exe`, drop your ROM on the window and press Patch.
Nothing to install - it picks the theme to match your game, and you can override it.

**From source:**

```bash
python patch.py "Pokemon - Version Argent SoulSilver.nds" --theme heartgold
```

That writes `Pokemon - Version Argent SoulSilver-1screen.nds` next to it. Your original
file is never modified.

Then in your emulator show only the top screen — in melonDS,
`Config → Screen sizing → Top only`. Full setup notes and the complete control list are in
**[docs/USAGE.md](docs/USAGE.md)**.

Save files are ordinary battery saves and work on the unpatched ROM too, so you can move
between the two freely.

## Compatibility

| game code | game | status |
|---|---|---|
| `IPGF` | SoulSilver (France) | **play-tested** — the reference build |
| `IPKF` | HeartGold (France) | **play-tested**, including a fresh start through Oak's speech |
| `IPKE` | HeartGold (USA) | **play-tested** — the opening, the drawn menus and the themes |
| other `IPGx` / `IPKx` | HGSS, other languages | untested — good chance of working |

Nothing is hardcoded per region. The patcher finds the code it edits by *instruction
shape*, and every address the resident hook needs is resolved from the ROM being patched:
the game-state block is read out of the main loop's own literal, the overlay values come
from the overlay table, the Pokédex entry point is found structurally, and the battle
phase word is read from the overlay loader's own literal. Measured across French and US,
ARM9 **code** addresses are identical and only data shifts (US = FR − 0x20); the patcher
measures that shift twice from independent places and refuses if they disagree, rather
than emitting a subtly broken ROM.

If you try another language, please open an issue either way.

Diamond/Pearl/Platinum are **not** supported — different code, different overlays.

## Status

Everything below has been played through, not merely implemented: the overworld and its
menus, battles including sub-screens, the bag through every pocket, the party menu
including reordering and summaries, the Pokédex with its area map, the PC boxes for
Pokémon and items, the Pokégear's map, radio, phone and configuration, shops and NPC
choice menus, flying, Dig and Escape Rope, evolution and the moves it teaches, and a new
game from the title screen through Oak's speech to walking outdoors.

The drawn menus — the battle commands, the overworld menu, the shop's and all three of the
PC's — were each play-tested through several rounds of correction, as were the field and
post-evolution prompts, the opening cinematic, the move relearner and saving from the
overworld menu. The three colour themes were checked on both editions.

Notably that covers the bag, the party menu and the PC box, which are still raw assembly
in the decompilation — nothing but play could have cleared them — and the Pokégear, which
was the largest touch surface found anywhere in the audit.

Known gaps, in order of how likely you are to meet them:

- **19 applications set no display routing of their own** and inherit whatever is current.
  Four turned out to be wrong and are now handled — most recently the move relearner; the
  rest are listed in [docs/AUDIT.md](docs/AUDIT.md) and are untested. Berry pots, the
  apricorn box and the Pal Pad are the ones a normal playthrough will reach.
- **Three screens deliberately stay on the touch screen** because they genuinely need the
  stylus — the trainer-card signature, the Ruins of Alph puzzles and the Pokéathlon. These
  are not fixable: moving them up would make them visible but untappable.
- **The Safari Zone, the Bug Contest and Pal Park** arrange the overworld menu differently,
  in a way that cannot be reproduced from outside the touch overlay. The patch detects them
  and swaps the screen there rather than drawing something wrong.
- **Safari Zone, Bug Contest and first-rival battles** hand the command menu to the touch
  screen instead of drawing it, because their options are not FIGHT / BAG / POKéMON / RUN
  and the patch only has those four labels.
- **Oak's two questions flicker.** The band behind the selected choice alternates with the
  game's own highlight for the few seconds those prompts are up. Cosmetic, understood, and
  written up in [docs/FINDINGS.md](docs/FINDINGS.md); fixing it needs more invasive work
  than it is worth.

If you find a screen on the wrong side, a savestate makes it quick to diagnose —
see [docs/USAGE.md](docs/USAGE.md#troubleshooting).

## Button navigation

Touch is physically the *lower* LCD, so anything shown on top cannot be tapped — every
screen the patch moves up has to be fully navigable with buttons.

A source-level audit against the decomp found the Ruins of Alph puzzle to be the only
genuinely touch-only app it covers, and cleared everything else it covers. The bag, party
menu and PC box are raw assembly there and could only be cleared by playing them, which
has now been done. See **[docs/AUDIT.md](docs/AUDIT.md)** for the method, the results and
what is still unchecked.

## Development

The whole toolchain is here: ROM unpacking, the display-site scanner, savestate diffing,
build and emulator-driving helpers. `patch-gui.py` is the window; `tools/build_exe.py`
freezes it into the released executable and `tools/make_icon.py` draws its icon. See **[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)** to
get set up, **[docs/AUDIT.md](docs/AUDIT.md)** for the button-navigation audit and what
the decomp says about the game's own screen routing, and
**[docs/FINDINGS.md](docs/FINDINGS.md)** for the reverse-engineering
write-up — memory addresses, what each discovery was, and the dead ends, so none of it
needs rediscovering.

## Legal

This repository contains **no game data** — no ROMs, no save files, no extracted assets.
It is a patcher that operates on a dump you provide of a game you own. Pokémon is a
trademark of Nintendo / Creatures / GAME FREAK, who are not affiliated with this project.

Tooling is MIT licensed — see [LICENSE](LICENSE).

## Credits

Overlay identities come from [pret/pokeheartgold](https://github.com/pret/pokeheartgold),
whose overlay numbering matches the retail ROM. Struct layouts and the names in
[docs/DECOMP.md](docs/DECOMP.md) were checked against the full decompilation at
[ctrl-cheeb-del/pokeheartgold](https://github.com/ctrl-cheeb-del/pokeheartgold); it is used
as a reference only, and nothing from it is copied here. ROM handling uses
[ndspy](https://github.com/RoadrunnerWMC/ndspy). Built and tested against
[melonDS](https://melonds.kuribo64.net/).
