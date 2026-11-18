"""mgm_bos.py - reader/writer for IL-2 Great Battles (Battle of Stalingrad) `.mgm` 3D models.

Format reverse-engineered from the shipped files (no engine code); spec in docs/mgm_format.md.

    model = read(path)          -> Model (object tree + decoded vertex/index buffers)
    write(model, path)          -> serialises it back (offsets recomputed)
    export_obj(model, path)     -> Wavefront OBJ of all geometry in world space

CLI (run with `python -P -E mgm_bos.py ...`):
    dump <file> [--verbose]     readable tree
    roundtrip <file>...         read -> write (in memory) -> byte compare
    obj <file> <out.obj>        export geometry + numeric sanity check
    demo <out.mgm> [out.obj]    build a toy aircraft with the builder API, write, re-read, round-trip

The file is a boost-style object serialisation:
    every object reference = str classname, u32 version(=0), str object-id (decimal, global counter)
    first occurrence of an id -> the object's fields follow inline; later occurrences -> nothing follows
    null reference = three empty fields (12 zero bytes)
followed by an opaque gap, all vertex buffers, and all index buffers (u16; u32 for chunks > 65535 verts).
"""
from __future__ import annotations

import struct
import sys
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

CLS_MODEL = 'class model::Model'
CLS_NODE = 'struct model::Node'
CLS_CHUNK = 'struct model::Chunk'
CLS_ANIM = 'struct model::Animation'

# ----------------------------------------------------------------------------------------------
# vertex layouts (selected by stride, and for stride 48 by shader)
# ----------------------------------------------------------------------------------------------
_BASE = [('pos', '<f4', 3), ('nrm', '<f4', 3), ('uv', '<f4', 2), ('slot', '<f4')]
VERTEX_LAYOUTS = {
    36: _BASE,
    40: _BASE + [('pk0', 'u1', 4)],
    44: _BASE + [('pk0', 'u1', 4), ('pk1', 'u1', 4)],
    60: _BASE + [('pos2', '<f4', 3), ('nrm2', '<f4', 3)],
    68: _BASE + [('pk0', 'u1', 4), ('pos2', '<f4', 3), ('nrm2', '<f4', 3), ('pk0_2', 'u1', 4)],
    76: _BASE + [('pk0', 'u1', 4), ('pk1', 'u1', 4), ('pos2', '<f4', 3), ('nrm2', '<f4', 3),
                 ('pk0_2', 'u1', 4), ('pk1_2', 'u1', 4)],
    116: [('pos', '<f4', (3, 3)), ('nrm', '<f4', (3, 3)), ('pk0', 'u1', 4), ('uv', '<f4', 2),
          ('slotw', '<f4', (3, 2)), ('pad', '<u4', 2)],
}
_LAYOUT48_DECAL = [('pos', '<f4', 3), ('nrm', '<f4', 3), ('uv', '<f4', 2), ('uv2', '<f4', 2),
                   ('slot', '<f4'), ('extra', '<u4')]
_LAYOUT48_OTHER = _BASE + [('extra', '<f4', 3)]


def index_dtype(nverts: int) -> np.dtype:
    """u16 indices, u32 once the chunk has more than 65535 vertices (seen in me410a1-c.mgm)."""
    return np.dtype('<u4') if nverts > 0xffff else np.dtype('<u2')


def vertex_dtype(stride: int, shader: str = '') -> np.dtype:
    if stride == 48:
        lay = _LAYOUT48_DECAL if shader == 'Decal' else _LAYOUT48_OTHER
    else:
        lay = VERTEX_LAYOUTS.get(stride)
    if lay is None:  # unknown layout: keep raw bytes (still lossless)
        return np.dtype([('raw', 'u1', stride)])
    dt = np.dtype(lay)
    assert dt.itemsize == stride, (stride, dt.itemsize)
    return dt


# Animation key: 36-byte packed struct
KEY_DTYPE = np.dtype([('t', '<f4'),          # argument value 0..1 at which this key applies
                      ('u4', '<u2'),         # unknown, 0 (69 keys of 20778 have 32760)
                      ('visible', 'u1'),     # 1 shown / 0 hidden
                      ('pad7', 'u1'),        # struct padding (junk)
                      ('pos', '<f4', 3),     # translation (position tracks)
                      ('rot', '<i2', 4),     # quaternion x,y,z,w scaled by QUAT_SCALE
                      ('scale', '<u2', 3),   # scale x,y,z * 1000
                      ('pad34', '<u2')])     # struct padding (junk)
assert KEY_DTYPE.itemsize == 36
QUAT_SCALE = 32760.0
TRACK_VIS, TRACK_POS, TRACK_ROT = 0, 100, 200


