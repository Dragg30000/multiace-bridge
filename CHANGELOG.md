# multiACE Bridge : journal des mises à jour

Plugin OrcaSlicer 2.5 pour Snapmaker U1 + multiACE (2 ACE).
Fichier à installer : `multiace_bridge_any.py` (Fichier → Plugins → désinstaller l'ancien → *Install local plugin* → redémarrer Orca).
Les versions précédentes sont dans les Releases GitHub.

## 0.34.4 (20/11/2026)
- Préparation avec le code de la U1 : prise en charge de **multiACE 1.27b**. Premier essai sur la vraie U1 : la vérification avait refusé le Preflight de la 1.27b (« parse_meta a changé (with_header) ») et, comme prévu, envoyé le fichier d'origine au Preflight de multiACE. Le plugin s'adapte maintenant à la version de la U1 : il n'exige que les fonctions présentes depuis la 1.27b et n'utilise les nouveautés (en-tête, estimation des échanges, options de lancement) que si le code de la U1 les fournit. Toujours lu sans être exécuté avant de décider.
- Avec multiACE 1.27b, les options « Au lancement » ne font pas partie du code partagé : la fenêtre le signale, la U1 garde ses réglages, et « Ouvrir dans le Preflight multiACE » permet de les choisir. Le plugin n'ajoute rien lui-même.
- Tests : u1code_test.py vérifie aussi le vrai code de multiACE 1.27b (rapport, fichier préparé, aucune option ajoutée). 17 tests OK.

## 0.34.3 (20/11/2026)
- Options déplacées en haut : bouton **⚙** dans la barre du panneau (à côté de ↻). Il ouvre une carte « Options » (adresse de la U1 avec Modifier, homing automatique, garde-fou, préparation de l'export avec le code de la U1), visible même quand les modules sont repliés ou en mode réduit ; ✕ la ferme. Les options ne sont plus cachées dans le module Têtes.
- Tests : host_test et ui_queue_test ouvrent les options par le bouton ⚙. 17 tests OK.

## 0.34.2 (20/11/2026)
- Adresse de la U1 : si le plugin ne la trouve pas (ni dans ses réglages, ni dans l'« hôte d'impression » du profil U1), ou si la U1 ne répond pas à cette adresse, une **boîte « Adresse de la U1 »** apparaît en haut du panneau ACE (aussi en mode réduit) pour la saisir ou la corriger. L'adresse est vérifiée (multiACE doit répondre) avant d'être enregistrée ; Orca peut alors demander l'autorisation réseau.
- Options du panneau : ligne « Adresse de la U1 : … » avec un bouton **Modifier**.
- Messages d'erreur : renvoient vers le panneau ACE (Options → Adresse de la U1) au lieu de l'onglet multiACE.
- Tests : host_test.py (adresse invalide, U1 muette, bonne adresse enregistrée, boîte affichée / fermée / pré-remplie, bouton Modifier). 17 tests OK.

## 0.34.1 (20/11/2026)
- Le plugin démarre **au lancement d'OrcaSlicer**, sans devoir ouvrir l'onglet multiACE : le panneau ACE s'ouvre et le garde-fou se lance dès le chargement (capacité « panneau ACE », `on_load`), puis à chaque événement d'Orca (projet ouvert, préréglage choisi…) si ce n'était pas encore possible. Avant, seul l'onglet multiACE recevait ces événements, et il n'était créé qu'à son ouverture.
- Adresse de la U1 : celle enregistrée dans le plugin, sinon l'« hôte d'impression » du profil imprimante U1, maintenant lue et mémorisée dès le chargement.
- Tests : harness vérifie que le panneau s'ouvre au chargement.

## 0.34.0 (20/11/2026)
- Aligné sur la demande de decay71 (multiACE, issue #243) : **le plugin n'a plus aucune logique d'attribution**. À l'export, il exécute dans Orca **le Preflight fourni par ta U1** (code multiACE de ta version : `/api/preflight/pysrc`, avec le chargement de `/api/preflight/livedata`), exactement ce que lance l'interface web multiACE. Il suit donc toute seule les mises à jour de multiACE.
- **Vérifications avant d'exécuter** : code présent, taille limitée, fonctions et paramètres attendus lus **sans exécuter** le code ; sinon (multiACE trop ancien ou version non reconnue, tête en manuel), rien n'est exécuté et le G-code **original** part dans le Preflight de multiACE (`/api/preflight/inbox`), avec la raison affichée.
- **Vérifications avant d'envoyer** : U1 libre, bobines identiques à celles de l'analyse (sinon nouvelle analyse), fichier préparé marqué par multiACE, uniquement des bobines présentes ; l'export d'origine n'est jamais modifié.
- Nouvelle fenêtre « multiACE - Preflight de la U1 » : plans proposés par multiACE (slicer / optimize / layer, avec échanges de bobine), bobine de chaque filament, préférences de lancement de multiACE (maillage, flux, time-lapse), boutons Imprimer et « Ouvrir dans le Preflight multiACE ».
- Option du panneau : « Préparer l'export avec le code multiACE de la U1 » (cochée). Décochée : le fichier d'origine part toujours dans le Preflight de multiACE, rien n'est exécuté.
- Retirés : l'ancienne fenêtre d'attribution, le moteur 1.27b embarqué (`multiace_engine_127.py`), le plan de placement maison, le choix de bobine forcé, le blocage sur les buses et le déplacement doux (le début du G-code est maintenant préparé par multiACE).
- De nouveau **un seul fichier** : `multiace_bridge_any.py` (désinstaller le .whl de la 0.33.0). Réglages conservés.
- Tests : u1code_test.py (vraies sources multiACE servies par une fausse U1 : plans, fichier préparé, refus si bobines changées, code absent ou modifié, tête manuelle, fichier déjà traité, repli vers le Preflight) ; security_test vérifie qu'aucun code n'est caché et que la vérification passe avant l'exécution. 16 tests OK.

## 0.33.0 (20/11/2026)
- Version prête pour Orca Cloud : le plugin est maintenant livré en **paquet .whl** (`multiace_bridge-0.33.0-py3-none-any.whl`), à installer à la place de `multiace_bridge_any.py` (désinstaller l'ancien, *Install local plugin*, choisir le .whl, redémarrer Orca). Réglages conservés.
- Moteur multiACE 1.27b de decay71 : fichier **lisible** `multiace_engine_127.py`, repris tel quel (plus de version compressée dans le plugin). Le test vérifie qu'il est identique à l'original.
- Option « Utiliser le moteur multiACE de la U1 » **retirée** : le plugin ne télécharge ni n'exécute plus aucun code venu du réseau (c'est ce qui classait le plugin « High risk » sur Orca Cloud). Aucun changement sur les impressions avec multiACE 1.27b : c'est le même moteur.
- Description du plugin : « Interface pour multiACE de decay71 ». En-tête du fichier simplifié.
- Tests : engine_test.py réécrit (moteur livré seulement, identique à l'original, plus aucun code réseau exécuté) ; run_all.py trouve le moteur à côté du plugin.

## 0.32.0 (20/11/2026)
- Caméra de la U1 dans le panneau : bouton 📷 dans la barre du haut (masquée → en haut → en bas, comme ▣ pour l'écran). Image fixe de la webcam « case » de la U1 (/webcam/snapshot.jpg, vérifié sur la vraie U1 : 1920 × 1080), rafraîchie chaque seconde, avec une étiquette « LIVE ». Visible aussi en mode réduit. Masquée : aucune requête. Choix mémorisé (réglage « camera »). Si la caméra ne répond pas : « Caméra indisponible pour le moment ».
- Tests : cam_test.py (fausse U1 avec caméra : cycle du bouton, rafraîchissement, mode réduit, caméra absente), ajouté à run_all.py ; harness.py et pop_test.py connaissent le réglage camera.

## 0.31.0 (20/11/2026)
- Température de chaque ACE (🌡, donnée « temp » de multiACE) affichée à côté de l'humidité (💧) : en-tête du module ACE (déplié et replié), mode réduit et menu d'un ACE. Pas de pastille si multiACE ne donne pas la température.
- Tests : pop_test.py vérifie la température et l'humidité aux quatre endroits.

## 0.30.0 (20/11/2026)
- Modules repliables un par un : « Avant de trancher », « Têtes » et chaque ACE ont un en-tête cliquable (flèche ▾ / ▸). Replié, le module garde une rangée de pastilles de couleur dans son en-tête (têtes ou bobines de l'ACE, 🔥 si l'ACE sèche) ; « Tout décharger » reste accessible. L'état replié de chaque module est mémorisé (réglage « folds », clés et valeurs vérifiées côté plugin).
- Actions au clic en petit : dans le mode réduit et sur les pastilles des modules repliés, un clic ouvre un petit menu :
  - tête : « Décharger Tn » ;
  - bobine : « Charger / Échanger → Tn » (ou « Décharger » si elle est sur une tête) et « Modifier couleur / matière / poids… » (ouvre le panneau complet sur son éditeur) ;
  - nom d'un ACE : « Sécher 45 °C · 4 h » ou « Arrêter le séchage ».
  Mêmes règles que le panneau complet : double clic pour confirmer, file d'attente, boutons bloqués pendant une impression. Le menu se ferme après l'action, sur Échap ou en cliquant ailleurs.
- Carte « Avant de trancher » : titre unique (plus de répétition dans le texte).
- Tests : fold_test.py et pop_test.py, ajoutés à run_all.py.

## 0.29.0 (20/11/2026)
- Mode réduit (bouton « – ») refait : une rangée « Têtes » (bobine en couleur + T1…T4), puis une rangée par ACE avec ses 4 bobines en couleur (slot vide hachuré, numéro du slot, ou « T2 » en couleur si la bobine est sur une tête), l'humidité en pastille et le séchage en cours (température, temps restant) ; en haut, une ligne « ✓ Buses OK » ou « ⚠ Buses à régler : T2 Standard… ».
- Carte « Avant de trancher » : petit bouton « ↓ en bas » / « ↑ en haut » pour la placer en haut ou sous les ACE ; le choix est mémorisé.
- Tests : mini_test.py (mode réduit, déplacement de la carte), ajouté à run_all.py ; harness.py connaît le réglage prep_pos.

## 0.28.0 (20/11/2026)
- Panneau relooké (aucune fonction changée) :
  - cartes arrondies pour les têtes et pour chaque ACE ;
  - têtes en tuiles 2 × 2 avec une bobine dessinée à la couleur du filament et une teinte de fond assortie ;
  - bobines dessinées dans les ACE, jauge de poids à la couleur de la bobine ;
  - humidité en pastille colorée (vert < 30 %, orange < 45 %, rouge au-delà) ; séchage en cours avec barre de progression ;
  - les 3 cases (homing auto, garde-fou, moteur de la U1) rangées dans « ⚙ Options », replié ;
  - boutons arrondis, titre en dégradé.
- Fenêtre d'attribution : le bloc « Détails du moteur » vide (reste d'une ancienne version) n'apparaît plus ; il ne s'affiche que s'il y a un message du moteur.
- Tests : ui_queue_test.py ouvre « ⚙ Options » avant de cliquer une case ; shot13.py (capture du nouveau panneau).

## 0.27.0 (20/11/2026)
- Choc au démarrage corrigé : après le chargement automatique des têtes, le G-code de démarrage Snapmaker envoie la tête au bord avant du plateau (ligne d'amorce, « G0 X85 Y1 Z2 F18000 », 300 mm/s) ; la tête, qui sort de son support à l'arrière, traversait tout le plateau à pleine vitesse et tapait. Nouvelle option « Déplacement doux vers la ligne d'amorce » (carte « Au lancement », cochée par défaut) : entre la fin du chargement auto (ou du maillage du plateau) et la 1re couche, les déplacements sans extrusion plus rapides que 100 mm/s passent à 100 mm/s, avec une accélération de 3000 mm/s² et la buse remontée de 5 mm avant ; l'accélération d'origine est remise avant la 1re couche. Rien d'autre n'est touché (extrusion, impression). Vérifié sur le vrai fichier du dragon : une seule ligne modifiée.
- Désinstallation / désactivation : OrcaSlicer prévient le plugin (on_unload) ; le garde-fou, la fenêtre d'attribution et le panneau s'arrêtent alors, plus aucun appel réseau (avant, le garde-fou continuait et Orca demandait une autorisation réseau pour un plugin supprimé).
- Tests : softstart_test.py (ralentissement, cas limites, arrêt propre), ajouté à run_all.py.

## 0.26.0 (20/11/2026)
- Buses vissées lues directement dans la U1 : le plugin interroge en lecture seule les têtes (extruder…extruder3 → nozzle_volume_type, même source que multiACE ; disponible sur les firmwares récents). Testé sur la vraie U1 : T1 Haut débit · T2 Haut débit · T3 Standard · T4 Haut débit.
  - « Ma U1 » se remplit tout seul (« lues dans la U1 · Rien à saisir ») ; la saisie manuelle ne sert plus qu'en secours (firmware sans l'info, ou U1 injoignable), tête par tête.
  - Utilisé par la carte « Avant de trancher » et par la fenêtre d'attribution. Valeur gardée 60 s pour ne pas interroger la U1 à chaque actualisation. Une valeur inconnue (ex. hybride) n'est jamais devinée.
- Tests : u1nozzle_test.py (réponse réelle d'une U1, vieux firmware, lecture partielle, U1 injoignable, panneau), ajouté à run_all.py.

## 0.25.0 (20/11/2026)
- Carte « Avant de trancher » simplifiée :
  - quand il y a quelque chose à régler : une grille T1 T2 / T3 T4 disposée comme le bloc « Buse » d'OrcaSlicer, avec seulement les cases à changer en couleur (« T2 STANDARD ← »). On recopie case par case ;
  - quand tout est bon : une seule ligne verte « ✓ buses d'OrcaSlicer OK pour tes bobines » ;
  - « Détail par filament » et « Ma U1 (buses vissées) » sont repliés (leur état ouvert/fermé est gardé entre deux actualisations) ; les alertes importantes (deux filaments sur la même tête, couleur absente des ACE) restent visibles ;
  - premier usage : la carte demande d'abord les buses vissées sur la U1.
- Vérifié : OrcaSlicer ne permet pas au plugin de régler ces buses lui-même (réglage du projet ; le profil imprimante ne les applique qu'au choix de l'imprimante).

## 0.24.0 (20/11/2026)
- Panneau : nouvelle carte « Avant de trancher ». OrcaSlicer considère que le filament N est imprimé par la tête TN, alors qu'en vrai il part sur la tête du slot de sa bobine (slot 3 → T3). La carte :
  - demande une fois les **buses réelles** de la U1 (T1 à T4 : Standard ou Haut débit), mémorisées dans le plugin ;
  - lit dans OrcaSlicer les couleurs des filaments 1 à 4 et les buses réglées, retrouve la bobine de chaque couleur dans les ACE (couleur la plus proche ; à égalité, celle qui ne demande aucun changement) ;
  - affiche pour chaque filament la tête qui l'imprimera vraiment et sa buse, et en haut « À régler dans OrcaSlicer : T2 Standard · T3 Haut débit » (ou « ✓ » si tout correspond), pour que le tranchage corresponde à la réalité ;
  - signale deux filaments sur la même tête (échanges de bobine), une couleur absente des ACE, et les filaments au-delà du 4e (non vérifiés).
  - OrcaSlicer ne permet pas à un plugin de changer ces buses lui-même (réglage du projet, non accessible) : il faut les recopier dans « Imprimante → Buse ».
- Fenêtre d'attribution : quand les buses réelles sont renseignées, les vérifications de buse les utilisent (buse prévue au tranchage = en-tête du G-code, buse réelle = réglage du plugin). L'astuce « inverser les buses dans Orca » ne déclenche donc plus de fausse alerte ni de blocage.
- Tests : prep_test.py (cas réel du dragon, lecture des réglages d'Orca, carte du panneau), ajouté à run_all.py.

## 0.23.0 (20/11/2026)
- Fenêtre d'attribution : type de buse pris en compte comme dans Snapmaker Orca.
  - Ligne « Buses de la U1 : T1 … · T4 … » au-dessus du tableau, avec le rappel que le slot d'une bobine décide de sa tête (slot 3 → T3).
  - Liste « Forcer une bobine » triée : la bonne couleur d'abord (bonne buse puis mauvaise buse), ensuite les autres couleurs. Chaque bobine indique sa tête et sa buse, avec « bonne buse » ou « buse ≠ ».
  - Choix automatique : si la même bobine (couleur + matière) est en double, celle dont la tête a la buse prévue au tranchage est prise.
  - Blocage : un filament de 5 g ou plus qui partirait sur un autre type de buse que celui du tranchage bloque « Lancer l'impression » et « Envoyer sur la U1 ». Une carte rouge explique le risque (sous-extrusion si une buse Standard reçoit un tranchage Haut débit) et comment corriger ; la case « Imprimer quand même avec ces buses » débloque. Le plugin vérifie aussi de son côté : sans la case, l'envoi est refusé.
- Tests : nozzle_test.py (détection, blocage côté plugin, fenêtre dans un navigateur), ajouté à run_all.py.
- Correction : l'en-tête du fichier (version affichée dans la liste des plugins d'OrcaSlicer) était resté à 0.21.0 en 0.22.0 et 0.23.0 ; corrigé, y compris dans versions\multiace_bridge_v0.22.0.py. security_test.py vérifie maintenant que l'en-tête et la version du panneau sont identiques.

## 0.22.0 (20/11/2026)
- Nouveau garde-fou ACE (case « Garde-fou : relancer après une déconnexion d'ACE » dans le panneau, cochée par défaut). Quand un ACE perd sa liaison USB, il redémarre sans sécher ni pousser. Tant qu'OrcaSlicer est ouvert, le plugin surveille l'état multiACE toutes les 2 s :
  - séchage : si un ACE est vu déconnecté puis revenu et que son séchage s'est arrêté, il est relancé 8 s plus tard avec la même température et le temps qu'il restait. Si le séchage s'arrête sans déconnexion visible (coupure trop brève pour être vue), le plugin ne relance pas tout seul : il propose un bouton « Relancer le séchage » (panneau et notification). Jamais de relance après un arrêt demandé depuis le panneau, pour un séchage automatique multiACE, ou s'il restait moins de 3 min ;
  - poussée du filament : pendant une impression uniquement, et uniquement pour la tête qui imprime (lue dans Klipper). multiACE 1.27b relance déjà la poussée après une reconnexion ; le plugin n'intervient que si l'ACE de cette tête ne pousse toujours pas après 12 s : ACE_ENABLE_FEED_ASSIST sur le slot de cette tête, au plus 3 essais espacés d'une minute, puis une alerte. Rien n'est envoyé pendant un échange, pour une tête manuelle, ni si l'ACE concerné n'est pas l'ACE actif (la commande agit sur l'ACE actif : on ne risque pas de pousser le mauvais) ;
  - chaque déconnexion, retour et relance est affiché dans le panneau (et en notification pour les alertes) : utile pour savoir combien de fois ça arrive.
- Tests : guard_test.py (21 cas de décision) et guard_live_test.py (fausse U1 qui simule une coupure d'ACE pendant une impression), ajoutés à run_all.py.

## 0.21.0 (20/11/2026)
- Code nettoyé : suppression de l'ancien générateur de profil 8 têtes et de la mémorisation des filaments associée (plus utilisés), variables mortes retirées ; analyse statique (pyflakes) sans avertissement.
- Sécurité :
  - une seule fonction de nettoyage (gcode_safe) pour toute valeur libre placée dans une commande G-code : caractères de commentaire, guillemets, retours à la ligne et caractères de contrôle retirés, longueur limitée ;
  - poids / températures / numéros reçus des fenêtres bornés (y compris valeurs infinies) ;
  - adresse de la U1 : toute entrée mal formée est refusée proprement ;
  - nom de fichier envoyé à la U1 nettoyé ;
  - moteur de l'imprimante : taille limitée (2 Mo), auto-test, et nouvelle case « Utiliser le moteur multiACE de la U1 » dans le panneau pour ne jamais télécharger de code.
- En-tête du fichier : description à jour et résumé des règles de sécurité ; licence GPL-3.0 indiquée.
- Tests : nouveaux security_test.py et run_all.py (lance toute la suite) ; profile_test.py retiré (fonction supprimée).
- Documentation : guide complet en PDF, français et anglais (dossier docs).

## 0.20.3 (20/11/2026)
- Éditeur de slot : choisir une bobine existante reprend maintenant SA couleur, sa matière, sa marque et son type (avant, seuls les poids étaient repris et le slot gardait son ancienne couleur). La case « appliquer à la bobine » est décochée dans ce cas, pour ne pas écraser la bobine avec l'ancienne couleur du slot.

## 0.20.2 (20/11/2026)
- Fenêtre d'attribution, carte « Au lancement » : pour un filament qui arrive en cours d'impression sans bobine associée à son slot, champ de poids (1000 g par défaut) et bouton « Créer la bobine ». La bobine est créée dans la table multiACE avec la couleur, la matière et la marque du slot, liée au slot ; l'analyse se met à jour et « Calibrer avant » apparaît.
- Plus de sélection de texte en bleu dans cette carte.

## 0.20.1 (20/11/2026)
- Export : quand OrcaSlicer bloque la lecture du G-code exporté (sa demande d'autorisation « open » s'affiche), le message dit maintenant de répondre « Oui » puis de réexporter, au lieu de « copie du G-code impossible ».

## 0.20.0 (20/11/2026)
- Fenêtre d'attribution : nouvelle carte « Au lancement », comme le Preflight multiACE.
  - Calibration du plateau oui / non (maillage sur la zone imprimée, au début du G-code). Non : la U1 garde le maillage précédent (la réactivation forcée par le début du G-code Snapmaker est neutralisée).
  - Calibration du flux (PA) oui / non, avec le choix des têtes mesurées au départ (chaque tête chargée au départ est listée avec sa couleur). La mesure est placée juste après le chargement automatique, quand les têtes sont pleines.
  - Pour les filaments qui n'arrivent qu'en cours d'impression : PA déjà mémorisé sur la bobine affiché, et bouton « Calibrer avant » qui ajoute la calibration de cette bobine à la file du panneau.
  - Time-lapse caméra oui / non.
  - Choix mémorisés pour la fois suivante. Appliqués à « Lancer l'impression » et à « Envoyer sur la U1 sans lancer » (ligne SET_PRINT_PREFERENCES … FORCE=1 en tête du fichier, comme multiACE). Avant, une impression lancée depuis Orca gardait les réglages de la dernière impression faite à l'écran.
- Chargement automatique au départ (déjà présent via le moteur multiACE) : expliqué dans la carte, statistique renommée « tête(s) chargée(s) automatiquement au départ ».

## 0.19.1 (20/11/2026)
- Choix de la bobine dans l'éditeur de slot : liste maison sur fond sombre (le menu Windows affichait du texte blanc sur fond blanc), avec une pastille de couleur, le nom de la couleur en français, le poids et l'endroit où la bobine est déjà montée.
- Les autres menus déroulants du panneau (matière, températures…) sont aussi lisibles.

## 0.19.0 (20/11/2026)
- Bobines sans RFID : dans l'éditeur d'un slot, menu « Bobine » pour l'associer à une bobine de la table multiACE (ACE_SPOOL_ASSIGN), en créer une nouvelle avec son poids (ACE_SPOOL_ADD), ou la détacher. Le poids et la calibration PA sont alors mémorisés sur la bobine.
- Calibration du filament : bouton « Calibrer cette bobine (PA) » dans l'éditeur du slot. Passe par la file : charge d'abord la bobine sur sa tête si besoin, puis mesure le PA (ACE_PA_CALIBRATE FORCE=1, via FLOW_CALIBRATE du firmware). multiACE mémorise la valeur sur la bobine pour cette buse : utilisable plus tard, pas seulement juste avant une impression. L'éditeur affiche le PA déjà mémorisé.
- Calibration du plateau : ligne « Calibration du plateau » sous les têtes (température 55 à 100 °C), lance la macro de la U1 AUTO_BED_MESH_CALIBRATE (chauffe, 2 min d'attente, maillage enregistré par la U1). Passe aussi par la file.
- Les calibrations demandent un homing comme les chargements (automatique si la case est cochée) et sont refusées pendant une impression.

## 0.18.0 (20/11/2026)
- Moteur d'attribution : le plugin utilise désormais le post-processeur INSTALLÉ sur l'imprimante (GET /api/preflight/pysrc, le « contrat plugin » annoncé par decay71 dans decay71/multiACE#243). Il suit donc automatiquement les mises à jour de multiACE.
- Le moteur de l'imprimante passe un auto-test avant d'être utilisé ; si l'imprimante ne le fournit pas (multiACE plus ancien) ou s'il échoue, le plugin garde sa copie intégrée 1.27b.
- La fenêtre d'attribution indique quel moteur a servi (« ⚙ moteur multiACE de l'imprimante… » ou « intégré 1.27b »).
- Brouillon de commentaire pour l'issue #243 : COMMENTAIRE_ISSUE_243.md.

## 0.17.1 (20/11/2026)
- Les boutons du panneau se calculent sur l'état prévu APRÈS la file d'attente : tu peux préparer toute une séquence d'avance (une bobine qui va quitter sa tête retrouve son bouton, celle qui va y aller affiche « prévue sur Tx »).
- Une action déjà prévue n'est plus proposée une deuxième fois.
- Sous chaque tête : « après la file : ACE x · slot y » (ou « vide ») quand la file va la changer.
- Plus de sélection de texte en bleu quand on clique dans la file.

## 0.17.0 (20/11/2026)
- Homing automatique : case « Homing automatique si nécessaire » dans le panneau (rubrique Têtes, décochée par défaut). Cochée, si la U1 n'a pas fait son homing, le plugin le fait tout seul avant de charger / échanger / décharger, sans te demander. Jamais pendant une impression. Le message de fin indique « homing automatique fait avant ».
- Séchage dans la file d'attente : « Sécher » prend sa place dans l'ordre des clics (file vide : il part tout de suite). Toujours autorisé pendant une impression. « Arrêter » le séchage part tout de suite, hors file.

## 0.16.5 (20/11/2026)
- Déchargement : le panneau attend jusqu'à 12 s que le capteur de tête se mette à jour (multiACE le rafraîchit avec du retard) avant de conclure.
- Si le capteur indique encore du filament alors que multiACE a terminé sans erreur, c'est un simple avertissement : la file n'est plus bloquée (constaté sur T3 vide physiquement mais vue « chargée »).

## 0.16.4 (20/11/2026)
- Autorisation réseau corrigée. Orca n'avait enregistré qu'une autorisation pour une seule adresse précise (…/multiace/api/version), pas pour toute la U1 : d'autres appels étaient bloqués (« AUDIT BLOCKED » dans ses journaux). Au prochain démarrage, Orca demande une fois l'accès à toute l'adresse de la U1 : il faut accepter.
- L'adresse de la U1 est relue même quand le stockage du plugin n'est pas encore prêt au démarrage (sinon aucune autorisation n'était demandée).

## 0.16.3 (20/11/2026)
- Homing et envoi « sur la U1 sans lancer » passent maintenant par l'adresse normale de la U1 (port 80), déjà autorisée dans Orca. Avant, ils utilisaient le port 7125 de Moonraker, qu'Orca bloquait (« AUDIT BLOCKED » dans ses journaux) : le homing ne pouvait pas marcher.
- Plus de demande d'autorisation réseau supplémentaire.

## 0.16.2 (20/11/2026)
- File d'attente : si la U1 est « occupée » (busy : échange multiACE, homing ou macro encore en cours), l'action attend qu'elle se libère (jusqu'à 10 min) au lieu d'échouer tout de suite.
- Message d'échec plus clair (en impression, en pause, occupée depuis plus de 10 min…) avec la marche à suivre.
- Numéro de version affiché en bas du panneau ACE, pour vérifier la version chargée par Orca.

## 0.16.1 (20/11/2026)
- File d'attente : les boutons ne se grisent plus pendant un échange multiACE ; tu peux ajouter autant d'actions que tu veux pendant qu'une tourne (seule une impression les bloque).
- Une action de la file attend la fin d'un échange multiACE en cours au lieu d'échouer.
- Double-clic de confirmation : un rafraîchissement du panneau n'annule plus le « Confirmer ? » (c'est ce qui empêchait le séchage de partir). La confirmation s'annule seule après 6 s.
- Boutons de séchage toujours actifs, même pendant un chargement.

## 0.16.0 (20/11/2026)
- File d'attente : charger, échanger et décharger s'enchaînent. Tu peux cliquer plusieurs actions à la suite (double-clic pour confirmer chacune), elles partent dans l'ordre.
- Chaque action est revérifiée au moment de partir : « Charger » devient « Échanger » si la tête est occupée entre-temps, et une action déjà faite est sautée (« Déjà en place », « Déjà vide »).
- Au premier échec, la file se met en pause et rien d'autre ne part. Boutons : Reprendre, Vider la file, ✕ pour retirer une action. « Faire le homing puis reprendre » relance toute la file.
- Le séchage ne passe pas par la file : il part tout de suite, même pendant un chargement.
- Auteur du plugin : « Dragg avec son ami Claude » (plus aucune donnée personnelle dans le plugin, les anciennes versions et les tests).

## 0.15.4 (20/11/2026)
- Homing : avant un chargement, un échange ou un déchargement, le plugin vérifie que la U1 est référencée. Sinon il propose « Faire le homing puis relancer » (G28, puis l'action est relancée toute seule) ou « Homing seul ». Refusé pendant une impression.
- Erreurs lisibles : plus de trace Python de Moonraker dans le panneau, seulement le message en français.
- Déchargement vérifié : si du filament est encore détecté dans une tête après la commande, le panneau le dit au lieu d'afficher « Terminé ».
- Actions affichées en clair (« Échange T1 ← ACE 1 slot 1 », « Séchage ACE 2 (50 °C, 4 h) »…) au lieu des noms de macros.
- Autorisation réseau demandée aussi pour Moonraker (port 7125) au lancement d'Orca : sert au homing et à l'envoi vers la liste des fichiers de la U1.

## 0.15.3 (20/11/2026)
- Filaments mixtes d'Orca 2.5 : ligne « Mélange filament X = … » dans la fenêtre, et alerte si un composant partage sa tête avec un autre filament (sinon : un échange de bobine à chaque couche).
- Un filament mixte ne provoque plus d'erreur « pas de bobine » (il n'est jamais envoyé tel quel à l'imprimante).
- Purge : la table de rinçage n'est plus multipliée deux fois (Orca l'écrit déjà multipliée).
- Purge : si la table n'a pas la taille attendue, on laisse la purge par défaut de multiACE au lieu d'une table mal lue.
- Description du plugin mise à jour dans la liste des plugins d'Orca.
- Kit de test du mélange : dossier `kit_test_melange\`.

## 0.15.2 (19/11/2026)
- Correction : la fenêtre d'attribution ne s'ouvrait plus à l'export (elle était créée pendant l'export, ce qu'Orca refuse). Elle s'ouvre maintenant ~1 s après.

## 0.15.1 (19/11/2026)
- Plan optimal complet : étapes numérotées dans l'ordre (retirer, déplacer, poser à côté si deux bobines échangent leur place) et disposition finale ACE 1 puis ACE 2, slots 1 à 4.
- Purge : lecture correcte des tables de rinçage par buse d'Orca 2.5 (4 tables à la suite, avant lues à tort comme une seule table 10 × 10).
- Vérifié sur un vrai G-code (casse-noisette) : grammes, type de buse, têtes prévues et miniature bien lus.

## 0.15.0 (19/11/2026)
- Fenêtre d'attribution refaite : miniature de l'objet, alertes, grammes nécessaires / restants, type de buse rappelé dans le choix des bobines.
- Suivi en direct : si tu changes une bobine, l'attribution se recalcule sans réexporter ; le plan appliqué est détecté.
- Bouton Imprimer d'Orca redirigé vers la fenêtre d'attribution (l'envoi direct d'Orca est annulé, c'est normal).
- Lancement bloqué tant que la U1 imprime ou si les bobines ont changé depuis l'analyse.
- Purge par paire de couleurs calculée comme le Preflight multiACE (ACE_SET_PURGE, 40 à 150 mm).
- Alertes : filament insuffisant sur une bobine, type de buse différent du tranchage.
- Mode « par couche » retiré.

## 0.14.2
- Suppression automatique de l'ancien profil « Snapmaker U1 multiACE » (8 têtes).

## 0.14.1
- Accès réseau demandé dès le lancement d'Orca ; bouton « Autoriser et réessayer ».
- Réglages gardés hors du dossier du plugin (plus perdus à la réinstallation).

## 0.14.0
- Plan optimal : placement des bobines qui minimise les échanges, bobines en double de même couleur utilisées.
- Ajout automatique du plugin de tranchage au profil de traitement.

## 0.12.0
- Couleurs Orca avec transparence (#RRGGBBAA) correctement lues : plus de pastilles grises.

## 0.11.0
- On reste sur le profil U1 4 têtes ; filaments mémorisés et restaurés au changement de profil.

## 0.10.0
- Choix forcé d'une bobine pour chaque couleur ; noms de couleur en français.

## 0.9.0 / 0.9.1
- Attribution automatique des couleurs aux bobines ACE à l'export, dans une fenêtre par-dessus l'Aperçu.

## 0.8.0
- Écran de la U1 incrusté dans le panneau ; panneau réductible.

## 0.7.0
- Modification de la couleur, matière et poids des bobines depuis le panneau.

## 0.6.x
- Séchage des ACE (aussi pendant une impression) et quantité de filament ; correction du temps restant affiché.

## 0.5.0
- Envoi du G-code exporté vers le Preflight multiACE, avec fenêtre sans quitter l'Aperçu.

## 0.4.x
- Panneau ACE ancré : têtes, bobines, charger / décharger / échanger ; ouverture automatique.

## 0.3.0
- Onglet multiACE : interface web multiACE dans OrcaSlicer.
