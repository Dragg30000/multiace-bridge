"""0.50.0 : barre de progression de l'impression dans le panneau (vrai code multiACE sur une fausse U1, fenêtre et
panneau dans Chrome, en français et en anglais) :
1. la fenêtre envoie avec l'impression la bande du plan (couleur qui imprime à chaque changement d'outil, échanges de
   bobine), gardée par nom de fichier sur la U1, aussi après un redémarrage ;
2. avancement lu sur Moonraker (M73 du fichier, sinon position dans le fichier), couche, temps écoulé ;
3. pause, reprise, arrêt par multiACE (/api/print-control), Moonraker avant multiACE 1.90 ;
4. panneau : bande, repères des échanges, curseur, prochain échange, boutons (arrêt en deux clics), bouton pour
   masquer la barre (réglage gardé)."""
import copy, json, os, random, tempfile, time
exec(open("/home/claude/prive/test/head_scenario.py").read())
from playwright.sync_api import sync_playwright

fails = 0
def check(c_, m):
    global fails
    print(("PASS " if c_ else "FAIL ") + m)
    fails += 0 if c_ else 1
def wait(f, t=20.0):
    end = time.time() + t
    while time.time() < end:
        if f(): return True
        time.sleep(0.05)
    return False

# ---- fausse U1 : Moonraker (avancement, pause / reprise / arrêt) et /api/print-control de multiACE
PR = {"status": {"print_stats": {"state": "standby"}}, "pc": "ok", "posts": []}
_get1, _post1 = H.do_GET, H.do_POST
def do_GET(self):
    if self.path.startswith("/printer/objects/query"):
        PR["q"] = self.path
        return self._j(200, {"result": {"eventtime": 1.0, "status": PR["status"]}})
    return _get1(self)
def do_POST(self):
    if self.path.endswith("/multiace/api/print-control"):
        n = int(self.headers.get("Content-Length") or 0); body = json.loads(self.rfile.read(n) or b"{}")
        PR["posts"].append(("multiace", body.get("verb")))
        if PR["pc"] == "404": return self._j(404, {"detail": "Not Found"})
        if PR["pc"] == "500": return self._j(500, {"detail": "moonraker: Klipper busy"})
        return self._j(200, dict({"ok": True, "verb": body.get("verb")}, **({"queued": True} if PR["pc"] == "queued" else {})))
    if self.path.startswith("/printer/print/"):
        n = int(self.headers.get("Content-Length") or 0); self.rfile.read(n)
        PR["posts"].append(("moonraker", self.path.rsplit("/", 1)[1])); return self._j(200, {"result": "ok"})
    return _post1(self)
H.do_GET, H.do_POST = do_GET, do_POST
MODE["mr"] = {"result": {"item": {"path": "x.gcode", "root": "gcodes"}, "print_started": True, "action": "create_file"}}

# ---------------------------------------------------------------- 1. bande : nettoyage, mémoire par fichier
S1 = {"seg": [[0, "#FFFFFF", 1], [0.5, "#e02020", 2], [0.25, "#111111", 0], [2, "#00ff00", 3], [0.7, "rouge", 1], [0.8, "#123456"]],
      "sw": [[0.5, 1, "#e02020"], [0.3, 7, "#111111"], ["x", 0, "#000000"], [0.9, None, "#abcdef"]]}
c1 = mb.strip_clean(S1)
check(c1 == {"seg": [[0.0, "#ffffff", 1], [0.25, "#111111", 0], [0.5, "#e02020", 2], [0.8, "#123456", None], [1.0, "#00ff00", 3]],
             "sw": [[0.3, None, "#111111"], [0.5, 1, "#e02020"], [0.9, None, "#abcdef"]]},
      "bande nettoyée : couleurs #rrggbb, places 0..1 triées, tête 0..3 : %s" % c1)
check(mb.strip_clean({"seg": []}) is None and mb.strip_clean("x") is None and mb.strip_clean({"seg": [[0, "red"]]}) is None,
      "bande vide ou illisible : rien")
mb.remember_strip("a.gcode", c1)
check(mb.strip_for("a.gcode") == c1 and mb.strip_for("b.gcode") is None, "bande gardée par nom de fichier")
mb._STRIPS["d"] = None
check(mb.strip_for("a.gcode") == c1, "relue après un redémarrage d'OrcaSlicer (strips.json)")
for i in range(14):
    mb.remember_strip("f%02d.gcode" % i, {"seg": [[0, "#000000", 0]], "sw": []}); time.sleep(0.002)
