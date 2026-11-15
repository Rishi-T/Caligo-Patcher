# Caligo Patcher

Makes **Caligo Chaser 1.0.4** (Com2uS, 2011) run properly on a modern 32-bit
Android device: it launches instead of crashing, it plays at a manageable speed,
it fills the screen, and it works with a gamepad.

You supply your own copy of the APK. This repository contains no game code and no
game assets — only the patch logic. If you also drop the game's resource folder
(`resources.csr` and `SE/`) into `inputs/`, the patcher packs it into the APK, so
the result installs and plays as a single file.

```
python patch.py            # needs Python 3.10+ and a JDK 17+
```

## Requirements

| Requirement | Notes |
|---|---|
| Python | 3.10 or newer. Standard library only — no pip packages. |
| Java | JDK 17+ (apktool and the signer are Java programs). Any Temurin/OpenJDK build works; point `runtime.java` in `config.yaml` at `.../bin/java.exe` if `java` is not on PATH. |

First run: `python patch.py --bootstrap` downloads the two pinned Java tools
(apktool 2.12.1, uber-apk-signer 1.3.0) into `tools/`. No Android SDK, no
external zip tool, nothing installed system-wide.

## Use

1. Put the original APK in `inputs/`.

   Optionally also put the game's resource folder there — either its contents
   (`resources.csr` + `SE/`) or the whole folder as `Com2uS/com.com2us.caligo/`.
   The patcher finds it and packs it in; skip this and you have to copy the folder
   onto the device yourself, exactly like the stock game.
2. `python patch.py --check` — verifies the config, finds Java and the tools,
   confirms the APK is the expected game, and says whether the resource folder was
   found. Changes nothing.
3. `python patch.py` — builds `outputs/<name>_patched_<timestamp>.apk`.
4. Install it. If an older patched build is installed, uninstall it first (the
   signature differs, so Android refuses the upgrade — and uninstalling deletes
   the game's saves, so back them up if they matter).

All options live in `config.yaml`, which is commented throughout.

With `input.bundle_data` on (the default) the patched game never touches
`/sdcard/Com2uS/` — you can delete that folder. The first launch unpacks about
9 MB into the app's own storage instead: it takes a second, needs no permissions,
and is skipped from then on.

## What it changes

Applied always (the game does not run without these):

| Change | Why |
|---|---|
| Java class handle fix (native, `libgame.so`) | the engine calls the Java side through a cached class pointer it never initialises; old Dalvik ignored that, modern ART crashes inside the class loader |
| Telephony placeholders | the game reads the device id and phone number at startup; Android 10+ throws even with the permission granted |
| Manifest rework | targetSdk, legacy storage flags, `extractNativeLibs`, hardware acceleration |
| Frame cap | the engine advances one tick per rendered frame and has no cap of its own, so a 60/120 Hz display runs the game 2×/4× too fast |

Optional (on by default):

| Change | Why |
|---|---|
| Full screen | the firmware reserves a 55 px navigation strip and side gesture panels; the engine also sized itself from the *app area* instead of the panel, leaving a black band at the top |
| Touch pad auto-hide | the on-screen D-pad covers the game; it hides after the first physical key and returns when you touch the screen |
| Gamepad mapping | the stock key table only knows old feature-phone keys, so a controller does nothing. Bindings are plain names in `config.yaml` |
| Sound effects | they are loaded from a path the app no longer owns; they load through a file descriptor instead |
| Bundled game data | the resources normally live in `/sdcard/Com2uS/<package>/`, which you have to copy by hand. With `input.bundle_data` on, the APK carries them and unpacks them into the app's own directory on first launch, so one install is enough |
| Analytics disabled | the endpoint has been dead for years |

## What it does not do

* **No 64-bit support.** The game ships a single 32-bit ARM library. Devices
  without 32-bit support (most recent flagships) cannot run it at all — no patch
  can change that.
* **No HUD/UI rescaling.** The HUD art is blitted at its authored pixel size, so on
  a 1080p panel it is scaled up and takes too much of the view — the bars and
  buttons crowd the play area. See `docs/FINDINGS.md` for what was tried.
* **No server features.** The original online services are long gone; the game
  is playable offline.
* **No resources or assets are modified.**

## Troubleshooting

| Symptom | Cause |
|---|---|
| `No working Java found` | no JDK on PATH; install one or set `runtime.java` |
| `anchor matched 0 time(s)` | the input is not the 1.0.4 APK, or it is already patched |
| `INSTALL_FAILED_DEPRECATED_SDK_VERSION` | an Android 14+ device refusing a `targetSdk` below 23; install with `adb install --bypass-low-target-sdk-block` |
| `INSTALL_FAILED_UPDATE_INCOMPATIBLE` | a different build is installed; uninstall it first (this deletes saves) |
| game runs too fast / too slow | adjust `patches.ms_per_frame` (40 ≈ 25 fps; higher is slower) |

## Verified on

Tested on an **Ayn Thor** (Android 13, ARMv7) with a physical gamepad: title screen,
menus, help pages, shops, level-ups and normal gameplay all work, played from a fresh
start to almost the end of the game without a crash.

Not exercised: the final stretch of the game, the online features (their servers are
long gone), and any device other than that one.

## How this was made

This is a hobby project: no support, no schedule, no compatibility promises, and no
affiliation with Com2uS.

It was heavily assisted by large language models. Most of the Python, most of the
comments and these docs were written with LLM help, working step by step with a human
who tested every change on real hardware and decided what was safe to ship. The
knowledge behind the patches — which byte in `libgame.so` to change, which key codes
the engine expects, why the class handle is null at launch — came from disassembling
the ARM library and from device testing, not from guessing.

So expect the code to be readable, repetitive in places and occasionally odd. Read it
before you trust it, and treat bug reports as friendly tips rather than tickets.

## Legal

Caligo Chaser and all of its content belong to Com2uS. This tool edits a copy of an
APK that you already own, on your own machine, and ships nothing from the game. Do not
redistribute patched APKs. Details in `NOTICE.md`.

MIT licensed — see `LICENSE`. Technical notes: `docs/FINDINGS.md`.
