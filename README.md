# multiACE Bridge

**OrcaSlicer 2.5 plugin: an interface for [multiACE](https://github.com/decay71/multiACE) on the Snapmaker U1.**

> **multiACE is decay71's project.** His code does all the real work; this plugin only brings it into OrcaSlicer. All credit goes to decay71 and the multiACE contributors.
> **multiACE est le projet de decay71.** C'est son code qui fait tout le travail ; ce plugin n'en est qu'une interface dans OrcaSlicer.

![multiACE panel](presentation/images/01_panneau_haut.png)

## Features / Fonctions

- Live multiACE panel inside Orca: heads, ACEs, real spool colours, humidity, temperature, drying
- Action queue (load, swap, unload, dry), spool editor without RFID, PA calibration per spool
- Compact mode, foldable modules, U1 camera and touchscreen in the panel
- "Before slicing" assistant: reads the nozzles fitted on the U1 (Standard / High Flow)
- Colour-to-spool assignment on export (multiACE 1.27b engine by decay71, included unchanged), nozzle check, placement plan
- Start options: bed mesh, flow calibration, time-lapse, soft move to the purge line
- ACE guard: restarts drying and filament feed after an ACE disconnect

Full presentation: [EN slides](presentation/multiACE_Bridge_slides_EN.pdf) · [diaporama FR](presentation/multiACE_Bridge_diaporama_FR.pdf) · guides in [docs/](docs/).
The interface is in French for now.

## Install / Installation

**Orca Cloud:** File → Plugins → Browse plugins → *multiACE Bridge* → Subscribe → Activate.

**Manual:** download `multiace_bridge-<version>-py3-none-any.whl`, then Orca → File → Plugins → *Install local plugin* → restart Orca → allow network access to your U1.

Requirements: OrcaSlicer 2.5, Snapmaker U1, multiACE (tested on 1.27b, paxx firmware). Tested with 2 ACE Pro on a USB hub.

## Bugs & feedback

Open an [issue](../../issues/new/choose) with your plugin, Orca and multiACE versions, number of ACEs and nozzle types. Ouvrez une *issue*, en français ou en anglais.

## Privacy

The plugin only talks to the U1 address you enter, on your local network. It does not download or run any code from the network.

## ⚠️ Disclaimer / Avertissement

Beta software provided **as is, without any warranty** (GPL-3.0). **Use at your own risk**: the author cannot be held liable for any damage to the printer, ACEs, spools or prints.
Bêta fournie **telle quelle, sans garantie**. **À vos risques et périls.**

## Credits

- **decay71** and the multiACE contributors: [decay71/multiACE](https://github.com/decay71/multiACE) (GPL-3.0). `multiace_engine_127.py` is their post-processor, unchanged.
- The **OrcaSlicer** team for the plugin system, and **paxx** for the firmware.

License: GPL-3.0. — Dragg with his friend Claude
