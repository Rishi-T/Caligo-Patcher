# SPDX-License-Identifier: MIT
"""A very small YAML subset parser (no dependencies).

Supported, and nothing else:

    key: value            # comment
    nested:
      child: 1
    list:
      - a
      - b
    inline: [a, b]        # flat, scalars only

Scalars:  quoted or bare strings, integers, true/false, null/~.
Anything outside this subset (multi-line strings, anchors, aliases, flow maps,
multiple documents, tabs) raises ConfigError instead of being guessed at.
"""


class ConfigError(Exception):
    pass


def _strip_comment(line):
    quote = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == quote:
                quote = None
        elif ch in '"\'':
            quote = ch
        elif ch == '#' and (i == 0 or line[i - 1] in ' \t'):
            return line[:i]
        i += 1
    return line


def _scalar(text):
    t = text.strip()
    if t == '':
        return None
    if t[0] in '"\'':
        if len(t) < 2 or t[-1] != t[0]:
            raise ConfigError('unterminated quoted string: %r' % t)
        return t[1:-1]
    if t.startswith('['):
        if not t.endswith(']'):
            raise ConfigError('unterminated inline list: %r' % t)
        inner = t[1:-1].strip()
        return [] if not inner else [_scalar(x) for x in inner.split(',')]
    low = t.lower()
    if low in ('true', 'yes'):
        return True
    if low in ('false', 'no'):
        return False
    if low in ('null', '~', 'none'):
        return None
    try:
        return int(t, 0)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        pass
    return t


def _tokenize(text):
    out = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = _strip_comment(raw).replace('\r', '')
        if not line.strip():
            continue
        stripped = line.lstrip(' ')
        if '\t' in line[:len(line) - len(stripped)]:
            raise ConfigError('line %d: tabs are not allowed for indentation' % n)
        out.append((len(line) - len(stripped), stripped, n))
    return out


def _block(tokens, i, indent):
    if i >= len(tokens):
        return None, i
    is_list = tokens[i][1].startswith('- ')
    result = [] if is_list else {}
    while i < len(tokens):
        ind, text, n = tokens[i]
        if ind < indent:
            break
        if ind > indent:
            raise ConfigError('line %d: unexpected indentation' % n)
        if is_list:
            if not text.startswith('- '):
                raise ConfigError('line %d: mixed list and mapping' % n)
            result.append(_scalar(text[2:]))
            i += 1
            continue
        if text.startswith('- '):
            raise ConfigError('line %d: mixed list and mapping' % n)
        if ':' not in text:
            raise ConfigError('line %d: expected "key: value"' % n)
        key, _, rest = text.partition(':')
        key = key.strip()
        if not key:
            raise ConfigError('line %d: empty key' % n)
        if key in result:
            raise ConfigError('line %d: duplicate key %r' % (n, key))
        if rest.strip():
            result[key] = _scalar(rest)
            i += 1
            continue
        # nested block: the next token must be indented deeper
        if i + 1 < len(tokens) and tokens[i + 1][0] > ind:
            value, i = _block(tokens, i + 1, tokens[i + 1][0])
            result[key] = value
        else:
            result[key] = None
            i += 1
    return result, i


def parse(text):
    tokens = _tokenize(text)
    if not tokens:
        return {}
    value, i = _block(tokens, 0, tokens[0][0])
    if i != len(tokens):
        raise ConfigError('line %d: trailing content' % tokens[i][2])
    if not isinstance(value, dict):
        raise ConfigError('top level must be a mapping')
    return value
