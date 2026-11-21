# /// script
# requires-python = ">=3.12"
#
# [tool.orcaslicer.plugin]
# name = "multiACE Bridge (Snapmaker U1)"
# description = "Interface pour multiACE de decay71 (Snapmaker U1) dans OrcaSlicer : panneau ACE, interface web multiACE en onglet, et envoi de l'export au Preflight de multiACE."
# author = "Dragg avec son ami Claude"
# version = "0.38.1"
# ///
"""multiACE Bridge - relie OrcaSlicer 2.5 a multiACE (decay71/multiACE) sur une Snapmaker U1.

Capacites :

* Onglet "multiACE" : l'interface web de multiACE (http://<U1>/multiace/) dans OrcaSlicer.
* Panneau ACE ancre : tetes, bobines, poids, sechage, ecran de la U1 ; charger / echanger /
  decharger / secher / calibrer dans une file d'attente ; homing automatique en option ;
  edition des slots et association des bobines de la table multiACE (slots sans RFID).
* Pipeline "multiACE : envoyer au Preflight" : a l'export, le plugin execute le Preflight fourni par
  la U1 (code multiACE de sa version, /api/preflight/pysrc + livedata), sans logique d'attribution
  propre, verifie tout puis imprime. Fenetre : plans de la U1, bobines imposees par l'utilisateur
  (remap_override du code multiACE, comme son interface web), alerte buse Haut debit / Standard,
  PA memorise par bobine et « Calibrer avant », maillage limite a la zone imprimee, flux par tete,
  envoi sans lancer. Si une verification echoue, le G-code original part dans le Preflight de
  multiACE (/api/preflight/inbox).
* Script "multiACE : renvoyer le dernier G-code".

Plugin communautaire, non officiel, sans lien avec Snapmaker ou OrcaSlicer. multiACE est le
projet de decay71 (github.com/decay71/multiACE) : ce plugin n'en est qu'une interface dans Orca.
Licence GPL-3.0, comme multiACE.
"""

import ast
import hashlib
import importlib.util
import inspect
import json
import os
import sys
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

import orca

VERSION = "0.38.1"
TIMEOUT_UI = 4          # secondes, appels faits sur le fil de l'interface
TIMEOUT_BG = 8          # secondes, appels en arriere-plan

# Arret du plugin (desinstallation, desactivation, fermeture d'OrcaSlicer) : OrcaSlicer appelle on_unload
# sur chaque capacite ; tous les fils de fond s'arretent alors (plus aucun appel reseau ensuite).
_STOP = threading.Event()


def plugin_shutdown():
    _STOP.set()
UPLOAD_TIMEOUT = 300    # secondes, envoi d'un gros G-code
BUNDLE_ID = "multiace-bridge"
NOZZLES = ("0.2", "0.4", "0.6", "0.8")
NOZZLE_CHOICES = ("Standard", "Haut débit")   # buses reelles possibles d'une tete de la U1
NOZZLE_BLOCK_G = 5      # g : un filament plus lourd sur le mauvais type de buse bloque l'envoi (sauf confirmation)
PROCESSED_MARKERS = ("; multiACE processed:", "; multiACE auto-load:")
U1CONTROL_MARKER = "; u1control:"

# Pas de proxy systeme : l'imprimante est sur le reseau local.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


# --------------------------------------------------------------------------- stockage

_storage_cache = None


def storage_dir():
    global _storage_cache
    if _storage_cache is None:
        path = orca.host.plugin.storage()
        if not path:
            raise RuntimeError("dossier de stockage du plugin indisponible")
        os.makedirs(path, exist_ok=True)
        _storage_cache = path
    return _storage_cache


def _settings_path():
    """Reglages hors du dossier du plugin : ils survivent a une desinstallation / reinstallation."""
    root = storage_dir()
    parts = root.replace("\\", "/").split("/")
    if "orca_plugins" in parts:
        stable_dir = os.path.join("/".join(parts[: parts.index("orca_plugins")]) or "/", "multiace_bridge")
        stable = os.path.join(stable_dir, "settings.json")
        old = os.path.join(root, "settings.json")
        if not os.path.exists(stable) and os.path.exists(old):
            try:
                os.makedirs(stable_dir, exist_ok=True)
                with open(old, "rb") as src, open(stable, "wb") as dst:
                    dst.write(src.read())
            except OSError:
                return old
        return stable
    return os.path.join(root, "settings.json")


