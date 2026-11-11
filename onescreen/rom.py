"""Turn a stock HeartGold/SoulSilver dump into a single-screen build.

Everything happens in memory: the ROM is unpacked, the ARM9 and overlays are
BLZ-decompressed, the display-routing sites are found and rewritten, the ITCM
payload is injected, and the result is repacked.

Patched modules are stored **uncompressed** (`compressed_static_end = 0` for the
ARM9, compression flag cleared for overlays). Both are standard, reversible
transforms; they cost ~300 KB of the ~7.5 MB of free ROM space and avoid any BLZ
recompression risk.
"""

import hashlib
import json
import pathlib
import struct

import ndspy.code
import ndspy.codeCompression
import ndspy.rom

from . import inject, labels, origin, regions, sites, table, themes

PAYLOAD_DIR = pathlib.Path(__file__).resolve().parent / "payload"
ORIGIN_PAYLOAD_DIR = PAYLOAD_DIR.parent / "payload_origin"

# Dumps this has been built and tested against. Anything else still patches, but
# is reported as unverified rather than silently trusted.
KNOWN = {
    "IPGF": ("Pokemon Version Argent SoulSilver (France)",
             "6ed98d446eb65861c71fc5f94bdc35691667f665"),
    "IPKF": ("Pokemon Version Or HeartGold (France)",
             "dba64620a959d5f69ed1cf3e43fcfcf2786d417e"),
    "IPKE": ("Pokemon HeartGold Version (USA)",
             "4fcded0e2713dc03929845de631d0932ea2b5a37"),
}

# Regions sharing the same code layout. HG/SS FR were measured byte-identical in
# ARM9 length and overlay RAM bases, and 114 of 129 overlays are identical, so
# the same edits apply. Other languages are untested - the scanner finds sites by
# instruction shape, so they may well work, but nothing is promised.
SUPPORTED_PREFIXES = ("IPG", "IPK")


def _text(v):
    return bytes(v).decode("ascii", "replace") if isinstance(v, (bytes, bytearray)) else str(v)


def load_payload(directory=None):
    directory = directory or PAYLOAD_DIR
    meta = json.loads((directory / "hook.json").read_text())
    # Addresses are stored as hex strings so they stay readable and cannot be
    # mistyped as decimal.
    meta["load_addr"] = int(meta["load_addr"], 16)
    meta["symbols"] = {k: int(v, 16) for k, v in meta["symbols"].items()}
    return (directory / "hook.bin").read_bytes(), meta


def identify(rom_bytes: bytes):
    """Return (gamecode, title, known_name_or_None, sha1)."""
    rom = ndspy.rom.NintendoDSRom(rom_bytes)
    code = _text(rom.idCode)
    sha1 = hashlib.sha1(rom_bytes).hexdigest()
    known = KNOWN.get(code)
    if known is None and sha1 == origin.SHA1:
        known = ("Pokemon Origin HeartGold v4.0.3 (EN 1.0.0-rc8)", origin.SHA1)
    return code, _text(rom.name).rstrip("\0 "), known, sha1


