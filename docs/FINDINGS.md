# Findings — what the game actually does, and where

Notes collected while making the patch set. Every address is a **virtual address
in `lib/lib/armeabi/libgame.so`** (the loader adds a random base at runtime) or a
file under the decoded APK tree. They are here so the next person does not have to
rediscover them.

## The engine's key vocabulary

`WrapperActivity.getGameKeyCode()` is a `sparse-switch` from Android keycode to
the engine's own 14 keys. The stock table only covers the old feature-phone keys
(ZXCD movement, ENTER, digits, letters); there is no entry for `DPAD_*` (19–22) or
gamepad buttons (96–110), which is why a controller does nothing out of the box.

The engine keys, as used by the label bodies (and by the virtual pad table at
`0xE5D5C`, 10-byte entries `x, y, w, h, key`):

| engine key | meaning | engine key | meaning |
|---|---|---|---|
| `0x31 0x33 0x37 0x39 0x30` | abilities 1–5 | `0x3E` | action / confirm |
| `0x3A 0x3B 0x3C 0x3D` | up / down / left / right | `0x49` | cancel / back |
| `0x2710` | charge (gauntlet) | `0x2711` | menu |
| `0x2713` | info / map | | |

`0x2710` is special: `getKeyCode()` folds it onto the action key while setting a
charging flag, and the key *release* handler turns it into `ProcessChargeAtk()`
(hero action 9). Hold to charge, release to fire. It is gated by
`enableChargeKey()`, so it does nothing in states where the game disables it.

The left analogue stick needs no code: Android synthesises `DPAD_*` from it.

## Speed

The engine advances exactly one game tick per rendered frame. There is no timer
and no cap, so the game's speed is the display's refresh rate: on a 120 Hz panel
it runs 4× too fast. The patch measures `SystemClock.uptimeMillis()` at the top of
`WrapperRenderer.onDrawFrame` and sleeps the remainder of the frame budget.
`SystemClock.sleep()` never throws, so the inserted code needs no try/catch.

Integer milliseconds only — 33 ≈ 30 fps, 40 ≈ 25 fps, 45 ≈ 22 fps.

## Rendering / the black band

Two independent causes:

1. The firmware reserves a 55 px navigation-bar strip plus ~7+6 px side gesture
   panels. `Theme.NoTitleBar.Fullscreen` hides the status bar only; the navigation
   bar must be hidden explicitly (`setSystemUiVisibility` with
   `IMMERSIVE_STICKY`, `0x1706`).
2. The engine builds its projection from `WrapperManager.DISPLAY_WIDTH/HEIGHT`,
   which `setDisplay()` fills from `Display.getWidth()/getHeight()`. On Android 13
   those report the *app area* (1907×1025), not the panel, and the value is cached
   at `nativeInit`. The engine therefore painted only the bottom 1025 rows of a
   1080-row surface — and since GL's viewport origin is bottom-left, the missing
   rows appear at the **top**.

`Display.getRealWidth()/getRealHeight()` are removed on Android 13
(`NoSuchMethodError`); `WindowManager.getMaximumWindowMetrics()` is the supported
replacement. Writing those two fields from another class also requires them to be
`public static`, otherwise the patch crashes with `IllegalAccessError`.

### HUD scaling was attempted and does not work by patching

The HUD is blitted at its authored pixel size, and the engine's layout fractions do
not apply to it. On a 1080p panel that means the HUD art is scaled up and sits
too large in the view - the bars and buttons cover more of the play area than the
layout was designed for - while the layout maths around it assumes otherwise. Four
levers were tried on hardware:

| lever | result |
|---|---|
| virtual-screen size | not a zoom knob: the engine lays out in fractions of it while art stays 1:1, so you get 1.33× cropping or a 0.67× image in a corner |
| font height | one byte in a startup immediate; changes text size only |
| HUD draw under a scaled matrix | the HUD draw code is a register-sharing fragment chain reached by a plain `bl`; there is no callable unit to wrap, and hijacking a dispatch table slot crashed |
| routing HUD blits through the engine's scaled blit path | no crash, but the art is torn and it is far too slow |
| bigger virtual screen + pinned `glViewport` | the viewport is coupled to the virtual screen; the finished frame is squeezed/cropped, not scaled |

Scaling the HUD relative to the world needs control over the renderer itself,
which is a re-implementation problem, not a patch.

## JNI / startup

Every Java bridge in the library does:

```
cls  = g_jni[1];                               /* .bss @ 0x11CE50 */
mid  = env->GetStaticMethodID(cls, "Name", "Sig");
if (mid) env->CallStaticXMethod(cls, mid, ...);
```

`nativeInit` writes only `g_jni[0]` (the JNIEnv). Nothing ever writes `g_jni[1]`.
Dalvik returned NULL for a null jclass, so the bridges silently did nothing and
the game still ran; ART crashes while formatting that error. The fix caches a
global reference to `com/com2us/caligo/WrapperManager` (string at `0x0DA2C4`)
once, from a stub placed in the body of `Java_com_com2us_HG_..._nativeForceStopDownload`
(`0x2C720`) — the exported package name does not exist in this APK, so that
function is unreachable dead code.

