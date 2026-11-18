"""War Thunder (Dagor) DDS -> native IL-2 DDS, following the proven Zero recipes (plane-import skill:
materials-and-textures / dds-and-hangs; Codex Retooled Test 6 build_material_fix.py).

* Dagor exports declare 2 (or more) mips but carry only the top level + 12 stray bytes -> IL-2 hides an E_INVALIDARG
  D3DError modal and the render thread hangs (Zero TEST05B). Never ship them as-is.
* colour_bc3(): BC3 output. Every DXT1 4-colour-mode block / every DXT5 colour block of the ORIGINAL top level is
  copied byte-exact into the BC3 colour half (DXT1 3-colour blocks cannot be expressed in BC3 and take texconv's
  re-encode of the decoded pixels); alpha = the supplied spec/gloss map (linear data); lower mips generated from the
  decoded image (documented separate image operation, not container repair).
* normal_rgba32(): Dagor DXT5nm (X in A, Y in G, the V flip already folded into -Y) -> legacy RGBA32 tangent normal,
  full mip chain, vectors renormalised per mip; no spatial flip, no gain.
Validation per file: complete mip byte sizes, offscreen D3D11 upload (skill audit_dds.py --d3d) done by the caller.
"""
import struct, subprocess, tempfile
from pathlib import Path
import numpy as np
from PIL import Image

from runtime_paths import TOOLS
TEXCONV = TOOLS/'texconv.exe'
DDSD_MIPMAPCOUNT, DDPF_FOURCC = 0x20000, 0x4


def header(raw):
    h = struct.unpack_from("<31I", raw, 4)
    return dict(height=h[2], width=h[3], mips=max(1, h[6]), fourcc=raw[84:88], flags=h[1])


def top_blocks(raw):
    """(fourcc, top-level block array (n,8|16) uint8, w, h) of a DXT1/DXT5 file (stray tail ignored)."""
    hd = header(raw); fc = hd["fourcc"]; assert fc in (b"DXT1", b"DXT5"), fc
    bs = 8 if fc == b"DXT1" else 16
    w, h = hd["width"], hd["height"]; n = max(1, (w + 3) // 4) * max(1, (h + 3) // 4)
    assert len(raw) >= 128 + n * bs, "truncated top level"
    return fc, np.frombuffer(raw, np.uint8, count=n * bs, offset=128).reshape(n, bs).copy(), w, h


def decode(raw_or_path):
    p = raw_or_path
    if isinstance(p, (bytes, bytearray)):
        import io
        return np.asarray(Image.open(io.BytesIO(p)).convert("RGBA")).copy()
    return np.asarray(Image.open(p).convert("RGBA")).copy()


def texconv_bc3(rgba, tmp):
    png = Path(tmp) / "img.png"; Image.fromarray(rgba, "RGBA").save(png)
    r = subprocess.run([str(TEXCONV), "-f", "BC3_UNORM", "-m", "0", "-y", "-nologo", "-o", str(tmp), str(png)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    d = bytearray((Path(tmp) / "img.dds").read_bytes())
    struct.pack_into("<I", d, 24, 0)                  # depth 0 like native headers (texconv writes 1)
    return d


def colour_bc3(src_raw, alpha, out):
    """src DXT1/DXT5 (Dagor) + alpha (HxW uint8) -> BC3 with full mips at `out`. Returns stats."""
    fc, blocks, w, h = top_blocks(src_raw)
    rgba = decode(src_raw); assert rgba.shape[:2] == (h, w)
    rgba[..., 3] = alpha
    with tempfile.TemporaryDirectory() as tmp:
        d = texconv_bc3(rgba, tmp)
    n = blocks.shape[0]
    gen = np.frombuffer(d, np.uint8, count=n * 16, offset=128).reshape(n, 16).copy()
    if fc == b"DXT1":
        c0 = blocks[:, 0].astype(np.uint16) | (blocks[:, 1].astype(np.uint16) << 8)
        c1 = blocks[:, 2].astype(np.uint16) | (blocks[:, 3].astype(np.uint16) << 8)
        keep = c0 > c1                                   # 4-colour blocks mean the same in BC3's colour half
        gen[keep, 8:] = blocks[keep, :8]
    else:
        keep = np.ones(n, bool); gen[:, 8:] = blocks[:, 8:]
    d[128:128 + n * 16] = gen.tobytes()
    Path(out).write_bytes(bytes(d))
    back = decode(bytes(d))
    return dict(format="BC3", size=[w, h], source=fc.decode(), exact_colour_blocks=int(keep.sum()), blocks=int(n),
                top_rgb_max_abs_diff_vs_source=int(np.abs(back[..., :3].astype(int) - decode(src_raw)[..., :3].astype(int)).max()))


def unit(v):
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-12)


def decode_dxt5nm(src_raw):
    a = decode(src_raw).astype(np.float32)
    xy = a[..., [3, 1]] / 127.5 - 1.0
    xy[..., 1] *= -1.0                                   # V flip of the native UVs
    z = np.sqrt(np.maximum(0.0, 1.0 - (xy * xy).sum(-1)))
    return unit(np.dstack([xy, z])), a[..., 0] / 255.0   # vectors, R = relative gloss


def normal_rgba32(vec, out):
    import cv2
    levels, v = [], vec.astype(np.float32)
    while True:
        rgb = np.clip(np.rint((unit(v) + 1.0) * 127.5), 0, 255).astype(np.uint8)
        levels.append(np.dstack([rgb, np.full(rgb.shape[:2], 255, np.uint8)]))
        if v.shape[:2] == (1, 1):
            break
        v = unit(cv2.resize(v, (max(1, v.shape[1] // 2), max(1, v.shape[0] // 2)), interpolation=cv2.INTER_AREA))
    a = levels[0]
    hd = [0] * 31
    hd[:7] = [124, 0x100f | DDSD_MIPMAPCOUNT, a.shape[0], a.shape[1], a.shape[1] * 4, 0, len(levels)]
    hd[18:26] = [32, 0x41, 0, 32, 0xff, 0xff00, 0xff0000, 0xff000000]
    hd[26] = 0x401008
    Path(out).write_bytes(b"DDS " + struct.pack("<31I", *hd) + b"".join(x.tobytes() for x in levels))
    return dict(format="RGBA32", size=[a.shape[1], a.shape[0]], mips=len(levels))


def normal_bc3(vec, out):
    """large tangent normals as BC3 RGB (stock IL-2 _B maps are DXT5), alpha 255; mips via texconv (box filter, not
    renormalised - documented compromise for the 4096 cockpit atlases; RGBA32 would be ~89 MB each)."""
    rgb = np.clip(np.rint((unit(vec) + 1.0) * 127.5), 0, 255).astype(np.uint8)
    rgba = np.dstack([rgb, np.full(rgb.shape[:2], 255, np.uint8)])
    with tempfile.TemporaryDirectory() as tmp:
        d = texconv_bc3(rgba, tmp)
    Path(out).write_bytes(bytes(d))
    return dict(format="BC3 normal", size=[rgba.shape[1], rgba.shape[0]])


def zero_depth(path):
    """texconv writes depth=1 on 2D textures; native IL-2 headers use 0 (skill: dds-and-hangs). Plain 2D only."""
    b = bytearray(Path(path).read_bytes())
    flags, depth, caps2 = struct.unpack_from("<I", b, 8)[0], struct.unpack_from("<I", b, 24)[0], struct.unpack_from("<I", b, 112)[0]
    if depth and not (flags & 0x800000) and caps2 == 0:
        struct.pack_into("<I", b, 24, 0); Path(path).write_bytes(bytes(b)); return True
    return False
