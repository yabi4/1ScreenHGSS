# 1ScreenHGSS — reverse-engineering findings

Target ROMs (user's own dumps, in `roms/`):

| file | gamecode | sha1 |
|---|---|---|
| `ipgf.nds` | `IPGF` — SoulSilver, France, rev 0 | `6ED98D446EB65861C71FC5F94BDC35691667F665` |
| `ipkf.nds` | `IPKF` — HeartGold, France, rev 0 | `DBA64620A959D5F69ED1CF3E43FCFCF2786D417E` |

## ROM layout

- ARM9: ROM `0x4000`, RAM `0x02000000`, stored size `0xBA378` (SS) / `0xBA370` (HG),
  **BLZ-compressed**, decompresses to `0x111F18` in both.
- `MODULE_PARAMS` at RAM `0x02000BA0` (file offset `0xBA0`), magic `0xDEC00621` at `+0x1C`:
  - `+0x08` autoload_start `0x02111880`
  - `+0x0C` static_bss_start `0x02111880`
  - `+0x10` static_bss_end `0x021E5920`
  - `+0x14` **compressed_static_end** `0x020BA378` → set to `0` to store ARM9 uncompressed
- Overlay table ROM `0xBE400`, **129 overlays**, all BLZ-compressed except ov35 / ov124.
  Overlays load from RAM `0x021E5920` — directly after ARM9 bss, so **ARM9 cannot be grown**.
- Filesystem: 513 files, opaque `/a/x/y/z` NARC layout.

## HG vs SS are nearly the same binary

This is the single most useful discovery — the patch is portable for free.

- Decompressed ARM9s are the **same length** and differ by **2184 bytes (0.195%)**;
  longest identical run 205,808 bytes. **ARM9 code is at identical addresses in both.**
- All **129 overlays have identical RAM bases**; **114 are byte-identical**.
  Overlay 10 (battle action select) is byte-identical. Overlay 12 (battle core) differs
  by 7 bytes. Only ov18 (89%) and ov74 (48%) differ substantially.

## Display routing

`POWCNT1` = `0x04000304`, **bit 15**:
- `1` = 2D engine A → **upper** LCD (stock: overworld, battle scene)
- `0` = 2D engine A → lower LCD, i.e. engine B (the touch UI) drives the **upper** LCD

The address can't be reached by a small immediate offset (ARM `STRH` imm is 8-bit, Thumb
5-bit; `0x304` exceeds both), so it always sits in a literal pool — which makes every use
site findable by scanning for the literal and then the PC-relative `LDR` that reaches it.

**110 reference sites** exist across ARM9 and 26 overlays. Classification:

| count | what it does |
|---|---|
| 42 | **sets** bit 15 (engine A → top) |
| 45 | writes POWCNT1 without touching bit 15 |
| 18 | loads the address, no store in window |
| 4 | ARM-mode, bit 0 = LCD power (`GX_DispOn` / `GX_IsDispOn` at `0x020DB6EC`, `0x020DB794`) |
| 1 | masked field write during boot graphics init (`0x0201A20A`) |

The game **re-asserts the stock routing at every app transition**, which is why an
external emulator/cheat swap does not stick across screens.

### The flip

The compiler builds the `0x8000` mask by shifting the address register itself
(`0x04000304 >> 11 == 0x8000`), giving a very recognisable idiom:

```
ldr  r2, =0x04000304   ; POWCNT1
ldrh r1, [r2]          ; current value
lsrs r0, r2, #11       ; r0 = 0x8000
orrs r0, r1            ; set bit 15          (0x4308)
strh r0, [r2]          ; commit              (0x8010)
```

To route engine B to the top instead we want `current & ~0x8000`:

```
bics r1, r0            ; 0x4381
strh r1, [r2]          ; 0x8011
```

**Two halfword edits per site. No new code, no hooks, no free space required.**
Register numbers vary per site, so `onescreen/sites.py` decodes each one and
computes the replacement encodings:

```
new_alu  = 0x4380 | (mask_reg << 3) | value_reg     ; bics rV, rM
new_strh = 0x8000 | (addr_reg << 3) | value_reg     ; strh rV, [rA]
```

**39 of the 42 set-sites decode cleanly** and are flippable, spread over ARM9 (4) and
25 overlays. Verified in melonDS: flipping all 39 boots at full speed and visibly moves
the touch UI to the top screen (`out/proof_swap.png`).

## Useful ARM9 addresses (identical in IPGF and IPKF)

| address | what |
|---|---|
| `0x02000CA4` | `NitroMain` |
| `0x02000DB0` | **main loop head** (back-edge `b` at `0x02000E46`) |
| `0x021D112C` | main state block (`r4` in the loop) |
| `0x021D1164` | `[r4+0x38]` processed held-keys mask, 1 = pressed (soft reset checks `0x30C` = L+R+START+SELECT) |
| `0x021D112C+0x00/+0x04` | current app callback + argument, dispatched via `blx` each frame |
| `0x0201A200` | boot graphics init (called once from `NitroMain`) |

These give a per-frame hook and an "which app is running" signal if dynamic swapping is
needed later (it is, for battles — see below).

## Overlay identities

From pret/pokeheartgold's `main.lsf`, which uses the **same overlay numbering as the
retail ROM** (verified: ov12 = battle system, ov1 = field). Only overlays containing a
flippable site are listed; see `onescreen/table.py` for the machine-readable table.

| ov | identity | v1 intent |
|---|---|---|
| 5, 15, 37, 56, 68, 71, 73, 82, 83, 85, 102, 108, 109, 113 | unidentified in the decomp | FLIP |
| 12 | **battle system** — commands, HP bars, input, cursors | **KEEP** |
| 17 | berry pots app | FLIP |
| 51 | trainer card — main interface | FLIP |
| 52 | trainer card — **signature (stylus drawing)** | **TOUCH** |
| 57, 59, 70, 72 | battle-related systems | FLIP |
| 74 | **main menu application** | FLIP |
| 80 | battle frontier | FLIP |
| 110 | **Ruins of Alph sliding puzzle (stylus)** | **TOUCH** |

**The field/overworld uses overlays 1, 2, 3 and 27 — none of which contain a flippable
site.** That is why blanket-flipping the overlays cannot disturb the overworld, and it
means the overworld's routing is established elsewhere (one of the 4 ARM9 sites, or
inherited from boot). The 4 ARM9 sites are left alone in v1.

## The two families, and the global display-select flag

Apps may draw their interactive UI on **either** engine and then route that engine to
the bottom screen. So there are two opposite idioms, and a correct patch must handle both:

| family | idiom | meaning | flip |
|---|---|---|---|
| **SET** (39 sites) | `lsrs rM,rA,#11` / `orrs` / `strh` | UI on engine B, bit15=1 → UI bottom | `orrs`→`bics` + change `strh` source |
| **CLR** (43 sites) | `ldr rM,=0xFFFF7FFF` / `ands` / `strh` | UI on engine **A**, bit15=0 → UI bottom | literal→`0x00008000`, `ands`→`orrs` |

v1 only handled SET, which is why the Bag flipped but the Pokédex/Pokégear did not.
The CLR literal is only rewritten when exactly one LDR in the module references it.

**Not every app sets POWCNT1 itself.** Many call a shared helper:

- **`0x02022D3C` — apply display select.** Reads a global flag byte and applies bit 15:
  ```
  ldr r0,=0x021D118C ; ldr r2,=POWCNT1 ; ldrb r0,[r0,#9]
  cmp r0,#0 ; bne .clear
  ... orrs (bit15=1, engine A top) ...
  .clear: ... ands 0xFFFF7FFF (bit15=0, engine A bottom) ...
  ```
  **Global flag byte: `0x021D1195`** (= `0x021D118C + 9`), initialised to 0 by the boot
  graphics init at `0x0201A30E`. Called from ~90 sites, **including ov001 (the field)**.
- **`0x02022D24`** — enables the sub engine's display (`DISPCNT_B |= 0x10000`), 33 callers.

Consequence: the field and several apps share this one helper and one flag, so no purely
static edit can flip one without the other. Apps that neither set POWCNT1 nor call the
helper simply **inherit** the field's routing — this is why the party screen stays on the
bottom no matter which sites are flipped.

Flipping the 4 ARM9 sites was tested (`out/ipgf-arm9only.nds`): it swaps the **overworld**
(touch menu on top, world below), confirming the field's routing is established there.
Excluding the boot-init site alone does not change that.

## Battle screen layout (confirmed in-game)

