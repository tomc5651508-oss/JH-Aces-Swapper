"""Fetch pinned open-source tools; no game asset files are bundled."""
import hashlib,json,shutil,subprocess,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];TOOLS=ROOT/'.tools/bin'
DOWNLOADS={
 'backend.zip':('https://codeload.github.com/NotNekroz/wt-asset-explorer/zip/99c794ab102785c39e628033a09bf4ff18dbe64e','c6c1f1ed25c2675e76d0f8d48622921398b59d0eb8fb0d065d2f524122673d14'),
 'texconv.exe':('https://github.com/microsoft/DirectXTex/releases/download/may2026/texconv.exe','dcfdec10244e02cf5037fba089c55fb7e1326b1c8181742d77d15fa5cb5eef06')}
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def unpack_backend(zp):
 # wt-asset-explorer is NOT shipped with the builder: its pinned upstream commit is unpacked here at setup
 # (dae_core, wtx, lib) and the builder's own edits (toolkit/backend_patches.json) are applied to it.
 dst=ROOT/'toolkit/wt-asset-explorer';pj=json.loads((ROOT/'toolkit/backend_patches.json').read_text(encoding='utf-8'))
 mark=dst/'.unpacked';want=digest(zp)+digest(ROOT/'toolkit/backend_patches.json')
 if mark.exists() and mark.read_text()==want:return
 if dst.exists():shutil.rmtree(dst)
 with zipfile.ZipFile(zp) as z:
  for n in z.namelist():
   rel=n.split('/',1)[1] if '/' in n else ''
   if not rel or n.endswith('/') or rel.split('/')[0] not in ('dae_core','wtx','lib'):continue
   out=dst/rel;out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(z.read(n))
 for p in pj['patches']:
  f=dst/p['file'];s=f.read_bytes().decode('utf-8').replace('\r\n','\n')
  if s.count(p['old'])!=1:raise RuntimeError('backend edit does not fit upstream: '+p['file'])
  f.write_bytes(s.replace(p['old'],p['new']).encode('utf-8'))
 mark.write_text(want)
 print('wt-asset-explorer unpacked from the pinned upstream commit, builder edits applied.',flush=True)
def setup():
 cache=ROOT/'.tools/downloads';cache.mkdir(parents=True,exist_ok=True);TOOLS.mkdir(parents=True,exist_ok=True)
 for name,(url,expected) in DOWNLOADS.items():
  p=cache/name
  if not p.exists() or digest(p)!=expected:
   print('Downloading pinned tool:',name,flush=True);tmp=p.with_suffix('.download')
   subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'DownloadTool.ps1'),'-Url',url,'-Destination',str(tmp)],check=True)
   if digest(tmp)!=expected:raise RuntimeError('Tool checksum mismatch: '+name)
   tmp.replace(p)
  if name=='backend.zip':unpack_backend(p)
  else:shutil.copyfile(p,TOOLS/name)
 shutil.copyfile(TOOLS/'texconv.exe',ROOT/'toolkit/wt-asset-explorer/texconv.exe')
 print('Pinned tools ready.',flush=True)
if __name__=='__main__':setup()
