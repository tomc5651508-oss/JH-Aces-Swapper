"""IL-2's observed 26,000,000-byte per-texture resource budget.

Preserve existing mip images. Compress RGB tangent normals to legacy BC3;
drop oversized top levels only when even BC3 cannot fit (8192 -> 4096).
"""
import argparse,hashlib,io,json,struct,subprocess,tempfile
from pathlib import Path
import numpy as np
from PIL import Image
LIMIT=26_000_000
def levels(raw):
 h=list(struct.unpack_from('<31I',raw,4));w,y=h[3],h[2];fc=raw[84:88];pos=128;out=[]
 assert raw[:4]==b'DDS ' and fc!=b'DX10'
 for _ in range(max(1,h[6])):
  size=max(1,(w+3)//4)*max(1,(y+3)//4)*(8 if fc==b'DXT1' else 16) if h[19]&4 else w*y*(h[21]//8)
  out.append((w,y,raw[pos:pos+size]));pos+=size;w=max(1,w//2);y=max(1,y//2)
 assert pos==len(raw),(pos,len(raw));return h,out
def sha(raw):return hashlib.sha256(raw).hexdigest()
def constrain(package,texconv,report=None):
 rows=[]
 for p in sorted(Path(package).rglob('*.dds')):
  raw=p.read_bytes()
  if len(raw)<=LIMIT:continue
  h,mips=levels(raw);original=(h[3],h[2]);is_normal=p.stem.lower().endswith('_b');drop=0
  while 128+sum(max(1,(w+3)//4)*max(1,(y+3)//4)*16 for w,y,_ in mips[drop:])>LIMIT:drop+=1
  chosen=mips[drop:];assert chosen
  if raw[84:88]==b'DXT5':
   h[3],h[2],h[6]=chosen[0][0],chosen[0][1],len(chosen);h[4]=len(chosen[0][2]);out=b'DDS '+struct.pack('<31I',*h)+b''.join(v for _,_,v in chosen);errors=[]
  else:
   assert is_normal and h[21]==32 and h[22:26]==[255,65280,16711680,4278190080],p
   payload=[];errors=[]
   with tempfile.TemporaryDirectory() as td:
    for i,(w,y,pixels) in enumerate(chosen):
     a=np.frombuffer(pixels,np.uint8).reshape(y,w,4);png=Path(td)/'level.png';Image.fromarray(a).save(png)
     run=subprocess.run([str(texconv),'-f','BC3_UNORM','-m','1','-y','-nologo','-o',td,str(png)],capture_output=True,text=True)
     if run.returncode:raise RuntimeError(run.stdout+run.stderr)
     encoded=(Path(td)/'level.dds').read_bytes();assert encoded[84:88]==b'DXT5';header=bytearray(encoded[:128]);payload.append(encoded[128:])
     if i==0:
      b=np.array(Image.open(io.BytesIO(encoded)).convert('RGBA'));step=max(1,w//512)
      v=a[::step,::step,:3].astype('f4')/127.5-1;u=b[::step,::step,:3].astype('f4')/127.5-1
      v/=np.maximum(np.linalg.norm(v,axis=-1,keepdims=True),1e-12);u/=np.maximum(np.linalg.norm(u,axis=-1,keepdims=True),1e-12)
      degrees=np.degrees(np.arccos(np.clip((u*v).sum(-1),-1,1)));errors=np.percentile(degrees,[50,95,99,100]).tolist()
    struct.pack_into('<7I',header,4,124,0xA1007,chosen[0][1],chosen[0][0],len(payload[0]),0,len(payload));struct.pack_into('<I',header,108,0x401008)
    out=bytes(header)+b''.join(payload)
  assert len(out)<=LIMIT
  hd,ms=levels(out);assert len(ms)==1+int(np.floor(np.log2(max(hd[3],hd[2]))))
  tmp=p.with_suffix('.budget.tmp');tmp.write_bytes(out);tmp.replace(p)
  row={'file':p.relative_to(package).as_posix(),'before_bytes':len(raw),'after_bytes':len(out),'before_size':original,'after_size':[hd[3],hd[2]],'format':'legacy BC3 RGB normal' if is_normal else 'legacy BC3 colour','dropped_top_mips':drop,'normal_angular_error_p50_p95_p99_max_deg_sampled':errors,'before_sha256':sha(raw),'after_sha256':sha(out),'existing_mip_images_preserved_before_block_encoding':True}
  rows.append(row);print('RESOURCE_BUDGET',p.name,len(raw),'->',len(out),'SIZE',row['after_size'],flush=True)
 bad=[str(p) for p in Path(package).rglob('*.dds') if p.stat().st_size>LIMIT];assert not bad
 result={'limit_bytes':LIMIT,'fixed':rows,'remaining_oversized':bad}
 if report:Path(report).write_text(json.dumps(result,indent=2),encoding='utf-8')
 return result
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('package',type=Path);ap.add_argument('--texconv',type=Path,required=True);ap.add_argument('--report',type=Path,required=True);a=ap.parse_args();constrain(a.package,a.texconv,a.report)
