import numpy as np
import cv2,json
from pathlib import Path
from types import SimpleNamespace
from PIL import Image
import resource_budget
def dds_info(raw):
 h,mips=resource_budget.levels(raw)
 return {'fmt':raw[84:88].decode('latin1'),'complete':True,'w':h[3],'h':h[2],'mips':h[6]}
C=SimpleNamespace(dds_info=dds_info)
def coverage(models, tex_stem, size, slot_filter=None):
    """UV raster (row = v*size) of every chunk whose diffuse is tex_stem."""
    m = np.zeros((size[1], size[0]), np.uint8)
    for mdl in models:
        for c in mdl.chunks:
            if not c.textures or Path(c.textures[0]).stem.lower() != tex_stem or c.vertices is None or (len(c.indices) < 3):
                continue
            uv = c.vertices['uv'].astype(np.float64)
            tri = c.indices.astype(np.int64).reshape(-1, 3)
            tri = tri[np.isfinite(uv[tri]).all((1, 2)) & (np.abs(uv[tri]) < 64).all((1, 2))]
            if not len(tri):
                continue
            p = np.round(uv[tri] * np.array(size) - 0.5).astype(np.int32)
            p = np.mod(p, np.array(size))
            cv2.fillPoly(m, list(p), 255)
    if m.mean() < 0.5:
        m[:] = 255
    return m > 0

def rank_map(S, cov, target_q):
    """histogram matching with mid-ranks for ties: S (0..255 float) over the coverage -> target quantile curve."""
    k = np.clip(np.rint(S * 4), 0, 1020).astype(np.int32)
    h = np.bincount(k[cov], minlength=1021).astype(np.float64)
    cum = np.cumsum(h)
    u = (cum - h / 2) / max(cum[-1], 1)
    lut = np.interp(u, np.linspace(0, 1, 101), target_q)
    out = lut[k]
    out[~cov] = float(target_q[50])
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)

def bc4_blocks(a):
    """HxW uint8 (multiple of 4) -> (nblocks, 8) DXT5 alpha blocks, 8-value mode."""
    h, w = a.shape
    b = a.reshape(h // 4, 4, w // 4, 4).transpose(0, 2, 1, 3).reshape(-1, 16).astype(np.int32)
    a0, a1 = (b.max(1), b.min(1))
    pal = np.empty((len(b), 8), np.int32)
    pal[:, 0], pal[:, 1] = (a0, a1)
    for i in range(2, 8):
        pal[:, i] = ((8 - i) * a0 + (i - 1) * a1 + 3) // 7
    idx = np.abs(b[:, :, None] - pal[:, None, :]).argmin(2).astype(np.uint64)
    idx[a0 == a1] = 0
    bits = np.zeros(len(b), np.uint64)
    for j in range(16):
        bits |= idx[:, j] << np.uint64(3 * j)
    out = np.zeros((len(b), 8), np.uint8)
    out[:, 0], out[:, 1] = (a0, a1)
    for k in range(6):
        out[:, 2 + k] = (bits >> np.uint64(8 * k) & np.uint64(255)).astype(np.uint8)
    return out

def replace_alpha_dxt5(raw, alpha):
    """keep every colour half of a DXT5 file, rewrite the alpha halves of all mips from `alpha` (top level size)."""
    info = C.dds_info(raw)
    assert info['fmt'] == 'DXT5' and info['complete'], info
    w, h, mips = (info['w'], info['h'], info['mips'])
    d = bytearray(raw)
    off = 128
    lvl = alpha.astype(np.float32)
    for i in range(mips):
        lw, lh = (max(1, w >> i), max(1, h >> i))
        if lvl.shape != (lh, lw):
            lvl = cv2.resize(lvl, (lw, lh), interpolation=cv2.INTER_AREA)
        bw, bh = ((lw + 3) // 4, (lh + 3) // 4)
        pad = np.pad(np.clip(np.rint(lvl), 0, 255).astype(np.uint8), ((0, bh * 4 - lh), (0, bw * 4 - lw)), mode='edge')
        blk = np.frombuffer(bytes(d[off:off + bw * bh * 16]), np.uint8).reshape(-1, 16).copy()
        blk[:, :8] = bc4_blocks(pad)
        d[off:off + bw * bh * 16] = blk.tobytes()
        off += bw * bh * 16
    return bytes(d)
