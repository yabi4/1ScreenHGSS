from collections import defaultdict
from pathlib import Path

import ndspy.rom
import ndspy.codeCompression
from onescreen import sites, table

p = Path(r"C:\HGSS1Screen\Origin_HeartGold_v4.0.3_EN_v1.0.0-rc8.nds")
rom = ndspy.rom.NintendoDSRom(p.read_bytes())

modules = [
    ("arm9", 0x02000000, ndspy.codeCompression.decompress(rom.arm9))
]

for oid, ov in sorted(rom.loadArm9Overlays().items()):
    modules.append((f"ov{oid:03d}", ov.ramAddress, bytes(ov.data)))

found = sites.find(modules)
groups = defaultdict(list)

for s in found:
    groups[s["module"]].append(s)

print("Gamecode:", bytes(rom.idCode).decode())
print("Gefundene Bildschirmwechsel:", len(found))
print()

for module in sorted(groups):
    entries = groups[module]
    decisions = defaultdict(int)

    for s in entries:
        decisions[table.intent_for(module, s["addr"])] += 1

    print(module, len(entries), dict(decisions))

print("\nWichtige Module:")
for module in ("arm9", "ov012", "ov014"):
    print(f"\n{module}:")
    for s in groups.get(module, []):
        print(hex(s["addr"]), s["family"],
              table.intent_for(module, s["addr"]))

print("\nAnalyse abgeschlossen. ROM unveraendert.")