# ----------------------------------------------------------------------------------------------
# object model
# ----------------------------------------------------------------------------------------------
@dataclass(eq=False)
class Node:
    index: int = 0                         # position in the flat node table (0 = Scene Root)
    name: str = ''
    bbox: tuple = (0.0,) * 6               # max xyz, min xyz (model space, approx AABB)
    parent: Optional['Node'] = None
    flags: int = 0                         # 0 / 1 / 0x80000001
    local: tuple = tuple(np.eye(4).ravel())    # 4x4 row-major, row-vector convention, T in row 3
    u1: int = 0                            # 0/1
    offset: tuple = tuple(np.eye(4).ravel())   # 4x4 mesh offset: vertex -> node local
    aux: tuple = (0,) * 8                  # 8 x u32: [0],[1] arg-ish pair, [2] arg, [3] arg, [4] ?, [5..7]=0
    nverts: int = 0                        # vertices of this node inside its chunk
    nindices: int = 0                      # indices of this node inside its chunk
    vbyte: int = 0                         # byte offset of first vertex inside chunk vertex buffer
    ibyte: int = 0                         # byte offset of first index inside chunk index buffer
    stride: int = 36                       # == chunk.stride
    shader: str = 'Specular'               # == chunk.shader
    children: list = field(default_factory=list)
    z: int = 0                             # u16 0/1/257
    w: int = 0                             # i32
    chunk: Optional['Chunk'] = None
    slot: int = 0                          # this node's slot in chunk.bones (vertex 'slot' value)

    def __repr__(self):
        return 'Node(%d %r)' % (self.index, self.name)


@dataclass(eq=False)
class Chunk:
    shader: str = 'Specular'
    colors: bytes = bytes(16)              # 4 x RGBA u8 (see spec)
    textures: list = field(default_factory=list)
    voff: int = 0                          # absolute file offset of vertices (recomputed on write)
    ioff: int = 0                          # absolute file offset of indices (recomputed on write)
    u8: int = 0
    stride: int = 36
    bones: list = field(default_factory=list)       # Node refs, slot order
    bone_map: list = field(default_factory=list)    # (node index, slot) pairs
    extra: list = field(default_factory=list)       # Node refs (skin helpers; usually empty)
    vertices: Optional[np.ndarray] = None
    indices: Optional[np.ndarray] = None
    nverts_hdr: int = 0                    # counts as stored (kept for diagnostics)
    nindices_hdr: int = 0

    def __repr__(self):
        return 'Chunk(%s %d v %d i)' % (self.shader, len(self.vertices), len(self.indices))


@dataclass(eq=False)
class Track:
    node: int = 0                          # node index
    hdr_hi: int = 0x0100                   # high u16 of the track header (always 0x0100)
    keys: Optional[np.ndarray] = None      # KEY_DTYPE array
    kind: int = TRACK_ROT                  # 0..99 vis, 100..199 pos, 200..299 rot (+layer)
    pair_node: Optional[int] = None        # node index in the trailing table if it differs


@dataclass(eq=False)
class Animation:
    tracks: list = field(default_factory=list)


@dataclass(eq=False)
class Model:
    root: Optional[Node] = None
    anims: list = field(default_factory=list)      # [(arg, Animation)]
    chunks: list = field(default_factory=list)     # buffer order
    gap: bytes = b''                               # opaque bytes between tree and vertex data

    def nodes(self):
        out, seen, stack = [], set(), [self.root]
        while stack:
            n = stack.pop()
            if n is None or id(n) in seen:
                continue
            seen.add(id(n)); out.append(n)
            stack.extend(reversed(n.children))
        for c in self.chunks:
            for n in c.bones + c.extra:
                if id(n) not in seen:
                    seen.add(id(n)); out.append(n)
        return sorted(out, key=lambda n: n.index)


# ----------------------------------------------------------------------------------------------
# reader
# ----------------------------------------------------------------------------------------------
class FormatError(Exception):
    pass


