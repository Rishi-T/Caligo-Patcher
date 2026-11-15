# SPDX-License-Identifier: MIT
"""Config handling, the stage runner, build, sign and the final report."""

import hashlib
import os
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime

from caligo import keys, toolchain, yamlite
from caligo.smali import StageError, Tree

import patches.autohide
import patches.core
import patches.fullscreen
import patches.jni_class
import patches.manifest

LIB_PATH = 'lib/armeabi/libgame.so'

# order matters: the manifest supplies the storage/locale settings every later
# edit assumes, and nothing else depends on another stage's text
STAGES = [
    ('manifest + crash fixes', patches.manifest),
    ('java class handle (native)', patches.jni_class),
    ('controller, frame cap, sound', patches.core),
    ('touch pad handling', patches.autohide),
    ('full screen', patches.fullscreen),
]

DEFAULTS = {
    'input': {'apk': 'auto'},
    'device': {'target_sdk': 5, 'min_sdk': 9},
    'patches': {'fullscreen': True, 'touch_pad': 'autohide', 'soundpool_fd_fix': True,
                'disable_flurry': True, 'diagnostics': False, 'ms_per_frame': 40},
    'controller': {'enabled': True, 'bindings': None},
    'signing': {'keystore': 'signing/caligo.jks', 'alias': 'caligo',
                'store_pass': 'caligo123', 'key_pass': 'caligo123'},
    'runtime': {'java': None, 'apktool': None, 'signer': None, 'keep_decoded': False},
}

DEFAULT_BINDINGS = {
    'dpad_up': 'up', 'dpad_down': 'down', 'dpad_left': 'left', 'dpad_right': 'right',
    'a': 'action', 'b': 'cancel', 'x': 'charge', 'y': 'ability_5',
    'l1': 'ability_1', 'l2': 'ability_2', 'r1': 'ability_3', 'r2': 'ability_4',
    'start': 'menu', 'select': 'info',
}

ALLOWED_SDK = range(5, 37)


class ConfigError(Exception):
    pass


# --------------------------------------------------------------------- config
def load_config(root, path=None):
    path = path or os.path.join(root, 'config.yaml')
    if not os.path.isfile(path):
        raise ConfigError('no config.yaml found at %s' % path)
    with open(path, 'rb') as f:
        raw = f.read().decode('utf-8')
    try:
        user = yamlite.parse(raw)
    except yamlite.ConfigError as e:
        raise ConfigError('%s: %s' % (path, e))
    cfg = _merge(DEFAULTS, user, path)
    _validate(cfg)
    return cfg


def _merge(defaults, user, path):
    out = {}
    for key, dflt in defaults.items():
        given = user.get(key)
        if given is None:
            given = {}
        if not isinstance(given, dict):
            raise ConfigError('%s: section %r must be a mapping' % (path, key))
        merged = dict(dflt) if isinstance(dflt, dict) else dflt
        for k, v in given.items():
            if k not in dflt:
                raise ConfigError('%s: unknown setting %s.%s' % (path, key, k))
            merged[k] = v
        out[key] = merged
    for key in user:
        if key not in defaults:
            raise ConfigError('%s: unknown section %r' % (path, key))
    if out['controller']['bindings'] is None:
        out['controller']['bindings'] = dict(DEFAULT_BINDINGS)
    return out


def _validate(cfg):
    dev = cfg['device']
    for name in ('target_sdk', 'min_sdk'):
        val = dev[name]
        if not isinstance(val, int) or val not in ALLOWED_SDK:
            raise ConfigError('device.%s must be an integer between 5 and 36 (got %r)'
                              % (name, val))

    ms = cfg['patches']['ms_per_frame']
    if not isinstance(ms, int) or not 16 <= ms <= 100:
        raise ConfigError('patches.ms_per_frame must be an integer 16..100 ms '
                          '(40 = 25 fps, 45 = slightly slower); got %r' % (ms,))
    mode = str(cfg['patches']['touch_pad']).strip().lower()
    if mode not in ('autohide', 'auto', 'always_hidden', 'hidden',
                    'always_visible', 'visible', 'off'):
        raise ConfigError('patches.touch_pad must be autohide, always_hidden or '
                          'always_visible (got %r)' % cfg['patches']['touch_pad'])
    for flag in ('fullscreen', 'soundpool_fd_fix', 'disable_flurry', 'diagnostics'):
        if not isinstance(cfg['patches'][flag], bool):
            raise ConfigError('patches.%s must be true or false' % flag)

    ctl = cfg['controller']
    if not isinstance(ctl['enabled'], bool):
        raise ConfigError('controller.enabled must be true or false')
    if not isinstance(ctl['bindings'], dict):
        raise ConfigError('controller.bindings must be a mapping of button: action')
    seen = {}
    for button, action in ctl['bindings'].items():
        try:
            b = keys.resolve('button', button, keys.BUTTONS)
            if action is not None:
                a = keys.resolve('action', action, keys.ACTIONS)
                if a in seen:
                    warn('buttons %r and %r both send %r' % (seen[a], b, a))
                seen[a] = b
        except ValueError as e:
            raise ConfigError('controller.bindings: %s' % e)

    sign = cfg['signing']
    for name in ('keystore', 'alias', 'store_pass', 'key_pass'):
        if not sign[name]:
            raise ConfigError('signing.%s must not be empty' % name)

    if cfg['runtime']['java'] is not None and not isinstance(cfg['runtime']['java'], str):
        raise ConfigError('runtime.java must be null or a path to a java executable')


