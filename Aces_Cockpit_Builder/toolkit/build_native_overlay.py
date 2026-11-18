import sys,os,json,re,copy,hashlib,struct,tempfile,shutil
from pathlib import Path
import numpy as np
from PIL import Image
import mgm_bos as G, native_helpers as CP, merge_mgm_chunks as MM, native_helpers as AWI
import native_helpers as X, wt_dds as D, cockpit_helpers as CK
from archives import Archives
from runtime_paths import WORK,GAME,BASE,NAME,PACKAGE,SOURCE,REPORT
PAIRS={'f4f_3':'P51B5','f4u_4':'P47D22','sbd_3':'IL2M42','a6m3':'Fw190A5','ki_61':'MC202s8'}
ARCH=Archives(GAME/'data');READS={};A=np.diag([1.,1.,-1.])
REPORT.mkdir(parents=True,exist_ok=True)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,d):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,indent=2,default=lambda x:x.tolist() if hasattr(x,'tolist') else str(x)),encoding='utf-8')
def readbase(rel):
 p=BASE/rel
 if p.exists():READS[str(p)]=sha(p);return p.read_bytes()
 return ARCH.read(rel.removeprefix('data/').lower())
def put(rel,data):p=PACKAGE/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);return p
def world(n):
 v,t=G.node_geometry(n);return (np.c_[v['pos'],np.ones(len(v))]@G.mat(n.offset)@G.world_matrix(n))[:,:3]