class _Reader:
    def __init__(self, data: bytes):
        self.d = data; self.p = 0; self.objs = {}; self.chunks_raw = []

    def u32(self):
        v = struct.unpack_from('<I', self.d, self.p)[0]; self.p += 4; return v

    def i32(self):
        v = struct.unpack_from('<i', self.d, self.p)[0]; self.p += 4; return v

    def u16(self):
        v = struct.unpack_from('<H', self.d, self.p)[0]; self.p += 2; return v

    def u8(self):
        v = self.d[self.p]; self.p += 1; return v

    def f32(self, n):
        v = struct.unpack_from('<%df' % n, self.d, self.p); self.p += 4 * n; return v

    def u32s(self, n):
        v = struct.unpack_from('<%dI' % n, self.d, self.p); self.p += 4 * n; return v

    def raw(self, n):
        v = self.d[self.p:self.p + n]
        if len(v) != n:
            raise FormatError('truncated at %#x' % self.p)
        self.p += n; return v

    def str(self):
        n = self.u32()
        if n > 1 << 16:
            raise FormatError('implausible string length %d at %#x' % (n, self.p - 4))
        return self.raw(n).decode('latin-1')

    def ref(self, want=None):
        at = self.p
        cls = self.str(); ver = self.u32(); oid = self.str()
        if cls == '' and oid == '':
            if ver != 0:
                raise FormatError('odd null ref at %#x' % at)
            return None
        if ver != 0:
            raise FormatError('class version %d at %#x (only 0 seen)' % (ver, at))
        if want and cls != want:
            raise FormatError('expected %s got %s at %#x' % (want, cls, at))
        if oid in self.objs:
            return self.objs[oid]
        if oid != str(len(self.objs)):
            raise FormatError('non-sequential object id %s at %#x' % (oid, at))
        reader = {CLS_MODEL: self.model, CLS_NODE: self.node, CLS_CHUNK: self.chunk,
                  CLS_ANIM: self.anim}.get(cls)
        if reader is None:
            raise FormatError('unknown class %r at %#x' % (cls, at))
        obj = {CLS_MODEL: Model, CLS_NODE: Node, CLS_CHUNK: Chunk, CLS_ANIM: Animation}[cls]()
        self.objs[oid] = obj
        reader(obj)
        return obj

    def model(self, m: Model):
        m.root = self.ref(CLS_NODE)
        n = self.u32()
        m.anims = [(self.u32(), self.ref(CLS_ANIM)) for _ in range(n)]
        n = self.u32()
        m.chunks = [self.ref(CLS_CHUNK) for _ in range(n)]

    def node(self, o: Node):
        o.index = self.u32(); o.name = self.str()
        o.bbox = self.f32(6)
        o.parent = self.ref(CLS_NODE)
        o.flags = self.u32()
        o.local = self.f32(16)
        o.u1 = self.u32()
        o.offset = self.f32(16)
        a = self.u32s(10)
        o.aux = a[:8]; o.nverts, o.nindices = a[8], a[9]
        o.vbyte = self.u32(); o.ibyte = self.u32()
        o.stride = self.u32()
        o.shader = self.str()
        n = self.u32()
        o.children = [self.ref(CLS_NODE) for _ in range(n)]
        o.z = self.u16(); o.w = self.i32()
        o.chunk = self.ref(CLS_CHUNK)
        o.slot = self.u32()

    def chunk(self, c: Chunk):
        c.shader = self.str(); c.colors = self.raw(16)
        n = self.u32(); c.textures = [self.str() for _ in range(n)]
        c.nverts_hdr = self.u32(); c.nindices_hdr = self.u32()
        c.voff = self.u32(); c.ioff = self.u32()
        c.u8 = self.u8(); c.stride = self.u32()
        n = self.u32(); c.bones = [self.ref(CLS_NODE) for _ in range(n)]
        n = self.u32(); c.bone_map = [tuple(self.u32s(2)) for _ in range(n)]
        n = self.u32(); c.extra = [self.ref(CLS_NODE) for _ in range(n)]

    def anim(self, a: Animation):
        n = self.u32()
        for _ in range(n):
            hdr = self.u32(); nb = self.u32()
            if nb % 36:
                raise FormatError('key block %d not a multiple of 36 at %#x' % (nb, self.p))
            keys = np.frombuffer(self.raw(nb), KEY_DTYPE).copy()
            a.tracks.append(Track(node=hdr & 0xffff, hdr_hi=hdr >> 16, keys=keys))
        n2 = self.u32()
        if n2 != n:
            raise FormatError('track table size %d != %d at %#x' % (n2, n, self.p))
        for t in a.tracks:
            nd, kind = self.u32s(2)
            t.kind = kind
            if nd != t.node:
                t.pair_node = nd


