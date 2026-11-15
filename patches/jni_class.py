# SPDX-License-Identifier: MIT
"""Give the engine a valid Java class handle (this is the fix that makes it run).

Every Java bridge in the library looks like:

    cls = g_jni[1];                                  /* .bss @ 0x11CE50 */
    mid = env->GetStaticMethodID(cls, "Name", "Sig");
    if (mid) env->CallStaticXMethod(cls, mid, ...);

`nativeInit` stores the JNIEnv in `g_jni[0]` and nothing ever writes `g_jni[1]`.
Dalvik returned NULL from GetStaticMethodID with a null jclass, so every bridge
silently did nothing and the game still "worked". ART instead crashes while
formatting the error (SIGSEGV inside the class loader).

The fix replaces `__android_init` (a 0x24 byte leaf) with a trampoline into a
cave inside a dead exported function, and the cave does:

    cls  = env->FindClass("com/com2us/caligo/WrapperManager")
    gref = env->NewGlobalRef(cls)
    g_jni[1] = gref

A *global* reference is required: the bridges are called later, from other
threads and other JNI entry points, so the local reference from nativeInit's
frame would be invalid.

The cave is the body of `Java_com_com2us_HG_WrapperManager_nativeForceStopDownload`
at 0x2C720: the exported name refers to package `com.com2us.HG`, which does not
exist in this APK, so that 368-byte function can never be entered.
"""

from caligo import elfx

G_JNI = 0x11CE50            # g_jni block: [0]=env, [1]=jclass
CLS_NAME = 0x0DA2C4         # "com/com2us/caligo/WrapperManager" in .rodata

INIT = 0xB3184              # __android_init, 0x24 bytes
INIT_SIZE = 0x24
CAVE = 0x2C720              # dead export body
JNI_FINDCLASS = 0x18        # JNINativeInterface slot 6 * 4
JNI_NEWGLOBALREF = 0x54     # slot 21 * 4


def trampoline(target):
    """push {lr}; ldr r3,[pc,#8]; add r3,pc; blx r3; pop {pc}; nop; .word delta

    `target` must have bit 0 set: blx only stays in Thumb state when the address
    is odd.
    """
    assert target & 1, 'blx target needs the Thumb bit'
    code = bytearray()
    code += elfx.u16(0xB500)        # push {lr}
    code += elfx.u16(0x4B02)        # ldr  r3,[pc,#8] -> literal
    code += elfx.u16(0x447B)        # add  r3,pc
    code += elfx.u16(0x4798)        # blx  r3
    code += elfx.u16(0xBD00)        # pop  {pc}
    code += elfx.u16(0x46C0)        # nop  (pad to the literal)
    assert len(code) == 0xC
    code += elfx.u32((target - elfx.pc_of_add(INIT + 0x4)) & 0xFFFFFFFF)
    return bytes(code)


def cave_stub():
    code = bytearray()
    code += elfx.u16(0xB570)        # 0x2C720 push {r4,r5,r6,lr}
    code += elfx.u16(0x4C08)        # ldr  r4,[pc,#0x20]  -> &g_jni
    code += elfx.u16(0x4908)        # ldr  r1,[pc,#0x20]  -> class name
    code += elfx.u16(0x447C)        # add  r4,pc
    code += elfx.u16(0x4479)        # add  r1,pc
    code += elfx.u16(0x6826)        # ldr  r6,[r4,#0]     ; r6 = env
    code += elfx.u16(0x6833)        # ldr  r3,[r6,#0]     ; r3 = env->functions
    code += elfx.u16(0x461D)        # mov  r5,r3
    code += elfx.u16(0x4630)        # mov  r0,r6
    code += elfx.u16(0x699B)        # ldr  r3,[r3,#0x18]  ; FindClass
    code += elfx.u16(0x4798)        # blx  r3
    code += elfx.u16(0x4601)        # mov  r1,r0
    code += elfx.u16(0x4630)        # mov  r0,r6
    code += elfx.u16(0x6D6B)        # ldr  r3,[r5,#0x54]  ; NewGlobalRef
    code += elfx.u16(0x4798)        # blx  r3
    code += elfx.u16(0x6060)        # str  r0,[r4,#4]     ; g_jni[1] = gref
    code += elfx.u16(0xBD70)        # pop  {r4,r5,r6,pc}
    assert len(code) == 0x22, hex(len(code))
    while (CAVE + len(code)) % 4:
        code += elfx.u16(0x46C0)
    assert CAVE + len(code) == 0x2C744, hex(len(code))
    # The two `add rX,pc` instructions see PC = insn_addr + 4 with bit 0 cleared.
    v1 = (G_JNI - elfx.pc_of_add(0x2C726)) & 0xFFFFFFFF
    v2 = (CLS_NAME - elfx.pc_of_add(0x2C728)) & 0xFFFFFFFF
    code += elfx.u32(v1)
    code += elfx.u32(v2)
    return bytes(code)


def apply(ctx):
    lib = ctx.lib
    elfx.check(lib, INIT, b'\x10\xb5', '__android_init prologue (push {r4,lr})')
    elfx.check(lib, CAVE, b'\xf0\xb5', 'dead-export prologue (push {r4-r7,lr})')

    trip = trampoline(CAVE | 1)
    stub = cave_stub()

    elfx.put(lib, INIT, trip)
    for off in range(len(trip), INIT_SIZE, 2):
        elfx.put(lib, INIT + off, elfx.u16(0x46C0))

    elfx.put(lib, CAVE, stub)
    ctx.note('__android_init 0x%X -> trampoline -> 0x%X; stub caches the global class '
             'reference in g_jni[1]' % (INIT, CAVE))
