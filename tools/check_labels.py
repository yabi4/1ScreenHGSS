"""Check every numeric local-label reference in the hook assembly.

GAS resolves `45b` to the nearest `45:` label ABOVE the reference and `45f` to
the nearest one BELOW it. A reference that reaches into another function is a
silent bug: the assembler is happy, the code is not.

That is not hypothetical. OneScreen_BattleExec used `b 45b` to reach its own
return label, but the `45:` above that line belongs to OneScreen_BattleDraw,
so the hook jumped into the middle of another function and the battle app
never got its return value back - the battle scene froze and the input died.
The assembler raised no error, and the emulation tests did not catch it
either; only bisecting the ROM did.

So this walks the source, resolves every reference the way GAS does, and
reports the ones that leave their own function. Run it after any edit to
src/hook.s:

    python tools/check_labels.py
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOK = ROOT / "src" / "hook.s"

BRANCHES = re.compile(
    r"^\s*(?:b|bl|beq|bne|bcs|bcc|bmi|bpl|bvs|bvc|bhi|bls|bge|blt|bgt|ble|"
    r"cbz|cbnz)\s+(\d+)([bf])\b"
)
LABEL = re.compile(r"^(\d+):")
# Only the hook's own entry points count as functions. A named label like
# ob_done or phase_running is a label INSIDE a function, not a new one.
FUNC = re.compile(r"^(OneScreen_[A-Za-z0-9_]*):")


def enclosing_function(funcs, line_no):
    """The function a line belongs to: the last entry point above it."""
    name = None
    for start, fname in funcs:
        if start <= line_no:
            name = fname
        else:
            break
    return name


def check(path):
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    labels = {}
    funcs = []
    for i, line in enumerate(lines, 1):
        m = LABEL.match(line)
        if m:
            labels.setdefault(int(m.group(1)), []).append(i)
        m = FUNC.match(line)
        if m:
            funcs.append((i, m.group(1)))

    bad = []
    refs = 0
    for i, line in enumerate(lines, 1):
        m = BRANCHES.match(line)
        if not m:
            continue
        num = int(m.group(1))
        spots = labels.get(num, [])
        if m.group(2) == "b":
            candidates = [s for s in spots if s < i]
            target = max(candidates) if candidates else None
        else:
            candidates = [s for s in spots if s > i]
            target = min(candidates) if candidates else None
        if target is None:
            bad.append((i, line.strip(), num, m.group(2), None, "unresolved"))
            continue
        refs += 1
        here = enclosing_function(funcs, i)
        there = enclosing_function(funcs, target)
        if here != there:
            bad.append((i, line.strip(), num, m.group(2), target,
                        f"{here} -> {there}"))

    print(f"{path.name}: {refs} numeric label references, {len(bad)} suspicious")
    for line_no, text, num, direction, target, why in bad:
        tgt = f"line {target}" if target else "nowhere"
        print(f"  line {line_no}: {text!r} -> label {num}{direction} "
              f"= {tgt} ({why})")
    return bad


if __name__ == "__main__":
    problems = check(HOOK)
    sys.exit(1 if problems else 0)
