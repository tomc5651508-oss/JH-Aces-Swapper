"""Build from locally installed, owned inputs. Never mount or write live game data."""
import argparse,datetime,hashlib,json,os,runpy,shutil,subprocess,sys,traceback,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parent
PAIRS={'f4f_3':'P51B5','f4u_4':'P47D22','sbd_3':'IL2M42','a6m3':'Fw190A5','ki_61':'MC202s8'}
# Kept after a successful build unless keep_source is set: reports only, no Gaijin-derived data.
KEEP_PLANE_FILES={'extraction_report.json','texture_validation.json','gunner_positions'}
EXTRACTED_SUFFIXES=('.dds','.ddsx','.glb','.obj','.dmf','.mtl','.npz','.bin','.png','.a2d','.mgm','.tga')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def inside(p,root):return p==root or root in p.parents
def preflight(cfg):
 aot,il2,base,out=[Path(cfg[k]).resolve() for k in ['aot','il2','base','output']]
 # Install check only; the archive is not unpacked (values come from aces_cockpit_params.json).
 if not (aot/'aces.vromfs.bin').is_file():raise ValueError('Select the Aces of Thunder install containing aces.vromfs.bin.')
 if not any((il2/'data').glob('*.gtp')):raise ValueError('Select an IL-2 Great Battles install with stock data/*.gtp archives.')
 for p,s in PAIRS.items():
  if not (aot/f'content.hq/pkg_cockpits/res/pkg_cockpits_aircrafts/{p}.grp').exists():raise ValueError('Missing Aces high-quality cockpit pack: '+p+'.grp. Install that game content first.')
  if not (base/f'data/graphics/planes/{s}/{s}-C.mgm').is_file():raise ValueError('JH 2.5 WT base is missing the cockpit slot '+s)
 if out.exists():raise ValueError('Output already exists. Choose a new folder; the builder never overwrites an existing mod.')
 if inside(out,aot) or inside(out,base):raise ValueError('Output must be separate from the source game and JH base.')
 if inside(out,il2) and out.parent!=il2/'MODS':raise ValueError('Inside IL-2, output must be a NEW direct child folder under MODS.')
 if inside(out,ROOT.parent):raise ValueError('Output must be separate from this builder folder.')
 if out.name.startswith('!'):raise ValueError('Do not use a JSGME backup/control folder as output.')
 expected=json.loads((ROOT/'baseline_compatibility.json').read_text())
 for rel,want in expected.items():
  p=base/rel
  choices=want if isinstance(want,list) else [want]
  if not p.is_file() or sha(p) not in choices:raise ValueError('This base differs from the tested JH 2.5 WT native donor: '+rel+'. Select a supported JH 2.5 WT base (WT, WT 18 to WT 25), not the Aces overlay.')
 return aot,il2,base,out
def clean_scratch(work,package):
 # Delete the extracted Gaijin source material and the scratch copy of the package; keep reports.
 removed=0
 def rm(p):
  nonlocal removed
  if p.is_dir():removed+=sum(f.stat().st_size for f in p.rglob('*') if f.is_file());shutil.rmtree(p)
  elif p.is_file():removed+=p.stat().st_size;p.unlink()
 for name in ('cache','configuration'):rm(work/name)
 rm(package)
 cockpits=work/'cockpits'
 if cockpits.is_dir():
  for plane in [d for d in cockpits.iterdir() if d.is_dir()]:
   for item in list(plane.iterdir()):
    if item.name not in KEEP_PLANE_FILES:rm(item)
 left=[p for p in work.rglob('*') if p.is_file() and p.suffix.lower() in EXTRACTED_SUFFIXES]
 assert not left,'Scratch cleanup left extracted data: '+str(left[0])
 return removed
