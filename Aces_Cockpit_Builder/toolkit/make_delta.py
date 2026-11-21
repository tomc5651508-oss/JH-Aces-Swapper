"""Turn the built package into a delta over the selected JH base.

- A package file byte-identical to the base file at the same path is dropped (no base copies in the pack).
- Text files the builder derives from the base (plane scripts, pilot bots, <slot>-C.txt) are dropped; the one line
  each changes goes into aces_gunsight_delta.json, applied to the live base script at play time:
    plane script  GunsightPosition = x, y, z           (eye for the sight)
    pilot bot     position = x, y, z  in [attach=0]     (head = eye minus the plane script attach position)
    <slot>-C.txt  CloseSphere = x, y, z, r
- aces_pack_base.json: sha256 of every base file the pack was built from (a later JH update = rebuild prompt).
usage: make_delta.py <package> <base>   (also called by worker.py)"""
import datetime, hashlib, json, re, sys
from pathlib import Path

DELTA = 'aces_gunsight_delta.json'


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _kind(rel):
    low = rel.lower()
    if not low.endswith('.txt') or not low.startswith('data/'):
        return None
    if '/luascripts/worldobjects/planes/' in low and low.count('/') == 4:
        return ('GunsightPosition', None)
    if '/luascripts/worldobjects/bots/' in low:
        return ('position', 'attach=0')
    if low.endswith('-c.txt') and '/graphics/planes/' in low:
        return ('CloseSphere', None)
    return None


def _line(text, key, section):
    """(line number, line) of `key =` (inside [section] ... [end] when given) or None"""
    lines, inside = text.splitlines(), section is None
    for i, ln in enumerate(lines):
        s = ln.strip().lower()
        if section is not None:
            if s == f'[{section}]':
                inside = True
                continue
            if inside and s == '[end]':
                return None
        if inside and re.match(rf'\s*{key}\s*=', ln, re.I):
            return i, ln.rstrip('\r\n')
    return None


def _blocked():
    """slots.json blocked_slots: no file and no view line for these slots goes into the pack."""
    try:
        from slots import DATA
        names = DATA.get('blocked_slots', [])
    except Exception:
        names = json.loads(Path(__file__).with_name('slots.json').read_text(encoding='utf-8')).get('blocked_slots', [])
    return [re.compile(rf'(^|[/_]){re.escape(n.lower())}(?![a-z0-9])') for n in names]


def is_blocked(rel, pats=None):
    low = rel.lower()
    return any(p.search(low) for p in (_blocked() if pats is None else pats))


def make_delta(package, base, base_label=None, derived=()):
    package, base = Path(package), Path(base)
    delta, dropped, kept_text, blocked = {}, [], [], []
    pats = _blocked()
    derived = [r for r in derived if not is_blocked(r, pats)]
    for p in sorted(x for x in package.rglob('*') if x.is_file()):
        rel = p.relative_to(package).as_posix()
        if is_blocked(rel, pats):
            p.unlink()
            blocked.append(rel)
            continue
        b = base / rel
        data = p.read_bytes()
        kind = _kind(rel)
        if kind and b.is_file():
            src = b.read_bytes()
            key, section = kind
            new, old = _line(data.decode('latin1'), key, section), _line(src.decode('latin1'), key, section)
            a, o = data.decode('latin1').splitlines(), src.decode('latin1').splitlines()
            others = [i for i, (x, y) in enumerate(zip(a, o)) if x != y and (new is None or i != new[0])]
            if new is None or old is None or len(a) != len(o) or others:
                kept_text.append(rel)            # not a one-line change: kept whole, listed in the report
                continue
            if new[1] != old[1]:
                delta[rel] = {'key': key, 'section': section, 'line': new[1], 'base_line': old[1],
                              'base_sha256': _sha(src)}
            p.unlink()
            dropped.append(rel)
        elif b.is_file() and b.read_bytes() == data:
            p.unlink()
            dropped.append(rel)
    for d in sorted((x for x in package.rglob('*') if x.is_dir()), key=lambda x: -len(x.parts)):
        if not any(d.iterdir()):
            d.rmdir()
    (package / DELTA).write_text(json.dumps({
        'format': 1,
        'about': 'Aces cockpit view lines. For each path: in the live JH base file, find the first line whose '
                 'text starts with "<key>" then "=" (inside [<section>] ... [end] when section is set) and replace '
                 'that whole line, up to but not including its line ending, with "line" (leading whitespace included). Every other byte stays as in '
                 'the base. Without these lines the Aces cockpits are seen from the JH eye.',
        'base_folder': base.name, 'files': delta}, indent=2) + '\n', encoding='utf-8')
    rels = set(derived) | set(delta)
    (package / 'aces_pack_base.json').write_text(json.dumps({
        'about': 'Base files this Aces pack was built from. A sha256 that differs from the live base = rebuild the '
                 'pack (the view lines in ' + DELTA + ' still apply).',
        'base_folder': base.name, 'base_label': base_label,
        'built': datetime.datetime.now().isoformat(timespec='seconds'),
        'base_files': {r: _sha((base / r).read_bytes()) for r in sorted(rels) if (base / r).is_file()}},
        indent=2) + '\n', encoding='utf-8')
    return {'delta_lines': len(delta), 'dropped': dropped, 'kept_whole_text': kept_text, 'blocked': blocked}


if __name__ == '__main__':
    r = make_delta(sys.argv[1], sys.argv[2])
    print(json.dumps(r, indent=1))
