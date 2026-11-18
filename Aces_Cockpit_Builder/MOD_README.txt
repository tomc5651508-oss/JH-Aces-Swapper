JH_PR_2.5 WT - Aces Cockpits and Optics

BUILT LOCALLY FROM YOUR OWN COPY - PERSONAL USE ONLY - DO NOT REDISTRIBUTE THIS GENERATED FOLDER.
This folder was made on your PC by the Aces Cockpit Builder from your own Aces of Thunder and IL-2
Great Battles installs. It contains material owned by Gaijin Entertainment and by the IL-2 Great Battles
developers. Do not upload, share or sell it. See NOTICE.txt (who owns what, why, and the rules).

Install: inactive overlay. With IL-2 closed, disable earlier Aces TEST overlays, then enable this folder
in JSGME after the JH 2.5 WT base selected at build time (see BUILD_RESULT.json). Disable it to roll back.
The builder does not enable mods or change live game data.

Cockpits:
  F4F-3            -> Wildcat F4F-4 / P51B5 slot
  F4U-4            -> Corsair F4U-1D / P47D22 slot
  SBD-3 Dauntless  -> IL2M42 slot
  A6M3 Model 22    -> Fw190A5 slot
  Ki-61-I Tei      -> Ki-61 Ko / Bf109F4 slot (WT 27; MC202s8 on WT 18 to WT 26)
  WT collimator card hide (visibility only, native optical passes kept): Bf110E2, IL2m44, LaGG3s29,
  MosquitoFBMkVIs2, Yak1s69 cockpits (WT 27).
Exterior meshes, flight models, weapons and systems come from the base. J2M2, SB2C and D4Y have no slot.

Current state:
- Canopy glass (TEST 4 fix): F4F, F4U and SBD canopy glass uses the uniform WT glass texture with the
  vanilla P-51D CanopyGlass material constants (no ring/lensing pattern from WT constants).
- For the WT base only. Never enable it over a 'JH_PR_2.5 Jungle Hawks - 1946' build: its plane scripts
  are WT base scripts.
- Plane scripts are the selected base's scripts; only GunsightPosition changes. Enabling this folder over a
  newer base than the one it was built on brings back that older base's plane scripts and cockpit donors -
  rebuild against your current base instead.
- Built without unpacking aces.vromfs.bin; eye and reticle values come from the builder's params file.
- Extracted source files were deleted from the builder's scratch folder after the build unless
  "Keep extracted source files" was selected.
- Every texture fits the 26,000,000-byte engine limit and passed DDS and D3D11 upload checks.

Needs an in-game check: sight magnification and calibration, gauge ranges, switches, night and damage
states, canopy glass look. Static checks only; nothing here is flight-tested by the builder.

BUILD_RESULT.json: inputs and report location. PACKAGE_SHA256.json: hashes of every generated file.