`__android_init` (`0xB3184`, 0x24 bytes) becomes a trampoline to that stub.

## Writing native patches: three rules

1. **Everything must be position independent.** The library is mapped at a random
   base, so new code reaches data through `ldr rX,[pc,#n]` + `add rX,pc` with a
   *delta* stored in the literal pool. An absolute virtual address in a literal
   writes into whatever lives at that raw address in the process — usually the
   heap — and the game crashes far away from the patch.
2. **`ADD Rd,PC` is not `LDR Rd,[pc]`.** On ARMv5TE the former reads
   `insn_addr + 4` with only bit 0 cleared; the latter rounds down to a word
   boundary. Two bytes of difference here silently produce a wrong pointer.
3. **`blx` keeps Thumb state only for an odd address.** A trampoline to Thumb code
   must pass `target | 1`, or the CPU takes the branch in ARM state and faults.

## Sound effects

`SoundManager` builds `/sdcard/Com2uS/<pkg>/SE/<name>` and calls
`SoundPool.load(String)`. On Android 11+ that fails ("error loading <path>")
because the path belongs to the previous install and the app cannot canonicalise
it. Opening the file and calling `load(FileDescriptor, offset, length, priority)`
works. Register discipline note: the method's `.locals` must stay at 11, because
raising it pushes the parameters past `v15` and the 4-bit `invoke` operands become
illegal; the patch uses `v0..v6`, `v9`, `v10` which are free at that point.

## Touch pad

`DrawViewGameVirtualKey` (`0x71C08`) draws the on-screen d-pad. It is called from
seven sites (gameplay, item shop, popup, and four net-timeout screens). The Java
layer cannot tell the engine whether a physical pad is in use, but the engine's
`nativeEvent` entry (`0x2C624`) receives every input event with `r2 = type`:
`2` = key down, `3` = key up, negative = touch. A hook at that entry records the
last kind in a flag word, and the seven call sites are retargeted to a gate that
returns early while the flag is set.

The flag is a word appended to `.bss` (grow `p_memsz` and the `SHT_NOBITS` section
size by 0x100), so it starts zeroed and lives in the same segment as everything
else the patch touches.

## Where the game keeps its files

One function builds every path the engine uses: `File::GetFullPathName`
(`0xC09C4`, four arguments - name, out, out-len, type). It picks a format string
from a six-entry jump table (`0xEFC20`) and `snprintf`s into the caller's buffer:

| type | format | target |
|---|---|---|
| 3 | `/sdcard/Com2uS/%s/%s` @ `0xEFC74` | external base dir: `resources.csr`, `SE/*.wav` |
| 0,1,2,4 | `/sdcard/Com2uS/%s/lib/[%s/]lib%s.so` and `/data/data/%s/lib/...` | per-file shared-library overrides |
| 5 | `/data/data/%s/%s` @ `0xED698` | app-private files (saves, texture store, ...) |

In every case the varargs are `(jGetPackageName(), name)`, so the format strings
differ only in their prefixes - which is what makes relocating them cheap: the
literal-pool word that selects type 3's format sits at `0xC0B38`, and pointing it
at the `/data/data/%s/%s` string moves the whole resource tree into the app's own
directory. One 32-bit edit, no new code.

Two traps:

* **The literal is GOT-relative, not absolute.** `0xC0B38` holds
  `format - 0x102A38`, and the code does `ldr rX,[pc,#n]; add rX,sb` with `sb` =
  GOT base. An absolute address would be wrong as soon as the loader picks a
  different base. Searching for `0x0EFC74` anywhere in the file finds nothing;
  searching for `0xFFFED23C` finds the one site.
* **The engine mmaps `resources.csr`** (`MMappedFile::GetPointer`), so it needs a
  real file at a real path. An APK asset cannot be mmapped, hence the first-launch
  extraction into `getFilesDir().getParent()` rather than reading from `assets/`.

`SoundManager` builds the sound-effect path in Java (`"/sdcard/Com2uS/"` +
`packageName` + `"/SE/"`), so the three constants there change to `"/data/data/"`
to match.

Carrying the data inside the APK therefore means unpacking it on first launch
(`BundledData.ensure`, called from `WrapperActivity.onCreate` before the engine
starts). Two details make that safe: `resources.csr` is copied to
`resources.csr.new` and renamed over the destination only if it has bytes, and a
separate `.bundle-ok` marker is written last, so an interrupted copy retries on
the next launch instead of leaving a 0-byte package that the engine will trust.

The two branches that matter are easy to invert, and both were wrong in the first
build: `File.exists()` returns **1** for "present", so *skipping* work needs
`if-nez` (an `if-eqz` there extracts only when the file already exists), and the
copy loop must continue while `read()` is positive (`InputStream.read` returns
`-1`, never `0`, at the end, so `if-gt ... :done` exits before the first write).
The symptom of both is identical - an empty file and a cheerful success log.

## Inputs the patcher relies on

The exact anchors in the stock 1.0.4 smali (`package com.com2us.caligo`,
`versionName 1.0.4`, `versionCode 5`). If an anchor does not match exactly once,
the patcher stops instead of producing an APK that looks patched but is not.
