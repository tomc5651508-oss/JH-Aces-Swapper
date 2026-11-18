import numpy as np
import json,types
from pathlib import Path
import mgm_bos as G
EXT=Path()
def unit(v):
    return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)

def uv_tangents(v, indices):
    """Per-vertex UV tangent/bitangent, orthogonalised to the normal (Codex's A6M5 recipe)."""
    p = v['pos'].astype(float)
    uv = v['uv'].astype(float)
    n = unit(v['nrm'].astype(float))
    idx = indices.reshape(-1, 3)
    dp1, dp2 = (p[idx[:, 1]] - p[idx[:, 0]], p[idx[:, 2]] - p[idx[:, 0]])
    du1, du2 = (uv[idx[:, 1]] - uv[idx[:, 0]], uv[idx[:, 2]] - uv[idx[:, 0]])
    det = du1[:, 0] * du2[:, 1] - du1[:, 1] * du2[:, 0]
    ok = abs(det) > 1e-10
    ft = (dp1[ok] * du2[ok, 1, None] - dp2[ok] * du1[ok, 1, None]) / det[ok, None]
    fb = (dp2[ok] * du1[ok, 0, None] - dp1[ok] * du2[ok, 0, None]) / det[ok, None]
    t = np.zeros_like(p)
    b = np.zeros_like(p)
    for k in range(3):
        np.add.at(t, idx[ok, k], unit(ft))
        np.add.at(b, idx[ok, k], unit(fb))
    t -= n * (n * t).sum(1, keepdims=True)
    bad = np.linalg.norm(t, axis=1) < 1e-08
    ref = np.where(abs(n[:, 2:3]) < 0.9, [[0.0, 0.0, 1.0]], [[1.0, 0.0, 0.0]])
    t[bad] = np.cross(n[bad], ref[bad])
    t = unit(t)
    sign = np.where((np.cross(n, t) * b).sum(1, keepdims=True) < 0, -1.0, 1.0)
    b = unit(np.cross(n, t)) * sign
    return (t, b)

def pack(v):
    a = np.zeros((len(v), 4), np.uint8)
    a[:, :3] = np.clip(np.rint(v[:, [2, 1, 0]] * 127.5 + 127.5), 0, 255)
    return a
def _qmat(q):
    x, y, z, w = q
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])

A=types.SimpleNamespace(_qmat=_qmat)
def qmat_to_quat(M):
    """quaternion (x, y, z, w) with convert_a6m5._qmat(q) == M (asserted)."""
    best = None
    for sign in (1.0, -1.0):
        t = np.trace(M)
        if t > 0:
            s = np.sqrt(t + 1.0) * 2
            w = 0.25 * s
            x = (M[2, 1] - M[1, 2]) / s
            y = (M[0, 2] - M[2, 0]) / s
            z = (M[1, 0] - M[0, 1]) / s
        elif M[0, 0] > M[1, 1] and M[0, 0] > M[2, 2]:
            s = np.sqrt(1.0 + M[0, 0] - M[1, 1] - M[2, 2]) * 2
            w = (M[2, 1] - M[1, 2]) / s
            x = 0.25 * s
            y = (M[0, 1] + M[1, 0]) / s
            z = (M[0, 2] + M[2, 0]) / s
        elif M[1, 1] > M[2, 2]:
            s = np.sqrt(1.0 + M[1, 1] - M[0, 0] - M[2, 2]) * 2
            w = (M[0, 2] - M[2, 0]) / s
            x = (M[0, 1] + M[1, 0]) / s
            y = 0.25 * s
            z = (M[1, 2] + M[2, 1]) / s
        else:
            s = np.sqrt(1.0 + M[2, 2] - M[0, 0] - M[1, 1]) * 2
            w = (M[1, 0] - M[0, 1]) / s
            x = (M[0, 2] + M[2, 0]) / s
            y = (M[1, 2] + M[2, 1]) / s
            z = 0.25 * s
        q = np.array([sign * x, sign * y, sign * z, w])
        q /= np.linalg.norm(q)
        if np.allclose(A._qmat(q), M, atol=0.0001):
            return q
        best = q
    raise AssertionError('quaternion convention mismatch')

class Clip:
    """WT exterior clip (decode_wt_a2d): absolute local transform of each animated node per sample."""

    def __init__(self, ext=EXT, model='ki_43_1'):
        d = ext / 'raw_resources'
        meta = json.loads((d / f'{model}_anim.animation.json').read_text())
        self.V = np.load(d / f'{model}_anim.animation.npz')['values']
        self.track = {e['name']: e['track'] for c in meta['channels'] for e in c['entries']}

    def moving(self, name):
        if name not in self.track:
            return False
        v = self.V[:, self.track[name]]
        dq = np.abs(np.abs((v[:, :4] * v[0, :4]).sum(1)) - 1).max()
        dp = np.abs(v[:, 4:7] - v[0, 4:7]).max()
        return dq > 1e-05 or dp > 0.0001

    def local(self, name, phase):
        v = self.V[int(round(phase * (len(self.V) - 1))), self.track[name]]
        x, y, z, w = v[:4]
        M = np.eye(4)
        M[:3, :3] = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
        M[:3, :3] = M[:3, :3] @ np.diag(v[7:10])
        M[:3, 3] = v[4:7]
        return M
def reindex(m):
    old = {n.index: n for n in m.nodes()}
    order, stack = ([], [m.root])
    while stack:
        x = stack.pop()
        order.append(x)
        stack.extend(reversed(x.children))
    for i, x in enumerate(order):
        x.index = i
    for _, an in m.anims:
        for t in an.tracks:
            t.node = old[t.node].index
            if t.pair_node is not None:
                t.pair_node = old[t.pair_node].index
    for c in m.chunks:
        c.bone_map = [(b.index, i) for i, b in enumerate(c.bones)]
