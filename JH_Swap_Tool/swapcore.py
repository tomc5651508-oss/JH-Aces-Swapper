import datetime
import hashlib
import json
import os
import re
import shutil
import stat
import sys
from pathlib import Path

TOOL_VERSION = "1.0"
APP_ID = "307960"
ACTIVE_NAME = "JH_PR_2.5 Jungle Hawks - active"
BACKUP_NAME = ACTIVE_NAME + ".backup"
BUILD_NAME = ACTIVE_NAME + ".building"
CORE_NAME = "JH_PR_2.5 Jungle Hawks - 1946"
WT_NAME = "JH WT ASSET PACK - FOR JH2.5"
WT_MANIFEST = "JH WT ASSET PACK - manifest.json"
ACES_PREFIX = "JH_PR_2.5 WT - Aces Cockpits and Optics"
ACES_MANIFEST = "PACKAGE_SHA256.json"
SWAP_MANIFEST = "JH Swap Tool - manifest.json"
GB = 1024 ** 3
DEFAULT_MARGIN_GB = 5

OFF, J1946, WT, ACES = "off", "1946", "wt", "aces"
LOOKS = {OFF: "Off (stock host)", J1946: "JH 1946", WT: "JH WT look"}
COCKPITS = {J1946: "1946", ACES: "Aces"}
GREEN, AMBER, GREY = "green", "amber", "grey"


class SwapError(Exception):
    pass


def app_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def load_slots(path=None):
    if path is None:
        for d in (app_dir(), Path(getattr(sys, "_MEIPASS", app_dir()))):
            if (d / "slots.json").is_file():
                path = d / "slots.json"
                break
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [(e["slot"], e["aircraft"]) for e in data["slots"]]


def settings_path():
    return Path(os.environ.get("APPDATA", Path.home())) / "JH Swap Tool" / "settings.json"


def load_settings(path=None):
    path = Path(path or settings_path())
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(data, path=None):
    path = Path(path or settings_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def steam_roots():
    roots = []
    try:
        import winreg
        for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    for name in ("SteamPath", "InstallPath"):
                        try:
                            roots.append(Path(winreg.QueryValueEx(k, name)[0]))
                        except OSError:
                            pass
            except OSError:
                pass
    except ImportError:
        pass
    roots.append(Path(r"C:\Program Files (x86)\Steam"))
    out = []
    for r in roots:
        if r.is_dir() and all(r.resolve() != o.resolve() for o in out):
            out.append(r)
    return out


def library_paths(steam_root):
    libs = [Path(steam_root)]
    vdf = Path(steam_root) / "steamapps" / "libraryfolders.vdf"
    if vdf.is_file():
        text = vdf.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r'"path"\s+"([^"]+)"', text):
            libs.append(Path(m.group(1).replace("\\\\", "\\")))
    return libs


def find_game(roots=None):
    for root in steam_roots() if roots is None else roots:
        for lib in library_paths(root):
            acf = lib / "steamapps" / f"appmanifest_{APP_ID}.acf"
            if not acf.is_file():
                continue
            m = re.search(r'"installdir"\s+"([^"]+)"', acf.read_text(encoding="utf-8", errors="replace"))
            if m:
                game = lib / "steamapps" / "common" / m.group(1)
                if game.is_dir():
                    return game
    return None


def natural_key(name):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def find_aces(mods):
    try:
        cands = [p for p in Path(mods).iterdir()
                 if p.is_dir() and p.name.lower().startswith(ACES_PREFIX.lower())]
    except OSError:
        return None
    if not cands:
        return None
    return max(cands, key=lambda p: (natural_key(p.name), p.stat().st_mtime))


def default_sources(mods):
    mods = Path(mods)
    return mods / CORE_NAME, mods / WT_NAME, find_aces(mods)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def index_files(root, prefix=""):
    out = {}
    root = Path(root)
    if not root.is_dir():
        return out
    for dirpath, _dirs, files in os.walk(root):
        for n in files:
            rel = Path(dirpath, n).relative_to(root).as_posix()
            if rel.lower().startswith(prefix):
                out[rel.lower()] = rel
    return out


