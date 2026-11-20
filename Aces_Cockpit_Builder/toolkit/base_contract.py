"""Placement contract of a JH base: the base data the builder reads to place the Aces cockpits.

A pinned base file (sha256 in baseline_compatibility.json) passes at once. Any other version of it passes when its
placement data equals placement_contract.json, so a JH update that changes glass colours, guns, ammunition or
loadouts builds without a builder update. Placement data, per file kind (what build_native_overlay.py,
fix_native_glass.py and inspect_sbd_gunner_contract.py read):
  <slot>-C.mgm   Scene Root transform (re-host fit), world matrix and vertex centre of the sight target nodes
                 (slots.json sight_target_nodes; Aldis telescope nodes; Type98 donor mask/reticle), moving arg list
  planes/*.txt   [attach=0] / [attach=1] bot object and position, a GunsightPosition line (its value is replaced)
  Bots/*.txt     an [attach=0] position line (its value is replaced: eye minus the plane script attach position)
  <slot>-C.txt   a CloseSphere line (its value is replaced)
usage: base_contract.py make <base> [contract.json]   |   base_contract.py check <base>"""
import hashlib, json, re, sys
from pathlib import Path
import numpy as np
import mgm_bos as G

HERE = Path(__file__).resolve().parent
CONTRACT = HERE / 'placement_contract.json'
TOL = 1e-4          # metres / matrix units; the mgm stores float32


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _slots():
    from slots import DATA
    return DATA


def _watch_nodes(slot, data):
    names, prefixes = set(), []
    for c in data['cockpits']:
        if c['slot'].lower() == slot.lower():
            names.update(c.get('sight_target_nodes', []))
            if c['optic_kind'] == 'aldis_telescope':
                prefixes.append('JH24_Aldis_')
    if slot.lower() == data['type98_donor_slot'].lower():
        names.update(['WT_NATIVE_Type98_Mask', 'WT_NATIVE_Type98_Reticle'])
    return names, prefixes


def _round(a):
    return [round(float(x), 5) for x in np.ravel(a)]


def _mgm(p, slot, data):
    m = G.read(p.read_bytes())
    names, prefixes = _watch_nodes(slot, data)
    nodes = {}
    for n in m.nodes():
        if n.name in names or any(n.name.startswith(q) for q in prefixes):
            row = {'world_matrix': _round(G.world_matrix(n))}
            if n.nverts:
                v, _ = G.node_geometry(n)
                w = (np.c_[v['pos'], np.ones(len(v))] @ G.mat(n.offset) @ G.world_matrix(n))[:, :3]
                row['vertex_centre'] = _round(w.mean(0))
            nodes[n.name] = row
    return {'scene_root': _round(np.array(m.root.local, float)),
            'nodes': nodes,
            'moving_args': sorted({a for a, an in m.anims if any(t.kind // 100 in (1, 2) for t in an.tracks)})}


def _block(text, n):
    b = re.search(r'\[attach=%d\](.*?)\[end\]' % n, text, re.S | re.I)
    if not b:
        return None
    o = re.search(r'object\s*=\s*"([^"]+)"', b[1], re.I)
    q = re.search(r'position\s*=([^\r\n]+)', b[1], re.I)
    return {'object': o[1].lower() if o else None,
            'position': _round(np.fromstring(q[1], sep=',')) if q else None}


def fingerprint(base, rel, data=None):
    data = data or _slots()
    p = Path(base) / rel
    if not p.is_file():
        return None
    parts = rel.replace('\\', '/').split('/')
    low = [x.lower() for x in parts]
    if rel.lower().endswith('-c.mgm'):
        return _mgm(p, parts[-2], data)
    text = p.read_bytes().decode('latin1')
    if 'bots' in low:
        b = re.search(r'\[attach=0\](.*?)\[end\]', text, re.S | re.I)
        return {'attach0_position_line': bool(b and re.search(r'position\s*=', b[1], re.I))}
    if 'planes' in low and 'luascripts' in low:
        return {'attach0': _block(text, 0), 'attach1': _block(text, 1),
                'gunsight_position_line': bool(re.search(r'(?im)^\s*GunsightPosition\s*=', text))}
    if rel.lower().endswith('-c.txt'):
        return {'close_sphere_line': bool(re.search(r'(?i)CloseSphere\s*=', text))}
    return {'sha256': _sha(p)}


def differences(want, got, path=''):
    """field paths where got differs from want (numbers within TOL)"""
    if isinstance(want, dict) and isinstance(got, dict):
        out = []
        for k in sorted(set(want) | set(got)):
            if k not in got:
                out.append(f'{path}{k} missing')
            elif k not in want:
                out.append(f'{path}{k} new')
            else:
                out += differences(want[k], got[k], f'{path}{k}.')
        return out
    if isinstance(want, list) and isinstance(got, list) and want and all(isinstance(x, float) for x in want + got):
        if len(want) != len(got) or np.max(np.abs(np.subtract(want, got))) > TOL:
            return [f'{path[:-1]} {want} -> {got}']
        return []
    return [] if want == got else [f'{path[:-1]} {want} -> {got}']


def check(base, rel, pins, contract=None, data=None):
    """(True, note) when the file is pinned or its placement data matches the contract; (False, reason) if not"""
    p = Path(base) / rel
    if not p.is_file():
        return False, f'{rel}: missing from the base'
    if _sha(p) in pins:
        return True, None
    contract = contract if contract is not None else json.loads(CONTRACT.read_text(encoding='utf-8'))
    want = contract.get('files', {}).get(rel)
    if want is None:
        return False, f'{rel}: not a tested version and no placement contract row for it'
    diff = differences(want, fingerprint(base, rel, data))
    if diff:
        return False, f'{rel}: placement data differs from the tested base - ' + '; '.join(diff[:4])
    return True, f'{rel}: not a tested version; placement data identical, other changes (glass, guns, loadouts) kept'


def make(base, out=CONTRACT, rels=None):
    data = _slots()
    rels = rels or list(json.loads((HERE / 'baseline_compatibility.json').read_text()).keys())
    files = {r: f for r in rels if (f := fingerprint(base, r, data)) is not None}
    out.write_text(json.dumps({'_about': 'Placement data of the tested JH base (see base_contract.py). Made from: '
                               + Path(base).name, 'files': files}, indent=1) + '\n', encoding='utf-8', newline='\n')
    return files


if __name__ == '__main__':
    cmd, base = sys.argv[1], Path(sys.argv[2])
    if cmd == 'make':
        f = make(base, Path(sys.argv[3]) if len(sys.argv) > 3 else CONTRACT)
        print('contract rows', len(f))
    else:
        pins = json.loads((HERE / 'baseline_compatibility.json').read_text())
        bad = 0
        for rel, want in pins.items():
            if not (base / rel).is_file():
                continue
            ok, note = check(base, rel, want if isinstance(want, list) else [want])
            bad += not ok
            print(('PASS ' if ok else 'FAIL ') + (note or f'{rel}: pinned'))
        print('RESULT', 'FAIL' if bad else 'PASS')
        sys.exit(1 if bad else 0)