def read(path_or_bytes) -> Model:
    data = path_or_bytes if isinstance(path_or_bytes, (bytes, bytearray)) else open(path_or_bytes, 'rb').read()
    r = _Reader(bytes(data))
    m = r.ref(CLS_MODEL)
    if not isinstance(m, Model):
        raise FormatError('file does not start with a Model')
    tree_end = r.p
    # buffers: vertices of all chunks (list order) then indices of all chunks
    cs = m.chunks
    if len(set(map(id, cs))) != len(cs):
        raise FormatError('chunk listed twice')
    vstart = cs[0].voff if cs else len(data)
    if vstart < tree_end:
        raise FormatError('vertex data overlaps tree')
    m.gap = bytes(data[tree_end:vstart])
    pos = vstart
    for c in cs:
        if c.voff != pos:
            raise FormatError('vertex buffers not contiguous at chunk %r' % c.shader)
        dt = vertex_dtype(c.stride, c.shader)
        c.vertices = np.frombuffer(data, dt, c.nverts_hdr, c.voff).copy()
        pos += c.nverts_hdr * c.stride
    for c in cs:
        if c.ioff != pos:
            raise FormatError('index buffers not contiguous at chunk %r' % c.shader)
        it = index_dtype(c.nverts_hdr)
        c.indices = np.frombuffer(data, it, c.nindices_hdr, c.ioff).copy()
        pos += c.nindices_hdr * it.itemsize
    if pos != len(data):
        raise FormatError('%d trailing bytes after index data' % (len(data) - pos))
    m._tree_end = tree_end
    return m


# ----------------------------------------------------------------------------------------------
# writer
# ----------------------------------------------------------------------------------------------
class _Writer:
    def __init__(self):
        self.b = bytearray(); self.ids = {}; self.patches = []   # (pos, chunk, which)

    def u32(self, v): self.b += struct.pack('<I', v & 0xffffffff)
    def i32(self, v): self.b += struct.pack('<i', v)
    def u16(self, v): self.b += struct.pack('<H', v)
    def u8(self, v): self.b.append(v)
    def f32(self, vals): self.b += struct.pack('<%df' % len(vals), *vals)

    def str(self, s):
        e = s.encode('latin-1'); self.u32(len(e)); self.b += e

    def ref(self, obj):
        if obj is None:
            self.str(''); self.u32(0); self.str(''); return
        cls = {Model: CLS_MODEL, Node: CLS_NODE, Chunk: CLS_CHUNK, Animation: CLS_ANIM}[type(obj)]
        k = id(obj)
        if k in self.ids:
            self.str(cls); self.u32(0); self.str(self.ids[k]); return
        oid = str(len(self.ids)); self.ids[k] = oid
        self.str(cls); self.u32(0); self.str(oid)
        getattr(self, type(obj).__name__.lower())(obj)

    def model(self, m):
        self.ref(m.root)
        self.u32(len(m.anims))
        for arg, a in m.anims:
            self.u32(arg); self.ref(a)
        self.u32(len(m.chunks))
        for c in m.chunks:
            self.ref(c)

    def node(self, o):
        self.u32(o.index); self.str(o.name); self.f32(o.bbox)
        self.ref(o.parent)
        self.u32(o.flags); self.f32(o.local); self.u32(o.u1); self.f32(o.offset)
        for v in tuple(o.aux) + (o.nverts, o.nindices, o.vbyte, o.ibyte, o.stride):
            self.u32(v)
        self.str(o.shader)
        self.u32(len(o.children))
        for ch in o.children:
            self.ref(ch)
        self.u16(o.z); self.i32(o.w)
        self.ref(o.chunk)
        self.u32(o.slot)

    def chunk(self, c):
        self.str(c.shader)
        assert len(c.colors) == 16
        self.b += c.colors
        self.u32(len(c.textures))
        for t in c.textures:
            self.str(t)
        self.u32(len(c.vertices)); self.u32(len(c.indices))
        self.patches.append((len(self.b), c)); self.u32(0); self.u32(0)
        self.u8(c.u8); self.u32(c.stride)
        self.u32(len(c.bones))
        for n in c.bones:
            self.ref(n)
        self.u32(len(c.bone_map))
        for a, b in c.bone_map:
            self.u32(a); self.u32(b)
        self.u32(len(c.extra))
        for n in c.extra:
            self.ref(n)

    def animation(self, a):
        self.u32(len(a.tracks))
        for t in a.tracks:
            keys = np.ascontiguousarray(t.keys, KEY_DTYPE)
            self.u32((t.hdr_hi << 16) | (t.node & 0xffff)); self.u32(keys.nbytes)
            self.b += keys.tobytes()
        self.u32(len(a.tracks))
        for t in a.tracks:
            self.u32(t.node if t.pair_node is None else t.pair_node); self.u32(t.kind)


