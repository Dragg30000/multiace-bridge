# multiACE Bridge : journal des mises à jour

Plugin OrcaSlicer 2.5 pour Snapmaker U1 + multiACE (1 à 4 ACE).
Fichier à installer : `multiace_bridge_any.py` (Fichier → Plugins → désinstaller l'ancien → *Install local plugin* → redémarrer Orca).
Toutes les versions précédentes sont dans `versions\` : pour revenir en arrière, installe l'une d'elles à la place.

## 0.46.3 (27/11/2026)
- **Correctif : envoi annulé à tort, « le fichier préparé n'a pas la marque multiACE ».** Avant d'envoyer, le plugin vérifie que le fichier préparé porte la marque de multiACE. Il ne la cherchait que dans les 64 premiers Ko du fichier. Or multiACE l'écrit juste avant la 1re couche, après les vignettes d'aperçu et le G-code de démarrage. Avec un aperçu lourd (modèle détaillé, beaucoup de couleurs), elle tombait plus loin, et la fenêtre annulait l'envoi d'un fichier pourtant bon. Le plugin la cherche maintenant dans le 1er Mo (multiACE lui-même lit 512 Ko). Rien d'autre ne change.
  - Avec la 0.46.2, pour contourner : menu ⋯ → « Ouvrir dans le Preflight multiACE ».
- Tests : 27 suites OK avec le code de multiACE 1.91. Nouvelle : marque_test (vrai export de la U1 avec un aperçu plus lourd, préparé par le vrai code multiACE : marque à 93 Ko, puis à 411 Ko).

## 0.46.2 (27/11/2026)
- **multiACE+ 1.91 : options « Au départ » envoyées avant l'impression.** Depuis multiACE 1.90.2, le Preflight de la U1 ne met plus la calibration du plateau, la calibration du flux (PA) et le time-lapse en ligne dans le fichier : une impression en cours ne peut plus les changer (avec le firmware 2.0 de la U1, elle était annulée, erreur 531). Il met une marque en tête du fichier. Pour « Imprimer », le plugin envoie maintenant ces options à la U1 juste avant de lancer l'impression, comme le Preflight web de multiACE. Sans cela, elles n'étaient plus appliquées avec multiACE 1.90.2 et 1.91.
  - Si la U1 les refuse, l'impression n'est pas lancée et la fenêtre dit pourquoi.
  - « Envoyer sans lancer » dit de les choisir sur l'écran de la U1 au lancement, ou de passer par « Mettre en file multiACE ».
  - Rien ne change avec multiACE 1.90.1 et avant.
- Tests : 26 suites OK avec le code de multiACE 1.91 et avec celui de la 1.90.1. Le plugin est vérifié avec le code de chaque version de multiACE, de 1.25b à 1.91.

## 0.46.1 (26/11/2026)
- **Aperçu plus vif.** Dans la fenêtre d'impression, la vignette repeinte aux couleurs des bobines est plus proche des bobines. Un projet noir, gris ou blanc repeint d'une couleur n'est plus terne : leur clarté est mesurée sur la vignette (le noir d'Orca n'est pas une ombre). Les couleurs sont rendues avec moins de blanc que la vignette d'Orca. Quand aucune couleur ne change, la vignette d'origine reste affichée.
- Tests : 26 suites OK.

## 0.46.0 (25/11/2026, publiée avec la 0.46.1)
- **Séchage auto selon l'humidité (ACE 2 Pro).** Le séchage auto de multiACE (déjà dans la 1.90) se règle depuis le panneau. Visible seulement si un ACE 2 Pro est détecté ; sans lui, rien ne change. Un bouton « Auto » sous « Sécher » ouvre les réglages de chaque ACE :
  - ACE 2 Pro : il démarre au-dessus d'un taux d'humidité, s'arrête sous un autre, à la température choisie. Les seuils qui se croisent ne sont pas proposés.
  - ACE Pro : il n'a pas de capteur. Il suit l'humidité de l'ACE 2 Pro choisi, à sa propre température, et continue de 0 min à 4 h après lui.
  Chaque changement part tout de suite, aussi pendant une impression. C'est multiACE qui sèche, sur la U1, même OrcaSlicer fermé ; par défaut pas pendant une impression. Un cycle du séchage auto est marqué « Auto » dans la colonne de l'ACE.
- **Décharger à la fin.** Nouvelle rubrique « À la fin » dans la fenêtre d'impression : aucune tête (par défaut), toutes, ou une seule. Seules les têtes du plan affiché alimentées par un ACE sont proposées. Juste après le PRINT_END du fichier, le plugin ajoute le déchargement de multiACE (`ACE_UNLOAD_HEAD`, comme le bouton « Décharger » du panneau) : homing XY si besoin, chauffe, filament renvoyé dans l'ACE, chauffe coupée. Une tête déjà vide est sautée ; le message d'envoi dit quelles têtes seront déchargées. Le réglage « décharger à la fin » de la U1 n'est pas utilisé : il ne fait rien pour une impression lancée par multiACE, la U1 n'apprenant les têtes utilisées que par son écran de lancement.
- Panneau : les traits des voies passent sous les rangées ouvertes (séchage, séchage auto) au lieu de barrer leur texte.
- Tests : 26 suites OK. Nouvelles : autodry_test (ACE 2 Pro simulé) et decharge_test (fichier préparé par le vrai code multiACE), en français et en anglais.

## 0.45.0 (25/11/2026, publiée avec la 0.46.1)
- **Aperçu aux couleurs de tes bobines.** En haut de la fenêtre « Preflight de la U1 », la vignette du G-code (agrandie : 120 px) est repeinte avec les couleurs des bobines du plan affiché. Elle suit le plan choisi et les bobines imposées. Un clic remet les couleurs du projet. C'est une approximation (l'image est repeinte, pas recalculée en 3D) ; rien ne change dans le fichier.
- **Filament restant.** Pour le plan affiché, les grammes de chaque couleur sont comparés, par bobine, au poids restant noté dans la table des bobines multiACE : « Pas assez de filament : ACE 2, voie 4 (Noir) a encore 41 g, il en faut environ 56 g (filament 1). » Moins de 10 % de marge : « Filament juste ». Poids inconnu : rien.
- **Réglages de l'imprimante**, sous « Au départ », avec leur état lu sur la U1 : Air-Print Detection et Quad Replenish (multiACE 1.90+), auto-refill de la U1, lumière éteinte à la fin, détection des spaghettis et des objets sur le plateau par la caméra, avec leur sensibilité (basse ou haute). Un clic les enregistre sur la U1, comme sur son écran. Un réglage que la U1 ne connaît pas n'est pas affiché.
- Idées vues dans le plugin multiACE+ de decay71 (test interne pour multiACE+ 1.95) ; ici, elles marchent avec multiACE+ 1.90.
- Tests : 24 suites OK. Nouvelle : envoi_test (aperçu identique à la référence Python, alerte filament, réglages, français et anglais).

## 0.44.0 (23/11/2026)
- **Séchage jusqu'à 7 jours** (avant : 8 h au plus). Durées : 1, 2, 4, 6, 8 et 12 h, puis 1, 2, 3, 5 et 7 jours.
  - Une commande de séchage dure 10 h au plus (le maximum de l'interface web de multiACE). Au-delà, l'ACE sèche par cycles de 10 h : le plugin lance le cycle suivant à la fin du précédent, avec la même commande ACE_DRY qu'avant, aussi pendant une impression.
  - Le bandeau de l'ACE affiche le temps restant au total (« 50 °C, 2 j 14 h ») et une barre sur toute la durée. Au survol : la durée choisie. Entre deux cycles : « démarrage… ». File d'attente : « Séchage ACE 1 (50 °C, 3 j par cycles de 10 h) ».
  - « Arrêter » arrête tout : le cycle en cours, les cycles suivants, et un séchage de cet ACE encore dans la file.
  - Séchage arrêté ailleurs avant la fin d'un cycle (écran de la U1, interface web multiACE) : pas relancé tout seul. Le panneau le dit avec « Relancer le séchage » ; le bandeau affiche « En pause », « Relancer » et « Arrêter ».
  - ACE déconnecté puis revenu : le cycle suivant repart tout seul. Durée atteinte : « séchage terminé », aussi en notification d'Orca.
  - Ce sont les relances d'OrcaSlicer : il doit rester ouvert. Fermé, l'ACE finit son cycle puis s'arrête. Le plan est enregistré (`dry_plan.json`, à côté des réglages) : à la réouverture d'Orca, le séchage reprend s'il n'est pas fini. Marche aussi case « Garde-fou » décochée.
- Tests : 23 suites OK. Nouvelle : dry_test (cycles, fausse U1 avec la vraie file et le vrai fil du garde-fou, panneau en français et en anglais).

## 0.43.1 (23/11/2026)
- **Mode tête dans la fenêtre « Preflight de la U1 ».** En mode tête (un ACE par tête, combineur 4→1), et en mode multi avec les copies de couleur, une tête alimentée à la main ou les changements en arrière-plan (ace2k), le Preflight de la U1 répond par un rapport « par tête ». La fenêtre le montre maintenant :
  - **Carte** : en mode tête, une colonne par tête, avec les 4 voies de son ACE ou son chargeur latéral. ACE non connecté signalé. En mode multi, la carte des voies habituelle, copies marquées « copie ».
  - **Plans de la U1** : « Comme chargé », « Optimisé », « Par couche », « Moins de mélange ». Durée, échanges, purge, rubans, et les **changements en arrière-plan** (« 14 sur 14, ~21 min gagnées », et pourquoi les autres ne le sont pas).
  - **Plans proposés** : la U1 les calcule sans regarder les bobines en place. La fenêtre donne les gestes (déplacer, poser, charger un chargeur latéral) avec « Placer pas à pas ». Le lancement attend que les bobines soient en place, vérifié avec le rapprochement de couleurs de la U1.
  - **Choisir les bobines moi-même** (plan « Comme chargé ») : une voie ou un chargeur de la matière du filament. Durée, échanges, arrière-plan et copies recalculés par le code de la U1.
  - **Envoi** : le fichier est réécrit par le code de la U1 en mode « head », identique octet pour octet à celui du Preflight web de multiACE pour le même choix. File multiACE en mode « head ».
  - Nouveau, **pas encore essayé sur une vraie U1 câblée en mode tête** : en cas de doute, « Ouvrir dans le Preflight multiACE » (menu ⋯).
- **Plusieurs bobines pareilles** (plusieurs rouges) : dans « Modifier », une bobine de la table multiACE déjà posée dans une autre voie occupée est proposée avec « Une bobine pareille sera créée pour cette voie ». Choisie, elle donne une **nouvelle bobine de la table**, pareille (marque, matière, type, couleur, nom, densité), avec son **PA mémorisé**. L'originale ne bouge pas. Avant : refusé.
- Interface anglaise : trois phrases du placement pas à pas restaient en français.
- Nouvelle bannière avec la nouvelle interface.
- Tests : 22 suites OK. Nouvelles : head_test (mode tête, copies, tête à la main ; fichier identique au Preflight web), copie_test.
- Versions 0.42.1 et 0.43.0 : internes, regroupées dans la 0.43.1.

## 0.42.0 (22/11/2026)
- **Nouvelle interface** du panneau et de la fenêtre « Preflight de la U1 ». Polices intégrées : rien n'est téléchargé.
  - **Carte des voies**, la même avec 1 à 4 ACE en mode multi : les 4 têtes en haut, une ligne par ACE. Trait plein : bobine chargée dans la tête. Pointillé de couleur : chargement prévu par la file. Losange orange : chemin pas encore calibré dans multiACE.
  - Clic sur une bobine ou une tête : charger, échanger, décharger, calibrer le débit, modifier. Séchage dans la bande de chaque ACE. File d'actions avec une barre de la couleur du filament.
  - Fenêtre : les plans dans un tableau (durée, échanges, purge, écart avec « Comme tranché »), un ruban par tête (chaque changement de couleur est un échange de bobine), la carte des bobines du plan, « Au départ » à côté du lancement, autres actions dans le menu « ⋯ ».
  - Mode tête (une ACE par tête) : rendu en liste gardé.
- **Placer pas à pas** : un geste à la fois, avec une flèche sur la carte. Si la bobine du geste alimente une tête chargée : bouton « Décharger Tn » (file du panneau, jamais pendant une impression).
- **Couleurs différentes du projet** : avertissement en haut de la fenêtre (« Rouge (filament 3) sera imprimé en Marron (ACE 2, voie 1) »), nombre sous chaque plan, repère « ! » et « remplace Rouge » sur la carte, rappel près du lancement. Rien n'est bloqué.
  - Une bobine que multiACE rapproche par son nom de couleur approché est aussi signalée (un violet que multiACE appelle « Blue »).
  - Quand le plan « Optimisé » donne les bonnes couleurs, l'avertissement propose « Choisir le plan Optimisé ». Ce plan ne réutilise plus une bobine d'une autre couleur : il demande de poser la bonne.
  - Sinon, l'avertissement dit quoi poser et où : une voie vide qui débloque une tête, les autres voies vides, à la place d'une bobine non identifiée, d'une bobine pas utilisée, ou d'une bobine qui ne fait que remplacer une couleur. Un ACE que la U1 ne compte pas est signalé. Bouton « Recharger ».
- **« Optimisé » impossible parce qu'une tête n'a aucune bobine de la matière dans sa voie** : le plugin redemande au code de la U1 sa proposition de disposition, comme pour « impossible avec les bobines chargées » (0.38.0).
- **Tête vide au départ** : la fenêtre la signale avec un bouton « Charger Tn depuis ACE x, voie y » (file du panneau). Essai réel : avec T4 vide, la U1 s'est arrêtée au tout début (erreur 523, séquence de départ de la U1) avant que multiACE ne charge la tête.
- **Éditeur de bobine** : choisir une bobine de la table multiACE notée dans une autre voie qui n'est pas vide est refusé tout de suite, en clair, sans rien enregistrer. Avant : erreur HTTP 400 de multiACE, et la couleur était enregistrée quand même.
- Polices : versions modifiées de Hubot Sans et Mona Sans (GitHub, SIL Open Font License 1.1), réduites au latin et renommées « MB Display » et « MB Text » : voir `OFL.txt`.
- Tests : 20 suites OK. Nouvelles : refonte_ui_test, refonte_window_test, couleurs_test, conseil_test, depart_test. ui_queue_test, mini_test, fold_test et pop_test testaient l'ancienne interface : retirées.

## 0.40.1 (22/11/2026)
- **En haut du panneau : le nom donné à la U1**, lu dans l'imprimante (le même que multiACE affiche en haut de son interface, « … · U1 »). Au survol : nom, firmware de la U1 et imprimante choisie dans Orca. Si la U1 ne donne pas de nom : celui de l'imprimante d'Orca.
- Aperçu de l'animation de lancement : `presentation\animation_lancement.mp4` et `.gif`.

## 0.40.0 (22/11/2026)
- **Animation au lancement de l'impression** : quand tu lances depuis la fenêtre « Preflight de la U1 », la mascotte Mange-3MF mange le G-code (« nom nom », « CRUNCH! »), les bobines sautent, puis « Impression lancée ! Bon appétit, la U1 ! » avec le nom du fichier. 6 s environ, clic pour fermer ; image fixe si Windows est réglé sur « mouvements réduits ». Rien pour « Envoyer sans lancer » ni la file.
- **En haut du panneau : le nom de l'imprimante** sélectionnée dans OrcaSlicer (au lieu de « ACE », déjà dans l'onglet « multiACE »), sur sa propre ligne, sans « (modified) ».

## 0.39.1 (22/11/2026)
- **« Optimisé » : la disposition revient quand les bobines en place n'ont pas les bonnes couleurs.** Avec multiACE 1.90, l'optimiseur peut tout faire tenir dans les bobines chargées en prenant d'autres couleurs (Brown → Rouge, Red → Bleu foncé…). Le plugin compare avec le choix de couleurs de la U1 (plan « Comme tranché ») ; si un filament imprimé tombe sur une autre couleur, il redemande à la U1 sa disposition (bonnes couleurs) et affiche à nouveau les étapes et la « Disposition finale ». La carte rappelle ce que la U1 ferait sans rien déplacer ; pour l'accepter, impose ces bobines.
- Tests : v037_test.py (102 vérifications), 19 tests OK.

## 0.39.0 (22/11/2026)
- **« Optimisé » et « Par couche » avec tes bobines imposées.** Imposer une bobine ne grise plus les autres plans : l'optimiseur de ta U1 les recalcule autour de ton choix. Ton choix lui est donné comme une contrainte de son propre format (le filament imposé ne peut aller que sur la tête de sa bobine, avec la couleur et la matière de cette bobine) ; la U1 décide de tout le reste. Chaque plan affiche ses échanges et sa durée « avec tes choix », ou « impossible avec tes choix ». À l'envoi, la disposition complète passe par le chemin des choix manuels de multiACE (comme « Comme tranché » avec bobines imposées) : test à l'appui, le fichier préparé est identique octet pour octet à celui du plan « Optimisé » de la U1 pour la même disposition. Avec multiACE 1.27b : comme avant (Comme tranché seulement).
- Tests : v037_test.py (82 vérifications), 19 tests OK.

## 0.38.3 (22/11/2026)
- **Bobines imposées : les chiffres suivent tes choix.** Quand tu imposes une bobine, le nombre d'échanges et la durée estimée sont recalculés par le code de ta U1 (le même calcul que son Preflight web quand on modifie la correspondance) : « 140 échanges · avec tes choix ». Avant, ils restaient ceux du plan d'origine (« avant tes choix »). Pendant le calcul : « calcul avec tes choix… ». Le plan « Comme tranché » affiche aussi ces chiffres.
- Tests : v037_test.py (69 vérifications), 19 tests OK.

## 0.38.2 (21/11/2026)
- Interface anglaise : textes restés en français traduits (« attente » / « échec » dans la file, « Aucune » dans le choix de bobine, étape « pose une bobine » de la Disposition finale). Rien d'autre ne change.
- Vidéo démo (anglais, 40 s, carrée) : `presentation\multiACE_Bridge_demo.mp4`.

## 0.38.1 (21/11/2026)
- **« Disposition finale » : couleur qu'aucune bobine chargée n'a.** Premier essai réel (Grinch, filament 5 vert absent des ACE) : le plugin demandait de déplacer la bobine marron (que la U1 n'avait associée que par « même matière, autre couleur ») à la place du vert. Maintenant, seule une bobine dont la U1 a reconnu la couleur est déplacée ; pour une couleur absente, l'étape devient « Retire Bleu de ACE 1 · slot 4, puis pose une bobine Vert PLA (filament 5, pas dans les ACE) dans ACE 1 · slot 4 », avec son « C'est fait » qui donne au slot la couleur et la matière du filament. Le titre l'indique (« en déplaçant 4 bobine(s) et posant 1 bobine(s) hors des ACE ») et la grille marque « à poser ».
- Premier essai réel de la 0.38.0 sur multiACE+ 1.90 : « Optimisé » proposé (33 échanges au lieu de 97, 13 h 24 au lieu de 16 h 20), file multiACE OK (« Loadout matches - ready to launch »).
- Tests : v037_test.py (61 vérifications), 19 tests OK.

## 0.38.0 (21/11/2026)
- **« Optimisé » n'est plus grisé avec multiACE 1.90.** En 1.90, multiACE ne calcule « Optimisé » qu'avec les bobines déjà en place (sinon : « impossible avec les bobines chargées »). Dans ce cas, le plugin redemande au même code de la U1 sa proposition de disposition (son mode « loadout suggestion », celui de la 1.27b). La fenêtre affiche à nouveau la carte « Plan Optimisé : N échanges au lieu de M en déplaçant X bobines », les étapes dans l'ordre avec « C'est fait » et la grille « Disposition finale ». Le lancement attend que les bobines soient en place ; après « Recharger », c'est le plan de la U1 avec tes bobines qui est imprimé. Le plugin n'a toujours aucune logique d'attribution.
- **Le premier export d'une nouvelle copie du plugin ouvrait le Preflight de multiACE** (par exemple après « Install local plugin »). OrcaSlicer refuse l'accès aux fichiers tant que tu n'as pas répondu à sa demande d'autorisation « open » : le plugin attend maintenant ta réponse (3 min au plus) au lieu de partir dans le Preflight de multiACE.
- Tests : v037_test.py (51 vérifications), 19 tests OK.

## 0.37.1
- Version interne, regroupée dans la 0.38.0.

## 0.37.0 (21/11/2026)
- **Filaments 5 et plus (outils virtuels multiACE 1.90).** Carte « Avant de trancher » : nouvelle section « Filaments 5 et plus » qui lit la table « Slicer filament → MMU / Slot » de multiACE (Config), ou sa formule par défaut (filament 5 = MMU 1 slot 1, 9 = MMU 2 slot 1…). Pour chaque filament : slot visé, tête, buse, et si la bobine de ce slot a la bonne couleur (⚠ slot vide, autre couleur, ACE absent). Cette table sert quand le fichier est imprimé tel quel ; avec le Preflight, la U1 réattribue par couleur. Avec multiACE 1.27b (sans outils virtuels) : comme avant.
- **« Disposition finale » : bouton « C'est fait » à chaque étape.** Quand tu as déplacé une bobine à la main, un clic fait suivre son identité dans le nouveau slot : couleur / matière / marque (étiquette du slot, comme le sélecteur de multiACE), l'ancienne étiquette est retirée, la bobine de la table multiACE (poids, PA) est réassociée. Une bobine RFID se relit seule. Refusé si le slot d'arrivée est vide ou pendant une impression. Quand toutes les étapes sont faites, la fenêtre se recharge toute seule.
- **« Mettre dans la file multiACE »** (Print Hub, multiACE 1.90) : le fichier préparé par la U1 est déposé dans sa file au lieu d'être lancé (même chemin que le Preflight de multiACE : dossier `multiace_queue`, puis `/api/queue` avec les slots utilisés et l'estimation). Tu le lances depuis multiACE ; la U1 revérifie les bobines au lancement. Bouton absent si la U1 n'a pas de file.
- **Panneau : « chemin non calibré »** sur chaque slot dont le chemin (Bowden) n'est pas calibré, avec la même règle que multiACE (valeurs enregistrées pour le slot ou son ACE, jamais la valeur globale). Lecture seule de la config ; la calibration se fait dans multiACE → Config → Calibration (le plugin ne la lance pas).
- Format de la file vérifié contre le vrai serveur multiACE 1.90. Nouveau test v037_test.py (43 vérifications) ; 19 tests OK.

## 0.36.1 (21/11/2026)
- Fenêtre « Preflight de la U1 » : la version de multiACE s'affiche (« code multiACE de ta U1 (version 1.90+…) »). Elle était cherchée au mauvais endroit et restait vide ; elle est lue dans `/api/version`, comme l'interface de multiACE (1.27b et 1.90).
- Premier essai réel en multiACE+ 1.90 : impression lancée depuis la fenêtre, estimation de la U1 identique à son Preflight web (42 min), un seul filament affiché, chargement automatique de T1 confirmé.
- Tests : u1full_test.py (50 vérifications). 18 tests OK.

## 0.36.0 (21/11/2026)
- **Estimation de temps de la U1** (multiACE+ 1.90) dans la fenêtre « Preflight de la U1 » : durée totale de chaque plan à côté de son nom (« ≈ 20 h 42 »), et un compteur « durée estimée par la U1 · dont 9 h 32 d'échanges · purge 47 g ». C'est le calcul de multiACE, appris sur la durée réelle de tes échanges. Rien n'est affiché avec multiACE 1.27b, qui ne le fournit pas.
- **Buses Haut débit / Standard lues dans les données de multiACE** (1.90 : envoyées avec le chargement) : l'alerte des buses utilise la même source que multiACE. Sinon, comme avant : lues dans la U1, puis le réglage « Ma U1 ».
- **Plans impossibles expliqués en clair** : « impossible avec les bobines chargées », « aucune répartition par couche possible », « plus de 4 couleurs dans une couche »… au lieu du message anglais de multiACE.
- Tests : u1full_test.py (49 vérifications). 18 tests OK avec multiACE 1.90 et 1.27b.

## 0.35.7 (21/11/2026)
- **Compatible multiACE+ 1.90** (sortie le 21/11/2026), toujours compatible 1.27b. Vérifié sur le vrai code des deux versions : le Preflight de la U1 (rapport, fichier préparé, bobines imposées, options au lancement), les commandes du panneau (charger, échanger, décharger, sécher, calibrer, éditer une bobine) et leurs paramètres sont identiques.
- multiACE 1.90 répond `{"klippy": "disconnected"}` pendant un redémarrage de Klipper : le panneau affiche « Klipper n'est pas prêt… » et le garde-fou n'en conclut rien sur les ACE (avant, un état sans ACE aurait pu être pris pour une déconnexion).
- Tests : les 18 tests passent avec multiACE 1.90 et 1.27b ; u1full_test.py (46 vérifications).

## 0.35.6 (21/11/2026)
- **Fenêtre « Preflight de la U1 » : seuls les filaments vraiment imprimés sont affichés.** Le code multiACE analyse tous les filaments déclarés dans le projet Orca, même ceux qui ne servent pas (exemple : un projet à 7 filaments où une seule couleur est imprimée). Ils n'apparaissent plus dans le tableau, le choix des bobines, les alertes de buse, les têtes chargées au départ, le PA par tête ni la disposition finale. Une ligne indique combien sont masqués. Filament utilisé = poids > 0 ou outil appelé dans le G-code. Rien ne change dans le calcul de la U1.
- Tests : u1full_test.py (44 vérifications). 18 tests OK.

## 0.35.5 (21/11/2026)
- **Interface en anglais.** Nouveau choix dans ⚙ Options : « Langue / Language » = Auto (Windows), Français ou English. En automatique, le plugin suit la langue de Windows (français si Windows est en français, anglais sinon). OrcaSlicer ne donne pas sa langue aux plugins, d'où ce choix.
  - Tout est traduit à l'affichage : panneau, options, fenêtre « Preflight de la U1 », fenêtre multiACE, messages, notifications d'Orca et résultats des étapes. Les valeurs (bobines, couleurs, buses Haut débit / Standard…) restent les mêmes en interne : rien ne change dans ce qui est envoyé à la U1.
  - Le nom de l'étape « multiACE : envoyer au Preflight » n'est jamais traduit (c'est son identifiant dans les profils).
  - Après un changement de langue : ferme et rouvre le panneau, ou redémarre OrcaSlicer.
- Tests : u1full_test.py (41 vérifications, dont la langue), harness. 18 tests OK.

## 0.35.4 (21/11/2026)
- **Étape « multiACE : envoyer au Preflight » ajoutée toute seule au profil de traitement** quand l'imprimante est une U1 (au démarrage, à l'ouverture d'un projet, puis contrôlée par le panneau toutes les 10 s). L'ancienne version attendait un événement « profil choisi » qu'OrcaSlicer 2.5 n'envoie jamais : elle ne s'ajoutait donc jamais. Les autres plugins du profil sont gardés ; les profils d'une autre imprimante (P1S…) ne sont jamais touchés. OrcaSlicer ne permet pas à un plugin d'enregistrer un profil : il passe en « modifié », enregistre-le (disquette) pour garder l'étape. Option ⚙ « Ajouter l'étape Preflight aux profils de la U1 ».
- **Bonne copie du plugin** : ⚙ Options affiche « ✓ Étape Preflight présente dans « profil » » et « Dernier export préparé par cette copie (vX) », ou ⚠ si le dernier export est passé par une autre copie (copie locale + copie Orca Cloud).
- **Bobines du panneau** : un 2e clic sur une bobine la replie (plus besoin de « Annuler »).
- **Chargement automatique au départ** vérifié dans le fichier préparé : le message après l'envoi dit quelles têtes seront chargées avant la 1re couche, ou prévient s'il n'y a pas de chargement automatique. Rappel dans « Au lancement ».
- Tests : u1full_test.py (35 vérifications), ui_queue_test (repli au 2e clic), harness. 18 tests OK.

## 0.35.3 (20/11/2026)
- **Plans « Optimisé » et « Par couche » : schéma « Disposition finale » de retour.** Avec multiACE 1.27b, ces plans ne partent pas des bobines chargées : ils proposent une nouvelle disposition (correspondance « disposition proposée »). La fenêtre l'affichait comme si les bobines y étaient déjà. Maintenant :
  - carte « Plan : N échanges au lieu de M en déplaçant X bobine(s) », avec les étapes **dans l'ordre** (« Retire Marron de ACE 1 · slot 2, puis Jaune : ACE 2 · slot 2 → ACE 1 · slot 2 ») ;
  - grille **Disposition finale** ACE × slot (T1 à T4) : en place, à mettre, libérée, pas utilisée, absente ;
  - « à mettre ici » / « en place » sur chaque ligne du tableau ;
  - **Lancer / Envoyer bloqués** tant que les bobines ne sont pas en place (vérifié aussi côté plugin avant tout envoi) ; bouton « J'ai placé les bobines : recharger ».
  - La bobine de chaque couleur est celle que la U1 associe à cette couleur (plan « Comme tranché ») : aucune logique d'attribution ajoutée.
- Tests : u1full_test.py (28 vérifications). 18 tests OK.

## 0.35.2 (20/11/2026)
- **Premier export de chaque session qui partait dans le Preflight de multiACE** : la vraie cause. Au premier chargement du code de la U1, OrcaSlicer demande l'autorisation « open » (le plugin ouvre des fichiers Python) et, tant que la question est affichée, refuse l'accès au fil d'arrière-plan : le chargement échouait et le plugin croyait le code de la U1 inutilisable. Maintenant il attend ta réponse (jusqu'à 3 min) avec le message « réponds Oui, la préparation continue toute seule », puis continue normalement. Les modules Python utilisés par le plugin sont chargés au démarrage d'Orca.
- Tests : u1full_test.py (25 vérifications, dont l'autorisation en attente). 18 tests OK.

## 0.35.1 (20/11/2026)
- **Premier export qui partait dans le Preflight de multiACE** : quand la U1 imprime, elle peut mettre plus de 8 s à servir son code au premier appel. Le plugin attend maintenant jusqu'à 30 s et refait jusqu'à 3 essais si la U1 ne répond pas à temps (pas si elle répond une erreur), au lieu d'abandonner tout de suite.
- **Liste « Forcer une bobine » refaite comme avant** : bouton avec la pastille de couleur et « Automatique · Marron ACE 1 · slot 2 → T2 · Haut débit » (la bobine choisie par la U1), menu avec une pastille par bobine, la tête, la buse, le poids et l'étiquette rouge « buse ≠ » sur les mauvaises têtes. Échap ou clic à côté ferme le menu.
- **Déplacement doux vers la ligne d'amorce** de retour (option « Au lancement », cochée par défaut) : après le chargement et les calibrations, les déplacements rapides avant la 1re couche passent à 100 mm/s avec une accélération réduite, et la buse remonte de 5 mm avant. Même traitement que la 0.33.
- Tests : u1full_test.py (22 vérifications). 18 tests OK.

## 0.35.0 (20/11/2026)
- **La fenêtre « Preflight de la U1 » reprend l'ancienne fenêtre d'attribution (v0.20)**, en respectant la méthode de decay71 : le calcul reste fait par le code multiACE de la U1, le plugin affiche et applique sans choisir lui-même.
  - En-tête avec la vignette, compteurs (changements d'outil, échanges de bobine, têtes chargées au départ, couleurs), plans de la U1.
  - Tableau Slicer → Bobine → Correspondance : « tranché pour T1 · Haut débit », tête et buse réelle de chaque bobine, poids restant.
  - **Forcer une bobine** : liste des bobines chargées, avec la buse de leur tête. Le choix est passé tel quel au code de la U1 (`remap_override`, le même mécanisme que l'édition manuelle dans le Preflight web de multiACE) ; le plan passe sur « Comme tranché ». Bobine absente ou filament inconnu : envoi refusé. « Revenir au choix de la U1 » annule.
  - **Alerte buse** Haut débit / Standard pour chaque filament du plan affiché (et de tes choix), sans blocage : « ⚠ Filament 2 : tranché pour une buse Haut débit (T2), imprimé sur T3 (Standard) ».
  - **Calibration du flux (PA) au départ** : cases par tête chargée au départ (les têtes décochées gardent leur PA mémorisé) ; pour les filaments qui arrivent en cours d'impression, PA mémorisé sur la bobine pour la buse de la tête et bouton **Calibrer avant** (file d'attente du panneau).
  - **Calibration du plateau sur la zone imprimée** : si le profil palpe tout le plateau (`BED_MESH_CALIBRATE PROBE_COUNT=11,11`), le plugin ajoute `MESH_MIN` / `MESH_MAX` autour des objets et de tout ce qui est extrudé à la 1re couche (tour de purge comprise), marge 5 mm, avec le même écart entre points. Commande Klipper standard, vérifiée dans le firmware de la U1 (Snapmaker/u1-klipper). Si le profil vise déjà une zone, rien ne change.
  - Boutons : Lancer l'impression, **Envoyer sur la U1 sans lancer**, Ouvrir dans le Preflight multiACE, **Recharger**, Fermer.
- Tests : u1full_test.py (19 vérifications : infos du fichier, bobines imposées, refus, maillage zone, flux par tête, envoi sans lancer, Calibrer avant). 18 tests OK.

## 0.34.5 (20/11/2026)
- Options « Au lancement » de retour avec multiACE 1.27b (maillage du plateau, calibration du flux, time-lapse) dans la fenêtre « Preflight de la U1 ». En 1.27b, multiACE ne les met pas dans le code partagé (elles sont dans son serveur) : le plugin reprend à l'identique la fonction de multiACE 1.27b (_prepend_print_prefs, decay71, GPL-3.0), et seulement dans ce cas. Avec une version de multiACE qui fournit prepend_print_prefs, c'est la sienne qui est utilisée.
- Tests : u1code_test vérifie que le résultat est identique, octet pour octet, à la fonction de multiACE 1.27b (3 combinaisons d'options). 17 tests OK.

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
