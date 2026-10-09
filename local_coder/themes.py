"""Read Orbit Shell's active theme and named color palettes for Lumina."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .settings import DEFAULT_PROJECT


COLOR_KEYS = (
    'background', 'surface', 'surfaceHover', 'textPrimary', 'textSecondary',
    'accent', 'windows', 'orange', 'warning', 'border', 'danger',
)
HEX_COLOR = re.compile(r'^#[0-9a-fA-F]{6}$')
THEME_ENTRY = re.compile(r'name:\s*"([a-z0-9-]+)"\s*,\s*palette:\s*makePalette\((.*?)\)', re.S)
LITERAL_COLOR = re.compile(r'"(#[0-9a-fA-F]{6})"')

DRACULA = dict(zip(COLOR_KEYS, (
    '#282a36', '#343746', '#44475a', '#f8f8f2', '#c3c5d8',
    '#bd93f9', '#8be9fd', '#ffb86c', '#f1fa8c', '#44475a', '#ff5555',
)))
MATERIAL_DEFAULT = dict(zip(COLOR_KEYS, (
    '#1b1b1f', '#29292f', '#36363d', '#e5e1e6', '#c8c5ca',
    '#aac7ff', '#8fc9ff', '#ffb77d', '#e5c36b', '#48484f', '#ffb4ab',
)))


def theme_snapshot(project=DEFAULT_PROJECT, state_root=None):
    """Return only validated colors from the user's Quickshell theme files."""
    project = Path(project)
    state_root = Path(state_root or os.environ.get('XDG_STATE_HOME') or Path.home()/'.local/state')
    palettes = {'dracula': DRACULA.copy()}
    try:
        source = (project/'orbit-shell/config/Theme.qml').read_text()
    except OSError:
        source = ''
    for name, args in THEME_ENTRY.findall(source):
        colors = LITERAL_COLOR.findall(args)
        if len(colors) == len(COLOR_KEYS):
            palettes[name] = dict(zip(COLOR_KEYS, (color.lower() for color in colors)))
        elif name == 'material-you':
            material = MATERIAL_DEFAULT.copy()
            try:
                data = json.loads((project/'colors.json').read_text())
                if isinstance(data, dict):
                    for key in COLOR_KEYS:
                        value = data.get(key)
                        if isinstance(value, str) and HEX_COLOR.fullmatch(value):
                            material[key] = value.lower()
            except (OSError, ValueError):
                pass
            palettes[name] = material
    try:
        selected = (state_root/'orbit-shell/theme').read_text().strip()
    except OSError:
        selected = ''
    if selected not in palettes:
        selected = 'dracula'
    return {'selected': selected, 'themes': [
        {'name': name, 'palette': palette} for name, palette in sorted(palettes.items())
    ]}