def run(script,*args):
 print('\n--- '+script+' ---',flush=True);subprocess.run([sys.executable,str(ROOT/script),*map(str,args)],check=True,env=os.environ.copy())
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--config',type=Path,required=True);ap.add_argument('--preflight',action='store_true');ap.add_argument('--skip-downloads',action='store_true',help=argparse.SUPPRESS);ap.add_argument('--finish-existing',action='store_true',help=argparse.SUPPRESS);a=ap.parse_args()
 cfg=json.loads(a.config.read_text(encoding='utf-8-sig'));aot,il2,base,out=preflight(cfg);print('Input checks passed.',flush=True)
 if a.preflight:return
 if not a.skip_downloads:
  from tools_setup import setup;setup()
 work=Path(cfg.get('work') or ROOT.parent/'.work'/('build_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])).resolve()
 if any(inside(work,p) for p in [aot,il2,base]):raise ValueError('Scratch work must be outside both games and the JH base. Move the builder to a separate writable folder.')
 work.mkdir(parents=True,exist_ok=a.finish_existing)
 cfg.update(work=str(work),aot=str(aot),il2=str(il2),base=str(base),output=str(out));job=work/'build-config.json';job.write_text(json.dumps(cfg,indent=2),encoding='utf-8');os.environ['AOT_BUILD_CONFIG']=str(job);os.environ['PYTHONUNBUFFERED']='1'
 from runtime_paths import TOOLS,PACKAGE,REPORT,SOURCE
 REPORT.mkdir(parents=True,exist_ok=True)
 def protection():
  files=[il2/'MODS/JSGME.ini',il2/'JSGME.ini']
  for n in ['scriptcrc.dll','scriptcrc_planes.dll','scriptcrc.ini','winmm.dll']:
   files.append(il2/n)
   if (il2/'bin').exists():files.extend((il2/'bin').rglob(n))
  return {str(p):sha(p) if p.is_file() else None for p in files}
 protected=protection();basehash={str(p.relative_to(base)):sha(p) for p in base.rglob('*-C.mgm')}
 if not a.finish_existing:
  run('extract_cockpits.py',*PAIRS);run('finish_assets.py');run('repair_texture_containers.py')
  run('build_native_overlay.py');run('match_overlay_materials.py');run('finish_native_overlay.py');run('fit_sbd_native_reticle.py');run('fix_native_glass.py')
 else:
  if not all((REPORT/(p+'.json')).is_file() for p in PAIRS):raise ValueError('A complete prior native build is required for finish-existing.')
 from resource_budget import constrain,LIMIT
 run('verify_selected_base.py')
 if not (a.finish_existing and (REPORT/'resource_budget.json').exists()):constrain(PACKAGE,TOOLS/'texconv.exe',REPORT/'resource_budget.json')
 suffix='_rechecked_'+uuid.uuid4().hex[:8] if a.finish_existing else ''
 run('inspect_mgm.py',PACKAGE,'--report',REPORT/('models'+suffix+'.json'))
 run('audit_dds.py',PACKAGE,'--d3d','--report',REPORT/('dds'+suffix+'.json'))
 deps=json.loads((REPORT/'inputs.json').read_text())
 assert all(Path(p).is_file() and sha(Path(p))==h for p,h in deps.items()),'Base changed during build'
 assert all(sha(base/p)==h for p,h in basehash.items()),'Base cockpit changed during build'
 if protected!=protection():print('Activation/protected-file state changed externally during this build. The builder does not mount mods or write those files.',flush=True)
 assert all(p.stat().st_size<=LIMIT for p in PACKAGE.rglob('*.dds'))
 readme=(ROOT.parent/'MOD_README.txt').read_text(encoding='utf-8');(PACKAGE/'README.txt').write_text(readme,encoding='utf-8')
 shutil.copyfile(ROOT.parent/'NOTICE.txt',PACKAGE/'NOTICE.txt')
 manifest=[{'file':p.relative_to(PACKAGE).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(PACKAGE.rglob('*')) if p.is_file() and p.name not in ('PACKAGE_SHA256.json','BUILD_RESULT.json')]
 (PACKAGE/'PACKAGE_SHA256.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
 # Only publish after the entire build validates; an existing destination is refused.
 assert not out.exists();shutil.copytree(PACKAGE,out,copy_function=shutil.copyfile)
 for row in manifest:assert sha(out/row['file'])==row['sha256'],row['file']
 evidence={'output':str(out),'source_install':str(aot),'base':str(base),'scratch_and_extraction':str(work),'activated':False,'resource_limit_bytes':LIMIT,'dds_count':len(list(out.rglob('*.dds'))),'mgm_count':len(list(out.rglob('*.mgm'))),'protected_unchanged':protected==protection(),'source_files_modified':False,'source_config_sha256':sha(aot/'aces.vromfs.bin'),'aces_vromfs_unpacked':False,'glass_constants':'vanilla P51D15 CanopyGlass (TEST 4 fix)','runtime_acceptance':'Static checks only; in-game flight acceptance pending.'}
 (out/'BUILD_RESULT.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
 if cfg.get('keep_source'):evidence['scratch_cleanup']='skipped: keep_source set'
 else:evidence['scratch_cleanup']={'removed_bytes':clean_scratch(work,PACKAGE),'kept':'reports, build-config.json, BUILD_RESULT.json'}
 (work/'BUILD_RESULT.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
 print('\nBUILD COMPLETE — inactive mod created:\n'+str(out)+'\nReports: '+str(work)+('' if cfg.get('keep_source') else ' (extracted source files deleted)')+'\nDisable earlier Aces overlays, then enable this mod after the selected JH 2.5 WT base manually.',flush=True)
if __name__=='__main__':
 try:main()
 except Exception as e:traceback.print_exc();print('\nBUILD FAILED: '+str(e),flush=True);sys.exit(1)
