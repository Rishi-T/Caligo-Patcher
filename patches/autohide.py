# SPDX-License-Identifier: MIT
"""On-screen touch pad: hide it automatically, always hide it, or leave it alone.

The engine calls Java_nativeEvent for every input event, with r2 = type:
2 for a key down, 3 for a key up, a negative value for a touch. So a small hook
at the top of nativeEvent can record "a physical key was used" vs "the screen was
touched" in a flag word, and the seven call sites that draw the virtual pad are
retargeted to a gate that returns early while the flag is set.

Result: the pad disappears on the first pad button and comes back on any touch.
"""

from caligo import elfx
from caligo.smali import StageError

DRAW = 0x71C08                                    # DrawViewGameVirtualKey
DRAW_SITES = [0x65882, 0x65944, 0x65A5A, 0x65EE6,   # net timeout popups
              0x9541A, 0x9654C, 0x9983A]            # gameplay, item shop, popup
GATE = 0x2C758                                     # dead-export body, after the jclass cave
HOOK = 0x2C7A0                                     # ditto, within +/-2 KB of nativeEvent
EVENT_ENTRY = 0x2C624                              # Java_..._nativeEvent
EVENT_PUSH = 0xB5F0                                # push {r4,r5,r6,r7,lr}
FLAG_INC = 0x100

BX_LR = b'\x70\x47'


def _gate(flag):
    lit = GATE + 0x1C
    code = b''.join([
        elfx.u16(0xB510),                                   # +00 push {r4, lr}
        elfx.u16(0x4C06),                                   # +02 ldr r4,[pc,#24]
        elfx.u16(0x447C),                                   # +04 add r4,pc
        elfx.u16(0x6824),                                   # +06 ldr r4,[r4]
        elfx.u16(0x2C00),                                   # +08 cmp r4,#0
        elfx.enc_bcond(GATE + 0x0A, GATE + 0x0E, 0x0),       # +0A beq draw
        elfx.u16(0xBD10),                                   # +0C pop {r4, pc}  (hidden)
        elfx.enc_bl(GATE + 0x0E, DRAW | 1),                 # +0E bl DrawViewGameVirtualKey
        elfx.u16(0xBD10),                                   # +12 pop {r4, pc}
        elfx.u16(0x46C0) * 4,                               # +14 pad to literal
        elfx.u32((flag - elfx.pc_of_add(GATE + 0x04)) & 0xFFFFFFFF),
    ])
    assert len(code) == 0x20 and lit == GATE + 0x1C, len(code)
    return code


def _hook(flag):
    code = b''.join([
        elfx.u16(EVENT_PUSH),                              # original push
        elfx.u16(0x4C08),                                  # ldr r4,[pc,#32]
        elfx.u16(0x447C),                                  # add r4,pc
        elfx.u16(0x2A02),                                  # cmp r2,#2   key down?
        elfx.enc_bcond(HOOK + 0x08, HOOK + 0x10, 0x0),      # beq .set1
        elfx.u16(0x2A00),                                  # cmp r2,#0
        elfx.enc_bcond(HOOK + 0x0C, HOOK + 0x16, 0xB),      # blt .set0   (touch)
        elfx.enc_b(HOOK + 0x0E, HOOK + 0x1A),               # b .done     (other events)
        elfx.u16(0x2501),                                  # .set1: movs r5,#1
        elfx.enc_b(HOOK + 0x12, HOOK + 0x18),               # b .store
        elfx.u16(0x46C0),                                  # pad
        elfx.u16(0x2500),                                  # .set0: movs r5,#0
        elfx.u16(0x6025),                                  # .store: str r5,[r4]
        elfx.enc_b(HOOK + 0x1A, EVENT_ENTRY + 2),           # .done: b nativeEvent+2
        elfx.u16(0x46C0) * 4,                              # pad to literal
        elfx.u32((flag - elfx.pc_of_add(HOOK + 0x04)) & 0xFFFFFFFF),
    ])
    assert len(code) == 0x28, len(code)
    return code


def _self_check(lib, flag):
    for lit, add_addr in ((GATE + 0x1C, GATE + 0x04), (HOOK + 0x24, HOOK + 0x04)):
        delta = int.from_bytes(bytes(lib[lit:lit + 4]), 'little')
        if delta & 0x80000000:
            delta -= 1 << 32
        resolved = elfx.pc_of_add(add_addr) + delta
        if resolved != flag:
            raise StageError('literal at 0x%X resolves to 0x%X, expected 0x%X'
                             % (lit, resolved, flag))


def always_hidden(ctx):
    lib = ctx.lib
    if bytes(lib[DRAW:DRAW + 2]) == BX_LR:
        ctx.note('touch pad: already hidden')
        return
    elfx.put(lib, DRAW, BX_LR)
    ctx.note('touch pad: permanently hidden (draw entry returns immediately)')


def autohide(ctx):
    lib = ctx.lib
    flag = elfx.extend_bss(lib, FLAG_INC)
    ctx.note('.bss +0x%X -> flag word at 0x%X' % (FLAG_INC, flag))

    # a stock prologue; tolerate an already-hidden pad from a previous tool
    if bytes(lib[DRAW:DRAW + 2]) == BX_LR:
        elfx.put(lib, DRAW, elfx.u16(EVENT_PUSH))
    elfx.check(lib, DRAW, b'\xf0\xb5', 'DrawViewGameVirtualKey prologue')

    elfx.put(lib, GATE, _gate(flag))
    elfx.put(lib, HOOK, _hook(flag))
    elfx.check(lib, EVENT_ENTRY, elfx.u16(EVENT_PUSH), 'nativeEvent prologue')
    elfx.put(lib, EVENT_ENTRY, elfx.enc_b(EVENT_ENTRY, HOOK))

    for site in DRAW_SITES:
        if elfx.dec_bl(lib, site) != DRAW:
            raise StageError('0x%X does not call DrawViewGameVirtualKey' % site)
        elfx.put(lib, site, elfx.enc_bl(site, GATE | 1))
        if elfx.dec_bl(lib, site) != GATE:
            raise StageError('retarget at 0x%X did not round-trip' % site)

    _self_check(lib, flag)
    ctx.note('touch pad: gate at 0x%X, input hook at 0x%X, %d draw sites retargeted'
             % (GATE, HOOK, len(DRAW_SITES)))


def apply(ctx):
    mode = str(ctx.config['patches']['touch_pad']).strip().lower()
    if mode in ('autohide', 'auto'):
        autohide(ctx)
    elif mode in ('always_hidden', 'hidden'):
        always_hidden(ctx)
    elif mode in ('always_visible', 'visible', 'off'):
        ctx.note('touch pad: left as stock (always visible)')
    else:
        raise StageError('patches.touch_pad must be autohide, always_hidden or '
                         'always_visible (got %r)' % mode)
