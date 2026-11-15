# SPDX-License-Identifier: MIT
"""Full-panel rendering: no black band at the top, no side columns.

Two separate causes, both fixed here:

1. The firmware reserves a 55 px navigation-bar strip (and ~7+6 px side gesture
   panels), so the app window is 1907x1025 even though the panel is 1920x1080.
   The theme hides the status bar only; the navigation bar has to be hidden
   explicitly. The deprecated-but-still-working setSystemUiVisibility() with
   IMMERSIVE_STICKY does it and still lets an edge swipe bring the bar back.

2. Even with the bar hidden, the engine sized itself from Display.getWidth()/
   getHeight(), which report the *app area* (1907x1025) rather than the panel,
   and caches that as its virtual screen at nativeInit. It then painted only the
   bottom 1025 rows of a 1080-row surface - and because the GL viewport origin is
   bottom-left, the missing rows show up as a band at the TOP.

   Display.getRealWidth()/getRealHeight() would be the obvious fix but they are
   gone on Android 13 (NoSuchMethodError). WindowManager.getMaximumWindowMetrics()
   is the supported replacement and reports the real panel for the rotation.
"""

ACT = 'smali/com/com2us/caligo/WrapperActivity.smali'
WM = 'smali/com/com2us/caligo/WrapperManager.smali'

FLAGS = 0x1706   # LAYOUT_STABLE | LAYOUT_HIDE_NAVIGATION | LAYOUT_FULLSCREEN
                 # | HIDE_NAVIGATION | FULLSCREEN | IMMERSIVE_STICKY

OLD_UI = """    invoke-virtual {v7, v8, v8}, Landroid/view/Window;->setFlags(II)V

    .line 102
    const-string v7, "sensor"
"""

NEW_UI = """    invoke-virtual {v7, v8, v8}, Landroid/view/Window;->setFlags(II)V

    # full screen: the firmware reserves a 55 px navigation strip plus 7+6 px
    # side gesture panels. IMMERSIVE_STICKY keeps them hidden but lets an edge
    # swipe bring the bar back, so the player can still leave the app.
    invoke-virtual {p0}, Lcom/com2us/caligo/WrapperActivity;->getWindow()Landroid/view/Window;

    move-result-object v7

    invoke-virtual {v7}, Landroid/view/Window;->getDecorView()Landroid/view/View;

    move-result-object v7

    const/16 v8, %#06x

    invoke-virtual {v7, v8}, Landroid/view/View;->setSystemUiVisibility(I)V

    .line 102
    const-string v7, "sensor"
""" % FLAGS

OLD_SET = """    invoke-virtual {v7, v8}, Lcom/com2us/caligo/WrapperManager;->setDisplay(Landroid/view/Display;)V
"""

NEW_SET = """    invoke-virtual {v7, v8}, Lcom/com2us/caligo/WrapperManager;->setDisplay(Landroid/view/Display;)V

    # Display.getWidth()/getHeight() report the app area (1907x1025), not the
    # panel. The engine caches that as its virtual screen, so it painted only the
    # bottom 1025 rows and left a band at the top. Take the real panel instead.
    invoke-interface {v6}, Landroid/view/WindowManager;->getMaximumWindowMetrics()Landroid/view/WindowMetrics;

    move-result-object v7

    invoke-virtual {v7}, Landroid/view/WindowMetrics;->getBounds()Landroid/graphics/Rect;

    move-result-object v7

    invoke-virtual {v7}, Landroid/graphics/Rect;->width()I

    move-result v8

    sput v8, Lcom/com2us/caligo/WrapperManager;->DISPLAY_WIDTH:I

    invoke-virtual {v7}, Landroid/graphics/Rect;->height()I

    move-result v8

    sput v8, Lcom/com2us/caligo/WrapperManager;->DISPLAY_HEIGHT:I
"""


def apply(ctx):
    tree = ctx.tree
    tree.patch(ACT, OLD_UI, NEW_UI)
    ctx.note('navigation bar hidden (setSystemUiVisibility 0x%X)' % FLAGS)

    tree.patch(ACT, OLD_SET, NEW_SET)
    ctx.note('virtual screen taken from getMaximumWindowMetrics()')

    # ...which writes two fields of another class, and writing another class's
    # private static field throws IllegalAccessError at runtime.
    for field in ('DISPLAY_WIDTH', 'DISPLAY_HEIGHT'):
        tree.patch(WM,
                   '.field private static %s:I' % field,
                   '.field public static %s:I' % field)
    ctx.note('DISPLAY_WIDTH/DISPLAY_HEIGHT are now public static')
