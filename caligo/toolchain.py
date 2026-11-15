# SPDX-License-Identifier: MIT
"""Finding and running the three external pieces: a JDK, apktool, a signer.

Everything is located in the same order: explicit config path, then this
project's tools/ directory, then the environment, then PATH. Nothing is
downloaded unless the user asks for it with --bootstrap, and nothing is
installed system-wide.
"""

import glob
import os
import shutil
import subprocess
import time
import urllib.request

APKTOOL_VERSION = '2.12.1'
SIGNER_VERSION = '1.3.0'

APKTOOL_URL = ('https://github.com/iBotPeaches/Apktool/releases/download/'
               'v%s/apktool_%s.jar' % (APKTOOL_VERSION, APKTOOL_VERSION))
SIGNER_URL = ('https://github.com/patrickfav/uber-apk-signer/releases/download/'
              'v%s/uber-apk-signer-%s.jar' % (SIGNER_VERSION, SIGNER_VERSION))

JAVA_HELP = (
    'No working Java found.\n'
    '  Caligo Patcher needs a JDK 17+ to run apktool and the APK signer.\n'
    '  Install one, or point runtime.java in config.yaml at an extracted JDK, e.g.\n'
    '    C:/Users/you/Downloads/jdk-21.0.2+13/bin/java.exe\n'
    '  Free builds: https://adoptium.net/temurin/releases/')


class ToolError(Exception):
    pass


def _running_in_wsl():
    try:
        with open('/proc/version', 'rb') as f:
            return b'microsoft' in f.read().lower()
    except OSError:
        return False


WSL = _running_in_wsl()


def _to_host_path(p):
    """Translate a POSIX path for a Windows executable.

    Only relevant when Python runs inside WSL but the JDK is a Windows build
    (java.exe) - the usual case on a Windows machine set up for Android work.
    Native Windows Python never takes this path.
    """
    if not p.startswith('/'):
        return p
    if p.startswith('/mnt/') and len(p) > 6 and p[5].isalpha() and p[6] == '/':
        return p[5].upper() + ':' + p[6:]
    return p


def host_args(java, argv):
    """Translate POSIX paths for a Windows java.exe (WSL only)."""
    if WSL and java.lower().endswith('.exe'):
        return [_to_host_path(a) for a in argv]
    return argv


def _which(names):
    for name in names:
        p = shutil.which(name)
        if p:
            return p
    return None


def _exists(p):
    return bool(p) and os.path.isfile(p)


def find_java(explicit=None):
    if explicit:
        cand = os.path.expanduser(str(explicit).replace('/', os.sep))
        if not _exists(cand):
            raise ToolError('runtime.java points at %s, which does not exist' % cand)
        return cand
    home = os.environ.get('JAVA_HOME')
    if home:
        for base in {home, home.replace('\\', '/')}:
            for n in ('java.exe', 'java'):
                cand = os.path.join(base, 'bin', n)
                if _exists(cand):
                    return cand
    found = _which(['java', 'java.exe'])
    if not found:
        raise ToolError(JAVA_HELP)
    return found


class Tools:
    def __init__(self, root, cfg):
        self.root = root
        self.java = self._java(cfg.get('java'))
        self.keytool = self._keytool(cfg.get('java'))
        self.apktool = self._jar(cfg.get('apktool'), 'apktool*.jar', 'APKTOOL', APKTOOL_URL)
        self.signer = self._jar(cfg.get('signer'), 'uber-apk-signer*.jar', None, SIGNER_URL)
        # a Windows java.exe cannot see /mnt/d/... paths
        self.translate = WSL and self.java.lower().endswith('.exe')

    # ---------------------------------------------------------------- java
    def _java(self, explicit):
        return find_java(explicit)

    def _keytool(self, explicit):
        home = os.environ.get('JAVA_HOME')
        bases = []
        if explicit:
            bases.append(os.path.dirname(str(explicit).replace('/', os.sep)))
        if home:
            bases.append(os.path.join(home, 'bin'))
        bases.append(os.path.dirname(self.java))
        for base in bases:
            for n in ('keytool.exe', 'keytool'):
                cand = os.path.join(base, n)
                if _exists(cand):
                    return cand
        raise ToolError('keytool not found next to java (%s). A full JDK is required, '
                        'not just a JRE.' % self.java)

    # ----------------------------------------------------------------- jar
    def _jar(self, explicit, pattern, env, url):
        if explicit:
            cand = os.path.expanduser(str(explicit).replace('/', os.sep))
            if not _exists(cand):
                raise ToolError('%s is configured but does not exist' % cand)
            return cand
        local = sorted(glob.glob(os.path.join(self.root, 'tools', pattern)))
        if local:
            return local[-1]
        if env and os.environ.get(env):
            cand = os.environ[env]
            if _exists(cand):
                return cand
        found = _which([pattern.replace('*.jar', '').rstrip('-_')])
        if found and found.endswith('.jar'):
            return found
        raise ToolError(
            'Missing %s (looked in tools/, the environment, then PATH).\n'
            '  Run:  python patch.py --bootstrap\n'
            '  (downloads apktool %s and uber-apk-signer %s into tools/)\n'
            '  or set the path in config.yaml.'
            % (pattern.replace('*.jar', ''), APKTOOL_VERSION, SIGNER_VERSION))

    # --------------------------------------------------------------- execs
    def _run(self, cmd, what, cwd=None, quiet=False):
        if getattr(self, 'translate', False):
            cmd = [cmd[0]] + [_to_host_path(a) for a in cmd[1:]]
        proc = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True,
                              errors='replace')
        if proc.returncode != 0:
            tail = '\n'.join(proc.stdout.strip().splitlines()[-25:])
            raise ToolError('%s failed (exit %d)\n%s' % (what, proc.returncode, tail))
        return proc.stdout

    def java_version(self):
        return self._run([self.java, '-version'], 'java -version').strip().splitlines()[0]

    def apktool_cmd(self, args, what, quiet=False):
        return self._run([self.java, '-jar', self.apktool] + args, what, quiet=quiet)

    def signer_cmd(self, args, what):
        return self._run([self.java, '-jar', self.signer] + args, what)

    def keytool_cmd(self, args, what):
        return self._run([self.keytool] + args, what)


