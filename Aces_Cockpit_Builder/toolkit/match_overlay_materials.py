"""Use Claude's measured vanilla alpha distributions on the new cockpit atlases."""
import build_native_overlay as B
import sys,types,json
from pathlib import Path
import numpy as np
from PIL import ImageFile
import material_helpers as F
F._pool=json.loads((Path(__file__).parent/'material_targets.json').read_text())
for v in F._pool.values():v['spec_q']=np.array(v['spec_q'])
F.pooled=lambda role:F._pool[role]
F.GAUGE=__import__('re').compile(r'gauge|pribor|instrument|label|tablic|tabli4|notes|instr',__import__('re').I)
ImageFile.LOAD_TRUNCATED_IMAGES=False
rows=[]
for plane,slot in B.PAIRS.items():
 report=json.loads((B.REPORT/f'{plane}.json').read_text());m=B.G.read(B.PACKAGE/f'data/graphics/planes/{slot}/{slot}-C.mgm')
 materials=json.loads(next((B.SOURCE/plane).glob('*metadata.json')).read_text())['materials']
 for key,item in report['textures'].items():
  mi=int(key);mat=materials[mi]
  if item.get('untextured'):continue
  p=B.PACKAGE/f'data/graphics/planes/{slot}/Textures/{item["name"]}.dds';raw=p.read_bytes();image=B.D.decode(raw);h,w=image.shape[:2]
  normal=item.get('source_normal');n=B.D.decode(normal) if normal and Path(normal).exists() else None
  role='gauge' if F.GAUGE.search(mat.get('diffuse') or '') else 'cockpit';target=F.pooled(role)
  score=.65*n[:,:,0].astype('f4')+.35*n[:,:,2].astype('f4') if n is not None else image[:,:,:3].mean(-1)
  if score.shape!=(h,w):score=F.cv2.resize(score,(w,h),interpolation=F.cv2.INTER_LINEAR)
  cov=F.coverage([m],item['name'].lower(),(w,h));alpha=F.rank_map(score,cov,target['spec_q']);holes=image[:,:,3]<8;alpha[holes]=0
  patched=F.replace_alpha_dxt5(raw,alpha);p.write_bytes(patched);check=B.D.decode(patched)
  assert np.array_equal(image[:,:,:3],check[:,:,:3]),p
  stat={'plane':plane,'file':p.name,'role':role,'source_gloss_and_metal_used':n is not None,'before':np.percentile(image[:,:,3][cov],[5,50,95]).tolist(),
        'after':np.percentile(check[:,:,3][cov],[5,50,95]).tolist(),'stock_target':target['spec_q'][[5,50,95]].tolist(),'stock_host_count':target['n'],'rgb_unchanged':True}
  rows.append(stat);item['vanilla_match']=stat
 report['material_matching']='Exact vanilla shader/stride/u8/color block; authored normals; WT gloss+metal ranked into measured vanilla cockpit/gauge alpha distributions.'
 B.dump(B.REPORT/f'{plane}.json',report);print('VANILLA_MATCH',plane,flush=True)
B.dump(B.REPORT/'vanilla_cockpit_material_match.json',{'results':rows,'target_distributions':F._pool,'claude_source':'work/jh250_wt4_mats/tools/fix4.py; pure measurement/mapping functions reused; no base writes'})