def load_settings():
    data = {}
    try:
        with open(_settings_path(), "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, ValueError):
        pass
    host = data.get("host") if isinstance(data.get("host"), str) else ""
    nozzle = data.get("nozzle") if data.get("nozzle") in NOZZLES else "0.4"
    auto_panel = data.get("auto_panel") if isinstance(data.get("auto_panel"), bool) else True
    auto_pipeline = data.get("auto_pipeline") if isinstance(data.get("auto_pipeline"), bool) else True
    popup = data.get("popup") if isinstance(data.get("popup"), bool) else True
    screen = data.get("screen") if data.get("screen") in ("off", "top", "bottom") else "off"
    camera = data.get("camera") if data.get("camera") in ("off", "top", "bottom") else "off"
    compact = data.get("compact") if isinstance(data.get("compact"), bool) else False
    prep_pos = data.get("prep_pos") if data.get("prep_pos") in ("top", "bottom") else "top"
    raw_folds = data.get("folds") if isinstance(data.get("folds"), dict) else {}
    folds = {k: v for k, v in list(raw_folds.items())[:12]
             if isinstance(k, str) and re.fullmatch(r"heads|prep|ace[0-7]", k) and isinstance(v, bool)}
    auto_home = data.get("auto_home") if isinstance(data.get("auto_home"), bool) else False
    ace_guard = data.get("ace_guard") if isinstance(data.get("ace_guard"), bool) else True
    u1_code = data.get("u1_code") if isinstance(data.get("u1_code"), bool) else True
    lang = data.get("lang") if data.get("lang") in ("auto", "fr", "en") else "auto"
    real = data.get("real_nozzles") if isinstance(data.get("real_nozzles"), list) else []
    real_nozzles = [(real[h] if h < len(real) and real[h] in NOZZLE_CHOICES else "") for h in range(4)]
    profile_base = data.get("profile_base") if isinstance(data.get("profile_base"), str) else ""
    filaments = [x for x in data.get("filaments") or [] if isinstance(x, str)][:16]
    return {"host": host, "nozzle": nozzle, "auto_panel": auto_panel, "popup": popup,
            "screen": screen, "camera": camera, "compact": compact, "prep_pos": prep_pos, "folds": folds,
            "profile_base": profile_base, "filaments": filaments, "auto_pipeline": auto_pipeline,
            "auto_home": auto_home, "ace_guard": ace_guard, "u1_code": u1_code,
            "real_nozzles": real_nozzles, "lang": lang}



# ---- langue de l'interface (fr par defaut ; en : table _I18N_EN appliquee a l'affichage)

LANGS = ("auto", "fr", "en")
_I18N_EN = {'impossible avec les bobines chargées': 'not possible with the loaded spools', 'aucune répartition possible sur les têtes': 'no possible head assignment', 'aucune répartition par couche possible': 'no per-layer assignment possible', 'aucune disposition par couche possible': 'no per-layer layout possible', 'plus de 4 couleurs dans une couche': 'more than 4 colours in a layer', 'trop de couleurs pour les têtes': 'too many colours for the heads', 'durée estimée par la U1': 'time estimated by the U1', 'd’échanges': 'of swaps', 'dont': 'incl.', 'purge': 'purge', 'impossible': 'not possible', ' filament(s) du projet non utilisé(s) dans ce fichier : masqué(s).': ' project filament(s) not used in this file: hidden.', 'autre copie': 'another copy', 'HAUT DÉBIT': 'HIGH FLOW', 'TRÈS HAUT DÉBIT': 'ULTRA HIGH FLOW', 'Avant de trancher': 'Before slicing', 'en attente': 'waiting', 'terminé': 'done', 'échoué': 'failed', 'annulé': 'cancelled', 'annulée': 'cancelled', 'nom de couleur proche': 'close colour name', 'couleur proche (nuance)': 'close colour (shade)', 'Automatique': 'Automatic', 'Retire %s de ACE': 'Remove %s from ACE', 'Par couche (layer)': 'Per layer (layer)', 'Disposition finale :': 'Final layout:', 'Au lancement': 'Print start', 'en place': 'in place', 'source inconnue': 'unknown source', 'Couleur': 'Colour', 'Marque': 'Brand', 'Poids': 'Weight', 'g restants': 'g left', 'buse': 'nozzle', 'absente': 'missing', 'Plans': 'Plans', 'Têtes': 'Heads', 'Calibration': 'Calibration', 'Mode': 'Mode', 'déconnecté': 'disconnected', 'Vérification': 'Check', 'Fichier': 'File', 'impression': 'printing', 'en impression': 'printing', 'pause': 'paused', 'Remplir': 'Fill', 'Charger tout': 'Load all', 'Tout charger': 'Load all', 'h restantes': 'h left', 'min restantes': 'min left', 'restant': 'left', 'restante': 'left', ' : ': ': ', ' ?': '?', ' ;': ';', 'Séchage': 'Drying', 'Bobine': 'Spool', 'Correspondance': 'Match', 'Actualiser': 'Refresh', 'Humidité dans l’ACE': 'Humidity in the ACE', 'Température dans l’ACE': 'Temperature in the ACE', 'Supprime la saisie manuelle': 'Removes the manual entry', 'sur T': 'on T', 'sur': 'on', 'Charge cette bobine sur T': 'Loads this spool on T', 'Bobine de la table multiACE associée à ce slot (utile sans RFID : poids, calibration PA mémorisée)': 'Spool from the multiACE table linked to this slot (useful without RFID: weight, stored PA calibration)', '« ': '“', ' »': '”', '«': '“', '»': '”', 'Confirmer ?': 'Confirm?', 'Agrandir': 'Expand', 'Retirer': 'Remove', 'Afficher': 'Show', 'hors ligne': 'offline', 'en cours': 'running', 'Adresse invalide': 'Invalid address', 'Déplacer cette carte': 'Move this card', '↑ en haut': '↑ to top', '↓ en bas': '↓ to bottom', 'Clique pour toucher l’écran de la U1': 'Click to touch the U1 screen', 'en haut': 'top', 'en bas': 'bottom', 'Recalculer avec mes choix': 'Recompute with my choices', 'Imprimer': 'Print', "multiACE : envoi direct a l'imprimante, Preflight non utilise": 'multiACE: direct upload to the printer, Preflight not used', 'multiACE : G-code deja traite par multiACE (script de post-traitement actif ?), non envoye': 'multiACE: G-code already processed by multiACE (post-processing script active?), not sent', 'multiACE : deja traite': 'multiACE: already processed', 'multiACE : %d filament(s) utilise(s), envoi reserve a %d et plus': 'multiACE: %d filament(s) used, sending is for %d or more', "Langue enregistrée : ferme et rouvre le panneau (ou redémarre OrcaSlicer) pour l'appliquer partout. / Language saved: close and reopen the panel (or restart OrcaSlicer) to apply it everywhere.": 'Language saved: close and reopen the panel (or restart OrcaSlicer) to apply it everywhere.', 'Clique sur une bobine pour modifier sa couleur, sa matière ou son poids. Clique deux fois sur un bouton pour confirmer une action. Charger / échanger / décharger / sécher / calibrer s’enchaînent dans une file d’attente (« Arrêter » le séchage part tout de suite).': 'Click a spool to change its colour, material or weight. Click a button twice to confirm an action. Load / swap / unload / dry / calibrate run one after another in a queue (“Stop” drying runs right away).', "Si un ACE se déconnecte puis revient : le plugin relance son séchage là où il en était, et pendant une impression il relance la poussée du filament, uniquement pour la tête qui imprime (si multiACE ne l'a pas déjà fait).": "If an ACE disconnects and comes back: the plugin restarts its drying where it was, and during a print it restarts the filament feed, only for the printing head (if multiACE hasn't already done it).", 'Choisis une bobine dans la dernière colonne pour imposer ta couleur : le plan passe sur « Comme tranché » et la U1 applique tes choix tels quels (comme dans son Preflight). Le type de buse de chaque tête est rappelé.': 'Pick a spool in the last column to force your colour: the plan switches to “As sliced” and the U1 applies your choices as is (like in its Preflight). Each head’s nozzle type is shown.', "À l'export, le plugin exécute dans Orca le Preflight fourni par ta U1 (code multiACE de ta version), vérifie tout puis imprime. Décoché : le fichier d'origine part dans le Preflight de multiACE, sans rien exécuter.": 'On export, the plugin runs inside Orca the Preflight served by your U1 (your multiACE version’s code), checks everything, then prints. Unticked: the original file goes to multiACE’s Preflight and nothing is run.', "Quand l'imprimante est une U1 et que le profil de traitement n'a pas l'étape « multiACE : envoyer au Preflight », le plugin l'ajoute. Le profil devient « modifié » : enregistre-le pour la garder.": 'When the printer is a U1 and the process preset lacks the “multiACE : envoyer au Preflight” step, the plugin adds it. The preset becomes “modified”: save it to keep the step.', "Calibration de ACE %d · slot %d sur T%d ajoutée à la file du panneau multiACE. Attends qu'elle soit finie, puis « Recharger » : le PA est mémorisé sur la bobine.": 'Calibration of ACE %d · slot %d on T%d added to the multiACE panel queue. Wait until it’s done, then “Reload”: the PA is stored on the spool.', "multiACE : acces reseau non autorise depuis le tranchage. Ouvre l'onglet multiACE, clique Enregistrer pour autoriser %s, puis renvoie depuis l'onglet.": 'multiACE: network access not allowed from slicing. Open the multiACE tab, click Save to allow %s, then resend from the tab.', 'multiACE : ce G-code a ete modifie par U1 Control ("U1 print setup"). Decoche-le pour ce profil afin que multiACE recoive l\'export original.': 'multiACE: this G-code was modified by U1 Control ("U1 print setup"). Untick it for this preset so multiACE gets the original export.', "OrcaSlicer n'a pas autorisé le plugin à ouvrir ses fichiers. Réexporte et réponds « Oui » à la demande d'autorisation (événement « open »).": 'OrcaSlicer didn’t allow the plugin to open its files. Export again and answer “Yes” to the permission request (“open” event).', 'Terminé : %s. Le capteur de %s indique encore du filament : si la tête est bien vide, ignore ce message ; sinon retire le reste à la main.': 'Done: %s. The %s sensor still reports filament: if the head is really empty, ignore this; otherwise remove the rest by hand.', 'Chargement automatique : les têtes vides ou avec une autre bobine au départ sont chargées depuis les ACE avant la première couche (': 'Auto-load: heads that are empty or hold another spool at start are loaded from the ACEs before the first layer (', "OrcaSlicer a bloqué l'accès réseau vers %s. Clique « Autoriser et réessayer » et accepte la demande d'OrcaSlicer (une seule fois).": 'OrcaSlicer blocked network access to %s. Click “Allow and retry” and accept OrcaSlicer’s request (only once).', 'OrcaSlicer te demande une autorisation pour le plugin (événement « open ») : réponds « Oui », la préparation continue toute seule.': 'OrcaSlicer is asking you for a permission for the plugin (“open” event): answer “Yes”, preparation goes on by itself.', "T%d : la poussée de l'ACE %d ne reprend pas après %d essais. Vérifie l'ACE (câble, hub) ; l'impression continue sans aide.": 'T%d: ACE %d feed doesn’t resume after %d tries. Check the ACE (cable, hub); the print goes on without assist.', 'Cette version de multiACE ne permet pas d’imposer une bobine depuis Orca : utilise « Ouvrir dans le Preflight multiACE ».': 'This multiACE version doesn’t allow forcing a spool from Orca: use “Open in multiACE Preflight”.', "Si la U1 n'a pas fait son homing, le plugin le fait tout seul avant de charger / échanger / décharger, sans te demander.": 'If the U1 isn’t homed, the plugin homes it by itself before load / swap / unload, without asking.', "%s : la U1 n'est pas référencée (homing). Clique « Faire le homing puis reprendre » : la U1 fait son Home puis reprend.": '%s: the U1 isn’t homed. Click “Home then resume”: the U1 homes and then resumes.', "la U1 n'est pas référencée (l'écran affiche « Axis Movement Anomaly ») : il faut un homing avant de bouger les têtes.": 'the U1 isn’t homed (the screen shows “Axis Movement Anomaly”): homing is needed before moving the heads.', '⚠ Pas de chargement automatique dans le fichier : vérifie que les bonnes bobines sont sur les têtes avant de lancer.': '⚠ No auto-load in the file: check the right spools are on the heads before printing.', 'Ancien profil « Snapmaker U1 multiACE » supprimé (il disparaît de la liste au plus tard au prochain démarrage).': 'Old “Snapmaker U1 multiACE” profile removed (it disappears from the list at the latest on next start).', "la U1 est %s : action refusée. Regarde l'écran de la U1 et l'interface multiACE, puis clique « Reprendre ».": 'the U1 is %s: action refused. Check the U1 screen and the multiACE interface, then click “Resume”.', 'Chargement automatique au départ : %s (têtes vides ou avec une autre bobine chargées avant la 1re couche).': 'Auto-load at start: %s (empty heads or heads with another spool loaded before the 1st layer).', "multiACE : impression préparée par le Preflight de la U1 (envoi direct d'OrcaSlicer annulé, c'est normal).": 'multiACE: print prepared by the U1 Preflight (OrcaSlicer’s direct upload cancelled, that’s normal).', '(le profil palpe tout le plateau : ajoute MESH_MIN / MESH_MAX, rien ne change si ton profil le fait déjà)': '(the preset probes the whole bed: adds MESH_MIN / MESH_MAX, nothing changes if your preset already does it)', "multiACE : envoi au Preflight impossible (%s). Le G-code est garde : renvoie-le depuis l'onglet multiACE.": 'multiACE: sending to the Preflight failed (%s). The G-code is kept: resend it from the multiACE tab.', "T%d ne reçoit plus de poussée de l'ACE %d, mais ce n'est pas l'ACE actif : rien envoyé par sécurité.": 'T%d no longer gets feed from ACE %d, but it isn’t the active ACE: nothing sent, for safety.', 'multiACE : adresse de la U1 inconnue : renseigne-la dans le panneau ACE (Options → Adresse de la U1)': 'multiACE: U1 address unknown: set it in the ACE panel (Options → U1 address)', "Chauffe le plateau, attend 2 min, mesure le maillage (AUTO_BED_MESH_CALIBRATE) ; la U1 l'enregistre": 'Heats the bed, waits 2 min, probes the mesh (AUTO_BED_MESH_CALIBRATE); the U1 saves it', 'Adresse de la U1 non renseignee : entre son IP dans le panneau ACE (Options → Adresse de la U1).': 'U1 address not set: enter its IP in the ACE panel (Options → U1 address).', "place d'abord les bobines comme dans la « Disposition finale » (filament %s), puis « Recharger »": 'first place the spools as in the “Final layout” (filament %s), then “Reload”', 'Pour OrcaSlicer, le filament N part sur TN ; en vrai, il part sur la tête du slot de sa bobine.': 'For OrcaSlicer, filament N goes to TN; in reality it goes to the head of its spool’s slot.', "ACE %d : le séchage s'est arrêté avant la fin (il restait %d min à %d °C). Coupure de l'ACE ?": 'ACE %d: drying stopped before the end (%d min left at %d °C). ACE dropout?', 'si besoin, puis mesure son PA (FLOW_CALIBRATE) et le mémorise sur la bobine pour cette buse': 'if needed, then measures its PA (FLOW_CALIBRATE) and stores it on the spool for this nozzle', "Entre l'adresse IP de ta U1 (affichée dans ses réglages réseau, par exemple 192.168.1.50).": 'Enter your U1’s IP address (shown in its network settings, e.g. 192.168.1.50).', "Klipper n'est pas prêt sur la U1 (redémarrage ou erreur en cours) : attends puis réessaie.": 'Klipper isn’t ready on the U1 (restart or error in progress): wait and try again.', '(après les calibrations : 100 mm/s, accélération réduite, buse remontée de 5 mm avant)': '(after calibrations: 100 mm/s, reduced acceleration, nozzle lifted 5 mm first)', ". Envoi direct d'OrcaSlicer annule : lance l'impression depuis le Preflight multiACE.": '. OrcaSlicer’s direct upload cancelled: start the print from the multiACE Preflight.', "%s envoyé sur la U1 sans lancer (%s) : lance-le depuis l'écran ou Fluidd.%s": '%s sent to the U1 without printing (%s): start it from the screen or Fluidd.%s', "Vérification : %s. Le fichier d'origine part dans le Preflight de multiACE.": 'Check: %s. The original file goes to the multiACE Preflight.', "les bobines ont changé depuis l'analyse : vérifie la nouvelle proposition": 'spools changed since the analysis: check the new proposal', 'Homing automatique activé : la U1 fera son homing toute seule si besoin.': 'Auto homing on: the U1 will home by itself when needed.', 'La U1 ne donne pas ses buses (firmware ancien) : ta saisie est utilisée.': 'The U1 doesn’t report its nozzles (old firmware): your input is used.', 'Buses de diamètres différents dans ce fichier : vérifie la proposition.': 'Nozzles of different diameters in this file: check the proposal.', 'Garde-fou activé : séchage et poussée relancés si un ACE se déconnecte.': 'Guard on: drying and feed restarted if an ACE disconnects.', ') : garde une seule copie de multiACE Bridge dans Fichier → Plugins.': '): keep a single copy of multiACE Bridge in File → Plugins.', "Pas de multiACE à %s : vérifie l'adresse (la U1 est-elle allumée ?)": 'No multiACE at %s: check the address (is the U1 on?)', 'Export : Preflight de la U1 exécuté dans Orca, avec vérifications.': 'Export: U1 Preflight run inside Orca, with checks.', "L'étape Preflight sera ajoutée aux profils de traitement de la U1.": 'The Preflight step will be added to the U1 process presets.', 'Vérification : %s. Utilise « Ouvrir dans le Preflight multiACE ».': 'Check: %s. Use “Open in multiACE Preflight”.', "les bobines imposées ne s'appliquent qu'au plan « Comme tranché »": 'forced spools only apply to the “As sliced” plan', 'Associe une bobine pour mémoriser le poids et la calibration PA.': 'Link a spool to store the weight and the PA calibration.', 'Indique une seule fois la buse vissée sur chaque tête de ta U1 :': 'Set once the nozzle fitted on each head of your U1:', 'multiACE : %d filament(s) utilise(s), envoi reserve a %d et plus': 'multiACE: %d filament(s) used, sending is for %d or more', 'multiACE : préparation avec le code multiACE de la U1 pour "%s"': 'multiACE: preparing with the U1’s multiACE code for "%s"', 'tête(s)), par le code multiACE de la U1. Vérifié avant l’envoi.': 'head(s)), by the U1’s multiACE code. Checked before sending.', 'Étape « multiACE : envoyer au Preflight » ajoutée au profil «': 'Step “multiACE : envoyer au Preflight” added to preset “', "cette version de multiACE ne permet pas d'imposer une bobine": 'this multiACE version doesn’t allow forcing a spool', "le fichier préparé n'a pas la marque multiACE : envoi annulé": 'the prepared file lacks the multiACE mark: sending cancelled', "Export : fichier d'origine envoyé au Preflight de multiACE.": 'Export: original file sent to the multiACE Preflight.', '%s a changé (%s) : version de multiACE non prise en charge': '%s changed (%s): multiACE version not supported', 'ACE %d revenu : séchage relancé (%d °C, %d min restantes).': 'ACE %d back: drying restarted (%d °C, %d min left).', 'Masquer le panneau (une notification permet de le rouvrir)': 'Hide the panel (a notification lets you reopen it)', 'Ajouté à la file d’attente : tu peux en ajouter d’autres.': 'Added to the queue: you can add more.', 'En partie lues dans la U1 ; le reste vient de ta saisie :': 'Partly read from the U1; the rest comes from your input:', 'Cliquer pour déplier / replier : couleur, matière, poids': 'Click to unfold / fold: colour, material, weight', 'bobine choisie absente des ACE : recharge la proposition': 'chosen spool not in the ACEs: reload the proposal', 'dans Paramètres › Firmware de la U1 (firmware Extended).': 'in the U1’s Settings › Firmware (Extended firmware).', 'Homing automatique désactivé : le panneau te demandera.': 'Auto homing off: the panel will ask you.', "La U1 termine une opération : l'action suivante attend…": 'The U1 is finishing an operation: the next action waits…', 'ce mode de têtes se règle dans le Preflight de multiACE': 'this head mode is set in the multiACE Preflight', 'une tête est en mode manuel : attribution indisponible': 'a head is in manual mode: assignment unavailable', 'Options (adresse de la U1, homing, garde-fou, export)': 'Options (U1 address, homing, guard, export)', '⚠ Mets ça à gauche (Imprimante → Buse) puis tranche :': '⚠ Set this on the left (Printer → Nozzle) then slice:', 'Le lancement attend que les bobines soient en place.': 'Printing waits until the spools are in place.', 'la U1 imprime : pas de homing pendant une impression': 'the U1 is printing: no homing during a print', 'le fichier utilise une bobine absente : envoi annulé': 'the file uses a missing spool: sending cancelled', 'reponse illisible de %s (multiACE est-il installe ?)': 'unreadable answer from %s (is multiACE installed?)', '%s absent (multiACE trop ancien pour cette méthode)': '%s missing (multiACE too old for this method)', 'Le plugin ne touche plus aux profils de traitement.': 'The plugin no longer touches process presets.', 'Étape Preflight : imprimante active autre que la U1': 'Preflight step: active printer is not the U1', ') : aucune bobine de cette couleur dans les ACE.': '): no spool of this colour in the ACEs.', "Garde-fou : relancer après une déconnexion d'ACE": 'Guard: restart after an ACE disconnect', "Préparer l'export avec le code multiACE de la U1": 'Prepare the export with the U1’s multiACE code', "Fichier d'origine envoyé au Preflight multiACE.": 'Original file sent to the multiACE Preflight.', 'Température et durée : dans le panneau complet.': 'Temperature and duration: in the full panel.', 'échange multiACE en cours depuis plus de 10 min': 'multiACE swap running for more than 10 min', '. Le plugin affiche et applique, la U1 décide.': '. The plugin shows and applies, the U1 decides.', "Ajouter l'étape Preflight aux profils de la U1": 'Add the Preflight step to the U1 presets', 'Mets une bobine dans ce slot pour l’utiliser.': 'Put a spool in this slot to use it.', '» : enregistre-le (disquette) pour la garder.': '”: save it (disk icon) to keep it.', 'ACE %d : relance du séchage impossible (%s).': 'ACE %d: drying restart failed (%s).', 'Caméra de la U1 : masquée / en haut / en bas': 'U1 camera: hidden / top / bottom', 'Pas encore de PA mémorisé pour cette bobine.': 'No PA stored for this spool yet.', 'T%d : relance de la poussée impossible (%s).': 'T%d: feed restart failed (%s).', 'multiACE : lecture du G-code impossible (%s)': 'multiACE: cannot read the G-code (%s)', 'Les bobines sont en place : tu peux lancer.': 'The spools are in place: you can print.', 'Préparation avec le code multiACE de la U1…': 'Preparing with the U1’s multiACE code…', 'code de la U1 impossible à enregistrer (%s)': 'cannot save the U1 code (%s)', 'filament(s) au-delà du 4e : non vérifié(s).': 'filament(s) beyond the 4th: not checked.', 'multiACE : "%s" envoye au Preflight de %s%s': 'multiACE: "%s" sent to the Preflight of %s%s', ': échanges de bobine pendant l’impression.': ': spool swaps during the print.', 'dossier de stockage du plugin indisponible': 'plugin storage folder unavailable', 'envoyé à multiACE, ouverture du Preflight…': 'sent to multiACE, opening the Preflight…', 'Écran de la U1 : masqué / en haut / en bas': 'U1 screen: hidden / top / bottom', 'Calcul fait par le code multiACE de ta U1': 'Computed by your U1’s multiACE code', 'Dernier export préparé par cette copie (v': 'Last export prepared by this copy (v', 'Poussée revenue sur T%d (ACE %d slot %d).': 'Feed back on T%d (ACE %d slot %d).', 'Une action est en cours : attends sa fin.': 'An action is running: wait for it to finish.', 'réponse inattendue de /preflight/livedata': 'unexpected answer from /preflight/livedata', 'T%d : poussée relancée (ACE %d slot %d).': 'T%d: feed restarted (ACE %d slot %d).', 'Température du plateau pendant la mesure': 'Bed temperature during probing', 'televersement vers la U1 impossible (%s)': 'upload to the U1 failed (%s)', '✓ buses d’OrcaSlicer OK pour tes bobines': '✓ OrcaSlicer nozzles OK for your spools', 'Déplacement doux vers la ligne d’amorce': 'Soft travel to the purge line', 'appliquer couleur / matière à la bobine': 'apply colour / material to the spool', 'la U1 ne fournit pas son Preflight (%s)': 'the U1 doesn’t serve its Preflight (%s)', 'le code de la U1 ne se charge pas (%s)': 'the U1 code doesn’t load (%s)', 'réponse inattendue de /preflight/pysrc': 'unexpected answer from /preflight/pysrc', 'Mesurées au départ (têtes chargées) :': 'Measured at start (loaded heads):', 'multiACE : renvoyer le dernier G-code': 'multiACE: resend the last G-code', '⚠ Le dernier export est passé par une': '⚠ The last export went through', 'Calibration du filament (PA) sur T%s': 'Filament (PA) calibration on T%s', 'Ouverture du panneau impossible : %s': 'Cannot open the panel: %s', 'Étape Preflight : ajout impossible (': 'Preflight step: cannot add it (', 'Caméra indisponible pour le moment.': 'Camera unavailable for now.', 'Modifier couleur / matière / poids…': 'Edit colour / material / weight…', 'le Preflight de la U1 a échoué (%s)': 'the U1 Preflight failed (%s)', "Aucun G-code garde pour l'instant.": 'No G-code kept yet.', 'Calibration du flux (PA) au départ': 'Flow (PA) calibration at start', 'J’ai placé les bobines : recharger': 'I placed the spools: reload', 'Reprise de la file (%d action(s)).': 'Queue resumed (%d action(s)).', '⚠ Buses à régler dans OrcaSlicer :': '⚠ Nozzles to set in OrcaSlicer:', 'Ouvrir dans le Preflight multiACE': 'Open in multiACE Preflight', '· arrive en cours d’impression (T': '· arrives during the print (T', '✓ Étape Preflight présente dans «': '✓ Preflight step present in “', '(aucune bobine associée au slot)': '(no spool linked to the slot)', 'Déchargement de toutes les têtes': 'Unloading all heads', 'Homing automatique si nécessaire': 'Auto homing when needed', 'multiACE : pas de fichier G-code': 'multiACE: no G-code file', '"%s" envoye au Preflight de %s.': '"%s" sent to the Preflight of %s.', 'Chargement T%s ← ACE %s slot %s': 'Loading T%s ← ACE %s slot %s', 'Calibration du plateau (%s °C)': 'Bed calibration (%s °C)', 'Faire le homing puis reprendre': 'Home then resume', "la U1 n'a pas répondu à temps.": 'the U1 didn’t answer in time.', ': aucune bobine dans les ACE.': ': no spool in the ACEs.', 'Bobine absente des ACE pour :': 'Spool missing from the ACEs for:', 'Envoyer sur la U1 sans lancer': 'Send to the U1 without printing', 'Toujours en cours sur la U1 :': 'Still running on the U1:', 'Une action est deja en cours.': 'An action is already running.', 'multiACE - Preflight de la U1': 'multiACE - U1 Preflight', 'occupée depuis plus de 10 min': 'busy for more than 10 min', 'Adresse de la U1 introuvable': 'U1 address not found', 'Impression lancée avec %s.%s': 'Print started with %s.%s', 'Rien à faire sur cette tête.': 'Nothing to do on this head.', 'tête(s) chargée(s) au départ': 'head(s) loaded at start', 'Échange T%s ← ACE %s slot %s': 'Swap T%s ← ACE %s slot %s', 'Étape Preflight absente de «': 'Preflight step missing from “', '(méthode de multiACE 1.27b)': '(multiACE 1.27b method)', "Modifier l'adresse de la U1": 'Change the U1 address', 'même matière, autre couleur': 'same material, other colour', 'Écran distant indisponible.': 'Remote screen unavailable.', 'Étape Preflight ajoutée à «': 'Preflight step added to “', '✓ Buses OK pour tes bobines': '✓ Nozzles OK for your spools', '(disquette) pour la garder': '(disk icon) to keep it', 'Calibrer cette bobine (PA)': 'Calibrate this spool (PA)', 'Séchage ACE %s (%s °C, %s)': 'Drying ACE %s (%s °C, %s)', 'seulement la zone imprimée': 'printed area only', 'Commande envoyée à la U1…': 'Command sent to the U1…', 'Matière absente des ACE :': 'Material missing from the ACEs:', 'Pose de côté la bobine de': 'Set aside the spool from', 'Revenir au choix de la U1': 'Back to the U1’s choice', 'choix de bobine illisible': 'unreadable spool choice', 'code de la U1 non reconnu': 'U1 code not recognised', 'Panneau multiACE masqué.': 'multiACE panel hidden.', 'échanges de bobine (ACE)': 'spool swaps (ACE)', ': tranché pour une buse': ': sliced for nozzle', 'Arrêt du séchage ACE %s': 'Stop drying ACE %s', 'code de la U1 illisible': 'unreadable U1 code', 'code de la U1 trop gros': 'U1 code too large', 'et tes bobines imposées': 'and your forced spools', 'Calibration du plateau': 'Bed calibration', 'Comme tranché (slicer)': 'As sliced (slicer)', 'la U1 est occupée (%s)': 'the U1 is busy (%s)', '— avant la mise à jour': '— before the update', 'Adresse enregistrée :': 'Address saved:', 'Connexion à multiACE…': 'Connecting to multiACE…', 'La U1 ne répond pas à': 'The U1 doesn’t answer at', 'Ma U1 (buses vissées)': 'My U1 (fitted nozzles)', 'couleur(s) du fichier': 'colour(s) in the file', ": vérifie l'adresse.": ': check the address.', 'Garde-fou désactivé.': 'Guard off.', 'disposition proposée': 'proposed layout', 'enregistre le profil': 'save the preset', 'fichier préparé vide': 'prepared file empty', '(clic pour changer)': '(click to change)', 'Détail par filament': 'Per-filament detail', 'Lancer l’impression': 'Start the print', 'Optimisé (optimize)': 'Optimized (optimize)', 'Relancer le séchage': 'Restart drying', 'changements d’outil': 'tool changes', 'même nom de couleur': 'same colour name', 'Étape Preflight : …': 'Preflight step: …', 'ACE %d déconnecté.': 'ACE %d disconnected.', 'Adresse de la U1 :': 'U1 address:', 'Arrêter le séchage': 'Stop drying', 'Fermer les options': 'Close options', 'Réduire / agrandir': 'Collapse / expand', 'homing refusé : %s': 'homing refused: %s', 'matière différente': 'different material', 'pas de PA mémorisé': 'no stored PA', 'sur la même tête T': 'on the same head T', '+ Nouvelle bobine': '+ New spool', 'Ajoutée à la file': 'Added to the queue', 'Aucune (détacher)': 'None (detach)', 'Caméra de la U1 :': 'U1 camera:', 'Envoi annulé : %s': 'Sending cancelled: %s', 'Forcer une bobine': 'Force a spool', 'Lues dans la U1 :': 'Read from the U1:', 'Time-lapse caméra': 'Camera time-lapse', 'Têtes déjà vides.': 'Heads already empty.', '· avant tes choix': '· before your choices', '· lues dans la U1': '· read from the U1', '(choix de la U1)': '(U1’s choice)', '. Rien à saisir.': '. Nothing to enter.', 'Déchargement T%s': 'Unloading T%s', 'Séchage relancé…': 'Drying restarted…', 'le plan « %s »%s': 'the “%s” plan%s', 'pas dans les ACE': 'not in the ACEs', 'Écran de la U1 :': 'U1 screen:', 'échange en cours': 'swap in progress', '(aucune bobine)': '(no spool)', ', imprimé sur T': ', printed on T', 'Déjà en place :': 'Already in place:', 'Homing terminé.': 'Homing done.', 'Revenir au RFID': 'Back to RFID', 'Très haut débit': 'Ultra high flow', 'après la file :': 'after the queue:', 'bobine partagée': 'shared spool', 'Calibrer avant': 'Calibrate before', 'Dans l’ordre :': 'In order:', 'E3D haut débit': 'E3D high flow', 'File d’attente': 'Queue', 'TPU haut débit': 'TPU high flow', 'Tout décharger': 'Unload all', 'non renseignée': 'not set', 'tranché pour T': 'sliced for T', 'PA mémorisé :': 'Stored PA:', 'Vider la file': 'Clear the queue', 'aucune bobine': 'no spool', 'cette adresse': 'this address', 'choix manuel': 'manual choice', 'du plugin (v': 'of the plugin (v', 'déchargement': 'unloading', 'en déplaçant': 'by moving', 'pas utilisée': 'unused', 'sans adresse': 'no address', 'sans capteur': 'no sensor', 'à mettre ici': 'to move here', 'Décharger T': 'Unload T', 'Déjà vide :': 'Already empty:', 'Enregistrer': 'Save', 'PA mémorisé': 'Stored PA', 'Bleu clair': 'Light blue', 'Bleu foncé': 'Dark blue', 'Cyan clair': 'Light cyan', 'Gris clair': 'Light grey', 'Gris foncé': 'Dark grey', 'Haut débit': 'High flow', 'Vert clair': 'Light green', 'Vert foncé': 'Dark green', 'au lieu de': 'instead of', 'déconnecté': 'disconnected', 'haut débit': 'high flow', 'm utilisés': 'm used', 'ont changé': 'changed', 'prévue sur': 'planned on', '· à régler': '· to set', 'Échec : %s': 'Failed: %s', 'échange(s)': 'swap(s)', 'Décharger': 'Unload', 'Recharger': 'Reload', 'Terminé :': 'Done:', 'Turquoise': 'Turquoise', 'bobine(s)': 'spool(s)', 'matière ≠': 'material ≠', '🔥 Séchage': '🔥 Drying', ', puis :': ', then:', 'Bordeaux': 'Burgundy', 'Modifier': 'Edit', 'Échanger': 'Swap', 'à mettre': 'to move', 'Annuler': 'Cancel', 'Arrêter': 'Stop', 'Charger': 'Load', 'Lavande': 'Lavender', 'Matière': 'Material', 'Réduire': 'Collapse', 'chargée': 'loaded', 'libérée': 'freed', 'masquée': 'hidden', '· reste': '· left', 'Fermer': 'Close', 'Lancer': 'Start', 'Marron': 'Brown', 'Plan «': 'Plan “', 'Sécher': 'Dry', 'Violet': 'Purple', 'aucune': 'none', 'déduit': 'deduced', 'masqué': 'hidden', '· slot': '· slot', 'Blanc': 'White', 'Crème': 'Cream', 'Jaune': 'Yellow', 'Pêche': 'Peach', 'Rouge': 'Red', 'Têtes': 'Heads', 'prête': 'ready', '· sur': '· on', 'échec': 'failed', 'Bleu': 'Blue', 'Gris': 'Grey', 'Kaki': 'Khaki', 'Noir': 'Black', 'Rose': 'Pink', 'Vert': 'Green', 'vide': 'empty'}

_I18N_EN.update({   # 0.37.0
    "Mettre dans la file multiACE": "Put in the multiACE queue",
    "File d’impression de multiACE (Print Hub) : tu lances depuis multiACE quand tu veux": "multiACE print queue (Print Hub): start it from multiACE whenever you want",
    "C’est fait": "Done",
    "✓ noté": "✓ noted",
    "Après l’avoir posée : sa couleur, sa matière et sa bobine de la table multiACE suivent dans le nouveau slot (une bobine RFID se relit seule)": "Once placed: its colour, material and multiACE table spool follow into the new slot (an RFID spool is read again by itself)",
    "%s ajouté à la file multiACE (%s) : lance-le depuis multiACE → Print Hub ; la U1 revérifie les bobines au lancement.%s": "%s added to the multiACE queue (%s): start it from multiACE → Print Hub; the U1 checks the spools again at start.%s",
    "Bobine notée dans ACE %d · slot %d.": "Spool noted in ACE %d · slot %d.",
    "Bobine de ACE %d · slot %d inconnue : « Recharger ».": "Spool of ACE %d · slot %d unknown: “Reload”.",
    "ACE %d · slot %d est vide : pose d'abord la bobine": "ACE %d · slot %d is empty: place the spool first",
    "couleur de la bobine illisible": "unreadable spool colour",
    "la U1 imprime": "the U1 is printing",
    "dossier invalide": "invalid folder",
    "chemin non calibré": "path not calibrated",
    "Calibre ce chemin dans multiACE : Config → Calibration (le plugin ne le fait pas)": "Calibrate this path in multiACE: Config → Calibration (the plugin doesn’t do it)",
    "Filaments 5 et plus (outils virtuels multiACE)": "Filaments 5 and up (multiACE virtual tools)",
    "Table « Slicer filament → MMU / Slot » de multiACE (Config). Elle sert quand le fichier est imprimé tel quel ; avec le Preflight, la U1 réattribue par couleur.": "multiACE “Slicer filament → MMU / Slot” table (Config). It applies when the file is printed as is; with the Preflight, the U1 reassigns by colour.",
    " filament(s) au-delà du 4e : bobine différente dans leur slot multiACE (voir « Filaments 5 et plus »).": " filament(s) beyond the 4th: different spool in their multiACE slot (see “Filaments 5 and up”).",
    "⚠ slot vide": "⚠ empty slot",
    "⚠ bobine": "⚠ spool",
    " absent": " missing",
    "(table)": "(table)",
    "(Orca : ": "(Orca: ",
    "pose une bobine": "put a spool",
    ", pas dans les ACE": ", not in the ACEs",
    "à poser": "to put",
    " posant ": " putting ",
    " bobine(s) hors des ACE": " spool(s) from outside the ACEs",
    "Couleur du filament %d illisible : « Recharger ».": "Filament %d colour unreadable: “Reload”.",
    "Après l’avoir posée : le slot reçoit cette couleur et cette matière (une bobine RFID se relit seule)": "Once placed: the slot gets this colour and material (an RFID spool is read again by itself)",
    " · en déplaçant des bobines": " · by moving spools",
})


def system_lang():
    """Langue de Windows (ou de l'environnement) : "fr" ou "en"."""
    try:
        import ctypes
        lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return "fr" if (lid & 0x3FF) == 0x0C else "en"
    except Exception:
        pass
    for k in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        v = os.environ.get(k) or ""
        if v and not v.upper().startswith(("C.", "C:", "POSIX")) and v.upper() not in ("C",):
            return "fr" if v.lower().startswith("fr") else "en"
    return "fr"


_LANG = {"v": None}


def ui_lang():
    if _LANG["v"] is None:
        want = load_settings().get("lang", "auto")
        _LANG["v"] = system_lang() if want == "auto" else want
    return _LANG["v"]


def _js_escape(text):
    return re.sub(r"([.*+?^${}()|\[\]\\/])", r"\\\1", text)


def _rule_source(fr, en, esc=re.escape):
    """Fragment francais -> (motif, remplacement) ; %s / %d deviennent des groupes."""
    parts = re.split(r"(%s|%d)", fr)
    pat, n = "", 0
    for i, part in enumerate(parts):
        if part in ("%s", "%d"):
            last = i == len(parts) - 1 or (i == len(parts) - 2 and parts[-1] == "")
            pat += r"(\d+)" if part == "%d" else ("(.+)" if last else "(.+?)")
            n += 1
        else:
            pat += esc(part)
    if re.match(r"\w\w", fr):            # pas de garde apres un prefixe d'une lettre (« T », « v »)
        pat = r"(?<![\w])" + pat
    if re.search(r"\w\w$", fr):
        pat += r"(?![\w])"
    k = [0]

    def sub(m):
        k[0] += 1
        return "\\%d" % k[0]
    rep = re.sub(r"%s|%d", sub, en.replace("\\", "\\\\"))
    return pat, rep, n


_I18N_EN = dict(sorted(_I18N_EN.items(), key=lambda kv: -len(kv[0])))   # le plus long d'abord
_I18N_RULES = []


def tr(text):
    """Texte affiche dans OrcaSlicer (notifications, resultats, titres) dans la langue choisie."""
    if not isinstance(text, str) or not text or ui_lang() != "en":
        return text
    if not _I18N_RULES:
        for fr, en in _I18N_EN.items():
            pat, rep, _n = _rule_source(fr, en)
            _I18N_RULES.append((re.compile(pat), rep))
    for rx, rep in _I18N_RULES:
        if rx.search(text):
            text = rx.sub(rep, text)
    return re.sub(r"\s+”", "”", re.sub(r"“\s+", "“", text))


def _js_rules():
    out = []
    for fr, en in _I18N_EN.items():
        pat, rep, _n = _rule_source(fr, en, _js_escape)
        pat = pat.replace(r"(?<![\w])", r"(?<![\p{L}\p{N}_])").replace(r"(?![\w])", r"(?![\p{L}\p{N}_])")
        rep = re.sub(r"\\(\d)", r"$\1", rep.replace("$", "$$")).replace("\\\\", "\\")
        out.append([pat, rep])
    return out


_I18N_JS = r"""<script>(function(){
var R=__RULES__.map(function(r){try{return [new RegExp(r[0],"gu"),r[1]]}catch(e){return null}}).filter(Boolean),C=new Map();
function T(s){if(!s||!/[A-Za-zÀ-ÿ]/.test(s))return s;var c=C.get(s);if(c!==undefined)return c;var o=s;
  for(var i=0;i<R.length;i++){R[i][0].lastIndex=0;if(R[i][0].test(o)){R[i][0].lastIndex=0;o=o.replace(R[i][0],R[i][1])}}
  o=o.replace(/“\s+/g,"“").replace(/\s+”/g,"”");if(C.size>5000)C.clear();C.set(s,o);return o}
var AT=["title","placeholder","alt","aria-label"],busy=false;
function walk(n){if(n.nodeType===3){var p=n.parentNode;if(p&&/^(SCRIPT|STYLE|TEXTAREA)$/.test(p.nodeName))return;var t=T(n.nodeValue);if(t!==n.nodeValue)n.nodeValue=t;return}
  if(n.nodeType!==1||/^(SCRIPT|STYLE|TEXTAREA)$/.test(n.nodeName))return;
  for(var i=0;i<AT.length;i++){var v=n.getAttribute&&n.getAttribute(AT[i]);if(v){var w=T(v);if(w!==v)n.setAttribute(AT[i],w)}}
  for(var c=n.firstChild;c;c=c.nextSibling)walk(c)}
function run(){if(busy)return;busy=true;try{walk(document.documentElement);document.title=T(document.title)}finally{busy=false}}
window.__i18nT=T;
var mo=new MutationObserver(function(ms){if(busy)return;busy=true;try{ms.forEach(function(m){if(m.type==="characterData")walk(m.target);else if(m.type==="attributes")walk(m.target);else m.addedNodes.forEach(walk)})}finally{busy=false}});
function start(){run();mo.observe(document.documentElement,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:AT})}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",start);else start();
})();</script>"""


def i18n_page(html):
    """Ajoute la traduction a une page HTML si l'interface est en anglais."""
    if ui_lang() != "en":
        return html
    js = _I18N_JS.replace("__RULES__", json.dumps(_js_rules(), ensure_ascii=False).replace("</", "<\\/"))
    html = html.replace('<html lang="fr">', '<html lang="en">', 1)
    i = html.find("<head>")
    if i < 0:
        m = re.search(r"<head[^>]*>", html)
        i = m.end() if m else 0
    else:
        i += len("<head>")
    return html[:i] + js + html[i:]


def _ok(*a):
    return orca.ExecutionResult.success(*[tr(x) if isinstance(x, str) else x for x in a])


def _fail(*a):
    return orca.ExecutionResult.failure(*[tr(x) if isinstance(x, str) else x for x in a])


def _skip(*a):
    return orca.ExecutionResult.skipped(*[tr(x) if isinstance(x, str) else x for x in a])


def _notify(ui, level, text, *rest):
    return ui.push_notification(level, tr(text), *[tr(x) if isinstance(x, str) else x for x in rest])

def save_settings(settings):
    write_json_atomic(_settings_path(), settings)


def write_json_atomic(path, value):
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def last_gcode_paths():
    root = storage_dir()
    return os.path.join(root, "last.gcode"), os.path.join(root, "last.json")


def last_gcode_info():
    _, meta_path = last_gcode_paths()
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        return meta if isinstance(meta, dict) else None
    except (OSError, ValueError):
        return None


def keep_last_gcode(source, name):
    """Garde une copie de l'export original pour pouvoir le renvoyer (l'inbox est a usage unique)."""
    gcode_path, meta_path = last_gcode_paths()
    tmp = gcode_path + ".tmp"
    with open(source, "rb") as src, open(tmp, "wb") as dst:
        while True:
            chunk = src.read(1 << 20)
            if not chunk:
                break
            dst.write(chunk)
    os.replace(tmp, gcode_path)
    write_json_atomic(meta_path, {"name": name, "size": os.path.getsize(gcode_path), "ts": time.time()})


# --------------------------------------------------------------------------- adresse

def normalize_host(text):
    """'192.168.1.50', 'http://u1.local/multiace', 'u1.local:80' -> 'hote[:port]' ou ''."""
    text = (text or "").strip().strip('"')
    if not text:
        return ""
    if "://" not in text:
        text = "http://" + text
    if re.search(r"[\x00-\x20\x7f]", text):
        return ""
    try:
        parts = urllib.parse.urlsplit(text)
        host = parts.hostname or ""
        port = parts.port
    except ValueError:          # port illisible, crochets mal formes...
        return ""
    if not host or not re.fullmatch(r"[A-Za-z0-9.\-]+|\[[0-9A-Fa-f:]+\]|[0-9A-Fa-f:]+", host):
        return ""
    if ":" in host and not host.startswith("["):
        host = "[" + host + "]"
    return host + (":%d" % port if port and port != 80 else "")


def origin_of(host):
    return "http://" + host if host else ""


def error_message(body):
    """Extrait le message utile d'une reponse d'erreur multiACE / Moonraker (sans la trace Python)."""
    for _ in range(3):
        try:
            parsed = json.loads(body) if isinstance(body, str) else body
        except ValueError:
            break
        if isinstance(parsed, dict):
            inner = parsed.get("detail", parsed.get("error", parsed.get("message")))
            if isinstance(inner, dict):
                inner = inner.get("message") or inner.get("error") or inner
            if inner is None:
                break
            body = inner
            continue
        break
    text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    m = re.search(r'"message"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if m:
        text = m.group(1)
    return text.split("\n")[0].split("Traceback")[0].strip()[:300]


def gcode_safe(value, limit=40):
    """Valeur libre (marque, type, matiere) envoyee dans une commande G-code via multiACE : sans les
    caracteres qui coupent ou prolongent la ligne Klipper (# * ; " ' retour a la ligne, controle)."""
    v = re.sub(r"[#*;\"'\\]", "", str(value or ""))
    v = re.sub(r"[\x00-\x1f\x7f]", " ", v)
    return " ".join(v.split())[:limit]


def needs_home(text):
    return bool(re.search(r"must home|home .*first|not homed|0003-0522", text or "", re.I))


def friendly_error(text):
    t = text or ""
    if needs_home(t):
        return ("la U1 n'est pas référencée (l'écran affiche « Axis Movement Anomaly ») : il faut un homing "
                "avant de bouger les têtes.")
    if re.search(r"printer is not ready|klippy.*(shutdown|not ready)", t, re.I):
        return "Klipper n'est pas prêt sur la U1 (redémarrage ou erreur en cours) : attends puis réessaie."
    if re.search(r"timed out|timeout", t, re.I):
        return "la U1 n'a pas répondu à temps."
    return t


def preset_host():
    """Adresse du profil imprimante selectionne (print_host), si c'est une U1."""
    try:
        bundle = orca.host.preset_bundle()
        preset = bundle.current_printer_preset()
        text = (preset.config_value("print_host") or bundle.full_config_value("print_host") or "")
        return normalize_host(text)
    except Exception:
        return ""


def effective_host(explicit=""):
    host = normalize_host(explicit) or load_settings()["host"]
    if host:
        return host
    host = preset_host()
    if host:
        # Memorise l'adresse : au prochain lancement, l'autorisation reseau est demandee d'un coup au chargement.
        try:
            st = load_settings()
            st["host"] = host
            save_settings(st)
        except Exception:
            pass
    return host


# --------------------------------------------------------------------------- client HTTP

class MultiAceError(Exception):
    pass


class MultiAce:
    def __init__(self, host):
        if not host:
            raise MultiAceError("Adresse de la U1 non renseignee : entre son IP dans le panneau ACE (Options → Adresse de la U1).")
        self.host = host
        self.base = origin_of(host) + "/multiace/api"

    def _open(self, method, path, data=None, headers=None, timeout=TIMEOUT_BG):
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers or {})
        try:
            return _OPENER.open(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = error_message(e.read(65536).decode("utf-8", "replace"))
            except Exception:
                pass
            err = MultiAceError("HTTP %d%s" % (e.code, (" : " + detail) if detail else ""))
            err.status = e.code
            raise err
        except PermissionError:
            raise
        except (urllib.error.URLError, OSError) as e:
            reason = getattr(e, "reason", e)
            # urllib enveloppe le refus du controle d'acces d'OrcaSlicer dans une URLError.
            if isinstance(reason, PermissionError):
                raise reason
            raise MultiAceError("U1 injoignable a %s (%s)" % (self.host, reason))

    def get_json(self, path, timeout=TIMEOUT_BG):
        with self._open("GET", path, timeout=timeout) as resp:
            raw = resp.read()
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            raise MultiAceError("reponse illisible de %s (multiACE est-il installe ?)" % path)

    def post_json(self, path, value, timeout=TIMEOUT_BG):
        body = json.dumps(value).encode("utf-8")
        with self._open("POST", path, data=body, headers={"Content-Type": "application/json"},
                        timeout=timeout) as resp:
            raw = resp.read()
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            return {}

    def delete_printer_file(self, rel_path, timeout=TIMEOUT_BG):
        """Supprime un fichier de la liste de la U1 (Moonraker), meilleur effort."""
        url = origin_of(self.host) + "/server/files/gcodes/" + urllib.parse.quote(rel_path)
        try:
            with _OPENER.open(urllib.request.Request(url, method="DELETE"), timeout=timeout) as resp:
                resp.read()
        except Exception:
            pass

    def state(self, timeout=TIMEOUT_BG):
        st = self.get_json("/state", timeout)
        # multiACE 1.90 : {"klippy": "disconnected"} pendant un redemarrage de Klipper, {"error": ...} si
        # Moonraker ne repond pas. Ce n'est pas un etat des ACE : ne rien en conclure (garde-fou, panneau).
        if isinstance(st, dict) and "aces" not in st and (st.get("klippy") or st.get("error")):
            raise MultiAceError("Klipper n'est pas prêt sur la U1 (redémarrage ou erreur en cours) : attends puis réessaie.")
        return st

    def inbox(self, timeout=TIMEOUT_BG):
        return self.get_json("/preflight/inbox", timeout)

    def discard_inbox(self, timeout=TIMEOUT_BG):
        with self._open("DELETE", "/preflight/inbox", timeout=timeout) as resp:
            resp.read()

    def macro(self, name, args, timeout=900):
        """Lance une macro multiACE via son API (meme chemin que l'interface web). Bloque jusqu'a la fin."""
        body = json.dumps({"name": name, "args": args}).encode("utf-8")
        with self._open("POST", "/macro", data=body, headers={"Content-Type": "application/json"}, timeout=timeout) as resp:
            resp.read()

    def home(self, timeout=180):
        """Homing (G28) par l'API multiACE (/macro accepte toute commande G-code) : meme adresse que le
        reste, donc deja autorisee par OrcaSlicer (le port 7125 de Moonraker ne l'est pas)."""
        try:
            self.macro("G28", {}, timeout=timeout)
        except MultiAceError as e:
            raise MultiAceError("homing refusé : %s" % friendly_error(str(e)))

    def homed_axes(self, timeout=TIMEOUT_UI):
        """Axes references par Klipper ("xyz" si tout est bon). None si Moonraker ne repond pas."""
        url = origin_of(self.host) + "/printer/objects/query?toolhead=homed_axes"   # Moonraker via nginx :80
        try:
            with _OPENER.open(url, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return str(data["result"]["status"]["toolhead"].get("homed_axes") or "")
        except Exception:
            return None

    def head_nozzle_types(self, timeout=TIMEOUT_UI):
        """Buses vissees sur les 4 tetes, lues dans la U1 (extruderN.nozzle_volume_type, firmware recent ;
        meme source que multiACE). Liste de 4 valeurs de NOZZLE_CHOICES, "" si la U1 ne le dit pas.
        Lecture seule."""
        names = ["extruder", "extruder1", "extruder2", "extruder3"]
        url = origin_of(self.host) + "/printer/objects/query?" + "&".join(names)   # Moonraker via nginx :80
        try:
            with _OPENER.open(url, timeout=timeout) as resp:
                status = json.loads(resp.read().decode("utf-8"))["result"]["status"]
        except Exception:
            return ["", "", "", ""]
        out = []
        for name in names:
            v = str((status.get(name) or {}).get("nozzle_volume_type") or "").strip().lower().replace(" ", "_")
            out.append({"standard": "Standard", "high_flow": "Haut débit"}.get(v, ""))
        return out

    def active_head(self, timeout=TIMEOUT_UI):
        """Tete qui imprime en ce moment (0-3) d'apres Klipper (toolhead.extruder), None si inconnue."""
        url = origin_of(self.host) + "/printer/objects/query?toolhead=extruder"   # Moonraker via nginx :80
        try:
            with _OPENER.open(url, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            name = str(data["result"]["status"]["toolhead"].get("extruder") or "")
        except Exception:
            return None
        m = re.fullmatch(r"extruder([0-3]?)", name)
        return int(m.group(1) or 0) if m else None

    def screen_tap(self, x, y, timeout=TIMEOUT_UI):
        """Extended Firmware : toucher l'ecran de la U1 (POST /screen/touch, hors /multiace)."""
        url = origin_of(self.host) + "/screen/touch?a=tap&x=%d&y=%d" % (x, y)
        req = urllib.request.Request(url, data=b"", method="POST")
        try:
            with _OPENER.open(req, timeout=timeout) as resp:
                resp.read()
        except urllib.error.URLError as e:
            if isinstance(getattr(e, "reason", None), PermissionError):
                raise e.reason
            raise MultiAceError("ecran distant injoignable (%s)" % getattr(e, "reason", e))

    def set_override(self, ace, slot, material, brand, subtype, color, timeout=TIMEOUT_BG):
        body = json.dumps({"ace": ace, "slot": slot, "material": material, "brand": brand,
                           "subtype": subtype, "color": color}).encode("utf-8")
        with self._open("POST", "/slot-override", data=body, headers={"Content-Type": "application/json"},
                        timeout=timeout) as resp:
            resp.read()

    def clear_override(self, ace, slot, timeout=TIMEOUT_BG):
        with self._open("DELETE", "/slot-override/%d/%d" % (ace, slot), timeout=timeout) as resp:
            resp.read()

    def upload_to_printer(self, path, name):
        """Televerse dans la liste des fichiers de la U1 (Moonraker, via nginx) sans lancer l'impression."""
        return self.send_gcode(path, name, endpoint="moonraker")

    def send_gcode(self, path, name, endpoint="/preflight/inbox", folder=None):
        """POST multipart en flux (les G-code multi-couleurs depassent souvent 100 Mo).
        folder : sous-dossier de la liste des fichiers (Moonraker seulement, ex. la file multiACE)."""
        name = os.path.basename(name or path)
        if not re.search(r"\.(gcode|gco|g)$", name, re.IGNORECASE):
            name += ".gcode"
        safe = re.sub(r"[\x00-\x1f\x7f\"\\/]", "_", name)[-180:]
        boundary = "----multiACEBridge" + uuid.uuid4().hex
        head = ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
                "Content-Type: application/octet-stream\r\n\r\n" % (boundary, safe)).encode("utf-8")
        if endpoint == "moonraker":
            if folder:
                if not re.fullmatch(r"[A-Za-z0-9_\-]{1,40}", folder):
                    raise MultiAceError("dossier invalide")
                head = ("--%s\r\nContent-Disposition: form-data; name=\"path\"\r\n\r\n%s\r\n"
                        % (boundary, folder)).encode("ascii") + head
            head = ("--%s\r\nContent-Disposition: form-data; name=\"root\"\r\n\r\ngcodes\r\n" % boundary).encode("ascii") + head
        tail = ("\r\n--%s--\r\n" % boundary).encode("ascii")
        size = os.path.getsize(path)

        def body():
            yield head
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    yield chunk
            yield tail

        headers = {"Content-Type": "multipart/form-data; boundary=" + boundary,
                   "Content-Length": str(len(head) + size + len(tail))}
        if endpoint == "moonraker":
            url = origin_of(self.host) + "/server/files/upload"     # Moonraker via nginx :80 (deja autorise)
            req = urllib.request.Request(url, data=body(), method="POST", headers=headers)
            try:
                with _OPENER.open(req, timeout=UPLOAD_TIMEOUT) as resp:
                    raw = resp.read()
            except urllib.error.URLError as e:
                if isinstance(getattr(e, "reason", None), PermissionError):
                    raise e.reason
                raise MultiAceError("televersement vers la U1 impossible (%s)" % getattr(e, "reason", e))
        else:
            with self._open("POST", endpoint, data=body(), headers=headers, timeout=UPLOAD_TIMEOUT) as resp:
                raw = resp.read()
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            return {"ok": True}


_probed = set()


def probe_network(host, force=False):
    """Premier contact SUR LE FIL DE L'INTERFACE : OrcaSlicer peut y afficher tout de suite sa demande
    d'autorisation reseau et memoriser la reponse (depuis un fil d'arriere-plan, il la refuse d'office)."""
    if not host or (host in _probed and not force):
        return
    _probed.add(host)
    try:
        MultiAce(host).get_json("/version", timeout=1.5)
    except Exception:
        pass



def permission_text(host):
    return ("OrcaSlicer a bloqué l'accès réseau vers %s. Clique « Autoriser et réessayer » et accepte la "
            "demande d'OrcaSlicer (une seule fois)." % (origin_of(host) or "la U1"))


# --------------------------------------------------------------------------- G-code

def read_head_tail(path, head_bytes=65536, tail_bytes=262144):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(min(size, head_bytes)).decode("utf-8", "replace")
        tail = ""
        if size > head_bytes:
            f.seek(max(head_bytes, size - tail_bytes))
            tail = f.read().decode("utf-8", "replace")
    return head, tail


def gcode_facts(path):
    head, tail = read_head_tail(path)
    text = head + "\n" + tail
    processed = any(m in head for m in PROCESSED_MARKERS)
    u1control = U1CONTROL_MARKER in text
    used = None
    m = re.search(r"^;\s*filament used \[mm\]\s*=\s*(.+)$", text, re.MULTILINE)
    if m:
        values = []
        for part in re.split(r"[,;]", m.group(1)):
            try:
                values.append(float(part.strip()))
            except ValueError:
                pass
        used = sum(1 for v in values if v > 0)
    tools = sorted({int(t) for t in re.findall(r"^T(\d+)\s*$", tail, re.MULTILINE)})
    return {"processed": processed, "u1control": u1control, "filaments_used": used, "max_tool_seen": tools[-1] if tools else None}


# --------------------------------------------------------------------------- page

ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#FEFEFE" stroke-width="1.6">
<rect x="2.5" y="5" width="19" height="14" rx="2.5"/>
<circle cx="7" cy="12" r="2.2"/><circle cx="12" cy="12" r="2.2"/><circle cx="17" cy="12" r="2.2"/>
<path d="M5 19v2M19 19v2"/></svg>"""

# Page de lancement : demande l'adresse au plugin, verifie que multiACE repond,
# puis remplace l'onglet par l'interface web de multiACE.
PAGE = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<style>
:root{color-scheme:dark;font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#1b1e22;color:#e9ecef}
.box{width:min(440px,90vw);text-align:center}
h1{font-size:18px;margin:0 0 6px}
p{color:#9aa3ad;margin:0 0 16px}
.row{display:flex;gap:8px;justify-content:center}
input{flex:1;background:rgba(255,255,255,.06);color:#e9ecef;border:1px solid rgba(255,255,255,.15);border-radius:6px;padding:8px 10px;font:inherit}
button{background:#009688;color:#fff;border:0;border-radius:6px;padding:8px 14px;font:inherit;cursor:pointer}
.err{color:#f08a80}
.spin{width:26px;height:26px;border:3px solid rgba(255,255,255,.15);border-top-color:#009688;border-radius:50%;margin:0 auto 14px;animation:r 1s linear infinite}
@keyframes r{to{transform:rotate(360deg)}}
</style></head><body>
<div class="box">
  <div id="wait"><div class="spin"></div><h1>Connexion à multiACE…</h1><p id="where"></p></div>
  <div id="form" hidden>
    <h1>multiACE</h1>
    <p id="why">Entre l'adresse IP de ta Snapmaker U1.</p>
    <div class="row"><input id="host" placeholder="ex. 192.168.1.50" spellcheck="false"><button id="go">Ouvrir</button></div>
  </div>
</div>
<script>
(function(){
  var $=function(i){return document.getElementById(i)};
  function post(m){if(window.orca)window.orca.postMessage(m)}
  function form(msg,host){$("wait").hidden=true;$("form").hidden=false;if(msg){$("why").textContent=msg;$("why").className="err"}if(host)$("host").value=host;$("host").focus()}
  window.orca&&window.orca.onMessage(function(m){
    if(!m)return;
    if(m.type==="open"){window.location.replace(m.url)}
    else if(m.type==="checking"){$("wait").hidden=false;$("form").hidden=true;$("where").textContent=m.host}
    else if(m.type==="ask"){form(m.error||"",m.host||"")}
  });
  $("go").onclick=function(){post({type:"open",host:$("host").value})};
  $("host").addEventListener("keydown",function(e){if(e.key==="Enter")$("go").click()});
  if(window.orca)post({type:"init"});else form("Pont OrcaSlicer indisponible.","");
})();
</script></body></html>"""


class MultiAcePage(orca.pages.PagesPluginCapabilityBase):
    """Onglet "multiACE" : affiche l'interface web de multiACE dans OrcaSlicer."""

    def on_unload(self):
        plugin_shutdown()

    def get_name(self):
        return "multiACE"

    def get_icon(self):
        path = os.path.join(storage_dir(), "multiace_icon.svg")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(ICON_SVG)
        except OSError:
            pass
        return path

    def get_default_config(self):
        return {}

    def get_ui(self):
        return i18n_page(PAGE)

    # Appele sur le fil de l'interface.
    def on_message(self, data):
        try:
            if isinstance(data, str):
                data = json.loads(data)
        except ValueError:
            return
        if not isinstance(data, dict):
            return
        kind = data.get("type")
        if kind == "init":
            auto_open_panel()
            host = effective_host()
            if not host:
                self.post_message({"type": "ask"})
                return
            self._check_async(host, save=False)
        elif kind == "open":
            raw = data.get("host") or ""
            host = normalize_host(raw)
            if not host:
                self.post_message({"type": "ask", "error": "Adresse invalide, par exemple 192.168.1.50", "host": raw})
                return
            self._check_async(host, save=True)

    def on_lifecycle_event(self, event, ctx):
        on_app_event(event, ctx)

    def _check_async(self, host, save):
        self.post_message({"type": "checking", "host": host})
        if save:
            # Premier contact sur le fil de l'interface : la demande d'autorisation
            # reseau d'OrcaSlicer peut s'afficher et etre memorisee.
            try:
                MultiAce(host).get_json("/version", timeout=TIMEOUT_UI)
            except PermissionError:
                self.post_message({"type": "ask", "error": permission_text(host), "host": host})
                return
            except Exception as e:
                self.post_message({"type": "ask", "error": str(e), "host": host})
                return
            save_settings(dict(load_settings(), host=host))
            self.post_message({"type": "open", "url": origin_of(host) + "/multiace/"})
            return

        def worker():
            try:
                MultiAce(host).get_json("/version", timeout=TIMEOUT_UI)
                self.post_message({"type": "open", "url": origin_of(host) + "/multiace/"})
            except PermissionError:
                self.post_message({"type": "ask", "error": permission_text(host) + " Clique Ouvrir.", "host": host})
            except Exception as e:
                self.post_message({"type": "ask", "error": str(e), "host": host})

        threading.Thread(target=worker, daemon=True).start()


# --------------------------------------------------------------------------- fenetre Preflight

POPUP = r"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#1b1e22;color:#e9ecef;
font:14px system-ui,-apple-system,"Segoe UI",sans-serif}p{color:#9aa3ad}</style></head>
<body><div style="text-align:center"><b>__NAME__</b><p>envoyé à multiACE, ouverture du Preflight…</p></div>
<script>setTimeout(function(){window.location.replace("__URL__")},300)</script></body></html>"""


class PreflightPopup:
    """Fenetre flottante avec l'interface multiACE, ouverte apres un export envoye au Preflight."""

    def __init__(self):
        self.window = None
        self.pending = None          # (nom, url, horodatage) en attente d'affichage
        self._lock = threading.Lock()

    def request(self, name, url):
        with self._lock:
            self.pending = (name, url, time.time())

    def show_pending(self):
        """A appeler hors du fil de tranchage. Ouvre la fenetre si un envoi recent attend."""
        with self._lock:
            pending, self.pending = self.pending, None
        if not pending or time.time() - pending[2] > 300:
            return
        name, url, _ = pending
        old = self.window
        if old is not None:
            try:
                if old.is_open():
                    old.close()     # on recharge pour que le Preflight reprenne le nouveau fichier
            except Exception:
                pass
        html = (POPUP.replace("__URL__", url.replace("\\", "").replace('"', ""))
                     .replace("__NAME__", name.replace("<", "").replace(">", "").replace("&", "et")))
        self.window = orca.host.ui.create_window(html=i18n_page(html), title="multiACE - Preflight", width=1180, height=820,
                                                 on_close=self._closed)

    def _closed(self):
        self.window = None


_POPUP = PreflightPopup()


def schedule_popup_fallback(delay=2.5):
    """Filet de securite si l'evenement de fin d'export n'arrive pas : on ouvre depuis un fil a part,
    apres la fin de l'etape de tranchage (jamais depuis le fil de tranchage lui-meme)."""
    def worker():
        time.sleep(delay)
        try:
            _POPUP.show_pending()
        except Exception:
            pass
    threading.Thread(target=worker, daemon=True).start()


# --------------------------------------------------------------------------- ancien profil 8 tetes
# Le plugin reste sur le profil Snapmaker U1 a 4 tetes : l'ancien profil « Snapmaker U1 multiACE »
# des premieres versions est seulement retire s'il est encore installe.

# Valeurs par outil du profil Snapmaker U1 d'origine (reprises de multiACE orca_profile.py).
PROFILE_NAME = "Snapmaker U1 multiACE"
BUNDLE_ID = "multiace-bridge"


def _data_dir():
    for base in (os.path.abspath(__file__), storage_dir()):
        parts = base.replace("\\", "/").split("/")
        if "orca_plugins" in parts:
            return "/".join(parts[: parts.index("orca_plugins")])
    raise RuntimeError("dossier de donnees d'OrcaSlicer introuvable")


def _user_folder(bundle):
    for collection in (bundle.printers, bundle.prints, bundle.filaments):
        for i in range(collection.size()):
            parts = os.path.normpath(collection.preset(i).file or "").replace("\\", "/").split("/")
            if "user" in parts:
                idx = parts.index("user")
                if idx + 1 < len(parts) and parts[idx + 1] != "_local":
                    return parts[idx + 1]
    return "default"


def on_multiace_profile():
    try:
        return PROFILE_NAME in (orca.host.preset_bundle().current_printer_preset().name or "")
    except Exception:
        return False


def remove_old_profile():
    """Supprime le profil "Snapmaker U1 multiACE" des anciennes versions (bundle local "multiace-bridge").

    Fil de l'interface. Ne fait rien si ce profil est l'imprimante selectionnee. Retourne True si supprime."""
    try:
        if on_multiace_profile():
            return False
        user_root = os.path.join(_data_dir(), "user")
        removed = False
        for folder in os.listdir(user_root) if os.path.isdir(user_root) else []:
            bundle_dir = os.path.join(user_root, folder, "_local", BUNDLE_ID)
            if not os.path.isdir(bundle_dir):
                continue
            for dirpath, dirnames, filenames in os.walk(bundle_dir, topdown=False):
                for name in filenames:
                    os.remove(os.path.join(dirpath, name))
                os.rmdir(dirpath)
            removed = True
        if removed:
            try:
                orca.host.preset.bundles.reload_local(BUNDLE_ID)
            except Exception:
                pass    # le profil disparait au prochain demarrage d'OrcaSlicer
        return removed
    except Exception:
        return False


# --------------------------------------------------------------------------- avant de trancher

def all_slots_from_state(state):
    """Toutes les bobines presentes (meme les couleurs deduites) : la liste des choix manuels."""
    out = []
    for ace in state.get("aces") or []:
        idx = ace.get("idx")
        if not isinstance(idx, int) or idx > 3:
            continue
        for slot in ace.get("slots") or []:
            if slot.get("state") == "empty" or slot.get("source") == "empty":
                continue
            out.append({"ace": idx, "slot": slot.get("idx"), "material": (slot.get("material") or "").strip(),
                        "color": (slot.get("color") or "").strip().lower(), "brand": slot.get("brand") or "",
                        "source": slot.get("source") or ""})
    return out


NOZZLE_FR = {"standard": "Standard", "high flow": "Haut débit", "high_flow": "Haut débit", "hybrid": "Hybride",
             "tpu high flow": "TPU haut débit", "e3d high flow": "E3D haut débit", "extra high flow": "Très haut débit"}


def _split(value):
    return [v.strip() for v in re.split(r"[;,]", value or "") if v.strip()] if value else []


def _norm_colour(c):
    """OrcaSlicer ecrit les couleurs avec la transparence (#F7D959FF) : le moteur attend #RRGGBB."""
    c = str(c or "").strip()
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})(?:[0-9a-fA-F]{2})?", c)
    return "#" + m.group(1).upper() if m else c


PREP_MAX_DIST = 60      # ecart RGB max pour rapprocher une couleur d'Orca d'une bobine (au-dela : pas trouvee)


def _rgb(c):
    c = _norm_colour(c)
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) if re.fullmatch(r"#[0-9A-F]{6}", c) else None