def slot_of(key, slots_lower, bots=False):
    p = key.split("/")
    if len(p) >= 5 and p[0] == "data" and p[1] == "graphics" and p[2] in ("planes", "skins"):
        return p[3] if p[3] in slots_lower else None
    if len(p) == 5 and p[:3] == ["data", "luascripts", "worldobjects"] and p[4].endswith(".txt"):
        stem = p[4][:-4]
        if p[3] == "planes":
            return stem if stem in slots_lower else None
        if bots and p[3] == "bots":
            for s in slots_lower:
                if stem.endswith("_" + s):
                    return s
    return None


class Sources:
    def __init__(self, slots, core, wt=None, aces=None):
        self.slots = [s for s, _a in slots]
        self.lower = {s.lower(): s for s in self.slots}
        self.core = Path(core) if core else None
        self.wt = Path(wt) if wt and Path(wt).is_dir() else None
        self.aces = Path(aces) if aces and Path(aces).is_dir() else None
        self.core_files = index_files(self.core) if self.core else {}
        self.wt_files = index_files(self.wt, "data/") if self.wt else {}
        self.aces_files = index_files(self.aces, "data/") if self.aces else {}
        self.wt_manifest = {}
        if self.wt and (self.wt / WT_MANIFEST).is_file():
            try:
                self.wt_manifest = json.loads((self.wt / WT_MANIFEST).read_text(encoding="utf-8"))
            except ValueError:
                self.wt_manifest = {}
        wt_slots = {slot_of(k, self.lower, bots=True) for k in self.wt_files}
        self.avail = {}
        for s in self.slots:
            low = s.lower()
            self.avail[s] = {
                WT: low in wt_slots,
                ACES: f"data/graphics/planes/{low}/{low}-c.mgm" in self.aces_files,
            }
        self._info = None

    def core_manifest(self):
        if not self.core or not self.core.is_dir():
            return None
        found = sorted(self.core.glob("SHA256 - *.json"))
        return found[0] if found else None

    def info(self):
        if self._info is None:
            def entry(root, manifest):
                if root is None:
                    return None
                e = {"path": str(root), "manifest": None, "manifest_sha256": None}
                if manifest and Path(manifest).is_file():
                    e["manifest"] = Path(manifest).name
                    e["manifest_sha256"] = sha256_file(manifest)
                return e
            self._info = {
                "core": entry(self.core, self.core_manifest()),
                "wt": entry(self.wt, self.wt and self.wt / WT_MANIFEST),
                "aces": entry(self.aces, self.aces and self.aces / ACES_MANIFEST),
            }
            if self._info["wt"]:
                self._info["wt"]["wt_version_install"] = self.wt_manifest.get("wt_version_install")
                self._info["wt"]["recipe_version"] = self.wt_manifest.get("recipe_version")
        return self._info

    def wt_files_match(self, slot):
        files = self.wt_manifest.get("files") or {}
        low = slot.lower()
        listed = {k.replace("\\", "/").lower(): v for k, v in files.items()}
        for key, rel in self.wt_files.items():
            if slot_of(key, self.lower, bots=True) != low:
                continue
            want = listed.get(key)
            if want is None or os.path.getsize(self.wt / rel) != want.get("size"):
                return False
        for key in listed:
            if slot_of(key, self.lower, bots=True) == low and key not in self.wt_files:
                return False
        return True


def preset_pure(slots):
    return {s: {"source": J1946, "cockpit": J1946} for s, _a in slots}


def preset_best(slots, avail):
    return {s: {"source": WT if avail[s][WT] else J1946,
                "cockpit": ACES if avail[s][ACES] and avail[s][WT] else J1946} for s, _a in slots}


def normalize(selection, slots, avail):
    out, notes = {}, []
    for s, _a in slots:
        e = selection.get(s) or {}
        src = e.get("source", J1946)
        cp = e.get("cockpit", J1946)
        if src not in LOOKS:
            src = J1946
        if cp not in COCKPITS:
            cp = J1946
        if src == WT and not avail[s][WT]:
            notes.append(f"{s}: WT look not available, JH 1946 used")
            src = J1946
        if cp == ACES and not avail[s][ACES]:
            notes.append(f"{s}: Aces cockpit not available, 1946 cockpit used")
            cp = J1946
        if cp == ACES and src != WT:          # Aces cockpit = WT plane script: only on the WT look
            notes.append(f"{s}: Aces cockpit needs the WT look, 1946 cockpit used")
            cp = J1946
        out[s] = {"source": src, "cockpit": cp}
    return out, notes


