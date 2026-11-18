"""Audit DDSs read-only, or explicitly write lossless derived repairs.

Supports the narrow native DDS formats in zero_native_dds.py. Optional --d3d
creates an independent headless WARP device; it never launches/attaches IL-2.
"""
import argparse
import json
import os
from pathlib import Path
from zero_native_dds import D3DProbe, normalize


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('paths',nargs='+',type=Path)
    ap.add_argument('--output-dir',type=Path)
    ap.add_argument('--repair-dagor-tail',action='store_true')
    ap.add_argument('--d3d',action='store_true')
    ap.add_argument('--report',type=Path)
    args=ap.parse_args()
    if args.repair_dagor_tail and args.output_dir is None:
        ap.error('--repair-dagor-tail requires a separate --output-dir')
    files=[]
    for p in args.paths:
        if p.is_dir(): files.extend(q.resolve() for q in p.rglob('*') if q.is_file() and q.suffix.lower()=='.dds')
        elif p.is_file() and p.suffix.lower()=='.dds':files.append(p.resolve())
        else:ap.error(f'Not a DDS file/directory: {p}')
    files=sorted(set(files))
    if not files:ap.error('No DDS files found')
    common=Path(os.path.commonpath([str(p.parent) for p in files]))
    if args.output_dir:
        destination=args.output_dir.resolve()
        for p in args.paths:
            if p.is_dir() and destination.is_relative_to(p.resolve()):
                ap.error('Output must be outside every input directory')
        for p in files:
            out=destination/p.relative_to(common)
            if out==p or out.exists():ap.error(f'Refusing overwrite: {out}')
    if args.report and args.report.exists():ap.error(f'Refusing report overwrite: {args.report}')
    rows=[];failed=0;probe=None
    if args.d3d:
        try:probe=D3DProbe()
        except Exception as error:
            print(json.dumps(dict(native_probe_available=False,error=str(error))));return 2
    try:
        for p in files:
            row={'input':str(p)}
            try:
                normalized,details=normalize(p.read_bytes());row.update(details)
                missing=bool(details['removed_nonimage_bytes'])
                if missing and args.output_dir and not args.repair_dagor_tail:
                    raise ValueError('Recognized malformed Dagor mip chain: repair needs --repair-dagor-tail')
                target=p
                if args.output_dir:
                    target=args.output_dir.resolve()/p.relative_to(common)
                    target.parent.mkdir(parents=True,exist_ok=True)
                    with target.open('xb') as stream:stream.write(normalized)
                    row['output']=str(target)
                    again,_=normalize(target.read_bytes())
                    if again!=normalized:raise ValueError('Repair is not idempotent')
                ok=not missing or args.output_dir is not None
                if probe:
                    row['d3d']=probe.check(target);ok=ok and row['d3d']['success']
                row['passed']=ok
            except Exception as error:
                row.update(passed=False,error=str(error))
            failed+=not row['passed'];rows.append(row)
    finally:
        if probe:probe.close()
    report=dict(files=len(rows),passed=len(rows)-failed,failed=failed,
                source_files_modified=False,native_probe_requested=args.d3d,results=rows)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        with args.report.open('x',encoding='utf-8') as stream:json.dump(report,stream,indent=2)
        print(json.dumps({k:v for k,v in report.items() if k!='results'}))
    else:print(json.dumps(report,indent=2))
    return 1 if failed else 0


if __name__=='__main__':raise SystemExit(main())
