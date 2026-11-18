import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
import swapcore as sc  # noqa: E402

SLOTS = sc.load_slots(HERE.parent / "slots.json")


def tree_state(root):
    out = {}
    for p in sorted(Path(root).rglob("*")):
        if p.is_file():
            st = p.stat()
            out[p.relative_to(root).as_posix()] = (st.st_size, st.st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jhswap_"))
        shutil.copytree(HERE / "fixtures", self.tmp / "game")
        self.game = self.tmp / "game"
        self.mods = self.game / "MODS"
        self.active = self.mods / sc.ACTIVE_NAME
        self.backup = self.mods / sc.BACKUP_NAME

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sources(self):
        return sc.Sources(SLOTS, *sc.default_sources(self.mods))

    def apply(self, selection, **kw):
        return sc.apply(self.sources(), selection, self.mods, margin=kw.pop("margin", 0), **kw)

    def read(self, rel, root=None):
        return ((root or self.active) / rel).read_text(encoding="utf-8")


class TestLayers(Base):
    def test_newest_aces(self):
        (self.mods / f"{sc.ACES_PREFIX} TEST 10").mkdir()
        self.assertEqual(sc.find_aces(self.mods).name, f"{sc.ACES_PREFIX} TEST 10")
        shutil.rmtree(self.mods / f"{sc.ACES_PREFIX} TEST 10")
        self.assertEqual(sc.find_aces(self.mods).name, f"{sc.ACES_PREFIX} TEST 2")

    def test_availability(self):
        avail = self.sources().avail
        self.assertEqual({s for s in avail if avail[s][sc.WT]}, {"A6M5", "Fw190A3", "P47D22"})
        self.assertEqual({s for s in avail if avail[s][sc.ACES]}, {"A6M5", "Fw190A3", "IL2M42"})

    def test_pure_1946(self):
        src = self.sources()
        plan = sc.resolve(src, sc.preset_pure(SLOTS))
        self.assertEqual(set(plan), set(src.core_files))
        self.assertEqual({layer for _t, _s, layer in plan.values()}, {"core"})

    def test_best_available(self):
        src = self.sources()
        sel = sc.preset_best(SLOTS, src.avail)
        self.assertEqual(sel["A6M5"], {"source": sc.WT, "cockpit": sc.ACES})
        self.assertEqual(sel["P47D22"], {"source": sc.WT, "cockpit": sc.J1946})
        self.assertEqual(sel["IL2M42"], {"source": sc.J1946, "cockpit": sc.J1946})   # Aces only with the WT look
        self.assertEqual(sel["Pe2s87"], {"source": sc.J1946, "cockpit": sc.J1946})
        plan = sc.resolve(src, sel)
        layer = {k: v[2] for k, v in plan.items()}
        self.assertEqual(layer["data/graphics/planes/a6m5/a6m5.mgm"], "wt")
        self.assertEqual(layer["data/graphics/planes/a6m5/a6m5-c.mgm"], "aces")
        self.assertEqual(layer["data/graphics/planes/p47d22/p47d22-c.mgm"], "core")
        self.assertEqual(layer["data/graphics/planes/fw190a3/textures/aot25_a6m2_0.dds"], "aces")
        self.assertEqual(layer["data/graphics/textures/wt_shared.dds"], "wt")
        self.assertEqual(layer["data/luascripts/worldobjects/planes/il2m42.txt"], "core")   # no Aces script on a 1946 airframe
        self.assertNotIn("data/luascripts/worldobjects/bots/jh120_pilot_il2m42.txt", layer)
        self.assertEqual(plan["data/luascripts/worldobjects/planes/il2m42.txt"][0],
                         "data/LuaScripts/WorldObjects/Planes/il2m42.txt")
        self.assertFalse(any(k.startswith("readme") for k, v in plan.items() if v[2] == "aces"))

        self.apply(sel)
        self.assertEqual(self.read("data/graphics/planes/A6M5/A6M5.mgm"), "wt exterior A6M5\n")
        self.assertEqual(self.read("data/graphics/planes/A6M5/A6M5-C.mgm"), "aces test2 A6M5\n")
        self.assertNotEqual(self.read("data/LuaScripts/WorldObjects/Planes/il2m42.txt"), "aces lua IL2M42\n")
        self.assertEqual(self.read("data/graphics/planes/Pe2s87/Pe2s87-C.mgm"), "core cockpit Ki-21 Sally\n")
        self.assertTrue((self.active / "README - JH_test.txt").is_file())

    def test_aces_needs_wt_look(self):
        src = self.sources()
        sel, notes = sc.normalize({"A6M5": {"source": sc.J1946, "cockpit": sc.ACES}}, SLOTS, src.avail)
        self.assertEqual(sel["A6M5"], {"source": sc.J1946, "cockpit": sc.J1946})
        self.assertTrue(any("needs the WT look" in n for n in notes))
        sel, notes = sc.normalize({"A6M5": {"source": sc.WT, "cockpit": sc.ACES}}, SLOTS, src.avail)
        self.assertEqual(sel["A6M5"], {"source": sc.WT, "cockpit": sc.ACES})

    def test_rehost_aces_files_follow_slot(self):
        # WT 27: Ki-61 Aces cockpit on Bf109F4, its script names the bot of the old host MC202s8 (1946 Ki-61 slot)
        aces = sc.find_aces(self.mods)
        wt = self.mods / sc.WT_NAME
        for rel, text in (("data/graphics/planes/Bf109F4/Bf109F4-C.mgm", "aces Bf109F4\n"),
                          ("data/LuaScripts/WorldObjects/planes/Bf109F4.txt",
                           '[attach=0]\n\tobject = "LuaScripts/WorldObjects/Bots/P4_Pilot_MC202s8.txt"\n[end]\n'),
                          ("data/LuaScripts/WorldObjects/Bots/P4_Pilot_MC202s8.txt", "aces bot for Bf109F4\n"),
                          ("data/LuaScripts/WorldObjects/Planes/Turrets/P4_unknown_Gun_1.txt", "aces turret, no slot\n")):
            (aces / rel).parent.mkdir(parents=True, exist_ok=True)
            (aces / rel).write_text(text, encoding="utf-8")
        (wt / "data/graphics/planes/Bf109F4").mkdir(parents=True, exist_ok=True)
        (wt / "data/graphics/planes/Bf109F4/Bf109F4.mgm").write_text("wt exterior Bf109F4\n", encoding="utf-8")
        src = self.sources()
        self.assertTrue(src.avail["Bf109F4"][sc.ACES])
        bot = "data/luascripts/worldobjects/bots/p4_pilot_mc202s8.txt"
        sel = sc.preset_pure(SLOTS)
        plan = sc.resolve(src, sel)
        self.assertNotIn(bot, plan)            # 1946 Ki-61 on MC202s8: no Aces bot
        sel["Bf109F4"] = {"source": sc.J1946, "cockpit": sc.ACES}
        plan = sc.resolve(src, sel)            # not normalized: resolve still keeps Aces off a non-WT look
        self.assertNotIn(bot, plan)
        self.assertEqual(plan["data/graphics/planes/bf109f4/bf109f4-c.mgm"][2], "core")
        sel["Bf109F4"] = {"source": sc.WT, "cockpit": sc.ACES}
        plan = sc.resolve(src, sel)
        self.assertEqual(plan[bot][2], "aces")
        self.assertEqual(plan["data/graphics/planes/bf109f4/bf109f4-c.mgm"][2], "aces")
        self.assertNotIn("data/luascripts/worldobjects/planes/turrets/p4_unknown_gun_1.txt", plan)

    def test_off_removes_slot(self):
        src = self.sources()
        sel = sc.preset_best(SLOTS, src.avail)
        sel["A6M5"]["source"] = sc.OFF
        sel["ju88a4"]["source"] = sc.OFF
        plan = sc.resolve(src, sel)
        for key in plan:
            self.assertNotIn("/a6m5", key)
            self.assertNotIn("ju88a4", key)
        self.apply(sel)
        self.assertFalse((self.active / "data/graphics/planes/A6M5").exists())
        self.assertFalse((self.active / "data/graphics/Skins/ju88a4").exists())
        self.assertFalse((self.active / "data/LuaScripts/WorldObjects/Planes/ju88a4.txt").exists())
        self.assertTrue((self.active / "data/graphics/planes/Fw190A3/Fw190A3.mgm").is_file())
        self.assertTrue((self.active / "data/scg/countries.cfg").is_file())

    def test_server_set(self):
        src = self.sources()
        path = self.tmp / "server.json"
        path.write_text(json.dumps({"slots": {"a6m5": {"source": "wt", "cockpit": "aces"},
                                              "Pe2s87": {"source": "wt", "cockpit": "aces"},
                                              "P51B5": {"source": "off", "cockpit": "1946"}}}))
        sel, notes = sc.preset_from_file(path, SLOTS, src.avail)
        self.assertEqual(sel["A6M5"], {"source": sc.WT, "cockpit": sc.ACES})
        self.assertEqual(sel["Pe2s87"], {"source": sc.J1946, "cockpit": sc.J1946})
        self.assertEqual(sel["P51B5"]["source"], sc.OFF)
        self.assertEqual(sel["MC202s8"], {"source": sc.J1946, "cockpit": sc.J1946})
        self.assertEqual(len(notes), 2)


class TestApply(Base):
    def test_hard_link_same_volume(self):
        m = self.apply(sc.preset_best(SLOTS, self.sources().avail))
        self.assertEqual(m["copied"], 0)
        self.assertEqual(m["linked"], m["files"])
        self.assertGreater(os.stat(self.active / "data/scg/countries.cfg").st_nlink, 1)

    def test_copy_other_volume(self):
        wt_root = str(self.mods / sc.WT_NAME)
        real = sc.volume_id

        def fake(path):
            return -1 if str(path).startswith(wt_root) else real(path)

        src = self.sources()
        sel = sc.preset_best(SLOTS, src.avail)
        with mock.patch.object(sc, "volume_id", fake):
            jobs, copy_bytes = sc.build_jobs(sc.resolve(src, sel), self.mods)
            m = sc.apply(src, sel, self.mods, margin=0)
        wt_bytes = sum(os.path.getsize(s) for _t, s, layer, _l in jobs if layer == "wt")
        self.assertEqual(copy_bytes, wt_bytes)
        self.assertEqual(m["copied"], sum(1 for j in jobs if j[2] == "wt"))
        self.assertEqual(os.stat(self.active / "data/graphics/planes/A6M5/A6M5.mgm").st_nlink, 1)
        self.assertGreater(os.stat(self.active / "data/graphics/planes/A6M5/A6M5-C.mgm").st_nlink, 1)

    def test_refuse_when_enabled_mods_ini(self):
        (self.mods / "JSGME.ini").write_text(f"[DEPENDANCIES]\n[MODS]\nOther Mod=1\n{sc.ACTIVE_NAME}=2\n")
        with self.assertRaises(sc.SwapError):
            self.apply(sc.preset_pure(SLOTS))
        self.assertFalse(self.active.exists())
        self.assertFalse((self.mods / sc.BUILD_NAME).exists())

    def test_refuse_when_enabled_root_ini(self):
        (self.game / "JSGME.ini").write_text(f"[MODS FOLDER]\nName=MODS\n[MODS]\n{sc.ACTIVE_NAME.upper()}=1\n")
        with self.assertRaises(sc.SwapError):
            self.apply(sc.preset_pure(SLOTS))
        self.assertFalse(self.active.exists())

    def test_jsgme_parse(self):
        self.assertEqual(sc.jsgme_enabled(self.mods), {"other mod"})

    def test_backup_and_rollback(self):
        pure = sc.preset_pure(SLOTS)
        best = sc.preset_best(SLOTS, self.sources().avail)
        self.apply(pure)
        self.assertFalse(self.backup.exists())
        self.apply(best)
        self.assertEqual(sc.read_active_manifest(self.mods)["slots"], best)
        self.assertEqual(json.loads((self.backup / sc.SWAP_MANIFEST).read_text())["slots"], pure)
        self.apply(best)
        self.assertEqual(json.loads((self.backup / sc.SWAP_MANIFEST).read_text())["slots"], best)
        self.apply(pure)
        own = sorted(p.name for p in self.mods.iterdir() if p.name.startswith(sc.ACTIVE_NAME))
        self.assertEqual(own, [sc.ACTIVE_NAME, sc.BACKUP_NAME])

        sc.rollback(self.mods)
        self.assertEqual(sc.read_active_manifest(self.mods)["slots"], best)
        self.assertEqual(self.read("data/graphics/planes/A6M5/A6M5.mgm"), "wt exterior A6M5\n")
        sc.rollback(self.mods)
        self.assertEqual(sc.read_active_manifest(self.mods)["slots"], pure)

        (self.mods / "JSGME.ini").write_text(f"[MODS]\n{sc.ACTIVE_NAME}=1\n")
        with self.assertRaises(sc.SwapError):
            sc.rollback(self.mods)

    def test_rollback_without_backup(self):
        with self.assertRaises(sc.SwapError):
            sc.rollback(self.mods)

    def test_free_space_refusal(self):
        before = tree_state(self.mods)
        src = self.sources()
        with mock.patch.object(sc, "volume_id", lambda p: -1 if str(p).startswith(str(src.core)) else 0), \
                mock.patch.object(sc, "free_bytes", lambda p: 5 * sc.GB + 100):
            with self.assertRaises(sc.SwapError) as cm:
                sc.apply(src, sc.preset_pure(SLOTS), self.mods)
        self.assertIn("free space", str(cm.exception))
        self.assertEqual(tree_state(self.mods), before)
        with mock.patch.object(sc, "free_bytes", lambda p: 4 * sc.GB):
            with self.assertRaises(sc.SwapError):
                sc.apply(src, sc.preset_pure(SLOTS), self.mods)
        self.assertFalse(self.active.exists())
        with mock.patch.object(sc, "free_bytes", lambda p: 5 * sc.GB + 100):
            m = sc.apply(src, sc.preset_pure(SLOTS), self.mods)
        self.assertEqual(m["copied"], 0)

    def test_manifest(self):
        src = self.sources()
        sel = sc.preset_best(SLOTS, src.avail)
        sel["P51B5"]["source"] = sc.OFF
        m = self.apply(sel)
        disk = sc.read_active_manifest(self.mods)
        self.assertEqual(disk, m)
        self.assertEqual(disk["slots"]["P51B5"]["source"], sc.OFF)
        self.assertEqual(disk["slots"]["A6M5"], {"source": sc.WT, "cockpit": sc.ACES})
        core_m = self.mods / sc.CORE_NAME / "SHA256 - JH_test.json"
        self.assertEqual(disk["sources"]["core"]["manifest_sha256"], hashlib.sha256(core_m.read_bytes()).hexdigest())
        wt_m = self.mods / sc.WT_NAME / sc.WT_MANIFEST
        self.assertEqual(disk["sources"]["wt"]["manifest_sha256"], hashlib.sha256(wt_m.read_bytes()).hexdigest())
        self.assertEqual(disk["sources"]["wt"]["wt_version_install"], "2.41.0.1")
        self.assertTrue(disk["sources"]["aces"]["path"].endswith("TEST 2"))
        self.assertEqual(disk["files"], sum(disk["layers"].values()))
        self.assertEqual(disk["files"], sum(1 for p in self.active.rglob("*") if p.is_file()) - 1)

    def test_other_folders_untouched(self):
        others = [p for p in self.mods.iterdir() if not p.name.startswith(sc.ACTIVE_NAME)]
        before = {p.name: tree_state(p) if p.is_dir() else p.read_bytes() for p in others}
        game_bin = tree_state(self.game / "bin")
        best = sc.preset_best(SLOTS, self.sources().avail)
        self.apply(best)
        self.apply(sc.preset_pure(SLOTS))
        sc.rollback(self.mods)
        after = {p.name: tree_state(p) if p.is_dir() else p.read_bytes() for p in others}
        self.assertEqual(before, after)
        self.assertEqual(tree_state(self.game / "bin"), game_bin)
        self.assertEqual(sc.jsgme_enabled(self.mods), {"other mod"})

    def test_remove_own_guard(self):
        with self.assertRaises(sc.SwapError):
            sc.remove_own(self.mods / "Other Mod", self.mods)
        self.assertTrue((self.mods / "Other Mod" / "data" / "other.txt").is_file())


class TestStatus(Base):
    def test_lights(self):
        src = self.sources()
        sel = sc.preset_best(SLOTS, src.avail)
        self.assertEqual(sc.slot_status("A6M5", sel["A6M5"], None, src)[0], sc.GREY)
        self.apply(sel)
        m = sc.read_active_manifest(self.mods)
        src = self.sources()
        for s, _a in SLOTS:
            self.assertEqual(sc.slot_status(s, sel[s], m, src), (sc.GREEN, "current"))
        changed = {"source": sc.J1946, "cockpit": sc.ACES}
        self.assertEqual(sc.slot_status("A6M5", changed, m, src)[0], sc.AMBER)

        wt_m = self.mods / sc.WT_NAME / sc.WT_MANIFEST
        data = json.loads(wt_m.read_text())
        data["wt_version_install"] = "2.43.0.0"
        wt_m.write_text(json.dumps(data))
        src = self.sources()
        self.assertEqual(sc.slot_status("A6M5", sel["A6M5"], m, src)[0], sc.AMBER)
        self.assertEqual(sc.slot_status("Pe2s87", sel["Pe2s87"], m, src)[0], sc.GREEN)

    def test_wt_file_mismatch(self):
        src = self.sources()
        sel = sc.preset_best(SLOTS, src.avail)
        self.apply(sel)
        m = sc.read_active_manifest(self.mods)
        (self.mods / sc.WT_NAME / "data/graphics/planes/P47D22/P47D22.mgm").write_text("changed size\n")
        src = self.sources()
        self.assertFalse(src.wt_files_match("P47D22"))
        self.assertTrue(src.wt_files_match("A6M5"))
        self.assertEqual(sc.slot_status("P47D22", sel["P47D22"], m, src)[0], sc.AMBER)


class TestSteam(unittest.TestCase):
    def test_find_game(self):
        tmp = Path(tempfile.mkdtemp(prefix="jhsteam_"))
        try:
            steam, lib = tmp / "Steam", tmp / "Lib"
            (steam / "steamapps").mkdir(parents=True)
            (lib / "steamapps" / "common" / "IL-2 Sturmovik Battle of Stalingrad").mkdir(parents=True)
            lib_esc = str(lib).replace("\\", "\\\\")
            (steam / "steamapps" / "libraryfolders.vdf").write_text(
                f'"libraryfolders"\n{{\n\t"0"\n\t{{\n\t\t"path"\t\t"{lib_esc}"\n\t\t"apps"\n\t\t{{\n'
                f'\t\t\t"307960"\t\t"1"\n\t\t}}\n\t}}\n}}\n')
            (lib / "steamapps" / "appmanifest_307960.acf").write_text(
                '"AppState"\n{\n\t"appid"\t\t"307960"\n\t"installdir"\t\t"IL-2 Sturmovik Battle of Stalingrad"\n}\n')
            self.assertEqual(sc.find_game([steam]), lib / "steamapps" / "common" / "IL-2 Sturmovik Battle of Stalingrad")
            self.assertIsNone(sc.find_game([tmp / "nothing"]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