def to_bytes(m: Model, gap: Optional[bytes] = None) -> bytes:
    w = _Writer()
    w.ref(m)
    if gap is None:
        gap = m.gap
    pos = len(w.b) + len(gap)
    for c in m.chunks:
        c.voff = pos; pos += len(c.vertices) * c.stride
        if c.vertices.dtype.itemsize != c.stride:
            raise ValueError('vertex dtype size %d != stride %d' % (c.vertices.dtype.itemsize, c.stride))
    for c in m.chunks:
        c.ioff = pos; pos += len(c.indices) * index_dtype(len(c.vertices)).itemsize
    for at, c in w.patches:
        struct.pack_into('<II', w.b, at, c.voff, c.ioff)
    out = bytearray(w.b); out += gap
    for c in m.chunks:
        out += np.ascontiguousarray(c.vertices).tobytes()
    for c in m.chunks:
        out += np.ascontiguousarray(c.indices, index_dtype(len(c.vertices))).tobytes()
    assert len(out) == pos
    return bytes(out)


def write(m: Model, path, gap: Optional[bytes] = None):
    data = to_bytes(m, gap)
    with open(path, 'wb') as f:
        f.write(data)
    return len(data)


# ----------------------------------------------------------------------------------------------
# helpers: transforms, geometry access, OBJ export
# ----------------------------------------------------------------------------------------------
def mat(t) -> np.ndarray:
    return np.array(t, dtype=np.float64).reshape(4, 4)


def world_matrix(n: Node) -> np.ndarray:
    """Row-vector convention: p_world = p_local @ world_matrix."""
    M = mat(n.local); p = n.parent
    while p is not None:
        M = M @ mat(p.local); p = p.parent
    return M


def node_geometry(n: Node):
    """(vertices, triangles) of one node; triangle indices are 0-based into the returned vertices."""
    c = n.chunk
    if c is None or n.nverts == 0:
        return None, None
    v0 = n.vbyte // c.stride
    i0 = n.ibyte // index_dtype(len(c.vertices)).itemsize
    verts = c.vertices[v0:v0 + n.nverts]
    idx = c.indices[i0:i0 + n.nindices].astype(np.int64) - v0
    return verts, idx.reshape(-1, 3)


def export_obj(m: Model, path, world=True, lod_name=''):
    lines = ['# exported by mgm_bos.py %s' % lod_name]
    vbase = 1
    report = {'nodes': 0, 'verts': 0, 'tris': 0, 'bad_idx': 0, 'nrm_len': [], 'pos': []}
    for n in m.nodes():
        verts, tris = node_geometry(n)
        if verts is None or 'pos' not in verts.dtype.names or verts.dtype['pos'].shape != (3,):
            continue
        P = verts['pos'].astype(np.float64); N = verts['nrm'].astype(np.float64)
        if world:
            M = mat(n.offset) @ world_matrix(n)
            P = np.c_[P, np.ones(len(P))] @ M
            P = P[:, :3]
            R = M[:3, :3]
            N = N @ np.linalg.inv(R).T
            ln = np.linalg.norm(N, axis=1, keepdims=True); ln[ln == 0] = 1
            N = N / ln
        uv = verts['uv'].astype(np.float64)
        report['bad_idx'] += int(((tris < 0) | (tris >= len(verts))).sum())
        report['nrm_len'].append(np.linalg.norm(verts['nrm'].astype(np.float64), axis=1))
        report['pos'].append(P)
        lines.append('o %s' % (n.name.replace(' ', '_') or 'node%d' % n.index))
        lines += ['v %.6f %.6f %.6f' % tuple(p) for p in P]
        lines += ['vt %.6f %.6f' % (u, 1.0 - v) for u, v in uv]
        lines += ['vn %.6f %.6f %.6f' % tuple(q) for q in N]
        for a, b, c in tris + vbase:
            lines.append('f %d/%d/%d %d/%d/%d %d/%d/%d' % (a, a, a, b, b, b, c, c, c))
        vbase += len(verts)
        report['nodes'] += 1; report['verts'] += len(verts); report['tris'] += len(tris)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    nl = np.concatenate(report['nrm_len']) if report['nrm_len'] else np.zeros(0)
    allp = np.concatenate(report['pos']) if report['pos'] else np.zeros((0, 3))
    report['nrm_len'] = (float(nl.min()), float(nl.max())) if len(nl) else None
    report['bbox_min'] = allp.min(0).round(3).tolist() if len(allp) else None
    report['bbox_max'] = allp.max(0).round(3).tolist() if len(allp) else None
    del report['pos']
    return report


def quat_of_key(k) -> np.ndarray:
    return k['rot'].astype(np.float64) / QUAT_SCALE


