import os,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
cfg=json.loads(Path(os.environ['AOT_BUILD_CONFIG']).read_text(encoding='utf-8-sig'))
WORK=Path(cfg['work']);AOT=Path(cfg['aot']);GAME=Path(cfg['il2']);BASE=Path(cfg['base'])
TOOLS=ROOT.parent/'.tools/bin'
from slots import NAME
PACKAGE=WORK/NAME;SOURCE=WORK/'cockpits';REPORT=WORK/'reports'