mb._STRIPS["d"] = None
check(len(mb._strips()) == 12 and mb.strip_for("f13.gcode") and not mb.strip_for("a.gcode") and not mb.strip_for("f01.gcode"),
      "les 12 dernières seulement (%d)" % len(mb._strips()))

# ---------------------------------------------------------------- 2. avancement lu sur Moonraker
cl = mb.MultiAce(host)
check(mb.print_progress(cl) == {"state": "standby"} and "print_stats" in PR["q"] and "display_status" in PR["q"],
      "hors impression : l'état seul")
mb.remember_strip("ChristmasBear_multiACE.gcode", c1)
PR["status"] = {"print_stats": {"state": "printing", "filename": "ChristmasBear_multiACE.gcode", "print_duration": 7800.6,
                                "info": {"current_layer": 120, "total_layer": 650}},
                "display_status": {"progress": 0.42}, "virtual_sdcard": {"progress": 0.31}}
p1 = mb.print_progress(cl)
check(p1 == {"state": "printing", "file": "ChristmasBear_multiACE.gcode", "p": 0.42, "elapsed": 7800, "layer": 120,
             "layers": 650, "strip": {"seg": c1["seg"], "sw": c1["sw"]}},
      "impression : avancement du M73, couche, temps, bande du fichier : %s" % {k: v for k, v in p1.items() if k != "strip"})
PR["status"]["display_status"] = {"progress": 0}
PR["status"]["print_stats"]["info"] = {}
check(mb.print_progress(cl)["p"] == 0.31 and mb.print_progress(cl)["layer"] is None, "sans M73 : position dans le fichier ; sans couche : rien")
PR["status"]["print_stats"]["state"] = "paused"; PR["status"]["print_stats"]["filename"] = "autre.gcode"
p2 = mb.print_progress(cl)
check(p2["state"] == "paused" and "strip" not in p2, "pause ; fichier envoyé ailleurs : pas de bande")

# ---------------------------------------------------------------- 3. pause, reprise, arrêt
PR["posts"].clear()
r = mb.print_control(cl, "pause")
check(PR["posts"] == [("multiace", "pause")] and r.get("ok"), "pause : /api/print-control de multiACE")
PR["pc"] = "queued"; r = mb.print_control(cl, "cancel")
check(r.get("queued") is True, "arrêt pendant un échange : multiACE le met en attente")
PR["pc"] = "404"; PR["posts"].clear(); r = mb.print_control(cl, "resume")
check(PR["posts"] == [("multiace", "resume"), ("moonraker", "resume")] and r == {"ok": True},
      "multiACE sans print-control (avant 1.90) : Moonraker /printer/print/resume")
PR["pc"] = "500"
try:
    mb.print_control(cl, "pause"); check(False, "erreur de multiACE remontée")
except mb.MultiAceError as e:
    check("500" in str(e) and "Klipper busy" in str(e), "erreur de multiACE remontée : %s" % e)
try:
    mb.print_control(cl, "G28"); check(False, "commande inconnue refusée")
except mb.MultiAceError:
    check(True, "commande inconnue refusée")
PR["pc"] = "ok"

# ---------------------------------------------------------------- 4. panneau (Python) : état avec l'avancement, commandes
class FakePanel:
    def __init__(s): s.posts = []
    def post(s, d): s.posts.append(json.loads(json.dumps(d)))
    def is_open(s): return True
st0 = mb.load_settings(); st0["host"] = host; mb.save_settings(st0)
ap = mb.AcePanelController(); FP = FakePanel(); ap.panel = FP
def states(): return [x for x in FP.posts if x.get("command") == "state"]
def dones(): return [x for x in FP.posts if x.get("command") == "done"]
PR["status"]["print_stats"]["filename"] = "ChristmasBear_multiACE.gcode"
ap.on_message({"command": "refresh"})
check(wait(lambda: states()) and states()[-1].get("prog", {}).get("strip") == {"seg": c1["seg"], "sw": c1["sw"]},
      "panneau : état avec l'avancement et la bande")