def make_key(t, rot=(0.0, 0.0, 0.0, 1.0), pos=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0), visible=1):
    k = np.zeros(1, KEY_DTYPE)
    k['t'] = t; k['visible'] = visible; k['pos'] = pos
    q = np.asarray(rot, np.float64); q = q / np.linalg.norm(q)
    k['rot'] = np.round(q * QUAT_SCALE).astype(np.int16)
    k['scale'] = np.round(np.asarray(scale) * 1000).astype(np.uint16)
    return k[0]


def axis_angle_quat(axis, deg):
    a = np.asarray(axis, np.float64); a = a / np.linalg.norm(a)
    h = np.radians(deg) / 2
    return tuple(a * np.sin(h)) + (np.cos(h),)


# ----------------------------------------------------------------------------------------------
# builder for NEW models (structure copied from the observed invariants, see spec section 9)
# ----------------------------------------------------------------------------------------------
ROOT_LOCAL = (0.0, 0.0, -1.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0)
DEFAULT_COLORS = bytes.fromhex('4b4b4b1aa1a1a131ffff00004b4b4b00')   # most common 'Specular' block
IDENT = tuple(np.eye(4).ravel())


def new_model() -> Model:
    """Scene Root (axis swap, flags 1) + the shared empty 'helper' chunk that owns all mesh-less nodes."""
    helper = Chunk(shader='Specular', colors=bytes(16), textures=[], stride=36,
                   vertices=np.zeros(0, vertex_dtype(36)), indices=np.zeros(0, '<u2'))
    root = Node(index=0, name='Scene Root', flags=1, local=ROOT_LOCAL, u1=0, chunk=helper, slot=0)
    helper.bones.append(root)
    return Model(root=root, anims=[], chunks=[helper], gap=b'')


def add_node(m: Model, name, parent: Node, translation=(0.0, 0.0, 0.0), rotation=None, mesh=None,
             shader='Specular', textures=('white.bmp', 'normal.bmp', 'white.bmp', 'white.bmp'),
             colors=DEFAULT_COLORS, flags=None) -> Node:
    """Add a node.  `mesh` = (positions Nx3, normals Nx3, uvs Nx2, triangles Mx3) in the node's own
    space; the node then gets its own single-bone chunk (the layout verified in LOD30/90).
    Without a mesh the node becomes a helper (pivot / hook) bone of the shared empty chunk.
    translation/rotation are relative to the parent, in the parent's frame (row-vector convention).
    Children of Scene Root live in the source frame: +X = left wing, +Y = aft, +Z = up."""
    idx = 1 + max(n.index for n in m.nodes())
    L = np.eye(4)
    if rotation is not None:
        L[:3, :3] = np.asarray(rotation, np.float64).reshape(3, 3)
    L[3, :3] = translation
    n = Node(index=idx, name=name, parent=parent, local=tuple(L.ravel()), u1=1)
    parent.children.append(n)
    if mesh is None:
        helper = m.chunks[0]
        n.flags = 1 if flags is None else flags
        n.chunk = helper; n.slot = len(helper.bones); helper.bones.append(n)
        n.stride, n.shader = helper.stride, helper.shader
    else:
        P, N, UV, T = (np.asarray(a) for a in mesh)
        if len(P) > 0xffff:
            raise ValueError('split meshes above 65535 vertices')
        v = np.zeros(len(P), vertex_dtype(36))
        v['pos'] = P; v['nrm'] = N; v['uv'] = UV; v['slot'] = 0.0
        c = Chunk(shader=shader, colors=colors, textures=list(textures), stride=36,
                  vertices=v, indices=np.asarray(T, '<u2').ravel())
        c.bones = [n]
        m.chunks.append(c)
        n.flags = 0 if flags is None else flags
        n.chunk = c; n.slot = 0; n.stride = 36; n.shader = shader
        n.nverts, n.nindices, n.vbyte, n.ibyte = len(v), len(c.indices), 0, 0
    return n


def add_rotation(m: Model, arg: int, node: Node, axis, keys, layer=0):
    """Rotation driven by `arg`: keys = [(t, degrees), ...] with t = argument value 0..1.
    The quaternion is written about `axis` (node/parent frame).  Keep the node's own local rotation
    identity (pivot node) so every plausible composition rule gives the same result."""
    k = np.array([make_key(t, axis_angle_quat(axis, deg)) for t, deg in keys], KEY_DTYPE)
    m.anims.append((arg, Animation(tracks=[Track(node=node.index, keys=k, kind=TRACK_ROT + layer)])))
    node.z = 1


def add_visibility(m: Model, arg: int, node: Node, keys, layer=0):
    """keys = [(t, visible 0/1), ...]"""
    k = np.array([make_key(t, visible=vis) for t, vis in keys], KEY_DTYPE)
    m.anims.append((arg, Animation(tracks=[Track(node=node.index, keys=k, kind=TRACK_VIS + layer)])))
    node.z = 1


