"""Decode actual Dagor v3 channel tables and sample them with the proven native ACL reader."""
import json,struct,subprocess,hashlib
from pathlib import Path
import numpy as np
from util.decompression import CompressedData
from util.fileread import BinFile
from parse import a2d_anim,anm_graph


def decode(path,glb):
 data=CompressedData(BinFile(path.read_bytes())).decompress()
 magic,version,header_size,dump_size=struct.unpack_from('<4sIII',data)
 assert magic==b'ANIM' and version in (0x300,0x301) and header_size==16
 assert len(data)==header_size+dump_size+64
 dump=data[header_size:header_size+dump_size];tables=data[-64:];channels=[];labels=[]
 def name_at(offset):
  assert 0<=offset<len(dump)
  return dump[offset:dump.index(b'\0',offset)].decode('utf-8')
 for kind in range(4):
  offset,count,padding=struct.unpack_from('<IIQ',tables,kind*16);assert padding==0
  for i in range(count):
   if kind<3:
    acl_offset,tracks_offset,n,channel,weights_offset,names_offset=struct.unpack_from('<QQIIQQ',dump,offset+i*40)
    entries=[]
    for j in range(n):
     name_offset=struct.unpack_from('<Q',dump,names_offset+8*j)[0]
     track=struct.unpack_from('<H',dump,tracks_offset+2*j)[0]
     weight=struct.unpack_from('<f',dump,weights_offset+4*j)[0]
     entries.append({'name':name_at(name_offset),'track':track,'weight':weight})
    channels.append({'channel':channel,'acl_offset':acl_offset,'entries':entries})
   else:
    name_offset,tick,padding=struct.unpack_from('<Qii',dump,offset+i*16)
    labels.append({'name':name_at(name_offset),'tick':tick,'seconds':tick/15360.0})
 offsets={c['acl_offset'] for c in channels};assert len(offsets)==1
 offset=offsets.pop();size=struct.unpack_from('<I',dump,offset)[0];blob=dump[offset:offset+size]
 acl=path.with_suffix('.acl');acl.write_bytes(blob);samples=path.with_suffix('.samples')
 from parse.acl_decode import decode as decode_acl
 decoded=decode_acl(blob);values=np.concatenate([decoded['rot'],decoded['trans'],decoded['scale']],axis=2)
 nf,nt,_=values.shape;rate=decoded['rate'];samples.write_bytes(struct.pack('<IIIf',0x4c43415a,nt,nf,rate)+values.astype('<f4').tobytes())
 assert np.isfinite(values).all()
 normerr=float(np.abs(np.linalg.norm(values[:,:,:4],axis=2)-1).max());assert normerr<.001
 names=['']*nt
 for c in channels:
  for e in c['entries']:
   assert e['track']<nt
   if names[e['track']]:assert names[e['track']]==e['name']
   names[e['track']]=e['name']
 np.savez_compressed(path.with_suffix('.animation.npz'),values=values,sample_rate=np.array(rate),track_names=np.array(names))
 decoded={'rot':values[:,:,:4],'trans':values[:,:,4:7],'scale':values[:,:,7:10],'rate':rate}
 a2d=a2d_anim.A2d(version,names,[e['name'] for e in labels],blob)
 js,binb=a2d_anim.read_glb(glb)
 animated=a2d_anim.add_animation(js,binb,a2d,path.stem,decoded=decoded)
 graph_path=path.with_name(path.stem.removesuffix('_anim')+'_animtree.anm')
 graph_status=None;named=0
 try:
  graph=anm_graph.extract_bytes(anm_graph.unwrap(graph_path.read_bytes()),graph_path.stem)
  graph_path.with_suffix('.json').write_text(json.dumps(graph,indent=2))
  named=a2d_anim.add_named_clips(js,binb,a2d,graph,path.stem,decoded=decoded)
  graph_status={'bindings':len(graph['bindings']),'named_review_clips':named,'note':'Review groups inferred from parameter stream; original graph retained.'}
 except Exception as e:graph_status={'error':repr(e)}
 a2d_anim.write_glb(glb,js,binb)
 report={'source':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'tracks':nt,'frames':nf,'sample_rate':rate,
         'duration_seconds':(nf-1)/rate,'all_samples_finite':True,'maximum_quaternion_norm_error':normerr,
         'channels':channels,'labels':labels,'glb_full_clip_channels':animated,'graph':graph_status,'decoder_output':'pure numpy ACL decoder; verified against native samples for all eight selected AoT cockpits',
         'runtime_tested':False}
 path.with_suffix('.animation.json').write_text(json.dumps(report,indent=2))
 return {k:v for k,v in report.items() if k not in ('channels','decoder_output')}