ap.on_message({"command": "prefs_get"})
check(wait(lambda: any(x.get("command") == "prefs" for x in FP.posts)) and [x for x in FP.posts if x.get("command") == "prefs"][-1]["progress"] is True,
      "réglage : barre affichée par défaut")
ap.on_message({"command": "prefs_set", "progress": False}); FP.posts.clear(); ap.on_message({"command": "refresh"})
check(wait(lambda: states()) and "prog" not in states()[-1] and mb.load_settings()["progress"] is False,
      "barre masquée : pas de lecture de l'avancement, réglage gardé")
ap.on_message({"command": "prefs_set", "progress": True})
FP.posts.clear(); PR["posts"].clear()
ap.on_message({"command": "print_ctl", "verb": "pause"})
check(wait(lambda: dones()) and dones()[-1] == {"command": "done", "ok": True, "text": "Pause demandée."} and PR["posts"] == [("multiace", "pause")],
      "panneau : pause %s" % dones()[-1:])
FP.posts.clear(); PR["pc"] = "queued"
ap.on_message({"command": "print_ctl", "verb": "cancel"})
check(wait(lambda: dones()) and dones()[-1]["text"] == "Arrêt demandé : la U1 finit d'abord l'échange de bobine en cours.", "panneau : arrêt pendant un échange")
FP.posts.clear(); PR["pc"] = "500"
ap.on_message({"command": "print_ctl", "verb": "resume"})
check(wait(lambda: dones()) and dones()[-1]["ok"] is False and dones()[-1]["text"].startswith("Reprise demandée : échec (HTTP 500"),
      "panneau : échec dit %r" % dones()[-1:])
PR["pc"] = "ok"; FP.posts.clear(); PR["posts"].clear()
ap.on_message({"command": "print_ctl", "verb": "FIRMWARE_RESTART"}); time.sleep(0.3)
check(not dones() and not PR["posts"], "panneau : commande inconnue ignorée")

# ---------------------------------------------------------------- 5. fenêtre : la bande du plan part avec l'impression
# 6 couleurs pour 4 têtes : des échanges de bobine (T1 et T2 portent chacune deux couleurs)
COLS = ["#000000", "#FFFFFF", "#E53935", "#1E88E5", "#43A047", "#FDD835"]
def make6(path, layers=60, seed=11):
    rnd = random.Random(seed)
    L = ["; HEADER_BLOCK_START", "; generated by OrcaSlicer 2.5.0", "; HEADER_BLOCK_END",
         "SET_PRINT_AUTO_BED_LEVELING ENABLE=1", "PRINT_START", "M104 T0 S140", "G28 X Y", "T0", "G90", "M109 S210 T0", "G1 X10 Y10 E5 F600"]
    cur = 0
    for layer in range(layers):
        L += [";LAYER_CHANGE", ";Z:%.2f" % (0.2 * (layer + 1)), "G1 Z%.2f" % (0.2 * (layer + 1)),
              "M73 P%d R%d" % (int(100 * layer / layers), int(120 * (1 - layer / layers)))]
        for t in rnd.sample(range(6), 3):
            if t != cur:
                L += ["; Change Tool%d -> Tool%d (layer %d)" % (cur, t, layer), "G91", "G1 Z1.5 F600", "G90", "M109 S210 T%d" % t, "M400", "T%d" % t]
                cur = t
            L += ["G1 X%d Y%d E1.2 F3000" % (rnd.randint(10, 200), rnd.randint(10, 200)) for _ in range(5)]
    L += ["PRINT_END", "; filament used [mm] = 900.00,5800.00,640.00,970.00,500.00,450.00", "; filament used [g] = 27.0,174.0,19.0,29.0,15.0,13.0",
          "; CONFIG_BLOCK_START", "; filament_colour = " + ";".join(c + "FF" for c in COLS), "; filament_type = PLA;PLA;PLA;PLA;PLA;PLA",
          "; nozzle_diameter = 0.4,0.4,0.4,0.4", "; CONFIG_BLOCK_END"]
    open(path, "w").write("\n".join(L) + "\n")
gp = tempfile.mktemp(suffix=".gcode"); make6(gp)
LIVE_P = [P(0, 0, "#111111"), P(0, 1, "#ffffff"), P(0, 2, "#e02020"), P(0, 3, "#1e88e5"),
          P(1, 0, "#43a047"), P(1, 1, "#fdd835")]
