# JH Swap Tool

Windows GUI for Jungle Hawks 2.5 (IL-2 Great Battles). The tool combines the JH 1946 core, the JH WT asset pack and the Aces cockpit folder into one JSGME folder:

`<MODS>\JH_PR_2.5 Jungle Hawks - active`

## Function

- One card per host slot (23 slots: 19 swaps; four Japanese fighters are listed twice, on the 1946 host and on the WT 27 host). Each card shows host slot -> JH aircraft, the source and a status light.
  - Green: the active folder matches the selection and the source folders.
  - Amber: outdated. The selection changed, or a source manifest, the WT version or the WT file sizes differ from the values in the active folder manifest.
  - Grey: not generated.
- Look per slot: "Off (stock host)", "JH 1946", "JH WT look". "JH WT look" shows only when the WT asset pack holds files for that slot.
- Cockpit per slot: "1946" or "Aces". "Aces" shows only when the Aces folder holds `data/graphics/planes/<Slot>/<Slot>-C.mgm`.
- Presets:
  - Pure 1946: JH 1946 and 1946 cockpit on all slots.
  - Best available: WT look and Aces cockpit where present, else 1946.
  - Multiplayer server set: reads a JSON file with a `slots` object, for example the `JH Swap Tool - manifest.json` from a server. Slots not in the file use JH 1946. Sources not installed fall back to 1946.
- Apply builds the active folder. Layer order:
  1. 1946 core folder (all files).
  2. WT asset pack `data/` files for slots set to "JH WT look", plus WT files that belong to no slot.
  3. Aces folder `data/` files for slots set to "JH WT look" + "Aces". Aces files of no slot are left out.
- "Off" removes these core files of the slot (case-insensitive):
  `data/graphics/planes/<Slot>/**`, `data/graphics/Skins/<Slot>/**`, `data/LuaScripts/WorldObjects/Planes/<Slot>.txt`.
- Slot files of the WT and Aces layers also include `data/LuaScripts/WorldObjects/Bots/*_<Slot>.txt`.
- Aces layer: a file named in the slot's Aces plane script (`"LuaScripts/WorldObjects/..."`) belongs to that slot. Example WT 27: `Planes/Bf109F4.txt` names `Bots/P4_Pilot_MC202s8.txt`, so that bot follows the Ki-61 on Bf109F4 and never replaces the bot of the 1946 Ki-61 on MC202s8.
- "Aces" needs "JH WT look" on the same slot (the Aces cockpit, plane script and bot are built from the WT base). "Aces" with "JH 1946" or "Off" uses the 1946 cockpit; Apply checks this again.
- Apply writes `JH Swap Tool - manifest.json` into the active folder: source per slot, source folder paths, SHA-256 of the source manifests, WT version, file counts.
- Files on the same volume as MODS are hard links. Files on another volume are copies. The build goes into `...- active.building`, then a rename makes it the active folder.
- Free-space check: Apply stops when free space minus the bytes to copy is less than "Keep free (GB)" (default 5).
- Backup: Apply moves the previous active folder to `<MODS>\JH_PR_2.5 Jungle Hawks - active.backup`. Only one backup exists.
- Roll back swaps the active folder and the backup. A second Roll back undoes the first.

## Rules

- The tool never writes to `bin\game`.
- The tool never changes or deletes a MODS folder other than `...- active`, `...- active.backup` and `...- active.building`.
- The tool never enables a mod in JSGME.
- After Apply, enable "JH_PR_2.5 Jungle Hawks - active" in JSGME. Do not enable the 1946 core, WT pack or Aces folder together with it.
- Before the next Apply or Roll back, disable "JH_PR_2.5 Jungle Hawks - active" in JSGME. The tool reads `[MODS]` in `<MODS>\JSGME.ini` and `<game>\JSGME.ini` and stops when the active folder or the backup is enabled.
- Do not edit files in the active folder. Most files are hard links: an edit in place also changes the source folder.

## Paths

- The game folder comes from Steam `libraryfolders.vdf` and `appmanifest_307960.acf`. "Detect" repeats the search. The MODS folder can also be set by hand.
- Default sources (empty field = default):
  - 1946 core: `<MODS>\JH_PR_2.5 Jungle Hawks - 1946`
  - WT asset pack: `<MODS>\JH WT ASSET PACK - FOR JH2.5` (manifest `JH WT ASSET PACK - manifest.json`)
  - Aces: the newest `<MODS>\JH_PR_2.5 WT - Aces Cockpits and Optics*` folder (natural sort of the name, then date).
- Settings: `%APPDATA%\JH Swap Tool\settings.json`.
- Slot table: `slots.json` next to the exe (or next to `jh_swap_tool.py`). The exe also holds a copy, used when no `slots.json` is next to it.

## Run from source

Python 3.10+ with tkinter. Pillow is only for the preview screenshot.

```
python jh_swap_tool.py
python jh_swap_tool.py --settings C:\temp\settings.json
```

## Tests

The tests use a small fake game tree in `tests\fixtures` and copy it to a temp folder before each test.

```
python -m unittest discover -s tests -v
python tests\make_fixtures.py        (rewrites tests\fixtures)
python tests\preview_gui.py          (writes JH_Swap_Tool_GUI_preview.png)
```

## Build

PyInstaller 6:

```
python build_exe.py
```

Output: `dist\JH_Swap_Tool.exe`, `dist\JH_Swap_Tool.zip` (exe, README.md, slots.json), `dist\JH_Swap_Tool.sha256.txt`.

## Limits

- "Off" removes only the three slot paths above. Other core files (careers, missions, country tables) still refer to the JH aircraft.
- The WT file check compares file sizes with the pack manifest, not SHA-256.
- The Aces folder is built against the WT bases. An Aces cockpit on a "JH 1946" slot also replaces the slot's plane Lua file from the Aces folder.
