import extract_cockpits as e
from parse.a2d_anim import read_glb,write_glb
from PIL import Image
import struct
summary=[]
for out in e.DEST.iterdir():
 if not out.is_dir() or out.name not in e.SELECTED:continue
 report=e.json.loads((out/'extraction_report.json').read_text());meta_path=next(out.glob('*metadata.json'));meta=e.json.loads(meta_path.read_text())
 npz=next(out.glob('*mesh.npz'));data=dict(e.np.load(npz));glb=next(out.glob('*.glb'));js,binb=read_glb(glb)
 byname={m['name']:m for m in js['meshes']};blocks=[]
 for b in meta['vertex_blocks']:
  if b['format']==3 and b['stride'] in (16,20,24):
   raw=(out/'raw_resources'/b['file']).read_bytes();offset={16:8,20:12,24:12}[b['stride']]
   packed=e.np.ndarray((b['vertices'],4),dtype='u1',buffer=raw,offset=offset,strides=(b['stride'],1))
   normals=packed[:,[2,1,0]].astype('f4')/127.5-1
   normals/=e.np.maximum(e.np.linalg.norm(normals,axis=1,keepdims=True),1e-15);blocks.append((b['first_vertex'],normals))
 normal_objects=0
 for i,obj in enumerate(meta['objects']):
  ids=data[f'source_vertex_id_{i}'];normals=e.np.empty((len(ids),3),dtype='<f4');covered=e.np.zeros(len(ids),bool)
  for first,n in blocks:
   mask=(ids>=first)&(ids<first+len(n));normals[mask]=n[ids[mask]-first];covered|=mask
  if covered.all() and len(ids):
   data[f'local_normals_{i}']=normals;obj['normals']='Authored packed D3DCOLOR normal decoded; raw bytes preserved';normal_objects+=1
   mesh=byname.get(obj['name'])
   if mesh:
    while len(binb)%4:binb.append(0)
    off=len(binb);binb.extend(normals.tobytes());js['bufferViews'].append({'buffer':0,'byteOffset':off,'byteLength':normals.nbytes,'target':34962})
    js['accessors'].append({'bufferView':len(js['bufferViews'])-1,'componentType':5126,'count':len(normals),'type':'VEC3'})
    for prim in mesh['primitives']:
     if js['accessors'][prim['attributes']['POSITION']]['count']==len(normals):prim['attributes']['NORMAL']=len(js['accessors'])-1
  else:obj['normals']='Not decoded in review; raw source retained'
 e.np.savez_compressed(npz,**data);js['buffers'][0]['byteLength']=len(binb);write_glb(glb,js,binb)
 meta['review_normals']=f'Authored packed normals decoded for {normal_objects}/{len(meta["objects"])} objects; remaining raw data preserved.'
 e.dump(meta_path,meta)
 texreport=[]
 preview=out/'preview_textures';preview.mkdir(exist_ok=True)
 for p in sorted((out/'textures').glob('*.dds')):
  row={'name':p.name,'bytes':p.stat().st_size,'sha256':e.sha(p)}
  try:
   im=Image.open(p);im.load();row.update(width=im.width,height=im.height,format='DDS',decoded=True)
   im.convert('RGBA').save(preview/(p.stem+'.png'))
  except Exception as ex:row.update(decoded=False,error=repr(ex))
  texreport.append(row)
 e.dump(out/'texture_validation.json',texreport)
 cfg=e.json.loads(next((out/'configuration').glob('*'+report['configuration']+'.json')).read_text())
 if cfg.get('gunnerFps'):
  gf=cfg['gunnerFps'];nodes={n['name']:n for n in meta['nodes']};head=nodes.get(gf.get('head'))
  gunner={'source':'Actual Aces of Thunder cockpit model and aircraft configuration','view':gf,
          'head_node':head,'station_meshes':[o['name'] for o in meta['objects'] if any(s in o['name'].lower() for s in ('turret','mgun','gunner'))],
          'scene':'../'+glb.name,'note':'Rear station geometry and transforms are retained in the shared complete cockpit scene; source gunner view remains relative to its named head node.',
          'ikGunner':cfg.get('ikGunner'),'crew':cfg.get('crew')}
  e.dump(out/'gunner_positions/rear_gunner.json',gunner)
 report['normal_objects_decoded']=normal_objects;report['dds_count']=len(texreport);report['dds_decode_failures']=[r['name'] for r in texreport if not r['decoded']]
 report['unresolved_engine_textures']=report.pop('missing_dds',[])
 report['gunner_station']=bool(cfg.get('gunnerFps'))
 report['status']='EXTRACTED; static validation; QA pending'
 e.dump(out/'extraction_report.json',report);summary.append(report)
 print('VALIDATED',out.name,len(texreport),report['dds_decode_failures'],flush=True)
e.dump(e.DEST/'extraction_summary.json',summary)
