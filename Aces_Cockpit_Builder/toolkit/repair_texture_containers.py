"""Lossless DDS header/mip reconstruction from preserved DDSx inputs."""
import extract_cockpits as e
from parse.material import DDSx
from PIL import Image
import struct
for out in e.DEST.iterdir():
 if not out.is_dir() or out.name not in e.SELECTED:continue
 checked=[]
 for p in sorted((out/'textures').glob('*.dds')):
  raw=p.read_bytes();fmt=struct.unpack_from('<I',raw,84)[0]
  if fmt in (21,50):
   candidates=[]
   for x in (out/'raw_textures').glob('part_*/'+p.stem+'.ddsx'):
    h=DDSx.Header(x.read_bytes()[:32]);candidates.append((h.w*h.h,x,h))
   _,src,h=max(candidates,key=lambda v:v[0]);payload=DDSx(str(src)).getData();bpp=32 if fmt==21 else 8
   sizes=[max(1,h.w>>i)*max(1,h.h>>i)*(bpp//8) for i in range(h.levels)]
   assert len(payload)==sum(sizes),(p,len(payload),sizes)
   if h.flags&0x40000:
    parts=[];pos=0
    for sz in reversed(sizes):parts.append(payload[pos:pos+sz]);pos+=sz
    payload=b''.join(reversed(parts))
   header=bytearray(128);header[:4]=b'DDS '
   struct.pack_into('<7I',header,4,124,0x100f|(0x20000 if h.levels>1 else 0),h.h,h.w,h.w*(bpp//8),0,h.levels)
   struct.pack_into('<8I',header,76,32,0x41 if fmt==21 else 0x20000,0,bpp,
                    0xff0000 if fmt==21 else 0xff,0xff00 if fmt==21 else 0,0xff if fmt==21 else 0,0xff000000 if fmt==21 else 0)
   struct.pack_into('<I',header,108,0x401008 if h.levels>1 else 0x1000)
   p.write_bytes(header+payload)
  row={'name':p.name,'bytes':p.stat().st_size,'sha256':e.sha(p)}
  try:
   im=Image.open(p);im.load();row.update(decoded=True,width=im.width,height=im.height)
   im.convert('RGBA').save(out/'preview_textures'/(p.stem+'.png'))
  except Exception as ex:row.update(decoded=False,error=repr(ex))
  checked.append(row)
 e.dump(out/'texture_validation.json',checked)
 report=e.json.loads((out/'extraction_report.json').read_text());report['dds_decode_failures']=[r['name'] for r in checked if not r['decoded']]
 e.dump(out/'extraction_report.json',report)
 print('DDS',out.name,len(checked),report['dds_decode_failures'],flush=True)