def finalize(m: Model, gap_bytes=0):
    """Fill derived fields: bone maps, node bboxes (model space, bind pose), dense checks."""
    nodes = m.nodes()
    assert [n.index for n in nodes] == list(range(len(nodes))), 'node indices must be dense 0..N-1'
    for c in m.chunks:
        c.bone_map = [(b.index, i) for i, b in enumerate(c.bones)]
        for b in c.bones:
            b.stride, b.shader = c.stride, c.shader
    for n in nodes:
        verts, tris = node_geometry(n)
        if verts is None:
            n.bbox = (0.0,) * 6; continue
        P = (np.c_[verts['pos'], np.ones(len(verts))] @ (mat(n.offset) @ world_matrix(n)))[:, :3]
        n.bbox = tuple(P.max(0)) + tuple(P.min(0))
    # one Animation per arg, args ascending, tracks sorted by node (all 98 shipped files do this);
    # layer digit = running count per (node, channel) in arg order (holds in 28/98 files; the rest
    # use some other order - meaning of the layer digit not proven)
    merged = {}
    for arg, a in m.anims:
        merged.setdefault(arg, Animation()).tracks.extend(a.tracks)
    count = {}
    m.anims = []
    for arg in sorted(merged):
        a = merged[arg]; a.tracks.sort(key=lambda t: t.node)
        for t in a.tracks:
            ch = t.kind // 100; k = (t.node, ch)
            t.kind = ch * 100 + count.get(k, 0); count[k] = count.get(k, 0) + 1
        m.anims.append((arg, a))
    m.gap = bytes(gap_bytes)
    return m


def _box(sx, sy, sz, cx=0.0, cy=0.0, cz=0.0):
    """Axis-aligned box mesh (24 verts, 12 tris) for the demo."""
    P, N, UV, T = [], [], [], []
    for axis in range(3):
        for sgn in (-1, 1):
            nrm = np.zeros(3); nrm[axis] = sgn
            u_ax, v_ax = [a for a in range(3) if a != axis]
            base = len(P)
            for du, dv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                p = np.zeros(3); p[axis] = sgn; p[u_ax] = du; p[v_ax] = dv
                P.append(p * (sx / 2, sy / 2, sz / 2) + (cx, cy, cz)); N.append(nrm); UV.append(((du + 1) / 2, (dv + 1) / 2))
            t = [(base, base + 1, base + 2), (base, base + 2, base + 3)]
            if sgn < 0:
                t = [(a, c, b) for a, b, c in t]
            T += t
    return np.array(P), np.array(N), np.array(UV), np.array(T)


def build_demo() -> Model:
    """Toy aircraft: fuselage, wing, ailerons, elevator, rudder, gear leg, propeller - each a pivot
    helper + mesh child, rotations on the real BoS argument numbers (see yak1s69.arg)."""
    m = new_model()
    cog = add_node(m, 'COG', m.root)
    add_node(m, 'Fuselage', cog, mesh=_box(1.0, 8.0, 1.2, 0, 0.5, 0))
    add_node(m, 'Wing', cog, mesh=_box(10.0, 1.6, 0.15, 0, -0.5, -0.3))

    # source frame: +X left, +Y aft, +Z up
    def surface(name, arg, pivot_at, axis, size, centre, keys):
        piv = add_node(m, 'Pivot_' + name, cog, translation=pivot_at)
        add_node(m, name, piv, mesh=_box(*size, *centre))
        add_rotation(m, arg, piv, axis, keys)
        return piv
    ail = [(0.0, -20.0), (0.5, 0.0), (1.0, 20.0)]
    surface('Aileron_L', 12200, (3.5, 0.3, -0.3), (1, 0, 0), (2.5, 0.4, 0.08), (0, 0.2, 0), ail)
    surface('Aileron_R', 12220, (-3.5, 0.3, -0.3), (1, 0, 0), (2.5, 0.4, 0.08), (0, 0.2, 0), ail)
    surface('Elevator', 12005, (0.0, 4.3, 0.0), (1, 0, 0), (3.0, 0.4, 0.06), (0, 0.2, 0),
            [(0.0, -25.0), (0.5, 0.0), (1.0, 25.0)])
    surface('Rudder', 12400, (0.0, 4.4, 0.6), (0, 0, 1), (0.06, 0.4, 1.2), (0, 0.2, 0.6),
            [(0.0, -25.0), (0.5, 0.0), (1.0, 25.0)])
    surface('Gear_L', 13300, (1.6, -0.8, -0.6), (0, 1, 0), (0.12, 0.12, 1.4), (0, 0, -0.7),
            [(0.0, 0.0), (1.0, 85.0)])
    surface('Prop', 14130, (0.0, -3.6, 0.0), (0, 1, 0), (2.8, 0.05, 0.2), (0, 0, 0),
            [(0.0, 0.0), (0.25, 90.0), (0.5, 180.0), (0.75, 270.0), (1.0, 360.0)])
    return finalize(m)


