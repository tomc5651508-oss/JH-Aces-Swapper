import build_native_overlay as B
import slots as S
import json,copy
from pathlib import Path
import numpy as np
rows=[]
def resolve(slot,name):
 stem=Path(name).stem
 for base in (B.PACKAGE,B.BASE):
  for ext in ('.dds','.tga','.bmp'):
   p=base/f'data/graphics/planes/{slot}/Textures/{stem}{ext}'
   if p.exists():return str(p),p.read_bytes()
 for key in (f'graphics/planes/{slot.lower()}/textures/{stem.lower()}.dds',f'graphics/textures/common/{stem.lower()}.dds'):
  if key in B.ARCH.files:return key,B.ARCH.read(key)
 hits=[k for k in B.ARCH.files if k.endswith('/'+stem.lower()+'.dds')]
 if hits:return hits[0],B.ARCH.read(hits[0])
 return None,None
for plane,slot in B.PAIRS.items():
 path=B.PACKAGE/f'data/graphics/planes/{slot}/{slot}-C.mgm';m=B.G.read(path);copied=[]
 for c in m.chunks:
  if not any(n.name.startswith('AOT25_') for n in c.bones):continue
  for t in c.textures:
   if not t or t.lower() in ('white.bmp','normal.bmp'):continue
   source,raw=resolve(slot,t);assert raw is not None,(slot,t)
   local=B.PACKAGE/f'data/graphics/planes/{slot}/Textures/{Path(t).stem}.dds'
   base=B.BASE/f'data/graphics/planes/{slot}/Textures/{Path(t).stem}.dds'
   if not local.exists() and not base.exists():local.parent.mkdir(parents=True,exist_ok=True);local.write_bytes(raw);copied.append({'texture':t,'source':source})
 rows.append({'plane':plane,'vanilla_texture_dependencies_copied':copied})

# The rest of the WT base may carry the same baked source collimator proxy alongside a native pair.
# Hide only confirmed WT collimator cards; leave physical sight housings and all native optical passes intact.
other=[]
for p in (B.BASE/'data/graphics/planes').glob('*/*-C.mgm'):
 if p.parent.name in B.PAIRS.values() or p.parent.name in S.REFLECTOR_EXCLUDE:continue
 if not S.REFLECTOR_AUTO and p.parent.name.lower() not in {s.lower() for s in S.REFLECTOR_ONLY}:continue
 m=B.G.read(p);cards=[n for n in m.nodes() if n.nverts and n.name.lower().startswith('wt_collimator') and n.shader!='BlendMask']
 if not cards:continue
 B.visibility(m,cards,0);raw=B.G.to_bytes(m);assert B.G.to_bytes(B.G.read(raw))==raw
 B.put(p.relative_to(B.BASE).as_posix(),raw)
 other.append({'slot':p.parent.name,'hidden_opaque_wt_proxy_nodes':[n.name for n in cards],'native_optical_passes_preserved':True})
if not S.REFLECTOR_AUTO:
 # List mode: every listed slot must still hold a WT collimator card, or the slot map is stale for this base.
 missing=sorted({s.lower() for s in S.REFLECTOR_ONLY}-{r['slot'].lower() for r in other})
 assert not missing,'reflector_hide slots without a WT collimator card in this base: '+', '.join(missing)
B.dump(B.REPORT/'optical_dependencies_and_other_reflectors.json',{'new_cockpits':rows,'other_reflector_fixes':other})
print('DEPENDENCIES',sum(len(r['vanilla_texture_dependencies_copied']) for r in rows),'OTHER_REFLECTORS',len(other),flush=True)
