# SPDX-License-Identifier: MIT
"""Byte-level editing of a 32-bit ARM ELF, plus the branch encoders the new
code needs.

Two rules that cost real time to learn, and that every native patch here obeys:

* The loader maps the library wherever it likes, so new code must reach data
  with PIC arithmetic (`ldr rX,[pc,#n]` + `add rX,pc` and a *delta* in the
  literal pool). A literal holding an absolute virtual address writes into
  whatever happens to live there in the process - usually the heap, which
  corrupts the game and crashes it far away from the patch.

* On ARMv5TE, `ADD Rd,PC` reads (insn_addr + 4) with only bit 0 cleared. It is
  NOT rounded down to a word boundary the way `LDR Rd,[pc,#imm]` is. Being two
  bytes off here silently produces a wrong pointer.
"""

import struct

PT_LOAD = 1
PF_W = 2
SHT_NOBITS = 8


class ElfError(Exception):
    pass


def u16(v):
    return struct.pack('<H', v & 0xFFFF)


def i16(v):
    return struct.pack('<h', v)


def u32(v):
    return struct.pack('<I', v & 0xFFFFFFFF)


def check(data, addr, expected, what):
    got = bytes(data[addr:addr + len(expected)])
    if got != expected:
        raise ElfError('%s at 0x%X: expected %s, found %s. The input APK is not the '
                       'expected version, or it is already patched.'
                       % (what, addr, expected.hex(' '), got.hex(' ')))


def put(data, addr, blob):
    data[addr:addr + len(blob)] = blob


def dec_bl(data, addr):
    h1, h2 = struct.unpack_from('<HH', data, addr)
    if (h1 & 0xF800) != 0xF000 or (h2 & 0xD000) != 0xD000:
        return None
    s = (h1 >> 10) & 1
    i1 = 1 - (((h2 >> 13) & 1) ^ s)
    i2 = 1 - (((h2 >> 11) & 1) ^ s)
    imm = (s << 24) | (i1 << 23) | (i2 << 22) | ((h1 & 0x3FF) << 12) | ((h2 & 0x7FF) << 1)
    if imm & (1 << 24):
        imm -= 1 << 25
    return (addr + 4 + imm) & ~1


def enc_bl(addr, target):
    imm = (target & ~1) - ((addr + 4) & ~1)
    if not -(1 << 24) <= imm < (1 << 24):
        raise ElfError('bl out of range: 0x%X -> 0x%X' % (addr, target))
    s = (imm >> 24) & 1
    i1 = (imm >> 23) & 1
    i2 = (imm >> 22) & 1
    h1 = 0xF000 | (s << 10) | ((imm >> 12) & 0x3FF)
    h2 = 0xD000 | (((i1 ^ s) ^ 1) << 13) | (((i2 ^ s) ^ 1) << 11) | ((imm >> 1) & 0x7FF)
    return struct.pack('<HH', h1, h2)


def enc_b(addr, target):
    imm = (target & ~1) - ((addr + 4) & ~1)
    if not -(1 << 11) <= imm < (1 << 11):
        raise ElfError('b out of range: 0x%X -> 0x%X' % (addr, target))
    return u16(0xE000 | ((imm >> 1) & 0x7FF))


def enc_bcond(addr, target, cond):
    imm = (target & ~1) - ((addr + 4) & ~1)
    if not 0 <= imm // 2 < 256:
        raise ElfError('conditional branch out of range: 0x%X -> 0x%X' % (addr, target))
    return u16(0xD000 | (cond << 8) | ((imm >> 1) & 0xFF))


def pc_of_add(addr):
    return (addr + 4) & ~1


def pc_of_ldr(addr):
    return (addr + 4) & ~3


def extend_bss(data, extra):
    """Grow the writable segment (and its NOBITS section) by `extra` bytes.

    Returns the virtual address of the first new byte - a fresh zero-initialised
    word, which is what the patched code uses as its flag.
    """
    if extra & 3:
        raise ElfError('bss growth must be word aligned, got %d' % extra)
    e_phoff = struct.unpack_from('<I', data, 0x1C)[0]
    e_phentsize = struct.unpack_from('<H', data, 0x2A)[0]
    e_phnum = struct.unpack_from('<H', data, 0x2C)[0]
    e_shoff = struct.unpack_from('<I', data, 0x20)[0]
    e_shentsize = struct.unpack_from('<H', data, 0x2E)[0]
    e_shnum = struct.unpack_from('<H', data, 0x30)[0]

    load = None
    for i in range(e_phnum):
        p = e_phoff + i * e_phentsize
        p_type, _, p_va, _, _, p_memsz, p_flags, _ = struct.unpack_from('<8I', data, p)
        if p_type == PT_LOAD and p_flags & PF_W:
            load = (p, p_va, p_memsz)
    if load is None:
        raise ElfError('libgame.so has no writable PT_LOAD segment')
    ph, seg_va, memsz = load
    end = seg_va + memsz
    if end & 3:
        raise ElfError('writable segment ends unaligned at 0x%X' % end)

    struct.pack_into('<I', data, ph + 20, memsz + extra)     # p_memsz
    for i in range(e_shnum):
        sh = e_shoff + i * e_shentsize
        if struct.unpack_from('<I', data, sh + 4)[0] == SHT_NOBITS:
            a, sz = struct.unpack_from('<II', data, sh + 12)
            if a + sz == end:
                struct.pack_into('<I', data, sh + 20, sz + extra)   # sh_size
    return end