dm = run(LIVE_P, {"mode": "multi", "head_nozzle_types": dict(NOZ)}, {0: (0, 0), 1: (0, 1), 2: (0, 2), 3: (0, 3)},
         name="ChristmasBear.gcode", path=gp)
check(bool(dm.get("report")), "fenêtre : rapport de la U1 (vrai code multiACE)")
FAKE = """<script>window.__h=[];window.__p=[];window.orca={postMessage:function(m){window.__p.push(typeof m==="string"?JSON.parse(m):m)},onMessage:function(f){window.__h.push(f)}};</script>"""
os.makedirs("/home/claude/testdata", exist_ok=True)
def page(html, data, nm, en=False):
    h = html.replace("<head>", "<head>" + FAKE, 1)
    if data is not None:
        h = h.replace("__DATA__", json.dumps(data).replace("</", "<\\/"))
    open("/home/claude/testdata/%s.html" % nm, "w").write(mb.i18n_page(h) if en else h)
    return "file:///home/claude/testdata/%s.html" % nm
def plain(s): return s.replace(" ", " ")
tl = dm["report"]["plans"]["slicer"]["timeline"]
occ = {(x["ace"], x["slot"]): x["color"].lower() for x in dm["report"]["live_slots"]}
n_sw = sum(1 for e in tl if e.get("kind") not in ("first_load", "head_change"))

