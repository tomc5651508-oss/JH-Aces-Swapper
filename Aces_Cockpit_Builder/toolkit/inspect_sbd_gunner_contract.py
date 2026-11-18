"""Read-only comparison of source rear eye and native crew attachments."""
import build_native_overlay as B
import json,re
from slots import TELESCOPES
def inspect_contract():
 T0=TELESCOPES[0];out=B.SOURCE/T0['plane'];meta=json.loads(next(out.glob('*metadata.json')).read_text());cfg=json.loads((out/'configuration'/(T0['config']+'.json')).read_text());report=json.loads((B.REPORT/(T0['plane']+'.json')).read_text())
 node=next(n for n in meta['nodes'] if n['name']==cfg['gunnerFps']['head']);src=(B.np.array(node['world'])@B.np.r_[cfg['gunnerFps']['pos'],1])[:3]
 desired=src*[1,1,-1]+B.np.array(report['placement_translation'])
 plane=B.readbase(f"data/LuaScripts/WorldObjects/planes/{T0['slot']}.txt").decode('latin1');blk=re.search(r'\[attach=1\](.*?)\[end\]',plane,re.S|re.I)[1]
 pos=B.np.fromstring(re.search(r'position\s*=([^\r\n]+)',blk,re.I)[1],sep=',');angle=B.np.fromstring(re.search(r'rotation\s*=([^\r\n]+)',blk,re.I)[1],sep=',')[1];a=B.np.radians(angle);c,s=B.np.cos(a),B.np.sin(a);R=B.np.array([[c,0,s],[0,1,0],[-s,0,c]])
 turret=B.readbase(T0['gunner_turret_script']).decode('latin1');block=re.search(r'\[attach=0\](.*?)\[end\]',turret,re.S|re.I)[1]
 seat=B.np.fromstring(re.search(r'position\s*=([^\r\n]+)',block,re.I)[1],sep=',');bot=re.search(r'object\s*=\s*"([^"]+)"',block)[1];bt=B.readbase('data/'+bot).decode('latin1');headblock=re.search(r'\[attach=0\](.*?)\[end\]',bt,re.S|re.I)[1];oldhead=B.np.fromstring(re.search(r'position\s*=([^\r\n]+)',headblock,re.I)[1],sep=',')
 newhead=(desired-pos)@B.np.linalg.inv(R)-seat;old=(seat+oldhead)@R+pos
 return {'old_eye':old.tolist(),'new_eye':old.tolist(),'attachment_position':pos.tolist(),'attachment_rotation_matrix':R.tolist(),'original_turret_crew_and_fire_contract_retained':True,'gunner_models_retained_from_current_base':True,'source_eye_candidate':desired.tolist(),'source_head_only_displacement_m':float(B.np.linalg.norm(newhead-oldhead)),'source_camera_conversion':'deferred: preserve native crew/camera attachment together'}
if __name__=='__main__':print(json.dumps(inspect_contract(),indent=2))