def visibility(m,nodes,value):
 ids={n.index for n in nodes}
 for _,an in m.anims:an.tracks=[t for t in an.tracks if not(t.node in ids and t.kind//100==0)]
 for n in nodes:CK.append_track(m,55,n,0,[G.make_key(0,visible=value),G.make_key(1,visible=value)])
def native(slot):return G.read(readbase(f'data/graphics/planes/{slot}/{slot}-C.mgm'))
def template(shader):
 # Exact untouched vanilla material/layout, never a converted WT template.
 path='graphics/planes/p51d15/p51d15-c.mgm'
 model=G.read(ARCH.read(path));matches=[c for c in model.chunks if c.shader==shader and len(c.vertices)]
 assert matches,shader
 c=matches[0];return c,{'archive_resource':path,'shader':c.shader,'stride':c.stride,'u8':c.u8,'colors':c.colors.hex(),'textures':c.textures}
def normal_mips(v,p):
 levels=[];v=v.astype('f4')
 while True:
  v/=np.maximum(np.linalg.norm(v,axis=-1,keepdims=True),1e-12)
  rgb=np.clip(np.rint((v+1)*127.5),0,255).astype('u1');levels.append(np.dstack([rgb,np.full(v.shape[:2],255,'u1')]))
  if v.shape[:2]==(1,1):break
  size=(max(1,v.shape[1]//2),max(1,v.shape[0]//2));v=np.stack([np.asarray(Image.fromarray(v[:,:,i]).resize(size,Image.Resampling.BOX)) for i in range(3)],axis=-1)
 h=[0]*31;h[:7]=[124,0x2100f,levels[0].shape[0],levels[0].shape[1],levels[0].shape[1]*4,0,len(levels)];h[18:26]=[32,0x41,0,32,255,65280,16711680,4278190080];h[26]=0x401008
 p.write_bytes(b'DDS '+struct.pack('<31I',*h)+b''.join(x.tobytes() for x in levels))
def textures(plane,slot,mats,used,bump_tpl):
 out=PACKAGE/f'data/graphics/planes/{slot}/Textures';out.mkdir(parents=True,exist_ok=True);rows={};names={}
 for mi in sorted(used):
  mi=int(mi)
  mat=mats[mi];dif=(mat.get('diffuse') or '').split('*')[0];normal=(mat.get('normal') or '').split('*')[0]
  key=(dif,normal,mat['shader']);name='AOT25_'+plane+'_'+str(mi);names[mi]=name
  cpath=SOURCE/plane/'textures'/f'{dif}.dds';npath=SOURCE/plane/'textures'/f'{normal}.dds'
  if not cpath.exists():
   # Only untextured opaque fittings may reach here; no fabricated cockpit relief.
   rows[mi]={'name':name,'untextured':True};continue
  raw=cpath.read_bytes();rgba=D.decode(raw);gloss=np.full(rgba.shape[:2],.25,dtype='f4')
  if normal and npath.exists():
   vec,g=D.decode_dxt5nm(npath.read_bytes())
   if g.shape!=gloss.shape:g=np.asarray(Image.fromarray(g).resize((rgba.shape[1],rgba.shape[0]),Image.Resampling.BILINEAR))
   gloss=g;normal_mips(vec,out/f'{name}_B.dds')
  else:
   normal_mips(np.array([[[0,0,1]]],dtype='f4'),out/f'{name}_B.dds')
  # Source normal R is relative gloss. Keep it in the measured vanilla cockpit band.
  alpha=np.clip(np.rint(16+gloss*40),16,56).astype('u1')
  if 'masked' in mat['shader'] and 'glass' not in mat['shader']:
   threshold=float(mat.get('parameters',{}).get('atest',127) or 127);alpha[rgba[:,:,3]<threshold]=0
  stats=D.colour_bc3(raw,alpha,out/f'{name}.dds')
  rows[mi]={'name':name,'source_colour':str(cpath),'source_normal':str(npath) if normal else None,'spec_alpha_percentiles':np.percentile(alpha[alpha>0],[5,50,95]).tolist() if np.any(alpha) else [0,0,0],**stats}
 return names,rows
def read_eye(slot):
 rel=f'data/LuaScripts/WorldObjects/planes/{slot}.txt';text=readbase(rel).decode('latin1');block=re.search(r'\[attach=0\](.*?)\[end\]',text,re.S|re.I)[1]
 bot=re.search(r'object\s*=\s*"([^"]+)"',block,re.I)[1];att=np.fromstring(re.search(r'position\s*=([^\r\n]+)',block,re.I)[1],sep=',')
 bt=readbase('data/'+bot).decode('latin1');hb=re.search(r'\[attach=0\](.*?)\[end\]',bt,re.S|re.I)[1];head=np.fromstring(re.search(r'position\s*=([^\r\n]+)',hb,re.I)[1],sep=',')
 return att+head,rel,text,bot,bt,att
def set_eye(slot,eye):
 old,rel,text,bot,bt,att=read_eye(slot);fmt=lambda v:', '.join(f'{x:.6f}' for x in v)
 pattern=r'(\[attach=0\]\s*position\s*=\s*)[^\r\n]+'
 bt,n=re.subn(pattern,lambda m:m[1]+fmt(eye-att),bt,count=1,flags=re.I);assert n
 put('data/'+bot,bt.encode('latin1'))
 text,n=re.subn(r'(GunsightPosition\s*=\s*)[^\r\n]+',lambda m:m[1]+fmt(eye),text,count=1,flags=re.I);assert n
 put(rel,text.encode('latin1'))
 c=readbase(f'data/graphics/planes/{slot}/{slot}-C.txt').decode('latin1')
 c=re.sub(r'(CloseSphere\s*=\s*)[^\r\n]+',lambda m:m[1]+fmt(eye)+', 2.5',c,flags=re.I)
 put(f'data/graphics/planes/{slot}/{slot}-C.txt',c.encode('latin1'))
 return {'old':old,'new':eye,'bot':bot}
def clone_optics(m,source,name,M):
 v,t=G.node_geometry(source);n=G.add_node(m,name,m.root,mesh=(v['pos'],v['nrm'],v['uv'],t),shader=source.shader,textures=source.chunk.textures,colors=source.chunk.colors)
 n.chunk.vertices=v.copy();n.chunk.vertices['slot']=0;n.chunk.stride=n.stride=source.stride;n.chunk.u8=source.chunk.u8
 for k in ['flags','u1','offset','z','w','aux']:setattr(n,k,copy.deepcopy(getattr(source,k)))
 n.local=tuple((G.world_matrix(source)@M@np.linalg.inv(G.world_matrix(m.root))).ravel());return n
def optical_pair(m,plane,slot,centre,source_width,reticle):
 if plane=='sbd_3':
  selected=[n for n in m.nodes() if n.nverts and n.name.startswith('JH24_Aldis_')]
  assert len(selected)>=5;mask=next(n for n in selected if 'Screen_Vizir' in n.name);ret=next(n for n in selected if 'ScreenRings' in n.name)
  c=world(mask).mean(0);axis=world(ret).mean(0)-c;axis/=np.linalg.norm(axis)
  R=CK.rot_between(axis,np.array([1.,0,0]));M=np.eye(4);M[:3,:3]=R;M[3,:3]=centre-c@R
  new=[clone_optics(m,n,'AOT25_'+n.name,M) for n in selected]
  visibility(m,new,1);return new,{'kind':'native Aldis telescope','mask_source':mask.name,'centre':centre.tolist(),'source_dynamic_tele_cards_excluded':True}
 reference=native('Fw190A3');mask=next(n for n in reference.nodes() if n.name=='WT_NATIVE_Type98_Mask');ret=next(n for n in reference.nodes() if n.name=='WT_NATIVE_Type98_Reticle')
 c=world(mask).mean(0);axis=world(ret).mean(0)-c;axis/=np.linalg.norm(axis)
 R=CK.rot_between(axis,np.array([1.,0,0]));M=np.eye(4);M[:3,:3]=R;M[3,:3]=centre-c@R
 near=clone_optics(m,mask,'AOT25_Sight_Mask',M);far=clone_optics(m,ret,'AOT25_Sight_Reticle',M)
 texname=f'AOT25_{plane}_Reticle';p=PACKAGE/f'data/graphics/planes/{slot}/Textures/{texname}.dds'
 rgba=D.decode(SOURCE/plane/'textures'/f'{reticle}.dds');rgba[:,:,3]=rgba[:,:,:3].max(-1)
 with tempfile.TemporaryDirectory(dir=WORK) as temp:p.write_bytes(bytes(D.texconv_bc3(rgba,temp)))
 far.chunk.textures[0]=texname+'.tga';visibility(m,[near,far],1)
 return [near,far],{'kind':'native paired BlendMask','source_reticle':reticle,'centre':centre.tolist(),'background_alpha_max':int(rgba[:,:,:3].max(-1)[rgba[:,:,:3].max(-1)==0].max(initial=0)),'no_opaque_source_collimator_card':True,'stock_pair_payload_retained':True}

EXCLUDE=re.compile(r'^(?:flare|fire|prop|wing|tail|rudder|elevator|aileron|gear|wheel|engine|radiator\d|pylon|bomb|rocket|drop_tank|flap|hook|antenna|gun\d|turret|mgun|Bip|skin$|cloth$|skin_wire|holes|dirt)',re.I)
def build(plane,slot):
 out=SOURCE/plane;meta=json.loads(next(out.glob('*metadata.json')).read_text());z=np.load(next(out.glob('*mesh.npz')));nodes={n['name']:n for n in meta['nodes']};mats=meta['materials'];m=native(slot)
 baseline_chunks=list(m.chunks);baseline_nodes=list(m.nodes());baseline_motion={(a,t.node,t.kind):t.keys.tobytes() for a,an in m.anims for t in an.tracks if t.kind//100!=0}
 # Keep the entire donor as an invisible native resource contract.
 visibility(m,[n for n in baseline_nodes if n.nverts],0)
 optic_name='tele' if plane=='sbd_3' else 'collimator';i=next(i for i,o in enumerate(meta['objects']) if o['name']==optic_name)
 source_c=z[f'positions_{i}'].mean(0)*[1,1,-1]
 if plane=='sbd_3':target_node=next(n for n in baseline_nodes if n.name=='JH24_Aldis_Aldis_Screen_Vizir05')
 elif plane=='a6m3':target_node=next(n for n in baseline_nodes if n.name=='WT_NATIVE_Type98_Mask')
 elif plane=='f4u_4':target_node=next(n for n in baseline_nodes if n.name=='JH24_F4F_Corsair_JH24_US_Sight_Mask')
 else:target_node=next(n for n in baseline_nodes if n.name in ('JH24_US_Sight_Mask','WT_Sight_Mask'))
 centre=world(target_node).mean(0);T=centre-source_c
 cfg=json.loads(next((out/'configuration').glob('*.json')).read_text())
 if 'cockpit' not in cfg:cfg=json.loads((out/'configuration'/json.loads((out/'extraction_report.json').read_text())['configuration']).with_suffix('.json').read_text())
 eye=np.array(cfg['cockpit'].get('headPosVr',cfg['cockpit']['headPos']))*[1,1,-1]+T
 # Sightline goes through the retained native near mask on the aircraft forward axis.
 eye[1:]=centre[1:];eye_rep=set_eye(slot,eye)
 bump_tpl,bump_ref=template('SpecularBump');glass_tpl,glass_ref=template('CanopyGlass');spec_tpl,spec_ref=template('Specular')
 moving_args={a for a,an in m.anims if any(t.kind//100 in (1,2) for t in an.tracks)};clip=X.Clip(out,meta['name'])
 bindings={};unbound=[];eligible=[];used=set();excluded=[]
 for i,obj in enumerate(meta['objects']):
  nm=obj['name']
  if obj['skinned'] or EXCLUDE.match(nm):excluded.append(nm);continue
  if nm in ('fuse','@root'):
   # Main aircraft fuselage is exterior reference; retain only cockpit-specific material sections.
   pass
  mapping={int(k):int(v) for k,v in obj['material_indices'].items()};fm=np.zeros(len(z[f'indices_{i}']),int)
  for first,mi in sorted(mapping.items()):fm[first:]=mi
  sections=[]
  for mi in np.unique(fm):
   mat=mats[mi];shader=mat['shader'];dif=(mat.get('diffuse') or '').split('*')[0]
   if shader in ('collimator','dynamic_tele') or any(s in shader for s in ('crack','fire','decal','null')):continue
   if nm in ('fuse','@root') and not any(s in dif for s in ('cockpit','cabine','seat','gauge','interior')):continue
   if 'glass' in shader:
    if 'gauge_glass' in dif or 'empty_glass' in dif:continue
    sections.append((mi,'glass',fm==mi));continue
   if not dif or not (out/'textures'/f'{dif}.dds').exists():continue
   sections.append((mi,'bump',fm==mi));used.add(mi)
  if not sections:continue
  arg=CK.arg_for(nm,moving_args,{0:0}) if clip.moving(nm) else None
  if arg:bindings[nm]=arg
  elif clip.moving(nm):unbound.append(nm)
  eligible.append((i,obj,sections))
 names,texrep=textures(plane,slot,mats,used,bump_tpl)
 rootW=G.world_matrix(m.root);rootInv=np.linalg.inv(rootW);pivots={};helpers=[]
 def source_origin(nm):return np.asarray(nodes[nm]['world'])[:3,3]*[1,1,-1]+T
 def pivot(nm):
  if nm in pivots:return pivots[nm]
  par=nodes[nm]['parent'];parent=pivot(par) if par in bindings else m.root
  origin=source_origin(nm);at=(np.r_[origin,1]@np.linalg.inv(G.world_matrix(parent)))[:3]
  outer=G.add_node(m,'AOT25_'+CK.safe(nm)+'_T',parent,translation=at);inner=G.add_node(m,'AOT25_'+CK.safe(nm)+'_P',outer);helpers.extend([outer,inner]);pivots[nm]=inner
  arg,rev=bindings[nm];wp=np.array(nodes[par]['world']) if par else np.eye(4);bind=np.array(nodes[nm]['local']);bindworld=np.array(nodes[nm]['world']);baseB=G.world_matrix(outer)[:3,:3].T
  pkeys=[];qkeys=[];last=None
  for phase in np.linspace(0,1,51):
   ls=clip.local(nm,1-phase if rev else phase);rw=wp[:3,:3]@ls[:3,:3]@np.linalg.inv(bind[:3,:3])@np.linalg.inv(wp[:3,:3]);rg=A@rw@A
   rl=np.linalg.inv(baseB)@rg@baseB;u,_,v=np.linalg.svd(rl);rl=u@np.diag([1,1,np.sign(np.linalg.det(u@v))])@v
   q=X.qmat_to_quat(rl.T)
   if last is not None and q@last<0:q=-q
   last=q
   dg=A@((wp@ls)[:3,3]-bindworld[:3,3]);local=dg@np.linalg.inv(G.world_matrix(parent)[:3,:3])
   pkeys.append(G.make_key(float(phase),pos=local));qkeys.append(G.make_key(float(phase),rot=q))
  CK.append_track(m,arg,outer,100,pkeys);CK.append_track(m,arg,inner,200,qkeys)
  return inner
 guest=[];parts=[]
 for i,obj,sections in eligible:
  nm=obj['name'];owner=nm
  while owner and owner not in bindings:owner=nodes.get(owner,{}).get('parent')
  parent=pivot(owner) if owner else m.root;W=G.world_matrix(parent);invW=np.linalg.inv(W)
  P=z[f'positions_{i}'].astype(float)*[1,1,-1]+T;UV=z[f'uv_{i}'].copy();UV[:,1]=1-UV[:,1];tri=z[f'indices_{i}'].astype('i8')
  if f'local_normals_{i}' not in z:excluded.append(nm+': undecoded normals');continue
  N=z[f'local_normals_{i}'].astype(float)
  if nm in nodes:N=N@np.linalg.inv(np.array(nodes[nm]['world'])[:3,:3])
  N=N*[1,1,-1];N/=np.maximum(np.linalg.norm(N,axis=1,keepdims=True),1e-12)
  for mi,role,mask in sections:
   selected=np.flatnonzero(mask)
   for start in range(0,len(selected),18000):
    tt=tri[selected[start:start+18000]];ids,ii=np.unique(tt,return_inverse=True);tt=ii.reshape(-1,3)
    p=(np.c_[P[ids],np.ones(len(ids))]@invW)[:,:3];n=N[ids]@W[:3,:3].T;n/=np.maximum(np.linalg.norm(n,axis=1,keepdims=True),1e-12)
    fn=np.cross(p[tt[:,1]]-p[tt[:,0]],p[tt[:,2]]-p[tt[:,0]])
    if np.mean(np.sum(fn*n[tt[:,0]],axis=1))>0:tt=tt[:,[0,2,1]]
    tpl=glass_tpl if role=='glass' else bump_tpl;name=names.get(mi,'AOT25_glass')
    tex=[name+'.tga',name+'_B.tga','white.bmp','white.bmp'] if role=='bump' else list(glass_tpl.textures)
    node=G.add_node(m,f'AOT25_{CK.safe(nm)}_M{mi}_{start//18000}',parent,mesh=(p,n,UV[ids],tt),textures=tex,colors=tpl.colors)
    c=node.chunk;old=c.vertices;new=np.zeros(len(old),G.vertex_dtype(tpl.stride,tpl.shader))
    for f in ('pos','nrm','uv','slot'):new[f]=old[f]
    tg,bg=CP.uv_tangents(old,c.indices);new['pk0']=CP.pack(tg)
    if 'pk1' in new.dtype.names:new['pk1']=CP.pack(bg)
    c.vertices=new;c.stride=node.stride=tpl.stride;c.shader=node.shader=tpl.shader;c.u8=tpl.u8
    for f in ['flags','u1']:setattr(node,f,copy.deepcopy(getattr(tpl.bones[0],f)))
    pw=world(node);node.bbox=tuple(pw.max(0))+tuple(pw.min(0));guest.append(c);parts.append({'object':nm,'material':mi,'triangles':len(tt),'node':node.name,'role':role})
 optical,opticrep=optical_pair(m,plane,slot,centre,float(np.ptp(z[f'positions_{i}'],axis=0).max()),(mats[meta['objects'][next(j for j,o in enumerate(meta['objects']) if o['name']==optic_name)]['material_indices']['0']]['diffuse'] or '').split('*')[0])
 # Repack only new draws; preserve optical pass ordering and all original donor buffers.
 groups={}
 for c in guest:groups.setdefault((c.shader,c.stride,c.u8,tuple(c.textures),c.colors),[]).append(c)
 newchunks=[]
 for _,cs in groups.items():
  owners=[c.bones[0] for c in cs]
  for k in range(0,len(owners),64):newchunks.append(MM._build(cs,owners[k:k+64]))
 # add_node placed helpers in a shared helper palette; split its new owners away from stock.
 for c in baseline_chunks:
  c.bones=[n for n in c.bones if n not in helpers]
  for s,n in enumerate(c.bones):n.slot=s
 hchunks=[]
 for k in range(0,len(helpers),64):
  hc=G.Chunk(shader='Specular',colors=bytes(16),textures=[],stride=36,vertices=np.zeros(0,G.vertex_dtype(36,'Specular')),indices=np.zeros(0,dtype='<u2'))
  hc.bones=helpers[k:k+64]
  for s,n in enumerate(hc.bones):n.chunk=hc;n.slot=s
  hchunks.append(hc)
 m.chunks=baseline_chunks+hchunks+[n.chunk for n in optical if n.shader=='BlendMask']+[c for c in newchunks if c.shader!='CanopyGlass']+[c for c in newchunks if c.shader=='CanopyGlass']+[n.chunk for n in optical if n.shader!='BlendMask']
 AWI.reindex(m);m.anims=[(a,an) for a,an in m.anims if an.tracks];m.anims.sort(key=lambda x:x[0])
 for _,an in m.anims:an.tracks.sort(key=lambda t:t.node)
 for c in m.chunks:
  c.bone_map=[(n.index,s) for s,n in enumerate(c.bones)]
  assert len(c.bones)<=64
 raw=G.to_bytes(m);p=put(f'data/graphics/planes/{slot}/{slot}-C.mgm',raw);back=G.read(p);assert G.to_bytes(back)==raw
 report={'plane':plane,'slot':slot,'source_model':meta['name'],'placement_translation':T,'eye':eye_rep,'optics':opticrep,'vanilla_templates':{'bump':bump_ref,'glass':glass_ref},'parts':parts,'bindings':bindings,'unbound_moving':unbound,'excluded':excluded,'textures':texrep,'triangles':sum(x['triangles'] for x in parts),'native_file':str(p),'runtime_tested':False,'limitations':['Source variants differ from existing F4F-4, F4U-1D and Ki-61 Ko identities. Host exterior, FM and systems remain inherited.','Gauge physical calibration, damage/night lighting and skin animation need runtime acceptance.']}
 dump(REPORT/f'{plane}.json',report);print('BUILT',plane,slot,report['triangles'],'tris',len(bindings),'animated objects',flush=True)
 return report
def main():
 PACKAGE.mkdir(parents=True,exist_ok=True);reports=[]
 for p,s in PAIRS.items():
  if len(sys.argv)>1 and p not in sys.argv[1:]:continue
  reports.append(build(p,s))
 dump(REPORT/'inputs.json',READS);dump(REPORT/'build.json',reports)
if __name__=='__main__':main()