with sync_playwright() as pw:
    br = pw.chromium.launch(executable_path="/usr/bin/google-chrome")
    mb._LANG["v"] = "fr"
    pg = br.new_page(viewport={"width": 1220, "height": 900})
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(page(mb.U1_PAGE, dm, "pg_win")); pg.wait_for_selector("#pmap .slot", timeout=8000)
    pg.evaluate("window.__p.length=0"); pg.click("#go"); pg.wait_for_timeout(150)
    msg = [x for x in pg.evaluate("window.__p") if x.get("a") == "print"]
    strip = (msg[-1] if msg else {}).get("strip") or {}
    seg, sw = strip.get("seg") or [], strip.get("sw") or []
    check(msg and seg and seg[0][0] == 0 and all(seg[i][0] <= seg[i + 1][0] for i in range(len(seg) - 1)),
          "fenêtre : bande envoyée avec l'impression (%d segments)" % len(seg))
    ev = sorted([e for e in tl if e.get("t") is not None], key=lambda e: e["i"])
    want_cols = {occ[(e["ace"], e["slot"])] for e in ev if e.get("ace") is not None}
    check({s[1] for s in seg} <= want_cols and all(isinstance(s[2], int) for s in seg),
          "couleurs des bobines qui impriment %s" % sorted({s[1] for s in seg}))
    check(len(sw) == n_sw and n_sw > 5 and all(0 <= w[0] <= 1 for w in sw) and all(w[1] in (0, 1) for w in sw),
          "un repère par échange de bobine de la frise de la U1 (%d)" % len(sw))
    check(not errs, "fenêtre sans erreur JS %s" % errs[:2])
    pg.close()
    # côté plugin : la bande gardée sous le nom du fichier sur la U1
    W.window = None
    W.on_message(msg[-1])
    check(wait(lambda: not W._busy, 60) and mb.strip_for("ChristmasBear_multiACE.gcode") == mb.strip_clean(strip),
          "impression lancée : bande gardée pour ChristmasBear_multiACE.gcode")
    W.on_message(dict(msg[-1], a="upload", strip={"seg": [[0, "#123456", 0]], "sw": []}))
    check(wait(lambda: not W._busy, 60) and mb.strip_for("ChristmasBear_multiACE.gcode") == {"seg": [[0.0, "#123456", 0]], "sw": []},
          "envoyé sans lancer : bande gardée aussi")
    mb.remember_strip("ChristmasBear_multiACE.gcode", mb.strip_clean(strip))

    # ---------------------------------------------------------------- 6. panneau dans Chrome
    PROG = {"state": "printing", "file": "ChristmasBear_multiACE.gcode", "p": 0.42, "elapsed": 7800, "layer": 120, "layers": 650,
            "strip": mb.strip_clean(strip)}
    nx = next(w for w in PROG["strip"]["sw"] if w[0] > 0.4205)
    for lang in ("fr", "en"):
        fr = lang == "fr"; mb._LANG["v"] = lang
        pg = br.new_page(viewport={"width": 340, "height": 900})
        errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(page(mb.PANEL.replace("__VERSION__", mb.VERSION), None, "pg_panel_" + lang, en=not fr)); pg.wait_for_timeout(150)
        send = lambda m: pg.evaluate("m=>window.__h.forEach(f=>f(m))", m)
        send({"command": "prefs", "host": "x", "screen": "off", "camera": "off", "compact": False, "auto_home": True, "folds": {}, "progress": True})
        st = {"display_index_base": 1, "mode": "multi", "printer_state": "printing", "aces": [], "toolheads": []}
        send({"command": "state", "state": st, "prog": PROG}); pg.wait_for_timeout(120)
        card = pg.evaluate("""()=>{var e=document.getElementById('progTop');return {cls:e.className,h:e.querySelector('.pgh').innerText,
          f:(e.querySelector('.pgf')||{}).textContent,rect:e.querySelectorAll('.pgs rect').length,ln:e.querySelectorAll('.pgs line').length,
          m:[].map.call(e.querySelectorAll('.pgm span'),function(x){return x.textContent}),mt:(e.querySelector('.pgm .rem')||{}).title,n:[].map.call(e.querySelectorAll('.pgn span'),function(x){return x.textContent}),b:[].map.call(e.querySelectorAll('.pgb button'),function(x){return x.textContent})}}""")
        SG = PROG["strip"]["seg"]
        ns, nw = sum(1 for i, x in enumerate(SG) if (SG[i + 1][0] if i + 1 < len(SG) else 1) > x[0]), len(PROG["strip"]["sw"])
        check(card["cls"] == "box prog" and plain(card["h"]).replace("\n", " ").strip() == ("Impression en cours 42 %" if fr else "Printing 42 %")
              and card["f"] == "ChristmasBear_multiACE.gcode", lang + " : carte en haut du panneau %r" % card["h"])
        check(card["rect"] == ns + 3 and card["ln"] == 2 * nw + 1, lang + " : bande de %d segments, %d repères d'échange, curseur" % (ns, nw))
        check([plain(x) for x in card["m"]] == (["couche 120 / 650", "reste environ 3 h 00"] if fr else ["layer 120 / 650", "about 3 h 00 left"])
              and plain(card["mt"]) == ("écoulé 2 h 10" if fr else "2 h 10 elapsed"), lang + " : %r, survol %r" % (card["m"], card["mt"]))
        want_n = [("Prochain échange vers %d %%" if fr else "Next swap around %d %%") % int(nx[0] * 100 + 0.5)] + (["T%d" % (nx[1] + 1)] if nx[1] is not None else [])
        check([plain(x) for x in card["n"]] == want_n, lang + " : %r" % card["n"])
        check(card["b"] == (["Pause", "Arrêter"] if fr else ["Pause", "Stop"]), lang + " : boutons %s" % card["b"])
        cx = pg.evaluate("()=>{var l=[].slice.call(document.querySelectorAll('#progTop .pgs line')).pop();return l.getAttribute('x1')}")
        check(cx == "42.000%", lang + " : curseur à 42 %% (%s)" % cx)
        pg.evaluate("window.__p.length=0"); pg.click("#progTop [data-pg=pause]"); pg.wait_for_timeout(80)
        check(pg.evaluate("window.__p") == [{"command": "print_ctl", "verb": "pause"}] and pg.is_disabled("#progTop [data-pg=pause]"),
              lang + " : Pause envoyée")
        send({"command": "state", "state": st, "prog": dict(PROG, state="paused")}); pg.wait_for_timeout(80)
        h2 = plain(pg.inner_text("#progTop .pgh")).replace("\n", " ").strip()
        check(h2 == ("En pause 42 %" if fr else "Paused 42 %") and pg.inner_text("#progTop [data-pg=resume]") == ("Reprendre" if fr else "Resume")
              and "warn" in pg.get_attribute("#progTop .led", "class"), lang + " : en pause, bouton Reprendre")
        pg.evaluate("window.__p.length=0"); pg.click("#progTop [data-pg=resume]"); pg.wait_for_timeout(80)
        check(pg.evaluate("window.__p") == [{"command": "print_ctl", "verb": "resume"}], lang + " : Reprendre envoyé")
        send({"command": "state", "state": st, "prog": PROG}); pg.wait_for_timeout(80)
        pg.evaluate("window.__p.length=0"); pg.click("#progTop [data-pg=cancel]"); pg.wait_for_timeout(80)
        check(pg.evaluate("window.__p") == [] and pg.inner_text("#progTop [data-pg=cancel]") == ("Confirmer l’arrêt" if fr else "Confirm stop"),
              lang + " : Arrêter : un premier clic demande confirmation")
        pg.click("#progTop [data-pg=cancel]"); pg.wait_for_timeout(80)
        check(pg.evaluate("window.__p") == [{"command": "print_ctl", "verb": "cancel"}], lang + " : deuxième clic : arrêt envoyé")
        send({"command": "state", "state": st, "prog": PROG}); pg.wait_for_timeout(80)
        pg.click("#progTop [data-pg=cancel]"); pg.wait_for_timeout(4300)
        check(pg.inner_text("#progTop [data-pg=cancel]") == ("Arrêter" if fr else "Stop"), lang + " : confirmation abandonnée après 4 s")
        pg.evaluate("window.__p.length=0"); pg.click("#pgb"); pg.wait_for_timeout(80)
        check(pg.evaluate("document.getElementById('progTop').innerHTML") == "" and pg.evaluate("window.__p") == [{"command": "prefs_set", "progress": False}]
              and "on" not in pg.get_attribute("#pgb", "class"), lang + " : bouton : barre masquée, réglage envoyé")
        send({"command": "state", "state": st, "prog": PROG}); pg.wait_for_timeout(80)
        check(pg.evaluate("document.getElementById('progTop').innerHTML") == "", lang + " : masquée, elle le reste")
        pg.evaluate("window.__p.length=0"); pg.click("#pgb"); pg.wait_for_timeout(80)
        check(pg.evaluate("window.__p") == [{"command": "prefs_set", "progress": True}, {"command": "refresh"}] and "on" in pg.get_attribute("#pgb", "class")
              and pg.is_visible("#progTop .pgs"), lang + " : réaffichée tout de suite, actualisation demandée")
        tip = pg.get_attribute("#pgb", "title")
        check(tip == ("Barre de progression de l'impression : affichée ou masquée" if fr else "Print progress bar: shown or hidden"), lang + " : %r" % tip)
        if fr:
            pg.screenshot(path="/home/claude/scratch/pg_panel.png", clip={"x": 0, "y": 0, "width": 340, "height": 270})
        send({"command": "state", "state": st, "prog": dict(PROG, strip=None, p=0.1, layer=None, elapsed=30)}); pg.wait_for_timeout(80)
        check(pg.evaluate("document.querySelectorAll('#progTop .pgs rect').length") == 3 and pg.query_selector("#progTop .pgn") is None
              and pg.query_selector("#progTop .pgm") is None, lang + " : impression lancée ailleurs : barre simple, sans échange")
        send({"command": "state", "state": st, "prog": {"state": "complete"}}); pg.wait_for_timeout(80)
        check(pg.evaluate("document.getElementById('progTop').innerHTML") == "", lang + " : impression finie : plus de barre")
        send({"command": "state", "state": st}); pg.wait_for_timeout(80)
        check(pg.evaluate("document.getElementById('progTop').innerHTML") == "", lang + " : sans avancement (Moonraker muet) : rien")
        send({"command": "state", "state": st, "prog": dict(PROG, p=0.995)}); pg.wait_for_timeout(80)
        check(plain(pg.inner_text("#progTop .pgn")).strip() == ("Plus d’échange de bobine" if fr else "No more spool swaps"), lang + " : après le dernier échange")
        send({"command": "state", "state": st, "prog": dict(PROG, strip=dict(PROG["strip"], sw=[]))}); pg.wait_for_timeout(80)
        check(plain(pg.inner_text("#progTop .pgn")).strip() == ("Aucun échange de bobine dans cette impression" if fr else "No spool swap in this print"),
              lang + " : impression sans échange : dit tel quel")
        check(not errs, lang + " : panneau sans erreur JS %s" % errs[:2])
        pg.close()
    br.close()

print("ECHECS : %d" % fails if fails else "TOUT OK")
if fails:
    raise SystemExit(1)
