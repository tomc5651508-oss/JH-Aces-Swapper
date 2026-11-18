"""Writes the small fake game tree in tests/fixtures (run once; output is committed)."""
import hashlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
import swapcore as sc  # noqa: E402

FIX = HERE / "fixtures"


def put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def sha_list(root):
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != sc.ACES_MANIFEST:
            data = p.read_bytes()
            out.append({"file": p.relative_to(root).as_posix(), "bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest()})
    return out


def main():
    if FIX.exists():
        shutil.rmtree(FIX)
    mods = FIX / "MODS"
    slots = sc.load_slots(HERE.parent / "slots.json")

    core = mods / sc.CORE_NAME
    put(core / "README - JH_test.txt", "core readme\n")
    put(core / "data" / "scg" / "countries.cfg", "countries\n")
    for slot, aircraft in slots:
        put(core / "data/graphics/planes" / slot / f"{slot}.mgm", f"core exterior {aircraft}\n")
        put(core / "data/graphics/planes" / slot / f"{slot}-C.mgm", f"core cockpit {aircraft}\n")
        put(core / "data/graphics/Skins" / slot / "skin1.dds", f"core skin {aircraft}\n")
        put(core / "data/LuaScripts/WorldObjects/Planes" / f"{slot.lower()}.txt", f"core lua {aircraft}\n")
    put(core / "SHA256 - JH_test.json", json.dumps({"release": "JH_test", "files": sha_list(core)}, indent=1))

    wt = mods / sc.WT_NAME
    for slot in ("A6M5", "Fw190A3", "P47D22"):
        put(wt / "data/graphics/planes" / slot / f"{slot}.mgm", f"wt exterior {slot}\n")
        put(wt / "data/graphics/Skins" / slot / "wt_skin.dds", f"wt skin {slot}\n")
    put(wt / "data/graphics/textures/wt_shared.dds", "wt shared\n")
    files = {}
    for p in sorted((wt / "data").rglob("*")):
        if p.is_file():
            data = p.read_bytes()
            files[p.relative_to(wt).as_posix()] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    put(wt / sc.WT_MANIFEST, json.dumps({"wt_version_install": "2.41.0.1", "recipe_version": 1,
                                          "files": files}, indent=1))

    a1 = mods / f"{sc.ACES_PREFIX} TEST 1"
    put(a1 / "data/graphics/planes/A6M5/A6M5-C.mgm", "aces test1 A6M5\n")
    a2 = mods / f"{sc.ACES_PREFIX} TEST 2"
    put(a2 / "README.txt", "aces readme\n")
    put(a2 / "data/graphics/planes/A6M5/A6M5-C.mgm", "aces test2 A6M5\n")
    put(a2 / "data/graphics/planes/Fw190A3/Fw190A3-C.mgm", "aces test2 Fw190A3\n")
    put(a2 / "data/graphics/planes/Fw190A3/Textures/AOT25_a6m2_0.dds", "aces tex\n")
    put(a2 / "data/graphics/planes/IL2M42/IL2M42-C.mgm", "aces test2 IL2M42\n")
    put(a2 / "data/graphics/planes/IL2M42/IL2M42-C.txt", "aces test2 IL2M42 txt\n")
    put(a2 / "data/LuaScripts/WorldObjects/planes/IL2M42.txt", "aces lua IL2M42\n")
    put(a2 / "data/LuaScripts/WorldObjects/Bots/JH120_Pilot_IL2M42.txt", "aces bot IL2M42\n")
    for a in (a1, a2):
        put(a / sc.ACES_MANIFEST, json.dumps(sha_list(a), indent=1))

    put(mods / "Other Mod" / "data" / "other.txt", "other mod\n")
    put(mods / "JSGME.ini", "[DEPENDANCIES]\n[MODS]\nOther Mod=1\n")
    put(FIX / "JSGME.ini", "[MODS FOLDER]\nName=MODS\n[JSGME DETAILS]\nFullPath=C:\\fake\\JSGME.exe\n")
    put(FIX / "bin" / "game" / "Il-2.exe", "not a game\n")


if __name__ == "__main__":
    main()