_WARNINGS = []


def warn(msg):
    _WARNINGS.append(msg)
    print('  warning: %s' % msg)


# ---------------------------------------------------------------------- input
def resolve_input(root, cfg):
    given = str(cfg['input']['apk']).strip()
    if given.lower() not in ('auto', ''):
        path = given if os.path.isabs(given) else os.path.join(root, given)
        if not os.path.isfile(path):
            raise ConfigError('input.apk points at %s, which does not exist' % path)
        return path
    base = os.path.join(root, 'inputs')
    found = []
    for dirpath, _, names in os.walk(base):
        for n in names:
            if n.lower().endswith('.apk'):
                found.append(os.path.join(dirpath, n))
    if not found:
        raise ConfigError('no APK in %s - put the original 1.0.4 APK there '
                          '(or set input.apk)' % base)
    if len(found) > 1:
        raise ConfigError('%d APKs in inputs/ - set input.apk to the one you want:\n  %s'
                          % (len(found), '\n  '.join(os.path.relpath(p, root) for p in found)))
    return found[0]


def output_path(root, input_apk):
    base = os.path.join(root, 'inputs')
    rel = os.path.relpath(input_apk, base)
    if rel.startswith('..'):
        rel = os.path.basename(input_apk)
    stamp = datetime.now().strftime('%Y%m%dT%H%M%S')
    stem, _ = os.path.splitext(os.path.basename(rel))
    name = '%s_patched_%s.apk' % (stem, stamp)
    return os.path.join(root, 'outputs', os.path.dirname(rel), name)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def apk_facts(path):
    with zipfile.ZipFile(path) as z:
        bad = z.testzip()
        if bad:
            raise ConfigError('%s is corrupt (bad entry %r)' % (path, bad))
        names = z.namelist()
    facts = {'entries': len(names)}
    for required in ('AndroidManifest.xml', 'classes.dex', LIB_PATH):
        if required not in names:
            raise ConfigError('%s has no %s - not a Caligo Chaser APK'
                              % (os.path.basename(path), required))
    return facts


# ---------------------------------------------------------------------- stage
class Ctx:
    def __init__(self, tree, lib, config):
        self.tree = tree
        self.lib = lib
        self.config = config

    def note(self, msg):
        print('    %s' % msg)


def decode(tools, apk, dest):
    tools.apktool_cmd(['d', '-f', '-o', dest, apk], 'apktool decode')


def input_version(tree):
    try:
        yml = tree.read('apktool.yml')
    except OSError:
        return None
    for line in yml.splitlines():
        if line.strip().startswith('versionName:'):
            return line.split(':', 1)[1].strip().strip('"\'')
    return None


