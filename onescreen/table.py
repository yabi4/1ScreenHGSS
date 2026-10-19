"""Which display-routing sites to flip, and which to leave alone.

Overlay identities come from pret/pokeheartgold's `main.lsf`, which uses the same
overlay numbering as the retail ROM (verified: ov12 = battle, ov1 = field).

Anything not listed defaults to FLIP - the whole point is that bottom-screen UI
should come to the top, so the exceptions are the interesting part.
"""

FLIP, KEEP, TOUCH = "FLIP", "KEEP", "TOUCH"

# Per-SITE decisions, keyed by the address of the POWCNT1 LDR. These win over the
# per-module table below.
SITE_INTENT = {
    # 0x02022D3C is the game's shared display-select helper: it reads a global
    # flag at 0x021D1195 and applies bit 15. ~90 call sites use it, INCLUDING
    # ov001 (the field). Flipping it inverts the overworld too - verified by
    # building an ARM9-only variant, which put the touch menu fullscreen on top
    # and the world underneath.
    0x02022D3E: KEEP,

    # Boot-time graphics init, called once from NitroMain; establishes the
    # initial routing that the field inherits.
    0x0201A2A2: KEEP,
}

# Overlay identities, for the ones that contain a flippable site. Named after
# the objects the full decompilation's main.lsf links into each overlay.
OVERLAY_NAMES = {
    5: "link battle preview / VS screens",
    12: "battle system - commands, HP bars, input, cursors",
    14: "PC box",
    15: "bag",
    17: "berry pots app",
    18: "pokedex app",
    37: "Union Room group drawing (stylus)",
    51: "trainer card - main interface",
    52: "trainer card - signature (stylus drawing)",
    54: "options app",
    56: "mail viewer",
    57: "Ball Capsule editor",
    59: "apricorn box screens",
    64: "Hall of Fame showcase",
    67: "Battle Room results",
    68: "move relearner",
    70: "GTS",
    71: "trade sequence",
    72: "Nintendo WFC connection",
    73: "record mixing",
    74: "main menu application",
    80: "battle frontier system",
    82: "Battle Hall",
    83: "Battle Castle",
    85: "Spin Trade",
    86: "Frontier records",
    87: "scratch-off cards",
    98: "Pokeathlon utilities",
    100: "pokegear - main interface",
    101: "pokegear - map / phone / radio",
    102: "Easy Chat",
    103: "mailbox",
    108: "Safari Zone area customizer",
    109: "photo album",
    110: "Ruins of Alph sliding puzzle (stylus)",
    111: "Bug Contest - swap Pokemon",
    112: "Pokewalker",
    113: "Unown report",
    122: "voltorb flip minigame",
}

MODULE_INTENT = {
    # The battle scene must stay on top while a turn resolves. The command menu
    # is swapped in dynamically by the ITCM hook instead - see src/hook.s.
    "ov012": KEEP,

    # Stylus-mandatory: the UI must stay on the physical digitizer (lower LCD).
    "ov052": TOUCH,   # trainer card signature - freehand drawing
    "ov110": TOUCH,   # Ruins of Alph sliding puzzle
    "ov037": TOUCH,   # Union Room group drawing - a canvas drawn on with the
                      # stylus (drawing_session.c), wireless multiplayer only
}

# Field/overworld overlays. None of them contain a flippable site, which is why
# blanket-flipping the overlays cannot disturb the overworld.
FIELD_OVERLAYS = (1, 2, 3, 27)


def intent_for(module: str, addr=None) -> str:
    if addr is not None and addr in SITE_INTENT:
        return SITE_INTENT[addr]
    return MODULE_INTENT.get(module, FLIP)


def describe(module: str) -> str:
    if module == "arm9":
        return "ARM9 static (boot / low-level display setup)"
    try:
        return OVERLAY_NAMES.get(int(module[2:]), "unidentified")
    except ValueError:
        return "unidentified"
