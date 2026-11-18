"""Private offline Aces cockpit extraction; source game is read-only."""
import os,sys,json,hashlib,shutil,traceback,struct,subprocess,contextlib
from pathlib import Path
from runtime_paths import ROOT,WORK as RUN,SOURCE as DEST,AOT as GAME
BACKEND=ROOT/'wt-asset-explorer'
# Eye/reticle values only, shipped with the builder; aces.vromfs.bin is never unpacked.
PARAMS=json.loads((ROOT/'aces_cockpit_params.json').read_text(encoding='utf-8'))['planes']
os.environ['WTX_ROOT']=str(BACKEND)
sys.path[:0]=[str(BACKEND),str(BACKEND/'dae_core')]
from PySide6.QtCore import QCoreApplication
app=QCoreApplication([])
import numpy as np
from wtx.assets import AssetLibrary,AssetRef,DYNMODEL_ID,_clean_tex_name
from parse.gameres import GameResourcePack
from parse.realres import Model,Anim2Data,AnimChar
from parse.material import DDSx
from parse.mesh import MatVData
from parse.gltf_conv import export_model_to_gltf
from util.assetcacher import AssetCacher
import util.log as log

from slots import SELECTED
def dump(path,data):
 path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text(json.dumps(data,indent=2,default=lambda o:o.tolist() if hasattr(o,'tolist') else str(o)),encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

# Preserve the untouched vertex streams and source IDs, including channels the review exporter does not decode.
vertex_blocks={}
orig_v=MatVData.VertexData.__init__
def capture_v(self,file,gv):
 raw=file.read();orig_v(self,file,gv);self._source_bytes=raw;vertex_blocks[id(self.getVertices())]=self
MatVData.VertexData.__init__=capture_v
orig_append=Model.appendVerts
def capture_append(self,verts,uvs,scale=True):
 block=vertex_blocks.get(id(verts))
 if block is not None:
  if not hasattr(self,'_source_blocks'):self._source_blocks=[]
  self._source_blocks.append((self.vertCnt,block))
 return orig_append(self,verts,uvs,scale)
Model.appendVerts=capture_append

def metadata(mdl,out):
 meta={'name':mdl.name,'vertices':mdl.vertCnt,'triangles':mdl.getFaceCount(),'nodes':[],
       'objects':[],'materials':[],'vertex_blocks':[],
       'review_normals':'Review GLB/OBJ computes geometric normals. Authored packed normals/tangents retained in raw vertex streams.',
       'skinning':'Raw resources preserve original skinning; review GLB uses the exporter skeleton attachment behavior.'}
 if mdl.skeleton:
  meta['nodes']=[{'name':n.name,'index':n.idx,'parent':n.parent.name if n.parent else None,'local':n.tm,'world':n.wtm} for n in mdl.skeleton.getNodes()]
 for i,m in enumerate(mdl.materials or []):
  meta['materials'].append({'index':i,'name':m.getName(),'shader':m.cls,'textures':list(m.textures),'diffuse':m.diffuse,'normal':m.normal,'parameters':m.getParams()})
 for i,(first,b) in enumerate(getattr(mdl,'_source_blocks',[])):
  p=out/'raw_resources'/f'{mdl.name}_vertexblock_{i}.bin';p.write_bytes(b._source_bytes)
  gv=b.globalVertexData
  meta['vertex_blocks'].append({'first_vertex':first,'vertices':gv.getVertexCnt(),'stride':gv.getVertexStride(),'format':gv.getStorageFormat(),'file':p.name,'sha256':sha(p),'bytes':len(b._source_bytes)})
 data={}
 for i,obj in enumerate(mdl):
  used=sorted({v for f in obj.faces for v in f});remap={v:j for j,v in enumerate(used)}
  node=mdl.skeleton.getNodeByName(obj.name) if mdl.skeleton and not obj.skinned else None
  data[f'positions_{i}']=np.asarray([mdl.getVertex(v,parentBone=node) for v in used],dtype='<f4')
  data[f'uv_{i}']=np.asarray([mdl.getUV(v) for v in used],dtype='<f4')
  data[f'indices_{i}']=np.asarray([[remap[v] for v in f] for f in obj.faces],dtype='<u4')
  data[f'source_vertex_id_{i}']=np.asarray(used,dtype='<u4')
  meta['objects'].append({'name':obj.name,'skinned':obj.skinned,'vertices':len(used),'triangles':len(obj.faces),'material_starts':obj.materials,'material_indices':getattr(obj,'material_ids',{})})
 np.savez_compressed(out/f'{mdl.name}_mesh.npz',**data)
 dump(out/f'{mdl.name}_metadata.json',meta)
 return meta

def source_resources(lib,ref,out):
 entries=[]
 for g,items in lib.grp_entries.items():
  for item in items:
   if (g==ref.grp or item['name'].startswith(ref.name+'_')):
    res=GameResourcePack(str(GAME/g)).getResourceByName(item['name'])
    res.save(str(out/'raw_resources'))
    entries.append({'archive':g,**item,'type':type(res).__name__,'extension':res.fileExtension})
 dump(out/'raw_resources/index.json',entries)
 return entries

def main():
 lib=AssetLibrary(GAME,RUN/'cache');lib.build_index(print)
 dump(RUN/'all_model_resources.json',[{'name':n,'grp':g,'class_id':c} for refs in lib.name_index.values() for n,g,c in refs if c==DYNMODEL_ID])
 summary=[]
 for plane,cfg in SELECTED.items():
  if len(sys.argv)>1 and plane not in sys.argv[1:]:continue
  out=DEST/plane;out.mkdir(parents=True,exist_ok=True);(out/'raw_resources').mkdir(exist_ok=True)
  row={'plane':plane,'configuration':cfg,'errors':[],'runtime_tested':False};summary.append(row)
  print('START',plane,flush=True)
  try:
   g=f'content.hq/pkg_cockpits/res/pkg_cockpits_aircrafts/{plane}.grp'
   refs=[AssetRef(e['name'],g,e['class_id']) for e in lib.grp_entries[g] if e['class_id']==DYNMODEL_ID]
   assert len(refs)==1
   ref=refs[0];row['model']=ref.name
   cfgdata=PARAMS[cfg]
   dump(out/f'configuration/{cfg}.json',cfgdata)
   dump(out/'configuration/cockpit_and_gunner.json',{k:v for k,v in cfgdata.items() if any(s in k.lower() for s in ('cockpit','gunner','turret','weapon','crew'))})
   row['gunner_configuration']=[k for k in cfgdata if 'gunner' in k.lower()]
   row['resources']=source_resources(lib,ref,out)
   mdl=lib._open_model(ref,print)
   meta=metadata(mdl,out);row.update(vertices=meta['vertices'],triangles=meta['triangles'],nodes=len(meta['nodes']),objects=len(meta['objects']),materials=len(meta['materials']))
   lib._load_texture_packs(mdl,print)
   rawtex=out/'raw_textures';rawtex.mkdir(exist_ok=True)
   rawtexindex=[]
   for t in sorted({_clean_tex_name(t) for m in meta['materials'] for t in m['textures'] if t}):
    for j,tex in enumerate(AssetCacher.getCachedAsset(DDSx,t) or []):
     td=rawtex/f'part_{j}';td.mkdir(exist_ok=True);tex.save(str(td))
     rawtexindex.append({'name':t,'part':j,'source':tex.filePath,'output':str(td.relative_to(out)/f'{t}.ddsx')})
   dump(rawtex/'index.json',rawtexindex)
   mdl.exportTextures(str(out),True,forceConvert=False)
   mdl.exportDmf(str(out),exportTexture=False)
   mdl.exportObj(str(out),exportTexture=False)
   glb=export_model_to_gltf(mdl,out,export_textures=True);row['glb']=str(glb)
   from cockpit_animation import decode
   row['animations']=[decode(p,glb) for p in (out/'raw_resources').glob('*.a2d')]
   wanted=sorted({_clean_tex_name(t) for m in meta['materials'] for t in m['textures'] if t})
   row['texture_dependencies']={t:lib.tex_index.get(t,[]) for t in wanted}
   row['missing_dds']=[t for t in wanted if not (out/'textures'/f'{t}.dds').exists()]
   row['source_archives']=[{'file':g,'sha256':sha(GAME/g)}]+[{'file':p,'sha256':sha(GAME/p)} for p in sorted({p for packs in row['texture_dependencies'].values() for p in packs})]
  except Exception as e:
   row['errors'].append(repr(e));traceback.print_exc();raise
  dump(out/'extraction_report.json',row);dump(DEST/'extraction_summary.json',summary)
  print('DONE',plane,json.dumps({k:row.get(k) for k in ('vertices','triangles','missing_dds','errors')}),flush=True)
if __name__=='__main__':main()
