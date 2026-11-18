"""Fit the authored alpha-only telescope reticle to the native paired pass.
The telescope FOV/magnification remains a user-runtime acceptance item.
"""
import build_native_overlay as B
import json,tempfile
plane='sbd_3';slot='IL2M42';path=B.PACKAGE/f'data/graphics/planes/{slot}/{slot}-C.mgm'
m=B.G.read(path);r=json.loads((B.REPORT/f'{plane}.json').read_text())
mask=next(n for n in m.nodes() if n.name.startswith('AOT25_JH24') and 'Screen_Vizir' in n.name)
old=next(n for n in m.nodes() if n.name.startswith('AOT25_JH24') and 'ScreenRings' in n.name)
donor=B.native('Fw190A3');ref=next(n for n in donor.nodes() if n.name=='WT_NATIVE_Type98_Reticle')
cfg=json.loads((B.SOURCE/plane/'configuration/sbd-3.json').read_text())
def find(d,k):
 if isinstance(d,dict):
  if k in d:return d[k]
  for v in d.values():
   x=find(v,k)
   if x is not None:return x
scale=find(cfg,'teleReticleTexScale');centre=B.world(mask).mean(0);eye=B.np.array(r['eye']['new'])
aperture=float(B.np.ptp(B.world(mask),axis=0)[1:3].min());eye_distance=float(centre[0]-eye[0]);far_distance=150.
width=aperture/eye_distance*far_distance*scale
p=B.world(ref);c=p.mean(0);span=B.np.ptp(p,axis=0);R=B.CK.rot_between((c-B.world(next(n for n in donor.nodes() if n.name=='WT_NATIVE_Type98_Mask')).mean(0))/B.np.linalg.norm(c-B.world(next(n for n in donor.nodes() if n.name=='WT_NATIVE_Type98_Mask')).mean(0)),B.np.array([1.,0,0]))
M=B.np.eye(4);M[:3,:3]=R*(width/max(span));target=eye+B.np.array([far_distance,0,0]);M[3,:3]=target-c@M[:3,:3]
new=next((n for n in m.nodes() if n.name=='AOT25_Telescope_Reticle'),None)
if new is None:new=B.clone_optics(m,ref,'AOT25_Telescope_Reticle',M)
rgba=B.D.decode(B.SOURCE/plane/'textures/telesight_us.dds');alpha=rgba[:,:,3].copy()
assert alpha.max()>0 and alpha.min()==0 and rgba[:,:,:3].max()==0
rgba[:,:,:3]=255;rgba[:,:,3]=alpha
tex='AOT25_sbd_3_TelescopeReticle';dest=B.PACKAGE/f'data/graphics/planes/{slot}/Textures/{tex}.dds'
with tempfile.TemporaryDirectory(dir=B.WORK) as tmp:dest.write_bytes(bytes(B.D.texconv_bc3(rgba,tmp)))
new.chunk.textures[0]=tex+'.tga';B.visibility(m,[old],0);B.visibility(m,[new],1)
m.chunks.remove(new.chunk);m.chunks.insert(m.chunks.index(mask.chunk)+1,new.chunk)
B.AWI.reindex(m)
for ch in m.chunks:ch.bone_map=[(n.index,s) for s,n in enumerate(ch.bones)]
raw=B.G.to_bytes(m);assert B.G.to_bytes(B.G.read(raw))==raw;path.write_bytes(raw)
r['optics'].update(source_reticle='telesight_us alpha channel',source_alpha_preserved=True,reticle_texture_scale=scale,near_aperture_m=aperture,eye_to_aperture_m=eye_distance,virtual_distance_m=far_distance,far_quad_width_m=width,opaque_black_source_rgb_replaced_by_white_with_authored_alpha=True,original_aldis_ring_geometry_hidden=True,angular_calibration_and_magnification_runtime_pending=True)
# Keep the established native rear turret/crew/camera together. The AoT camera
# would require a 0.693m head-only displacement, which is not a crew integration.
from inspect_sbd_gunner_contract import inspect_contract
r['gunner_view']=inspect_contract()
B.dump(B.REPORT/'sbd_3.json',r);print('SBD_RETICLE',width,'m; authored alpha preserved; rear native camera retained',flush=True)
