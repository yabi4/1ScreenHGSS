"""Run routines from the assembled hook payload under an ARM emulator.

There is no substitute for playing the game, but a lot of the hook is plain
pointer walking and arithmetic that can be checked without it: give a routine a
synthetic FieldSystem, ScriptMenu or BattleSystem in emulated main RAM, call it,
and look at what it returns or writes. tools/test_hook.py does exactly that.

    pip install unicorn

Memory map, as on the DS:

    0x01FF8000  ITCM, 32 KB      the payload loads at its own load address
    0x02000000  main RAM, 4 MB   synthetic game structs go here
    0x04000000  I/O              mapped so register writes (POWCNT1) land
    0x05000000  palette RAM
    0x06000000  VRAM (a window of it)

Calls return to a sentinel address; anything that runs off into unmapped memory
raises, which is the point - a routine that dereferences a bad pointer fails
the test instead of silently reading zeros.
"""

import json
import pathlib
import shutil
import struct
import subprocess

from unicorn import Uc, UcError, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
                               UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR,
                               UC_ARM_REG_PC)

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAYLOAD = ROOT / "onescreen" / "payload"

ITCM = (0x01FF8000, 0x8000)
MAIN = (0x02000000, 0x400000)
IO = (0x04000000, 0x2000)
PAL = (0x05000000, 0x800)
VRAM = (0x06000000, 0x40000)
STACK_TOP = 0x023FF000
RETURN = 0x023FFF00              # a `b .` lands here when a call returns
ARGS = (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)


class Hook:
    def __init__(self, payload: bytes = None, meta: dict = None):
        if payload is None:
            payload = (PAYLOAD / "hook.bin").read_bytes()
        if meta is None:
            meta = json.loads((PAYLOAD / "hook.json").read_text())
        self.meta = meta
        self.load = int(meta["load_addr"], 16)
        self.sym = {k: int(v, 16) for k, v in meta["symbols"].items()}
        self.sym.update(elf_symbols())
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        for base, size in (ITCM, MAIN, IO, PAL, VRAM):
            self.uc.mem_map(base, size)
        self.uc.mem_write(self.load, payload)
        self.uc.mem_write(RETURN, struct.pack("<H", 0xE7FE))   # b .
        self._heap = MAIN[0] + 0x100000

    # --- memory ---------------------------------------------------------------
    def alloc(self, size: int, align: int = 4) -> int:
        self._heap = (self._heap + align - 1) & ~(align - 1)
        addr = self._heap
        self._heap += size
        self.uc.mem_write(addr, b"\0" * size)
        return addr

    def write(self, addr: int, data: bytes):
        self.uc.mem_write(addr, bytes(data))

    def read(self, addr: int, size: int) -> bytes:
        return bytes(self.uc.mem_read(addr, size))

    def w8(self, addr, v):
        self.write(addr, struct.pack("<B", v & 0xFF))

    def w16(self, addr, v):
        self.write(addr, struct.pack("<H", v & 0xFFFF))

    def w32(self, addr, v):
        self.write(addr, struct.pack("<I", v & 0xFFFFFFFF))

    def r8(self, addr):
        return self.read(addr, 1)[0]

    def r16(self, addr):
        return struct.unpack("<H", self.read(addr, 2))[0]

    def r32(self, addr):
        return struct.unpack("<I", self.read(addr, 4))[0]

    def var(self, name: str) -> int:
        """Address of a payload variable or routine, by its assembled name."""
        if name in self.sym:
            return self.sym[name]
        raise KeyError(f"{name} is not exported in hook.json; add `.global {name}`")

    def string(self, codes) -> int:
        """A game String: u16 maxsize, u16 size, u32 magic, u16 codes[]."""
        codes = list(codes)
        addr = self.alloc(8 + 2 * (len(codes) + 1))
        self.write(addr, struct.pack("<HHI", len(codes) + 1, len(codes), 0xB6F8D2EC))
        self.write(addr + 8, struct.pack(f"<{len(codes) + 1}H", *codes, 0xFFFF))
        return addr

    # --- calls ----------------------------------------------------------------
    def call(self, target, *args, max_insns: int = 2_000_000) -> int:
        """Call a Thumb routine (a symbol name or an address) and return r0."""
        addr = self.var(target) if isinstance(target, str) else target
        if len(args) > 4:
            raise ValueError("only register arguments are supported")
        for reg, value in zip(ARGS, args):
            self.uc.reg_write(reg, value & 0xFFFFFFFF)
        self.uc.reg_write(UC_ARM_REG_SP, STACK_TOP)
        self.uc.reg_write(UC_ARM_REG_LR, RETURN | 1)
        try:
            self.uc.emu_start(addr | 1, RETURN, count=max_insns)
        except UcError as exc:
            pc = self.uc.reg_read(UC_ARM_REG_PC)
            raise RuntimeError(f"emulation fault in {target!r} at pc={pc:#010x}: "
                               f"{exc}") from None
        pc = self.uc.reg_read(UC_ARM_REG_PC)
        if pc & ~1 != RETURN:
            raise RuntimeError(f"{target!r} did not return within {max_insns} "
                               f"instructions (pc={pc:#010x})")
        return self.uc.reg_read(UC_ARM_REG_R0)

    def stub(self, addr: int, fn):
        """Make the game function at `addr` run `fn(hook, r0, r1, r2, r3)` in
        Python instead, returning its value in r0. For calls the hook makes into
        game code that the test does not want to emulate."""
        addr &= ~1
        self.uc.mem_write(addr, struct.pack("<H", 0x4770))      # bx lr

        def _hook(uc, address, size, _user):
            if address == addr:
                regs = [uc.reg_read(r) for r in ARGS]
                ret = fn(self, *regs)
                if ret is not None:
                    uc.reg_write(UC_ARM_REG_R0, ret & 0xFFFFFFFF)

        self.uc.hook_add(UC_HOOK_CODE, _hook, begin=addr, end=addr)


def elf_symbols() -> dict:
    """Every symbol in build/hook.elf - variables included, which hook.json
    leaves out. Empty if the payload has not been built here."""
    elf = ROOT / "build" / "hook.elf"
    nm = shutil.which("arm-none-eabi-nm")
    if not elf.exists() or nm is None:
        return {}
    out = subprocess.run([nm, str(elf)], capture_output=True, text=True,
                         check=True).stdout
    syms = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3:
            syms[parts[2]] = int(parts[0], 16)
    return syms


def signed(v: int) -> int:
    return v - (1 << 32) if v & 0x80000000 else v
