"""Ensure this overlay preserves the selected base's native cockpit contracts."""
import build_native_overlay as B
import re,json
def paths(m):
 p={}
 def walk(n,parent,occurrence):
  here=parent+'/'+n.name+'#'+str(occurrence);p[n.index]=here;counts={}
  for c in n.children:
   k=counts.get(c.name,0);counts[c.name]=k+1;walk(c,here,k)
 walk(m.root,'',0);return p
def motion(m):
 p=paths(m);return {(a,p[t.node],t.kind):t.keys.tobytes() for a,an in m.anims for t in an.tracks if t.kind//100!=0}
rows=[]
for f in B.PACKAGE.rglob('*.mgm'):
 assert f.name.lower().endswith('-c.mgm'),'Exterior mesh overrides are forbidden'
 old=B.G.read(B.readbase(f.relative_to(B.PACKAGE).as_posix()));new=B.G.read(f)
 assert motion(old).items()<=motion(new).items()
 pn=paths(new);newnodes={pn[n.index]:n for n in new.nodes()};po=paths(old)
 for n in old.nodes():
  other=newnodes[po[n.index]];assert n.local==other.local and n.offset==other.offset,(f.name,n.name,n.index,'native transform differs')
 for i,c in enumerate(old.chunks):
  d=new.chunks[i];assert (c.shader,c.stride,c.u8,c.colors,c.textures,c.vertices.tobytes(),c.indices.tobytes())==(d.shader,d.stride,d.u8,d.colors,d.textures,d.vertices.tobytes(),d.indices.tobytes())
 rows.append({'slot':f.parent.name,'native_buffers_materials_transforms_and_motion_preserved':True})
pattern=rb'(?im)^(GunsightPosition\s*=\s*)[^\r\n]+'
for plane,slot in B.PAIRS.items():
 rel=f'data/LuaScripts/WorldObjects/planes/{slot}.txt';a=B.readbase(rel);b=(B.PACKAGE/rel).read_bytes()
 assert re.sub(pattern,b'GunsightPosition=<view>',a)==re.sub(pattern,b'GunsightPosition=<view>',b)
B.dump(B.REPORT/'selected_base_preservation.json',{'base':str(B.BASE),'models':rows,'all_plane_script_fields_except_sight_position_preserved':True,'exterior_overrides':False})
print('SELECTED BASE PRESERVED',len(rows),'COCKPIT CONTRACTS; NO EXTERIOR OVERRIDES',flush=True)