# ----------------------------------------------------------------------------------------------
# dump
# ----------------------------------------------------------------------------------------------
def dump(m: Model, out=sys.stdout, verbose=False):
    nodes = m.nodes()
    pr = lambda *a: print(*a, file=out)
    pr('Model: %d nodes, %d chunks, %d animations, gap %d bytes' % (len(nodes), len(m.chunks), len(m.anims), len(m.gap)))
    pr('\n== node tree (index name [shader] verts/idx  slot  flags) ==')

    def walk(n, depth, seen):
        if id(n) in seen:
            pr('  ' * depth + '(cycle %d)' % n.index); return
        seen.add(id(n))
        T = mat(n.local)[3, :3]
        geo = ' %d v/%d i' % (n.nverts, n.nindices) if n.nverts else ''
        pr('  ' * depth + '%d %r [%s]%s slot=%d flags=%#x T=(%.3f %.3f %.3f)%s' % (
            n.index, n.name, n.shader, geo, n.slot, n.flags, T[0], T[1], T[2],
            (' aux=%s' % (n.aux,)) if any(n.aux) else ''))
        if verbose:
            pr('  ' * depth + '    local=%s' % np.round(mat(n.local), 4).tolist())
            pr('  ' * depth + '    offset=%s bbox=%s u1=%d z=%d w=%d' % (np.round(mat(n.offset), 4).tolist(), np.round(n.bbox, 3).tolist(), n.u1, n.z, n.w))
        for c in n.children:
            walk(c, depth + 1, seen)
    walk(m.root, 0, set())
    pr('\n== chunks (buffer order) ==')
    for i, c in enumerate(m.chunks):
        pr('%d %s stride=%d verts=%d idx=%d tex=%s bones=%d extra=%s colors=%s' % (
            i, c.shader, c.stride, len(c.vertices), len(c.indices), c.textures, len(c.bones),
            [n.name for n in c.extra], c.colors.hex()))
    pr('\n== animations (arg -> tracks) ==')
    byidx = {n.index: n for n in nodes}
    kinds = {0: 'vis', 1: 'pos', 2: 'rot'}
    for arg, a in m.anims:
        for t in a.tracks:
            nm = byidx[t.node].name if t.node in byidx else '?'
            ts = ' '.join('%.3g' % x for x in t.keys['t'])
            pr('arg %5d  %s%d node %d %r  %d keys t=[%s]' % (arg, kinds.get(t.kind // 100, '?'), t.kind % 100,
                                                           t.node, nm, len(t.keys), ts))
            if verbose:
                for k in t.keys:
                    pr('        t=%.4f vis=%d pos=%s q=%s scale=%s' % (k['t'], k['visible'], np.round(k['pos'], 4).tolist(),
                                                                   np.round(quat_of_key(k), 4).tolist(), (k['scale'] / 1000).tolist()))


def roundtrip(path) -> bool:
    orig = open(path, 'rb').read()
    m = read(orig)
    out = to_bytes(m)
    if out == orig:
        return True
    n = min(len(out), len(orig))
    diff = next((i for i in range(n) if out[i] != orig[i]), n)
    print('  first difference at %#x (sizes %d vs %d)' % (diff, len(orig), len(out)))
    return False


def main(argv):
    if len(argv) < 2:
        print(__doc__); return 2
    cmd = argv[0]
    if cmd == 'dump':
        m = read(argv[1]); dump(m, verbose='--verbose' in argv); return 0
    if cmd == 'roundtrip':
        bad = 0
        for p in argv[1:]:
            ok = roundtrip(p)
            print('%s  %s' % ('OK  ' if ok else 'FAIL', p)); bad += not ok
        return 1 if bad else 0
    if cmd == 'demo':
        m = build_demo(); n = write(m, argv[1]); print('wrote', argv[1], n, 'bytes')
        ok = roundtrip(argv[1]); print('roundtrip', 'OK' if ok else 'FAIL')
        m2 = read(argv[1]); dump(m2)
        if len(argv) > 2:
            print(export_obj(m2, argv[2]))
        return 0 if ok else 1
    if cmd == 'obj':
        m = read(argv[1]); rep = export_obj(m, argv[2], lod_name=argv[1]); print(rep); return 0
    print(__doc__); return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