# ----------------------------------------------------------------------- main
def run(root, args):
    cfg = load_config(root, args.config)

    if args.check or args.dry_run:
        print('\n== config')
        print('  input     : %s' % cfg['input']['apk'])
        print('  targetSdk : %d   (tested value: 5)' % cfg['device']['target_sdk'])
        print('  minSdk    : %d' % cfg['device']['min_sdk'])
        print('  frame cap : %d ms/frame (~%d fps)' %
              (cfg['patches']['ms_per_frame'], 1000 // cfg['patches']['ms_per_frame']))
        print('  patches   : %s' % ', '.join(
            '%s=%s' % (k, cfg['patches'][k]) for k in
            ('fullscreen', 'touch_pad', 'soundpool_fd_fix', 'disable_flurry', 'diagnostics')))
        print('  controller: %s' % ('on, %d bindings' % len(cfg['controller']['bindings'])
                                    if cfg['controller']['enabled'] else 'off'))

    apk = resolve_input(root, cfg)
    out = output_path(root, apk)
    print('\n== input: %s' % os.path.relpath(apk, root))
    if args.check or args.dry_run:
        facts = apk_facts(apk)
        print('  %d entries, %s' % (facts['entries'], _size(apk)))

    if cfg['device']['target_sdk'] != 5:
        warn('device.target_sdk is %d; only 5 has been tested. Behaviour changes at '
             '23+ (runtime permissions, scoped storage, insets) affect these patches.'
             % cfg['device']['target_sdk'])

    if args.check:
        tools = toolchain.Tools(root, cfg['runtime'])
        print('\n== tools')
        print('  java      : %s' % tools.java)
        print('              %s' % tools.java_version())
        print('  apktool   : %s' % os.path.basename(tools.apktool))
        print('  signer    : %s' % os.path.basename(tools.signer))
        print('\n== plan')
        for name, _ in STAGES:
            print('  - %s' % name)
        print('\n== output would be: %s' % os.path.relpath(out, root))
        print('\ncheck ok')
        return 0

    tools = toolchain.Tools(root, cfg['runtime'])
    work = os.path.join(root, 'build', os.path.splitext(os.path.basename(out))[0])
    decoded = os.path.join(work, 'decoded')
    if os.path.isdir(work):
        shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)

    print('\n== decode')
    decode(tools, apk, decoded)
    tree = Tree(decoded)

    version = input_version(tree)
    print('  versionName: %s' % version)
    if version and version != '1.0.4':
        warn('input reports version %s; this patcher targets 1.0.4' % version)

    libpath = tree.path(LIB_PATH)
    if not os.path.isfile(libpath):
        raise ConfigError('%s missing from the decoded APK' % LIB_PATH)
    with open(libpath, 'rb') as f:
        lib = bytearray(f.read())

    ctx = Ctx(tree, lib, cfg)
    print('\n== patches')
    for name, module in STAGES:
        print('  [%s]' % name)
        try:
            module.apply(ctx)
        except (StageError, ValueError) as e:
            raise ConfigError('stage "%s" failed:\n%s' % (name, e))
    with open(libpath, 'wb') as f:
        f.write(bytes(lib))

    if args.dry_run:
        print('\ndry run: patches applied to %s (nothing built)' % os.path.relpath(decoded, root))
        return 0

    print('\n== build')
    unsigned = os.path.join(work, 'app-unsigned.apk')
    tools.apktool_cmd(['b', '-f', '-o', unsigned, decoded], 'apktool build')
    print('  %s' % _size(unsigned))

    print('\n== sign')
    keystore = _keystore(root, cfg['signing'], tools)
    tools.signer_cmd(['-a', unsigned, '--allowResign',
                      '--ks', keystore, '--ksAlias', cfg['signing']['alias'],
                      '--ksPass', cfg['signing']['store_pass'],
                      '--ksKeyPass', cfg['signing']['key_pass'],
                      '--overwrite'], 'sign')
    idsig = unsigned + '.idsig'
    if os.path.isfile(idsig):
        os.remove(idsig)

    os.makedirs(os.path.dirname(out), exist_ok=True)
    shutil.move(unsigned, out)
    if not cfg['runtime']['keep_decoded']:
        shutil.rmtree(work, ignore_errors=True)
    else:
        print('  decoded tree kept at %s' % os.path.relpath(decoded, root))

    _verify(tools, out)
    _report(root, apk, out, cfg)
    return 0


def _keystore(root, sign, tools):
    path = sign['keystore']
    if not os.path.isabs(path):
        path = os.path.join(root, path)
    if os.path.isfile(path):
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    print('  generating %s' % os.path.relpath(path, root))
    tools.keytool_cmd(['-genkeypair', '-keystore', path,
                       '-alias', sign['alias'], '-keyalg', 'RSA', '-keysize', '2048',
                       '-validity', '10000',
                       '-storepass', sign['store_pass'], '-keypass', sign['key_pass'],
                       '-dname', 'CN=Caligo Patcher, OU=hobby, O=hobby, '
                                 'L=na, ST=na, C=US'], 'keytool')
    return path


def _verify(tools, apk):
    print('\n== verify')
    out = tools.signer_cmd(['-a', apk, '-y'], 'signer verify')
    for line in out.strip().splitlines():
        if any(k in line for k in ('Verified', 'verified', 'DOES NOT', 'ERROR')):
            print('  %s' % line.strip())
    with zipfile.ZipFile(apk) as z:
        bad = z.testzip()
        if bad:
            raise ConfigError('produced APK is corrupt (bad entry %r)' % bad)


def _report(root, src, out, cfg):
    print('\n== done')
    print('  %s' % os.path.abspath(out))
    print('  %s   sha256 %s' % (_size(out), sha256(out)))
    print('\n  install it:')
    print('    * copy the APK to the device and open it, or')
    print('    * with adb and debugging enabled:')
    print('        adb install -r "%s"' % os.path.basename(out))
    print('  If an older patched build is installed, uninstall it first (the signature')
    print('  differs, so an upgrade is refused). Uninstalling deletes the game\'s saves.')
    if cfg['device']['target_sdk'] < 23:
        print('  On Android 14+ a targetSdk below 23 cannot be installed over the GUI;')
        print('  adb can bypass it:')
        print('        adb install --bypass-low-target-sdk-block "%s"' % os.path.basename(out))
    print('\n  note: the game is 32-bit ARM only. Devices without 32-bit support')
    print('        (most recent flagships) cannot run it at all.')
    lines = [l for l in _WARNINGS]
    if lines:
        print('\n  warnings from this run:')
        for l in lines:
            print('    - %s' % l)


def _size(path):
    n = os.path.getsize(path)
    for unit in ('B', 'KB', 'MB'):
        if n < 1024 or unit == 'MB':
            return '%.1f %s' % (n, unit) if unit != 'B' else '%d B' % n
        n /= 1024.0
    return '%d B' % n
