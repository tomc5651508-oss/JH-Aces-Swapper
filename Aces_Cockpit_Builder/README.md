# Aces Cockpit Builder for JH 2.5 WT

Builds the overlay mod **JH_PR_2.5 WT - Aces Cockpits and Optics** from your own Aces of Thunder install. Read `NOTICE.txt` first: who owns what, why this is a builder and not a download, and the rules (free, personal use, do not share the generated folder).

## Use

Extract the ZIP to a writable folder outside both game installs, then double-click **Build Cockpit Mod.bat**.

1. Select your **Aces of Thunder** install, with the high-quality cockpit content installed.
2. Select **IL-2 Great Battles** and your **JH 2.5 WT base**. The default is the highest-numbered `JH_PR_2.5 Jungle Hawks - WT N` folder in `MODS` (fallback WT 27). Supported base: WT 27 (`toolkit\slots.json`). Bases WT, WT 18 to WT 26 need the older slot map: put `"slots": "<builder>\\toolkit\\slots_wt18-26.json"` in the job config. Steam locations are filled in when found.
3. Choose a **new output folder** and click **Build mod**. Browse selects the parent folder (for example IL-2's `MODS`) and adds an unused folder name. First setup downloads a private Python runtime, pinned packages and checksum-verified tools; no Python install is needed.
4. **Keep extracted source files (for debugging)** is off by default. Off: after a successful build the extracted Aces material in `.work` is deleted. On: it is kept.
5. The output is an inactive mod. With IL-2 closed, disable earlier Aces TEST overlays, then enable the generated mod after the selected JH 2.5 WT base in JSGME. The builder never enables mods.

Requires Windows 10/11 x64, Internet for first setup, and about 15 GB of free scratch space during the build (released afterwards). A build takes several minutes; the log shows each step.

## What it builds

Five cockpits: F4F-3 -> P51B5 slot, F4U-4 -> P47D22, SBD-3 -> IL2M42, A6M3 Model 22 -> Fw190A5, Ki-61-I Tei -> Bf109F4 (WT 27 host; MC202s8 on WT 18 to WT 26). On a re-hosted slot the cockpit is built in the frame of the old host and gets the same Scene Root fit as the base cockpit (WT 27 Bf109F4: pitch -3.29 deg); GunsightPosition, the pilot bot head position and CloseSphere follow that fit. Sights, gauges, normals and animation bindings are converted to native IL-2 materials and passes. The SBD keeps the base's native rear turret, guns and crew/camera attachments. J2M2, SB2C and D4Y have no slot and are not added.

Plane scripts are taken from the selected base; only the `GunsightPosition` line changes. No exterior meshes are written.

## Current state

- **Canopy glass:** the new CanopyGlass chunk of the F4F, F4U and SBD cockpits takes the glass of the base pit's WT glass chunk: texture (shared WT atlas or a pit-only `<atlas>_C`), u8 and CanopyGlass constants. On WT 27 bases these are the vanilla P-51D constants (TEST 4); JH v2.6.3 and later carry the base glass fix.
- **Kept base pit nodes:** every base pit node is hidden (arg 55) except `keep_base_nodes` of the slot in `toolkit\slots.json`. F4U (P47D22): `WT_fuse_1`, `WT_fuse_6`, `WT_fuse_14`, the WT forward-fuselage shell that fills the exterior fuselage hidden in cockpit view (without it the exterior engine damage cap shows through the nose).
- **Bases:** no version gate. The build stops only when a file it needs is missing or unreadable (the five cockpit slots' -C.mgm, -C.txt, plane script and its pilot bot, the Type98 donor mesh). Differences from the tested placement data (`toolkitase_contract.py`) are log lines.
- **Delta pack:** the pack holds only files the builder creates (Aces cockpit meshes, textures, a modified mesh where a reflector is hidden). No base file copies: plane scripts, pilot bots and -C.txt stay the base's; their view lines (GunsightPosition, bot [attach=0] position, CloseSphere) are in `aces_gunsight_delta.json`, applied to the live base files by the JH launcher at play time. `aces_pack_base.json` lists the sha256 of the base files the pack was built from; `PACKAGE_SHA256.json` lists every shipped file.
- **WT collimator cards:** on WT 27 the opaque WT collimator card is hidden (visibility track only, native optical passes kept) in Bf110E2-C, IL2m44-C, LaGG3s29-C, MosquitoFBMkVIs2-C and Yak1s69-C (`reflector_hide` in `toolkit\slots.json`; the build stops if a listed slot has no card).
- **No configuration unpack:** `aces.vromfs.bin` is not unpacked. The few values used (eye positions, SBD reticle scale, SBD gunner eye) are in `toolkit\aces_cockpit_params.json`. The archive is only checked to exist, as an install check. Cockpit `.grp`/`.dxp.bin` packs are read directly.
- **Scratch cleanup:** after a successful build the raw resources, review exports (GLB/OBJ/DMF), textures, cache and the scratch package copy in `.work` are deleted. Reports, `build-config.json` and `BUILD_RESULT.json` stay. A failed build keeps everything for diagnosis.
- **Texture limit:** every texture fits the 26,000,000-byte engine resource limit and passes DDS validation and offscreen D3D11 upload. Large normals use BC3 with full mip chains; an 8192 atlas uses its 4096 mip.

## Folders

The builder reads the source games and the selected base and writes only to its own `.tools`, `.jobs`, `.work` folders and the new output folder. Existing output folders are refused. It does not enable JSGME mods, start the game or install loader files. Logs: `.jobs`. Reports: `.work`.

## Not checked by the builder

Sight magnification and calibration, gauge ranges, night lighting, damage states and the canopy glass look need an in-game check.

## Sources

[wt-asset-explorer](https://github.com/NotNekroz/wt-asset-explorer) commit `99c794ab102785c39e628033a09bf4ff18dbe64e` (not included: downloaded at setup, then the builder's edits in `toolkitackend_patches.json` are applied), [Microsoft DirectXTex texconv](https://github.com/microsoft/DirectXTex/releases/tag/may2026), [Python 3.11.9](https://www.python.org/downloads/release/python-3119/), PyPI packages pinned in `toolkit\requirements.txt`. Download hashes are fixed in the setup scripts. The NumPy ACL decoder is ported from the MIT-licensed Animation Compression Library (`toolkit\ACL_LICENSE.txt`). Earlier versions used wt_ext_cli to unpack `aces.vromfs.bin`; it is no longer downloaded or run.
