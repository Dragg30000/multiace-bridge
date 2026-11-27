## multiACE Bridge (Snapmaker U1)

> **multiACE is decay71's project**: his code does all the real work. This plugin is only an interface to it inside OrcaSlicer. All credit goes to him and the multiACE contributors.
> **multiACE est le projet de decay71** : c'est son code qui fait tout le travail. Ce plugin n'en est qu'une interface dans OrcaSlicer.

> ⚠ **Requires multiACE (by decay71) installed on your Snapmaker U1**: the plugin is only an interface, it does nothing without it. Tested on **multiACE 1.27b, multiACE+ 1.90 and 1.91** (older versions: export goes to multiACE's own Preflight).

Control a **Snapmaker U1 running multiACE** (1 to 4 ACE Pro) from one panel inside OrcaSlicer: no more juggling between Orca, Fluidd and the multiACE web UI. New in 0.47: the print window follows the U1 when spools change, shows the grams with the purge, lets you look at the U1 (touchscreen, cameras, light, multiACE panel) and warns when two filaments share a colour.

![01_cover.jpg](https://api.orcaslicer.com/api/v1/bundles/media/38d09c9e-0fa6-4ff8-9550-1b971cdb28a8/content){align=center}

### Live panel: the lanes map

- **The same map for 1 to 4 ACEs**: the 4 heads on top, one row per ACE. A solid line is the spool loaded in the head, a dotted line a queued load, an orange diamond a path not calibrated in multiACE.
- **Click a spool or a head** to load, swap, unload, calibrate the flow (PA) or edit it. Actions run one after another in a queue, with auto homing when needed.
- **Spool editor**, even without RFID, linked to the multiACE spool table; PA stored per spool.
- **Several spools of the same colour**: a spool already in another lane can be picked again; a matching entry is created for this lane, with its stored PA.
- **💧 Humidity, 🌡 temperature and drying** in each ACE's row, **from 1 h to 7 days**: beyond 10 h, in 10 h cycles that the plugin restarts while OrcaSlicer is open.
- **Auto-dry with an ACE 2 Pro** (shown only when one is connected): it dries by itself above one humidity level and stops below another. An ACE Pro, which has no humidity sensor, can follow it and run on after it. multiACE does the drying on the U1, even with OrcaSlicer closed.

![13_lanes_map.jpg](https://api.orcaslicer.com/api/v1/bundles/media/3c963622-651d-4d77-91f4-4c0e25f8e334/content){align=center}

![20_spool_copy.jpg](https://api.orcaslicer.com/api/v1/bundles/media/30709573-be66-41ac-a04d-36370f97bbc7/content){align=center}

![21_long_drying.jpg](https://api.orcaslicer.com/api/v1/bundles/media/394d219b-1ae1-4437-9699-a28b015da7c1/content){align=center}

![24_auto_dry.jpg](https://api.orcaslicer.com/api/v1/bundles/media/3a60b500-5c76-48df-9f5b-f3394d097ed9/content){align=center}

### Export with your U1's own multiACE Preflight

On export, the plugin runs **the Preflight code served by your U1** (your multiACE version) after checks. The U1 decides, the plugin shows it, applies your choices and checks. No assignment logic of its own, your export is never modified; if anything doesn't match, the original G-code goes to multiACE's Preflight.

- **The U1's plans side by side** (as sliced / optimized / per layer): time, swaps, purge, and one bar per head along the print, where each colour change is a spool swap.

![14_print_window.jpg](https://api.orcaslicer.com/api/v1/bundles/media/38eed66c-ed7c-458a-91e3-3e7418716329/content){align=center}

- **Preview in your spool colours**: the G-code thumbnail is repainted with the colours of the spools of the plan shown, a bit more vivid than Orca's thumbnail, and follows your choices. Click it for the project colours. An approximation: the image is repainted, not rendered again.
- **Filament left, purge included**: grams per colour and per spool ("23 g / 500 g"), and a warning when a spool runs short, from the weight in the multiACE spool table.
- **Same colour twice**: a **!** on the preview when two filaments of the project share a colour.

![22_preview_filament.jpg](https://api.orcaslicer.com/api/v1/bundles/media/36cf6731-5fca-479a-ae27-cd7fd91bf516/content){align=center}

- **Printer settings**, read from the U1 and saved on it in one click, like on its screen: Air-Print Detection and Quad Replenish (multiACE), U1 auto-refill, light off when done, spaghetti and bed-object detection with their sensitivity (low/high). Settings the U1 doesn't know aren't shown.

![23_printer_settings.jpg](https://api.orcaslicer.com/api/v1/bundles/media/3314fb54-fd81-4ab7-a90e-34a02991e541/content){align=center}

- **Unload at the end**: no head, all of them, or one head fed by an ACE, for this print only. Right after the print, multiACE unloads them like the panel's Unload button and sends the filament back to the ACE.

![25_unload_at_end.jpg](https://api.orcaslicer.com/api/v1/bundles/media/3f0020da-b77d-47ac-a880-d2c997033527/content){align=center}

- **The window follows the U1**: spools changed on the U1 are picked up within seconds and the plans recomputed; your choices stay.
- **Look at the U1** from the window: touchscreen, cameras with the light switch, multiACE panel.

- **Place step by step**: when the optimized plan moves spools, one move at a time with an arrow on the map and a **"Done"** button. If the spool feeds a loaded head, **"Unload Tn"** is right there. Printing waits until everything is in place.

![15_step_by_step.jpg](https://api.orcaslicer.com/api/v1/bundles/media/3f1a6d85-04c2-4cf6-a58a-b0b03323a57e/content){align=center}

- **Colours that differ from your project**: the window tells you which filament will print in which colour, on each plan, on the map and next to the print button. Nothing is blocked. One click to the optimized plan when it gives the right colours; otherwise it tells you what to fetch and where to put it.

![16_colour_warning.jpg](https://api.orcaslicer.com/api/v1/bundles/media/3a219415-bbf9-44fe-8ca7-853461606eb9/content){align=center}

![17_what_to_place.jpg](https://api.orcaslicer.com/api/v1/bundles/media/34aeac57-10db-4865-81ad-3e330cfd728e/content){align=center}

- **Empty head at start**: the U1's start sequence can stop on an empty head (error 523) before multiACE loads it, so the window offers **"Load Tn from ACE x, lane y"**.

![18_empty_head.jpg](https://api.orcaslicer.com/api/v1/bundles/media/3b63cf64-f7c3-45c7-b926-61fb145433be/content){align=center}

- **Head mode** (one ACE per head, 4-to-1 combiner, side feeders), and multi mode with colour copies, a hand-fed head or background swaps (ACE 2 Pro): one column per head, the U1's plans *As loaded*, *Optimized*, *Per layer* and *Less mixing*, and the swaps run in the background. Proposed plans come with the moves to make. The file is rewritten by the U1 code, byte-identical to multiACE's web Preflight. Not tried yet on a real U1 in head mode: if in doubt, use **"Open in multiACE Preflight"**.

![19_head_mode.jpg](https://api.orcaslicer.com/api/v1/bundles/media/3d384f9c-91aa-4ffa-8fd7-5ea4dfdb489a/content){align=center}

- **High flow / Standard nozzle warning**, **force a spool** per filament (applied as is by the U1), **print start options** (bed mesh on the printed area, PA head by head, soft travel to the purge line, time-lapse), **U1 time estimate**, **multiACE queue** (Print Hub), **send without printing**.
- **Launch animation**: Mange-3MF eats your G-code when the print starts.

![12_lancement.jpg](https://api.orcaslicer.com/api/v1/bundles/media/3024a1f6-a2db-4ff0-80ad-159fa7567eeb/content){align=center}

### Also in the panel

- **"Before slicing" assistant**: reads the nozzles fitted on the U1 and tells you what to set in Orca (Standard / High Flow). With 5 filaments or more (multiACE+ 1.90 virtual tools), shows where each one goes and whether the right colour is loaded.
- **ACE guard**: if an ACE drops its USB link, drying and filament feed are restarted.
- **U1 camera and touchscreen** in the panel, **compact mode**, **⚙ Options**, a **U1 address** box when the printer can't be found, and the **pipeline step added to your U1 process preset** automatically (save the preset to keep it).
- **English or French interface** (⚙ Options → Language; Auto follows Windows).

### Requirements

- OrcaSlicer **2.5**
- Snapmaker **U1** + **multiACE 1.27b or newer** (tested on 1.27b, multiACE+ 1.90 and 1.91 with the paxx12 Extended firmware; the remote screen needs Extended with "Remote Screen" enabled)
- Tested with 2 ACE Pro on a USB hub. Feedback welcome with 3–4 ACEs, an ACE 2 Pro (auto-dry), head mode or other nozzle setups.

### Privacy

Talks **only to your U1 on your local network**. Only runs the Preflight served by your own U1, after checks.

### ⚠️ Disclaimer / Avertissement

Beta, provided **as is, without any warranty** (GPL-3.0). **Use at your own risk**: the author cannot be held liable for any damage to the printer, ACEs, spools or prints. Always check before starting a print.
Bêta fournie **telle quelle, sans garantie**. **À vos risques et périls** : l'auteur ne peut être tenu responsable d'aucun dommage.

### Bugs & feedback

GitHub: https://github.com/Dragg30000/multiace-bridge · report a bug: https://github.com/Dragg30000/multiace-bridge/issues

### Thanks

**decay71** and the multiACE contributors, the **OrcaSlicer** team, and **paxx**. Fonts: modified versions of **Hubot Sans** and **Mona Sans** by GitHub (SIL Open Font License 1.1), renamed "MB Display" and "MB Text".

### ☕ Support

The plugin is free. If it helps you, a tip is welcome: **https://ko-fi.com/dragg**
And please support **multiACE by decay71** too, it does all the real work: https://github.com/decay71/multiACE
Le plugin est gratuit : un pourboire sur Ko-fi fait plaisir, et pensez aussi à soutenir multiACE de decay71.

*Interface in English or French.* — Dragg with his friend Claude