def patch(rom_bytes: bytes, log=print, auto_battle=True,
          theme=themes.DEFAULT_THEME, battle_take_over=True):
    """Return the patched ROM image.

    `theme` colours what the patch draws - the panels' palettes and the band
    behind a highlighted choice. It changes no sizes or offsets.

    `battle_take_over=False` leaves the battle application's own exec pointer
    alone, so the game runs the battle by itself. A bisect aid.
    """
    code, title, known, sha1 = identify(rom_bytes)
    log(f"  ROM      : {title}  [{code}]")
    log(f"  SHA-1    : {sha1}")

    is_origin = sha1 == origin.SHA1

    if not code.startswith(SUPPORTED_PREFIXES):
        raise SystemExit(
            f"{code} is not a Pokemon HeartGold/SoulSilver ROM. This patch only "
            "targets HGSS (game codes IPKx / IPGx).")
    if known and sha1 == known[1]:
        log(f"  Verified : {known[0]}")
    elif known:
        log(f"  WARNING  : {code} recognised but the SHA-1 does not match the "
            "tested dump. Continuing anyway; report problems.")
    else:
        log(f"  NOTE     : {code} has not been tested (only IPGF/IPKF/IPKE have). "
            "The scanner works by instruction shape, so this may still be fine.")

    rom = ndspy.rom.NintendoDSRom(rom_bytes)

    arm9 = bytearray(ndspy.codeCompression.decompress(rom.arm9))
    inject.check_module_params(arm9)

    overlays = rom.loadArm9Overlays()
    modules = [("arm9", 0x02000000, bytes(arm9))]
    ov_data = {}
    for ovid, ov in sorted(overlays.items()):
        ov_data[ovid] = bytearray(ov.data)
        modules.append((f"ov{ovid:03d}", ov.ramAddress, bytes(ov_data[ovid])))

    found = sites.find(modules)
    chosen, skipped = [], []
    for s in found:
        if table.intent_for(s["module"], s["addr"],
                            origin_build=is_origin) == table.FLIP:
            chosen.append(s)
        else:
            skipped.append(s)

    log(f"  Sites    : {len(found)} found, {len(chosen)} flipped, {len(skipped)} left alone")
    for s in skipped:
        log(f"             skip {s['module']:<7} {s['addr']:#010x} "
            f"[{table.intent_for(s['module'], s['addr'], origin_build=is_origin)}] "
            f"{table.describe(s['module'])}")

    by_module = {}
    for s in chosen:
        by_module.setdefault(s["module"], []).append(s)

    sites.apply(arm9, by_module.get("arm9", []))
    inject.set_uncompressed(arm9)

    payload, meta = load_payload(ORIGIN_PAYLOAD_DIR if is_origin else None)
    extra_overlays = []
    if auto_battle:
        hook_sites = {}
        key_sites = {}
        evo_sites = {}
        if is_origin:
            # Origin HeartGold has its own layout; onescreen/origin.py holds
            # every address it needs, each one checked against the ROM.
            values, delta = origin.resolve(arm9, overlays, meta=meta, log=log,
                                           theme=theme,
                                           battle_take_over=battle_take_over)
            # The Oak speech app's exec pointer is a word in its own overlay,
            # not an ARM9 template entry, so it is patched here.
            extra_overlays = origin.patch_oak_exec(ov_data, overlays, meta, log=log)
            if not extra_overlays:
                values["origin_oak_exec_orig"] = 0
            battle_ov = origin.BATTLE_OVERLAY
            origin.patch_evolution_party(
                ov_data[battle_ov], overlays[battle_ov].ramAddress,
                meta["symbols"]["OneScreen_OriginEvolutionPartyMon"])
            extra_overlays.append(battle_ov)
            log("  Evolution: bound the post-battle scan to occupied party slots")
            apps = origin.app_table(arm9, overlays)
            hook_sites = dict(site=origin.MAIN_LOOP_SITE,
                              orig_fn=origin.ORIG_LOOP_FN)
            key_sites = dict(site=origin.KEY_READ_SITE,
                             orig_fn=origin.ORIG_KEY_READ_FN,
                             button_call=origin.BUTTON_MODE_CALL,
                             button_fn=origin.BUTTON_MODE_FN)
            evo_sites = dict(literal=origin.EVOLUTION_TASK_LITERAL,
                             orig=origin.EVOLUTION_TASK_ORIG)
            values["evolution_task_orig"] = origin.EVOLUTION_TASK_ORIG
        else:
            # The functions the hook calls on the game's behalf. They are the
            # same in every retail region.
            values, delta = regions.resolve(arm9, overlays)
            values["orig_loop_fn"] = inject.ORIG_LOOP_FN | 1
            values["read_keys_orig"] = inject.ORIG_KEY_READ_FN | 1
            values["apply_button_mode"] = inject.BUTTON_MODE_FN | 1
            # The evolution scene's main-queue task, the one the hook wraps.
            values["evolution_task_orig"] = inject.EVOLUTION_TASK_ORIG
            # The battle menu is the retail one, read out of the BattleSystem.
            values["battle_mode"] = 0
            values["origin_menu_ptr"] = 0
            values["origin_menu_flag"] = 0
            values["origin_cursor"] = 0
            values["origin_state"] = 0
            values["origin_battle_data"] = 0
            # Retail reads its prompt and CANCEL state from BattleInput.
            values["origin_prompt_cursor"] = 0
            values["origin_cancel_flag"] = 0
            values["origin_battle_vblank"] = 0
            values["origin_evo_get_mon"] = 0
            values["origin_evo_done"] = 0
            # The start menu's struct is the retail one, offsets and all.
            values["startmenu_state_off"] = 0x26
            values["startmenu_inhibit_off"] = 0x34C
            # Origin's Oak speech app has no exec pointer in an ARM9 template,
            # so the retail build has nothing to record there.
            values["origin_oak_exec_orig"] = 0
            # Take over these apps' exec pointers in their OverlayManagerTemplates,
            # so the hook is handed &proc_state - the screen level - every frame
            # instead of having to find the manager in RAM. The templates live in
            # ARM9 static data and are located by shape, so this is region-neutral.
            for label, ovy_id, field, symbol, effect, in_arm9 in (
                    ("Pokedex", 18, "dex_exec_orig", "OneScreen_DexExec",
                     "area map will stay on the bottom screen", False),
                    ("PC box", 14, "pc_exec_orig", "OneScreen_PcExec",
                     "box screens will stay on the bottom screen", False),
                    ("Fly map", 101, "map_exec_orig", "OneScreen_MapExec",
                     "the flight animation will stay on the bottom screen", False),
                    ("Oak", 53, "oak_exec_orig", "OneScreen_OakExec",
                     "the opening speech will stay inverted", False),
                    # The battle's init/exec/exit are ARM9 wrappers, not ov12 code,
                    # so this one needs the arm9_resident shape. It is what hands the
                    # hook the live BattleSystem every frame, which the top-screen
                    # command menu is built on.
                    ("Battle", 12, "battle_exec_orig", "OneScreen_BattleExec",
                     "the battle command menu will stay on the bottom screen", True)):
                tmpl = regions.find_overlay_template(arm9, overlays, ovy_id,
                                                     arm9_resident=in_arm9)
                if tmpl:
                    tmpl_addr, _init, orig_exec, _exit = tmpl
                    values[field] = orig_exec
                    struct.pack_into("<I", arm9, (tmpl_addr + 4) - 0x02000000,
                                     meta["symbols"][symbol] | 1)
                    log(f"  {label:<9}: template {tmpl_addr:#010x}, exec "
                        f"{orig_exec:#010x} -> {symbol}")
                else:
                    values[field] = 0
                    log(f"  {label:<9}: template not found; {effect}")
            intro_a, intro_b, intro_c = regions.find_intro_scenes(overlays)
            values["intro_a_exec"] = intro_a
            values["intro_b_exec"] = intro_b
            values["intro_c_exec"] = intro_c
            if intro_a and intro_b and intro_c:
                log(f"  Intro    : scenes {intro_a:#010x} {intro_b:#010x} {intro_c:#010x} "
                    f"put on the top screen")
            else:
                log("  Intro    : scenes not found; the opening cinematic is left alone")

            # The colour a selected choice is drawn on. Zero leaves the game's own
            # palettes untouched, which is what every build did before themes.
            values["theme_band"] = themes.get(theme)["band"]

            # NPC lists the patch does not draw itself go to the game's own
            # top-screen list instead of taking the screen: script command 752 is
            # pointed at OneScreen_MenuExec, and the move tutors' 653 at
            # OneScreen_TutorExec. Found by shape and cross-checked; anything
            # unexpected and the lists swap, the safe fallback for a ROM we cannot
            # vouch for - there is no option to ask for that any more.
            for field in ("menu_exec_orig", "open_list", "string_width",
                          "setup_native", "tutor_exec_orig"):
                values[field] = 0
            native, redirects, detail = regions.resolve_native_lists(arm9, overlays)
            if native:
                values.update(native)
                for site, symbol in redirects:
                    struct.pack_into("<I", arm9, site - 0x02000000,
                                     meta["symbols"][symbol] | 1)
                log(f"  Lists    : the game's top-screen list; {detail}")
            else:
                log(f"  Lists    : {detail}; NPC lists keep the touch screen")
            apps = regions.check_app_table(arm9, overlays)

        payload = inject.fill_config(payload, meta["symbols"]["OneScreen_Config"],
                                     meta["load_addr"], values)

        # The top-screen command labels, rasterised from this ROM's own message
        # archive and font so the build speaks whatever language the dump does.
        # If anything about that data is not what we expect we ship without
        # them: the hook checks the blob's magic and simply draws nothing, which
        # costs the labels but leaves every other behaviour intact.
        try:
            mf = labels.MessageFiles(origin.MSG_FILES, origin.FONT_FILE) \
                if is_origin else None
            if mf is not None:
                origin.check_messages(rom)
            blob = labels.build(rom, log=log, theme=theme, overlays=overlays,
                                mf=mf,
                                box=labels.ORIGIN_BOX if is_origin else None,
                                layout_overlays=origin.touch_layout_overlays(overlays)
                                if is_origin else None,
                                oak_gender_rows=origin.OAK_GENDER_ROWS
                                if is_origin else None)
            payload = inject.fill_labels(payload,
                                         meta["symbols"]["OneScreen_Labels"],
                                         meta["load_addr"], blob)
        except labels.LabelError as exc:
            log(f"  Labels   : NOT BUILT - {exc}")
            log("             the battle menu will not be drawn on the top screen")

        payload = inject.fill_app_table(payload,
                                        meta["symbols"]["OneScreen_AppTable"],
                                        meta["load_addr"], apps,
                                        meta["symbols"].get("OneScreen_AppTableEnd", 0))
        for name, callback, _swap, ok in apps:
            log(f"  App      : {name:<12} {callback:#010x} "
                + ("verified" if ok else
                   "CODE DOES NOT MATCH - entry dropped, this app will not swap"))
        inject.patch_main_loop(arm9, meta["symbols"]["OneScreen_Frame"],
                               **hook_sites)
        inject.patch_key_read(arm9, meta["symbols"]["OneScreen_ReadKeys"],
                              **key_sites)
        inject.patch_evolution_task(
            arm9, meta["symbols"]["OneScreen_EvolutionTask"], **evo_sites)
        arm9 = inject.add_autoload_block(arm9, payload, meta["load_addr"])
        log(f"  ITCM     : {len(payload)} bytes at {meta['load_addr']:#010x} "
            f"(payload v{meta['payload_version']}), main loop "
            f"{hook_sites.get('site', inject.MAIN_LOOP_SITE):#010x}, keypad read "
            f"and evolution task hooked")
        log(f"  Region   : data shifted {delta:+#x} from the French reference")
        for name in inject.CONFIG_FIELDS:
            log(f"             {name:<15} {values[name]:#010x}")
    else:
        log("  ITCM     : skipped (--no-hook): static screen flips only")

    rom.arm9 = bytes(arm9)

    touched = []
    for ovid, ov in sorted(overlays.items()):
        picks = by_module.get(f"ov{ovid:03d}")
        if not picks and ovid not in extra_overlays:
            continue
        buf = ov_data[ovid]
        if picks:
            sites.apply(buf, picks)
        ov.data = bytes(buf)
        ov.compressed = False
        rom.files[ov.fileID] = ov.save(compress=False)
        touched.append(ovid)
    rom.arm9OverlayTable = ndspy.code.saveOverlayTable(overlays)
    log(f"  Overlays : {len(touched)} rewritten, stored uncompressed")

    return bytes(rom.save())