- **Top screen:** battle scene, both HP bars, **and the message box** ("Que doit faire
  KAIMINUS ?"). The plan's open question is settled — battle narration is on the top.
- **Bottom screen:** command buttons (ATTAQUE / SAC / FUITE / POKéMON), then the move list.

This confirms the swap cadence is viable: while choosing an action the top screen carries
only a prompt you don't need to read, and while a turn resolves the bottom menu is idle.

## Battle state, measured

At the rival battle's action-select menu (`out/ipgf-v4.nds`, rival save):

| what | value |
|---|---|
| app callback `[0x021D112C]` | `0x02239751` — inside **ov12** (`0x022378E0`..`0x0226EC60`) |
| `POWCNT1` | `0x820F` — bit 15 set, battle scene on top |
| `[0x0221BE40]` | `0xB082B5F8 0x20D51C06 0x1C0D9201 0x1C1A0080` |

Those four words are an **exact byte match for overlay 10** as stored in the ROM
(`tools/whichov.py` disambiguates the six overlays sharing that base: ov7, ov8, ov9,
ov10, ov63, ov65). So **ov10 is confirmed resident during action-select**, and the plan of
swapping on its load/unload is sound.

After the battle ends, `[0x0221BE40]` reads all zeros — the region is cleared on unload,
which means a residency check is viable in principle. Not yet confirmed for the
*mid-battle* unload (turn resolution), which is the case that actually matters.

### Hook point still to find

- `find_template.py 10` finds **no** OverlayManagerTemplate for ov10, so it is not launched
  through the app framework the way the menu apps are.
- `find_loader.py` (rank BL targets by variety of small r0 constants) produced false
  positives: `0x02037AC0` / `0x02037B38` turned out to be field/script state accessors on
  the struct at `*(0x021D416C)`, not overlay loaders.

Two options remain: find the real loader (a GDB breakpoint on the ov10 RAM range would
identify it directly), or poll ov10 residency per frame from the main loop at `0x02000DB0`
and call `OneScreen_SetSwap`.

## Testing note: reaching battles

Wild encounters could not be triggered by automation (100+ paced steps, no encounter). The
working approach is the user's save placed one step from the **rival battle** — walk right,
mash A through the dialogue. Deterministic and repeatable.

## Battles: solved with an in-ROM toggle (v5)

**ov10 is the trainer AI, not the menu.** The decomp lists `OVY_12` as owning "commands,
HP bars, input, cursors", so the action-select menu lives *inside* ov12 and there is no
overlay boundary to hook. ov10 merely happens to be resident across the turn, which made
it look like a usable signal. It is not.

*Later, with the full decompilation:* it is a usable signal after all, just not a hook
point. `BattleSystem_SetTrainerAIOverlayLoaded` swaps ov7 out for ov10 exactly when
command selection starts and back when every battler has chosen, which is why the
overlay-slot proxy described below tracks the phase so well.

What shipped instead: `OneScreen_Frame` in ITCM, reached by replacing the main loop's
`bl 0x0200110C` at **`0x02000DB0`** with a call to our code, which runs the original and
then polls the pad. **L+R toggles POWCNT1 bit 15.**

- Pad state is read from `0x021D1164` (1 = pressed); rising-edge latched in an ITCM word.
- `inject.py:patch_main_loop` asserts the site really holds `bl 0x0200110C` before
  patching, so a wrong address fails the build rather than corrupting the ROM. This check
  passes for **both** IPGF and IPKF, confirming the main loop is at the same address.
- The toggle persists until something else writes POWCNT1 — which is exactly right,
  because each app asserts its own routing on entry and **nothing re-asserts it mid-battle**.

Verified in the rival battle: L+R brings ATTAQUE/SAC/FUITE/POKéMON to the top screen, and
the move list (Griffe NORMAL PP 35/35, Groz'Yeux NORMAL PP 30/30, ANNULER) is fully
readable and D-pad navigable there. Turn resolution keeps the swap, so it is two presses
per turn.

## Savestate diffing (works well — use this, not GDB)

`tools/savestate.py` locates the 4 MB main-RAM block inside a melonDS savestate by
searching for the first bytes of `build/<code>/arm9_dec.bin` (main RAM starts at
`0x02000000` and the ARM9 static section is loaded there verbatim). Main RAM sits at file
offset `0x24` in melonDS 1.1 states. This sidesteps both GDB limits entirely.

Diffing `ipgf-v5.ml1` (action-select) against `ipgf-v5.ml2` (turn resolution), same battle,
same run: 93,834 differing bytes overall, but only **43 bytes** inside
`0x022C0000..0x022C1000`, and the interesting one is a 70-byte region at `0x022C0556`
that goes from **all zeros to structured data**:

```
ml1  0x022c0554:  0x00000000 0x00000000 0x00000000 ...
ml2  0x022c0554:  0x00040000 0x00000001 0x00040002 0x0225000e ...
```

That is battle context + `0x2E8` (context base `0x022C026C` in that run). It reads as a
battle script / text-command queue that fills as the turn plays out.

**Candidate rule:** `ctx = *(u32*)0x021D1130; action_select = (*(u32*)(ctx + 0x2E8) == 0)`.

### Critical constraint

The battle context is **heap-allocated and its address changes between runs** — measured
`0x022C026C` in the savestates and `0x022C02B0` in a later launch. Any detection must
dereference `0x021D1130`; a hardcoded `0x022C05xx` is meaningless. (This also invalidated
one probe: the fixed window read the wrong offset once ctx shifted by `0x44`.)

### Result: rejected

A third savestate (`ml3`, turn 2 action-select, same run, same context `0x022C026C`)
showed that region **byte-identical to `ml2`**. The queue is cumulative, not per-turn, so
the rule would have worked on turn 1 only.

## Triangulation, and why the second candidate also failed

Three states make a much better filter than two: with `ml1` and `ml3` both at
action-select and `ml2` mid-turn, a genuine state variable satisfies
**`ml1 == ml3` and `ml2 != ml1`** — anything that merely counts, accumulates or animates
differs between `ml1` and `ml3` too. `tools/savestate.py triangulate` implements this.

It surfaced candidates at **fixed ARM9 BSS addresses** (no heap pointer chasing needed),
the cleanest looking being `0x021DD440`: `0` at both menus, `1` during resolution.

**It is a coincidence.** Probed live at a turn-1 action-select it reads **`1`**, where the
savestate had `0`. The reason is simple arithmetic: **68,535 bytes** satisfy the
three-state constraint, so false positives are guaranteed. Three samples is not enough
evidence, however clean a byte looks.

**What would actually work:** repeat the triangulation across **several different
battles** (different opponents, different turns, ideally a wild battle and a trainer
battle) and intersect the candidate sets. A real state variable survives every
intersection; coincidences die fast. That needs ~6 savestates rather than 3.

The auto-swap code is written and gated behind `build.py --auto-battle`
(`--defsym ENABLE_AUTO_BATTLE=1`), **off by default**, so the shipped build is the
verified manual-toggle one. Only the state byte is wrong; the surrounding design — gate
on the app callback being inside ov12, edge-trigger so a manual override survives — is
sound and reusable once a real state variable is found.

## Automatic battle swapping: SOLVED

`BATTLE_STATE = 0x021E17C4`, a fixed ARM9 BSS address. **1 = awaiting the player's
command, 2 = turn executing.** A second copy at `+0x2C` behaves identically, which is what
a per-battler state array looks like.

How it was found, after two failed guesses:

1. **Groups, not pairs.** Savestates from **three different battles** — five "waiting"
   states (including the move-select submenu) against three "executing" states. A real
   state variable is constant within each group and differs between them, across
   different opponents and turns. `savestate.py intersect` does this.
2. **Reject heap churn.** That still left 61,188 bytes, because whole blocks read as fill
   (`0xAB`/`0xBB`/`0xFF`) while idle and as allocated data mid-turn — a perfect
   correlation that is useless. Two filters fixed it:
   - both values must be small (`<= 32`) — state enums are, fill bytes are not
   - the byte must be **isolated** (no other hit within 8 bytes) — a state variable sits
     alone; heap blocks change in long runs

   **61,188 → 11**, of which 5 were at fixed (non-heap) addresses.
3. **Confirm live.** All 5 survived a GDB probe in a *fourth* battle that was not in the
   sample. `0x021E17C4` was chosen for the cleanest semantics.

### Returning from a submenu (v15)

Two bugs of the same shape — coming *back* to a root menu:

- **Battle.** `bt_committed` is set by A and was only cleared on a phase change, so once
  you had been into the move list or bag the idle timeout never re-armed and the menu
  stayed up forever. **B now clears the commit**, since B is exactly "go back a level".
- **Overworld.** Entering a sub-app (party, bag, Pokédex) cleared `menu_swapped`, so on
  return the X menu was still open but we had forgotten we swapped for it — and the field
  re-applies its own layout on re-entry, putting the menu back on the bottom. The latch is
  now **kept** across sub-apps and the routing re-applied every frame while the menu is
  open. It is still dropped on entering a **battle**, where the battle logic owns the
  screens.

### Sub-screens opened from the battle menu (v14)

The bag and party opened *from inside a battle* stayed on the bottom. Two separate causes,
both worth recording:

1. **The state variable was conflating two situations.** `0x02111930` reads `0x06` both
   when a command is confirmed *and* while a sub-screen is open, so the code decided the
   turn was executing and threw the scene back on top. `0x021D0E28` distinguishes them
   (`0x08` sub-screen vs `0x07` confirmed) — see the constant block in `src/hook.s`.
   Testing it **negatively** (`!= 0x07`) also covers waiting sub-states we never
   enumerated, which is what broke the earlier `== 0x0A` test.
2. **A one-shot swap is not enough.** Those sub-screens re-assert the display routing
   themselves as they open, undoing our swap. The routing is now **re-applied every frame**
   while the menu is up. L+R clears `bt_menu_up` so a manual override is still not fought.

Note the raw state is collapsed to a single "executing" bit *before* the
transition check. Without that, moving between waiting sub-states (`0x0A` → `0x08`) counts
as a phase change and resets the interaction state, dropping the menu the instant you
open the bag.

Verified: bag category screen, item list and party list all render on the top screen
inside a battle.

### Picking the right one of the five: timing matters (v12)

The five surviving candidates all agree on *what* the phase is, but not on *when* they
change. Probed 150 ms after confirming a move:

| candidate | value | |
|---|---|---|
| `0x021E17C4` | still `1` (menu) | **late** — only flips once the turn machinery starts |
| `0x02134F15` | still `0x02` | late |
| `0x021E17F0` | still `1` | late |
| `0x021D0E28` | already `0x07` | early |
| `0x02111930` | already `0x06` | early |

A late variable makes the swap look wrong: the text and animation are already under way
before the screen changes.

`0x021D0E28` was tried and **rejected** — it is too fine-grained, taking at least three
values inside a battle (`0x0A`, `0x08`, `0x07`). A single "is it the menu" comparison
misses sub-states, and the menu silently stops appearing.

**`0x02111930` is the one in use:** `0x07` through every awaiting-a-command state
including the move list, flipping to `0x06` the instant a command is confirmed. It also
reads `0x07` outside battle, which is harmless because everything is gated on the app
living in overlay 12.

> **Out of date — read the later section.** This conclusion was reversed. `0x02111930`
> conflates "command confirmed" with "a sub-screen is open" (both `0x06`), which broke the
> bag and party. What ships is `0x021D0E28`, rejected above for being too fine-grained and
> then re-adopted with a *negative* test (`!= 0x07`) rather than a positive one, which is
> what makes the extra values harmless. See *The battle phase word* below for the account
> that matches the code.

Also worth recording: **do not try to guess which A press confirms the command.** An
attempt to fire on "the second A" swapped away from the move list, because the number of
presses varies with whether the cursor was moved first, backed out with B, or SAC/POKéMON
was chosen. The state variable already flips on confirmation — let it do the work.

### On-demand, not forced (v9)

Swapping the moment the game asks for an action turned out to be the wrong call: it hides
the battle scene exactly when you want to read the result of the last turn. The menu now
comes up only when you reach for it.

| condition | top screen |
|---|---|
| phase 2 (turn executing) | battle scene, forced |
| phase 1 entered | unchanged — deliberately no swap |
| D-pad or A newly pressed | command menu |
| `IDLE_FRAMES` (60 ≈ 1 s) with no input, uncommitted | battle scene |
| A pressed | committed: timeout disabled, menu stays |

A is a trigger as well as the D-pad because the cursor starts on ATTAQUE — pressing A
without moving first would open the move list unseen on the bottom screen.

All five behaviours verified in-game on a live trainer battle.

> **Superseded.** This whole state machine was removed on `beta-ui`. The commands are
> drawn onto the battle scene now, so there is nothing to raise and nothing to time out —
> see *Drawing the battle command menu* below. Kept because the reasoning about *when* the
> screen should move is still the reasoning that applies.

The lesson worth keeping: **three savestates from one battle is not evidence.** 68,535
bytes passed that test and the one that looked cleanest was still a coincidence.

### The A press that pinned the menu

Reported from play: mash A to skip the battle intro and the command menu comes up
immediately and then never times out — the only way to get the scene back was to go into a
submenu and press B.

`bt_committed` was the cause. It exists so the move list does not vanish while you read it,
and it was set by *any* A press while awaiting a command, cleared only by B or a phase
change. But "awaiting a command" is really "overlay 10 is resident"
([see above](#the-battle-variable-identified)), and overlay 10 loads while the intro text
is still playing. So an A press eaten by the text set a commit for a menu that did not
exist yet, and nothing later cleared it.

The fix is to make the rule mean what it says: **A is a selection only if there was a menu
on screen to select from.** An A press with no menu up just brings the menu up, exactly
like the D-pad. A second A — now with the menu visibly up — commits.

Belt and braces on top of that, the timeout is also suppressed whenever the phase reads
`8` (a sub-screen is open), because browsing the bag or the party is exactly where long
pauses are legitimate. That comes from the game's own state, so it holds even when the
commit flag is wrong.

The residual case: press A once from the battle scene, then sit reading the move list for
over a second, and it will step aside. Any button brings it straight back.

## Pokédex area map — solved with the decomp, after RAM diffing failed twice

Wanted: at the per-Pokémon detail level, put the **area map** on the top screen, but only
there — not on the species grid. They share one app callback (`0x021E5C5D`, inside ov18)
and both read `POWCNT1 = 0x820F`, so `app_table` cannot separate them.

**Two RAM-diff candidates were tried and both were noise:**

| candidate | savestates said | live reality |
|---|---|---|
| `0x02111930` | `0x06` grid / `0x07` detail | reads `0x07` **at the grid too** |
| `0x021E3E8B` | `0x04` grid / `0x02` detail | `0x04` at the grid once, `0x02` at the grid later |

Both are transient globals that merely happened to be settled when the savestates were
taken. Intersecting four savestates still left 159 isolated candidates — far too many.

### What actually worked

pret/pokeheartgold has the Pokédex decompiled (`src/application/pokedex/`), which gives the
real structure instead of a guess:

```c
struct OverlayManager { OverlayManagerTemplate template;  // init/exec/exit/ovy_id
                        int exec_state;                   // +0x10
                        int proc_state;                   // +0x14
                        void *args; void *data; ... };
```

and `OverlayManager_Run` calls `template.exec(man, &man->proc_state)`. **The screen level
is `proc_state`, handed to the app every frame.** Searching RAM for an OverlayManager with
`ovy_id == 18` confirmed it:

| level | `proc_state` |
|---|---|
| species grid | **11** |
| detail level (area map) | **69** |

Consistent across four savestates covering two different Pokémon, and `69` has its own
struct in the decomp (`PokedexAppData_UnkSub0868_State69`), which corroborates it.

### Reaching it at runtime

The manager is heap-allocated and no fixed global points at it (checked two levels of
back-references — all heap). So instead of chasing pointers, the patcher **takes over the
`exec` pointer** in the Pokédex's `OverlayManagerTemplate`, which lives in ARM9 *static*
data. The framework then calls our trampoline with `r1 = &proc_state`, and it tail-calls
the real exec. No pointer chasing, no per-frame scanning.

The template is located **structurally** — three pointers into overlay 18 followed by the
id — so it is region-independent. Exactly one match per ROM:

| ROM | template | exec |
|---|---|---|
| SoulSilver FR | `0x020FA268` | `0x021E5B81` |
| HeartGold FR | `0x020FA268` | `0x021E5B85` |
| HeartGold US | `0x020FA284` | `0x021E5B65` |

Verified in-game: the area map renders on the top screen, and backing out restores the
species grid. This technique generalises to any OverlayManager application.

### The fade-in flash, and why 69 alone was the wrong rule

Swapping on state 69 made the map fade in on the **bottom** screen and then jump across
once it was fully visible. The menus never did that, so the difference was worth chasing.

69 is not where the map is built. `PokedexApp_MainSeq_68` builds it, starts a fade in
**from black**, and returns `MainSeq_03` — the shared "wait for the palette fade" state,
which loops back to whatever `unk_085C` names. Only once the fade has finished does 68
return 69. So the entire visible fade-in happens under states **68 and 03**, and swapping
at 69 was swapping *after* the animation the player was watching.

Two corrections came out of that:

- **The map screen is a state range, not just 69.** 69 is the idle screen, 70 fades back
  out, and 71–75 handle scrolling between maps and the sub-interactions — every one of
  them returns to 69. 76 begins the next tab.
- **02 and 03 are shared fade waits reached from both sides**, so they say nothing about
  which screen is up and must not be read as "not the map". They hold the current routing.

### …and why 68 alone still flashed

Acting on 68 was still wrong, and play-testing caught it: the flash got shorter but did
not go away. **Which state builds the map depends on how you arrived.**

| route | states |
|---|---|
| from another tab | 91 (or 78 / 81) fades out → 03 → returns **68** |
| from the species grid | 64 / 15 fades out → 03 → returns **66** |

and `MainSeq_66` does its own setup and then **tail-calls `PokedexApp_MainSeq_68` directly**:

```c
static int PokedexApp_MainSeq_66(PokedexAppData *app) {
    ...
    return PokedexApp_MainSeq_68(app);
}
```

So on the grid route the map is built and the fade started while `proc_state` still reads
**66**, and the value 68 never appears until the fade has already finished — which is
precisely the frame we were swapping on. Hence the range starts at 66. Both routes into 66
come after a fade to black (one also calls `ZeroPalettesByBitmask`), so swapping there is
invisible.

**67 also had to become a hold state.** It is the shared "fade this tab out and go back to
the list" state, reached from whichever tab was open, so picking a side there threw the map
to the bottom screen before it had faded.

The general lesson, now twice: **a state machine's screen identity is not a single value,
and a tail call between handlers means a state you expect to see may never be written.**
Read the transitions, not just the resting states.

Acting on 68 also makes the swap *invisible*: 68 fades in from black, so the previous
screen has already faded out and both engines are black at the moment of the flip. That is
exactly why the menus never flashed — they were already being swapped while black. **The
general rule: swap during the game's own fade, not after it.**

The routing is also re-applied on every state change rather than only when the side flips,
because the app reconfigures the display as it builds each screen.

### The battle variable, identified

`BATTLE_STATE` (FR `0x021D0E28`) was derived empirically and shipped as a magic number.
The decomp names it — not where the earlier search looked (`asm/unk_0200B150.s` is still
raw assembly), but in `src/poke_overlay.c`:

```c
typedef struct PMiLoadedOverlay { FSOverlayID id; BOOL active; };
static PMiLoadedOverlay sOverlayRegions[OVY_REGION_NUM][OVY_MAX_PER_REGION];
```

3 regions × 8 slots × 8 bytes of BSS, tracking which overlays are resident. Dumping
`0x021D0E10` onward from four savestates shows the array exactly:

| | slot 0 | slot 1 | slot 2 | **slot 3** |
|---|---|---|---|---|
| in battle | `12`, active | `18`, active | `6`, active | **`10`, active** |
| in the Pokédex | `18`, active | `2`, stale | `3`, stale | **`27`, stale** |

So `0x021D0E28` is `sOverlayRegions[OVY_REGION_MAIN][3].id` — the overlay id occupying
main-region slot 3. The battle loads a different overlay per phase, which is why it tracks
the phase: `10` = the trainer AI, loaded for exactly the command-selection phase, `8` = a
sub-screen, `7` = the turn executing. `27` is
just a stale id in an inactive slot, which is what "outside battle" was really measuring.

**This closes the US gap.** The array is BSS so it cannot be found by shape, but exactly
one ARM9 literal points at it, at a fixed *code* address (`0x0200713C`). Reading that
literal gives the base per ROM:

| ROM | `sOverlayRegions` | slot 3 |
|---|---|---|
| SoulSilver FR / HeartGold FR | `0x021D0E10` | `0x021D0E28` |
| HeartGold US | `0x021D0DF0` | `0x021D0E08` |

The US value matches what the −0x20 delta predicted, so nothing changes in behaviour — but
it is now **read from the ROM instead of inferred**, and it doubles as an independent
second measurement of the region shift, which the patcher cross-checks against the one it
gets from the main loop's literal.

**The caveat this exposed:** the value says which overlay is *resident*, not whether the
menu is accepting input. Overlay 10 is already loaded while the battle intro text is still
playing, so "awaiting a command" goes true early — see
[The A press that pinned the menu](#the-a-press-that-pinned-the-menu).

### Lesson

**A candidate is not confirmed until it has been probed live in a state that was not part
of the sample.** That check caught all four bad candidates; savestate intersection alone
caught none of them. Where the decomp has coverage, prefer its structure over any
statistical search.

## PC box — savestates, because the decomp does not reach it

Overlay 14 is one of the 75 still raw assembly in pret. `PCBox_Main` exists as a symbol
(`asm/overlay_14.s`, `; 0x021E596C`) but there is no state machine, no state constants, and
nothing like the `POKEDEXAPP_MAINSEQ_*` enum that made the Pokédex tractable. So the screen
levels had to come from observation.

The method that worked for the Pokédex works without any source: scan a savestate's RAM for
an `OverlayManager` whose `template.ovy_id == 14` and whose three function pointers land
inside overlay 14's RAM range, then read `exec_state` (+0x10) and `proc_state` (+0x14).
Seven savestates, one live manager at `0x022A9C10`:

| savestate | `exec_state` | `proc_state` |
|---|---|---|
| PC option list, before entering | — | **no manager exists** |
| inside a box, cursor on a Pokémon | 2 | 81 |
| inside a box, holding a Pokémon | 2 | 115 |
| item storage | 2 | 117 |
| back on the option list | — | **no manager exists** |
| fading in | 2 | 0 |
| fading out | 3 | 0 |

The useful result is the one that is absent. **The PC option list has no overlay-14 manager
at all**, checked both before entering and after backing out — it is a field menu, and the
app only exists once you are inside. So the whole of overlay 14 is "managing the box", every
screen in it wants engine B on top, and there is no per-state rule to get wrong. The
trampoline just applies the swap on every call.

### The direction was wrong, and inference kept getting it backwards

Two shipped attempts forced the box towards engine B, on the reasonable-sounding
assumption that the touch UI is always on engine B. It is not. Disassembling overlay 14's
single `POWCNT1` site in the stock ROM settles it in one look:

| | instruction | effect |
|---|---|---|
| stock | `ldr r0,=0xFFFF7FFF ; ands r0,r1` | clears bit 15 -> **engine B on top** |
| patched | `ldr r0,=0x00008000 ; orrs r0,r1` | sets bit 15 -> **engine A on top** |

So stock HGSS puts engine B on the PC's *top* screen, which means the box grid — the half
you actually operate — is drawn on **engine A**. The static site flip already turns that
into "grid on top" and needs no help at all; forcing engine B up shoved the grid back down
and undid it.

**`SetSwap(1)` means "engine A to the bottom", not "bring the touch UI up".** The two
coincide for most apps only because most apps happen to draw their touch UI on engine B.
Establish which engine an app actually draws on — by disassembling its site — before
choosing a value. Several rounds of otherwise-sound reasoning about savestates could not
substitute for that one disassembly.

### Ordering: why the first attempt did nothing at all

Swapping before tail-calling the app — the way the Pokédex trampoline does — had **no
visible effect whatsoever**. The reason is ordering, and the evidence is two measurements:

- overlay 14 contains exactly **one** `POWCNT1` site, so the app is not fighting us with a
  stream of its own writes;
- `gSystem.screensFlipped` reads **0** in all seven PC savestates, and `GfGfx_SwapDisplay`
  turns that into "engine A on top".

So anything the app calls that routes screens puts the box back on the bottom — and because
our write came *first*, the app always had the last word. The Pokédex gets away with a
pre-exec swap only because it does not re-route.

The fix is to run the app first and set the routing afterwards, plus a two-frame countdown
that re-applies it from `OneScreen_Frame`, the same place the battle logic writes from,
which is known to win. The cost is that L+R does not stick while the PC is open.

**The general rule: when an app re-routes screens, your write has to be the last one in the
frame — a trampoline that swaps before tail-calling is the wrong order.**

Coming out is self-healing: the field re-asserts its own layout on return, the same reason
the overworld menu needed a latch.

The template resolves structurally in every ROM, and US lands on `0x021E596D` — exactly the
`0x021E596C` the decomp's assembly listing gives for `PCBox_Main`, with the Thumb bit. A
free cross-check that the structural search finds the right thing.

## Field script menus — the PC option list, and everything like it

The PC option list is not part of the PC app at all (that was the savestate result above).
It is a **field script menu**, drawn on the touch screen by the running script inside the
field app — the same mechanism as shop lists and NPC yes/no choices. There is no app
transition to detect and no `POWCNT1` write of our own to catch.

pret gives the signal directly. `FieldSystem` (`include/field_system.h`) has:

```c
struct FieldSystem { FieldProcessManager *processManager;   // +0x00
                     ... ; int bottomScreenType;            // +0x18
                     int unk1C; ... };                      // +0x1C
```

and `ScrCmd_TouchscreenMenuHide` sets `unk1C = 3` when a script takes the bottom screen,
while `ScrCmd_TouchscreenMenuShow` sets it back to `0` for the normal icon bar. The live
`FieldSystem` hangs off `sFieldSysPtr`, the file-static in `field_system.c`.

Finding `sFieldSysPtr` was a search with a real control, unlike the two Pokédex candidates
that failed. Scanning every 4-byte-aligned word of ARM9 BSS for a pointer that is **stable
across all seven savestates** and whose `+0x1C` reads 3 in both option-list states left
**exactly one** hit: `0x021D4178` → `0x022A027C`. The struct there is unmistakable — six
heap pointers, then two small ints, then more heap pointers, exactly the decomp's layout.

Then the rule that caught every earlier bad candidate: **probe out of sample.** Reading the
same fixed address in six savestates from *different sessions and different builds*:

| savestate | `unk1C` |
|---|---|
| all seven PC states | **3** |
| Pokédex ×2, battle, overworld ×2, name entry | **0** |

Clean separation on both sides, from data that was never part of the search.

Six ARM9 literals point at `sFieldSysPtr`, at the **same six code addresses** in all three
ROMs, each holding its own region's value — so the patcher reads it per ROM
(FR `0x021D4178`, US `0x021D4158`) and cross-checks the shift, as with `sOverlayRegions`.

The hook tests **non-zero** rather than `== 3`: any non-default mode means a script has put
something on the bottom screen the player needs. Applied every frame while it is up, and
the world goes back when it clears.

This is the broadest fix in the project so far — it covers the PC option list, shop menus
and NPC choice menus in one rule.

## Flying — and reading the hook's own mind

Selecting a destination on the Town Map left the whole flight animation on the bottom
screen, and it only corrected itself much later.

Savestates through the sequence show the shape of it: the Town Map app is live before the
press (overlay 101, `exec_state 2`), reads `exec_state 3` immediately after — the app
exiting — and is gone by mid-animation with `gSystem.vBlankIntr` back to the field. **So
the flight animation is drawn by the field, after the Town Map tears down.**

Two things then ruled out every state-based approach:

- the arrived-but-wrong and arrived-and-corrected savestates are **identical field for
  field**, differing only in `POWCNT1`;
- `location->mapId` only changes on arrival, far too late for "swap when I press A".

### The actual cause, found by reading our own variables

A first fix — restore the world on the app→field transition — changed nothing, and the
reason was invisible in game state because it was in *our* state.

The payload lives in ITCM, which is not part of the main-RAM block `savestate.py` extracts.
But it begins with the ASCII signature `1SGS`, so it can be found by searching the raw
savestate file. `python tools/savestate.py hook state.mln` does exactly that, and it said:

| savestate | `menu_swapped` |
|---|---|
| town map, mid-flight, arrived-wrong | **1** |
| after it corrected | 0 |

Flying is reached *through* the X menu, and that latch is deliberately kept across
sub-apps so a trip into the bag and back leaves the menu on top. But flying does not come
back to the menu, it comes back to the world — so `Poll` was re-applying "menu on top"
every frame, which is what put the animation on the bottom screen, and the new restore
code sat behind that gate and never ran.

The fix hooks the fly map's template and watches for it to **stop** being called, which is
the frame after you confirm. If the field has taken over by then, the latch is dropped and
the world is forced up for half a second. Backing out of the town map into the Pokégear
proper is excluded by that same check.

**The lesson: when a fix has no effect, suspect your own state before the game's.** Game
state had nothing to say here; one look at `menu_swapped` had the whole answer.

## The field's task manager — and what it can and cannot tell you

Reaching the field's running task needs no searching:

```c
struct TaskManager { TaskManager *prev; TaskFunc func; u32 state; void *env;
                     u32 unk10; void *unk14; FieldSystem *fieldSystem; ... };
```

via `sFieldSysPtr -> fieldSystem->taskman` (+0x10), and the struct **confirms itself** —
`+0x18` reads back the same `FieldSystem` pointer we started from. Three savestates:

| state | `taskman` | `taskman->func` |
|---|---|---|
| X menu open | `0x022C01D8` | `0x0203BEF1` — ARM9, i.e. `Task_StartMenu` |
| no menu | **NULL** | — |
| after Dig | `0x022C01D8` | `0x0224C3CD` — an **overlay** address, a script task |

Two facts are safe to use, and only two:

- **`taskman == NULL`** means the field is idle, so a press of X really will open the
  menu. That is the game's own gate (`src/field_control.c` only reaches `StartMenu_Init`
  when no task is running), which is exactly why a ladder swallows the press.
- **an overlay-resident `func`** means a script owns the field. Scripts live in overlays;
  the menu lives in ARM9.

### The mistake worth recording

The tempting third reading — "`func` is in ARM9, therefore the menu is open" — is **wrong**,
and shipping it broke more than it fixed: the cave-name card and the flight sequence are
ARM9 field tasks too, so the menu got forced on top of both. ARM9 means "not a script",
nothing more.

The corrected design uses each fact only in the direction it supports:

| symptom | rule |
|---|---|
| X on a ladder swapped with no menu | accept X only if **last frame's** `taskman` was NULL |
| Dig / Escape Rope kept the menu latched | an overlay task appearing **clears** the latch |

The clearing rule can only ever lower the latch, never raise it, so it cannot put the menu
over a cave card or a flight however wrong its premise turns out to be. **A rule that can
only remove behaviour is far safer to ship than one that can add it** — the broad version
failed in ways play-testing surfaced one at a time, which is the expensive way to find out.

Reading `taskman` from the frame *before* the press also avoids racing the game: our hook
runs inside the same main loop that handles input, so by the time we see the X press the
menu task may already exist.

## Regions: what actually differs

Measured between French HeartGold (`IPKF`) and US HeartGold (`IPKE`):

| | result |
|---|---|
| Display-routing sites found | **87 in both — 42 SET + 45 CLR, identical** |
| ARM9 code anchors (`0x02022D40`, `0x02000DB8`, `0x02000E32`) | **same address in both** |
| Name-entry app at `0x02083140` | **byte-identical** (`b508 f79d fa6b f788`) |
| Main-loop hook site `0x02000DB0` | identical (`f000 f9ac`) |
| ITCM autoload block | identical (`0x01FF8000`, size `0x620`) |
| ARM9 bytes differing | 7.08% — all in *data*, not code layout |
| Overlay bases, `static_bss_start`, `bss_end` | shifted uniformly by **−0x20** |

**ARM9 code addresses are identical across regions; only data, BSS and overlay bases
move, and they move together.** That is why the static half of the patch needed no region
work at all: `sites.py` finds sites by instruction shape, and `table.py`'s exceptions are
overlay *numbers* plus two ARM9 *code* addresses (`0x02022D3E`, `0x0201A2A2` — both
confirmed to hold a POWCNT1 LDR in US as well).

### How the hook is region-resolved

Rather than a per-region address table, `onescreen/regions.py` derives everything from
the ROM (see `OneScreen_Config` in `src/hook.s`):

| value | source |
|---|---|
| `app_callback` | the literal the main loop loads into r4, read at the fixed code address `0x02000DA6` |
| `pad_held` | `app_callback + 0x38` |
| `field_callback` | overlay 1 RAM base + 1 |
| `ov12_lo` / `ov12_hi` | overlay 12 base and base+size |
| `battle_state` | French value + the delta implied by `app_callback` |

The delta falls out of the main-loop literal for free (FR `0x021D112C`, US `0x021D110C`),
so five of six values are read straight from the ROM. Verified live over GDB: the config
block in a patched US ROM reads back exactly the resolved values, and `app_callback`
points into overlay 1's range as it should.

`battle_state` is the only value still *inferred* rather than read. If US battles
misbehave, re-derive it with `tools/savestate.py intersect` on US savestates — and
remember the rule that a candidate is not confirmed until probed live in a state outside
the sample.

## Screens that never write POWCNT1

Some apps route the wrong engine to the top and cannot be caught by static site flips.
Two mechanisms cover them:

- **Overworld X menu** — drawn *inside* the field app (callback stays `0x021E5921`), with
  no POWCNT1 write and no app transition. Nothing to detect, so it is driven from the
  buttons the player already presses: **X toggles, B restores**.
- **`app_table` in `src/hook.s`** — `{app callback, desired routing}` pairs applied on app
  transition. First entry: **name entry** (`0x02083141`, ARM9-resident) which sets the
  global flag at `0x021D1195` to 1 and calls the shared helper, putting its engine-A
  keyboard on the bottom. Add entries here as more screens turn up.

## Automatic battle swapping: what was missing (historical)

Needs a battle sub-state variable (action-select vs turn resolution). Blockers hit:

- The **melonDS GDB stub accepts exactly one connection per emulator launch** — verified
  twice, reconnection always fails with `vMustReplyEmpty: timeout`. So each run yields a
  single memory snapshot.
- The battle context pointer (`[0x021D1130]`) **moves between runs** (`0x022C0294` vs
  `0x022C026C`), so a raw fixed-address diff across two launches is unreliable.

Cleanest way forward: two **melonDS savestates** on the same build (one at action-select,
one during resolution). Savestates contain full main RAM, so both states can be diffed
offline with no emulator driving and no pointer drift.

## Open problem (historical): battles

Battles load overlays 6, 7, 10, 12, 18; **overlay 10 is reloaded every time the player
picks an action**, so it is the action-select menu. **Overlay 10 contains no POWCNT1 site
at all** — it inherits whatever routing the battle set up (ov12, site `0x02239B6E`).

So a static flip of ov12 would put the command menu on top for the *entire* battle,
including animations. Battles therefore still need **dynamic** swapping between
action-select and turn resolution. Everything else (menus, bag, party, PC, shops) is
solvable with static flips alone.

## Free space: SOLVED — ~31 KB of unused ITCM

The ARM9 autoload list at `0x02111F00` has exactly two blocks:

| block | destination | image size | bss |
|---|---|---|---|
| 1 | `0x01FF8000` — **ITCM** | `0x620` | 0 |
| 2 | `0x027E0000` — DTCM | `0x60` | `0x20` |

ITCM is 32 KB (`0x01FF8000`–`0x02000000`) and HGSS uses **1568 bytes of it**. That leaves
**`0x01FF8620`–`0x02000000`, about 31 KB**, which is:

- always resident (never paged, never unloaded),
- outside the BSS clear range, so nothing wipes it,
- the fastest memory on the ARM9,
- reachable by Thumb `BL` from ARM9 (~173 KB away) and from every overlay (~2.5 MB), both
  well inside the ±4 MB branch range.

Claim it by appending a **third autoload entry**: put the code image after the existing
autoload images (file offset `0x111F00`), move the autoload list after it, and update
`autoload_list` / `autoload_list_end` in MODULE_PARAMS. This is safe because the existing
ITCM/DTCM images already live at `autoload_start == static_bss_start`, which proves
autoload processing runs *before* the BSS clear.

**Implemented and verified end-to-end** (`onescreen/inject.py`, `src/hook.s`,
`build.py --inject`). Built `out/ipgf-v4.nds`, booted it, and read ITCM over GDB:

```
0x1ff8620:  0x53475331  0x00000001  0x88114a09  0x28000ad3
            "1SGS"      version     ldr/ldrh    lsrs/cmp
```

Byte-for-byte the assembled payload, resident from boot, game runs normally.
52 bytes used, **31,148 bytes of ITCM still free**. Exported entry points:

| symbol | address |
|---|---|
| `OneScreen_Signature` | `0x01FF8620` |
| `OneScreen_SetSwap(r0)` | `0x01FF8628` — r0=0 engine A top, r0!=0 UI on top |
| `OneScreen_GetSwap()` | `0x01FF863C` |

## Debugging: melonDS GDB stub

`[Instance0.Gdb] Enabled = true`, ARM9 on port 3333 (JIT already off by default). Attach
with the devkitARM gdb — `tools/probe.ps1` wraps it. **The stub accepts only one
connection per emulator launch**, so it is one probe per run; drive the game to the state
you want, then probe once.

Measured ground truth (v3):

| state | app callback `[0x021D112C]` | flag `[0x021D1195]` | live POWCNT1 |
|---|---|---|---|
| overworld | `0x021E5921` (ov001 base = field) | 0 | `0x820F` (bit15 **set**, engine A top) |
| party screen | `0x020796B9` (**ARM9 static**) | 0 | `0x020F` (bit15 clear, engine A bottom) |

The party being an ARM9-resident app with its own CLR-family site at `0x02078E66` is what
made it look like it "inherited" routing. It does not.

## Analyser bug worth remembering

`_analyse` originally treated **any** `STRH` as the commit point. The compiler interleaves
unrelated stores into these sequences — e.g. at `0x02078E66`:

```
ldr  r2, =POWCNT1
strh r1, [r3, #0]     <- unrelated store, NOT the commit
ldrh r1, [r2, #0]
ldr  r0, =0xFFFF7FFF
ands r0, r1
strh r0, [r2, #0]     <- the real commit
```

Only a store through the POWCNT1 register ends the sequence; anything else must be skipped.
Fixing this took the site count from 82 to **87 (45 CLR + 42 SET)** and is what made the
party screen fixable.

## Per-site intents

`0x02022D3E` must never be flipped: it is inside the shared helper, so flipping it inverts
every app that uses the helper *including the field*. `0x0201A2A2` (boot init) likewise.
Everything else defaults to FLIP. See `SITE_INTENT` in `onescreen/table.py`.

## Dead ends (recorded so they aren't retried)

- **ARM9 zero-run "free space"** (3602 bytes across 26 regions, identical addresses in
  both games): all of it is inside live data tables indexed by base+offset — the
  surrounding bytes are structured arrays and pointer tables. Not safe.
- **"Dead function" detection by unreferenced Thumb `push {..,lr}` prologue**: produces
  false positives inside ARM-mode regions (e.g. `0x020CBCEC` is mid-`memcpy`, not a
  function). Would need real ARM/Thumb region separation to be trustworthy.
- Neither matters now — the flip approach needs no free space.

## Tooling notes

- `ndspy` handles BLZ decompress/recompress; a load→save round-trip differs from the
  original in only 11 bytes (ROM-size field, header CRC, trailing padding).
- Patched ARM9 and overlays are stored **uncompressed** (`compressed_static_end = 0`,
  overlay compression flag cleared). Costs ~200 KB of the ~7.5 MB free ROM space and
  avoids BLZ recompression risk entirely. Verified to boot.
- melonDS 1.1 ships with **all keys unbound**; `tools/melonds_config.py` sets them
  (Qt key codes) and switches `ScreenSizing` (4 = top only).
- Screenshots via `PrintWindow` with `PW_RENDERFULLCONTENT` work without stealing focus.
  Note the ALT tap used to unlock `SetForegroundWindow` opens melonDS's Qt menu bar —
  send `ESC` afterwards or keystrokes hit the menu instead of the game.

## Drawing the battle command menu

The first thing this project draws rather than reroutes. Everything it needs was found
statically or measured live; none of it is guessed.

**Where it draws.** The battle message box is already on the main engine, which is what
makes this cheap — `battleSystem->window[0]`, `GF_BG_LYR_MAIN_1`, tile rect x=2 y=19,
27×4 tiles, palette 11, baseTile 31. Confirmed three ways: the decomp
(`asm/overlay_12_022378C0.s:375`), the same `AddWindowParameterized` immediate sequence
found at three sites in the retail ov12 of all three ROMs, and a live dump mid-battle —
`BG1CNT` charBase 1, engine-A `DISPCNT` character-base offset 0, so the tiles start at
`0x06004000 + baseTile*32`. The right-hand columns hold only the "look at the bottom
screen" icon, which the blit covers.

Palette 11 reads fg 1, shadow 2, paper 15, with a usable salmon accent at 12 — which
pret's `sFontInfos` (`src/font.c:28`) states independently as `fgColor 1, bgColor 15,
shadowColor 2`.

**What it draws.** `onescreen/labels.py` pulls the strings out of the ROM being patched
(`msg_0197` entries 924–927, plus 940/941 for yes/no) and rasterises them with the game's
own font (`a/0/1/6` file 1, fontId 1). Both are language-neutral, so the build speaks
whatever the dump speaks. Two gotchas worth keeping: ndspy returns the five font files as
empty and the archive's own FAT has to be read instead; and the glyph format is 2bpp,
16×16, most significant pair leftmost, high byte of each u16 first.

**How it knows what is happening.** The battle is an `OverlayManager` app whose
init/exec/exit are ARM9 wrappers rather than overlay code, so `find_overlay_template`
needed an `arm9_resident` shape — exactly one match per ROM (FR `0x020FA468`, US
`0x020FA484`). Its exec hands over the live `BattleSystem` every frame.

| what | where | how it was pinned |
|---|---|---|
| `battleInput` | `BattleSystem + 0x19C` | a scan for a word pointing back at `BattleSystem` found `0x19C` at runtime |
| `curMenuId` | `BattleInput + 0x68B` | literal census (below) |
| `menuCursor` | `BattleInput + 0x6DC` | the full decompilation; earlier builds learned it at runtime from a wrong 0x6D4 start (see below) |

**The literal census.** pret warns at `battle_input.h:168` that its offsets in this struct
drift, and they do — by `0x20`. Offsets that large cannot be a Thumb immediate, so every
access loads them from a literal pool, which makes the pool a census of the struct.
Scanning ov12's word-aligned literals in `[0x500,0x800)` shows

    0x68a x9   0x68b x6   0x68c x5   0x68d x1   0x68e x3   0x68f x2

six consecutive single-byte offsets — pret's run of six `u8` fields. What confirms the
alignment rather than merely fitting it is the *gap*: `0x688` and `0x689` are absent
entirely, and those are the two fields pret calls `unused_668`/`unused_669`. Unreferenced
fields leave no literals.

**The cursor was the one thing the census got wrong.** Extending the same +0x20 put
`menuCursor` on `0x6d4`, with `0x6d8` and `0x6dc` read as `keyPressed` and
`tutorial.finger`. The full decompilation (ctrl-cheeb-del/pokeheartgold, byte-matching, so
its layout is the compiler's) gives `0x6d4` `scrollXEnd`, `0x6d8` `BattleCursor *cursor`
and `0x6dc` **`menuCursor`** — and that reading explains the census counts better: `0x6d8`
x8 and `0x6dc` x7 are the eight functions that touch the sprite cursor and the seven that
take `&menuCursor`. pret's labels drift by `0x20` to `0x28` here, not by a constant.
Earlier builds recovered from the wrong start by learning the offset at runtime
(`OneScreen_BattleLearn`), which converged on `0x6dc`; v0.3 uses the fixed value and drops
the learner, which had also been diffing freed memory whenever the bag was open.

**Menu ids 1..4 are the root menu**, not just the two the enum names — 3 and 4 are the
"put the menu back up" states you land on after backing out of a submenu. Testing only 1
and 2 left the screens swapped with no labels after a trip into the bag. v0.2b drew 1..8,
which the full decompilation shows was too wide: `sBattleMenuTemplates` gives the
main-menu cursor to ten ids, but 5/6 are the first rival battle (FIGHT alone, a 1x1
cursor), 7/8 the Safari Zone (BALL / BAIT / MUD / RUN) and 19/20 the Bug Contest (BALL in
place of BAG). Drawing FIGHT / BAG / POKéMON / RUN over those labels choices the game is
not offering, so from v0.3 they swap like any other menu.

**Two things the menu id cannot see**, both found by playing:

- The bag and party run as **overlay 8** and free the `BattleInput` that `curMenuId` lives
  in (`graphicsMode` 3). The stale byte still read as the root menu, so they drew on the
  bottom screen until the overlay id was checked first.
- Confirming a choice resets the game's cursor *before* the menu id changes, so the
  highlight flashed back to FIGHT on the way out. Fixed by freezing the image at the
  moment A is pressed and holding it across a submenu trip — which is also simply correct,
  since the game restores the cursor to that same choice.

## Resolved dead end: a yes/no box for the field prompts

The first attempt on `beta-ui` was **abandoned**. The goal was the battle treatment for
the overworld's binary questions, beginning with the nurse's "heal your Pokémon?" offer.
Its negative results remain below because they ruled out several convincing but wrong
paths. The conclusion did not: the prompt has a shared controller, one level deeper than
the `ov01` list-menu code that was searched first. The superficially similar question
after an evolution is a different ARM9 controller, documented in the next section.

### Resolution: mode 3 is a custom overlay-27 controller

The nurse script is already readable in pret. `scr_seq_0003_002` prints a `msg_0040`
message ending in `{YESNO 0}`, calls `TouchscreenMenuHide`, then reads
`GetMenuChoice VAR_SPECIAL_RESULT`. `{YESNO}` itself is only the three-tile "look at the
lower screen" indicator; it does not create the choice. `ScrCmd_GetMenuChoice` calls
`ov01_021F6ABC(fieldSystem, 3, 3, &ctx->data[1])`, which asks bottom-screen mode 3 to enter
state 3. `TouchscreenMenuHide` records that requested mode at `FieldSystem+0x1C`, and
`TouchscreenMenuShow` eventually returns it to 0.

Mode 3 is entry 3 in overlay 27's bottom-UI table. It is not `ListMenu2D` and not
`yes_no_prompt.c`; it is a custom state machine reached through two `SysTask` objects:

    FieldSystem + 0xD8       outer SysTask *
      SysTask + 0x10         outer environment
        +0x04                child SysTask *
        +0x08                FieldSystem * back-reference
          SysTask + 0x10     child controller
            +0x00            state
            +0x24            FieldSystem * back-reference
            +0x394           binary selection (0 yes, 1 no)

`SysTask.data` being at `+0x10` is confirmed by `include/sys_task.h` and `src/sys_task.c`.
The controller's assembly divides cleanly into the two kinds of UI that earlier work had
conflated:

| state | behaviour | top-screen treatment |
|---|---|---|
| 0–2 | setup, idle and transition | keep the world |
| 3 | initialise binary prompt, selection 0 | draw Yes selected |
| 4 | handle binary input | draw the live selection |
| 5 | confirm and return the result | hold the live selection |
| 6 | tear down the binary prompt | wipe once; keep the world |
| 7–10 | initialise, run and close a longer list | show the lower UI |
| 11 | communication-club cleanup/abort | show the native lower UI |

The native handler maps Up to 0, Down to 1, A to the current choice, and B to 1 followed
by confirmation. The patch therefore never interprets input or writes the script result;
it only mirrors the controller's selection into the rightmost three tiles of the existing
27×4 field dialogue. Setup and teardown remain on the world so there is no one-frame
screen flash, while the genuine list and external-cleanup states continue to use native
routing.

This chain is safe to follow only while the field app is running. Every pointer must be
word-aligned and wholly inside main RAM, both `FieldSystem` back-references must match,
the state must be 0–11, and a drawn selection must be 0 or 1. Any failed check means draw
nothing and use the existing screen swap. That directly addresses both regressions from
the first attempt: painting another app's VRAM and following a stale pointer into I/O.

The useful sources are pret's `files/fielddata/script/scr_seq/scr_seq_0003.s`,
`src/scrcmd_c.c`, `asm/overlay_01_021F6830.s`, `asm/overlay_27.s` and
`include/sys_task.h`. The LLM-assisted
[pokeheartgold-slop](https://github.com/antonsynd/pokeheartgold-slop) fork can help turn a
narrow overlay-27 function into C if live behaviour ever disagrees with this reading, but
it is a last-resort aid, not the authority: the matching retail assembly and savestate
values must still win. The nurse speech itself needs no further decompilation.

### What the first investigation ruled out

**The value was lower than it looked.** When a script menu owns the bottom screen the
patch already swaps it up, and the buttons read perfectly well there. The only gain would
have been keeping the world visible. Worth remembering before anyone tries again.

**The original conclusion was that there was no shared binary-choice system.**
`ScrCmd_YesNo` builds a `ListMenu2D` on `GF_BG_LYR_MAIN_3` — already the main engine, so
those prompts need no work at all. Oak's speech has its own (`OakSpeechYesNo_*`). Those
facts are true, but the conclusion was too broad: the nurse's green two-button panel is
the shared custom controller in overlay 27 described above.

What was disproved, in order:

1. **`menu + 0x9B` is the item count.** It is — `MoveTutorMenu_SetListItem_Internal` ends
   by incrementing it — but it reads 0 at a nurse prompt.
2. **`menu + 0xB8` is its `ListMenu2D`.** `ov01_021EDE8C` does call
   `Handle2dMenuInput(menu->[0xB8])` every frame, so the offset is right, but the pointer
   reached from `ov01_021F6B20`'s chain is not that menu: its first word should be the
   `FieldSystem` (`ov01_021EDAFC` opens with `str r4, [r6]`) and reads `0x00400000`.
3. **The nurse uses that menu at all.** A whole-RAM scan of a savestate at the prompt
   found **no** genuine `ListMenu2D` anywhere, and `ov01_021EDAFC` always builds one.
4. **A byte found by savestate diff is the selection.** Diffing two states that differed
   only in which button was highlighted gave exactly one isolated `0↔1` byte in 4 MB. It
   turned out to sit at a fixed offset inside a **96 KB heap block** (`0x18000` in its
   header), i.e. a heap offset, not a struct field — stable only while allocation order
   happens to repeat. A hardware watchpoint on it never fired while the cursor moved,
   which settled it.
5. **"A script menu that is not a list menu" identifies a binary prompt.** This one
   shipped briefly and is the reason to be careful: it fires on any scripted
   bottom-screen moment that is not a list, including simply switching on the PC.

**What did work**, and was worth reusing: the shop's menu *is* a real `ov01` list menu —
first word is the `FieldSystem`, item count 3 at `+0x9B` for Buy/Sell/Quit. So shops and
multi-choice questions can be recognised reliably. The binary touch prompts simply could
not be recognised through those `ov01` list-menu paths.

**Two regressions this caused**, both from drawing before the ground was measured:

- `OneScreen_ScriptMenu` runs every frame *whatever app is on screen*. Harmless while it
  only touched `POWCNT1`; the moment it drew, it painted over VRAM the PC box and shops
  had taken for their own graphics. Gate any drawing on the overworld actually running.
- Walking a pointer chain with only null checks froze the game in a shop. A stale pointer
  is not null, it is arbitrary, and `ldr` through arbitrary reaches I/O space — reading
  the IPC FIFO at `0x04100000` pops it and hangs the ARM9. Range-check every link.

**Method note.** Savestates were far more productive than driving the emulator: no
one-connection-per-launch limit, no navigation timing, and the same query can be re-run
offline. Three offline queries against a pair of savestates produced more than six live
runs did. `tools/savestate.py` is the tool; melonDS writes slots as `<rom>.ml1`, `.ml2`.

## Post-evolution move-learning prompts

The "forget a move?" screen looks like another green binary field prompt, but it is not
owned by overlay 27. A French SoulSilver savestate taken on the first option gave a much
cleaner root: `gSystem.vBlankIntr` was the Thumb callback at `0x02077271`, and its argument
at `gSystem+4` was a `0xBC`-byte evolution task-data block at `0x022C0564`. This is the
callback installed by `sub_02075A7C`; the corresponding two-option state machine is ARM9
code.

The controller fields in that block are:

    +0x64  evolution state
    +0x8A  prompt substate (0 input, 1 confirmation animation)
    +0x8B  selection (1 Yes / forget, 2 No / keep)

The captured fixture resolves to state 21, substate 0 and selection 1, matching the red
"forget" choice in the screenshot. There are two copies of the same prompt flow:

| state | role | mirrored choice |
|---|---|---|
| 20 | set up "forget a move?" | Yes |
| 21 | input/confirmation for that question | live `+0x8B` |
| 34 | set up "stop trying to teach it?" | Yes |
| 35 | input/confirmation for that question | live `+0x8B` |

The native handler remains authoritative. Up and Down change `+0x8B`, A confirms it, and
B selects 2 and confirms No. The patch neither reads the keypad for this feature nor
writes the result; it only turns the native 1/2 into the existing localized Yes/No image.

**The window can be verified rather than assumed.** The task data points to its `BgConfig`
at `+0x00` and to a live `Window` at `+0x04`. That window points back to the same
`BgConfig`, has packed geometry `0x1B130201` (MAIN_1, x=2, y=19, width=27) and
`0x001F0B04` (height=4, palette=11, base tile=31), and has a live pixel buffer at `+0x0C`.
It is therefore exactly the same four-row tile rectangle as battle window 0. The prompt
can alias both the battle Yes/No geometry and its localized image data, with no new image
bytes.

The runtime resolver requires the structurally resolved evolution callback to be active,
range-checks the complete task-data block and every pointer, checks the window's `BgConfig`
ownership and packed geometry words, and requires the state to remain in the known 0–45
range. Only the four states above are treated as prompts, and their live choices must be
1 or 2. A valid non-prompt evolution state wipes a previously drawn label once. Invalid
or stale data resets the latch without touching VRAM, which matters when the VBlank owner
changes to the next application.

This is also why a script-level `GetMenuChoice` rewrite would not have helped this screen:
the post-evolution move flow never uses that script command or overlay-27 controller.

## Drawing Oak's prompts

The second thing this patch draws, and much cheaper than the first, for one reason:
`src/oaks_speech.c` is decompiled. Everything the battle menu had to be reverse-engineered
for was simply readable here.

**The state machine is named.** `OakSpeechData.state` is at `+0x0C` — which the hook was
already reading, so the struct base was confirmed before any of this started — and the
enum in `src/oaks_speech.c` names every value. Only the three states that actually take
input are drawn on; the setup and fade states around them would otherwise flash a prompt
the player cannot answer yet:

| state | |
|---|---|
| 65 | `GENDER_SELECT_MENU_HANDLE_INPUT` |
| 69 | `CONFIRM_GENDER_YESNO_HANDLE_INPUT` |
| 98 | `CONFIRM_NAME_YESNO_HANDLE_INPUT` |

**The count and the selection are one struct away.** `OakSpeechMultichoice` is inline at
`+0x160`, anchored by `filler_148[0x18]` immediately before it and by `unk_080` and
`unk_114` earlier, all three named after their own offsets:

    +0x161 numOptions    +0x163 cursorPos

That pairing — "how many options" and "which one is lit", reachable from a pointer the
framework hands over every frame — is exactly what the first field-prompt investigation
had not yet located, and is the whole reason this took an afternoon and that took days.

**The two questions read differently, and the layout has to match.**
`OakSpeech_GenderSelectHandleInput` moves on `PAD_KEY_LEFT` and `PAD_KEY_RIGHT`; the
confirmations go through the generic multichoice handler on `PAD_KEY_UP` and
`PAD_KEY_DOWN`. So the gender options are drawn side by side and the confirmations
stacked. Stacking both would have implied the wrong keys.

**Same tile rectangle for the third time.** `sWindowTemplate_DialogMsg` is x=2, y=19, 27x4
— identical to the battle message window and the field dialog box. Only the layer beneath
differs:

|  | battle window[0] | field dialog box | Oak dialogWindow |
|---|---|---|---|
| layer | `MAIN_1` | `MAIN_3` | `MAIN_0` |
| char base | `0x06004000` | `0x06008000` | `0x06018000` |
| base tile | 31 | `0x237` | `0x36D` |
| palette | 11 | 12 | 6 |

Oak's native dialog uses palette 6 indices 1, 2 and 15 for ink, shadow and paper; index 12
is free for the custom selected band. Rather than hardcode an approximation, each active
prompt copies Oak's own backdrop accent from main BG palette 1/index 1 (`0x05000022`) to
dialog palette 6/index 12 (`0x050000D8`). The observed values are `0x71AA` in SoulSilver
(blue/silver) and `0x1A18` in HeartGold (gold). Both colours already belong to the retail
intro, and normal dialog text keeps its native palette entries.

**The words are the game's own.** `msg_0286` entries 7 and 16, whose row ids in the decomp
are literally `msg_0286_boy` and `msg_0286_girl`, and `msg_0219` entries 47 and 48 for
Oak's yes and no. A first attempt used the charmap's ♂ and ♀ (`01BB` / `01BC`) after a
search for standalone "Boy"/"Girl" came up empty — the search was simply too narrow.

**What the swap used to hide.** The old rule swapped for the whole gender range 62..93.
Drawing the prompts while that was still in place flipped the screen back and forth through
every fade and setup state between them. The gender flow now never swaps; only the tutorial
menu does, because three options of running text do not fit beside the question.

Two bugs worth remembering, both from the boxes being different widths:

- Taking a prompt down must wipe **the box that is actually up**. The gender box is ten
  tiles and the yes/no one three, so wiping the wrong one leaves labels on screen.
- Going from the gender prompt to the confirmation must clear the **wider** box, or the
  same leftovers appear.

### Resolved: the flickering "look at the bottom screen" indicator

A small DS/focus indicator used to flicker for a frame or two before Oak's custom prompts
appeared. The failed investigations are retained below because each ruled out a plausible
fix and narrowed the eventual answer.

It was **not** a regression in the custom label drawing. Oak's question messages 37, 38,
39, 41 and 42 end in `{YESNO 0}`. That text control is the old instruction to look at the
lower screen; the previous full-screen swap merely hid it.

What was ruled out, by measurement rather than argument:

1. **It is tiles in the dialog box, so blitting over it will do.** At that stage the hook
   held the box's own all-paper image over that corner on every non-prompt frame —
   confirmed live, `oak_drawn` read `0x22` — and the indicator still flickered.
2. **It is `data->sprites[3]`, the touch-to-advance object.** The decomp says that object
   lives in the corner and is shown and hidden around these states, so the hook cleared its
   `drawFlag` (`+0x34`, `sprites[3]` at `+0xE4`). A savestate showed **`oak_flag = 0`** —
   the flag was already zero before the write, so that object was never being drawn. The
   write was removed; it bought nothing, and it was the only place the hook wrote game
   state beyond `gSystem.screensFlipped`.
3. **The prompt states were too narrow.** Widened to cover the lead-in states, then to
   every state of the speech. No change.

The missing piece was the text-printer order. `{YESNO 0}` is encoded in the live `String`
as the four halfwords `[0xFFFE, 0x0200, 0x0001, 0x0000]`. `RunTextPrinter` processes the
`0x0200` command in a task after `OneScreen_OakExec`, calls
`RenderScreenFocusIndicatorTile`, then copies the whole window. A later redraw was
therefore guaranteed to beat the earlier wipe on frames where the control ran.

The fix removes the cause instead of racing that queue. In Oak's three message-printing
lead-ins (states 61, 67 and 97), while `printDialogMsgState` at `+0x104` is 1, the hook
validates the live `String *` at `+0x110`: aligned and wholly in main RAM, maximum size
`0x400`, current size below that maximum, and magic `0xB6F8D2EC`. It scans only the stated
length for the exact four-halfword sequence above and changes command id `0x0200` to the
unused `0x0209`. The generic parser skips that control safely, so no focus tile reaches
the pixel buffer. Requiring Oak's own VBlank argument to match its data block keeps the
write out of the nested naming application; restricting both state and exact sequence
leaves the tutorial and every other text control alone.

**Validation caveat.** The existing `beta-ui` savestate set has no frame from Oak's intro.
The cause and fix are supported by the decompiled message/state flow, exact assembly and
the main-loop task order, but the final absence of the flash still needs a fresh-start
melonDS play-through on both editions.

## The overworld menu, drawn on the world

The X menu was the first thing drawn with **no window to borrow**. Battles, the field and
Oak all wrote into a message window the game had already created, so the tiles were
allocated, mapped and palettised and drawing was a memcpy into them. The overworld has no
such window — the world fills the screen — so this one writes a **tilemap** as well as tile
pixels, which nothing else in the patch does.

### Where it can be drawn, and why nothing had to be reconfigured

During field play the world is **3D on BG0 at priority 1**, not a tilemap at all. That
priority is the number the whole feature hangs on, and it is set deliberately: `FieldMap_Init`
installs `initializeSimple3DVramManager` (`src/gf_3d_render.c:46`), which sets BG0 to 1 —
where `GF_3DVramMan_DefaultInitializer` would have set 0.

The three 2D layers come from `src/field/fieldmap.c:464-507`:

| | MAIN_1 | MAIN_2 | MAIN_3 |
|---|---|---|---|
| charBase | `0x10000` | `0x14000` | `0x08000` |
| screenBase | `0x0000` | `0x0800` | `0x1000` |
| priority | 3 | 3 | **0** |

So **only MAIN_3 is in front of the world**, and all three planes are enabled and merely
transparent while you walk. Drawing there needs no register touched: no priority shuffle,
no bank change, no `BgConfig` call. MAIN_1 is emptier — the Poké Mart is its only field
consumer — but putting it in front would have meant a priority shuffle *and* would have
covered the dialog box, since ties break toward the lower BG number.

### Tile placement, and the game's own habit of double-booking

`Task_StartMenu` loads its own graphic to **tile 0** of MAIN_3 (`src/start_menu.c:468`).
That file — `a/0/1/4` #12 — is LZ77 with an uncompressed size of `0x1040`, so **130 tiles**.
The only permanently allocated window on the layer is the map-name card at `0x197`
(`src/field/draw_map_name.c:32`), which lives for the whole field session.

Everything between is scratch belonging to script list menus (`0x3D`, `0xDD`), the mart,
and the comm club — none of which can be open while the start menu is. Parking the panel at
`0x84` (first `0x90`; moved down so the PC box menu fits) is therefore safe, and it is exactly what the game does to itself: script yes/no
sits at baseTile `0x21F` (`src/scrcmd_c.c:131`), *inside* the map-name window's range,
because the two never coexist.

The strips are re-uploaded on **every open** rather than once. A script list menu's own
tiles run `0x3D..0xDD` and eat into ours while the menu is shut, and the bag and party reuse
the layer wholesale. 5 KB once per press of X removes the entire class of bug.

### The three fields that drive it — all read from a live savestate

Read out of `out/beta-ui.ml1`, taken with the menu open and POKéDEX lit, rather than
trusted from the decomp alone:

| field | value read | what it means |
|---|---|---|
| `FieldSystem +0xD3` | `0` | the cursor — POKéDEX, matching the screen |
| `FieldSystem +0xD2` | `2` | the touch overlay's mode: menu open |
| `StartMenuTaskData +0x26` | `3` | `HANDLE_INPUT` |
| `StartMenuTaskData +0x2C` | **`10`** | `numActiveButtons`, for a **seven**-entry menu |
| `StartMenuTaskData +0x3A` | `[0,1,2,11,3,4,5,9,10,0]` | `selectionToAction[]` |
| `StartMenuTaskData +0x34C` | — | `inhibitIconFlags`, which is what it ended up using |

Four things in that table are worth keeping.

**The cursor is not in the task struct.** It lives in `FieldSystem`, because the *touch
overlay* owns it — `ov27_0225B404` writes it on every D-pad move and `start_menu.c` only
reads it. Looking for it in `StartMenuTaskData` finds `selectedIndex` at `+0x28`, which is
a latched copy taken at the moment you press A, not the moving cursor.

**`numActiveButtons` overcounts.** `StartMenu_BuildActionLists` unconditionally appends the
two registered-item buttons (`src/start_menu.c:520-521`), which the D-pad cannot reach —
`ov27_0225D0B4` navigates seven slots.

**`selectionToAction[]` is a trap, and the first build fell in it.** Decoded against the
enum at `src/start_menu.c:49` the savestate's copy is POKEDEX, POKEMON, BAG,
**POKEGEAR (11)**, TRAINER_CARD, SAVE, OPTIONS, then the two extras — exactly the order on
screen, which is precisely what makes it look like the right source. It is not, for two
reasons that only a save with an incomplete menu reveals:

1. **It is compacted, and the menu is not.** The grid slots are fixed: an entry you have
   not earned leaves its slot **empty**. Early in the game the real menu shows SAC alone in
   the left column *at row 2*, with the trainer card, SAUVER and OPTIONS down the right —
   because POKéDEX, POKéMON and POKéMATOS are missing from their own slots, not absent from
   a list. Packing the compacted list into consecutive cells puts every entry in the wrong
   place and desynchronises the cursor, which indexes the compacted order.
2. **Past the real entries it holds zeros**, and zero *is* `START_MENU_ACTION_POKEDEX`. A
   four-entry menu drew POKéDEX twice in the right-hand column, from padding.

The right source is **`inhibitIconFlags` at `+0x34C`** — the game's own answer, computed
once when the menu opens (`FieldSystem_GetStartMenuButtonInhibitFlags_Normal`,
`src/start_menu.c:288`). Walk the fixed cells, skip any whose bit is set, and the panel
matches the touch screen exactly. The cursor is then each drawn cell's position *among the
enabled ones*, which is what `+0xD3` counts.

Watch the enums: they are different. `START_MENU_ACTION_POKEGEAR` is **11**, but
`START_MENU_ACTION_DISABLE_POKEGEAR` is **9**.

**The special zones were detected rather than drawn, until v0.3.** Safari, the Bug Contest
and Pal Park use different grids (`ov27_0225CFC8` rows 1-3) that put RETIRE in slot 0 and
shift everything after it, and the active variant lives in overlay 27's own struct, which
this once called out of reach. The RETIRE bit separated them from the normal menu, and in
those zones `OneScreen_StartMenu` returned 0 and the caller swapped.

It is not out of reach. The full decompilation names the struct - `TouchscreenMenuData`,
the touch app's own data - and the path to it is the one the field prompts already walk:
`FieldSystem.bottomScreenTask` -> `BottomScreenAppManager` (app 0, running) -> the app's
SysTask -> data. Everything the panel needs is in there, every offset confirmed in pret's
retail assembly of overlay 27:

| offset | field | what it gives the panel |
|---|---|---|
| `+0x10` | `fieldSystem` | the back-pointer that proves it is this field's menu |
| `+0x14` | `selection` | the selected **slot** — no more counting enabled entries |
| `+0x470` | `icons[7].shown`, stride 8 | which slots exist right now |
| `+0x51C` | `layout:4` at bits 1-4 | which of the game's seven grids is up |

So v0.3 draws the game's own grid for all seven layouts — normal, Safari, Bug Contest, Pal
Park, the Union Room (with CHAT and LOG, `msg_0196` 34/35), the Colosseum and the Battle
Tower partner room — from the game's own table, which the patcher first checks is really in
the ROM's overlay 27. The inhibit-flag logic survives as the fallback for frames when the
touch app is switching, and that test had to be tightened on the way: the RETIRE bit alone
also passes in the Union Room, Colosseum and partner room, and drew the normal grid in the
Union Room.

### Why it is a grid and not a list

`ov27_0225D0B4` (`asm/overlay_27.s:6073`) is a `[7][4][3]` table:
per slot, per direction, three candidate destinations, and the navigator takes the first
whose slot is enabled — which is how it skips locked entries. Decoded, slots 0-3 are the
left column and 4-6 the right; **up/down wrap inside a column, left/right jump between
them**.

Drawn as a single list that reads as a bug: DOWN cycles through the first four entries and
never reaches the rest. The panel is 2x4 because the input is.

### Highlighting without a second set of pixels

The small boxes each ship one finished image per highlighted entry. That does not scale
here: eight cells x two states, at 8x2 tiles a cell, is **~32 KB against 11 KB of free
ITCM**. So the panel ships **one strip per label** and highlights by writing a different
**palette number into the selected cell's tilemap entries** — a few halfwords a frame.

That is also how the game does it. `ov27_0225B398` reloads a 32-byte OBJ palette for the
selected icon rather than moving a cursor sprite.

Storing one strip per *label* rather than one image per *cell* is what allows the runtime
`selectionToAction[]` lookup: the tilemap points any cell at any strip, so the assignment
is free.

### The trainer-card row cannot show your name

`msg_0196` entry 3 is the trainer card, and it decodes to a bare `{STRVAR_1 3, 0, 0}` — the
game calls `BufferPlayersName` and expands it at runtime (`asm/overlay_27.s:3455`). Patch-time
rasterisation has no save file to read, so that row uses `msg_0282` entry 5 instead:
**DRESSEUR** in French, **TRAINER** in English. Still the ROM's own words, still
language-neutral.

The other eight come from `msg_0196` via `ov27_0225CF94`: 0 POKéDEX, 1 POKéMON, 2 BAG,
4 SAVE, 5 OPTIONS, 6 EXIT (the enum calls it `RUNNING_SHOES`), 8 RETIRE, 14 POKéGEAR.


## The script list menus (the shop's, the PC's)

The shop's `ACHETER / VENDRE / QUITTER` and all three PC lists are **the same
object**. A script builds a menu (`ScrCmd_064` then `ScrCmd_066` per entry),
overlay 27's touch controller renders it, and the controller keeps a pointer
straight back to it. One renderer covers all of them, and the PC box menu too,
despite looking like a different system entirely.

### The chain, all read from savestates rather than inferred

```
FieldSystem -> +0xD8 outer SysTask -> +0x10 outer data
            -> +0x04 child SysTask -> +0x10 controller
     controller +0x394  cursor
     controller +0x3A0  the menu
         menu +0x9B  entry count
         menu +0x1C  String* per entry, stride 4
     String: +0x00 maxsize, +0x02 size, +0x04 magic, +0x08 u16 codes
```

**`+0x394` was already in this file under another name.** It was recorded as
`FIELD_CHILD_CHOICE_OFF`, the binary-prompt choice. It is the list cursor as
well - proved by two savestates of one shop menu reading 0 then 1 as the cursor
moved ACHETER -> VENDRE. The field that made this feature possible had been
sitting in the hook since the field-prompt work.

**`+0x39C` is not the menu.** It holds an ARM9 code address. Reading the entry
count through it gives 255, no menu matches, and the panel silently never
appears while everything still works - because unrecognised menus fall back to
swapping. Cost an entire build to notice; the fix was four bytes.

### Menus cannot be identified by message id

`ov01_021EDD68` reads each entry's id into a string, expands placeholders into a
pre-allocated `String`, stores that and the entry's return value, and **throws
the id away**. Since this same code draws every NPC choice in the game, and
drawing the wrong words would be worse than swapping, a menu is recognised by
its **entry count plus the characters of its first entry**, compared against text
rasterised at patch time. The numbers are the game's own character set and match
exactly: ACHETER is `[299,301,306,303,318,303,316]` in the ROM and in RAM.

Every menu worth drawing has a first entry free of placeholders, which matters -
the player's own PC row expands to their name and could never be matched.

### What the default archive gives away

When a script passes no msgdata (`ScrCmd_064`), `ov01_021EDAFC` loads
**`msg_0191`** itself. That is where every one of these menus' words lives:
321/322/323 for the shop, 62/63/64/75 for the PC list, 73/74/65/66 for the PC's
item menu, 67-72 for the box menu.

### Why the shop was drawn alone at first

Storage, not difficulty. The four label sets needed **15.3 KB** together; after the
shop there were about 3.6 KB left between free ITCM and the blob reservation. The
PC box alone needed 8.3 KB and 269 VRAM tiles against the 263 free below the
map-name window, because its entries are two lines tall. Compressing the tile
pool (it is almost all paper) and moving the strips down to tile `0x84` is what
let all four in.

### The first entry is not enough (v0.3)

The full decompilation's script corpus turned up a menu the key could not tell
apart: the Pokéathlon Dome's marts are `msg_0191` 321 / 324 / 323 - BUY / INFO /
SEE YA - three entries with the shop's first entry, so they were drawn as
ACHETER / VENDRE / QUITTER. Each record now also carries a 16-bit hash of every
other entry the patcher can know in advance (`_menu_hash` in `labels.py`,
`OneScreen_ListHash` in the hook - the same function, tested against each other
under emulation in `tools/test_hook.py`). Entries it cannot know, such as your own
PC's row, are left out by a per-record skip mask.

The menu pointer is read from `TouchscreenChoiceMenuData.menu` (`+0x0C`) rather
than `+0x3A0`. Both held the same pointer in every savestate, but `+0x3A0` is
really `selectionCallbackArg`, which `ScrCmd_MenuExec` fills in - and the move
tutor's list (`ScrCmd_MoveTutorChooseMove`) enters the list state without setting
it, leaving whatever the previous menu put there.


### The game's own top-screen list (v0.3)

The full decompilation shows HGSS never dropped Diamond and Pearl's top-screen list
window. Two script-command families build a `ScriptMenu` the same way -
`ScriptListMenuInit` / `ScriptListMenuItemAdd` (68-70) and `MenuInit` / `MenuItemAdd`
(749-751) - and differ in where they keep it and how they show it:

| command | shows it with | waits with |
|---|---|---|
| 752 `ScrCmd_MenuExec` | the touch choice app, state 7 | `NativeScript_WaitMenuExec` |
| 71 `ScrCmd_ScriptListMenuExec` | `ScriptMenu_ShowList`, a window on `MAIN_3` | `NativeScript_WaitMultichoice` |

HGSS's scripts use 752 for nearly every list (146 sites in 49 scripts). So v0.3 points
table entry 752 at `OneScreen_MenuExec`, which gives any menu it does not draw itself to
`ScriptMenu_ShowList` - the game's window, cursor, scrolling past eight entries and help
text - instead of letting it take the screen. The choice app stays idle on the hidden
screen, which `OneScreen_ScriptMenu` already routes as "keep the world".

What had to line up, all from the decompilation:

- **The menu.** `ScrCmd_MenuExec` takes it from the choice controller's own slot
  (`+0x0C`); the redirect reads it from there, after checking the controller is the running
  app 3, idle, and points back at this field.
- **The result.** `ScriptMenu_Init` already set `*ret_p = 0xEEEE`; the redirect sets it again.
  On A both paths write the entry's value. On **B** they differ: the touch list picks the
  last entry, `ScriptMenu_ListTask` writes `0xFFFE`. Scripts are written for the touch list -
  the apricorn juice stand and the fossil menus test for the last entry's value and carry on
  with anything else as if something had been chosen - so `OneScreen_WaitList` replaces
  `0xFFFE` with the last entry's value.
- **Freeing it.** `ScriptMenu_CloseList` frees the menu itself; `NativeScript_WaitMenuExec`
  would free it a second time, so the redirect installs its own wait.
- **Placement.** The scripts' x/y were written for the top screen and always clear the
  dialogue box, but nothing stops a long translation running past column 31, so x is
  pulled left if `ScriptMenu_GetListItemsWidth` says it must be.
- **What it will not take.** Recognised menus (the shop, the PC) keep the themed panel.
  Entries with a line break or a control code - about 40 sites: Battle Frontier prize
  shops, Game Corner TMs, coins and prize Pokémon, drink machines, rankings, Pokéathlon
  courses, the day-care's level column, the mulch shop's price column - keep the touch
  screen, because `ListMenu` prints one 16-pixel row per entry. (Control codes survive into
  the menu's strings: `StringExpandPlaceholders` copies every one that is not a `STRVAR`.)
  The move tutors' lists never reach the redirect at all: `ScrCmd_MoveTutorChooseMove` (653)
  builds its own menu and opens the touch list directly.
- **Room.** The list's window goes on `MAIN_3`, the layer the script's own boxes use, and
  on the touch screen the two never met. Mom's savings menu opens `ShowSavingsBox 1,1` - a
  16x8 window at (1, 1) drawn from tile 1 - then asks for a list at (1, 1), whose window
  takes tiles from `0x3D`. So before handing over, `OneScreen_ListRoom` reads the layer's
  tilemap buffer: anything already inside the list's rectangle or its one-tile frame, or
  anywhere using a tile the window would be given, keeps the touch list. The dialogue box
  (tiles from `0x237`, rows 18-23) never trips it; every corpus list ends above row 18.
  A themed panel left over from the menu before is cleared first, so it does not count.

The patcher finds all of it by shape: the 853-entry table (entries 0 and 1 are
`movs r0, #0; bx lr`), then the calls and literal pools of entries 752 and 71, cross-checked
against ARM9 addresses that do not move between regions (`MenuExec_PrintItemHelp`,
`NativeScript_WaitMenuExec`, `NativeScript_WaitMultichoice`) and `ShowList`'s retail
prologue. Any mismatch and the table is left alone.

## Who owns the VRAM you just drew into

Four separate bugs in this project have been the same mistake: **assuming what we
drew is still there.** Tiles, palette and tilemap are each reclaimed
independently, by different things, at different times. Worth reading before
drawing anywhere new.

**The tilemap is not yours - the game keeps a shadow copy.** Every layer has a
buffer in main RAM which the game commits wholesale whenever its contents change;
reprinting a menu option's description does exactly that. Cells written straight
to VRAM are not in that copy, so the commit erases them and the panel reappears a
frame later. This is what made the PC menus flash on every cursor move.

Proved rather than guessed: with the box menu open, `bgs[3].tilemapBuffer` held
**zeros across the whole panel rectangle**. The fix is to write the panel into
that buffer as well as VRAM, so the next commit repaints it instead.

```
FieldSystem +0x08 -> BgConfig
    +0x08 Background bgs[8], 44 bytes each
        +0x00 tilemapBuffer, +0x04 bufferSize (0x800 for a 32x24 map)
    so MAIN_3's buffer pointer is at BgConfig + 0x8C
```

**The tiles and the palette are not yours either.** Any application that runs in
between - the photo album, the mailbox, the bag - may take the same tiles and
palette slots. A cached "already uploaded" flag then leaves the tilemap pointing
at whatever that application left, which draws as a **solid black box** rather
than as anything obviously wrong.

Two guards, because one is not enough: forget the upload when the running
application is not the field, *and* forget it whenever no panel was up recently.
The second catches whatever is a field task rather than an application, which is
not always obvious from the outside.

**A cached upload flag must record WHICH thing is loaded, not merely that
something is.** A single boolean meant stepping from the PC's list into its box
menu kept the previous menu's strips and drew the new tilemap over them.

**Clear on change, not only on close.** Panels are not all the same size, so a
smaller one drawn where a larger one was leaves the old edges on screen.

## Other menus that could be drawn next

`msg_0191` is the archive the script list menus default to, so scanning it for
short strings enumerates the candidates. Everything below already works with the
renderer in place - each needs a label set and its first entry as an identifying
key, nothing more.

Worth doing, common in ordinary play:

| menu | msg_0191 entries |
|---|---|
| GTS / trade counter | 133 DEPOSER POKeMON, 134 CHERCHER POKeMON, 130 INFOS, 131 ECHANGE, 132 RETOUR |
| Move Deleter / Tutor / Name Rater | short confirm lists |
| Union Room | 168 SALUER, 169 DISCUTER, 170 TCHAT |

Occasional or optional content:

| menu | msg_0191 entries |
|---|---|
| Battle Tower / Frontier | 6-10 COMBAT SOLO / DUO / MIXTE / MULTI / 50 |
| Pokeathlon | 271-279 |
| Shard trading | 205-208 TESSON ROUGE / BLEU / JAUNE / VERT |
| Bug Contest | 199 INSCRIRE, 200 INFORMATIONS, 201 QUITTER |
| Safari Zone | 194 REGLES DE BASE, 195 SHOW CAPTURE, 196 STOCKAGE |
| Fossil selection | 159-165, seven fossil names |

Two caveats. Several of these live in the special zones - Safari, the Bug
Contest, the Pokeathlon - so each needs checking on its own. And every
`OUI / NON` prompt (42/43, 46/47) goes through the field yes/no path instead, not
this renderer.

**The day-care is not on this list, and the first version of it was wrong to say
so.** msg_0191 132/133/134 look like a deposit/retrieve menu but belong to the
GTS counter - OFFER POKeMON / SEEK POKeMON / INFO / TRADE / EXIT in English. The
day-care itself is `msg_0439`, and its prompts are `{YESNO}`s, covered by the field
yes/no path. Its one list - which Pokémon to take back - is msg_0191 136-138, built at
runtime from the Pokémon's own names and levels, so it could never be rasterised.

Worth taking as the general lesson: a plausible-looking run of short strings in
msg_0191 is not evidence that a menu exists, or of which feature owns it. Check
the feature's own message file before building anything.

The honest read after that correction: none of these is clearly worth the label
budget and the play-test round-trips. The GTS needs servers that no longer exist,
the Pokeathlon and Safari are special-zone content, and the rest are one-offs
where swapping costs nothing.

## Still outstanding

Nothing known. The X menu's shadow-copy bug is fixed: `OneScreen_MirrorRect`
copies the finished panel out of VRAM and into the game's own tilemap after
drawing, and clears it from there on the way out. Done as a copy after the fact
rather than by writing both destinations inside the drawing loops, which have no
spare registers and had already been play-tested.


## Applications that live in overlays

The move relearner is the Blackthorn tutor's move list: **overlay 68,
`MoveRelearner_Main`**. It sets no display routing of its own, so it keeps
whatever it inherits - and once field prompts began holding the world on top, it
inherited that and opened on the bottom screen. Teach a move and the routing left
behind afterwards happened to be the other way, which is why it looked
intermittent rather than broken.

Two things make an overlay-resident application different from an ARM9 one:

- **It has no static `OverlayManagerTemplate` to take over.** `launch_application.c`
  builds that on the stack, so there is nothing in ROM to patch. It is matched on
  the live exec pointer instead.
- **Overlay code MOVES between regions.** ARM9 code addresses are identical
  across IPGF, IPKF and IPKE; overlay ones are not. US loads overlay 68 0x20
  lower and the function sits at 0x021E5B6C rather than 0x021E5B8C. A written-down
  address would have worked on French and silently failed everywhere else - which
  is exactly what the first attempt did, and the patcher said so.

So these are found by searching the overlay for the function's own bytes, with the
`BL` instructions masked out because their encodings are target-relative. Exactly
one match in each of the three ROMs.

### A bounds check that did not bound anything

Adding a third entry to `app_table` black-screened the game on boot. The table
reserved two entries and a terminator, `OneScreen_SetSwap` began immediately
after it, and the fill overwrote that routine's first instructions - a routine
the hook calls constantly.

`fill_app_table` did check its write, but against the size of the *payload*, which
is always true. It now stops at `OneScreen_AppTableEnd`, and adding one entry too
many is rejected with a message naming the file to edit. A check that cannot fail
is worse than no check: it reads as safety while providing none.

## The opening cinematic

Overlay 60, four scene functions in sequence. Three of them show content on the
wrong screen, and the corrections are not uniform - two want engine A raised, one
wants engine B, so each carries its own value rather than a shared "swap".

**It is the one part of this patch driven by elapsed time.** Diffing a good frame
against a bad one inside a single scene leaves exactly ONE differing byte: a frame
counter in the scene's own data block. There is no scene id and no flag, so the
halves cannot be separated any other way. That is defensible here in a way it
would not be elsewhere - a cinematic's scenes really are defined by time - but the
thresholds (102, 1090, 1867) are measured numbers, taken on frames where the
screen is black so being a frame out cannot be seen. Play-tested on IPKE as well
as IPGF, so the timing does hold across regions.

**The last sequence outlives the application that starts it.** At its final frame
nothing is registered in the application slot at all, so there is no scene counter
left to test. It is held instead on a tick counter beside that slot
(`state_block + 0x2C`, about twice the scene rate) which keeps running after the
intro tears down. The hold expires on its own and is dropped the moment the field
system appears, so it cannot follow the player into the game.

## Four attempts on one bug: the save screen

Choosing SAUVER does not start an application. The start menu task stays alive in
`START_MENU_STATE_SAVE` while the save box runs, so the app never changes, and
every guard that keys off an app change silently does nothing. That single fact
produced four separate failures, each hidden behind the last:

1. **The panel held the world on top** while the save box sat underneath it.
   Drawing now stops for states 6 and 7 and the caller swaps instead.
2. **The panel came back blank.** The save screen takes those tiles and that
   palette; the "already uploaded" flag still said otherwise. Every other entry on
   the menu is a separate application, so Poll's app-change guard covered those -
   which is why only SAUVER showed it.
3. **The panel came back frozen.** `sm_drawn` was answering two questions - "are
   the tiles uploaded" and "is a panel on screen" - so clearing it to force a
   re-upload also told the wipe there was nothing to remove. The stale panel then
   survived in the game's shadow tilemap, being re-committed every frame. Split
   into `sm_drawn` and `sm_shown`.
4. **Cancelling left no panel at all.** `menu_swapped` is set only by an X press,
   and the save had cleared it; saving looked fine only because the menu closes
   afterwards anyway. The latch now re-arms from the game's own state whenever the
   menu is in `START_MENU_STATE_HANDLE_INPUT` - narrower than "the menu exists" on
   purpose, since X and B move it to the close state in the same frame the game
   reads the press.

The root cause of (3) and (4) together: the X menu kept three pieces of state that
each half-answered "is the menu up?". Deriving it from the game's own state is
what it should have done from the start.

### And one that was not a bug at all

The fix for (4) did nothing on its first build, because it was placed *before* the
label the preceding branch jumps to - the B path branches to `15` rather than
falling through, so the block was unreachable. It assembled cleanly and cost a
test round.

Worth the habit: after a control-flow edit, disassemble the built payload and
confirm the call is actually emitted where it should be. Checking
`OneScreen_Poll` for a `BL` to the new routine takes seconds and is the only way
to catch dead code, which no build error will ever report.


## Colour: what the patch owns, and what it only borrows

Two different mechanisms, and the difference decides how hard each is to change.

**The panels own their palettes.** The X menu, the shop's and the PC's menus ship
two 16-entry palettes in the label blob and copy them into main-BG slots 7 and 8.
Nothing else writes those slots, so a theme is a patch-time swap of 64 bytes:
every offset, record field and tile is identical whichever theme is chosen. The
three themes produce blobs of exactly the same size, differing only inside the
palette regions.

**The selected band is borrowed.** Every prompt - battle commands, battle yes/no,
evolution, field yes/no, Oak's yes/no and gender - paints its highlight with
palette **index 12**, and stock, the patch never wrote that entry. It relied on
the salmon the game happens to keep in the battle message palette, which is why a
highlight was salmon in battle and a different colour elsewhere.

Theming it means writing palettes the patch did not previously write:

| prompt | palette | address |
|---|---|---|
| Oak | 6 | `0x050000D8` |
| battle, evolution | 11 | `0x05000178` |
| field yes/no | 12 | `0x05000198` |

Written per frame from each draw site while a prompt is up - never from the frame
hook unconditionally. Palette memory is shared, and colouring 11 or 12 outside a
prompt would recolour whatever else happened to be using index 12 at the time.

`_render`'s `invert` flag is orthogonal to all of this: it does not change the
band, only the glyphs on it, dropping the shadow and turning ink to paper. Oak's
two prompts used it because the band used to be whatever saturated colour his
intro was showing. A theme picks a light colour deliberately, so inverting made
his selected choice white while every other prompt's was black - it is off now.

### Oak's prompts used to flash - solved with the full decompilation (v0.3)

The band behind Oak's selected choice alternated with a salmon red, and with white, about
once a second. This section once blamed a race with the print task and then the multichoice
controller; both were wrong, and v0.2b left it alone. The full decompilation names the
real culprit in one look.

`OakSpeech_InitMsgPrinter` starts a **`PaletteBlink`** on top-screen BG palette 6 - the
dialog window's own palette - to animate the "look at the bottom screen" icon, whose colours
are 11-14 (`src/palette_blink.c`). It is a SysTask on the main queue, which runs *after* the
overlay manager and therefore after `OneScreen_OakExec`, and on ticks 0 and 24 of its
32-tick cycle it writes **all sixteen** colours of palette 6 back to palette RAM from its own
copy. The band is palette 6 colour 12, so on tick 0 the copy's `0x62FF` - the salmon - came
back, and on tick 24 colour 12 went to the copy's white paper. The main loop runs at about
30 Hz, so that is one flash of each per ~1.07 s.

Two consequences that shaped the fix:

- **Moving the band to another colour does not help.** The blink writes every colour, so
  any index would be reset from its snapshot twice a cycle (to black, for 7-10).
- **The blink has nothing to show in those states anyway.** The icon it animates is
  suppressed in exactly the three questions that draw a band.

So `OneScreen_OakBlink` holds it still - `state = PALETTE_BLINK_PAUSE` - while states 65,
69 or 98 are up, and sets `PALETTE_BLINK_RESTART` when they end, but only if it was the
one that paused it. It never writes `END`, which would destroy the task. Before writing a
byte it checks the struct is the one expected: in main RAM, palette 6, top screen, no
`PaletteData`, and its `apply` pointer equal to `PaletteBlink_LoadMainBgPltt`
(`0x020165A5`, ARM9, the same in every region).

The same research found the hook's own damage in the same window. On every frame outside
the three prompts, the hook held an all-paper image over the dialog's columns 24-26, on the
belief that text never reaches them. Only messages carrying the `{YESNO}` icon keep clear of
that corner; with the US text, five of Oak's lines run past x = 192 (`msg 2`, `3`, `6`, `36`
and `43`) and lost their last letters once printing paused, and the tutorial's own icon was
painted out as well. That wipe is gone; our box is taken down once when a prompt ends.

