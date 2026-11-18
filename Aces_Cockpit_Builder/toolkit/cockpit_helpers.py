import re
import numpy as np
import mgm_bos as G
ENG = {'rpm': [3103, 3102], 'manifold_pressure': [3109], 'fuel_pressure': [3122], 'oil_pressure': [3142], 'oil_temperature': [3152, 3154], 'head_temperature': [3112, 3172, 3174], 'water_temperature': [3172, 3174], 'exhaust_temperature': [3190, 3179], 'carb_temperature': [3139], 'throttle': [1100], 'prop_pitch': [1106], 'mixture': [1111, 1112, 1113], 'supercharger': [1110, 1108], 'radiator': [1180, 1181, 1182, 1184, 1188], 'radiator_lever': [1180, 1181, 1182, 1184, 1188], 'oil_radiator_lever': [1130], 'magneto': [1152]}

GLOBAL = {'speed': [8201], 'vario': [8232], 'altitude_hour': [8251], 'altitude_min': [8252], 'altitude_10k': [8253], 'compass': [8551, 8561], 'turn': [8002], 'bank': [8171], 'aviahorizon_roll': [8012], 'aviahorizon_pitch': [8011], 'clock_hour': [8511], 'clock_min': [8512], 'clock_sec': [8513], 'fuel': [2501], 'stick_elevator': [406], 'stick_ailerons': [407], 'pedals': [402], 'trimmer': [436, 434], 'aileron_trim': [435], 'gears': [423], 'flaps': [430], 'flaps_indicator': [431, 730], 'blister': [22001]}

REVERSED = {406, 407}

def safe(nm):
    """WT names may carry non-Latin-1 bytes (g4m1 'àtmosphere_pressure'): node names must encode as latin-1."""
    return re.sub('[^ -~]', '_', nm)

def arg_for(name, donor_args, engine_map):
    """WT object -> (native arg, reversed) or None."""
    base = re.sub('_\\d+$', '', name)
    m = re.match('^([a-z_]+?)(\\d*)$', base)
    if not m:
        return None
    stem, idx = (m.group(1), m.group(2))
    if stem in ENG:
        k = engine_map.get(int(idx) if idx else 0)
        cands = ENG[stem]
        if k is None and len(engine_map) == 1:
            k = 0
            cands = [1130, 1132] if stem.startswith('radiator') else ENG[stem][1:]
        if k is None:
            return None
        for a in cands:
            if a + 100 * k in donor_args:
                return (a + 100 * k, False)
        return None
    stem2 = re.sub('\\d+$', '', base)
    for key in (base, stem2, stem):
        if key in GLOBAL:
            for a in GLOBAL[key]:
                if a in donor_args:
                    return (a, a in REVERSED)
    if stem2.startswith('pedals') and 402 in donor_args:
        return (402, False)
    if stem2.startswith('blister') and 22001 in donor_args:
        return (22001, False)
    return None

def append_track(m, arg, node, kind, keys):
    k = np.array(keys, G.KEY_DTYPE)
    an = next((a for x, a in m.anims if x == arg), None)
    if an is None:
        an = G.Animation()
        m.anims.append((arg, an))
    an.tracks.append(G.Track(node=node.index, keys=k, kind=kind))
    an.tracks.sort(key=lambda t: t.node)
    node.z = 1

def rot_between(a, b):
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(a @ b)
    if np.linalg.norm(v) < 1e-09:
        return np.eye(3) if c > 0 else -np.eye(3)
    k = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return (np.eye(3) + k + k @ k * (1 / (1 + c))).T