def _human(n):
    return '%.1f MB' % (n / 1048576.0) if n >= 1048576 else '%d KB' % max(1, n // 1024)


def _download(url, dest, label, attempts=3):
    """Fetch one jar, with a per-read timeout, progress output and retries.

    GitHub redirects release downloads to a separate host, which can stall for
    many seconds (measured: 10 s just for the redirect) - and urlopen() without a
    timeout waits forever when that happens, with nothing printed, which looks
    exactly like a hang. So: hard timeout, visible progress, retry, and verify the
    result is really a jar before trusting it.
    """
    part = dest + '.part'
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'caligo-patcher'})
            started = time.time()
            with urllib.request.urlopen(req, timeout=30) as r, open(part, 'wb') as f:
                total = int(r.headers.get('Content-Length') or 0)
                got = 0
                last_pct = -10
                while True:
                    chunk = r.read(262144)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if total:
                        pct = int(got * 100 / total)
                        if pct >= last_pct + 10:
                            last_pct = pct
                            print('    %3d%%  %s / %s' % (pct, _human(got), _human(total)),
                                  flush=True)
                    elif got // (1 << 20) > (got - len(chunk)) // (1 << 20):
                        print('    %s' % _human(got), flush=True)
            size = os.path.getsize(part)
            if size < 65536:
                raise OSError('only %d bytes downloaded' % size)
            os.replace(part, dest)
            print('  %s: %s in %.1fs' % (label, _human(size), time.time() - started))
            return dest
        except Exception as exc:                      # noqa: BLE001 - report and retry
            if os.path.exists(part):
                os.remove(part)
            print('  %s: attempt %d/%d failed: %s' % (label, attempt, attempts, exc))
            if attempt < attempts:
                time.sleep(2 * attempt)
    raise ToolError(
        'Could not download %s.\n'
        '  Download it manually and put it in tools/:\n    %s' % (label, url))


def _check_jar(tools_cfg, jar, label):
    """Confirm a downloaded jar actually runs (catches HTML error pages)."""
    try:
        out = subprocess.run([tools_cfg] + host_args(tools_cfg, ['-jar', jar, '--version']),
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, errors='replace', timeout=90)
    except subprocess.TimeoutExpired:
        print('  %s: did not answer --version within 90 s (kept anyway)' % label)
        return
    first = (out.stdout or '').strip().splitlines()
    print('  %s: %s' % (label, first[0] if first else 'no version output'))


def bootstrap(root):
    os.makedirs(os.path.join(root, 'tools'), exist_ok=True)
    targets = [(APKTOOL_URL, 'apktool_%s.jar' % APKTOOL_VERSION, 'apktool'),
               (SIGNER_URL, 'uber-apk-signer-%s.jar' % SIGNER_VERSION, 'uber-apk-signer')]
    for url, name, label in targets:
        dest = os.path.join(root, 'tools', name)
        if os.path.isfile(dest):
            print('  already present: %s (%s)' % (name, _human(os.path.getsize(dest))))
            continue
        print('  downloading %s' % label)
        _download(url, dest, label)

    # verify with whichever java the config resolves to, if one can be found
    try:
        java_path = find_java()
    except ToolError:
        print('  (skipping the jar check: no Java found yet)')
        return
    for _, name, label in targets:
        dest = os.path.join(root, 'tools', name)
        if os.path.isfile(dest):
            _check_jar(java_path, dest, label)