def preset_from_file(path, slots, avail):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = {k.lower(): v for k, v in (data.get("slots") or {}).items()}
    sel = {s: entries.get(s.lower(), {"source": J1946, "cockpit": J1946}) for s, _a in slots}
    return normalize(sel, slots, avail)


REF_RE = re.compile(r'"(LuaScripts/WorldObjects/[^"]+\.txt)"', re.I)


def aces_refs(sources):
    """Aces data files named in an Aces plane script -> that slot (lower case). A re-hosted slot names a bot of its old
    host (WT 27: Bf109F4.txt -> Bots/P4_Pilot_MC202s8.txt); the SBD script names its turret script."""
    refs = {}
    for s in sources.lower:
        rel = sources.aces_files.get(f"data/luascripts/worldobjects/planes/{s}.txt")
        if not rel:
            continue
        text = (sources.aces / rel).read_text(encoding="latin1", errors="replace")
        for m in REF_RE.finditer(text):
            key = "data/" + m.group(1).replace("\\", "/").lower()
            if key in sources.aces_files:
                refs.setdefault(key, s)
    return refs


def resolve(sources, selection):
    off = {s.lower() for s in sources.slots if selection[s]["source"] == OFF}
    wt = {s.lower() for s in sources.slots if selection[s]["source"] == WT}
    # The Aces files are built from a WT base (cockpit, plane script, bot): only on slots with the WT look.
    aces = {s.lower() for s in sources.slots
            if selection[s]["source"] == WT and selection[s]["cockpit"] == ACES}
    refs = aces_refs(sources) if aces else {}
    plan = {}
    for key, rel in sources.core_files.items():
        if slot_of(key, sources.lower) in off:
            continue
        plan[key] = (rel, sources.core / rel, "core")
    for layer, files, root, chosen in (("wt", sources.wt_files, sources.wt, wt),
                                       ("aces", sources.aces_files, sources.aces, aces)):
        if not chosen:
            continue
        for key, rel in files.items():
            if layer == "aces":
                # Aces files of no slot are left out: each one belongs to a cockpit slot (directly, by a reference
                # in the slot's Aces plane script, or by the bot name suffix).
                s = slot_of(key, sources.lower) or refs.get(key) or slot_of(key, sources.lower, bots=True)
                if s in chosen:
                    target = plan[key][0] if key in plan else rel
                    plan[key] = (target, root / rel, layer)
                continue
            s = slot_of(key, sources.lower, bots=True)
            if s is None or s in chosen:
                target = plan[key][0] if key in plan else rel
                plan[key] = (target, root / rel, layer)
    return plan


def volume_id(path):
    return os.stat(path).st_dev


def free_bytes(path):
    return shutil.disk_usage(path).free


def own_paths(mods):
    mods = Path(mods)
    return mods / ACTIVE_NAME, mods / BACKUP_NAME, mods / BUILD_NAME


def jsgme_enabled(mods, game_root=None):
    names = set()
    game_root = Path(game_root) if game_root else Path(mods).parent
    for ini in (Path(mods) / "JSGME.ini", game_root / "JSGME.ini"):
        if not ini.is_file():
            continue
        raw = ini.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")
        section = None
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip().upper()
            elif section == "MODS" and "=" in line:
                names.add(line.rsplit("=", 1)[0].strip().lower())
    return names


def check_not_enabled(mods, game_root=None):
    enabled = jsgme_enabled(mods, game_root)
    for name in (ACTIVE_NAME, BACKUP_NAME):
        if name.lower() in enabled:
            raise SwapError(f'"{name}" is enabled in JSGME. Disable it in JSGME first, then try again.')


def _writable(func, path, _exc):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def remove_own(path, mods):
    path = Path(path)
    if path not in own_paths(mods):
        raise SwapError(f"Refused to delete {path}: not a JH Swap Tool folder.")
    shutil.rmtree(path, onexc=_writable)


def read_active_manifest(mods):
    path = Path(mods) / ACTIVE_NAME / SWAP_MANIFEST
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def build_jobs(plan, mods):
    mods_dev = volume_id(mods)
    jobs, copy_bytes = [], 0
    for key in sorted(plan):
        target, src, layer = plan[key]
        link = volume_id(src) == mods_dev
        if not link:
            copy_bytes += os.path.getsize(src)
        jobs.append((target, src, layer, link))
    return jobs, copy_bytes