def slicing_advice(state, real, colours, orca_nozzles):
    """Assistant « avant de trancher ». Pour OrcaSlicer, le filament N est imprime par la tete TN ; en
    vrai, il part sur la tete du slot ou est sa bobine (slot 3 -> T3). Pour chacun des filaments 1-4 :
    bobine de meme couleur dans les ACE, tete reelle, buse reelle de cette tete = buse a regler pour TN
    dans OrcaSlicer pour que le tranchage corresponde a la realite.
    real : buses reelles des 4 tetes (NOZZLE_CHOICES ou "") ; colours / orca_nozzles : lus dans Orca."""
    slots = [x for x in all_slots_from_state(state) if x.get("color") and x.get("slot") is not None]
    rows, used_heads = [], {}
    for i, colour in enumerate(colours[:4]):
        want = _rgb(colour)
        now = orca_nozzles[i] if i < len(orca_nozzles) else None
        cands = []
        for x in slots:
            got = _rgb(x["color"])
            if want and got:
                d = sum((a - b) ** 2 for a, b in zip(want, got)) ** 0.5
                if d <= PREP_MAX_DIST:
                    need = real[x["slot"]] if x["slot"] < len(real) else ""
                    # la plus proche ; a egalite, celle qui ne demande rien a changer, puis l'ordre des ACE
                    cands.append((round(d), 0 if need and need == now else 1, x["ace"], x["slot"], x))
        row = {"t": i, "color": _norm_colour(colour), "now": now, "found": bool(cands)}
        if cands:
            x = min(cands, key=lambda c: c[:4])[4]
            need = real[x["slot"]] if x["slot"] < len(real) else ""
            row.update(ace=x["ace"], slot=x["slot"], head=x["slot"], need=need or None,
                       ok=bool(need) and need == now, spool_color=x["color"])
            used_heads.setdefault(x["slot"], []).append(i)
        rows.append(row)
    todo = [{"t": r["t"], "need": r["need"]} for r in rows if r["found"] and r.get("need") and not r["ok"]]
    shared = [{"head": h, "filaments": ts} for h, ts in sorted(used_heads.items()) if len(ts) > 1]
    virtual = virtual_tool_rows(state, real, colours, orca_nozzles)
    return {"rows": rows, "todo": todo, "shared": shared, "real_known": all(real[:4]) if real else False,
            "virtual": virtual, "extra": 0 if virtual is not None else max(0, len(colours) - 4)}


VIRTUAL_TOOL_MAX = 31      # multiACE : outils T4..T31 (filaments 5 a 32)


def virtual_tool_rows(state, real, colours, orca_nozzles):
    """Filaments 5 et plus (multiACE 1.90, « outils virtuels ») : la table « Slicer filament → MMU / Slot »
    de multiACE (tool_map, sinon sa formule ace=(n-4)//4, slot=(n-4)%4). Lecture seule : montre ou part
    chaque filament quand le fichier est imprime tel quel, et si la bobine de ce slot a la bonne couleur.
    None : multiACE sans outils virtuels (1.27b) ou projet de 4 filaments au plus."""
    if not isinstance(state, dict) or not isinstance(state.get("tool_map"), dict) or len(colours) <= 4:
        return None
    tmap, mode = state["tool_map"], state.get("mode")
    aces = {a.get("idx"): a for a in state.get("aces") or [] if isinstance(a.get("idx"), int)}
    head_ace = state.get("head_ace") or {}
    out = []
    for i, colour in enumerate(colours[4:VIRTUAL_TOOL_MAX + 1], start=4):
        ent = tmap.get(str(i))
        if isinstance(ent, (list, tuple)) and len(ent) == 2 and all(isinstance(v, int) for v in ent):
            ace, slot, mapped = ent[0], ent[1], True
        else:
            (ace, slot), mapped = divmod(i - 4, 4), False
        if mode == "head":
            head = next((int(h) for h, a in head_ace.items() if str(h).isdigit() and _int_or_none(a) == ace), None)
        else:
            head = slot if 0 <= slot <= 3 else None
        row = {"t": i, "color": _norm_colour(colour), "ace": ace, "slot": slot, "mapped": mapped, "head": head,
               "present": ace in aces}
        a = aces.get(ace) or {}
        sl = next((s for s in a.get("slots") or [] if s.get("idx") == slot), None)
        empty = sl is None or sl.get("state") == "empty" or sl.get("source") == "empty"
        row["empty"] = empty
        if not empty:
            row["spool_color"] = _norm_colour(sl.get("color"))
            row["material"] = (sl.get("material") or "").strip()
            want, got = _rgb(colour), _rgb(sl.get("color"))
            row["match"] = bool(want and got and sum((x - y) ** 2 for x, y in zip(want, got)) ** 0.5 <= PREP_MAX_DIST)
        need = real[head] if head is not None and head < len(real) else ""
        now = orca_nozzles[i] if i < len(orca_nozzles) else None
        row.update(need=need or None, now=now, ok=bool(need) and (now is None or need == now))
        out.append(row)
    return out


_NOZZLE_CACHE = {}         # hote -> (instant, buses lues dans la U1)
NOZZLE_CACHE_S = 60.0


def effective_nozzles(client):
    """Buses vissees : lues dans la U1 quand elle les donne (valeur gardee 60 s), sinon le reglage
    « Ma U1 » du panneau, tete par tete. Retourne (liste de 4, source "u1" / "mixte" / "manuel")."""
    now = time.monotonic()
    hit = _NOZZLE_CACHE.get(client.host)
    if hit and now - hit[0] < NOZZLE_CACHE_S:
        read = hit[1]
    else:
        read = client.head_nozzle_types()
        _NOZZLE_CACHE[client.host] = (now, read)
    manual = load_settings()["real_nozzles"]
    real = [read[h] or manual[h] for h in range(4)]
    src = "u1" if all(read) else ("mixte" if any(read) else "manuel")
    return real, src


_CALIB_CACHE = {}          # hote -> (instant, {"ace_slot": True/False})
CALIB_CACHE_S = 60.0


def _cfg_positive(params, key):
    try:
        return float(str(params.get(key, "")).split("#")[0].strip()) > 0
    except ValueError:
        return False


def path_calibration(client, force=False):
    """Calibration du chemin (Bowden) de chaque slot, comme l'onglet Config → Calibration de multiACE :
    un chemin est calibre quand retract_length ET swap_retract_length sont enregistres pour ce slot
    ([ace N] retract_length_S) ou pour son ACE ([ace N] retract_length) — jamais la valeur globale de [ace].
    Lecture seule (GET /api/config), gardee 60 s. Retourne {"ace_slot": bool} ou None si illisible."""
    now = time.monotonic()
    hit = _CALIB_CACHE.get(client.host)
    if hit and not force and now - hit[0] < CALIB_CACHE_S:
        return hit[1]
    try:
        cfg = client.get_json("/config", timeout=TIMEOUT_UI)
        per = cfg.get("per_ace_params") if isinstance(cfg, dict) else None
        if not isinstance(per, dict):
            raise ValueError
    except Exception:
        _CALIB_CACHE[client.host] = (now, None)
        return None
    out = {}
    for ace in range(8):
        p = per.get(str(ace)) or per.get(ace) or {}
        if not isinstance(p, dict):
            p = {}
        for slot in range(4):
            out["%d_%d" % (ace, slot)] = all(_cfg_positive(p, "%s_%d" % (k, slot)) or _cfg_positive(p, k)
                                             for k in ("retract_length", "swap_retract_length"))
    _CALIB_CACHE[client.host] = (now, out)
    return out


def orca_filament_setup():
    """Couleurs des filaments et buses des tetes dans OrcaSlicer (projet en cours). None si ce n'est
    pas une U1 ou si OrcaSlicer ne repond pas."""
    try:
        bundle = orca.host.preset_bundle()
        if "U1" not in (bundle.current_printer_preset().config_value("printer_model") or ""):
            return None
        colours = [c.strip().strip('"') for c in _split(bundle.full_config_value("filament_colour"))]
        nozzles = [NOZZLE_FR.get(v.strip().strip('"').lower().replace("_", " "), v.strip().strip('"'))
                   for v in _split(bundle.full_config_value("nozzle_volume_type"))]
        return colours, nozzles
    except Exception:
        return None




# --------------------------------------------------------------------------- preflight avec le code de la U1

# Methode voulue par l'auteur de multiACE (decay71/multiACE#243) : le plugin n'a AUCUNE logique
# d'attribution. Il execute dans Orca le Preflight fourni par la U1 (GET /api/preflight/pysrc : le
# post-processeur + preflight_core, exactement ce que lance l'interface web multiACE) avec le
# chargement de GET /api/preflight/livedata, puis envoie le fichier prepare a la U1.
# Si une verification echoue (code absent, trop gros, fonctions ou parametres differents de ceux
# attendus, tete en manuel...), on n'execute rien : le G-code original part dans le Preflight
# de multiACE (/api/preflight/inbox), qui fait tout lui-meme.

U1CODE_MAX = 4 * 1024 * 1024      # octets par fichier source
# Parametres indispensables (presents depuis multiACE 1.27b) ; les autres sont utilises s'ils existent.
U1CODE_NEEDS = {
    "parse_meta": ("pp", "line_iter"),
    "build_report": ("slicer_colors", "slicer_types", "num_aces", "plan_proxy", "live_slots", "head_ctx",
                     "token", "filename", "size", "meta"),
    "rewrite_pipeline": ("src_path", "tmp_a", "tmp_b", "slicer_colors", "slicer_types", "num_aces",
                         "live_slots", "head_ctx", "mode", "meta"),
}
U1CODE_OPTIONAL = ("prepend_print_prefs", "used_ace_slots_file")
PLAN_LABELS = {"slicer": "Comme tranché (slicer)", "optimize": "Optimisé (optimize)", "layer": "Par couche (layer)"}


class U1CodeError(Exception):
    """Verification refusee : on passe par le Preflight de multiACE."""


_u1code = {"sha": None, "pp": None, "core": None, "caps": {}}
_u1code_lock = threading.Lock()


class U1AccessError(Exception):
    """OrcaSlicer n'a pas (encore) autorise un acces fichier : il pose la question a l'utilisateur et,
    pendant ce temps, refuse l'acces au fil d'arriere-plan. On attend sa reponse au lieu d'abandonner."""


def _denied(e):
    seen = 0
    while e is not None and seen < 6:
        if isinstance(e, PermissionError) or "permission" in str(e).lower():
            return True
        e = e.__cause__ or e.__context__
        seen += 1
    return False


U1ACCESS_WAIT = 180        # secondes pour repondre a la demande d'autorisation d'Orca


