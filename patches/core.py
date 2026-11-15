# SPDX-License-Identifier: MIT
"""Controller key table, the frame cap, and the sound-effects load fix."""

from caligo import keys
from caligo.smali import StageError

ACT = 'smali/com/com2us/caligo/WrapperActivity.smali'
RND = 'smali/com/com2us/caligo/WrapperRenderer.smali'
SND = 'smali/com/com2us/caligo/SoundManager.smali'

# the stock switch table ends with the 0x54 entry; the pad keys are appended
# there and the assembler sorts the payload itself
SWITCH_ANCHOR = "        0x54 -> :sswitch_8\n    .end sparse-switch"


def controller(ctx):
    tree = ctx.tree
    block, entries = keys.build_block(ctx.config['controller']['bindings'])
    method = tree.read(ACT)
    keys.check_labels(method, entries)
    start = method.replace('\r\n', '\n').find('getGameKeyCode')
    if start < 0:
        raise StageError('getGameKeyCode() not found in %s' % ACT)
    tree.patch(ACT, SWITCH_ANCHOR,
               "        0x54 -> :sswitch_8\n" + block + "    .end sparse-switch")
    for code, label, button, action in entries:
        ctx.note('  0x%02x %-9s -> %-10s (%s)' % (code, button, action, label))


def frame_cap(ctx):
    tree = ctx.tree
    ms = ctx.config['patches']['ms_per_frame']

    tree.patch(RND,
               '.field private static renderer:Lcom/com2us/caligo/WrapperRenderer;',
               '.field private static renderer:Lcom/com2us/caligo/WrapperRenderer;\n\n'
               '# timestamp of the previous frame, in ms, for the frame limiter\n'
               '.field public static lastFrame:J')

    tree.patch(RND,
               '.method public onDrawFrame(Ljavax/microedition/khronos/opengles/GL10;)V\n'
               '    .locals 3',
               '.method public onDrawFrame(Ljavax/microedition/khronos/opengles/GL10;)V\n'
               '    .locals 6')

    tree.patch(RND,
               '    .line 29\n    invoke-static {}, Ljava/lang/System;->currentTimeMillis()J',
               '''    # ---- frame cap: at least %(ms)d ms per frame (~%(fps)d fps) ----
    # The engine advances one game tick per rendered frame and has no cap of its
    # own, so on a 60/120 Hz display the game runs 2x/4x too fast. SystemClock
    # sleep() does not throw InterruptedException, so no try/catch is needed.
    invoke-static {}, Landroid/os/SystemClock;->uptimeMillis()J
    move-result-wide v0

    sget-wide v2, Lcom/com2us/caligo/WrapperRenderer;->lastFrame:J

    sub-long v4, v0, v2

    const-wide/16 v2, 0x%(ms)x

    sub-long/2addr v2, v4

    const-wide/16 v4, 0x0

    cmp-long v4, v2, v4

    if-lez v4, :cond_cap

    invoke-static {v2, v3}, Landroid/os/SystemClock;->sleep(J)V

    :cond_cap
    invoke-static {}, Landroid/os/SystemClock;->uptimeMillis()J
    move-result-wide v2

    sput-wide v2, Lcom/com2us/caligo/WrapperRenderer;->lastFrame:J

    # ---- original code ----
    .line 29
    invoke-static {}, Ljava/lang/System;->currentTimeMillis()J''' % dict(
                   ms=ms, fps=1000 // ms))
    ctx.note('frame cap: %d ms/frame (~%d fps)' % (ms, 1000 // ms))


def sound_fd(ctx):
    """Load sound effects through a FileDescriptor.

    The engine builds "/sdcard/Com2uS/<pkg>/SE/<name>" and hands that string to
    SoundPool.load(). On Android 11+ the file is dropped with "error loading
    <path>" because the path belongs to a previous install, so the app cannot
    canonicalise it. Opening the file ourselves and passing the descriptor works.

    Register discipline: .locals stays 11 (p0=v11, p1=v12) - raising it would push
    the parameters past v15 and every 4-bit invoke operand in the method becomes
    illegal. Free at the load site: v0, v1, v4, v5, v6, v9, v10. load() takes a
    contiguous 7-register range (this + fd + two longs + int), so v0..v6.
    """
    tree = ctx.tree
    tree.patch(SND,
               """    :goto_3
    sget-object v4, Lcom/com2us/caligo/SoundManager;->soundPool:Landroid/media/SoundPool;

    invoke-virtual {v4, v3, v8}, Landroid/media/SoundPool;->load(Ljava/lang/String;I)I

    move-result v2""",
               """    :goto_3
    # ---- load via a file descriptor, not via a path string ----
    :try_start_fd
    new-instance v9, Ljava/io/File;

    invoke-direct {v9, v3}, Ljava/io/File;-><init>(Ljava/lang/String;)V

    new-instance v10, Ljava/io/FileInputStream;

    invoke-direct {v10, v9}, Ljava/io/FileInputStream;-><init>(Ljava/io/File;)V

    invoke-virtual {v9}, Ljava/io/File;->length()J

    move-result-wide v4

    invoke-virtual {v10}, Ljava/io/FileInputStream;->getFD()Ljava/io/FileDescriptor;

    move-result-object v1

    sget-object v0, Lcom/com2us/caligo/SoundManager;->soundPool:Landroid/media/SoundPool;

    const-wide/16 v2, 0x0

    const/16 v6, 0x1

    invoke-virtual/range {v0 .. v6}, Landroid/media/SoundPool;->load(Ljava/io/FileDescriptor;JJI)I

    move-result v2

    invoke-virtual {v10}, Ljava/io/FileInputStream;->close()V
    :try_end_fd
    .catch Ljava/lang/Exception; {:try_start_fd .. :try_end_fd} :catch_fd

    goto :fd_ok

    :catch_fd
    const/4 v2, 0x0

    :fd_ok
    nop""")
    ctx.note('sound effects load through a FileDescriptor')


def apply(ctx):
    if ctx.config['controller']['enabled']:
        controller(ctx)
    else:
        ctx.note('controller: left at stock (a gamepad will do nothing)')

    frame_cap(ctx)

    if ctx.config['patches']['soundpool_fd_fix']:
        sound_fd(ctx)