def apply(sources, selection, mods, game_root=None, margin=DEFAULT_MARGIN_GB * GB, progress=None):
    mods = Path(mods)
    if not mods.is_dir():
        raise SwapError(f"MODS folder not found: {mods}")
    active, backup, building = own_paths(mods)
    check_not_enabled(mods, game_root)
    for root in (sources.core, sources.wt, sources.aces):
        if root and any(Path(root).resolve() == p.resolve() for p in (active, backup, building)):
            raise SwapError(f"Source folder {root} is a JH Swap Tool output folder.")
    if not sources.core_files:
        raise SwapError(f"1946 core folder is missing or empty: {sources.core}")
    plan = resolve(sources, selection)
    jobs, copy_bytes = build_jobs(plan, mods)
    free = free_bytes(mods)
    if free - copy_bytes < margin:
        raise SwapError(f"Not enough free space on the MODS drive: {copy_bytes / GB:.2f} GB to copy, "
                        f"{free / GB:.2f} GB free, {margin / GB:.2f} GB must stay free.")
    if building.exists():
        remove_own(building, mods)
    linked = copied = 0
    try:
        for i, (target, src, _layer, link) in enumerate(jobs):
            dst = building / target
            dst.parent.mkdir(parents=True, exist_ok=True)
            if link:
                try:
                    os.link(src, dst)
                except OSError as e:
                    raise SwapError(f"Hard link failed for {src}: {e}") from e
                linked += 1
            else:
                shutil.copy2(src, dst)
                copied += 1
            if progress:
                progress(i + 1, len(jobs))
        manifest = {
            "tool": "JH Swap Tool",
            "tool_version": TOOL_VERSION,
            "built": datetime.datetime.now().isoformat(timespec="seconds"),
            "sources": sources.info(),
            "slots": {s: dict(selection[s]) for s in sources.slots},
            "files": len(jobs),
            "linked": linked,
            "copied": copied,
            "copied_bytes": copy_bytes,
            "layers": {name: sum(1 for j in jobs if j[2] == name) for name in ("core", "wt", "aces")},
        }
        (building / SWAP_MANIFEST).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    except BaseException:
        if building.exists():
            remove_own(building, mods)
        raise
    if backup.exists():
        remove_own(backup, mods)
    if active.exists():
        active.rename(backup)
    building.rename(active)
    return manifest


def rollback(mods, game_root=None):
    mods = Path(mods)
    active, backup, building = own_paths(mods)
    check_not_enabled(mods, game_root)
    if not backup.is_dir():
        raise SwapError("No backup to roll back to.")
    if building.exists():
        remove_own(building, mods)
    if active.exists():
        active.rename(building)
    backup.rename(active)
    if building.exists():
        building.rename(backup)


def slot_status(slot, chosen, manifest, sources):
    if not manifest or slot not in (manifest.get("slots") or {}):
        return GREY, "not generated"
    applied = manifest["slots"][slot]
    if applied.get("source") != chosen["source"] or (
            chosen["source"] != OFF and applied.get("cockpit") != chosen["cockpit"]):
        return AMBER, "selection changed, press Apply"
    old = manifest.get("sources") or {}
    new = sources.info()

    def changed(layer):
        a, b = old.get(layer), new.get(layer)
        if not a or not b:
            return True
        keys = ["path", "manifest_sha256"] + (["wt_version_install", "recipe_version"] if layer == "wt" else [])
        return any(a.get(k) != b.get(k) for k in keys)

    if changed("core"):
        return AMBER, "outdated: 1946 core changed"
    if applied["source"] == WT:
        if not sources.avail[slot][WT]:
            return AMBER, "outdated: WT pack files missing"
        if changed("wt"):
            return AMBER, "outdated: WT pack version or manifest changed"
        if not sources.wt_files_match(slot):
            return AMBER, "outdated: WT files differ from pack manifest"
    if applied["source"] != OFF and applied.get("cockpit") == ACES:
        if not sources.avail[slot][ACES]:
            return AMBER, "outdated: Aces cockpit missing"
        if changed("aces"):
            return AMBER, "outdated: Aces folder changed"
    return GREEN, "current"
