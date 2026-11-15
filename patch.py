#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Caligo Patcher - turn a stock Caligo Chaser 1.0.4 APK into a playable one.

    python patch.py                 build using config.yaml
    python patch.py --check         validate config, tools and input only
    python patch.py --dry-run       apply the patches to a decoded tree, build nothing
    python patch.py --bootstrap     download apktool + the signer into tools/

Requires Python 3.10+ and a JDK 17+ (apktool and the signer are Java programs).
Nothing else: no pip packages, no external zip tool, no Android SDK.
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from caligo import pipeline, toolchain          # noqa: E402
from caligo.elfx import ElfError                # noqa: E402
from caligo.smali import StageError             # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='patch.py',
        description='Patch Caligo Chaser 1.0.4 for modern 32-bit Android devices.')
    ap.add_argument('--config', default=None, help='config file (default: config.yaml)')
    ap.add_argument('--check', action='store_true',
                    help='validate config, tools and the input APK, then stop')
    ap.add_argument('--dry-run', action='store_true', dest='dry_run',
                    help='decode and patch, but do not build or sign')
    ap.add_argument('--bootstrap', action='store_true',
                    help='download the pinned tools into tools/')
    ap.add_argument('--keep-decoded', action='store_true', dest='keep_decoded',
                    help='keep the decoded working tree under build/')
    args = ap.parse_args(argv)

    try:
        if args.bootstrap:
            print('== bootstrap')
            toolchain.bootstrap(ROOT)
            print('  done - tools/ now holds apktool %s and uber-apk-signer %s'
                  % (toolchain.APKTOOL_VERSION, toolchain.SIGNER_VERSION))
            return 0
        if args.keep_decoded:
            pipeline.DEFAULTS['runtime']['keep_decoded'] = True
        return pipeline.run(ROOT, args)
    except (pipeline.ConfigError, toolchain.ToolError, StageError, ElfError) as e:
        print('\nerror: %s' % e, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('\ninterrupted', file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
