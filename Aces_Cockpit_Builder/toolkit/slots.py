"""Slot map loader. The data is in slots.json (or the file named by AOT_SLOTS); scripts import from here."""
import json, os
from pathlib import Path

PATH = Path(os.environ.get('AOT_SLOTS') or Path(__file__).with_name('slots.json'))
DATA = json.loads(PATH.read_text(encoding='utf-8'))
NAME = DATA['pack_name']
COCKPITS = DATA['cockpits']
BY_PLANE = {c['plane']: c for c in COCKPITS}
PAIRS = {c['plane']: c['slot'] for c in COCKPITS}
CONFIGS = {c['plane']: c['config'] for c in COCKPITS}
SELECTED = {**CONFIGS, **DATA.get('unassigned', {})}
TYPE98_DONOR = DATA['type98_donor_slot']
GLASS = {c['plane']: (c['slot'], c['glass_atlas']) for c in COCKPITS if c.get('glass_atlas')}
TELESCOPES = [c for c in COCKPITS if c['optic_kind'] == 'aldis_telescope']
REFLECTOR_EXCLUDE = set(DATA.get('reflector_hide', {}).get('exclude_slots', []))
REFLECTOR_AUTO = DATA.get('reflector_hide', {}).get('mode', 'auto') == 'auto'
REFLECTOR_ONLY = DATA.get('reflector_hide', {}).get('slots', [])
