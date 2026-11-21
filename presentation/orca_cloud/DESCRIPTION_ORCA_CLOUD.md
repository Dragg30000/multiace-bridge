## multiACE Bridge (Snapmaker U1)

> **multiACE is decay71's project**: his code does all the real work. This plugin is only an interface to it inside OrcaSlicer. All credit goes to him and the multiACE contributors.
> **multiACE est le projet de decay71** : c'est son code qui fait tout le travail. Ce plugin n'en est qu'une interface dans OrcaSlicer.

> ⚠ **Requires multiACE (by decay71) installed on your Snapmaker U1**: the plugin is only an interface, it does nothing without it. Tested on **multiACE 1.27b and multiACE+ 1.90** (older versions: export goes to multiACE's own Preflight).

Control a **Snapmaker U1 running multiACE** (1 to 4 ACE Pro) from one panel inside OrcaSlicer: no more juggling between Orca, Fluidd and the multiACE web UI.

![01_panneau_haut.webp](https://api.orcaslicer.com/api/v1/bundles/media/3305e43d-b2f2-46ed-9cd2-c4bfa55775dc/content){align=center}

### Features

- **Live panel**: heads and ACEs, real spool colours, remaining weight, 💧 humidity, 🌡 temperature, drying progress.
- **Queue**: load, swap, unload, dry; actions run one after another, auto homing when needed.
- **Spool editor**, even without RFID, linked to the multiACE spool table. PA calibration stored per spool.
- **"Path not calibrated"** badge on slots whose Bowden path isn't calibrated in multiACE (Config → Calibration).

![11_ace_sechage.webp](https://api.orcaslicer.com/api/v1/bundles/media/3feb108e-28ce-4b9b-a1fa-b90aa509bfae/content){align=center}

![03_editeur.webp](https://api.orcaslicer.com/api/v1/bundles/media/35a0beaf-a852-4ec0-a0ce-ebf67567c268/content){align=center}

- **Compact mode** that keeps colours visible, foldable modules, action menu on click.
- **U1 camera and touchscreen** in the panel (top, bottom or hidden).
- **Starts with Orca**, **⚙ Options** at the top, a **U1 address** box when the printer can't be found, and the **pipeline step added to your U1 process preset** automatically (save the preset to keep it).
- **English or French interface** (⚙ Options → Language; Auto follows Windows).

![05_mode_reduit.webp](https://api.orcaslicer.com/api/v1/bundles/media/3c09eb33-e0f7-4016-be70-a705689c3420/content){align=center}

![08_camera.webp](https://api.orcaslicer.com/api/v1/bundles/media/3c8dce5e-d3c6-4e82-a06a-15a040b9eda3/content){align=center}

![16_options.webp](https://api.orcaslicer.com/api/v1/bundles/media/3e7bdd7a-8cdc-4886-959a-fcc24e32d81f/content){align=center}

- **Export with your U1's own multiACE Preflight**: the plugin runs the Preflight code served by your U1 (your multiACE version) after checks. The window shows the U1's plans with **its time estimate** (multiACE+ 1.90), only the filaments really printed, **warns when a colour lands on a different High flow / Standard nozzle**, lets you **force a spool** (applied as is by the U1), and offers at print start a **bed mesh on the printed area**, **PA head by head** and a **soft start**. Otherwise the original G-code goes to multiACE's Preflight. No assignment logic of its own, export never modified.
- **Optimized plan, even when the loaded spools don't fit**: the U1 code proposes a spool layout. Follow the steps, click **"Done"** after each move (colour, material and spool entry follow the spool), printing waits until everything is in place.
- **Put in the multiACE queue** (multiACE+ 1.90 Print Hub): print it later from multiACE, the U1 checks the spools again at launch.

![18_preflight_u1.webp](https://api.orcaslicer.com/api/v1/bundles/media/3d25495c-5fb8-4601-8322-9c9d5a54dd29/content){align=center}

![18b_forcer_bobine.webp](https://api.orcaslicer.com/api/v1/bundles/media/36c21bd7-d69d-428c-8e0d-353718312d9b/content){align=center}

![18c_au_lancement.webp](https://api.orcaslicer.com/api/v1/bundles/media/3f960206-e260-4add-86c8-383c4b8c598d/content){align=center}

- **"Before slicing" assistant**: reads the nozzles fitted on the U1 and tells you what to set in Orca (Standard / High Flow). With 5 filaments or more (multiACE+ 1.90 virtual tools), shows where each one goes (MMU / slot) and whether the right colour is loaded.
- **ACE guard**: if an ACE drops its USB link, drying and filament feed are restarted (only for the printing head).

![09_avant_de_trancher.webp](https://api.orcaslicer.com/api/v1/bundles/media/35573bb6-7002-4943-b6c5-dc21090dc6de/content){align=center}

![10_garde_fou.webp](https://api.orcaslicer.com/api/v1/bundles/media/38118d76-3ec1-4b1c-9627-f57600096e2c/content){align=center}

### Requirements

- OrcaSlicer **2.5**
- Snapmaker **U1** + **multiACE 1.27b or newer** (tested on 1.27b and multiACE+ 1.90 with the paxx12 Extended firmware; the remote screen needs Extended with "Remote Screen" enabled)
- Tested with 2 ACE Pro on a USB hub. Feedback welcome with 3–4 ACEs, ACE 2 or other nozzle setups.

### Privacy

Talks **only to your U1 on your local network**. Only runs the Preflight served by your own U1, after checks.

### ⚠️ Disclaimer / Avertissement

Beta, provided **as is, without any warranty** (GPL-3.0). **Use at your own risk**: the author cannot be held liable for any damage to the printer, ACEs, spools or prints. Always check before starting a print.
Bêta fournie **telle quelle, sans garantie**. **À vos risques et périls** : l'auteur ne peut être tenu responsable d'aucun dommage.

### Bugs & feedback

GitHub: https://github.com/Dragg30000/multiace-bridge · report a bug: https://github.com/Dragg30000/multiace-bridge/issues

### Thanks

**decay71** and the multiACE contributors, the **OrcaSlicer** team, and **paxx**.

### ☕ Support

The plugin is free. If it helps you, a tip is welcome: **https://ko-fi.com/dragg**
And please support **multiACE by decay71** too, it does all the real work: https://github.com/decay71/multiACE
Le plugin est gratuit : un pourboire sur Ko-fi fait plaisir, et pensez aussi à soutenir multiACE de decay71.

*Interface in English or French.* — Dragg with his friend Claude