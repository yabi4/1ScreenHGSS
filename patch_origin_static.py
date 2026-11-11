from pathlib import Path
import hashlib
import ndspy.rom
import ndspy.code
from onescreen import sites, table

src = Path(r"C:\HGSS1Screen\Origin_HeartGold_v4.0.3_EN_v1.0.0-rc8.nds")
dst = src.with_name("Origin_HeartGold_STATIC_1Screen_TEST.nds")

expected = "a54a647599d59ed0060dfc4375c289d6e041318a"
data = src.read_bytes()

if hashlib.sha1(data).hexdigest() != expected:
    raise SystemExit("Falsche ROM-Version! Abbruch.")

rom = ndspy.rom.NintendoDSRom(data)
original_arm9 = bytes(rom.arm9)
overlays = rom.loadArm9Overlays()

modules = [
    (f"ov{oid:03d}", ov.ramAddress, bytes(ov.data))
    for oid, ov in sorted(overlays.items())
]

found = sites.find(modules)
chosen = [
    s for s in found
    if table.intent_for(s["module"], s["addr"]) == table.FLIP
]

print("Erkannte Overlay-Sites:", len(found))
print("Geplante FLIPs:", len(chosen))
print("Unveraendert:", len(found) - len(chosen))

if len(found) != 82 or len(chosen) != 80:
    raise SystemExit("Unerwartete Fundstellen. Kein Patch erstellt.")

changed = 0

for oid, ov in sorted(overlays.items()):
    name = f"ov{oid:03d}"
    picks = [s for s in chosen if s["module"] == name]

    if not picks:
        continue

    buf = bytearray(ov.data)
    sites.apply(buf, picks)

    ov.data = bytes(buf)
    ov.compressed = False

    rom.files[ov.fileID] = ov.save(compress=False)
    changed += 1

    print(f"{name}: {len(picks)} FLIPs")

rom.arm9OverlayTable = ndspy.code.saveOverlayTable(overlays)

if bytes(rom.arm9) != original_arm9:
    raise SystemExit("ARM9 wurde unerwartet veraendert!")

output = bytes(rom.save())
check = ndspy.rom.NintendoDSRom(output)

if bytes(check.arm9) != original_arm9:
    raise SystemExit("ARM9 im Ergebnis stimmt nicht ueberein!")

dst.write_bytes(output)

print("\nErfolg!")
print("Overlays veraendert:", changed)
print("ARM9 unveraendert: JA")
print("Ausgabedatei:", dst)
print("Groesse:", len(output), "Bytes")
