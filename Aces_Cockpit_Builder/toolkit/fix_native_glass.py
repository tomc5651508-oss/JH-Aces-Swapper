"""Repair atlas-role mismatch, preserving host meshes and non-glass material data."""
import build_native_overlay as B
import json,re
from slots import GLASS as US
rows=[]
for plane,(slot,tex) in US.items():
 donor=B.native(slot)
 reference=next(c for c in donor.chunks if c.shader=='CanopyGlass' and c.stride==40 and any(n.name.startswith('WT_') for n in c.bones) and c.textures and B.Path(c.textures[0]).stem.lower()==tex.lower())
 path=B.PACKAGE/f'data/graphics/planes/{slot}/{slot}-C.mgm';m=B.G.read(path);changed=[]
 original=[(c.vertices.tobytes(),c.indices.tobytes()) for c in m.chunks]
 original_motion=[(a,t.node,t.kind,t.keys.tobytes()) for a,an in m.anims for t in an.tracks]
 for c in m.chunks:
  if c.shader!='CanopyGlass' or not any(n.name.startswith('AOT25_') and not n.name.startswith('AOT25_JH24_') for n in c.bones):continue
  if not c.textures or B.Path(c.textures[0]).stem.lower() not in ('p51d15na_g',tex.lower()):continue
  assert all(n.name.startswith('AOT25_') for n in c.bones)
  before={'colors':c.colors.hex(),'textures':list(c.textures),'u8':c.u8}
  # TEST 4: keep the chunk's own vanilla P-51D CanopyGlass constants (template in build_native_overlay);
  # the WT constants gave tinted, lensing glass. Only the uniform glass texture and u8 come from the reference.
  c.textures=list(reference.textures);c.u8=reference.u8
  # Same native layout; no UV remapping, new vertex data or visibility changes.
  changed.append({'nodes':[n.name for n in c.bones],'before':before,'after':{'colors':c.colors.hex(),'textures':list(c.textures),'u8':c.u8}})
 assert changed,(plane,'No introduced glass chunk found')
 assert original==[(c.vertices.tobytes(),c.indices.tobytes()) for c in m.chunks]
 assert original_motion==[(a,t.node,t.kind,t.keys.tobytes()) for a,an in m.anims for t in an.tracks]
 raw=B.G.to_bytes(m);assert B.G.to_bytes(B.G.read(raw))==raw;path.write_bytes(raw)
 rpath=B.REPORT/f'{plane}.json';r=json.loads(rpath.read_text());r['glass_fix']={'native_reference_slot':slot,'atlas':tex,'original_stock_P51_window_atlas_removed':True,'vanilla_p51d15_glass_constants_kept':True,'vertex_index_and_animation_buffers_unchanged':True,'changes':changed};B.dump(rpath,r)
 rows.append({'plane':plane,'slot':slot,'changes':changed,'native_reference_base':str(B.BASE)})
# Retain every current base edit in the aircraft scripts, including WT 19 loadouts.
merges=[]
for plane,slot in B.PAIRS.items():
 rel=f'data/LuaScripts/WorldObjects/planes/{slot}.txt';source=B.readbase(rel);p=B.PACKAGE/rel;overlay=p.read_bytes();pattern=rb'(?im)^(GunsightPosition\s*=\s*)[^\r\n]+'
 line=re.search(pattern,overlay);assert line,(plane,'No sight position')
 merged,n=re.subn(pattern,lambda m:m[1]+line[0].split(b'=',1)[1].strip(),source,count=1);assert n==1
 assert re.sub(pattern,b'GunsightPosition=<view>',source)==re.sub(pattern,b'GunsightPosition=<view>',merged)
 p.write_bytes(merged);merges.append({'plane':plane,'slot':slot,'base_script_sha256':B.hashlib.sha256(source).hexdigest(),'merged_script_sha256':B.hashlib.sha256(merged).hexdigest(),'only_gunsight_position_changed_from_selected_base':True})
B.dump(B.REPORT/'glass_and_base_preservation.json',{'glass':rows,'plane_script_merges':merges,'exterior_meshes_written':False,'runtime_tested':False})
print('GLASS_FIXED',len(rows),'AIRCRAFT; BASE SCRIPTS PRESERVED',len(merges),flush=True)
