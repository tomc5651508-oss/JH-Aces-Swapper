r"""Merge the chunks of a BoS .mgm per material, the way stock exterior models are built (2026-10-13).

Why: the converted 1946 planes keep one chunk per 1946 part (Zero exterior 51 live chunks, 40 of them BumpChrome; Betty
83 BumpChrome) while stock models have <= 35 chunks and <= 7 BumpChrome. The shader pass (Specular -> BumpChrome) made
the game die at boot (Tom's bisect 2026-10-12/13: pre-shader Zero boots, shader Zero alone does not). Stock layout
(fw190a3.mgm chunk 1: one BumpChrome chunk, 64 bones): every node on a chunk owns a contiguous vertex range (vbyte /
nverts) and index range (ibyte / nindices); its vertices carry slot = node.slot = its position in chunk.bones;
indices are chunk-absolute; bone_map = [(node.index, slot)].
merge(): chunks with identical (shader, stride, u8, textures, colors) are concatenated in file order; each node's
vertex/index ranges are copied, vertex slots rewritten, indices rebased; nodes get the new chunk/slot/vbyte/ibyte.
Geometry per node (pos/nrm/uv/tangents and triangle corner positions) is asserted unchanged after a write + read-back.
usage: python -P -E merge_mgm_chunks.py <in.mgm|dir> <out dir>      (dir: every *.mgm except cockpits *-C.mgm)
"""
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mgm_bos as G

MAX_BONES = 64                      # max bones per chunk in every stock model surveyed (bos_ref + bos_data)


def _isz(c):
    return c.indices.dtype.itemsize


def node_mesh(n):
    c = n.chunk
    v0 = n.vbyte // c.stride
    s = n.ibyte // _isz(c)
    return c.vertices[v0:v0 + n.nverts], c.indices[s:s + n.nindices].astype(np.int64) - v0


def merge(m):
    live = [c for c in m.chunks if c.vertices is not None and len(c.vertices)]
    groups = {}
    for c in live:
        key = (c.shader, c.stride, c.u8, tuple(c.textures), bytes(c.colors))
        groups.setdefault(key, []).append(c)
    by_chunk = {}
    for n in m.nodes():
        if n.chunk is not None and n.chunk.vertices is not None and len(n.chunk.vertices):
            by_chunk.setdefault(id(n.chunk), []).append(n)
    new_chunks = []                         # empty (helper/hook) chunks first, split at 64 bones like stock
    for c in m.chunks:                      # (bf110e2.mgm helpers = 64 + 30; Ki-45/Betty had 115/106 in one chunk)
        if c.vertices is not None and len(c.vertices): continue
        bones = list(c.bones)
        for k in range(0, max(len(bones), 1), MAX_BONES):
            nc = c if k == 0 else G.Chunk(shader=c.shader, colors=c.colors, textures=list(c.textures), u8=c.u8,
                                          stride=c.stride, vertices=c.vertices, indices=c.indices)
            nc.bones = bones[k:k + MAX_BONES]; nc.bone_map = [(b.index, s) for s, b in enumerate(nc.bones)]
            for s, b in enumerate(nc.bones): b.chunk, b.slot = nc, s
            new_chunks.append(nc)
    for key, cs in groups.items():
        nodes = []
        for c in cs:
            ns = sorted(by_chunk.get(id(c), []), key=lambda n: n.vbyte)
            covered = sum(n.nverts for n in ns)
            assert covered == len(c.vertices), (key[0], key[3][:1], covered, len(c.vertices))   # every vertex owned
            nodes += ns
        for part in range(0, len(nodes), MAX_BONES):                # stock never exceeds 64 bones per chunk
            new_chunks.append(_build(cs, nodes[part:part + MAX_BONES]))
    before = len(m.chunks)
    m.chunks = new_chunks
    return before, len(m.chunks)


def _build(cs, nodes):
    if True:
        total_v = sum(n.nverts for n in nodes)
        verts = np.zeros(total_v, cs[0].vertices.dtype)
        idx_parts, vb, bones, bone_map = [], 0, [], []
        ib = 0
        for slot, n in enumerate(nodes):
            v, tri = node_mesh(n)
            v = v.copy(); v["slot"] = slot
            verts[vb:vb + len(v)] = v
            idx_parts.append(tri + vb)
            n.vbyte = vb * cs[0].stride
            n.ibyte = ib
            n.slot = slot
            bones.append(n); bone_map.append((n.index, slot))
            vb += len(v); ib += len(tri)
        allidx = np.concatenate(idx_parts) if idx_parts else np.zeros(0, np.int64)
        dt = G.index_dtype(total_v)
        assert allidx.max(initial=0) <= np.iinfo(dt).max
        c = cs[0]
        merged = G.Chunk(shader=c.shader, colors=c.colors, textures=list(c.textures), u8=c.u8, stride=c.stride,
                         bones=bones, bone_map=bone_map, extra=[x for cc in cs for x in cc.extra],
                         vertices=verts, indices=allidx.astype(dt))
        for n in nodes:
            n.ibyte *= merged.indices.dtype.itemsize
            n.chunk = merged
        return merged


def corners(m):
    """{node index: (vertex record bytes without slot, triangle corner positions)} for comparison."""
    out = {}
    for n in m.nodes():
        if n.chunk is None or n.chunk.vertices is None or not len(n.chunk.vertices) or not n.nverts: continue
        v, tri = node_mesh(n)
        fields = [f for f in v.dtype.names if f != "slot"]
        out[n.index] = (b"".join(np.ascontiguousarray(v[f]).tobytes() for f in fields), v["pos"][tri].tobytes())
    return out


def process(src, dst):
    m = G.read(src)
    ref = corners(m)
    b, a = merge(m)
    dst.parent.mkdir(parents=True, exist_ok=True)
    G.write(m, dst)
    back = G.read(dst)
    got = corners(back)
    assert got.keys() == ref.keys() and all(got[k] == ref[k] for k in ref), f"geometry changed in {src}"
    for c in back.chunks:                                          # stock invariants
        assert len(c.bones) <= MAX_BONES and [s for _, s in c.bone_map] == list(range(len(c.bones))), "bones/chunk"
        assert all(b.chunk is c and b.slot == s for s, b in enumerate(c.bones)), "node chunk/slot"
        if c.vertices is None or not len(c.vertices): continue
        assert [s for _, s in c.bone_map] == list(range(len(c.bones))) and len(c.bones) <= MAX_BONES
        for n in back.nodes():
            if n.chunk is c and n.nverts:
                v0 = n.vbyte // c.stride
                assert np.all(c.vertices["slot"][v0:v0 + n.nverts] == n.slot)
    bc = sum(c.shader == "BumpChrome" for c in back.chunks)
    print(f"{src.name}: chunks {b} -> {a} (BumpChrome {bc})")


def main():
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    files = [src] if src.is_file() else [p for p in sorted(src.rglob("*.mgm")) if not p.stem.lower().endswith("-c")]
    for p in files:
        process(p, out / (p.name if src.is_file() else p.relative_to(src)))


if __name__ == "__main__":
    main()
