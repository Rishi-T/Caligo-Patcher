# SPDX-License-Identifier: MIT
"""The game's own key vocabulary, and the physical buttons that can drive it.

Everything user-facing is a readable name. Hex appears only here.

`ACTIONS` maps a config name to the `:sswitch_N` label that already implements
that game key inside `WrapperActivity.getGameKeyCode()`. The labels are
positional in the stock method (they are only jump targets), so each one is
paired with the engine key constant it handles - that constant is what the
label body compares against, and it is what makes "charge" different from
"action".
"""

# config name -> (sswitch label, engine key constant)
ACTIONS = {
    'ability_1': ('sswitch_0', 0x31),
    'ability_2': ('sswitch_1', 0x33),
    'ability_3': ('sswitch_2', 0x37),
    'ability_4': ('sswitch_3', 0x39),
    'ability_5': ('sswitch_4', 0x30),
    'up': ('sswitch_5', 0x3A),
    'left': ('sswitch_6', 0x3C),
    'right': ('sswitch_7', 0x3D),
    'down': ('sswitch_8', 0x3B),
    'charge': ('sswitch_9', 0x2710),
    'action': ('sswitch_a', 0x3E),
    'menu': ('sswitch_b', 0x2711),
    'cancel': ('sswitch_c', 0x49),
    'info': ('sswitch_e', 0x2713),
}

# config name -> Android KeyEvent keycode
BUTTONS = {
    'dpad_up': 0x13,
    'dpad_down': 0x14,
    'dpad_left': 0x15,
    'dpad_right': 0x16,
    'a': 0x60,
    'b': 0x61,
    'x': 0x63,
    'y': 0x64,
    'l1': 0x66,
    'r1': 0x67,
    'l2': 0x68,
    'r2': 0x69,
    'thumbl': 0x6A,
    'thumbr': 0x6B,
    'start': 0x6C,
    'select': 0x6D,
}

ALIASES = {
    'ability1': 'ability_1', 'ability2': 'ability_2', 'ability3': 'ability_3',
    'ability4': 'ability_4', 'ability5': 'ability_5',
    'confirm': 'action', 'back': 'cancel', 'map': 'info', 'charge_attack': 'charge',
    'l3': 'thumbl', 'r3': 'thumbr',
    'dpadup': 'dpad_up', 'dpaddown': 'dpad_down',
    'dpadleft': 'dpad_left', 'dpadright': 'dpad_right',
    'lb': 'l1', 'rb': 'r1', 'lt': 'l2', 'rt': 'r2',
    'button_a': 'a', 'button_b': 'b', 'button_x': 'x', 'button_y': 'y',
}

ORDER = ['dpad_up', 'dpad_down', 'dpad_left', 'dpad_right',
         'a', 'b', 'x', 'y', 'l1', 'l2', 'r1', 'r2',
         'thumbl', 'thumbr', 'start', 'select']


def resolve(kind, name, table):
    key = str(name).strip().lower()
    key = ALIASES.get(key, key)
    if key not in table:
        raise ValueError('%s %r is not known (known: %s)'
                         % (kind, name, ', '.join(sorted(table))))
    return key


def build_block(bindings):
    """Render the `.sparse-switch` entries for the configured bindings.

    Returned sorted by Android keycode, which is the order the assembler wants
    and the order the payload ends up in.
    """
    entries = []
    for button, action in bindings.items():
        if action is None:
            continue
        b = resolve('button', button, BUTTONS)
        a = resolve('action', action, ACTIONS)
        entries.append((BUTTONS[b], ACTIONS[a][0], b, a))
    if not entries:
        raise ValueError('controller.enabled is true but no bindings are set')
    entries.sort()
    lines = []
    for code, label, b, a in entries:
        lines.append('        0x%02x -> :%s' % (code, label))
    return ''.join(l + '\n' for l in lines), entries


def check_labels(method_text, entries):
    """Fail if a generated target label is not defined in the stock method."""
    # decoded smali may carry CRLF (apktool on Windows), so normalise first
    text = method_text.replace('\r\n', '\n')
    missing = [lbl for _, lbl, _, _ in entries if (':%s\n' % lbl) not in text]
    if missing:
        raise ValueError('input does not look like a clean 1.0.4: label(s) %s not found '
                         'in getGameKeyCode()' % ', '.join(':' + m for m in missing))
