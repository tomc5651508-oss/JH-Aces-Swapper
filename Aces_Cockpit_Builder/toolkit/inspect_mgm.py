"""Read-only MGM inventory and structural checks; not an engine acceptance test.

Python + numpy. Uses sibling mgm_bos.py. No game launch, asset rewrite or private
lab imports. Reports only input basenames, suitable for sharing distilled facts.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import mgm_bos as G


def inspect(path, details=False):
    raw = path.read_bytes()
    m = G.read(raw)
    nodes = m.nodes()
    errors, warnings, chunks = [], [], []
    node_ids = {id(n) for n in nodes}
    by_index = {n.index: n for n in nodes}
    chunk_index = {id(c): i for i, c in enumerate(m.chunks)}

    def check(ok, message):
        if not ok:
            errors.append(message)

    check(len(chunk_index) == len(m.chunks), 'duplicate chunk objects')
    check([n.index for n in nodes] == list(range(len(nodes))), 'node indices not dense/unique')
    check(m.root is not None and m.root.index == 0, 'missing/indexed root')
    for n in nodes:
        label = f'node {n.index} {n.name}'
        check(id(n.chunk) in chunk_index, f'{label}: orphan chunk')
        check(n.parent is None if n is m.root else id(n.parent) in node_ids,
              f'{label}: invalid parent')
        for child in n.children:
            check(child.parent is n, f'{label}: child/parent disagreement')
        seen, p = set(), n
        while p is not None:
            if id(p) in seen:
                errors.append(f'{label}: parent cycle')
                break
            seen.add(id(p))
            p = p.parent
        if id(n.chunk) not in chunk_index:
            continue
        c = n.chunk
        check(0 <= n.slot < len(c.bones) and c.bones[n.slot] is n,
              f'{label}: owner slot disagreement')
        check((n.stride, n.shader) == (c.stride, c.shader), f'{label}: shader/stride disagreement')
        if n.nverts:
            check(n.vbyte % c.stride == 0, f'{label}: vertex byte alignment')
            first = n.vbyte // c.stride
            check(first >= 0 and first + n.nverts <= len(c.vertices), f'{label}: vertex range')
            v = c.vertices[first:first + n.nverts]
            if 'slot' in v.dtype.names:
                check(bool(np.all(v['slot'] == n.slot)), f'{label}: vertex slot values')
        if n.nindices:
            width = c.indices.dtype.itemsize
            check(n.ibyte % width == 0 and n.nindices % 3 == 0, f'{label}: index alignment/count')
            first = n.ibyte // width
            check(first >= 0 and first + n.nindices <= len(c.indices), f'{label}: index range')
            idx = c.indices[first:first + n.nindices].astype(np.int64)
            check(bool(np.all((idx >= 0) & (idx < len(c.vertices)))), f'{label}: index out of chunk')
            if 'slot' in c.vertices.dtype.names:
                start = n.vbyte // c.stride
                check(bool(np.all((idx >= start) & (idx < start + n.nverts))),
                      f'{label}: rigid triangle outside owned vertices')

    for i, c in enumerate(m.chunks):
        label = f'chunk {i}'
        if len(c.bones) > 64 and not len(c.vertices):
            warnings.append(f'{label}: helper-only palette {len(c.bones)} exceeds surveyed 64; retain baseline and investigate before adding helpers')
        else:
            check(len(c.bones) <= 64, f'{label}: geometry palette over observed 64-bone contract')
        check(c.bone_map == [(n.index, k) for k, n in enumerate(c.bones)], f'{label}: bone map')
        check(c.vertices.dtype.itemsize == c.stride, f'{label}: dtype/stride')
        check(c.indices.dtype == G.index_dtype(len(c.vertices)), f'{label}: index width')
        owners = [n for n in nodes if n.chunk is c]
        check({id(n) for n in owners} == {id(n) for n in c.bones}, f'{label}: missing owners/helpers')
        for slot, n in enumerate(c.bones):
            check(n.chunk is c and n.slot == slot, f'{label}: bone ownership {slot}')
        for n in c.extra:
            check(id(n) in node_ids, f'{label}: unknown extra helper')
        for attr, count_attr, size in [('vbyte', 'nverts', c.stride),
                                       ('ibyte', 'nindices', c.indices.dtype.itemsize)]:
            ranges = sorted((getattr(n, attr) // size, getattr(n, count_attr))
                            for n in owners if getattr(n, count_attr))
            cursor = 0
            for start, count in ranges:
                check(start == cursor, f'{label}: gap/overlap in {attr} at {start}')
                cursor = start + count
            total = len(c.vertices) if attr == 'vbyte' else len(c.indices)
            check(cursor == total, f'{label}: incomplete {attr} ownership')
        nonfinite = {}
        for field in c.vertices.dtype.names:
            a = c.vertices[field]
            if a.dtype.kind == 'f':
                bad = int(np.count_nonzero(~np.isfinite(a)))
                if bad:
                    nonfinite[field] = bad
        if nonfinite:
            warnings.append(f'{label}: nonfinite {nonfinite}; compare retained stock buffers; reject in new data')
        chunks.append(dict(index=i, shader=c.shader, stride=c.stride, vertices=len(c.vertices),
                           triangles=len(c.indices) // 3, bones=len(c.bones),
                           colors_hex=bytes(c.colors).hex(), flags=c.u8,
                           textures=list(c.textures), nonfinite=nonfinite,
                           owners=[n.name for n in c.bones]))

    arguments, track_rows = [], []
    for arg, anim in m.anims:
        arguments.append(arg)
        for t in anim.tracks:
            check(t.node in by_index, f'arg {arg}: missing node {t.node}')
            check(t.pair_node is None or t.pair_node in by_index, f'arg {arg}: missing pair node')
            times = t.keys['t']
            check(bool(np.isfinite(times).all() and np.all(np.diff(times) >= 0)),
                  f'arg {arg}: nonfinite/unsorted key times')
            track_rows.append(dict(arg=arg, node=t.node, name=by_index[t.node].name if t.node in by_index else None,
                                   kind=t.kind, keys=len(t.keys), pair_node=t.pair_node,
                                   key_sha256=hashlib.sha256(t.keys.tobytes()).hexdigest()))
    check(arguments == sorted(set(arguments)), 'argument IDs not sorted/unique')
    roundtrip = G.to_bytes(m) == raw
    check(roundtrip, 'byte-identical roundtrip failed')
    row = dict(file=path.name, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw),
               nodes=len(nodes), chunks=chunks, arguments=arguments, tracks=len(track_rows),
               maximum_palette=max((len(c.bones) for c in m.chunks), default=0),
               roundtrip_exact=roundtrip, errors=errors, warnings=warnings,
               structural_pass=not errors, runtime_tested=False)
    if details:
        row['node_details'] = [dict(index=n.index, name=n.name,
                                    parent=n.parent.index if n.parent else None,
                                    chunk=chunk_index.get(id(n.chunk)), slot=n.slot,
                                    vertices=n.nverts, indices=n.nindices, aux=list(n.aux),
                                    flags=n.flags, local=list(n.local), offset=list(n.offset)) for n in nodes]
        row['track_details'] = track_rows
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('paths', nargs='+', type=Path)
    ap.add_argument('--details', action='store_true')
    ap.add_argument('--report', type=Path)
    args = ap.parse_args()
    files = []
    for p in args.paths:
        if p.is_dir():
            files.extend(f.resolve() for f in p.rglob('*') if f.is_file() and f.suffix.lower() == '.mgm')
        elif p.is_file() and p.suffix.lower() == '.mgm':
            files.append(p.resolve())
        else:
            ap.error(f'Not an MGM input: {p}')
    if not files:
        ap.error('No MGM files found')
    if args.report and args.report.exists():
        ap.error('Refusing report overwrite')
    rows = []
    for p in sorted(set(files)):
        try:
            rows.append(inspect(p, args.details))
        except Exception as error:
            rows.append(dict(file=p.name, structural_pass=False, errors=[str(error)], runtime_tested=False))
    report = dict(source_files_modified=False, runtime_tested=False, results=rows)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
        print(json.dumps(dict(files=len(rows), passed=sum(r['structural_pass'] for r in rows),
                              report=str(args.report), runtime_tested=False)))
    else:
        print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if all(r['structural_pass'] for r in rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
