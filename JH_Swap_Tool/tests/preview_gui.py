"""Opens the GUI on a temp copy of the fixtures and saves a PNG of the window."""
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
import jh_swap_tool  # noqa: E402
import swapcore as sc  # noqa: E402


def main(out):
    tmp = Path(tempfile.mkdtemp(prefix="jhswap_preview_"))
    try:
        shutil.copytree(HERE / "fixtures", tmp / "game")
        mods = tmp / "game" / "MODS"
        slots = sc.load_slots(HERE.parent / "slots.json")
        src = sc.Sources(slots, *sc.default_sources(mods))
        sel = sc.preset_best(slots, src.avail)
        sel["P51B5"]["source"] = sc.OFF
        sc.apply(src, sel, mods, margin=0)
        sel["Pe2s87"] = {"source": sc.OFF, "cockpit": sc.J1946}
        settings = tmp / "settings.json"
        settings.write_text(json.dumps({"mods": str(mods), "margin_gb": 5, "selection": sel}))
        jh_swap_tool.main(["--settings", str(settings), "--preview", str(out)])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "JH_Swap_Tool_GUI_preview.png")
