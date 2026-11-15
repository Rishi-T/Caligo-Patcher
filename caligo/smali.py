# SPDX-License-Identifier: MIT
"""Exact-anchor text editing for decoded smali / XML files.

Every edit must match exactly the expected number of times. A mismatch is a
hard error naming the file and showing the anchor, because a patcher that
silently does nothing is worse than one that refuses: it produces an APK that
looks patched and behaves like stock.
"""

import os


class StageError(Exception):
    pass


class Tree:
    def __init__(self, root):
        self.root = root

    def path(self, rel):
        return os.path.join(self.root, rel.replace('/', os.sep))

    def read(self, rel):
        with open(self.path(rel), 'rb') as f:
            return f.read().decode('utf-8')

    def write(self, rel, text):
        p = self.path(rel)
        os.makedirs(os.path.dirname(p) or '.', exist_ok=True)
        with open(p, 'wb') as f:
            f.write(text.encode('utf-8'))

    def patch(self, rel, old, new, count=1):
        text = self.read(rel)
        crlf = '\r\n' in text
        body = text.replace('\r\n', '\n')
        found = body.count(old)
        if found != count:
            raise StageError(
                '%s: anchor matched %d time(s), expected %d.\n'
                '  The input APK is not the expected version, or it is already patched.\n'
                '  Anchor began with: %r' % (rel, found, count, old[:120]))
        body = body.replace(old, new, count)
        if crlf:
            body = body.replace('\n', '\r\n')
        self.write(rel, body)
        return found