def _load_source(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


U1CODE_TIMEOUT = 30        # secondes : la U1 qui imprime peut mettre du temps a servir son code
U1CODE_TRIES = 3


def _get_patient(client, path):
    """GET avec delai long et nouvel essai si la U1 ne repond pas a temps (pas si elle repond une erreur)."""
    last = None
    for i in range(U1CODE_TRIES):
        try:
            return client.get_json(path, timeout=U1CODE_TIMEOUT)
        except MultiAceError as e:
            if getattr(e, "status", None) is not None:
                raise
            last = e
            if _STOP.is_set():
                break
            time.sleep(1.5 * (i + 1))
    raise last


def _check_static(core_src):
    """Lit le code sans l'executer : les fonctions et parametres attendus doivent exister."""
    try:
        tree = ast.parse(core_src)
    except SyntaxError:
        raise U1CodeError("code de la U1 illisible")
    defs = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            a = node.args
            defs[node.name] = {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs}
    for fn, params in U1CODE_NEEDS.items():
        if fn not in defs:
            raise U1CodeError("fonction %s absente : version de multiACE non prise en charge" % fn)
        missing = [p for p in params if p not in defs[fn]]
        if missing:
            raise U1CodeError("%s a changé (%s) : version de multiACE non prise en charge" % (fn, ", ".join(missing)))
    return {"header": "with_header" in defs["parse_meta"],
            "cost": "cost_params" in defs["build_report"] and "header_text" in defs["build_report"],
            "prefs": "prepend_print_prefs" in defs, "used": "used_ace_slots_file" in defs,
            "remap": "remap_override" in defs["rewrite_pipeline"]}


def u1_code(client):
    """Telecharge et verifie le Preflight de la U1 ; renvoie (pp, core, empreinte). Leve U1CodeError."""
    try:
        src = _get_patient(client, "/preflight/pysrc")
    except MultiAceError as e:
        raise U1CodeError("la U1 ne fournit pas son Preflight (%s)" % e)
    if not isinstance(src, dict):
        raise U1CodeError("réponse inattendue de /preflight/pysrc")
    pp_src, core_src, cost_src = src.get("postprocess"), src.get("core"), src.get("swap_cost")
    for label, text in (("post-processeur", pp_src), ("preflight_core", core_src)):
        if not isinstance(text, str) or not text.strip():
            raise U1CodeError("%s absent (multiACE trop ancien pour cette méthode)" % label)
    for text in (pp_src, core_src, cost_src or ""):
        if len(text.encode("utf-8")) > U1CODE_MAX:
            raise U1CodeError("code de la U1 trop gros")
    if "def match_colors_to_slots" not in pp_src or "def build_report" not in core_src:
        raise U1CodeError("code de la U1 non reconnu")
    caps = _check_static(core_src)   # avant d'executer quoi que ce soit
    sha = hashlib.sha256((pp_src + "\0" + core_src + "\0" + (cost_src or "")).encode("utf-8")).hexdigest()
    with _u1code_lock:
        if _u1code["sha"] == sha:
            return _u1code["pp"], _u1code["core"], sha[:10]
        folder = os.path.join(storage_dir(), "u1code")
        os.makedirs(folder, exist_ok=True)
        files = {"post_process_virtual_toolheads.py": pp_src, "preflight_core.py": core_src}
        if isinstance(cost_src, str) and cost_src.strip():
            files["swap_cost.py"] = cost_src
        try:
            for fname, text in files.items():
                with open(os.path.join(folder, fname), "w", encoding="utf-8", newline="\n") as f:
                    f.write(text)
        except OSError as e:
            if _denied(e):
                raise U1AccessError(str(e)[:120])
            raise U1CodeError("code de la U1 impossible à enregistrer (%s)" % str(e)[:120])
        old = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            pp = _load_source("multiace_u1_postprocess", os.path.join(folder, "post_process_virtual_toolheads.py"))
            core = _load_source("multiace_u1_preflight_core", os.path.join(folder, "preflight_core.py"))
            if "swap_cost.py" in files and hasattr(core, "load_swap_cost"):
                core.load_swap_cost(os.path.join(folder, "swap_cost.py"))
        except Exception as e:
            if _denied(e):
                raise U1AccessError(str(e)[:120])
            raise U1CodeError("le code de la U1 ne se charge pas (%s)" % str(e)[:120])
        finally:
            sys.dont_write_bytecode = old
        for fn in U1CODE_NEEDS:
            if not callable(getattr(core, fn, None)):
                raise U1CodeError("fonction %s absente : version de multiACE non prise en charge" % fn)
        _u1code.update(sha=sha, pp=pp, core=core, caps=caps)
        return pp, core, sha[:10]


def _read_lines(path, size=1 << 20):
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        rest = ""
        while True:
            block = f.read(size)
            text = rest + block
            if not block:
                if text:
                    yield from text.splitlines(True)
                return
            lines = text.splitlines(True)
            rest = lines.pop() if lines else ""
            yield from lines


def _live(client):
    try:
        live = _get_patient(client, "/preflight/livedata")
    except MultiAceError as e:
        if getattr(e, "status", None) == 409:
            raise U1CodeError("une tête est en mode manuel : attribution indisponible")
        raise U1CodeError("chargement illisible (%s)" % e)
    if not isinstance(live, dict) or not isinstance(live.get("live_slots"), list):
        raise U1CodeError("réponse inattendue de /preflight/livedata")
    return live


def _signature(live):
    return json.dumps([live.get("live_slots"), live.get("head_ctx")], sort_keys=True)


def _params(fn):
    try:
        return set(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        return set()


def u1_report(client, path, name):
    pp, core, sha = u1_code(client)
    live = _live(client)
    caps = _u1code.get("caps") or {}
    if caps.get("header"):
        colors, types, naces, _used, plan, meta, header = core.parse_meta(pp, _read_lines(path), with_header=True)
    else:
        colors, types, naces, _used, plan, meta = core.parse_meta(pp, _read_lines(path))
        header = None
    extra = {"header_text": header, "cost_params": live.get("cost_params") or {}} if caps.get("cost") else {}
    # multiACE 1.90 : « Optimisé » / « Par couche » ne travaillent qu'avec les bobines deja chargees. Le
    # meme code de la U1 sait encore proposer une disposition (build_one_plan sans live_slots : « loadout
    # suggestion »). On garde les arguments de son propre appel pour lui redemander cette proposition
    # quand le plan est impossible avec les bobines en place. Aucune logique d'attribution ici.
    calls, orig = {}, getattr(core, "build_one_plan", None)
    if callable(orig) and "live_slots" in _params(orig):
        def spy(*a, **k):
            if len(a) > 1 and a[1] in ("optimize", "layer"):
                calls[a[1]] = (a, dict(k))
            return orig(*a, **k)
        core.build_one_plan = spy
    try:
        report = core.build_report(pp, slicer_colors=colors, slicer_types=types, num_aces=naces, plan_proxy=plan,
                                   live_slots=live["live_slots"], head_ctx=live.get("head_ctx") or {"mode": "multi"},
                                   token="", filename=name, size=os.path.getsize(path), meta=meta, **extra)
    except Exception as e:
        if type(e).__name__ == "PreflightRejected":
            raise MultiAceError(str(e))
        raise U1CodeError("le Preflight de la U1 a échoué (%s)" % str(e)[:160])
    finally:
        if callable(orig):
            core.build_one_plan = orig
    plans = report.get("plans") if isinstance(report, dict) else None
    if isinstance(plans, dict):
        for k, (a, kw) in calls.items():
            cur = plans.get(k) or {}
            if cur.get("feasible") or "loaded spools" not in str(cur.get("reason") or ""):
                continue
            try:
                sug = orig(*a, **dict(kw, live_slots=None))
            except Exception:
                continue
            if isinstance(sug, dict) and sug.get("feasible"):
                sug["suggested"] = True                # disposition a faire a la main (tier « planned »)
                sug["live_reason"] = cur.get("reason")
                plans[k] = sug
    if not isinstance(plans, dict) or not any(isinstance(p, dict) and p.get("feasible") for p in plans.values()):
        raise U1CodeError("ce mode de têtes se règle dans le Preflight de multiACE")
    report["_prefs_ok"] = bool(caps.get("prefs"))
    return report, live, sha


# Options de lancement pour multiACE 1.27b : dans cette version, elles ne font pas partie du code
# partage (preflight_core) mais du serveur multiACE (main.py : _print_prefs_line, _flow_cal_block,
# _prepend_print_prefs, decay71/multiACE v1.27b, GPL-3.0). Reprises ici a l'identique, utilisees
# SEULEMENT si le code de la U1 ne fournit pas prepend_print_prefs (versions plus recentes : le leur).
_FLOW_CAL_LINE_127 = re.compile(r"^\s*SM_PRINT_FLOW_CALIBRATE\b", re.IGNORECASE)
_AUTO_LOAD_END_127 = re.compile(r"^\s*;\s*multiACE auto-load: end\b")
_BARE_T_127 = re.compile(r"^\s*T(\d+)\s*(?:;.*)?$")


def _flow_cal_block_127(lines):
    end_idx = None
    initial = None
    heads = set()
    for i, line in enumerate(lines):
        m = _BARE_T_127.match(line)
        if m:
            h = int(m.group(1))
            if 0 <= h <= 3:
                heads.add(h)
                if end_idx is None:
                    initial = h
            continue
        if end_idx is None and _AUTO_LOAD_END_127.match(line):
            end_idx = i
    if end_idx is None or not heads:
        return None, []
    if initial is None:
        initial = min(heads)
    block = ["; multiACE preflight: flow calibration (moved behind the auto-load, heads loaded)\n"]
    order = sorted(h for h in heads if h != initial) + ([initial] if initial in heads else [])
    for h in order:
        block.append("T%d A0\n" % h)
        block.append("FLOW_CALIBRATE EXTRUDER=%d\n" % h)
    block.append("T%d\n" % initial)
    block.append("; multiACE preflight: flow calibration end\n")
    return end_idx + 1, block


def prepend_print_prefs_127(in_path, out_path, bed_mesh=False, camera=False, flow_cal=False):
    ins_idx, block = None, []
    if flow_cal:
        with open(in_path, "r", encoding="utf-8", errors="replace") as src:
            ins_idx, block = _flow_cal_block_127(src.readlines())
    i = -1
    with open(out_path, "w", encoding="utf-8", errors="replace") as out:
        out.write("; multiACE preflight: print preferences\n")
        out.write("SET_PRINT_PREFERENCES BED_LEVEL=%d FLOW_CALIBRATE=%d TIME_LAPSE_CAMERA=%d FORCE=1\n"
                  % (1 if bed_mesh else 0, 1 if flow_cal else 0, 1 if camera else 0))
        with open(in_path, "r", encoding="utf-8", errors="replace") as src:
            for i, line in enumerate(src):
                if ins_idx is not None and i == ins_idx:
                    out.writelines(block)
                if line.lstrip().upper().startswith("SET_PRINT_PREFERENCES"):
                    out.write("; multiACE disabled: " + line.lstrip())
                    continue
                if ins_idx is not None and _FLOW_CAL_LINE_127.match(line):
                    out.write("; multiACE moved: " + line.lstrip())
                    continue
                out.write(line)
            if ins_idx is not None and ins_idx >= i + 1:
                out.writelines(block)


def autoload_heads(path):
    """Tetes chargees au depart par le bloc « multiACE auto-load » du fichier prepare (None : pas de bloc)."""
    head, _tail = read_head_tail(path, head_bytes=1 << 20, tail_bytes=0)
    m = re.search(r"^; multiACE auto-load:.*?^; multiACE auto-load: end", head, re.M | re.S)
    if not m:
        return None
    return sorted({int(h) for h in re.findall(r"^ACE_(?:SWAP|LOAD)_HEAD HEAD=(\d)", m.group(0), re.M)})


def used_filaments(info):
    """Filaments vraiment imprimes (grammes > 0 ou outil appele dans le G-code) ; None si inconnu."""
    grams, order = (info or {}).get("grams") or [], (info or {}).get("order") or []
    if not grams and not order:
        return None
    return {t for t, g in enumerate(grams) if g > 0} | set(order)


COLOR_TIERS = ("exact_hex", "name_exact", "name_base", "name_canon", "fuzzy")   # la U1 a trouve la couleur


def placement_todo(report, plan_name, used=None):
    """Plans « optimize » / « layer » de multiACE 1.27b : une disposition PROPOSEE (tier « planned »),
    pas les bobines chargees. Liste des filaments dont la bobine (celle que la U1 associe a la couleur
    dans le plan « slicer ») n'est pas encore a la place proposee. Vide = pret a imprimer."""
    plans = (report or {}).get("plans") or {}
    rows = (plans.get(plan_name) or {}).get("mapping") or []
    if plan_name == "slicer" or not any(m.get("tier") == "planned" for m in rows):
        return []
    src = {m.get("t"): m.get("slot") for m in (plans.get("slicer") or {}).get("mapping") or []
           if m.get("tier") in COLOR_TIERS}
    todo = []
    for m in rows:
        if used is not None and m.get("t") not in used:
            continue
        tgt, have = m.get("slot") or {}, src.get(m.get("t")) or {}
        if not have or (have.get("ace"), have.get("slot")) != (tgt.get("ace"), tgt.get("slot")):
            todo.append(m.get("t"))
    return todo


def u1_prepare(client, path, name, plan_name, prefs, expected, report=None, forced=None):
    """Recalcule avec le chargement du moment, ecrit le G-code pret a imprimer, le verifie.
    forced : bobines imposees par l'utilisateur ({t: ace*4+slot}, plan « Comme tranché » seulement),
    passees telles quelles au code de la U1 (remap_override, comme son interface web)."""
    pp, core, _sha = u1_code(client)
    live = _live(client)
    if _signature(live) != expected:
        raise MultiAceError("les bobines ont changé depuis l'analyse : vérifie la nouvelle proposition")
    caps = _u1code.get("caps") or {}
    extra = {}
    if forced:
        if plan_name != "slicer":
            raise MultiAceError("les bobines imposées ne s'appliquent qu'au plan « Comme tranché »")
        if not caps.get("remap"):
            raise U1CodeError("cette version de multiACE ne permet pas d'imposer une bobine")
        extra["remap_override"] = forced_remap(report, forced, live["live_slots"])
    folder = os.path.join(storage_dir(), "u1run")
    os.makedirs(folder, exist_ok=True)
    tmp_a, tmp_b, tmp_c = (os.path.join(folder, n) for n in ("a.gcode", "b.gcode", "c.gcode"))
    colors, types, naces, _used, _plan, meta = core.parse_meta(pp, _read_lines(path))
    final = core.rewrite_pipeline(pp, src_path=path, tmp_a=tmp_a, tmp_b=tmp_b, slicer_colors=colors,
                                  slicer_types=types, num_aces=naces, live_slots=live["live_slots"],
                                  head_ctx=live.get("head_ctx") or {"mode": "multi"}, mode=plan_name,
                                  meta=meta, **extra)

    def nxt(cur):
        return next(p for p in (tmp_a, tmp_b, tmp_c) if p != cur and p != path)

    if prefs.get("bed") or prefs.get("cam") or prefs.get("flow"):
        other = nxt(final)
        fn = core.prepend_print_prefs if caps.get("prefs") else prepend_print_prefs_127
        fn(final, other, bool(prefs.get("bed")), bool(prefs.get("cam")), bool(prefs.get("flow")))
        final = other
    heads = prefs.get("flow_heads")
    if prefs.get("flow") and isinstance(heads, list):
        other = nxt(final)
        limit_flow_heads(final, other, [h for h in heads if isinstance(h, int) and 0 <= h <= 3])
        final = other
    if prefs.get("bed") and prefs.get("zone"):
        other = nxt(final)
        mesh_on_print_zone(final, other)
        final = other
    if prefs.get("soft"):
        other = nxt(final)
        soft_start(final, other)
        final = other
    # Verifications du fichier produit avant tout envoi.
    if not os.path.exists(final) or os.path.getsize(final) < 1024:
        raise MultiAceError("fichier préparé vide")
    facts = gcode_facts(final)
    if not facts["processed"]:
        raise MultiAceError("le fichier préparé n'a pas la marque multiACE : envoi annulé")
    if hasattr(core, "used_ace_slots_file"):
        present = {(s.get("ace"), s.get("slot")) for s in live["live_slots"]}
        used = {tuple(x) for x in core.used_ace_slots_file(final) or []}
        if not used <= present:
            raise MultiAceError("le fichier utilise une bobine absente : envoi annulé")
    return final


# ---- informations du fichier tranche et du chargement (affichage seulement, aucun choix de bobine)

_T_LINE = re.compile(r"^T(\d+)\s*(?:;.*)?$")
_THUMB_RE = re.compile(r"^; thumbnail(?:_(PNG|JPG))? begin (\d+)x(\d+) \d+\s*\n(.*?)^; thumbnail(?:_(?:PNG|JPG))? end",
                       re.M | re.S)


def _header_value(text, key):
    m = re.search(r"^;\s*%s\s*=\s*(.*)$" % re.escape(key), text, re.M)
    return m.group(1).strip() if m else None


def slice_info(path):
    """Ce que le slicer a prevu, lu dans l'export : buse pour laquelle chaque filament est tranche,
    grammes, ordre de premiere utilisation des filaments, vignette."""
    head, tail = read_head_tail(path, head_bytes=1 << 20, tail_bytes=1 << 20)
    text = head + "\n" + tail
    vol = [NOZZLE_FR.get(v.strip().strip('"').lower(), v.strip().strip('"'))
           for v in _split(_header_value(text, "nozzle_volume_type"))]
    fmap = []
    for v in _split(_header_value(text, "filament_map")):
        try:
            fmap.append(int(v) - 1)
        except ValueError:
            fmap.append(None)
    grams = []
    for v in _split(_header_value(text, "filament used [g]")):
        try:
            grams.append(float(v))
        except ValueError:
            grams.append(0.0)
    sliced = []
    for t in range(max(len(grams), len(fmap))):
        e = fmap[t] if t < len(fmap) and fmap[t] is not None and 0 <= fmap[t] <= 3 else (t if t <= 3 else None)
        sliced.append({"head": e, "nozzle": vol[e] if e is not None and e < len(vol) else ""})
    want = {t for t, g in enumerate(grams) if g > 0} or None
    order = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line[:1] != "T":
                continue
            m = _T_LINE.match(line)
            if m:
                t = int(m.group(1))
                if t not in order:
                    order.append(t)
                    if want is not None and want <= set(order):
                        break
    thumb, best = None, 0
    for m in _THUMB_RE.finditer(head):
        area = int(m.group(2)) * int(m.group(3))
        if best < area <= 600 * 600:
            data = "".join(l.lstrip("; ").strip() for l in m.group(4).splitlines())
            if re.fullmatch(r"[A-Za-z0-9+/=]+", data or ""):
                thumb = "data:image/%s;base64,%s" % ("jpeg" if m.group(1) == "JPG" else "png", data)
                best = area
    return {"sliced": sliced, "grams": grams, "order": order, "thumb": thumb}


def load_info(client):
    """Bobines des ACE (poids, PA memorise) et buses vissees, lues dans la U1. Lecture seule."""
    try:
        state = client.state(timeout=TIMEOUT_BG)
    except Exception:
        state = {}
    spools, binding = state.get("spools") or {}, state.get("spool_binding") or {}
    slots = {}
    for key, sid in binding.items():
        m = re.fullmatch(r"(\d+)_(\d+)", str(key))
        sp = spools.get(str(sid)) if sid is not None else None
        if not m or not isinstance(sp, dict):
            continue
        pam = {}
        for k, v in (sp.get("pa_matrix") or {}).items():
            if isinstance(v, (int, float)):
                pam[str(k)] = float(v)
        try:
            w = float(sp.get("weight_g")) if sp.get("weight_g") is not None else None
        except (TypeError, ValueError):
            w = None
        slots["%s_%s" % (m.group(1), m.group(2))] = {"spool": str(sid), "grams": w, "pa": pam}
    try:
        real, src = effective_nozzles(client)
    except Exception:
        real, src = load_settings()["real_nozzles"], "manuel"
    dia = str(load_settings().get("nozzle") or "0.4")
    try:
        dia = "%g" % float(dia)
    except ValueError:
        pass
    ident = {}
    for x in all_slots_from_state(state):
        if isinstance(x.get("slot"), int):
            k = "%d_%d" % (x["ace"], x["slot"])
            sp = binding.get(k)
            ident[k] = {"material": x["material"], "brand": x["brand"], "color": x["color"], "source": x["source"],
                        "subtype": "", "spool": str(sp) if sp is not None else None}
    for a in state.get("aces") or []:
        for sl in a.get("slots") or []:
            k = "%s_%s" % (a.get("idx"), sl.get("idx"))
            if k in ident:
                ident[k]["subtype"] = sl.get("subtype") or ""
    return {"slots": slots, "real": real, "real_src": src, "dia": dia, "ident": ident}


def forced_remap(report, forced, live_slots):
    """Bobines imposees par l'utilisateur -> remap_override du code multiACE (format de son interface
    web : {"t": ace*4+slot}), appliqué tel quel par la U1. Aucune decision prise ici."""
    plan = ((report or {}).get("plans") or {}).get("slicer") or {}
    present = {int(s["ace"]) * 4 + int(s["slot"]) for s in live_slots or []
               if isinstance(s.get("ace"), int) and isinstance(s.get("slot"), int)}
    known = {int(c["t"]) for c in (report or {}).get("slicer_colors") or [] if isinstance(c.get("t"), int)}
    eff = {}
    for m in plan.get("mapping") or []:
        s = m.get("slot") or {}
        if isinstance(m.get("t"), int) and isinstance(s.get("ace"), int) and isinstance(s.get("slot"), int):
            eff[m["t"]] = s["ace"] * 4 + s["slot"]
    for k, v in (forced or {}).items():
        try:
            t, synth = int(k), int(v)
        except (TypeError, ValueError):
            raise MultiAceError("choix de bobine illisible")
        if t not in known or synth not in present:
            raise MultiAceError("bobine choisie absente des ACE : recharge la proposition")
        eff[t] = synth
    return {str(t): s for t, s in eff.items() if s != t}


_MESH_LINE = re.compile(r"^(\s*BED_MESH_CALIBRATE\b)([^;\n]*)(.*)$", re.I)
_EXCL_POLY = re.compile(r"^EXCLUDE_OBJECT_DEFINE\b.*?\bPOLYGON=(\[\[.*\]\])", re.I)
MESH_MARGIN = 5.0     # mm autour de la zone imprimee


def _print_zone(path):
    """Contour de ce qui est imprime sur le plateau : objets declares (EXCLUDE_OBJECT_DEFINE) et tout ce
    qui est extrude a la 1re couche (tour de purge, jupe, bordure comprises)."""
    xs, ys = [], []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        layers, x, y = 0, None, None
        for line in f:
            m = _EXCL_POLY.match(line)
            if m:
                try:
                    for px, py in json.loads(m.group(1)):
                        xs.append(float(px))
                        ys.append(float(py))
                except (ValueError, TypeError):
                    pass
                continue
            if line.startswith(";LAYER_CHANGE") or line.startswith("; LAYER_CHANGE"):
                layers += 1
                if layers > 1:
                    break
                continue
            if layers == 1 and line[:2] in ("G0", "G1"):
                mx = re.search(r"\bX(-?\d+(?:\.\d*)?)", line)
                my = re.search(r"\bY(-?\d+(?:\.\d*)?)", line)
                x = float(mx.group(1)) if mx else x
                y = float(my.group(1)) if my else y
                me = re.search(r"\bE(-?\d+(?:\.\d*)?)", line)
                if me and float(me.group(1)) > 0 and x is not None and y is not None:
                    xs.append(x)
                    ys.append(y)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _pair(text, key):
    m = re.search(r"\b%s\s*=\s*(-?\d+(?:\.\d*)?)\s*[,x]\s*(-?\d+(?:\.\d*)?)" % key, text, re.I)
    return (float(m.group(1)), float(m.group(2))) if m else None


def mesh_on_print_zone(in_path, out_path):
    """Maillage du plateau limite a la zone imprimee : le BED_MESH_CALIBRATE du debut qui palpe tout le
    plateau recoit MESH_MIN / MESH_MAX (commande Klipper standard, geree par le firmware de la U1) et
    un nombre de points qui garde l'ecart d'origine. Rien n'est touche si la ligne vise deja une zone
    (profil avec maillage adaptatif) ou si la zone est introuvable. Retourne le texte de la ligne."""
    head, tail = read_head_tail(in_path, head_bytes=1 << 20, tail_bytes=1 << 20)
    cfg = tail + "\n" + head
    lo = _pair(cfg, r";\s*bed_mesh_min") or (3.0, 3.0)
    hi = _pair(cfg, r";\s*bed_mesh_max") or (267.0, 267.0)
    zone = _print_zone(in_path)
    done = None
    with open(in_path, "r", encoding="utf-8", errors="replace") as src, \
            open(out_path, "w", encoding="utf-8", newline="\n") as out:
        for line in src:
            if done is None:
                m = _MESH_LINE.match(line)
                if m:
                    args = m.group(2)
                    if zone is None or re.search(r"\bMESH_M(IN|AX)\s*=|\bADAPTIVE\s*=\s*1", args, re.I):
                        done = ""
                    else:
                        x0 = max(lo[0], zone[0] - MESH_MARGIN)
                        y0 = max(lo[1], zone[1] - MESH_MARGIN)
                        x1 = min(hi[0], zone[2] + MESH_MARGIN)
                        y1 = min(hi[1], zone[3] + MESH_MARGIN)
                        pc = _pair(args, "PROBE_COUNT") or (11.0, 11.0)
                        dx = (hi[0] - lo[0]) / max(1.0, pc[0] - 1)
                        dy = (hi[1] - lo[1]) / max(1.0, pc[1] - 1)
                        nx = max(4, min(int(pc[0]), int(-(-(x1 - x0) // dx)) + 1))
                        ny = max(4, min(int(pc[1]), int(-(-(y1 - y0) // dy)) + 1))
                        if x1 - x0 < 10 or y1 - y0 < 10:
                            done = ""
                        else:
                            rest = re.sub(r"\bPROBE_COUNT\s*=\s*\S+", "", args, flags=re.I).strip()
                            new = "%s MESH_MIN=%.2f,%.2f MESH_MAX=%.2f,%.2f PROBE_COUNT=%d,%d%s%s" % (
                                m.group(1).rstrip(), x0, y0, x1, y1, nx, ny, (" " + rest) if rest else "",
                                (" " + m.group(3)) if m.group(3) else "")
                            out.write("; multiACE Bridge: maillage limite a la zone imprimee (avant : %s)\n"
                                      % line.strip())
                            out.write(new.rstrip() + "\n")
                            done = new.strip()
                            continue
            out.write(line)
    return done or ""


_AUTO_END = re.compile(r"^\s*;\s*multiACE auto-load: end\b")
_MESH_ANY = re.compile(r"^\s*(?:BED_MESH_CALIBRATE|AUTO_BED_MESH_CALIBRATE)\b", re.I)
_LAYER_CH = re.compile(r"^\s*;\s*LAYER_CHANGE\b")
_M204 = re.compile(r"^\s*M204\s+S(\d+)", re.I)
_TRAVEL = re.compile(r"^(\s*G[01]\b)([^;]*?)\bF(\d+(?:\.\d*)?)([^;]*)(;.*)?$", re.I)
SOFT_START_F = 6000         # mm/min (100 mm/s) : vitesse max des deplacements avant la 1re couche
SOFT_START_ACCEL = 3000     # mm/s2 pendant ces deplacements
SOFT_START_LIFT = 5         # mm : on remonte d'abord la buse


def soft_start(in_path, out_path):
    """Depart en douceur (repris de la 0.33) : entre la fin du chargement auto (ou du maillage du plateau)
    et la 1re couche, les deplacements sans extrusion plus rapides que SOFT_START_F sont ralentis, avec
    une acceleration reduite, et la buse remonte d'abord de SOFT_START_LIFT mm. Evite le choc de la tete
    qui traverse le plateau a 300 mm/s vers la ligne d'amorce. Retourne le nombre de lignes ralenties."""
    end_idx = mesh_idx = layer_idx = None
    accel = 10000
    with open(in_path, "r", encoding="utf-8", errors="replace") as src:
        for i, line in enumerate(src):
            if _AUTO_END.match(line):
                end_idx = i
            elif _MESH_ANY.match(line):
                mesh_idx = i
            elif _LAYER_CH.match(line):
                layer_idx = i
                break
            else:
                m = _M204.match(line)
                if m:
                    accel = int(m.group(1))
    start = end_idx if end_idx is not None else mesh_idx
    if mesh_idx is not None and start is not None:
        start = max(start, mesh_idx)
    done = 0
    on = False
    with open(in_path, "r", encoding="utf-8", errors="replace") as src, \
            open(out_path, "w", encoding="utf-8", newline="\n") as out:
        for i, line in enumerate(src):
            if start is not None and layer_idx is not None and start < i < layer_idx:
                t = _TRAVEL.match(line)
                if t and " E" not in (" " + t.group(2) + t.group(4)).upper() and float(t.group(3)) > SOFT_START_F \
                        and re.search(r"\b[XY]-?\d", t.group(2) + t.group(4), re.I):
                    if not on:
                        on = True
                        out.write("; multiACE Bridge: deplacement doux vers la ligne d'amorce\n")
                        out.write("M204 S%d\nG91\nG1 Z%d F1200\nG90\n" % (SOFT_START_ACCEL, SOFT_START_LIFT))
                    out.write("%s%sF%d%s ; multiACE Bridge: F%s ralenti\n"
                              % (t.group(1), t.group(2), SOFT_START_F, t.group(4).rstrip(), t.group(3)))
                    done += 1
                    continue
            if on and i == layer_idx:
                out.write("M204 S%d ; multiACE Bridge: acceleration d'origine\n" % accel)
                on = False
            out.write(line)
    return done


_FLOW_PAIR = re.compile(r"^\s*(?:T(\d+)\s+A0|FLOW_CALIBRATE\s+EXTRUDER=(\d+))\s*$", re.I)


def limit_flow_heads(in_path, out_path, heads):
    """Calibration du flux seulement sur les tetes cochees : dans le bloc ajoute par multiACE, les paires
    T<h> A0 / FLOW_CALIBRATE des autres tetes sont mises en commentaire (elles gardent le PA memorise)."""
    keep = {int(h) for h in heads}
    inside = False
    with open(in_path, "r", encoding="utf-8", errors="replace") as src, \
            open(out_path, "w", encoding="utf-8", newline="\n") as out:
        for line in src:
            low = line.lower()
            if "flow calibration" in low and line.lstrip().startswith(";"):
                inside = not low.rstrip().endswith("end")
                out.write(line)
                continue
            if inside:
                m = _FLOW_PAIR.match(line)
                if m:
                    h = int(m.group(1) or m.group(2))
                    if h not in keep:
                        out.write("; multiACE Bridge skipped: " + line.lstrip())
                        continue
            out.write(line)



U1_PAGE = r"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<style>
:root{--fg:#e9ecef;--muted:#9aa3ad;--line:rgba(255,255,255,.12);--accent:#009688;--bad:#e05a4f;--warn:#e0a030;
  color-scheme:dark;font:13px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
*{box-sizing:border-box}body{margin:0;padding:16px 18px 24px;background:#1b1e22;color:var(--fg)}
.hdr{display:flex;gap:14px;align-items:center;margin-bottom:12px}
.hdr img{width:92px;height:92px;object-fit:contain;border-radius:10px;background:rgba(255,255,255,.04);border:1px solid var(--line)}
h1{font-size:16px;margin:0 0 2px;word-break:break-all}.sub{color:var(--muted);margin:0;font-size:12px}
.banner{border-radius:8px;padding:9px 12px;margin-bottom:10px;background:rgba(80,120,255,.14);color:#c9d3ff}
.alerts{border-radius:8px;padding:9px 12px;margin-bottom:10px;background:rgba(224,160,48,.13);color:#f1c27d}.alerts div{margin:2px 0}
.err{background:rgba(224,90,79,.15);border-radius:8px;padding:12px;margin-bottom:12px}
.stats{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:10px}
.stat{background:rgba(255,255,255,.04);border:1px solid var(--line);border-radius:9px;padding:8px 12px;min-width:120px}
.stat b{display:block;font-size:20px;font-variant-numeric:tabular-nums}.stat span{color:var(--muted);font-size:11.5px}
.plans{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 10px}
.plans label{display:flex;gap:6px;align-items:center;border:1px solid var(--line);border-radius:8px;padding:6px 10px;cursor:pointer}
.plans label.on{border-color:var(--accent);background:rgba(0,150,136,.12)}.plans label.off{opacity:.45;cursor:default}
table{width:100%;border-collapse:collapse;margin-bottom:8px}
th{font-size:11px;text-transform:uppercase;letter-spacing:.6px;color:var(--muted);text-align:left;font-weight:600;padding:4px 6px;border-bottom:1px solid var(--line)}
td{padding:6px;border-bottom:1px solid var(--line);vertical-align:middle}
.sw{display:inline-block;width:16px;height:16px;border-radius:50%;border:1px solid rgba(255,255,255,.3);vertical-align:-3px;margin-right:6px;flex:none}
.arrow{color:var(--muted);text-align:center}
.tag{font-size:11px;border-radius:4px;padding:1px 6px;background:rgba(0,150,136,.18);color:#4fd1c0;white-space:nowrap;margin-right:4px}
.tag.warn{background:rgba(224,160,48,.18);color:var(--warn)}.tag.man{background:rgba(120,140,255,.18);color:#aab6ff}
.tag.noz{background:rgba(224,90,79,.18);color:#f08a80}
small,.muted{color:var(--muted)}
.pick{position:relative;width:340px}
td:first-child{min-width:190px}td:nth-child(3){min-width:170px}
.pk{width:100%;display:flex;align-items:center;gap:6px;background:rgba(255,255,255,.06);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:5px 8px;font:inherit;cursor:pointer;text-align:left}
.pk .lbl{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.pk .car{color:var(--muted);font-size:10px}
.pk.changed{border-color:#aab6ff}
.menu{position:absolute;z-index:10;right:0;top:calc(100% + 3px);background:#25292e;border:1px solid var(--line);border-radius:8px;padding:4px;box-shadow:0 8px 24px rgba(0,0,0,.5);max-height:320px;overflow:auto;min-width:100%;width:max-content;max-width:520px}
.menu div{display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:5px;cursor:pointer;white-space:nowrap}
.menu div:hover,.menu div.sel{background:rgba(255,255,255,.08)}.menu .sep{height:1px;padding:0;margin:3px 4px;background:var(--line);cursor:default}
.hint{color:var(--muted);font-size:11.5px;margin:0 0 12px}
.card{border-radius:8px;padding:12px;margin-bottom:12px;background:rgba(255,255,255,.04)}
.opt{display:flex;align-items:center;gap:6px;margin:6px 0 0;cursor:pointer}.optsub{margin:4px 0 4px 24px;font-size:12px}
.optsub .opt{margin:3px 0}.okc{color:#4fd1c0}.warnc{color:#f0b060}
button{background:var(--accent);color:#fff;border:0;border-radius:6px;padding:8px 14px;font:inherit;cursor:pointer}
button.ghost{background:transparent;color:var(--fg);border:1px solid var(--line)}button.mini{padding:2px 8px;font-size:11px;margin-left:6px}
button:disabled{opacity:.4;cursor:default}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:12px 0}
#msg{margin-top:8px}.msg.ok{color:#3fb27f}.msg.bad{background:rgba(224,90,79,.15);border-radius:8px;padding:8px}
.lay{background:rgba(66,133,244,.08);border:1px solid rgba(66,133,244,.25);border-radius:8px;padding:12px;margin-bottom:12px}
.lay.ok{background:rgba(0,150,136,.10);border-color:rgba(0,150,136,.35)}
.psub{margin:10px 0 4px;font-size:12px;color:#9aa4b2;text-transform:uppercase;letter-spacing:.04em}
ol.steps{margin:0 0 4px 18px;padding:0}ol.steps li{margin:4px 0}
table.grid{width:100%;border-collapse:collapse;margin:2px 0 8px;table-layout:fixed}
table.grid th,table.grid td{border:1px solid rgba(255,255,255,.08);padding:6px;font-size:12px;text-align:left;vertical-align:top}
table.grid td.mv{background:rgba(66,133,244,.14)}.tag.mv{background:rgba(66,133,244,.22);color:#9cc0ff}.tag.un{background:rgba(255,255,255,.08);color:#9aa4b2}
.loading{display:flex;align-items:center;gap:12px;padding:30px 0;color:var(--muted)}
.spin{width:22px;height:22px;border:3px solid rgba(255,255,255,.15);border-top-color:#009688;border-radius:50%;animation:r 1s linear infinite}
@keyframes r{to{transform:rotate(360deg)}}
</style></head><body><div id="app"></div>
<script>
var D=__DATA__;
(function(){
var S={sel:null,forced:{},flow:null,busy:false,msg:null,open:null,done:{}};
function esc(x){var d=document.createElement("span");d.textContent=x==null?"":String(x);return d.innerHTML}
function col(c){var m=/^#?([0-9a-fA-F]{6})/.exec(String(c||"").trim());return m?"#"+m[1]:"#777"}
function post(m){try{window.orca.postMessage(m)}catch(e){try{window.chrome.webview.postMessage(m)}catch(_){}}}
function rgb(h){h=col(h).slice(1);return [parseInt(h.slice(0,2),16),parseInt(h.slice(2,4),16),parseInt(h.slice(4,6),16)]}
function cname(h){
  var c=rgb(h),r=c[0]/255,g=c[1]/255,b=c[2]/255,mx=Math.max(r,g,b),mn=Math.min(r,g,b),l=(mx+mn)/2,d=mx-mn,s=0,hu=0;
  if(d>0){s=d/(1-Math.abs(2*l-1));hu=mx===r?((g-b)/d)%6:mx===g?(b-r)/d+2:(r-g)/d+4;hu=(hu*60+360)%360}
  if(l>0.9)return "Blanc";if(l<0.1)return "Noir";
  if(s<0.15)return l>0.7?"Gris clair":l<0.32?"Gris foncé":"Gris";
  if(hu<12||hu>=345)return l<0.3?"Bordeaux":l>0.75?"Rose":"Rouge";
  if(hu<42)return (l<0.45||s<0.45)?(l>0.6?"Beige":"Marron"):(l>0.75?"Pêche":"Orange");
  if(hu<66)return l<0.35?"Kaki":(s<0.5&&l>0.7?"Crème":"Jaune");
  if(hu<160)return l<0.28?"Vert foncé":l>0.7?"Vert clair":"Vert";
  if(hu<195)return l>0.7?"Cyan clair":"Turquoise";
  if(hu<250)return l<0.3?"Bleu foncé":l>0.7?"Bleu clair":"Bleu";
  if(hu<290)return l>0.7?"Lavande":"Violet";
  return (s>0.6&&l<0.55)?"Magenta":"Rose";
}
function sw(h){return '<span class="sw" style="background:'+col(h)+'"></span>'}
var COLOR_TIERS={exact_hex:1,name_exact:1,name_base:1,name_canon:1,fuzzy:1};
var TIER={exact_hex:"couleur identique",name_exact:"même nom de couleur",name_base:"nom de couleur proche",name_canon:"nom de couleur proche",
  fuzzy:"couleur proche (nuance)",fallback:"même matière, autre couleur",duplicate:"bobine partagée",planned:"disposition proposée",no_slot:"aucune bobine"};
function tierTag(t){if(!t)return "";var loose=/^loose_/.test(t),b=t.replace(/^loose_/,""),w=/fallback|duplicate|no_slot/.test(b)||loose;
  return '<span class="tag'+(w?' warn':'')+'">'+esc(TIER[b]||b)+'</span>'+(loose?'<span class="tag warn">matière différente</span>':'')}
function L(){return D.load||{slots:{},real:["","","",""],dia:"0.4"}}
function I(){return D.info||{sliced:[],grams:[],order:[]}}
function live(){return (D.report&&D.report.live_slots)||[]}
function synth(s){return s.ace*4+s.slot}
function slotBy(n){var a=live();for(var i=0;i<a.length;i++)if(synth(a[i])===n)return a[i];return null}
function realOf(h){var r=L().real||[];return h!=null&&h>=0&&h<4?(r[h]||""):""}
function vt(n){return n==="Haut débit"?"high_flow":n==="Standard"?"standard":""}
function grams(s){var x=L().slots[s.ace+"_"+s.slot];return x&&x.grams>0?' · ≈ '+Math.round(x.grams)+' g':''}
function forcedOn(){return Object.keys(S.forced).length>0}
var REASON={"loaded spools do not fit this layout":"impossible avec les bobines chargées","no feasible head assignment":"aucune répartition possible sur les têtes",
  "no layer-feasible head assignment":"aucune répartition par couche possible","no layer-feasible loadout":"aucune disposition par couche possible",
  ">4 colors in some layer":"plus de 4 couleurs dans une couche","too many colours for the loadout":"trop de couleurs pour les têtes"};
function reasonFr(r){return REASON[r]||r||"impossible"}
function dur(s){s=Math.round(+s||0);var h=Math.floor(s/3600),m=Math.round((s%3600)/60);if(m===60){h++;m=0}return h?(h+" h "+(m<10?"0":"")+m):(m+" min")}
function estTxt(e){return e&&e.total_s?"≈ "+dur(e.total_s):""}
function usedT(t){var g=I().grams||[],o=I().order||[];if(!g.length&&!o.length)return true;return (g[t]>0)||o.indexOf(t)>=0}
function hiddenCount(){var r=D.report||{},n=0;(r.slicer_colors||[]).forEach(function(c){if(!usedT(c.t))n++});return n}
function planKey(){return forcedOn()?"slicer":S.sel}
function mapping(){
  var r=D.report||{},p=(r.plans||{})[planKey()]||{},out=[];
  (p.mapping||[]).forEach(function(m){if(!usedT(m.t))return;var s=m.slot;var row={t:m.t,slot:s?{ace:s.ace,slot:s.slot,material:s.material,color:s.color}:null,tier:m.tier,loose:m.loose_mat};
    if(S.forced[m.t]!=null){var f=slotBy(S.forced[m.t]);if(f){row.slot={ace:f.ace,slot:f.slot,material:f.material,color:f.color,name:f.name};row.tier="manual"}}
    out.push(row)});
  return out}
function headOf(row){return row.slot?row.slot.slot:null}
function placement(){
  var r=D.report||{},k=planKey();if(!r.plans||k==="slicer"||forcedOn())return null;
  var p=r.plans[k]||{},rows=(p.mapping||[]).filter(function(m){return usedT(m.t)});if(!rows.some(function(m){return m.tier==="planned"}))return null;
  var src={};((r.plans.slicer||{}).mapping||[]).forEach(function(m){if(m.slot&&COLOR_TIERS[m.tier])src[m.t]={ace:m.slot.ace,slot:m.slot.slot,color:m.slot.color}});
  var moves=[],missing=[],tg={};
  rows.forEach(function(m){if(!m.slot)return;var key=m.slot.ace+"_"+m.slot.slot,s=src[m.t];tg[key]={t:m.t,s:s,c:(s&&s.color)||m.slot.color};
    if(!s)missing.push(m.t);else if(s.ace!==m.slot.ace||s.slot!==m.slot.slot)moves.push({t:m.t,from:s,to:{ace:m.slot.ace,slot:m.slot.slot},c:s.color})});
  var occ={};live().forEach(function(x){occ[x.ace+"_"+x.slot]=x});
  var srcKeys={};moves.forEach(function(m){srcKeys[m.from.ace+"_"+m.from.slot]=m});
  var order=[],left=moves.slice(),free={},guard=0;
  while(left.length&&guard++<40){var i=-1;for(var j=0;j<left.length;j++){var k2=left[j].to.ace+"_"+left[j].to.slot,o=occ[k2];
      if(!o||free[k2]||!(srcKeys[k2]&&left.indexOf(srcKeys[k2])>=0)){i=j;break}}
    if(i<0){order.push({park:left[0].to});free[left[0].to.ace+"_"+left[0].to.slot]=1;continue}
    var mv=left.splice(i,1)[0],k3=mv.to.ace+"_"+mv.to.slot,o2=occ[k3];if(o2&&!srcKeys[k3]&&!free[k3])mv.out=o2;
    free[mv.from.ace+"_"+mv.from.slot]=1;order.push(mv)}
  // couleurs qu'aucune bobine chargee n'a : une bobine a poser (prise hors des ACE)
  var sc={};(r.slicer_colors||[]).forEach(function(x){sc[x.t]=x});
  rows.forEach(function(m){if(!m.slot||src[m.t])return;var k4=m.slot.ace+"_"+m.slot.slot,o4=occ[k4],c4=(sc[m.t]||{}).hex||m.slot.color;
    tg[k4].c=c4;order.push({t:m.t,nw:1,to:{ace:m.slot.ace,slot:m.slot.slot},c:c4,mat:(sc[m.t]||{}).material||m.slot.material||"",out:(o4&&!srcKeys[k4]&&!free[k4])?o4:null})});
  var n=r.num_aces||1;live().forEach(function(x){n=Math.max(n,x.ace+1)});rows.forEach(function(m){if(m.slot)n=Math.max(n,m.slot.ace+1)});
  return {moves:moves,missing:missing,order:order,tg:tg,occ:occ,srcKeys:srcKeys,n:n,ready:!moves.length&&!missing.length}}
function where(a){return "ACE "+(a.ace+1)+" · slot "+(a.slot+1)+" (T"+(a.slot+1)+")"}
function layoutCard(L,colors){
  var r=D.report||{},p=(r.plans||{})[planKey()]||{},sp=((r.plans||{}).slicer||{}).swaps,h='<div class="lay'+(L.ready?' ok':'')+'">';
  h+='<b>Plan « '+esc((D.labels||{})[planKey()]||planKey())+' » : '+p.swaps+' échange(s)'+(sp!=null?' au lieu de '+sp:'')+(L.moves.length?' en déplaçant '+L.moves.length+' bobine(s)':'')+(L.missing.length?(L.moves.length?' et':' en')+' posant '+L.missing.length+' bobine(s) hors des ACE':'')+'.</b>';
  if(L.ready)h+=' <span class="okc">Les bobines sont en place : tu peux lancer.</span>';
  if(L.order.length){h+='<div class="psub">Dans l’ordre :</div><ol class="steps">';
    L.order.forEach(function(m,i){if(m.park){h+='<li>Pose de côté la bobine de '+esc(where(m.park))+' (elle sera remise ensuite)</li>';return}
      if(m.nw){var dn2=S.done[i];h+='<li>'+(m.out?'Retire '+esc(cname(m.out.color))+' de '+esc(where(m.to))+', puis : ':'')+'pose une bobine '+sw(m.c)+'<b>'+esc(cname(m.c))+'</b>'+(m.mat?' '+esc(m.mat):'')+' <small>filament '+(m.t+1)+', pas dans les ACE</small> dans <b>'+esc(where(m.to))+'</b>'+
        (dn2?' <span class="okc">✓ noté</span>':' <button class="ghost mini" data-nw="'+i+'" data-t="'+m.t+'" data-to="'+m.to.ace+'_'+m.to.slot+'"'+(S.busy?' disabled':'')+' title="Après l’avoir posée : le slot reçoit cette couleur et cette matière (une bobine RFID se relit seule)">C’est fait</button>')+'</li>';return}
      var c=colors[m.t]||{},dn=S.done[i];h+='<li>'+(m.out?'Retire '+esc(cname(m.out.color))+' de '+esc(where(m.to))+', puis : ':'')+sw(m.c)+'<b>'+esc(cname(m.c))+'</b> <small>filament '+(m.t+1)+'</small> : '+esc(where(m.from))+' → <b>'+esc(where(m.to))+'</b>'+
        (dn?' <span class="okc">✓ noté</span>':' <button class="ghost mini" data-mv="'+i+'" data-f="'+m.from.ace+'_'+m.from.slot+'" data-to="'+m.to.ace+'_'+m.to.slot+'"'+(S.busy?' disabled':'')+' title="Après l’avoir posée : sa couleur, sa matière et sa bobine de la table multiACE suivent dans le nouveau slot (une bobine RFID se relit seule)">C’est fait</button>')+'</li>'});
    h+='</ol>'}
  if(false)h+='<div class="warnc">Bobine absente des ACE pour : '+L.missing.map(function(t){return "filament "+(t+1)}).join(", ")+'.</div>';
  h+='<div class="psub">Disposition finale :</div><table class="grid"><tr><th></th>';for(var s=0;s<4;s++)h+='<th>Slot '+(s+1)+' (T'+(s+1)+')</th>';h+='</tr>';
  for(var a=0;a<L.n;a++){h+='<tr><th>ACE '+(a+1)+'</th>';for(s=0;s<4;s++){var k=a+"_"+s,t=L.tg[k],o=L.occ[k];
    if(t){var mv=!t.s||(t.s.ace!==a||t.s.slot!==s);h+='<td'+(mv?' class="mv"':'')+'>'+sw(t.c)+esc(cname(t.c))+' <small>fil. '+(t.t+1)+'</small><br>'+(!t.s?'<span class="tag warn">à poser</span>':mv?'<span class="tag mv">à mettre</span>':'<span class="tag">en place</span>')+'</td>'}
    else if(o)h+='<td class="muted">'+sw(o.color)+esc(cname(o.color))+'<br><span class="tag un">'+(L.srcKeys[k]?'libérée':'pas utilisée')+'</span></td>';
    else h+='<td class="muted">vide</td>'}h+='</tr>'}
  h+='</table>';if(!L.ready)h+='<div class="row" style="margin:6px 0 0"><button class="ghost" id="rl2"'+(S.busy?' disabled':'')+'>J’ai placé les bobines : recharger</button><small>Le lancement attend que les bobines soient en place.</small></div>';
  return h+'</div>'}
function nozWarn(row){var sl=(I().sliced||[])[row.t]||{},h=headOf(row),real=realOf(h);
  if(!sl.nozzle||!real||h==null||sl.nozzle===real)return null;
  return {sliced:sl.nozzle,shead:sl.head,real:real,head:h}}
function startHeads(rows){var byT={},seen={},out=[];rows.forEach(function(r){byT[r.t]=r});
  var order=(I().order||[]).slice();rows.forEach(function(r){if(order.indexOf(r.t)<0)order.push(r.t)});
  order.forEach(function(t){var r=byT[t];if(!r||!r.slot)return;var h=headOf(r);if(seen[h])return;seen[h]=1;out.push(r)});return out}
function paOf(row){var x=L().slots[row.slot.ace+"_"+row.slot.slot];var k=L().dia+"_"+vt(realOf(headOf(row)));
  return {spool:x?x.spool:null,pa:x&&x.pa&&x.pa[k]!=null?x.pa[k]:null}}
function cn(c){return (c&&c.name)||cname(c&&(c.hex||c.color))}
function spoolTxt(x,sl,auto){var rl=realOf(x.slot),bad=sl&&sl.nozzle&&rl&&sl.nozzle!==rl;
  return sw(x.color)+'<span class="lbl">'+(auto?'<b>Automatique</b> · ':'')+esc(cname(x.color))+' <small>'+esc(x.material||'')+' · ACE '+(x.ace+1)+' · slot '+(x.slot+1)+' → T'+(x.slot+1)+(rl?' · '+esc(rl):'')+esc(grams(x))+'</small></span>'+
    (bad?'<span class="tag noz">buse ≠ '+esc(sl.nozzle)+'</span>':'')}
function autoSlot(t){var r=D.report||{},p=(r.plans||{})[planKey()||"slicer"]||{},m=(p.mapping||[]).filter(function(x){return x.t===t})[0];return m&&m.slot?m.slot:null}

function render(){
  var a=document.getElementById("app"),r=D.report,h='';
  h+='<div class="hdr">'+(D.info&&D.info.thumb?'<img src="'+esc(D.info.thumb)+'" alt="">':'')+'<div><h1>'+esc(D.name||"multiACE Preflight")+'</h1>';
  h+='<p class="sub">Calcul fait par le code multiACE de ta U1'+(D.version?' (version '+esc(D.version)+')':'')+(D.sha?' · '+esc(D.sha):'')+'. Le plugin affiche et applique, la U1 décide.</p></div></div>';
  if(D.banner)h+='<div class="banner">'+esc(D.banner)+'</div>';
  if(D.loading&&!r)h+='<div class="loading"><div class="spin"></div>'+esc(D.loading)+'</div>';
  if(D.error)h+='<div class="err">'+esc(D.error)+'</div>';
  if(r){
    var plans=r.plans||{};
    if(S.sel===null)["slicer","optimize","layer"].forEach(function(k){if(S.sel===null&&plans[k]&&plans[k].feasible)S.sel=k});
    var rows=mapping(),colors={};(r.slicer_colors||[]).forEach(function(c){colors[c.t]=c});
    var al=[];
    if(r.missing_materials&&r.missing_materials.length)al.push("Matière absente des ACE : "+r.missing_materials.join(", "));
    rows.forEach(function(row){var w=nozWarn(row);if(w)al.push("⚠ Filament "+(row.t+1)+" : tranché pour une buse "+w.sliced+(w.shead!=null?" (T"+(w.shead+1)+")":"")+", imprimé sur T"+(w.head+1)+" ("+w.real+").");
      if(!row.slot)al.push("Filament "+(row.t+1)+" : aucune bobine dans les ACE.")});
    if(r.nozzles_mixed)al.push("Buses de diamètres différents dans ce fichier : vérifie la proposition.");
    if(al.length)h+='<div class="alerts">'+al.map(function(x){return '<div>'+esc(x)+'</div>'}).join("")+'</div>';
    var p=plans[planKey()]||{},st=startHeads(rows);
    h+='<div class="stats"><div class="stat"><b>'+(p.tool_changes!=null?p.tool_changes:"–")+'</b><span>changements d’outil</span></div>'+
       '<div class="stat"><b>'+(p.swaps!=null?p.swaps:"–")+'</b><span>échanges de bobine (ACE)'+(forcedOn()?' · avant tes choix':'')+'</span></div>'+
       '<div class="stat"><b>'+st.length+'</b><span>tête(s) chargée(s) au départ</span></div>'+
       '<div class="stat"><b>'+rows.length+'</b><span>couleur(s) du fichier</span></div>'+
       (p.estimate&&p.estimate.total_s?'<div class="stat"><b>'+dur(p.estimate.total_s)+'</b><span>durée estimée par la U1'+(p.estimate.added_s?' · dont '+dur(p.estimate.added_s)+' d’échanges':'')+(p.estimate.purge&&p.estimate.purge.g?' · purge '+Math.round(p.estimate.purge.g)+' g':'')+(forcedOn()?' · avant tes choix':'')+'</span></div>':'')+'</div>';
    h+='<div class="plans">';["slicer","optimize","layer"].forEach(function(k){var q=plans[k];if(!q)return;var on=planKey()===k,dis=!q.feasible||(forcedOn()&&k!=="slicer");
      h+='<label class="'+(on?'on':'')+(dis?' off':'')+'"><input type="radio" name="p" value="'+k+'"'+(on?' checked':'')+(dis?' disabled':'')+'><b>'+esc((D.labels||{})[k]||k)+'</b> <small>'+(q.feasible?q.swaps+' échange(s)'+(q.estimate&&q.estimate.total_s?' · '+estTxt(q.estimate):'')+(q.suggested?' · en déplaçant des bobines':''):esc(reasonFr(q.reason)))+'</small></label>'});
    h+='</div>';
    h+='<table><tr><th>Slicer</th><th></th><th>Bobine</th><th>Correspondance</th>'+(D.can_force?'<th>Forcer une bobine</th>':'')+'</tr>';
    rows.forEach(function(row){var c=colors[row.t]||{},sl=(I().sliced||[])[row.t]||{},g=(I().grams||[])[row.t],s=row.slot,w=nozWarn(row);
      h+='<tr><td>'+sw(c.hex)+'<b>Filament '+(row.t+1)+'</b> · '+esc(cn(c))+' <small>'+esc(c.material||"")+(g>0?' '+(g<10?g.toFixed(1):Math.round(g))+' g':'')+'</small>'+
        (sl.head!=null?'<br><small>tranché pour T'+(sl.head+1)+(sl.nozzle?' · '+esc(sl.nozzle):'')+'</small>':'')+'</td><td class="arrow">→</td>';
      var pl0=placement(),st0=pl0&&s&&pl0.tg[s.ace+"_"+s.slot],gs=st0?(st0.s?grams(st0.s):''):(s?grams(s):'');
      h+='<td>'+(s?sw(s.color)+esc(s.name||cname(s.color))+' <small>ACE '+(s.ace+1)+' · slot '+(s.slot+1)+' → T'+(s.slot+1)+(realOf(s.slot)?' · '+esc(realOf(s.slot)):'')+esc(gs)+'</small>':'<small>aucune</small>')+'</td>';
      var pl=placement(),st2=pl&&pl.tg[(s?s.ace+"_"+s.slot:"")];
      h+='<td>'+(row.tier==="manual"?'<span class="tag man">choix manuel</span>':tierTag(row.tier))+(st2?(!st2.s?'<span class="tag warn">absente</span>':(st2.s.ace!==s.ace||st2.s.slot!==s.slot)?'<span class="tag mv">à mettre ici</span>':'<span class="tag">en place</span>'):'')+(row.loose&&row.tier!=="manual"?'<span class="tag warn">matière différente</span>':'')+
        (s&&c.material&&s.material&&String(s.material).toUpperCase()!==String(c.material).toUpperCase()&&row.tier==="manual"?'<span class="tag warn">matière ≠</span>':'')+
        (w?'<span class="tag noz">buse '+esc(w.real)+' ≠ '+esc(w.sliced)+'</span>':'')+'</td>';
      if(D.can_force){var cur=S.forced[row.t]!=null?slotBy(S.forced[row.t]):null,au=autoSlot(row.t);
        h+='<td><div class="pick"><button type="button" class="pk'+(cur?' changed':'')+'" data-pk="'+row.t+'">'+
          (cur?spoolTxt(cur,sl,false):au?spoolTxt(au,sl,true):'<span class="lbl"><b>Automatique</b> <small>(aucune bobine)</small></span>')+'<span class="car">▾</span></button>';
        if(S.open===row.t){h+='<div class="menu"><div data-ch="'+row.t+'" data-v=""'+(cur?'':' class="sel"')+'>'+(au?spoolTxt(au,sl,true):'<span class="lbl"><b>Automatique</b> (choix de la U1)</span>')+'</div><div class="sep"></div>';
          live().forEach(function(x){var n=synth(x);h+='<div data-ch="'+row.t+'" data-v="'+n+'"'+(S.forced[row.t]===n?' class="sel"':'')+'>'+spoolTxt(x,sl,false)+'</div>'});
          h+='</div>'}
        h+='</div></td>'}
      h+='</tr>'});
    h+='</table>';
    var hid=hiddenCount();if(hid)h+='<p class="hint">'+hid+' filament(s) du projet non utilisé(s) dans ce fichier : masqué(s).</p>';
    if(D.can_force)h+='<p class="hint">Choisis une bobine dans la dernière colonne pour imposer ta couleur : le plan passe sur « Comme tranché » et la U1 applique tes choix tels quels (comme dans son Preflight). Le type de buse de chaque tête est rappelé.'+(forcedOn()?' <button class="ghost mini" id="unforce">Revenir au choix de la U1</button>':'')+'</p>';
    else h+='<p class="hint">Cette version de multiACE ne permet pas d’imposer une bobine depuis Orca : utilise « Ouvrir dans le Preflight multiACE ».</p>';
    var LAY=placement();if(LAY)h+=layoutCard(LAY,colors);
    // Au lancement
    var P=D.prefs||{},startIds=st.map(function(x){return headOf(x)});
    if(S.flow===null)S.flow=startIds.slice();
    h+='<div class="card"><b>Au lancement</b>'+(r._prefs_ok===false?' <small>(méthode de multiACE 1.27b)</small>':'');
    h+='<label class="opt"><input type="checkbox" id="bed"'+(P.bed?' checked':'')+'> Calibration du plateau</label>';
    h+='<div class="optsub"><label class="opt"><input type="checkbox" id="zone"'+(P.zone?' checked':'')+(P.bed?'':' disabled')+'> seulement la zone imprimée <small>(le profil palpe tout le plateau : ajoute MESH_MIN / MESH_MAX, rien ne change si ton profil le fait déjà)</small></label></div>';
    h+='<label class="opt"><input type="checkbox" id="flow"'+(P.flow?' checked':'')+'> Calibration du flux (PA) au départ</label>';
    h+='<div class="optsub"><div class="muted">Mesurées au départ (têtes chargées) :</div>';
    st.forEach(function(x){var hd=headOf(x),c=colors[x.t]||{};h+='<label class="opt"><input type="checkbox" class="fh" data-h="'+hd+'"'+(S.flow.indexOf(hd)>=0?' checked':'')+(P.flow?'':' disabled')+'> T'+(hd+1)+' · '+sw(x.slot.color)+esc(cn(c))+' <small>filament '+(x.t+1)+'</small></label>'});
    rows.forEach(function(x){if(!x.slot||st.indexOf(x)>=0)return;var pa=paOf(x),c=colors[x.t]||{},hd=headOf(x);
      h+='<div class="opt">'+sw(x.slot.color)+esc(cn(c))+' <small>filament '+(x.t+1)+' · arrive en cours d’impression (T'+(hd+1)+')</small> — '+
        (pa.pa!=null?'<span class="okc">PA mémorisé '+pa.pa.toFixed(4)+'</span>':'<span class="warnc">pas de PA mémorisé'+(pa.spool?'':' (aucune bobine associée au slot)')+'</span>')+
        (pa.spool?'<button class="ghost mini" data-pre="'+hd+'_'+x.slot.ace+'_'+x.slot.slot+'">Calibrer avant</button>':'')+'</div>'});
    h+='</div><label class="opt"><input type="checkbox" id="soft"'+(P.soft?' checked':'')+'> Déplacement doux vers la ligne d’amorce <small>(après les calibrations : 100 mm/s, accélération réduite, buse remontée de 5 mm avant)</small></label>';
    h+='<label class="opt"><input type="checkbox" id="cam"'+(P.cam?' checked':'')+'> Time-lapse caméra</label>';
    h+='<div class="muted" style="margin-top:8px;font-size:12px">Chargement automatique : les têtes vides ou avec une autre bobine au départ sont chargées depuis les ACE avant la première couche ('+st.length+' tête(s)), par le code multiACE de la U1. Vérifié avant l’envoi.</div></div>';
  }
  if(S.msg)h+='<div id="msg" class="msg '+(S.msg.ok?'ok':'bad')+'">'+esc(S.msg.text)+'</div>';
  h+='<div class="row">';
  var LR=r?placement():null,blk=S.busy||!planKey()||(LR&&!LR.ready);
  if(r)h+='<button id="go"'+(blk?' disabled':'')+'>Lancer l’impression</button><button class="ghost" id="up"'+(blk?' disabled':'')+'>Envoyer sur la U1 sans lancer</button>'+(D.can_queue?'<button class="ghost" id="qu"'+(blk?' disabled':'')+' title="File d’impression de multiACE (Print Hub) : tu lances depuis multiACE quand tu veux">Mettre dans la file multiACE</button>':'');
  h+='<button class="ghost" id="pf"'+(S.busy?' disabled':'')+'>Ouvrir dans le Preflight multiACE</button>'+(r?'<button class="ghost" id="rl"'+(S.busy?' disabled':'')+'>Recharger</button>':'')+'<button class="ghost" id="x">Fermer</button></div>';
  a.innerHTML=h;bind();
}
function gv(i){var e=document.getElementById(i);return !!(e&&e.checked)}
function send(act){S.busy=true;S.msg=null;var fh=[];Array.prototype.forEach.call(document.querySelectorAll(".fh"),function(e){if(e.checked)fh.push(+e.dataset.h)});
  var f={};Object.keys(S.forced).forEach(function(k){f[k]=S.forced[k]});
  var m={a:act,plan:planKey(),bed:gv("bed"),zone:gv("zone"),flow:gv("flow"),cam:gv("cam"),soft:gv("soft"),flow_heads:fh,forced:f};
  D.prefs={bed:m.bed,zone:m.zone,flow:m.flow,cam:m.cam,soft:m.soft};render();post(m)}
function bind(){
  var q=function(s){return document.querySelectorAll(s)},on=function(i,f){var e=document.getElementById(i);if(e)e.onclick=f};
  Array.prototype.forEach.call(q('input[name=p]'),function(i){i.onchange=function(){S.sel=i.value;S.flow=null;render()}});
  Array.prototype.forEach.call(q('[data-pk]'),function(e){e.onclick=function(ev){ev.stopPropagation();var t=+e.dataset.pk;S.open=S.open===t?null:t;render()}});
  Array.prototype.forEach.call(q('[data-ch]'),function(e){e.onclick=function(ev){ev.stopPropagation();var t=+e.dataset.ch;if(e.dataset.v==="")delete S.forced[t];else S.forced[t]=+e.dataset.v;S.open=null;S.flow=null;render()}});
  Array.prototype.forEach.call(q('.fh'),function(e){e.onchange=function(){var h=+e.dataset.h,i=S.flow.indexOf(h);if(e.checked&&i<0)S.flow.push(h);if(!e.checked&&i>=0)S.flow.splice(i,1)}});
  ["bed","flow","zone","cam","soft"].forEach(function(k){var e=document.getElementById(k);if(e)e.onchange=function(){D.prefs=D.prefs||{};D.prefs[k]=e.checked;render()}});
  Array.prototype.forEach.call(q('[data-nw]'),function(b){b.onclick=function(){var t=b.dataset.to.split("_").map(Number);
    S.busy=true;S.msg=null;render();post({a:"newspool",step:+b.dataset.nw,t:+b.dataset.t,to_ace:t[0],to_slot:t[1]})}});
  Array.prototype.forEach.call(q('[data-mv]'),function(b){b.onclick=function(){var f=b.dataset.f.split("_").map(Number),t=b.dataset.to.split("_").map(Number);
    S.busy=true;S.msg=null;render();post({a:"moved",step:+b.dataset.mv,from_ace:f[0],from_slot:f[1],to_ace:t[0],to_slot:t[1]})}});
  Array.prototype.forEach.call(q('[data-pre]'),function(b){b.onclick=function(){var v=b.dataset.pre.split("_").map(Number);b.disabled=true;b.textContent="Ajoutée à la file";post({a:"precal",head:v[0],ace:v[1],slot:v[2]})}});
  on("unforce",function(){S.forced={};S.flow=null;render()});
  on("go",function(){send("print")});on("up",function(){send("upload")});on("qu",function(){send("queue")});
  on("pf",function(){S.busy=true;S.msg=null;render();post({a:"preflight"})});
  on("rl",function(){S.busy=true;S.msg=null;render();post({a:"reload"})});
  on("rl2",function(){S.busy=true;S.msg=null;render();post({a:"reload"})});
  on("x",function(){post({a:"close"})});
}
window.__orca_on_message=function(m){if(m.type==="data"){var keep=D.report&&m.data.report&&D.name===m.data.name;D=m.data;if(!keep){S.sel=null;S.forced={}}S.flow=null;S.busy=false;S.msg=null;S.done={}}
  else if(m.type==="done"){S.busy=!!m.final;S.msg=m;
    if(m.ok&&m.step!=null){S.done[m.step]=true;var LD=placement();
      if(LD&&LD.order.every(function(x,i){return x.park||S.done[i]})){S.busy=true;render();post({a:"reload"});return}}}
  render()};
try{window.orca.onMessage(window.__orca_on_message)}catch(e){}
document.addEventListener("click",function(){if(S.open!==null){S.open=null;render()}});
document.addEventListener("keydown",function(e){if(e.key==="Escape"&&S.open!==null){S.open=null;render()}});
render();
})();
</script></body></html>"""


class U1PreflightWindow:
    """Proposition calculee par le code de la U1 ; verifie tout avant d'envoyer."""

    def __init__(self):
        self.window = None
        self.job = None
        self.live_sig = None
        self.prefs = {"bed": True, "zone": True, "flow": False, "cam": False, "soft": True}
        self.report = None
        self.info = None
        self.load = None
        self._lock = threading.Lock()

    def start(self, path, name, host, delay=1.0):
        with self._lock:
            self.job = {"path": path, "name": name, "host": host, "id": time.time()}
            job = self.job

        def worker():
            time.sleep(delay)
            if self.job is not job or _STOP.is_set():
                return
            self._send({"name": name, "loading": "Préparation avec le code multiACE de la U1…"})
            client = MultiAce(host)
            version = ""
            try:
                v = client.get_json("/version", timeout=TIMEOUT_BG)   # {"web": "1.90", ...} (1.27b et 1.90)
                version = str((v or {}).get("web") or "") if isinstance(v, dict) else ""
            except Exception:
                pass
            deadline = time.monotonic() + U1ACCESS_WAIT
            while True:
                try:
                    report, live, sha = u1_report(client, path, name)
                    break
                except (U1AccessError, PermissionError) as e:
                    if isinstance(e, PermissionError) and not getattr(e, "filename", None):
                        self._send({"name": name, "error": permission_text(host)})     # reseau refuse
                        return
                    if self.job is not job or _STOP.is_set():
                        return
                    if time.monotonic() > deadline:
                        self._send({"name": name, "error": "OrcaSlicer n'a pas autorisé le plugin à ouvrir ses fichiers. "
                                    "Réexporte et réponds « Oui » à la demande d'autorisation (événement « open »)."})
                        return
                    self._send({"name": name, "loading": "OrcaSlicer te demande une autorisation pour le plugin "
                                "(événement « open ») : réponds « Oui », la préparation continue toute seule."})
                    time.sleep(2)
                except U1CodeError as e:
                    self._fallback(job, "Vérification : %s. Le fichier d'origine part dans le Preflight de multiACE." % e)
                    return
                except Exception as e:
                    self._send({"name": name, "error": "Analyse impossible : %s" % e})
                    return
            if self.job is not job:
                return
            info = {"sliced": [], "grams": [], "order": [], "thumb": None}
            for _ in range(3):
                try:
                    info = slice_info(path)
                    break
                except PermissionError:
                    time.sleep(2)       # autorisation d'Orca en attente : on reessaie
                except OSError:
                    break
            load = load_info(client)
            can_queue = False
            try:
                q = client.get_json("/queue", timeout=TIMEOUT_BG)     # file Print Hub (multiACE 1.90+)
                can_queue = isinstance(q, dict) and isinstance(q.get("queue"), list)
            except Exception:
                pass
            hnt = ((live or {}).get("head_ctx") or {}).get("head_nozzle_types") or {}
            if isinstance(hnt, dict) and hnt:
                real = list(load.get("real") or ["", "", "", ""])
                for k, v in hnt.items():
                    try:
                        h = int(k)
                    except (TypeError, ValueError):
                        continue
                    lab = NOZZLE_FR.get(str(v).strip().lower().replace("-", "_"), "")
                    if 0 <= h <= 3 and lab in NOZZLE_CHOICES:
                        real[h] = lab
                load["real"], load["real_src"] = real, "multiACE"
            self.live_sig = _signature(live)
            self.report = report
            self.info = info
            self.load = load
            caps = _u1code.get("caps") or {}
            self._send({"name": name, "version": version, "sha": sha, "report": report, "labels": PLAN_LABELS,
                        "prefs": self.prefs, "info": info, "load": load, "can_force": bool(caps.get("remap")),
                        "can_queue": can_queue})

        threading.Thread(target=worker, daemon=True).start()

    def _fallback(self, job, text):
        try:
            MultiAce(job["host"]).send_gcode(job["path"], job["name"])
            _POPUP.request(job["name"], origin_of(job["host"]) + "/multiace/")
            _POPUP.show_pending()
            self._send({"name": job["name"], "banner": text})
        except Exception as e:
            self._send({"name": job["name"], "error": "%s Envoi impossible : %s" % (text, e)})

    def _send(self, data):
        data.setdefault("labels", PLAN_LABELS)
        data.setdefault("prefs", self.prefs)
        w = self.window
        if w is not None:
            try:
                if w.is_open():
                    w.post({"type": "data", "data": data})
                    return
            except Exception:
                pass
        payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
        self.window = orca.host.ui.create_window(html=i18n_page(U1_PAGE.replace("__DATA__", payload)),
                                                 title=tr("multiACE - Preflight de la U1"), width=1100, height=860,
                                                 on_message=self.on_message, on_close=self._closed)

    def _closed(self):
        self.window = None

    def _reply(self, ok, text, final=False, step=None):
        w = self.window
        if w is not None:
            try:
                w.post({"type": "done", "ok": ok, "text": text, "final": final, "step": step})
            except Exception:
                pass

    def on_message(self, m):
        if not isinstance(m, dict) or not self.job:
            return
        a = m.get("a")
        if a == "close":
            w = self.window
            if w is not None:
                try:
                    w.close()
                except Exception:
                    pass
            return
        if a == "preflight":
            threading.Thread(target=self._to_preflight, daemon=True).start()
        elif a in ("print", "upload", "queue") and m.get("plan") in PLAN_LABELS:
            self.prefs = {k: m.get(k) is True for k in ("bed", "zone", "flow", "cam", "soft")}
            prefs = dict(self.prefs)
            fh = m.get("flow_heads")
            if isinstance(fh, list):
                prefs["flow_heads"] = [h for h in fh if isinstance(h, int) and not isinstance(h, bool) and 0 <= h <= 3]
            forced = m.get("forced") if isinstance(m.get("forced"), dict) else {}
            threading.Thread(target=self._print, args=(m["plan"], prefs, forced, a),
                             daemon=True).start()
        elif a == "precal":
            try:
                h, ace, sl = int(m.get("head")), int(m.get("ace")), int(m.get("slot"))
            except (TypeError, ValueError):
                return
            if 0 <= h <= 3 and 0 <= ace <= 7 and 0 <= sl <= 3:
                # Meme file d'attente que le bouton du panneau : bobine sur sa tete, puis mesure memorisee.
                _PANEL._run("ACE_LOAD_HEAD", {"HEAD": h, "ACE": ace, "SLOT": sl})
                _PANEL._run("ACE_PA_CALIBRATE", {"HEAD": h, "FORCE": 1})
                self._reply(True, "Calibration de ACE %d · slot %d sur T%d ajoutée à la file du panneau multiACE. "
                                  "Attends qu'elle soit finie, puis « Recharger » : le PA est mémorisé sur la "
                                  "bobine." % (ace + 1, sl + 1, h + 1))
        elif a == "reload":
            self.start(self.job["path"], self.job["name"], self.job["host"], delay=0)
        elif a == "moved":
            threading.Thread(target=self._moved, args=(m,), daemon=True).start()
        elif a == "newspool":
            threading.Thread(target=self._newspool, args=(m,), daemon=True).start()

    def _newspool(self, m):
        """« Disposition finale » : une couleur du plan n'est sur aucune bobine chargee ; l'utilisateur en a
        pose une. Le slot recoit la couleur et la matiere du filament (etiquette, comme le selecteur de
        multiACE). Une bobine RFID se relit seule."""
        try:
            step, t, ta, ts = (int(m.get(k)) for k in ("step", "t", "to_ace", "to_slot"))
        except (TypeError, ValueError):
            return
        if not (0 <= ta <= 7 and 0 <= ts <= 3 and 0 <= t < 64):
            return
        sc = next((x for x in (self.report or {}).get("slicer_colors") or [] if x.get("t") == t), None)
        color = (str((sc or {}).get("hex") or ""))[:7].lower()
        if not re.fullmatch(r"#[0-9a-f]{6}", color):
            self._reply(False, "Couleur du filament %d illisible : « Recharger »." % (t + 1))
            return
        client = MultiAce(self.job["host"])
        try:
            state = client.state(timeout=TIMEOUT_UI)
            if str(state.get("printer_state") or "").lower() in ("printing", "paused"):
                raise MultiAceError("la U1 imprime")
            dst = {(x["ace"], x["slot"]): x for x in all_slots_from_state(state)}.get((ta, ts))
            if dst is None:
                raise MultiAceError("ACE %d · slot %d est vide : pose d'abord la bobine" % (ta + 1, ts + 1))
            if dst.get("source") != "rfid":
                client.set_override(ta, ts, gcode_safe((sc or {}).get("material"), 16).upper() or "PLA", "", "", color)
                client.macro("MULTIACE_REFRESH_OVERRIDES", {}, timeout=60)
            self._reply(True, "Bobine notée dans ACE %d · slot %d." % (ta + 1, ts + 1), step=step)
        except PermissionError:
            self._reply(False, permission_text(self.job["host"]))
        except Exception as e:
            self._reply(False, "Échec : %s" % e)

    def _moved(self, m):
        """« Disposition finale » : l'utilisateur a deplace une bobine a la main. Son identite (couleur,
        matiere, bobine de la table multiACE) suit dans le nouveau slot, par le meme chemin que le
        selecteur de slot de multiACE (slot-override + ACE_SPOOL_ASSIGN). Une bobine RFID se relit seule."""
        try:
            step = int(m.get("step"))
            fa, fs, ta, ts = (int(m.get(k)) for k in ("from_ace", "from_slot", "to_ace", "to_slot"))
        except (TypeError, ValueError):
            return
        if not all(0 <= v <= 7 for v in (fa, ta)) or not all(0 <= v <= 3 for v in (fs, ts)) or (fa, fs) == (ta, ts):
            return
        idt = ((self.load or {}).get("ident") or {}).get("%d_%d" % (fa, fs))
        if not idt:
            self._reply(False, "Bobine de ACE %d · slot %d inconnue : « Recharger »." % (fa + 1, fs + 1), step=None)
            return
        client = MultiAce(self.job["host"])
        try:
            state = client.state(timeout=TIMEOUT_UI)
            ps = str(state.get("printer_state") or "").lower()
            if ps in ("printing", "paused"):
                raise MultiAceError("la U1 imprime")
            now = {(x["ace"], x["slot"]): x for x in all_slots_from_state(state)}
            dst = now.get((ta, ts))
            if dst is None:
                raise MultiAceError("ACE %d · slot %d est vide : pose d'abord la bobine" % (ta + 1, ts + 1))
            if idt.get("source") != "rfid" and dst.get("source") != "rfid":
                color = idt.get("color") or ""
                if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                    raise MultiAceError("couleur de la bobine illisible")
                client.set_override(ta, ts, gcode_safe(idt.get("material"), 16).upper() or "PLA",
                                    gcode_safe(idt.get("brand")), gcode_safe(idt.get("subtype")), color.lower())
            if idt.get("source") == "override":
                client.clear_override(fa, fs)       # l'etiquette restait sur l'ancien slot
            sid = idt.get("spool")
            if sid and sid.isdigit():
                bind = state.get("spool_binding") or {}
                if str(bind.get("%d_%d" % (fa, fs))) == sid:
                    client.macro("ACE_SPOOL_ASSIGN", {"ACE": fa, "SLOT": fs}, timeout=60)
                client.macro("ACE_SPOOL_ASSIGN", {"ACE": ta, "SLOT": ts, "ID": sid}, timeout=60)
            client.macro("MULTIACE_REFRESH_OVERRIDES", {}, timeout=60)
            self._reply(True, "Bobine notée dans ACE %d · slot %d." % (ta + 1, ts + 1), step=step)
        except PermissionError:
            self._reply(False, permission_text(self.job["host"]))
        except Exception as e:
            self._reply(False, "Échec : %s" % e)

    def _to_preflight(self):
        job = self.job
        try:
            MultiAce(job["host"]).send_gcode(job["path"], job["name"])
            _POPUP.request(job["name"], origin_of(job["host"]) + "/multiace/")
            _POPUP.show_pending()
            self._reply(True, "Fichier d'origine envoyé au Preflight multiACE.")
        except PermissionError:
            self._reply(False, permission_text(job["host"]))
        except Exception as e:
            self._reply(False, "Échec : %s" % e)

    def _print(self, plan_name, prefs, forced=None, how="print"):
        job = self.job
        client = MultiAce(job["host"])
        upload_only = how in ("upload", "queue", True)
        try:
            if not upload_only:
                state = client.state(timeout=TIMEOUT_UI)
                ps = str(state.get("printer_state") or "").lower()
                if ps in ("printing", "paused") or state.get("swap_in_progress"):
                    raise MultiAceError("la U1 est occupée (%s)" % (ps or "échange en cours"))
            todo = placement_todo(self.report, plan_name, used_filaments(self.info))
            if todo:
                raise MultiAceError("place d'abord les bobines comme dans la « Disposition finale » (filament %s), "
                                    "puis « Recharger »" % ", ".join(str(t + 1) for t in todo))
            final = u1_prepare(client, job["path"], job["name"], plan_name, prefs, self.live_sig,
                               report=self.report, forced=forced)
            heads = autoload_heads(final)
            load_txt = (" Chargement automatique au départ : %s (têtes vides ou avec une autre bobine chargées "
                        "avant la 1re couche)." % ", ".join("T%d" % (h + 1) for h in heads)) if heads else \
                       (" ⚠ Pas de chargement automatique dans le fichier : vérifie que les bonnes bobines sont "
                        "sur les têtes avant de lancer." if heads is None else "")
            base, ext = os.path.splitext(os.path.basename(job["name"]))
            target = base + "_multiACE" + (ext or ".gcode")
            what = "le plan « %s »%s" % (PLAN_LABELS[plan_name], " et tes bobines imposées" if forced else "")
            if how == "queue":
                self._enqueue(client, final, target, plan_name, forced, what, load_txt)
                return
            if upload_only:
                client.send_gcode(final, target, endpoint="moonraker")
                self._reply(True, "%s envoyé sur la U1 sans lancer (%s) : lance-le depuis l'écran ou Fluidd.%s"
                            % (target, what, load_txt))
                return
            client.send_gcode(final, target, endpoint="/upload-and-print")
            self._reply(True, "Impression lancée avec %s.%s" % (what, load_txt), final=True)
        except U1CodeError as e:
            self._reply(False, "Vérification : %s. Utilise « Ouvrir dans le Preflight multiACE »." % e)
        except PermissionError:
            self._reply(False, permission_text(job["host"]))
        except Exception as e:
            if "ont changé" in str(e):
                self.start(job["path"], job["name"], job["host"], delay=0)
            self._reply(False, "Envoi annulé : %s" % e)


    def _enqueue(self, client, final, target, plan_name, forced, what, load_txt):
        """File d'impression de multiACE (Print Hub, 1.90+) : meme chemin que son Preflight « mettre en
        file » — fichier prepare depose dans gcodes/multiace_queue/ sans lancer, puis enregistre par
        POST /api/queue avec les slots qu'il utilise. Au lancement depuis multiACE, la U1 reverifie que
        ce sont toujours les memes bobines."""
        upname = uuid.uuid4().hex[:12] + "_" + target
        res = client.send_gcode(final, upname, endpoint="moonraker", folder=QUEUE_DIR)
        item = ((res or {}).get("result") or {}).get("item") or {}
        rel = str(item.get("path") or "")
        if not rel.startswith(QUEUE_DIR + "/"):
            rel = QUEUE_DIR + "/" + re.sub(r"[\x00-\x1f\x7f\"\\/]", "_", upname)[-180:]
        used = None
        try:
            _pp, core, _sha = u1_code(client)
            if hasattr(core, "used_ace_slots_file"):
                used = [[int(a), int(b)] for a, b in core.used_ace_slots_file(final) or []]
        except Exception:
            used = None
        plan = ((self.report or {}).get("plans") or {}).get(plan_name) or {}
        body = {"filename": target, "path": rel, "mode": plan_name, "used_slots": used,
                "estimate": None if forced else plan.get("estimate"),
                "swaps": None if forced else plan.get("swaps")}
        try:
            client.post_json("/queue", body, timeout=TIMEOUT_UI)
        except Exception:
            client.delete_printer_file(rel)      # pas d'entree dans la file : ne pas laisser le fichier
            raise
        self._reply(True, "%s ajouté à la file multiACE (%s) : lance-le depuis multiACE → Print Hub ; la U1 "
                          "revérifie les bobines au lancement.%s" % (target, what, load_txt))


QUEUE_DIR = "multiace_queue"       # dossier de la file multiACE (main.py : _QUEUE_DIR)
_U1PF = U1PreflightWindow()


# --------------------------------------------------------------------------- pipeline

_recent_sends = {}


def _wait_access(fn, wait=None):
    """Execute fn ; tant qu'OrcaSlicer attend la reponse a sa demande d'autorisation (PermissionError de
    l'audit « open »), reessaie chaque seconde, au plus U1ACCESS_WAIT s. Les autres erreurs passent."""
    deadline = time.monotonic() + (U1ACCESS_WAIT if wait is None else wait)
    while True:
        try:
            return fn()
        except PermissionError:
            if time.monotonic() > deadline or _STOP.is_set():
                raise
            time.sleep(1)


class SendToPreflight(orca.slicing.SlicingPipelineCapabilityBase):
    """Process > Autres > Slicing Pipeline Plugin > "multiACE : envoyer au Preflight"."""

    def on_unload(self):
        plugin_shutdown()

    def get_name(self):
        return "multiACE : envoyer au Preflight"

    def get_default_config(self):
        # also_on_print : envoyer aussi quand on clique Imprimer / Envoyer a l'imprimante,
        #                 et bloquer alors l'envoi direct d'OrcaSlicer.
        # min_filaments : n'envoyer que si au moins N filaments sont utilises (1 = toujours).
        return {"also_on_print": False, "min_filaments": 1}

    def _config(self):
        cfg = self.get_default_config()
        try:
            stored = json.loads(self.get_config())
            if isinstance(stored, dict):
                cfg.update({k: stored[k] for k in cfg if k in stored})
        except (TypeError, ValueError):
            pass
        return cfg

    def execute(self, ctx):
        if ctx.step != orca.slicing.Step.psGCodePostProcess:
            return _ok()
        path = getattr(ctx, "gcode_path", "") or ""
        if not path or not os.path.exists(path):
            return _skip("multiACE : pas de fichier G-code")
        note_pipeline_ran()
        cfg = self._config()
        target = (getattr(ctx, "host", "") or "").strip()
        to_printer = target not in ("", "File")
        u1code = load_settings().get("u1_code", True)
        if to_printer and not u1code and not cfg.get("also_on_print"):
            return _skip("multiACE : envoi direct a l'imprimante, Preflight non utilise")

        name = os.path.basename((getattr(ctx, "output_name", "") or "").strip() or path)
        try:
            facts = _wait_access(lambda: gcode_facts(path))
        except OSError as e:
            return _fail(orca.PluginResult.RecoverableError, "multiACE : lecture du G-code impossible (%s)" % e)
        if facts["processed"]:
            return _skip("multiACE : G-code deja traite par multiACE (script de post-traitement actif ?), non envoye")
        if facts["u1control"]:
            return _fail(
                orca.PluginResult.RecoverableError,
                "multiACE : ce G-code a ete modifie par U1 Control (\"U1 print setup\"). Decoche-le pour ce profil "
                "afin que multiACE recoive l'export original.")
        used = facts["filaments_used"]
        try:
            minimum = int(cfg.get("min_filaments") or 1)
        except (TypeError, ValueError):
            minimum = 1
        if used is not None and used < minimum:
            return _skip("multiACE : %d filament(s) utilise(s), envoi reserve a %d et plus" % (used, minimum))

        size = os.path.getsize(path)
        key = (name, size)
        now = time.time()
        # L'etape peut tourner deux fois de suite pour un meme export : on ignore le doublon immediat.
        if now - _recent_sends.get(key, 0) < 90:
            return _skip("multiACE : deja traite")

        kept = False
        # Copie : Preflight de la U1, et « renvoyer le dernier G-code ». Au 1er export d'une copie du plugin
        # (nouvelle installation, version locale...), OrcaSlicer demande l'autorisation « open » et refuse
        # l'acces tant qu'on n'a pas repondu : on attend la reponse au lieu de partir dans le Preflight de
        # multiACE (c'etait la cause de « le premier export ouvre multiACE »).
        try:
            _wait_access(lambda: keep_last_gcode(path, name))
            kept = True
        except OSError:
            pass

        host = normalize_host(load_settings()["host"])
        if not host:
            try:
                host = normalize_host(ctx.config_value("print_host"))
            except Exception:
                host = ""
        if not host:
            return _fail(orca.PluginResult.RecoverableError,
                                                "multiACE : adresse de la U1 inconnue : renseigne-la dans le panneau ACE (Options → Adresse de la U1)")
        if u1code and kept:
            _recent_sends[key] = now
            _U1PF.start(last_gcode_paths()[0], name, host)
            if to_printer:
                return _fail(
                    orca.PluginResult.FatalError,
                    "multiACE : impression préparée par le Preflight de la U1 (envoi direct d'OrcaSlicer annulé, c'est normal).")
            return _ok("multiACE : préparation avec le code multiACE de la U1 pour \"%s\"" % name)
        try:
            MultiAce(host).send_gcode(path, name)
        except PermissionError:
            return _fail(
                orca.PluginResult.RecoverableError,
                "multiACE : acces reseau non autorise depuis le tranchage. Ouvre l'onglet multiACE, clique "
                "Enregistrer pour autoriser %s, puis renvoie depuis l'onglet." % (origin_of(host) or "la U1"))
        except Exception as e:
            return _fail(
                orca.PluginResult.RecoverableError,
                "multiACE : envoi au Preflight impossible (%s). Le G-code est garde : renvoie-le depuis l'onglet multiACE." % e)
        _recent_sends[key] = now
        if not to_printer and load_settings().get("popup", True):
            _POPUP.request(name, origin_of(host) + "/multiace/")
            schedule_popup_fallback()

        message = "multiACE : \"%s\" envoye au Preflight de %s%s" % (
            name, host, (" (%d filaments)" % used) if used else "")
        if to_printer:
            # Envoye au Preflight : on arrete l'envoi direct pour que l'impression ne parte pas deux fois.
            return _fail(
                orca.PluginResult.FatalError,
                message + ". Envoi direct d'OrcaSlicer annule : lance l'impression depuis le Preflight multiACE.")
        return _ok(message)


# --------------------------------------------------------------------------- panneau ACE

PANEL = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<style>
:root{--fg:var(--orca-fg,#e9ecef);--muted:var(--orca-muted,#9aa3ad);--line:var(--orca-border,rgba(255,255,255,.12));
  --accent:#009688;--bad:#e05a4f;--warn:#e0a030;color-scheme:dark;font:12.5px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif}
*{box-sizing:border-box}
body{margin:0;padding:10px 10px 30px;color:var(--fg)}
.top{display:flex;align-items:center;gap:6px;margin-bottom:8px}
.top b{font-size:13.5px;flex:1}
.pill{font-size:11px;border-radius:999px;padding:2px 8px;background:rgba(255,255,255,.08);color:var(--muted)}
.pill.ok{background:rgba(63,178,127,.18);color:#3fb27f}.pill.bad{background:rgba(224,90,79,.18);color:var(--bad)}
.pill.warn{background:rgba(224,160,48,.18);color:var(--warn)}
h4{margin:12px 0 6px;font-size:11px;letter-spacing:.7px;text-transform:uppercase;color:var(--muted);display:flex;align-items:center;gap:6px}
h4 span{flex:1}
.item{display:flex;align-items:center;gap:8px;padding:5px 2px;border-top:1px solid var(--line)}
.sw{width:18px;height:18px;border-radius:50%;flex:none;border:1px solid rgba(255,255,255,.25)}
.sw.empty{background:repeating-linear-gradient(45deg,transparent 0 3px,rgba(255,255,255,.12) 3px 5px)}
.t{flex:1;min-width:0}.t small{display:block;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
button{background:transparent;color:var(--fg);border:1px solid var(--line);border-radius:5px;padding:3px 8px;font:inherit;font-size:11.5px;cursor:pointer;white-space:nowrap}
button.go{border-color:rgba(0,150,136,.6);color:#4fd1c0}
button.arm{background:var(--warn);border-color:var(--warn);color:#1b1e22}
button:disabled{opacity:.35;cursor:default}
.msg{margin:8px 0;padding:7px 9px;border-radius:6px;display:none;font-size:12px}
.hostbox{border-color:#8a6d1f}.hosthint{font-size:12px;opacity:.8;margin:4px 0 8px}.hostrow{display:flex;gap:6px}.hostrow input{flex:1;min-width:0;background:#11151a;color:inherit;border:1px solid #3a444e;border-radius:6px;padding:5px 7px}.hostline{font-size:12px;margin:2px 0 6px;display:flex;gap:6px;align-items:center;flex-wrap:wrap}
select option{background:#22262c;color:#e8eaed}
.sppick{position:relative}.spbtn{width:100%;text-align:left;display:flex;align-items:center;gap:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.splist{display:none;position:absolute;z-index:20;left:0;right:0;top:100%;margin-top:2px;max-height:260px;overflow:auto;background:#1c1f24;border:1px solid rgba(255,255,255,.15);border-radius:6px;box-shadow:0 6px 18px rgba(0,0,0,.5)}
.splist.show{display:block}.spo{display:flex;align-items:center;gap:8px;padding:6px 8px;cursor:pointer;font-size:12px;color:#e8eaed}
.spo:hover{background:rgba(255,255,255,.08)}.spo.on{background:rgba(0,150,136,.18)}.spo.new{color:#4fd1c0}
.spl{display:flex;flex-direction:column;line-height:1.25}.spl small{color:#9aa4b2}
.calib{display:flex;align-items:center;gap:8px;font-size:12px;margin:2px 0 10px;padding:6px 8px;border:1px solid rgba(255,255,255,.08);border-radius:6px}.calib span{flex:1}
.ah{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--mut,#9aa4b2);margin:-2px 0 8px;cursor:pointer}
.queue{display:none;margin:0 0 8px;padding:7px 9px;border-radius:6px;background:rgba(255,255,255,.05);font-size:12px}
.queue.show{display:block}.queue,.item button,button{user-select:none;-webkit-user-select:none}
.t small.plan{color:#4fd1c0}.queue ol{margin:4px 0 6px 18px;padding:0}.queue li{margin:2px 0}
.queue li.run{color:#4fd1c0;font-weight:600}.queue li.fail{color:#f08a80}.queue .x{background:none;border:0;color:#9aa4b2;cursor:pointer;padding:0 4px}
.queue .qb{font-size:11px;padding:3px 8px;margin-right:6px}
.msg.show{display:block}.msg.info{background:rgba(0,150,136,.15)}.msg.err{background:rgba(224,90,79,.15)}
.badge{font-size:10.5px;border-radius:4px;padding:0 5px;background:rgba(255,255,255,.08);color:var(--muted)}
.badge.derived{color:var(--warn)}.badge.nocal{color:#f0b060;background:rgba(224,160,48,.14)}
.note{color:var(--muted);font-size:11.5px}
.prep{margin:4px 0 8px;padding:7px 8px;border-radius:8px;background:rgba(255,255,255,.04)}
.ph{margin:0 0 4px}.ng{display:grid;grid-template-columns:1fr 1fr;gap:4px;margin:4px 0 6px}
.nc{padding:4px 6px;border-radius:5px;background:rgba(255,255,255,.05);font-size:11.5px;color:var(--muted)}
.nc.chg{background:rgba(224,160,48,.28);color:#ffd27a;font-weight:700}
details.pf{margin-top:4px}details.pf summary{cursor:pointer;color:var(--muted);font-size:11px}
.rn{display:flex;flex-wrap:wrap;gap:4px 8px;margin:6px 0;font-size:11.5px;color:var(--muted);align-items:center}
.rn select{background:#1c1f24;color:var(--fg);border:1px solid var(--line);border-radius:5px;font:inherit;font-size:11px;padding:1px 2px}
.pr{display:flex;gap:6px;align-items:flex-start;padding:3px 0;font-size:11.5px}.pr .sw{width:14px;height:14px;margin-top:1px}
.pw{color:var(--warn);margin:4px 0}.pok{color:#3fb27f;margin:4px 0}.okc{color:#3fb27f}.warnc{color:var(--warn)}
.dry{display:flex;flex-wrap:wrap;align-items:center;gap:5px;padding:5px 2px 7px;font-size:11.5px;color:var(--muted)}
.dry b{color:var(--fg);font-weight:600}
.dry.on b{color:#f0a35a}
.dry select{background:rgba(255,255,255,.06);color:var(--fg);border:1px solid var(--line);border-radius:5px;padding:2px 4px;font:inherit;font-size:11.5px}
.qty{font-variant-numeric:tabular-nums}
.top button{padding:3px 7px}
.top button.on{border-color:rgba(0,150,136,.7);color:#4fd1c0}
.screen{margin:4px 0 8px;position:relative}
.cam img{display:block;width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:10px;border:1px solid var(--line);background:#000}
.cam{position:relative;margin:4px 0 8px}.cam .live{position:absolute;left:8px;top:7px;font-size:10px;font-weight:700;color:#fff;background:rgba(224,60,60,.85);border-radius:4px;padding:1px 5px}
.cam .err{font-size:11.5px;color:var(--muted);padding:10px;border:1px dashed var(--line);border-radius:8px;text-align:center}
.screen img{display:block;width:100%;border-radius:8px;border:1px solid var(--line);cursor:pointer;background:#000;image-rendering:auto}
.screen .err{font-size:11.5px;color:var(--muted);padding:10px;border:1px dashed var(--line);border-radius:8px;text-align:center}
#mini{display:flex;gap:6px;align-items:center;flex-wrap:wrap;padding:4px 0 6px}
#mini[hidden]{display:none}
#mini .h{display:flex;align-items:center;gap:4px;font-size:11.5px}
#mini .sw{width:14px;height:14px}
body.compact #foot,body.compact #mc,body.compact #mcH{display:none}
.item.click{cursor:pointer}.item.click:hover{background:rgba(255,255,255,.03)}
.ed{border:1px solid var(--line);border-radius:7px;padding:8px;margin:2px 0 8px;display:grid;grid-template-columns:auto 1fr;gap:6px 8px;align-items:center;font-size:11.5px}
.ed label{color:var(--muted)}
.ed input,.ed select{background:rgba(255,255,255,.06);color:var(--fg);border:1px solid var(--line);border-radius:5px;padding:3px 6px;font:inherit;font-size:11.5px;min-width:0}
.ed input[type=color]{padding:0;width:34px;height:24px;border-radius:4px}
.ed .full{grid-column:1/-1;display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.ed .sw2{display:flex;gap:4px;flex-wrap:wrap}.ed .sw2 i{width:16px;height:16px;border-radius:50%;cursor:pointer;border:1px solid rgba(255,255,255,.25)}
.bar{height:3px;border-radius:2px;background:rgba(255,255,255,.1);margin-top:3px;overflow:hidden}.bar i{display:block;height:100%;background:#4fd1c0}

/* ---- habillage v0.28 */
body{background:radial-gradient(130% 50% at 0% 0%,rgba(0,150,136,.10),transparent 60%),radial-gradient(120% 40% at 100% 100%,rgba(122,167,255,.06),transparent 60%)}
.top b{font-size:16px;letter-spacing:.4px;background:linear-gradient(90deg,#4fd1c0,#7aa7ff);-webkit-background-clip:text;background-clip:text;color:transparent}
button{border-radius:999px;padding:4px 11px;transition:background .15s,border-color .15s}
button:hover:not(:disabled){background:rgba(255,255,255,.07)}
button.go{background:rgba(0,150,136,.16);border-color:rgba(0,150,136,.5);color:#5fe0cf}
button.go:hover:not(:disabled){background:rgba(0,150,136,.28)}
.top button{border-radius:8px}
.card{background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.07);border-radius:12px;padding:8px 10px 10px;margin:0 0 10px;box-shadow:0 4px 14px rgba(0,0,0,.18)}
.card h4{margin:2px 0 8px}
.prep{border:1px solid rgba(255,255,255,.07);border-radius:12px;padding:8px 10px}
.heads{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px}
.htile{border-radius:10px;padding:8px;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.06);display:flex;flex-direction:column;gap:3px;min-width:0}
.htile.on{background:linear-gradient(155deg,var(--tint),rgba(255,255,255,.025) 75%)}
.hrow{display:flex;align-items:center;gap:8px;min-width:0}.hrow>div{min-width:0}
.hn{font-size:15px;font-weight:700;line-height:1.1}
.hm{font-size:11.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.htile small{display:block;color:var(--muted);font-size:10.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.htile small.plan{color:#4fd1c0}
.htile button{margin-top:4px;width:100%;font-size:11px;padding:3px 6px}
.spool{border-radius:50%;flex:none;background:radial-gradient(circle,#1b1e22 0 22%,rgba(255,255,255,.35) 23% 26%,var(--c) 28% 100%)}
.spool.empty{background:repeating-linear-gradient(45deg,transparent 0 3px,rgba(255,255,255,.12) 3px 5px);box-shadow:0 0 0 1px rgba(255,255,255,.15)}
.ace .item{border-top:1px solid rgba(255,255,255,.06);border-radius:8px;padding:6px 4px}
.ace .item.click:hover{background:rgba(255,255,255,.04)}
.ace .bar{height:4px;border-radius:3px;margin-top:4px;max-width:160px}
h4 span.hum{flex:none}.tmp{background:rgba(122,167,255,.14);color:#9cbcff}.hum{font-size:10.5px;border-radius:999px;padding:1px 8px;font-weight:600;text-transform:none;letter-spacing:0}
.hum.ok{background:rgba(63,178,127,.18);color:#5fd39a}.hum.mid{background:rgba(224,160,48,.18);color:#f0b45a}.hum.hi{background:rgba(224,90,79,.2);color:#f08a80}
.dry{border-radius:8px;padding:6px 8px;margin:0 0 4px;background:rgba(255,255,255,.03)}
.dry.on{background:linear-gradient(90deg,rgba(240,140,60,.16),rgba(240,140,60,.04))}
.dprog{flex-basis:100%;height:3px;border-radius:2px;background:rgba(255,255,255,.08);overflow:hidden}.dprog i{display:block;height:100%;background:linear-gradient(90deg,#f0a35a,#f06a4a)}
.calib{border-radius:10px;background:rgba(255,255,255,.03)}
.optscard .ah{margin:5px 0}.optscard h4 button{padding:2px 8px}
#foot{opacity:.75}
h4.fh{cursor:pointer;user-select:none}h4.fh:hover{color:var(--fg)}
.chev{display:inline-block;width:12px;font-style:normal;color:var(--muted);transition:transform .15s}
.folded .chev{transform:rotate(-90deg)}
.card.folded{padding-bottom:6px}.card.folded>:not(h4){display:none}.card.folded h4{margin-bottom:0}
.fmini{display:inline-flex;gap:4px;vertical-align:middle;margin-left:6px}
.fmini .spool{box-shadow:0 0 0 1px rgba(255,255,255,.15)!important}
.prep.folded .pbody{display:none}
[data-pk]{cursor:pointer}.mrow .sl[data-pk]:hover .spool,.fmini [data-pk]:hover{filter:brightness(1.25)}
.pop{position:fixed;z-index:60;min-width:170px;max-width:240px;background:#23272d;border:1px solid rgba(255,255,255,.16);border-radius:10px;padding:9px;box-shadow:0 10px 28px rgba(0,0,0,.55)}
.pop .pt{display:flex;align-items:center;gap:8px;font-weight:600;font-size:12px}.pop .pt small{display:block;font-weight:400;color:var(--muted);font-size:10.5px}
.pop button{display:block;width:100%;margin-top:7px}.pop .pn{color:var(--muted);font-size:10.5px;margin-top:6px}.prep .ptitle{cursor:pointer;user-select:none;font-weight:600}
.pmv{float:right;border:0;background:none;color:var(--muted);font-size:10.5px;padding:0 2px;margin-top:-1px}
.pmv:hover:not(:disabled){background:none;color:var(--fg)}
#mini{display:block;padding:2px 0 6px}
.mrow{display:flex;align-items:center;gap:6px;padding:6px 8px;margin:0 0 6px;border-radius:10px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.07)}
.mrow .lab{font-size:11px;font-weight:700;color:var(--muted);width:40px;flex:none}
.mrow .sl{display:flex;flex-direction:column;align-items:center;gap:1px;flex:1;min-width:0}
.mrow .sl small{font-size:9.5px;color:var(--muted);line-height:1}.mrow .sl small.on{color:#5fe0cf;font-weight:700}
.mrow .info{display:flex;flex-direction:column;align-items:flex-end;gap:2px;flex:none;font-size:10px;color:#f0a35a}
.mprep{font-size:11px;margin:0 0 6px;padding:4px 8px;border-radius:8px}
.mprep.ok{color:#5fd39a;background:rgba(63,178,127,.10)}.mprep.todo{color:#f0b45a;background:rgba(224,160,48,.12)}
</style></head><body>
<div class="top"><b>ACE</b><span id="st" class="pill">…</span>
  <button id="cam" title="Caméra de la U1 : masquée / en haut / en bas">📷</button>
  <button id="scr" title="Écran de la U1 : masqué / en haut / en bas">▣</button>
  <button id="cmp" title="Réduire / agrandir">–</button>
  <button id="hd" title="Masquer le panneau (une notification permet de le rouvrir)">⇥</button>
  <button id="opt" title="Options (adresse de la U1, homing, garde-fou, export)">⚙</button>
  <button id="rf" title="Actualiser">↻</button></div>
<div id="screenTop"></div><div id="camTop"></div>
<div id="msg" class="msg"></div>
<div id="optsCard" class="card optscard" hidden><h4><span>⚙ Options</span><button id="optX" class="ghost" title="Fermer les options">✕</button></h4>
<div class="hostline">Adresse de la U1 : <b id="hostCur">—</b> <button id="hostEdit" class="ghost">Modifier</button></div>
<label class="ah" title="Si la U1 n'a pas fait son homing, le plugin le fait tout seul avant de charger / échanger / décharger, sans te demander."><input type="checkbox" id="ah"> Homing automatique si nécessaire</label>
<label class="ah" title="Si un ACE se déconnecte puis revient : le plugin relance son séchage là où il en était, et pendant une impression il relance la poussée du filament, uniquement pour la tête qui imprime (si multiACE ne l'a pas déjà fait)."><input type="checkbox" id="gf"> Garde-fou : relancer après une déconnexion d'ACE</label><label class="ah" title="À l'export, le plugin exécute dans Orca le Preflight fourni par ta U1 (code multiACE de ta version), vérifie tout puis imprime. Décoché : le fichier d'origine part dans le Preflight de multiACE, sans rien exécuter."><input type="checkbox" id="uc"> Préparer l'export avec le code multiACE de la U1</label><label class="ah" title="Quand l'imprimante est une U1 et que le profil de traitement n'a pas l'étape « multiACE : envoyer au Preflight », le plugin l'ajoute. Le profil devient « modifié » : enregistre-le pour la garder."><input type="checkbox" id="ap"> Ajouter l'étape Preflight aux profils de la U1</label><div class="hostline" id="pipeSt">Étape Preflight : …</div><label class="ah">Langue / Language <select id="lang"><option value="auto">Auto (Windows)</option><option value="fr">Français</option><option value="en">English</option></select></label>

</div>
<div id="hostbox" class="card hostbox" hidden><b id="hostTitle">Adresse de la U1 introuvable</b>
<div class="hosthint">Entre l'adresse IP de ta U1 (affichée dans ses réglages réseau, par exemple 192.168.1.50).</div>
<div class="hostrow"><input id="hostIn" placeholder="192.168.1.50" spellcheck="false"><button id="hostOk">Enregistrer</button><button id="hostX" class="ghost">Annuler</button></div></div>
<div id="queue" class="queue"></div>
<div id="mini" hidden></div>
<div id="full">
<div id="prepTop"><div id="prep"></div></div>
<div class="card" id="headsCard">
<h4 class="fh" data-fold="heads"><span><i class="chev">▾</i>Têtes<span id="headsMini" class="fmini"></span></span><button id="ua">Tout décharger</button></h4>
<div id="heads" class="heads"></div>
<div class="calib"><span>Calibration du plateau</span><select id="bt" title="Température du plateau pendant la mesure">
<option value="55" selected>55 °C</option><option value="60">60 °C</option><option value="70">70 °C</option><option value="80">80 °C</option><option value="100">100 °C</option></select>
<button data-act="calbed" title="Chauffe le plateau, attend 2 min, mesure le maillage (AUTO_BED_MESH_CALIBRATE) ; la U1 l'enregistre">Lancer</button></div>
</div>
<div id="aces"></div>
<div id="prepBottom"></div>
</div>
<div id="camBottom"></div><div id="screenBottom"></div>
<p class="note" id="foot">Clique sur une bobine pour modifier sa couleur, sa matière ou son poids. Clique deux fois sur un bouton pour confirmer une action. Charger / échanger / décharger / sécher / calibrer s’enchaînent dans une file d’attente (« Arrêter » le séchage part tout de suite).<br><span style="opacity:.6">multiACE Bridge v__VERSION__</span></p>
<script>
(function(){
  var $=function(i){return document.getElementById(i)};
  var S={base:1,busy:false,locked:false,armed:null,dt:{},dd:{},edit:null,last:null};
  function esc(x){var d=document.createElement("span");d.textContent=x==null?"":String(x);return d.innerHTML}
  function post(m){window.orca&&window.orca.postMessage(m)}
  function n(i){return typeof i==="number"?i+S.base:"?"}
  function col(c){return typeof c==="string"&&/^#[0-9a-fA-F]{6}$/.test(c)?c:null}
  function sw(c){return '<div class="sw'+(c?"":" empty")+'" style="'+(c?"background:"+c:"")+'"></div>'}
  function rgba(c,a){var v=rgb(c);return "rgba("+v[0]+","+v[1]+","+v[2]+","+a+")"}
  function spool(c,px){return '<div class="spool'+(c?"":" empty")+'" style="width:'+px+'px;height:'+px+'px;'+(c?"--c:"+c+";box-shadow:0 0 0 2px rgba(255,255,255,.10),0 0 12px "+rgba(c,.45):"")+'"></div>'}
  function rgb(h){var m=/^#?([0-9a-fA-F]{6})/.exec(String(h||""));h=m?m[1]:"777777";return [parseInt(h.slice(0,2),16),parseInt(h.slice(2,4),16),parseInt(h.slice(4,6),16)]}
  function cname(h){
    var c=rgb(h),r=c[0]/255,g=c[1]/255,b=c[2]/255,mx=Math.max(r,g,b),mn=Math.min(r,g,b),l=(mx+mn)/2,d=mx-mn,s=0,hu=0;
    if(d>0){s=d/(1-Math.abs(2*l-1));hu=mx===r?((g-b)/d)%6:mx===g?(b-r)/d+2:(r-g)/d+4;hu=(hu*60+360)%360}
    if(l>0.9)return "Blanc";if(l<0.1)return "Noir";
    if(s<0.15)return l>0.7?"Gris clair":l<0.32?"Gris foncé":"Gris";
    if(hu<12||hu>=345)return l<0.3?"Bordeaux":l>0.75?"Rose":"Rouge";
    if(hu<42)return (l<0.45||s<0.45)?(l>0.6?"Beige":"Marron"):(l>0.75?"Pêche":"Orange");
    if(hu<66)return l<0.35?"Kaki":(s<0.5&&l>0.7?"Crème":"Jaune");
    if(hu<160)return l<0.28?"Vert foncé":l>0.7?"Vert clair":"Vert";
    if(hu<195)return l>0.7?"Cyan clair":"Turquoise";
    if(hu<250)return l<0.3?"Bleu foncé":l>0.7?"Bleu clair":"Bleu";
    if(hu<290)return l>0.7?"Lavande":"Violet";
    return (s>0.6&&l<0.55)?"Magenta":"Rose";
  }

  function say(t,k){var m=$("msg");if(!t){m.className="msg";return}m.textContent=t;m.className="msg show "+(k||"info")}
  function word(x){return {empty:"vide",ready:"prête",loading:"chargement",unloading:"déchargement",error:"erreur",feeding:"alimentation",assist:"assistance",nosensor:"sans capteur",unknown:"inconnu"}[x]||x||""}
  function dis(){return S.locked?" disabled":""}
  function renderQueue(q){var box=$("queue");S.q=q;
    if(!q||!q.items.length){box.className="queue";box.innerHTML="";return}
    box.className="queue show";
    box.innerHTML='<b>File d’attente</b>'+(q.paused?' <span class="badge" style="color:var(--bad)">en pause</span>':'')+
      '<ol>'+q.items.map(function(it){var cls=it.status==="en cours"?"run":it.status==="échec"?"fail":"";
        return '<li class="'+cls+'">'+esc(it.label)+' <small>('+esc(it.status)+')</small>'+(it.status!=="en cours"?'<button class="x" data-q="'+it.id+'" title="Retirer">✕</button>':'')+'</li>'}).join("")+'</ol>'+
      (q.paused?'<button class="qb go" data-qa="queue_resume">Reprendre</button>':'')+
      (q.items.some(function(it){return it.status!=="en cours"})?'<button class="qb ghost" data-qa="queue_clear">Vider la file</button>':'')}
  document.addEventListener("click",function(e){var t=e.target;
    if(t.dataset&&t.dataset.q){post({command:"queue_remove",id:+t.dataset.q});e.stopPropagation();return}
    if(t.dataset&&t.dataset.qa){post({command:t.dataset.qa});e.stopPropagation()}},true);

  function spoolOf(st,ace,slot){var b=st.spool_binding||{},id=b[ace+"_"+slot];return id!=null?(st.spools||{})[String(id)]||null:null}
  function qty(sp,c){
    if(!sp)return "";
    var w=Number(sp.weight_g);
    if(w>0)return '<span class="qty">≈ '+Math.round(w)+' g</span><div class="bar"><i style="width:'+Math.min(100,Math.round(w/10))+'%'+(c?";background:linear-gradient(90deg,"+rgba(c,.55)+","+c+")":"")+'"></i></div>';
    var u=Number(sp.used_mm);
    if(u>0)return '<span class="qty">'+(u/1000).toFixed(1).replace(".",",")+' m utilisés</span>';
    return "";
  }
  function dryer(a){
    var d=a.dryer||{},st=String(d.status||"stop").toLowerCase(),on=st!=="stop"&&st!=="free"&&st!=="";
    if(on){
      // remain_time est en secondes (l'interface multiACE affiche remain_time/60 min).
      var r=Math.round((Number(d.remain_time)||0)/60),h=Math.floor(r/60),m=r%60;
      var tot=Number(d.duration)||0,pc=tot>0?Math.max(0,Math.min(100,Math.round(100-100*r/tot))):null;
      return '<div class="dry on"><b>🔥 Séchage '+(d.target_temp?d.target_temp+' °C':'')+'</b>'+(r?' · reste '+(h?h+' h ':'')+m+' min':'')+
        '<span style="flex:1"></span><button data-act="stopdry" data-ace="'+a.idx+'">Arrêter</button>'+
        (pc!=null?'<div class="dprog" title="'+pc+' %"><i style="width:'+pc+'%"></i></div>':'')+'</div>';
    }
    var t=S.dt[a.idx]||45,du=S.dd[a.idx]||240;
    var temps=[40,45,50,55].map(function(v){return '<option'+(v===t?" selected":"")+'>'+v+'</option>'}).join("");
    var durs=[[60,"1 h"],[120,"2 h"],[240,"4 h"],[360,"6 h"],[480,"8 h"]].map(function(v){return '<option value="'+v[0]+'"'+(v[0]===du?" selected":"")+'>'+v[1]+'</option>'}).join("");
    return '<div class="dry">Séchage <select data-dt="'+a.idx+'">'+temps+'</select>°C <select data-dd="'+a.idx+'">'+durs+'</select>'+
      '<span style="flex:1"></span><button class="go" data-act="dry" data-ace="'+a.idx+'">Sécher</button></div>';
  }
  var MATS=["PLA","PETG","ABS","ASA","TPU","PA","PC","PLA-CF","PETG-CF","PA-CF"];
  var QUICK=["#ffffff","#000000","#808080","#e53935","#fb8c00","#fdd835","#43a047","#1e88e5","#8e24aa","#f48fb1","#8d6e63","#c0a080"];
  function editor(st,a,s){
    var sp=spoolOf(st,a.idx,s.idx),c=col(s.color)||"#ffffff",mat=(s.material||"PLA").toUpperCase();
    var opts=MATS.indexOf(mat)<0?[mat].concat(MATS):MATS;
    var w=sp&&Number(sp.weight_g)>0?Math.round(sp.weight_g):"";
    var cur=sp?String(sp.id):"";
    var all=Object.keys(st.spools||{}).map(function(k){return st.spools[k]}).sort(function(x,y){return Number(x.id)-Number(y.id)});
    // Liste maison (pas un <select>) : pastille de couleur, texte lisible sur fond sombre, et l'endroit
    // ou la bobine est deja montee.
    var where={};Object.keys(st.spool_binding||{}).forEach(function(k){var v=String(st.spool_binding[k]);var m=/^(\d+)_(\d+)$/.exec(k);if(m)where[v]="ACE "+n(+m[1])+" · slot "+n(+m[2])});
    var spLab=function(x){return "#"+x.id+" "+[x.label,x.vendor,x.material,x.subtype].filter(Boolean).join(" ")};
    var spRow=function(x){var id=String(x.id),w2=Number(x.weight_g)>0?Math.round(x.weight_g)+" g":"",here=id===cur;
      return '<div class="spo'+(here?" on":"")+'" data-v="'+esc(id)+'" data-w="'+(Number(x.weight_g)>0?Math.round(x.weight_g):"")+'">'+sw(col("#"+(x.color||""))||"#888")+
        '<span class="spl">'+esc(spLab(x))+'<small>'+esc(cname("#"+(x.color||"")))+(w2?" · "+w2:"")+(where[id]&&!here?" · sur "+where[id]:"")+'</small></span></div>'};
    var curSp=cur&&st.spools?st.spools[cur]:null;
    var spoolLine='<label>Bobine</label><div class="sppick" style="grid-column:auto"><input type="hidden" id="e_spid" value="'+esc(cur)+'">'+
        '<button type="button" class="spbtn" id="e_spbtn" title="Bobine de la table multiACE associée à ce slot (utile sans RFID : poids, calibration PA mémorisée)">'+
        (curSp?sw(col("#"+(curSp.color||"")))+esc(spLab(curSp)):"Aucune")+' ▾</button>'+
        '<div class="splist" id="e_splist"><div class="spo" data-v="">Aucune (détacher)</div>'+all.map(spRow).join("")+'<div class="spo new" data-v="new">+ Nouvelle bobine</div></div></div>'+
      '<label>Poids</label><div class="full" style="grid-column:auto"><input id="e_w" type="number" min="0" max="65535" step="1" value="'+w+'" style="width:80px"> g restants</div>'+
      (sp?'<div class="full"><label><input id="e_sp" type="checkbox" checked> appliquer couleur / matière à la bobine '+esc(sp.label||("#"+sp.id))+'</label></div>':'')+
      (sp&&sp.pa_matrix&&Object.keys(sp.pa_matrix).length?'<div class="full note">PA mémorisé : '+Object.keys(sp.pa_matrix).map(function(k){return esc(k.replace("_"," mm ").replace("high_flow","haut débit").replace("standard","standard"))+" = "+Number(sp.pa_matrix[k]).toFixed(4)}).join(" · ")+'</div>':
        '<div class="full note">'+(sp?'Pas encore de PA mémorisé pour cette bobine.':'Associe une bobine pour mémoriser le poids et la calibration PA.')+'</div>');
    var hh=headFor(st,a.idx,s.idx);
    var paBtn=hh==null?"":'<button data-act="calpa" data-head="'+hh+'" data-ace="'+a.idx+'" data-slot="'+s.idx+'"'+(sp?dis():" disabled")+' title="Charge cette bobine sur T'+n(hh)+' si besoin, puis mesure son PA (FLOW_CALIBRATE) et le mémorise sur la bobine pour cette buse">Calibrer cette bobine (PA)</button>';
    return '<div class="ed" data-ace="'+a.idx+'" data-slot="'+s.idx+'">'+
      '<label>Couleur</label><div class="full" style="grid-column:auto"><input id="e_c" type="color" value="'+c+'"><input id="e_hex" value="'+c+'" style="width:76px"></div>'+
      '<div class="full sw2">'+QUICK.map(function(q){return '<i data-q="'+q+'" style="background:'+q+'"></i>'}).join("")+'</div>'+
      '<label>Matière</label><select id="e_m">'+opts.map(function(o){return '<option'+(o===mat?" selected":"")+'>'+esc(o)+'</option>'}).join("")+'</select>'+
      '<label>Marque</label><input id="e_b" value="'+esc(s.brand||"")+'" placeholder="ex. SUNLU">'+
      '<label>Type</label><input id="e_s" value="'+esc(s.subtype||"")+'" placeholder="ex. Basic, Matte, Silk">'+
      spoolLine+
      '<div class="full"><button class="go" id="e_ok">Enregistrer</button><button id="e_no">Annuler</button>'+
      (s.source==="override"?'<button id="e_rf" title="Supprime la saisie manuelle">Revenir au RFID</button>':'')+'</div>'+
      (paBtn?'<div class="full">'+paBtn+'</div>':'')+'</div>';
  }
  function headFor(st,ace,slot){
    if(st.mode==="head"){var ha=st.head_ace||{};for(var h in ha){if(Number(ha[h])===ace)return Number(h)}return null}
    return slot;
  }
  // Etat des tetes APRES la file d'attente : les boutons se calculent dessus, pour preparer une
  // sequence complete d'avance et ne pas proposer deux fois la meme action.
  function planned(st){
    var hs=(st.toolheads||[]).map(function(t){return {idx:t.idx,filament_detected:!!t.filament_detected,ace:t.ace,slot:t.slot,manual:t.manual,feeder:t.feeder}});
    ((S.q&&S.q.items)||[]).forEach(function(it){var a=it.args||{},h=+a.HEAD;
      if(it.name==="ACE_LOAD_HEAD"||it.name==="ACE_SWAP_HEAD"){if(hs[h]){hs[h].filament_detected=true;hs[h].ace=+a.ACE;hs[h].slot=+a.SLOT}}
      else if(it.name==="ACE_UNLOAD_HEAD"){if(hs[h]){hs[h].filament_detected=false;hs[h].ace=null;hs[h].slot=null}}
      else if(it.name==="ACE_UNLOAD_ALL_HEADS"){hs.forEach(function(x){if(!x.manual&&!x.feeder){x.filament_detected=false;x.ace=null;x.slot=null}})}});
    return hs}
  function slotName(st,a,s){var A=(st.aces||[]).filter(function(x){return x.idx===a})[0];var sl=A&&(A.slots||[]).filter(function(x){return x.idx===s})[0];
    return sl?{c:col(sl.color),txt:"ACE "+n(a)+" · slot "+n(s)}:{c:null,txt:"ACE "+n(a)+" · slot "+n(s)}}
  function renderPrep(p){
    var el=$("prep");if(!el)return;
    S.prep=p;if(S.last)renderMini(S.last);
    if(!p){el.innerHTML="";return}
    var ae=document.activeElement;if(ae&&ae.closest&&ae.closest("#prep")&&ae.tagName==="SELECT")return;
    S.prepOpen=S.prepOpen||{};
    var real=p.real||["","","",""],man=p.manual||real;
    var sel='<div class="rn">'+man.map(function(v,h){return '<label>T'+(h+1)+' <select data-rn="'+h+'"><option value=""'+(v?"":" selected")+'>?</option>'+
      ["Standard","Haut débit"].map(function(o){return '<option'+(v===o?" selected":"")+'>'+o+'</option>'}).join("")+'</select></label>'}).join("")+'</div>';
    function fold(k,title,body,open){var o=S.prepOpen[k];if(o===undefined)o=!!open;
      return '<details class="pf" data-k="'+k+'"'+(o?" open":"")+'><summary>'+title+'</summary>'+body+'</details>'}
    var html;
    if(!p.real_known){
      html='<div class="note">Indique une seule fois la buse vissée sur chaque tête de ta U1 :</div>'+sel;
    }else{
      var todo={};p.todo.forEach(function(t){todo[t.t]=t.need});
      var cell=function(i){var r=p.rows[i]||{},v=todo[i]||(r.found&&r.need)||r.now||"?",chg=todo[i]!=null;
        return '<div class="nc'+(chg?" chg":"")+'">T'+(i+1)+' '+esc(chg?v.toUpperCase():v)+(chg?" ←":"")+'</div>'};
      var warn=(p.shared||[]).map(function(x){return '<div class="pw">⚠ Filaments '+x.filaments.map(function(t){return t+1}).join(" et ")+' sur la même tête T'+(x.head+1)+' : échanges de bobine pendant l’impression.</div>'}).join("")+
        p.rows.filter(function(r){return !r.found}).map(function(r){return '<div class="pw">⚠ Filament '+(r.t+1)+' ('+esc(cname(r.color))+') : aucune bobine de cette couleur dans les ACE.</div>'}).join("")+
        (p.extra?'<div class="note">'+p.extra+' filament(s) au-delà du 4e : non vérifié(s).</div>':'');
      var head=p.todo.length?'<div class="ph pw">⚠ Mets ça à gauche (Imprimante → Buse) puis tranche :</div><div class="ng">'+[0,1,2,3].map(cell).join("")+'</div>':
        '<div class="ph pok">✓ buses d’OrcaSlicer OK pour tes bobines</div>';
      var rows=p.rows.map(function(r){
          var where=r.found?'ACE '+n(r.ace)+' slot '+n(r.slot)+' → T'+(r.head+1)+' · '+esc(r.need||"?")+(r.ok?' <span class="okc">✓</span>':''):'<span class="warnc">pas dans les ACE</span>';
          return '<div class="pr">'+sw(col(r.color))+'<span><b>Filament '+(r.t+1)+'</b> '+esc(cname(r.color))+' → '+where+'</span></div>'}).join("")+
        '<div class="note">Pour OrcaSlicer, le filament N part sur TN ; en vrai, il part sur la tête du slot de sa bobine.</div>';
      var mine=p.real_src==="u1"?'<div class="note">Lues dans la U1 : '+real.map(function(v,h){return 'T'+(h+1)+' '+esc(v)}).join(" · ")+'. Rien à saisir.</div>':
        (p.real_src==="mixte"?'<div class="note">En partie lues dans la U1 ; le reste vient de ta saisie :</div>'+sel:
         '<div class="note">La U1 ne donne pas ses buses (firmware ancien) : ta saisie est utilisée.</div>'+sel);
      var vrows="",vbad=0;
      if(p.virtual&&p.virtual.length){
        vrows=p.virtual.map(function(r){var st;
          if(!r.present){st='<span class="warnc">⚠ ACE '+n(r.ace)+' absent</span>';vbad++}
          else if(r.empty){st='<span class="warnc">⚠ slot vide</span>';vbad++}
          else if(!r.match){st=sw(col(r.spool_color))+'<span class="warnc">⚠ bobine '+esc(cname(r.spool_color))+(r.material?' '+esc(r.material):'')+'</span>';vbad++}
          else st=sw(col(r.spool_color))+esc(cname(r.spool_color))+(r.material?' '+esc(r.material):'')+' <span class="okc">✓</span>';
          var hd=r.head!=null?' → T'+(r.head+1)+(r.need?' · '+esc(r.need):''):'';
          var nz=(r.now&&r.need&&r.now!==r.need)?' <span class="warnc">(Orca : '+esc(r.now)+')</span>':'';
          return '<div class="pr">'+sw(col(r.color))+'<span><b>Filament '+(r.t+1)+'</b> '+esc(cname(r.color))+' → ACE '+n(r.ace)+' slot '+n(r.slot)+(r.mapped?' <small>(table)</small>':'')+hd+nz+' : '+st+'</span></div>'}).join("")+
          '<div class="note">Table « Slicer filament → MMU / Slot » de multiACE (Config). Elle sert quand le fichier est imprimé tel quel ; avec le Preflight, la U1 réattribue par couleur.</div>';
        if(vbad)warn+='<div class="pw">⚠ '+vbad+' filament(s) au-delà du 4e : bobine différente dans leur slot multiACE (voir « Filaments 5 et plus »).</div>';
      }
      html=head+warn+fold("d","Détail par filament",rows,false)+(vrows?fold("v","Filaments 5 et plus (outils virtuels multiACE)",vrows,!!vbad):"")+fold("u","Ma U1 (buses vissées)"+(p.real_src==="u1"?" · lues dans la U1":""),mine,false);
    }
    var mv='<button class="pmv" data-pmv="1" title="Déplacer cette carte">'+(S.prepPos==="bottom"?"↑ en haut":"↓ en bas")+'</button>';
    var pf=isF("prep"),stat=!p.real_known?"":(p.todo.length?' <span class="warnc">· à régler</span>':' <span class="okc">· ✓</span>');
    el.innerHTML='<div class="prep'+(pf?" folded":"")+'">'+mv+'<div class="ptitle" data-fold="prep"><i class="chev">▾</i>Avant de trancher'+stat+'</div><div class="pbody">'+html+'</div></div>';
    el.querySelector("[data-pmv]").onclick=function(){S.prepPos=S.prepPos==="bottom"?"top":"bottom";placePrep();post({command:"prefs_set",prep_pos:S.prepPos});renderPrep(S.prep)};
    Array.prototype.forEach.call(el.querySelectorAll("details.pf"),function(d){d.addEventListener("toggle",function(){S.prepOpen[d.dataset.k]=d.open})});
    Array.prototype.forEach.call(el.querySelectorAll("select[data-rn]"),function(x){x.onchange=function(){
      var v=[0,1,2,3].map(function(h){var s=el.querySelector('select[data-rn="'+h+'"]');return s?s.value:""});
      post({command:"prefs_set",real_nozzles:v});x.blur();setTimeout(function(){post({command:"refresh"})},150)}});
  }
  function render(st){
    S.last=st;renderMini(st);applyFold();
    $("headsMini").innerHTML=isF("heads")?minis((st.toolheads||[]).map(function(t){return t.filament_detected?col(t.color):null}),(st.toolheads||[]).map(function(t){return "h:"+t.idx})):"";
    S.base=st.display_index_base===0?0:1;
    var ps=(st.printer_state||"").toLowerCase();
    // Pendant un echange multiACE on peut continuer a remplir la file : seule l'impression bloque.
    S.locked=ps==="printing"||ps==="paused";
    var label=(S.q&&S.q.items.some(function(i){return i.status==="en cours"}))?"action en cours":ps==="printing"?"impression":ps==="paused"?"en pause":st.swap_in_progress?"échange en cours":"prête";
    $("st").className="pill "+(label!=="prête"?"warn":"ok");$("st").textContent=label;
    var heads=st.toolheads||[],ph=planned(st),qn=(S.q&&S.q.items||[]).length;
    $("heads").innerHTML=heads.map(function(t){
      var loaded=!!t.filament_detected,c=loaded?col(t.color):null;
      var src=t.manual?"manuel":t.feeder?"chargeur U1":(t.ace!=null&&t.slot!=null)?("ACE "+n(t.ace)+" · slot "+n(t.slot)):(loaded?"source inconnue":"vide");
      var fail=t.load_failed?' <span class="badge" style="color:var(--bad)">échec</span>':"";
      var p=ph[t.idx]||t,pl=!!p.filament_detected;
      var can=pl&&!t.manual&&!t.feeder;
      var changed=qn&&(pl!==loaded||(pl&&(p.ace!==t.ace||p.slot!==t.slot)));
      var plan=changed?'<small class="plan">après la file : '+(pl?(p.ace!=null?esc(slotName(st,p.ace,p.slot).txt):"chargée"):"vide")+'</small>':"";
      return '<div class="htile'+(loaded?" on":"")+'"'+(c?' style="--tint:'+rgba(c,.22)+'"':"")+'><div class="hrow">'+spool(c,28)+
        '<div><div class="hn">T'+n(t.idx)+'</div><div class="hm">'+esc(loaded?(t.material||"chargée")+(t.subtype?" "+t.subtype:""):"vide")+fail+'</div></div></div>'+
        '<small>'+esc(src)+'</small>'+plan+
        (can?'<button data-act="unload" data-head="'+t.idx+'"'+dis()+'>Décharger</button>':"")+'</div>';
    }).join("")||'<div class="note">—</div>';
    Array.prototype.forEach.call(document.querySelectorAll('button[data-act=calbed]'),function(x){x.disabled=S.locked});
    $("ua").disabled=S.locked||!ph.some(function(t){return t.filament_detected&&!t.manual&&!t.feeder});
    $("aces").innerHTML=(st.aces||[]).map(function(a){
      var fk="ace"+a.idx,fo=isF(fk),dd=a.dryer||{},dso=String(dd.status||"stop").toLowerCase(),don=dso!=="stop"&&dso!=="free"&&dso!=="";
      var mini=fo?'<span class="fmini">'+minis((a.slots||[]).map(function(s){return s.state==="empty"||s.source==="empty"?null:col(s.color)}),(a.slots||[]).map(function(s){return "s:"+a.idx+":"+s.idx}))+'</span>'+(don?' <span style="color:#f0a35a;text-transform:none;letter-spacing:0">🔥</span>':""):"";
      var head='<h4 class="fh" data-fold="'+fk+'"><span><i class="chev">▾</i>'+(a.unit_name?esc(a.unit_name):"ACE "+n(a.idx))+mini+(a.connected?"":' <span class="badge" style="color:var(--bad)">déconnecté</span>')+'</span>'+climate(a)+'</h4>';
      return '<div class="card ace'+(fo?" folded":"")+'">'+head+dryer(a)+(a.slots||[]).map(function(s){
        var empty=s.state==="empty"||s.source==="empty",c=empty?null:col(s.color);
        var h=headFor(st,a.idx,s.idx);
        var onHead=ph.some(function(t){return t.ace===a.idx&&t.slot===s.idx&&t.filament_detected});
        var onNow=heads.some(function(t){return t.ace===a.idx&&t.slot===s.idx&&t.filament_detected});
        var name=empty?"vide":esc((s.brand?s.brand+" ":"")+(s.material||"inconnu")+(s.subtype?" "+s.subtype:""));
        var badge=s.source==="derived"?' <span class="badge derived">déduit</span>':"";
        if(!empty&&S.calib&&S.calib[a.idx+"_"+s.idx]===false)badge+=' <span class="badge nocal" title="Calibre ce chemin dans multiACE : Config → Calibration (le plugin ne le fait pas)">chemin non calibré</span>';
        var busyHead=h!=null&&ph.some(function(t){return t.idx===h&&t.filament_detected});
        var act=busyHead?"swap":"load",verb=busyHead?"Échanger":"Charger";
        var btn=empty||h==null?"":onHead?'<span class="badge">'+(onNow?"sur":"prévue sur")+' T'+n(h)+'</span>':
          '<button class="go" data-act="'+act+'" data-head="'+h+'" data-ace="'+a.idx+'" data-slot="'+s.idx+'"'+dis()+'>'+verb+' → T'+n(h)+'</button>';
        var q=empty?"":qty(spoolOf(st,a.idx,s.idx),c);
        var editing=S.edit&&S.edit.ace===a.idx&&S.edit.slot===s.idx;
        return '<div class="item'+(empty?"":" click")+'" data-edit="'+(empty?"":a.idx+"_"+s.idx)+'" title="'+(empty?"":"Cliquer pour déplier / replier : couleur, matière, poids")+'">'+spool(c,22)+'<div class="t"><b>'+n(s.idx)+'</b> '+name+badge+'<small>'+(empty?"":esc(word(s.state)))+'</small>'+(q?'<small>'+q+'</small>':'')+'</div>'+btn+'</div>'+
          (editing?editor(st,a,s):"");
      }).join("")+'</div>';
    }).join("")||'<h4><span>ACE</span></h4><div class="note">Aucun ACE.</div>';
    rearm();
  }
  function keyOf(b){return b.id==="ua"?"ua":b.dataset.act+(b.dataset.head||"")+(b.dataset.ace||"")+(b.dataset.slot||"")}
  // Un rafraichissement ne doit pas annuler un bouton en attente de confirmation.
  function rearm(){if(!S.armed)return;var found=null;
    Array.prototype.forEach.call(document.querySelectorAll("button[data-act],#ua"),function(x){if(keyOf(x)===S.armed)found=x});
    if(!found||found.disabled){S.armed=null;return}
    found.dataset.label=found.textContent;found.classList.add("arm");found.textContent="Confirmer ?"}
  function closeEdit(){S.edit=null;if(S.last)render(S.last)}
  // ---- écran distant de la U1 (Extended Firmware : Paramètres > Firmware > Remote Screen)
  S.screen="off";S.compact=false;S.host="";S.shotBusy=false;
  function screenBox(){return S.screen==="top"?$("screenTop"):S.screen==="bottom"?$("screenBottom"):null}
  function placeScreen(){
    $("screenTop").innerHTML="";$("screenBottom").innerHTML="";
    $("scr").classList.toggle("on",S.screen!=="off");
    $("scr").title="Écran de la U1 : "+(S.screen==="off"?"masqué":S.screen==="top"?"en haut":"en bas")+" (clic pour changer)";
    var box=screenBox();if(!box||!S.host)return;
    box.innerHTML='<div class="screen"><img id="shot" alt="Écran de la U1" title="Clique pour toucher l’écran de la U1"></div>';
    S.shotBusy=false;nextShot();
  }
  function nextShot(){
    var img=$("shot");if(!img||S.shotBusy||document.hidden)return;
    S.shotBusy=true;
    var probe=new Image();
    probe.onload=function(){S.shotBusy=false;var i=$("shot");if(i){i.src=probe.src;i.dataset.w=probe.naturalWidth;i.dataset.h=probe.naturalHeight}};
    probe.onerror=function(){S.shotBusy=false;var b=screenBox();if(b&&$("shot"))b.innerHTML='<div class="screen"><div class="err">Écran distant indisponible.<br>Active <b>Remote Screen</b> dans Paramètres › Firmware de la U1 (firmware Extended).</div></div>';};
    probe.src="http://"+S.host+"/screen/snapshot?t="+Date.now();
  }
  setInterval(nextShot,700);
  // ---- camera de la U1 (Moonraker : webcam « case », image fixe /webcam/snapshot.jpg)
  S.cam="off";S.camBusy=false;
  function camBox(){return S.cam==="top"?$("camTop"):S.cam==="bottom"?$("camBottom"):null}
  function placeCam(){
    $("camTop").innerHTML="";$("camBottom").innerHTML="";
    $("cam").classList.toggle("on",S.cam!=="off");
    $("cam").title="Caméra de la U1 : "+(S.cam==="off"?"masquée":S.cam==="top"?"en haut":"en bas")+" (clic pour changer)";
    var box=camBox();if(!box||!S.host)return;
    box.innerHTML='<div class="cam"><img id="camimg" alt="Caméra de la U1"><span class="live">● LIVE</span></div>';
    S.camBusy=false;nextCam();
  }
  function nextCam(){
    var img=$("camimg");if(!img||S.camBusy||document.hidden)return;
    S.camBusy=true;
    var probe=new Image();
    probe.onload=function(){S.camBusy=false;var i=$("camimg");if(i)i.src=probe.src};
    probe.onerror=function(){S.camBusy=false;var b=camBox();if(b&&$("camimg"))b.innerHTML='<div class="cam"><div class="err">Caméra indisponible pour le moment.</div></div>'};
    probe.src="http://"+S.host+"/webcam/snapshot.jpg?t="+Date.now();
  }
  setInterval(nextCam,1000);
  S.fold={};
  function isF(k){return !!S.fold[k]}
  function climate(a){var h=a.humidity_effective!=null?a.humidity_effective:a.humidity,t=Number(a.temp),out="";
    if(typeof h==="number")out+='<span class="hum '+(h<30?"ok":h<45?"mid":"hi")+'" title="Humidité dans l’ACE">💧 '+Math.round(h)+' %</span>';
    if(a.temp!=null&&a.temp!==""&&isFinite(t))out+=' <span class="hum tmp" title="Température dans l’ACE">🌡 '+Math.round(t)+' °C</span>';
    return out}
  function minis(list,keys){return list.map(function(c,i){return keys?'<span data-pk="'+keys[i]+'">'+spool(c,13)+'</span>':spool(c,13)}).join("")}
  function applyFold(){var hc=$("headsCard");if(hc)hc.classList.toggle("folded",isF("heads"))}
  document.addEventListener("click",function(e){
    var h=e.target.closest&&e.target.closest("[data-fold]");if(!h||e.target.closest("button,select,input,a,[data-pk]"))return;
    var k=h.dataset.fold;S.fold[k]=!isF(k);post({command:"prefs_set",fold:{k:k,on:S.fold[k]}});
    applyFold();if(S.last)render(S.last);renderPrep(S.prep)});
  function closePop(){var o=$("pop");if(o)o.remove()}
  function popFor(pk){
    var st=S.last||{},f=pk.split(":"),k=f[0],heads=st.toolheads||[],ph=planned(st),html="";
    if(k==="h"){var t=heads.filter(function(x){return x.idx===+f[1]})[0];if(!t)return "";
      var c=t.filament_detected?col(t.color):null,src=t.ace!=null&&t.slot!=null?"ACE "+n(t.ace)+" · slot "+n(t.slot):(t.filament_detected?"source inconnue":"vide");
      var p=ph[t.idx]||t;
      html='<div class="pt">'+spool(c,22)+'<div>T'+n(t.idx)+' · '+esc(t.filament_detected?(t.material||"chargée"):"vide")+'<small>'+esc(src)+'</small></div></div>'+
        (p.filament_detected&&!t.manual&&!t.feeder?'<button data-act="unload" data-head="'+t.idx+'"'+dis()+'>Décharger T'+n(t.idx)+'</button>':'<div class="pn">Rien à faire sur cette tête.</div>');
    }else if(k==="s"){var a=(st.aces||[]).filter(function(x){return x.idx===+f[1]})[0],sl=a&&(a.slots||[]).filter(function(x){return x.idx===+f[2]})[0];if(!sl)return "";
      var empty=sl.state==="empty"||sl.source==="empty",c=empty?null:col(sl.color),hh=headFor(st,a.idx,sl.idx);
      var on=ph.filter(function(x){return x.ace===a.idx&&x.slot===sl.idx&&x.filament_detected})[0];
      var busy=hh!=null&&ph.some(function(x){return x.idx===hh&&x.filament_detected});
      html='<div class="pt">'+spool(c,22)+'<div>'+(empty?"Slot "+n(sl.idx)+" vide":esc((sl.brand?sl.brand+" ":"")+(sl.material||""))+' <span style="color:var(--muted)">'+esc(cname(sl.color))+'</span>')+'<small>ACE '+n(a.idx)+' · slot '+n(sl.idx)+'</small></div></div>';
      if(!empty){
        html+=on?'<button data-act="unload" data-head="'+on.idx+'"'+dis()+'>Décharger T'+n(on.idx)+'</button>':
          (hh!=null?'<button class="go" data-act="'+(busy?"swap":"load")+'" data-head="'+hh+'" data-ace="'+a.idx+'" data-slot="'+sl.idx+'"'+dis()+'>'+(busy?"Échanger":"Charger")+' → T'+n(hh)+'</button>':"");
        html+='<button data-pedit="'+a.idx+'_'+sl.idx+'">Modifier couleur / matière / poids…</button>';
      }else html+='<div class="pn">Mets une bobine dans ce slot pour l’utiliser.</div>';
    }else if(k==="a"){var A=(st.aces||[]).filter(function(x){return x.idx===+f[1]})[0];if(!A)return "";
      var d=A.dryer||{},ds=String(d.status||"stop").toLowerCase(),don=ds!=="stop"&&ds!=="free"&&ds!=="",r=Math.round((Number(d.remain_time)||0)/60);
      html='<div class="pt">'+(A.unit_name?esc(A.unit_name):"ACE "+n(A.idx))+'</div><div class="pn">'+climate(A)+'</div>'+
        (don?'<div class="pn">🔥 Séchage '+(d.target_temp||"")+' °C'+(r?' · reste '+(Math.floor(r/60)?Math.floor(r/60)+' h ':'')+r%60+' min':'')+'</div><button data-act="stopdry" data-ace="'+A.idx+'">Arrêter le séchage</button>':
          '<button class="go" data-act="dry" data-ace="'+A.idx+'">Sécher '+(S.dt[A.idx]||45)+' °C · '+((S.dd[A.idx]||240)/60)+' h</button><div class="pn">Température et durée : dans le panneau complet.</div>');
    }
    return html;
  }
  document.addEventListener("click",function(e){
    var pb=e.target.closest&&e.target.closest("[data-pedit]");
    if(pb){var q=pb.dataset.pedit.split("_");closePop();S.edit={ace:+q[0],slot:+q[1]};
      if(S.compact){setCompact(false);savePrefs()}
      if(isF("ace"+q[0])){S.fold["ace"+q[0]]=false;post({command:"prefs_set",fold:{k:"ace"+q[0],on:false}})}
      if(S.last)render(S.last);return}
    var t=e.target.closest&&e.target.closest("[data-pk]");
    if(!t){if(!(e.target.closest&&e.target.closest(".pop")))closePop();return}
    closePop();var html=popFor(t.dataset.pk);if(!html)return;
    var o=document.createElement("div");o.id="pop";o.className="pop";o.innerHTML=html;document.body.appendChild(o);
    var r=t.getBoundingClientRect(),w=o.offsetWidth,h=o.offsetHeight;
    o.style.left=Math.max(6,Math.min(window.innerWidth-w-6,r.left+r.width/2-w/2))+"px";
    o.style.top=(r.bottom+6+h>window.innerHeight?Math.max(6,r.top-h-6):r.bottom+6)+"px";
  },true);
  document.addEventListener("keydown",function(e){if(e.key==="Escape")closePop()});
  function placePrep(){var el=$("prep");if(!el)return;($(S.prepPos==="bottom"?"prepBottom":"prepTop")).appendChild(el)}
  function setCompact(on){
    S.compact=on;document.body.classList.toggle("compact",on);
    $("full").hidden=on;$("mini").hidden=!on;$("cmp").textContent=on?"+":"–";$("cmp").title=on?"Agrandir":"Réduire";
  }
  function renderMini(st){
    var heads=st.toolheads||[],on=function(a,sl){return heads.filter(function(t){return t.filament_detected&&t.ace===a&&t.slot===sl})[0]};
    var p=S.prep,pr="";
    if(p&&p.real_known)pr=p.todo&&p.todo.length?'<div class="mprep todo">⚠ Buses à régler dans OrcaSlicer : '+p.todo.map(function(t){return "T"+(t.t+1)+" "+esc(t.need)}).join(" · ")+'</div>':
      '<div class="mprep ok">✓ Buses OK pour tes bobines</div>';
    var hr='<div class="mrow"><span class="lab">Têtes</span>'+heads.map(function(t){var c=t.filament_detected?col(t.color):null;
      return '<div class="sl" data-pk="h:'+t.idx+'" title="'+esc(t.filament_detected?(t.material||"chargée"):"vide")+'">'+spool(c,20)+'<small class="on">T'+n(t.idx)+'</small></div>'}).join("")+'</div>';
    var ar=(st.aces||[]).map(function(a){
      var d=a.dryer||{},dst=String(d.status||"stop").toLowerCase(),dr=dst!=="stop"&&dst!=="free"&&dst!=="";
      var rm=Math.round((Number(d.remain_time)||0)/60),rt=rm?(Math.floor(rm/60)?Math.floor(rm/60)+" h ":"")+(rm%60)+" min":"";
      var slots=(a.slots||[]).map(function(s){var empty=s.state==="empty"||s.source==="empty",c=empty?null:col(s.color),t=empty?null:on(a.idx,s.idx);
        return '<div class="sl" data-pk="s:'+a.idx+':'+s.idx+'" title="'+esc(empty?"vide":(s.brand?s.brand+" ":"")+(s.material||""))+'">'+spool(c,20)+'<small'+(t?' class="on">T'+n(t.idx):'>'+n(s.idx))+'</small></div>'}).join("");
      return '<div class="mrow"><span class="lab" data-pk="a:'+a.idx+'" title="Séchage">'+(a.unit_name?esc(a.unit_name):"ACE "+n(a.idx))+(a.connected===false?' <span style="color:var(--bad)">✕</span>':"")+'</span>'+slots+
        '<div class="info"><span>'+climate(a)+'</span>'+(dr?'<span>🔥 '+(d.target_temp||"")+'°'+(rt?" · "+rt:"")+'</span>':"")+'</div></div>';
    }).join("");
    $("mini").innerHTML=pr+hr+ar;
  }
  function savePrefs(){post({command:"prefs_set",screen:S.screen,camera:S.cam,compact:S.compact})}
  $("cam").onclick=function(){S.cam=S.cam==="off"?"top":S.cam==="top"?"bottom":"off";placeCam();savePrefs()};
  $("scr").onclick=function(){S.screen=S.screen==="off"?"top":S.screen==="top"?"bottom":"off";placeScreen();savePrefs()};
  $("cmp").onclick=function(){setCompact(!S.compact);savePrefs()};
  $("hd").onclick=function(){post({command:"hide"})};

  document.addEventListener("click",function(e){
    var img=e.target;if(img.id!=="shot"||!img.dataset.w)return;
    var r=img.getBoundingClientRect(),x=Math.round((e.clientX-r.left)*img.dataset.w/r.width),y=Math.round((e.clientY-r.top)*img.dataset.h/r.height);
    post({command:"tap",x:x,y:y});setTimeout(nextShot,250);
  });
  document.addEventListener("click",function(e){
    var t=e.target;
    if(t.dataset&&t.dataset.q){$("e_c").value=t.dataset.q;$("e_hex").value=t.dataset.q;return}
    if(t.id==="e_no"){closeEdit();return}
    if(t.id==="e_rf"){var ed=t.closest(".ed");post({command:"reset",ace:+ed.dataset.ace,slot:+ed.dataset.slot});S.busy=true;say("Envoi…","info");S.edit=null;return}
    if(t.id==="e_ok"){
      var ed2=t.closest(".ed"),hex=$("e_hex").value.trim();
      if(!/^#[0-9a-fA-F]{6}$/.test(hex)){say("Couleur invalide (format #RRGGBB).","err");return}
      var wEl=$("e_w"),spEl=$("e_sp"),sid=$("e_spid");
      post({command:"edit",ace:+ed2.dataset.ace,slot:+ed2.dataset.slot,color:hex,material:$("e_m").value,
            brand:$("e_b").value,subtype:$("e_s").value,weight:wEl?wEl.value:"",apply_spool:spEl?spEl.checked:false,
            spool:sid?sid.value:null});
      S.busy=true;S.edit=null;say("Enregistrement…","info");return;
    }
    if(t.closest("#e_spbtn")){var L=$("e_splist");L.classList.toggle("show");return}
    var o=t.closest(".spo");
    if(o&&o.closest("#e_splist")){var v=o.dataset.v;$("e_spid").value=v;$("e_splist").classList.remove("show");
      $("e_spbtn").innerHTML=(v==="new"?"+ Nouvelle bobine":v===""?"Aucune":o.innerHTML.replace(/<small>.*<\/small>/,""))+" ▾";
      if(v&&v!=="new"){
        if($("e_w"))$("e_w").value=o.dataset.w||"";
        // La bobine choisie impose son identite au slot : couleur, matiere, marque, type.
        var spx=(S.last&&S.last.spools||{})[v];
        if(spx){var hx=col("#"+(spx.color||""));if(hx){hx=hx.toLowerCase();$("e_c").value=hx;$("e_hex").value=hx}
          var mt=String(spx.material||"").toUpperCase();if(mt){var sel=$("e_m");if(!Array.prototype.some.call(sel.options,function(x){return x.value===mt})){var op=document.createElement("option");op.textContent=mt;sel.insertBefore(op,sel.firstChild)}sel.value=mt}
          $("e_b").value=spx.vendor||"";$("e_s").value=spx.subtype||"";
          var cb=$("e_sp");if(cb)cb.checked=false}}
      if(v==="new"&&$("e_w"))$("e_w").value="1000";
      return}
    if(t.closest(".ed")&&!t.closest("button[data-act]"))return;
    var row=t.closest(".item.click");
    if(row&&!t.closest("button")&&row.dataset.edit){
      var p=row.dataset.edit.split("_");
      if(S.edit&&S.edit.ace===+p[0]&&S.edit.slot===+p[1]){closeEdit();return}   // 2e clic : on replie
      S.edit={ace:+p[0],slot:+p[1]};if(S.last)render(S.last);return;
    }
    var b=e.target.closest("button[data-act]")||(e.target.id==="ua"?e.target:null);
    if(!b||b.disabled)return;
    var key=keyOf(b);
    if(S.armed!==key){
      Array.prototype.forEach.call(document.querySelectorAll("button.arm"),function(x){x.classList.remove("arm");x.textContent=x.dataset.label||x.textContent});
      S.armed=key;b.dataset.label=b.textContent;b.classList.add("arm");b.textContent="Confirmer ?";
      clearTimeout(S.armT);S.armT=setTimeout(function(){if(S.armed===key){S.armed=null;if(S.last&&!S.edit)render(S.last)}},6000);
      return;
    }
    S.armed=null;clearTimeout(S.armT);
    var queued=b.id==="ua"||["unload","load","swap","dry","calpa","calbed"].indexOf(b.dataset.act)>=0;
    if(!queued)S.busy=true;
    if(b.id==="ua")post({command:"unload_all"});
    else if(b.dataset.act==="unload")post({command:"unload",head:+b.dataset.head});
    else if(b.dataset.act==="dry"){var ai=+b.dataset.ace;post({command:"dry",ace:ai,temp:S.dt[ai]||45,duration:S.dd[ai]||240})}
    else if(b.dataset.act==="stopdry")post({command:"stopdry",ace:+b.dataset.ace});
    else if(b.dataset.act==="calpa"){post({command:"calib_pa",head:+b.dataset.head,ace:+b.dataset.ace,slot:+b.dataset.slot});S.edit=null}
    else if(b.dataset.act==="calbed")post({command:"calib_bed",temp:S.bt||55});
    else post({command:b.dataset.act,head:+b.dataset.head,ace:+b.dataset.ace,slot:+b.dataset.slot});
    if(b.closest(".pop"))setTimeout(closePop,0);
    if(queued){say("Ajouté à la file d’attente : tu peux en ajouter d’autres.","info");b.textContent=b.dataset.label||b.textContent;b.classList.remove("arm");return}
    say("Commande envoyée à la U1…","info");
  });
  document.addEventListener("input",function(e){
    var t=e.target;
    if(t.id==="e_c")$("e_hex").value=t.value;
    if(t.id==="e_hex"&&/^#[0-9a-fA-F]{6}$/.test(t.value.trim()))$("e_c").value=t.value.trim();
  });
  document.addEventListener("change",function(e){
    var t=e.target;if(t.id==="bt")S.bt=+t.value;
    if(t.dataset.dt!=null)S.dt[t.dataset.dt]=+t.value;if(t.dataset.dd!=null)S.dd[t.dataset.dd]=+t.value;
  });
  $("rf").onclick=function(){post({command:"refresh"})};
  function hostBox(show,title){var b=$("hostbox");b.hidden=!show;S.hostEditing=!!show&&!!title&&title!=="Adresse de la U1 introuvable";$("hostTitle").textContent=title||"Adresse de la U1 introuvable";if(show){var i=$("hostIn");if(!i.value)i.value=S.host||"";}}
  $("hostOk").onclick=function(){var v=$("hostIn").value.trim();if(!v){$("hostIn").focus();return}$("hostOk").disabled=true;post({command:"set_host",host:v})};
  $("hostIn").onkeydown=function(e){if(e.key==="Enter")$("hostOk").onclick()};
  $("hostX").onclick=function(){S.hostEditing=false;$("hostbox").hidden=true};
  function showOpts(on){$("optsCard").hidden=!on;$("opt").classList.toggle("on",on)}
  $("opt").onclick=function(){showOpts($("optsCard").hidden)};
  $("optX").onclick=function(){showOpts(false)};
  $("hostEdit").onclick=function(){$("hostIn").value=S.host||"";hostBox(true,"Modifier l'adresse de la U1");S.hostEditing=true;$("hostIn").focus()};
  $("lang").onchange=function(){post({command:"prefs_set",lang:$("lang").value});say("Langue enregistrée : ferme et rouvre le panneau (ou redémarre OrcaSlicer) pour l'appliquer partout. / Language saved: close and reopen the panel (or restart OrcaSlicer) to apply it everywhere.","info")};
  $("ap").onchange=function(){post({command:"prefs_set",auto_pipeline:$("ap").checked});say($("ap").checked?"L'étape Preflight sera ajoutée aux profils de traitement de la U1.":"Le plugin ne touche plus aux profils de traitement.","info")};
  function pipeShow(p){var e=$("pipeSt");if(!e||!p)return;var t="",w=false;
    if(p.state==="present")t="✓ Étape Preflight présente dans « "+esc(p.preset||"")+" »";
    else if(p.state==="added"){t="Étape Preflight ajoutée à « "+esc(p.preset||"")+" » : <b>enregistre le profil</b> (disquette) pour la garder";w=true;
      if(!S.pipeSaid||S.pipeSaid!==p.preset){S.pipeSaid=p.preset;say("Étape « multiACE : envoyer au Preflight » ajoutée au profil « "+(p.preset||"")+" » : enregistre-le (disquette) pour la garder.","info")}}
    else if(p.state==="missing"){t="Étape Preflight absente de « "+esc(p.preset||"")+" »";w=true}
    else if(p.state==="not_u1")t="Étape Preflight : imprimante active autre que la U1";
    else if(p.state==="error"){t="Étape Preflight : ajout impossible ("+esc(p.error||"")+")";w=true}
    if(p.ran_version){if(p.ran_here===false){t+="<br>⚠ Le dernier export est passé par une <b>autre copie</b> du plugin (v"+esc(p.ran_version)+") : garde une seule copie de multiACE Bridge dans Fichier → Plugins.";w=true}
      else if(p.ran_here)t+="<br>Dernier export préparé par cette copie (v"+esc(p.ran_version)+")"+(p.ran_version!==p.version?" — avant la mise à jour":"")}
    e.innerHTML=t;e.style.color=w?"#f0b060":""}
  $("uc").onchange=function(){post({command:"prefs_set",u1_code:$("uc").checked});say($("uc").checked?"Export : Preflight de la U1 exécuté dans Orca, avec vérifications.":"Export : fichier d'origine envoyé au Preflight de multiACE.","info")};
  $("gf").onchange=function(){post({command:"prefs_set",ace_guard:$("gf").checked});say($("gf").checked?"Garde-fou activé : séchage et poussée relancés si un ACE se déconnecte.":"Garde-fou désactivé.","info")};
  $("ah").onchange=function(){post({command:"prefs_set",auto_home:$("ah").checked});say($("ah").checked?"Homing automatique activé : la U1 fera son homing toute seule si besoin.":"Homing automatique désactivé : le panneau te demandera.","info")};
  window.orca&&window.orca.onMessage(function(m){
    if(!m)return;
    if(m.command==="host_result"){$("hostOk").disabled=false;if(m.ok){S.host=m.host;$("hostCur").textContent=m.host;hostBox(false);say("Adresse enregistrée : "+m.host,"ok")}else{hostBox(true,m.error||"Adresse invalide");}return}
    if(m.command==="state"){if(m.nohost){$("st").className="pill bad";$("st").textContent="sans adresse";hostBox(true);return}if(m.error){$("st").className="pill bad";$("st").textContent="hors ligne";say(m.error,"err");if(m.unreachable)hostBox(true,"La U1 ne répond pas à "+(S.host||"cette adresse")+" : vérifie l'adresse.");return}if(!S.hostEditing)hostBox(false);S.calib=m.calib||null;renderPrep(m.prep);pipeShow(m.pipe);if(S.edit){S.last=m.state||{};return}render(m.state||{})}
    else if(m.command==="prefs"){S.host=m.host||"";S.screen=m.screen||"off";S.cam=m.camera||"off";setCompact(!!m.compact);placeScreen();placeCam();S.prepPos=m.prep_pos==="bottom"?"bottom":"top";placePrep();S.fold=m.folds||{};applyFold();$("ah").checked=!!m.auto_home;$("gf").checked=m.ace_guard!==false;$("uc").checked=m.u1_code!==false;$("ap").checked=m.auto_pipeline!==false;if($("lang"))$("lang").value=m.lang||"auto";$("hostCur").textContent=S.host||"non renseignée";if(!S.host)hostBox(true)}
    else if(m.command==="done"){S.busy=false;say(m.text,m.ok?"info":"err");
      if(m.fix==="home"){var mm=$("msg");var b=document.createElement("div");b.style.marginTop="8px";
        b.innerHTML='<button class="fixbtn" data-r="1">Faire le homing puis reprendre</button> <button class="fixbtn ghost" data-r="0">Homing seul</button>';
        mm.appendChild(b);b.querySelectorAll("button").forEach(function(x){x.onclick=function(){S.busy=true;say("Homing en cours (G28)…","info");post({command:"home",retry:x.getAttribute("data-r")==="1"})}})}
      post({command:"refresh"})}
    else if(m.command==="status"){say(m.text,"info")}
    else if(m.command==="guard"){say(m.text,m.kind||"info");if(m.ask!=null){var gb=document.createElement("div");gb.style.marginTop="8px";gb.innerHTML='<button class="fixbtn">Relancer le séchage</button>';gb.querySelector("button").onclick=function(){post({command:"guard_dry",ace:m.ask});say("Séchage relancé…","info")};$("msg").appendChild(gb)}}
    else if(m.command==="queue"){renderQueue(m);if(S.last&&!S.edit)render(S.last)}
  });
  post({command:"prefs_get"});
  post({command:"refresh"});
  setInterval(function(){if(!document.hidden&&S.armed==null&&!(document.activeElement&&document.activeElement.tagName==="SELECT"))post({command:"refresh"})},4000);
})();
</script></body></html>"""


def action_label(name, a):
    """Libelle lisible d'une macro multiACE (numerotation 1-based comme sur la U1)."""
    def g(k):
        try:
            return int(a.get(k)) + 1
        except (TypeError, ValueError):
            return "?"
    if name == "ACE_SWAP_HEAD":
        return "Échange T%s ← ACE %s slot %s" % (g("HEAD"), g("ACE"), g("SLOT"))
    if name == "ACE_LOAD_HEAD":
        return "Chargement T%s ← ACE %s slot %s" % (g("HEAD"), g("ACE"), g("SLOT"))
    if name == "ACE_UNLOAD_HEAD":
        return "Déchargement T%s" % g("HEAD")
    if name == "ACE_UNLOAD_ALL_HEADS":
        return "Déchargement de toutes les têtes"
    if name == "ACE_DRY":
        try:
            d = int(a.get("DURATION"))
            dur = "%d h%s" % (d // 60, (" %02d" % (d % 60)) if d % 60 else "")
        except (TypeError, ValueError):
            dur = "?"
        return "Séchage ACE %s (%s °C, %s)" % (g("ACE"), a.get("TEMP"), dur)
    if name == "ACE_PA_CALIBRATE":
        return "Calibration du filament (PA) sur T%s" % g("HEAD")
    if name == "AUTO_BED_MESH_CALIBRATE":
        return "Calibration du plateau (%s °C)" % a.get("TEMP", 55)
    if name == "ACE_STOP_DRYING":
        return "Arrêt du séchage ACE %s" % g("ACE")
    return " ".join([name] + ["%s=%s" % kv for kv in a.items()])


QUEUE_POLL = 2.0
UNLOAD_SETTLE, UNLOAD_POLL = 12.0, 1.0
HEAD_MOVES = ("ACE_LOAD_HEAD", "ACE_SWAP_HEAD", "ACE_UNLOAD_HEAD", "ACE_UNLOAD_ALL_HEADS")
CALIBRATIONS = ("ACE_PA_CALIBRATE", "AUTO_BED_MESH_CALIBRATE")
NEEDS_HOME = HEAD_MOVES + CALIBRATIONS


class AcePanelController:
    """Panneau ancre a cote de la vue 3D (Preparer / Apercu). Une seule instance pour tout le plugin."""

    def __init__(self):
        self.panel = None
        self._lock = threading.Lock()
        self._refreshing = False
        self._action = False
        self._qlock = threading.Lock()
        self._queue, self._qid, self._qrun, self._paused = [], 0, False, False
        self.closed_by_user = False

    def open(self, force=False):
        """Ouvre (ou reaffiche) le panneau. Retourne un message."""
        if self.panel is not None and self.panel.is_open():
            self.panel.show()
            return "Panneau ACE affiche."
        if self.closed_by_user and not force:
            return "Panneau ferme par l'utilisateur."
        self.closed_by_user = False
        self.panel = orca.host.ui.create_dock_panel(
            html=i18n_page(PANEL.replace("__VERSION__", VERSION)), title="multiACE", width=320, height=620,
            on_message=self.on_message, on_close=self.on_close, dock="right")
        return "Panneau ACE ouvert."

    def on_close(self):
        self.panel = None
        self.closed_by_user = True

    def hide(self):
        """Masque le panneau sans le fermer, et laisse une notification pour le rouvrir."""
        panel = self.panel
        if panel is None:
            return
        panel.hide()
        try:
            ui = orca.host.ui
            level = getattr(ui, "ImportantNotificationLevel", None) or getattr(ui.NotificationLevel, "ImportantNotificationLevel")
            _notify(ui, level, "Panneau multiACE masqué.", "Afficher", self._show_from_notification)
        except Exception:
            pass

    def _show_from_notification(self):
        try:
            if self.panel is not None and self.panel.is_open():
                self.panel.show()
            else:
                self.open(force=True)
        except Exception:
            pass
        return True

    def _post(self, data):
        panel = self.panel
        if panel is not None:
            try:
                panel.post(data)
            except Exception:
                pass

    # Appele sur le fil de l'interface.
    def on_message(self, message):
        if isinstance(message, str):
            try:
                message = json.loads(message)
            except ValueError:
                return
        if not isinstance(message, dict):
            return
        cmd = message.get("command")
        if cmd == "refresh":
            self._refresh()
            return
        if cmd == "set_host":
            raw = str(message.get("host") or "")[:200]
            host = normalize_host(raw)
            if not host:
                self._post({"command": "host_result", "ok": False, "error": "Adresse invalide, par exemple 192.168.1.50"})
                return
            # Sur le fil de l'interface : OrcaSlicer peut demander l'autorisation pour cette adresse.
            try:
                MultiAce(host).get_json("/version", timeout=TIMEOUT_UI)
            except PermissionError:
                self._post({"command": "host_result", "ok": False, "error": permission_text(host)})
                return
            except Exception:
                self._post({"command": "host_result", "ok": False,
                            "error": "Pas de multiACE à %s : vérifie l'adresse (la U1 est-elle allumée ?)" % host})
                return
            st = load_settings()
            st["host"] = host
            save_settings(st)
            _probed.add(host)
            self._post({"command": "host_result", "ok": True, "host": host})
            self._refresh()
            return
        if cmd == "prefs_get":
            probe_network(effective_host())
            if remove_old_profile():
                self._post({"command": "done", "ok": True,
                            "text": "Ancien profil « Snapmaker U1 multiACE » supprimé (il disparaît de la liste au plus tard au prochain démarrage)."})
            st = load_settings()
            self._post({"command": "prefs", "host": effective_host(), "screen": st["screen"], "compact": st["compact"],
                        "prep_pos": st["prep_pos"], "folds": st["folds"], "camera": st["camera"],
                        "auto_home": st["auto_home"],
                        "ace_guard": st["ace_guard"], "u1_code": st["u1_code"], "real_nozzles": st["real_nozzles"],
                        "auto_pipeline": st["auto_pipeline"], "lang": st["lang"], "lang_now": ui_lang()})
            _GUARD.ensure()
            return
        if cmd == "prefs_set":
            st = load_settings()
            if message.get("camera") in ("off", "top", "bottom"):
                st["camera"] = message["camera"]
            if message.get("screen") in ("off", "top", "bottom"):
                st["screen"] = message["screen"]
            if isinstance(message.get("compact"), bool):
                st["compact"] = message["compact"]
            if message.get("prep_pos") in ("top", "bottom"):
                st["prep_pos"] = message["prep_pos"]
            f = message.get("fold")
            if isinstance(f, dict) and isinstance(f.get("k"), str) and re.fullmatch(r"heads|prep|ace[0-7]", f["k"]) \
                    and isinstance(f.get("on"), bool):
                st["folds"] = dict(st.get("folds") or {}, **{f["k"]: f["on"]})
            if isinstance(message.get("auto_home"), bool):
                st["auto_home"] = message["auto_home"]
            if isinstance(message.get("ace_guard"), bool):
                st["ace_guard"] = message["ace_guard"]
            if isinstance(message.get("u1_code"), bool):
                st["u1_code"] = message["u1_code"]
            if message.get("lang") in LANGS:
                st["lang"] = message["lang"]
                _LANG["v"] = None
            if isinstance(message.get("auto_pipeline"), bool):
                st["auto_pipeline"] = message["auto_pipeline"]
                _PIPE["status"] = None
            rn = message.get("real_nozzles")
            if isinstance(rn, list) and len(rn) == 4 and all(x in NOZZLE_CHOICES or x == "" for x in rn):
                st["real_nozzles"] = list(rn)
            try:
                save_settings(st)
            except OSError:
                pass
            return
        if cmd == "guard_dry":
            _GUARD.redo_dry(message.get("ace"))
            return
        if cmd == "hide":
            self.hide()
            return
        if cmd == "home":
            self._home(bool(message.get("retry")))
            return
        if cmd in ("queue_clear", "queue_remove", "queue_resume"):
            self._queue_cmd(cmd, message)
            return
        if cmd == "tap":
            try:
                x, y = int(message.get("x")), int(message.get("y"))
            except (TypeError, ValueError):
                return
            if 0 <= x < 4096 and 0 <= y < 4096:
                host = effective_host()

                def tap():
                    try:
                        MultiAce(host).screen_tap(x, y)
                    except PermissionError:
                        self._post({"command": "done", "ok": False, "text": permission_text(host)})
                    except Exception as e:
                        self._post({"command": "done", "ok": False, "text": "Toucher l'ecran : %s" % e})
                threading.Thread(target=tap, daemon=True).start()
            return
        script = None
        try:
            head = int(message.get("head"))
            if not 0 <= head <= 3:
                raise ValueError
        except (TypeError, ValueError):
            head = None
        if cmd in ("load", "swap") and head is not None:
            try:
                ace, slot = int(message.get("ace")), int(message.get("slot"))
            except (TypeError, ValueError):
                return
            if not (0 <= ace <= 7 and 0 <= slot <= 3):
                return
            script = ("ACE_SWAP_HEAD" if cmd == "swap" else "ACE_LOAD_HEAD", {"HEAD": head, "ACE": ace, "SLOT": slot})
        elif cmd == "unload" and head is not None:
            script = ("ACE_UNLOAD_HEAD", {"HEAD": head})
        elif cmd == "unload_all":
            script = ("ACE_UNLOAD_ALL_HEADS", {})
        elif cmd == "edit":
            self._edit(message)
            return
        elif cmd == "calib_pa" and head is not None:
            try:
                ace, slot = int(message.get("ace")), int(message.get("slot"))
            except (TypeError, ValueError):
                return
            if 0 <= ace <= 7 and 0 <= slot <= 3:
                # La bobine choisie d'abord sur sa tete (sautee si elle y est deja), puis la mesure,
                # forcee meme si une valeur existe : multiACE la memorise sur la bobine pour cette buse.
                self._run("ACE_LOAD_HEAD", {"HEAD": head, "ACE": ace, "SLOT": slot})
                self._run("ACE_PA_CALIBRATE", {"HEAD": head, "FORCE": 1})
            return
        elif cmd == "calib_bed":
            try:
                temp = int(message.get("temp") or 55)
            except (TypeError, ValueError):
                return
            if 40 <= temp <= 110:
                self._run("AUTO_BED_MESH_CALIBRATE", {"TEMP": temp})
            return
        elif cmd == "reset":
            try:
                ace, slot = int(message.get("ace")), int(message.get("slot"))
            except (TypeError, ValueError):
                return
            if 0 <= ace <= 7 and 0 <= slot <= 3:
                def job(client):
                    client.clear_override(ace, slot)
                    client.macro("MULTIACE_REFRESH_OVERRIDES", {}, timeout=60)
                self._work("Retour a l'identite RFID", job)
            return
        elif cmd in ("dry", "stopdry"):
            try:
                ace = int(message.get("ace"))
            except (TypeError, ValueError):
                return
            if not 0 <= ace <= 7:
                return
            if cmd == "stopdry":
                # Arreter le sechage est toujours sans risque, meme pendant une impression.
                _GUARD.expect_stop(ace)
                self._run("ACE_STOP_DRYING", {"ACE": ace}, allow_busy=True)
                return
            try:
                temp, duration = int(message.get("temp")), int(message.get("duration"))
            except (TypeError, ValueError):
                return
            if not (30 <= temp <= 55 and 10 <= duration <= 480):
                return
            # Comme l'interface web multiACE (ACE_DRY), aussi pendant une impression : multiACE 1.27b
            # garde l'assistance d'alimentation de la tete qui imprime pendant le changement d'ACE actif.
            self._run("ACE_DRY", {"ACE": ace, "TEMP": temp, "DURATION": duration}, allow_busy=True)
            return
        if script:
            self._run(*script)

    def _refresh(self):
        if _STOP.is_set():
            return
        host = effective_host()
        if not host:
            self._post({"command": "state", "nohost": True})
            return
        with self._lock:
            if self._refreshing:
                return
            self._refreshing = True

        def worker():
            try:
                client = MultiAce(host)
                state = client.state(timeout=TIMEOUT_UI)
                msg = {"command": "state", "state": state}
                setup = orca_filament_setup()
                if setup is not None and isinstance(state, dict):
                    real, src = effective_nozzles(client)
                    msg["prep"] = dict(slicing_advice(state, real, setup[0], setup[1]), real=real, real_src=src,
                                       manual=load_settings()["real_nozzles"])
                try:
                    msg["pipe"] = pipeline_status()
                except Exception:
                    pass
                try:
                    msg["calib"] = path_calibration(client)
                except Exception:
                    pass
                self._post(msg)
            except PermissionError:
                self._post({"command": "state", "error": permission_text(host)})
            except Exception as e:
                self._post({"command": "state", "error": str(e), "unreachable": "injoignable" in str(e)})
            finally:
                with self._lock:
                    self._refreshing = False

        threading.Thread(target=worker, daemon=True).start()

    def _edit(self, m):
        """Meme chemin que le selecteur de slot de multiACE : surcharge d'identite du slot
        (POST /slot-override) + ACE_SPOOL_SET sur la bobine associee (couleur, matiere, poids)."""
        try:
            ace, slot = int(m.get("ace")), int(m.get("slot"))
        except (TypeError, ValueError):
            return
        if not (0 <= ace <= 7 and 0 <= slot <= 3):
            return

        def clean(v, n=40):
            return gcode_safe(v, n)

        material = clean(m.get("material"), 16).upper() or "PLA"
        brand, subtype = clean(m.get("brand")), clean(m.get("subtype"))
        color = str(m.get("color") or "").strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            self._post({"command": "done", "ok": False, "text": "Couleur invalide."})
            return
        weight = m.get("weight")
        try:
            weight = None if weight in (None, "") else int(round(float(weight)))
        except (TypeError, ValueError, OverflowError):
            weight = None
        if weight is not None and not 0 <= weight <= 65535:
            self._post({"command": "done", "ok": False, "text": "Poids invalide."})
            return
        apply_spool = bool(m.get("apply_spool", True))

        spool = m.get("spool")
        if spool is not None:
            spool = str(spool).strip()
            if spool not in ("", "new") and not spool.isdigit():
                self._post({"command": "done", "ok": False, "text": "Bobine invalide."})
                return

        def job(client):
            client.set_override(ace, slot, material, brand, subtype, color.lower())
            state = client.state(timeout=TIMEOUT_UI)
            sid = (state.get("spool_binding") or {}).get("%d_%d" % (ace, slot))
            sid = str(sid) if sid else None
            if spool == "new":
                # Nouvelle entree dans la table multiACE, liee directement a ce slot (comme le web).
                add = {"MATERIAL": material, "COLOR": color[1:].upper(), "ACE": ace, "SLOT": slot}
                if brand:
                    add["VENDOR"] = brand
                if subtype:
                    add["SUBTYPE"] = subtype
                if weight is not None:
                    add["WEIGHT"] = weight
                client.macro("ACE_SPOOL_ADD", add, timeout=60)
                client.macro("MULTIACE_REFRESH_OVERRIDES", {}, timeout=60)
                return
            if spool is not None and spool != (sid or ""):
                if spool:
                    client.macro("ACE_SPOOL_ASSIGN", {"ACE": ace, "SLOT": slot, "ID": spool}, timeout=60)
                    sid = spool
                else:
                    client.macro("ACE_SPOOL_ASSIGN", {"ACE": ace, "SLOT": slot}, timeout=60)   # detache
                    sid = None
            if sid:
                args = {"ID": sid}
                if apply_spool:
                    args.update(MATERIAL=material, COLOR=color[1:].upper(), SUBTYPE=subtype)
                    if brand:
                        args["VENDOR"] = brand
                if weight is not None:
                    args["WEIGHT"] = weight
                if len(args) > 1:
                    client.macro("ACE_SPOOL_SET", args, timeout=60)
            client.macro("MULTIACE_REFRESH_OVERRIDES", {}, timeout=60)

        self._work("Slot %d de l'ACE %d mis a jour" % (slot + 1, ace + 1), job)

    def _work(self, label, job):
        """Action de gestion (identite, poids) : autorisee meme pendant une impression, comme dans multiACE."""
        host = effective_host()
        with self._lock:
            if self._action:
                self._post({"command": "done", "ok": False, "text": "Une action est deja en cours."})
                return
            self._action = True

        def worker():
            try:
                job(MultiAce(host))
                self._post({"command": "done", "ok": True, "text": label + "."})
            except PermissionError:
                self._post({"command": "done", "ok": False, "text": permission_text(host)})
            except Exception as e:
                self._post({"command": "done", "ok": False, "text": "Echec : %s" % e})
            finally:
                with self._lock:
                    self._action = False

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------ file d'attente des actions de tete
    # Charger / echanger / decharger s'enchainent dans l'ordre des clics. Chaque action est revue au
    # moment de partir (charger devient echanger si la tete est occupee, une action deja faite est
    # sautee). Au premier echec la file se met en pause : rien ne part tant que tu n'as pas repris.

    def _queue_post(self):
        with self._qlock:
            items = [{"id": it["id"], "label": it["label"], "status": it["status"], "name": it["name"],
                      "args": it["args"]} for it in self._queue]
            paused = self._paused
        self._post({"command": "queue", "items": items, "paused": paused})

    def _enqueue(self, name, args, allow_busy=False):
        with self._qlock:
            self._qid += 1
            self._queue.append({"id": self._qid, "name": name, "args": dict(args), "label": action_label(name, args),
                                "status": "attente", "allow_busy": allow_busy})
        self._queue_post()
        self._kick()

    def _kick(self):
        with self._qlock:
            if self._qrun or self._paused or not self._queue:
                return
            self._qrun = True
        threading.Thread(target=self._queue_worker, args=(effective_host(),), daemon=True).start()

    def _queue_worker(self, host):
        try:
            while True:
                with self._qlock:
                    if self._paused or not self._queue:
                        break
                    item = self._queue[0]
                    item["status"] = "en cours"
                self._queue_post()
                try:
                    ok, text, fix = self._exec(MultiAce(host), item["name"], item["args"],
                                               item.get("allow_busy", False), queued=True)
                except PermissionError:
                    ok, text, fix = False, permission_text(host), None
                except Exception as e:
                    ok, text, fix = False, "Echec de %s : %s" % (item["label"], friendly_error(str(e))), None
                with self._qlock:
                    if ok:
                        if self._queue and self._queue[0] is item:
                            self._queue.pop(0)
                    else:
                        item["status"] = "échec"
                        self._paused = True
                    rest = len(self._queue)
                msg = {"command": "done", "ok": ok, "text": text}
                if fix:
                    msg["fix"] = fix
                if not ok and rest > 1:
                    msg["text"] += " File en pause (%d action(s) en attente)." % (rest - 1)
                self._post(msg)
                self._queue_post()
        finally:
            with self._qlock:
                self._qrun = False
        self._kick()

    def _queue_cmd(self, cmd, message):
        with self._qlock:
            if cmd == "queue_clear":
                self._queue = [it for it in self._queue if it["status"] == "en cours"]
                self._paused = False
            elif cmd == "queue_remove":
                self._queue = [it for it in self._queue
                               if it["status"] == "en cours" or it["id"] != message.get("id")]
                if not any(it["status"] == "échec" for it in self._queue):
                    self._paused = False
            elif cmd == "queue_resume":
                for it in self._queue:
                    if it["status"] == "échec":
                        it["status"] = "attente"
                self._paused = False
        self._queue_post()
        self._kick()

    def _home(self, retry):
        host = effective_host()
        with self._qlock:
            if self._qrun:
                self._post({"command": "done", "ok": False, "text": "Une action est en cours : attends sa fin."})
                return
            self._qrun = True          # bloque la file pendant le homing

        def worker():
            ok = False
            try:
                client = MultiAce(host)
                state = client.state(timeout=TIMEOUT_UI)
                ps = str(state.get("printer_state") or "").lower()
                if ps in ("printing", "paused") or state.get("swap_in_progress"):
                    raise MultiAceError("la U1 imprime : pas de homing pendant une impression")
                self._post({"command": "status", "text": "Homing en cours (G28)…"})
                client.home()
                ok = True
                with self._qlock:
                    waiting = len(self._queue)
                self._post({"command": "done", "ok": True,
                            "text": "Homing terminé." + (" Reprise de la file (%d action(s))." % waiting
                                                         if retry and waiting else "")})
            except PermissionError:
                self._post({"command": "done", "ok": False, "text": permission_text(host)})
            except Exception as e:
                self._post({"command": "done", "ok": False, "text": "Homing : %s" % e})
            finally:
                with self._qlock:
                    self._qrun = False
            if ok and retry:
                self._queue_cmd("queue_resume", {})

        threading.Thread(target=worker, daemon=True).start()

    def _exec(self, client, name, args, allow_busy, queued=False):
        """Execute une macro multiACE. Retourne (ok, texte, correctif propose)."""
        state = client.state(timeout=TIMEOUT_UI)
        ps = str(state.get("printer_state") or "").lower()
        def occupied(st, p):
            return bool(st.get("swap_in_progress") or st.get("unload_all_active") or p == "busy")
        if queued and not allow_busy and ps not in ("printing", "paused") and occupied(state, ps):
            # U1 occupee (echange multiACE, macro ou homing en cours, lance d'ici ou d'ailleurs) :
            # on attend qu'elle se libere au lieu d'echouer.
            self._post({"command": "status", "text": "La U1 termine une opération : l'action suivante attend…"})
            end = time.time() + 600
            while occupied(state, ps) and ps not in ("printing", "paused") and time.time() < end:
                time.sleep(QUEUE_POLL)
                state = client.state(timeout=TIMEOUT_UI)
                ps = str(state.get("printer_state") or "").lower()
        if not allow_busy and (ps in ("printing", "paused") or state.get("swap_in_progress")
                               or (queued and ps == "busy")):
            why = {"printing": "en impression", "paused": "en pause", "busy": "occupée depuis plus de 10 min"}.get(
                ps, "échange multiACE en cours depuis plus de 10 min" if state.get("swap_in_progress") else ps)
            raise MultiAceError("la U1 est %s : action refusée. Regarde l'écran de la U1 et l'interface "
                                "multiACE, puis clique « Reprendre »." % why)
        heads = state.get("toolheads") or []
        if queued and name in HEAD_MOVES:
            # L'etat a pu changer depuis le clic (actions precedentes de la file) : on ajuste.
            try:
                h = int(args.get("HEAD", -1))
            except (TypeError, ValueError):
                h = -1
            th = heads[h] if 0 <= h < len(heads) else {}
            if name in ("ACE_LOAD_HEAD", "ACE_SWAP_HEAD"):
                if (th.get("filament_detected") and th.get("ace") == int(args["ACE"])
                        and th.get("slot") == int(args["SLOT"])):
                    return True, "Déjà en place : " + action_label(name, args), None
                name = "ACE_SWAP_HEAD" if th.get("filament_detected") else "ACE_LOAD_HEAD"
            elif name == "ACE_UNLOAD_HEAD" and th and not th.get("filament_detected"):
                return True, "Déjà vide : " + action_label(name, args), None
            elif name == "ACE_UNLOAD_ALL_HEADS" and heads and not any(x.get("filament_detected") for x in heads):
                return True, "Têtes déjà vides.", None
        label = action_label(name, args)
        auto_home = name in NEEDS_HOME and ps not in ("printing", "paused") and load_settings().get("auto_home")
        homed_now = False

        def do_home():
            self._post({"command": "status", "text": "Homing automatique (G28) avant : %s…" % label})
            client.home()

        if name in NEEDS_HOME:
            homed = client.homed_axes()
            if homed is not None and "z" not in homed.lower():
                if not auto_home:
                    # Klipper refuserait (« Must home Z axis first ») : on propose le homing d'abord.
                    return (False, "%s : la U1 n'est pas référencée (homing). Clique « Faire le homing puis "
                                   "reprendre » : la U1 fait son Home puis reprend." % label, "home")
                do_home()
                homed_now = True
        for attempt in (1, 2):
            try:
                client.macro(name, args, timeout=60 if name in ("ACE_DRY", "ACE_STOP_DRYING")
                             else 1800 if name in CALIBRATIONS else 900)
                break
            except PermissionError:
                raise
            except Exception as e:
                if "timed out" in str(e).lower():
                    return True, "Toujours en cours sur la U1 : " + label, None
                if needs_home(str(e)):
                    if auto_home and attempt == 1 and not homed_now:
                        do_home()           # verification impossible avant : homing puis un seul nouvel essai
                        homed_now = True
                        continue
                    return False, "%s impossible : %s" % (label, friendly_error(str(e))), "home"
                return False, "Echec de %s : %s" % (label, friendly_error(str(e))), None
        if name in ("ACE_UNLOAD_ALL_HEADS", "ACE_UNLOAD_HEAD"):
            # Le capteur de tete remonte avec un peu de retard (cache multiACE ~5 s) : on attend qu'il
            # passe a vide avant de conclure, au lieu de lire l'etat une seule fois.
            want = None if name == "ACE_UNLOAD_ALL_HEADS" else int(args.get("HEAD", -1))
            left, end = [], time.time() + UNLOAD_SETTLE
            while True:
                try:
                    now_heads = client.state(timeout=TIMEOUT_UI).get("toolheads") or []
                    left = [i for i, x in enumerate(now_heads)
                            if x.get("filament_detected") and (want is None or i == want)]
                except Exception:
                    left = []
                if not left or time.time() >= end:
                    break
                time.sleep(UNLOAD_POLL)
            if left:
                # multiACE a termine sans erreur : on ne bloque pas la file sur ce seul capteur, qui peut
                # rester a "detecte" alors que la tete est vide (constate sur la U1). Simple avertissement.
                names = ", ".join("T%d" % (i + 1) for i in left)
                return (True, "Terminé : %s. Le capteur de %s indique encore du filament : si la tête est "
                              "bien vide, ignore ce message ; sinon retire le reste à la main." % (label, names),
                        None)
        return True, "Terminé : " + label + (" (homing automatique fait avant)" if homed_now else ""), None

    def _run(self, name, args, allow_busy=False):
        if name in HEAD_MOVES or name in CALIBRATIONS or name == "ACE_DRY":
            # Le sechage passe aussi par la file, a sa place dans l'ordre des clics (file vide : il part
            # tout de suite). Il reste autorise pendant une impression, comme dans multiACE.
            self._enqueue(name, args, allow_busy)
            return
        host = effective_host()      # sechage : tout de suite, hors file (aussi pendant une impression)

        def worker():
            try:
                ok, text, fix = self._exec(MultiAce(host), name, args, allow_busy)
                msg = {"command": "done", "ok": ok, "text": text}
                if fix:
                    msg["fix"] = fix
                self._post(msg)
            except PermissionError:
                self._post({"command": "done", "ok": False, "text": permission_text(host)})
            except Exception as e:
                self._post({"command": "done", "ok": False,
                            "text": "Echec de %s : %s" % (action_label(name, args), friendly_error(str(e)))})

        threading.Thread(target=worker, daemon=True).start()


_PANEL = AcePanelController()


# --------------------------------------------------------------------------- garde-fou ACE
#
# Un ACE qui perd sa liaison USB redemarre : son sechage s'arrete et il ne pousse plus le filament.
# multiACE rearme deja la poussee de la tete qui imprime quand il reussit a se reconnecter ; le
# garde-fou est un filet en plus, cote OrcaSlicer :
#   - sechage : un ACE vu deconnecte puis revenu, dont le sechage s'est arrete, est relance avec la
#     meme temperature et le temps qu'il restait. Arret inexplique sans deconnexion vue (coupure plus
#     courte que le releve) : on demande, bouton « Relancer », on ne relance pas tout seul.
#     Un arret demande depuis le panneau ou un sechage automatique (multiACE) ne sont jamais touches ;
#   - poussee : pendant une impression, uniquement pour la tete qui imprime, si l'ACE qui l'alimente
#     ne pousse plus depuis GUARD_FA_LOST secondes (multiACE n'a pas repris la main). Jamais pour une
#     autre tete, jamais pendant un echange, au plus GUARD_FA_MAX essais.
# Fonctionne tant qu'OrcaSlicer est ouvert. Lecture de /api/state toutes les GUARD_POLL secondes.

GUARD_POLL = 2.0            # s entre deux releves
GUARD_SETTLE = 8.0          # s laisses a un ACE revenu (et a multiACE) avant d'agir
GUARD_DRY_MIN_LEFT = 180    # s : en dessous, le sechage etait de toute facon presque fini
GUARD_DRY_WINDOW = 30.0     # s : une deconnexion vue autant avant l'arret du sechage l'explique
GUARD_FA_LOST = 12.0        # s sans poussee sur la tete qui imprime avant d'intervenir
GUARD_FA_RETRY = 60.0       # s entre deux essais
GUARD_FA_MAX = 3            # essais par tete et par impression


def _drying_of(ace):
    """(temperature, secondes restantes) si l'ACE seche en ce moment, sinon None."""
    d = ace.get("dryer") if isinstance(ace.get("dryer"), dict) else {}
    if str(d.get("status") or "").lower() in ("", "stop", "free", "unknown"):
        return None
    try:
        temp, left = int(float(d.get("target_temp") or 0)), int(float(d.get("remain_time") or 0))
    except (TypeError, ValueError):
        return None
    return (temp, left) if 30 <= temp <= 70 and left > 0 else None


def _int_or_none(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


class AceGuard:
    """Decisions du garde-fou (sans reseau). step() recoit l'etat multiACE, la tete qui imprime et
    l'heure, et rend la liste des actions :
      ("dry", ace, temp, minutes)     relancer le sechage (deconnexion constatee)
      ("ask_dry", ace, temp, minutes) proposer de le relancer (arret inexplique)
      ("fa", ace, slot, head)         relancer la poussee de la tete qui imprime
      ("note", texte, genre)          information a afficher ("info" / "err")"""

    def __init__(self):
        self.aces = {}
        self.fa = {}
        self.stops = {}
        self.offer = {}

    def expect_stop(self, ace, now):
        self.stops[ace] = now + 60.0

    def step(self, state, head, now):
        out = []
        for a in state.get("aces") or []:
            i = _int_or_none(a.get("idx"))
            if i is None:
                continue
            r = self.aces.setdefault(i, {"conn": None, "dry": None, "lost": None, "back": None, "todo": None})
            conn = bool(a.get("connected"))
            if not conn:
                if r["conn"]:
                    r["lost"] = now
                    out.append(("note", "ACE %d déconnecté." % (i + 1), "err"))
                r["conn"] = False
                continue                       # on garde son dernier sechage en memoire
            if r["conn"] is False:
                r["back"] = now
                out.append(("note", "ACE %d revenu." % (i + 1), "info"))
            r["conn"] = True
            dry = _drying_of(a)
            if dry:
                r["dry"] = (dry[0], dry[1], now, bool(a.get("auto_dry_running")))
                r["todo"] = None
                continue
            if r["dry"]:
                temp, left, seen, auto = r["dry"]
                r["dry"] = None
                left -= now - seen
                if not auto and left >= GUARD_DRY_MIN_LEFT and self.stops.get(i, 0) < now:
                    sure = r["lost"] is not None and r["lost"] >= seen - GUARD_DRY_WINDOW
                    r["todo"] = {"temp": temp, "left": left, "at": now, "sure": sure}
            t = r["todo"]
            if t and now - max(t["at"], r["back"] or 0) >= GUARD_SETTLE:
                r["todo"] = None
                left = t["left"] - (now - t["at"])
                if left >= GUARD_DRY_MIN_LEFT:
                    minutes = max(10, min(480, int(-(-left // 60))))
                    out.append(("dry" if t["sure"] else "ask_dry", i, t["temp"], minutes))
        out += self._feed(state, head, now)
        return out

    def _feed(self, state, head, now):
        printing = str(state.get("printer_state") or "").lower() == "printing"
        if not printing or head is None:
            self.fa = {}
            return []
        if state.get("swap_in_progress"):
            return []
        th = next((t for t in state.get("toolheads") or [] if _int_or_none(t.get("idx")) == head), None)
        if not th or not th.get("head_source_known") or th.get("manual") or th.get("feeder"):
            return []
        ace, slot = _int_or_none(th.get("ace")), _int_or_none(th.get("slot"))
        unit = next((a for a in state.get("aces") or [] if _int_or_none(a.get("idx")) == ace), None)
        if ace is None or slot is None or not unit or not unit.get("connected") or not 0 <= slot <= 3:
            return []
        key = (head, ace, slot)
        if _int_or_none(unit.get("feed_assist")) != -1:
            f = self.fa.pop(key, None)
            if f and f["tries"]:
                return [("note", "Poussée revenue sur T%d (ACE %d slot %d)." % (head + 1, ace + 1, slot + 1), "info")]
            return []
        f = self.fa.setdefault(key, {"since": now, "tries": 0, "last": None, "told": False})
        if now - f["since"] < GUARD_FA_LOST or (f["last"] is not None and now - f["last"] < GUARD_FA_RETRY):
            return []
        if f["tries"] >= GUARD_FA_MAX:
            if not f["told"]:
                f["told"] = True
                return [("note", "T%d : la poussée de l'ACE %d ne reprend pas après %d essais. Vérifie l'ACE "
                         "(câble, hub) ; l'impression continue sans aide." % (head + 1, ace + 1, GUARD_FA_MAX), "err")]
            return []
        if _int_or_none(state.get("active_device")) != ace:
            # ACE_ENABLE_FEED_ASSIST agit sur l'ACE actif : sans lui on risquerait de pousser le mauvais.
            if not f["told"]:
                f["told"] = True
                return [("note", "T%d ne reçoit plus de poussée de l'ACE %d, mais ce n'est pas l'ACE actif : "
                         "rien envoyé par sécurité." % (head + 1, ace + 1), "err")]
            return []
        f["tries"] += 1
        f["last"] = now
        return [("fa", ace, slot, head)]


class GuardRunner:
    """Fil de fond du garde-fou : un seul pour tout le plugin."""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self.guard = AceGuard()
        self._asks = {}

    def ensure(self):
        if _STOP.is_set():
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def expect_stop(self, ace):
        with self._lock:
            self.guard.expect_stop(ace, time.monotonic())

    def _loop(self):
        host = None
        while not _STOP.wait(GUARD_POLL):
            try:
                st = load_settings()
                if not st.get("ace_guard", True) or not st.get("host"):
                    with self._lock:
                        self.guard = AceGuard()
                    continue
                if st["host"] != host:
                    host = st["host"]
                    with self._lock:
                        self.guard = AceGuard()
                client = MultiAce(host)
                try:
                    state = client.state(timeout=TIMEOUT_UI)
                except Exception:
                    continue                   # U1 injoignable : on ne conclut rien sur les ACE
                if not isinstance(state, dict):
                    continue
                head = None
                if str(state.get("printer_state") or "").lower() == "printing":
                    head = client.active_head()
                with self._lock:
                    actions = self.guard.step(state, head, time.monotonic())
                for act in actions:
                    self._do(client, act)
            except Exception:
                continue

    def _say(self, text, kind="info", ask=None, notify=False):
        msg = {"command": "guard", "text": text, "kind": kind}
        if ask is not None:
            msg["ask"] = ask
        _PANEL._post(msg)
        if notify:
            try:
                ui = orca.host.ui
                level = getattr(ui.NotificationLevel, "WarningNotificationLevel")
                if ask is not None:
                    _notify(ui, level, text, "Relancer le séchage", lambda a=ask: self.redo_dry(a) or True)
                else:
                    _notify(ui, level, text)
            except Exception:
                pass

    def _do(self, client, act):
        kind = act[0]
        if kind == "note":
            self._say(act[1], act[2], notify=act[2] == "err")
        elif kind == "dry":
            _, ace, temp, minutes = act
            try:
                client.macro("ACE_DRY", {"ACE": ace, "TEMP": temp, "DURATION": minutes}, timeout=60)
                self._say("ACE %d revenu : séchage relancé (%d °C, %d min restantes)." % (ace + 1, temp, minutes),
                          "info", notify=True)
            except Exception as e:
                self._say("ACE %d : relance du séchage impossible (%s)." % (ace + 1, friendly_error(str(e))),
                          "err", notify=True)
        elif kind == "ask_dry":
            _, ace, temp, minutes = act
            with self._lock:
                self._asks[ace] = (temp, minutes, time.monotonic())
            self._say("ACE %d : le séchage s'est arrêté avant la fin (il restait %d min à %d °C). "
                      "Coupure de l'ACE ?" % (ace + 1, minutes, temp), "err", ask=ace, notify=True)
        elif kind == "fa":
            _, ace, slot, head = act
            try:
                client.macro("ACE_ENABLE_FEED_ASSIST", {"INDEX": slot}, timeout=30)
                self._say("T%d : poussée relancée (ACE %d slot %d)." % (head + 1, ace + 1, slot + 1),
                          "info", notify=True)
            except Exception as e:
                self._say("T%d : relance de la poussée impossible (%s)." % (head + 1, friendly_error(str(e))),
                          "err", notify=True)

    def redo_dry(self, ace):
        """Bouton « Relancer le sechage » (panneau ou notification)."""
        ace = _int_or_none(ace)
        with self._lock:
            ask = self._asks.pop(ace, None)
        host = load_settings().get("host")
        if ask is None or not host:
            return
        temp, minutes, at = ask
        minutes = max(10, minutes - int((time.monotonic() - at) // 60))

        def worker():
            self._do(MultiAce(host), ("dry", ace, temp, minutes))

        threading.Thread(target=worker, daemon=True).start()


_GUARD = GuardRunner()


class AcePanel(orca.script.ScriptPluginCapabilityBase):
    """Plugins > "multiACE : panneau ACE" : rouvre le panneau s'il a ete ferme.

    Cette capacite est creee au chargement du plugin : c'est elle qui demarre tout (panneau, garde-fou),
    sans attendre que l'onglet multiACE soit ouvert."""

    def on_load(self):
        start_soon()

    def on_lifecycle_event(self, event, ctx):
        on_app_event(event, ctx)

    def on_unload(self):
        plugin_shutdown()

    def get_name(self):
        return "multiACE : panneau ACE"

    def execute(self):
        try:
            return _ok(_PANEL.open(force=True))
        except Exception as e:
            return _skip("Ouverture du panneau impossible : %s" % e)


PIPELINE_NAME = "multiACE : envoyer au Preflight"
_pipeline_lock = threading.Lock()


def _parse_strings(value):
    value = (value or "").strip()
    if not value:
        return []
    quoted = re.findall(r'"((?:[^"\\]|\\.)*)"', value)
    return quoted if quoted else [v.strip() for v in value.split(";") if v.strip()]


_PIPE = {"t": 0.0, "status": None, "added": set()}
PIPE_EVERY = 10.0           # secondes entre deux controles du profil de traitement


def _ran_path():
    return os.path.join(os.path.dirname(_settings_path()), "pipeline_ran.json")


def note_pipeline_ran():
    """Note quelle copie du plugin a execute l'etape (dossier partage par toutes les copies)."""
    try:
        with open(_ran_path(), "w", encoding="utf-8") as f:
            json.dump({"version": VERSION, "storage": storage_dir(), "at": time.time()}, f)
    except (OSError, RuntimeError):
        pass


def pipeline_status(force=False):
    """Controle (et ajout si besoin) de l'etape « multiACE : envoyer au Preflight » dans le profil de
    traitement actif, quand l'imprimante est une U1. L'ajout passe par l'API d'OrcaSlicer, comme une
    modification faite a la main : le profil devient « modifie », a enregistrer par l'utilisateur.
    Appele hors du fil de l'interface (begin_update bloque le fil appelant)."""
    now = time.monotonic()
    if not force and _PIPE["status"] is not None and now - _PIPE["t"] < PIPE_EVERY:
        return _PIPE["status"]
    if not _pipeline_lock.acquire(blocking=False):
        return _PIPE["status"]
    st = {"state": "unknown"}
    try:
        _PIPE["t"] = now
        bundle = orca.host.preset_bundle()
        model = bundle.current_printer_preset().config_value("printer_model") or ""
        if "U1" not in model:
            st = {"state": "not_u1"}
        else:
            proc = bundle.prints.edited_preset()
            name = proc.label() if hasattr(proc, "label") else ""
            current = _parse_strings(proc.config_value("slicing_pipeline_plugin"))
            if PIPELINE_NAME in current:
                st = {"state": "present", "preset": name}
            elif not load_settings().get("auto_pipeline", True):
                st = {"state": "missing", "preset": name}
            else:
                tx = orca.host.preset.process.begin_update()
                tx.set("slicing_pipeline_plugin", ";".join('"%s"' % v.replace('"', '') for v in current + [PIPELINE_NAME]))
                res = tx.commit()
                name = getattr(res, "target_name", "") or name
                st = {"state": "added", "preset": name}
                _PIPE["added"].add(name)
    except Exception as e:
        st = {"state": "error", "error": str(e)[:160]}
    finally:
        _pipeline_lock.release()
    try:
        with open(_ran_path(), "r", encoding="utf-8") as f:
            ran = json.load(f)
        if isinstance(ran, dict):
            st["ran_version"] = str(ran.get("version") or "")
            try:
                st["ran_here"] = os.path.normcase(str(ran.get("storage") or "")) == os.path.normcase(storage_dir())
            except RuntimeError:
                pass
    except (OSError, ValueError):
        pass
    st["version"] = VERSION
    _PIPE["status"] = st
    return st


def ensure_pipeline_async(delay=2.0):
    """Controle de l'etape Preflight en arriere-plan (demarrage, projet ouvert...)."""
    def worker():
        time.sleep(delay)
        pipeline_status(force=True)
    threading.Thread(target=worker, daemon=True).start()


def on_app_event(event, ctx):
    """Evenements d'OrcaSlicer (recus par l'onglet et par le panneau, sans doublon d'effet)."""
    names = ("PresetSelected", "ProjectOpened", "NewProject", "PlateSelected", "DeviceSelected")
    if any(event == getattr(orca.LifecycleEvent, n, object()) for n in names):
        auto_open_panel()
    # OrcaSlicer 2.5 n'envoie pas PresetSelected : le profil est aussi controle par le panneau (toutes les 10 s).
    if any(event == getattr(orca.LifecycleEvent, n, object()) for n in ("PresetSelected", "ProjectOpened", "NewProject", "PresetSaved")):
        ensure_pipeline_async()
    if event == getattr(orca.LifecycleEvent, "GCodeExportFinished", object()):
        try:
            _POPUP.show_pending()
        except Exception:
            pass


def start_soon():
    """Au chargement : l'adresse vient des reglages ou du profil imprimante (hote d'impression) ;
    on ouvre le panneau et on lance le garde-fou sans attendre l'onglet multiACE."""
    try:
        effective_host()
    except Exception:
        pass
    try:
        auto_open_panel()
    except Exception:
        pass
    ensure_pipeline_async(delay=4.0)


def auto_open_panel():
    """Ouverture automatique (une fois par session), sauf si l'utilisateur l'a desactivee ou fermee."""
    if _PANEL.panel is not None or _PANEL.closed_by_user:
        return
    if not load_settings().get("auto_panel", True):
        return
    try:
        _PANEL.open()
    except Exception:
        pass
    _GUARD.ensure()
    ensure_pipeline_async()


# --------------------------------------------------------------------------- script

class ResendLast(orca.script.ScriptPluginCapabilityBase):
    def on_unload(self):
        plugin_shutdown()

    def get_name(self):
        return "multiACE : renvoyer le dernier G-code"

    def execute(self):
        info = last_gcode_info()
        gcode_path, _ = last_gcode_paths()
        if not info or not os.path.exists(gcode_path):
            return _skip("Aucun G-code garde pour l'instant.")
        host = load_settings()["host"]
        try:
            MultiAce(host).send_gcode(gcode_path, info.get("name"))
        except PermissionError:
            return _skip(permission_text(host))
        except Exception as e:
            return _skip("Envoi impossible : %s" % e)
        return _ok("\"%s\" envoye au Preflight de %s." % (info.get("name"), host))


# --------------------------------------------------------------------------- enregistrement

@orca.plugin
class MultiAceBridge(orca.base):
    def register_capabilities(self):
        grants = {"threading": True}
        network = []
        host = ""
        try:
            host = load_settings()["host"]
        except Exception:
            host = ""
        if not host:
            # Pendant le chargement, le stockage du plugin n'est pas toujours disponible : on relit
            # les reglages a cote du dossier orca_plugins (<data_dir>/multiace_bridge/settings.json).
            try:
                parts = os.path.abspath(__file__).replace("\\", "/").split("/")
                if "orca_plugins" in parts:
                    base = "/".join(parts[: parts.index("orca_plugins")])
                    with open(os.path.join(base, "multiace_bridge", "settings.json"), encoding="utf-8") as f:
                        host = normalize_host(json.load(f).get("host") or "")
            except Exception:
                host = ""
        if host:
            network.append(origin_of(host))
        # network= : autorisation pour toute l'adresse (tous chemins et ports), demandee une fois.
        for kw in ("network", "network_http"):
            try:
                orca.request_permissions(**grants, **{kw: network})
                break
            except TypeError:
                continue
        else:
            orca.request_permissions(**grants)
        orca.register_capability(MultiAcePage)
        orca.register_capability(SendToPreflight)
        orca.register_capability(ResendLast)
        orca.register_capability(AcePanel)
