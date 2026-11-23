"""0.44.0 : séchage long (jusqu'à 7 jours, par cycles de 10 h relancés par le plugin).
1. logique des plans (sans réseau) ; 2. fausse U1 (HTTP) avec la vraie file du panneau et le vrai fil du
garde-fou, case « Garde-fou » décochée ; 3. panneau (FR et EN) dans Chrome."""
import http.server, json, os, sys, tempfile, threading, time, types
STORE = tempfile.mkdtemp()
sys.modules["orca"] = types.SimpleNamespace(
    plugin=lambda c: c, base=object, pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
    script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
    slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object),
    host=types.SimpleNamespace(plugin=types.SimpleNamespace(storage=lambda: STORE)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import multiace_bridge_any as P

fails = 0
def check(name, cond):
    global fails
    print(("OK   " if cond else "FAIL ") + name)
    fails += 0 if cond else 1

TMP = tempfile.mkdtemp()
def plans(name, queued=lambda i: True):
    return P.DryPlans(path_fn=lambda: os.path.join(TMP, name), queued_fn=queued)
def ace(i, conn=True, dry=None):
    d = {"status": "drying", "target_temp": dry[0], "remain_time": dry[1]} if dry else {"status": "stop"}
    return {"idx": i, "connected": conn, "dryer": d}
def st(*aces):
    return {"aces": list(aces)}
kinds = lambda acts: [a[0] for a in acts]
DAY = 86400

# ---------------------------------------------------------------- 1. formats et logique
P._LANG["v"] = "fr"
check("format jours", P.fmt_left(3 * DAY) == "3 j" and P.fmt_left(2 * DAY + 14 * 3600) == "2 j 14 h")
check("format heures et minutes", P.fmt_left(14 * 3600 + 5 * 60) == "14 h 05" and P.fmt_left(35 * 60 - 10) == "35 min")
P._LANG["v"] = "en"
check("format anglais", P.fmt_left(2 * DAY + 14 * 3600) == "2 d 14 h")
P._LANG["v"] = "fr"
check("cycle : 10 h au plus, 10 min au moins", P._dry_minutes(3 * DAY) == 600 and P._dry_minutes(30) == 10
      and P._dry_minutes(125 * 60) == 125)

T0 = 1_000_000.0
d = plans("a.json")
d.start(0, 50, 3 * 1440, now=T0, mono=0)
check("plan enregistré", json.load(open(os.path.join(TMP, "a.json")))["0"]["end"] == T0 + 3 * DAY)
check("premier cycle dans la file : rien", d.step(st(ace(0)), T0 + 5, 5) == [])
d.sent(0, mono=10)
check("commande partie : on laisse l'ACE démarrer", d.step(st(ace(0)), T0 + 20, 20) == [])
acts = d.step(st(ace(0)), T0 + 140, 140)
check("ne démarre pas -> question", kinds(acts) == ["dry_ask"] and acts[0][4] == "nostart" and d.view()["0"]["paused"])
check("en pause : rien de plus", d.step(st(ace(0)), T0 + 400, 400) == [])
r = d.resume(0, now=T0 + 410, mono=410)
check("Relancer : cycle de 10 h", r is not None and r[0] == 50 and r[1] == 600 and not d.view()["0"]["paused"])
check("après Relancer : on attend que l'ACE sèche", d.step(st(ace(0)), T0 + 420, 420) == [])
check("cycle vu", d.step(st(ace(0, dry=(50, 36000))), T0 + 500, 500) == [])
d.step(st(ace(0, dry=(50, 100))), T0 + 36400, 36400)
acts = d.step(st(ace(0)), T0 + 36500, 36500)
check("fin normale du cycle -> cycle suivant", kinds(acts) == ["dry_run"] and acts[0][1:4] == (0, 50, 600) and acts[0][5] is False)
check("une seule relance", d.step(st(ace(0)), T0 + 36510, 36510) == [])
d.step(st(ace(0, dry=(50, 30000))), T0 + 36600, 36600)
acts = d.step(st(ace(0)), T0 + 36602, 36602)
check("arrêt avant la fin sans coupure -> question, pas de relance", kinds(acts) == ["dry_ask"] and acts[0][4] == "stopped")

d.start(1, 45, 2 * 1440, now=T0, mono=0)
d.sent(1, mono=1)
d.step(st(ace(1, dry=(45, 30000))), T0 + 1000, 1000)
d.step(st(ace(1, conn=False)), T0 + 1002, 1002)
check("ACE revenu sans séchage : on laisse le temps", d.step(st(ace(1)), T0 + 1004, 1004) == [])
acts = d.step(st(ace(1)), T0 + 1013, 1013)
check("coupure -> cycle suivant", kinds(acts) == ["dry_run"] and acts[0][1] == 1)

d.start(2, 45, 20, now=T0, mono=0)
d.sent(2, mono=1)
d.step(st(ace(2, dry=(45, 1200))), T0 + 10, 10)
acts = d.step(st(ace(2, dry=(45, 30))), T0 + 1170, 1170)
check("durée atteinte -> terminé", kinds(acts) == ["dry_done"] and acts[0][2] == 1200 and 2 not in d.active())
d.start(3, 45, 30, now=T0, mono=0)
d.sent(3, mono=1)
acts = d.step(st(ace(3)), T0 + 1500, 50)
check("moins de 10 min à faire, ACE arrêté -> terminé", kinds(acts) == ["dry_done"] and 3 not in d.active())

q = {"in": True}
e = plans("b.json", queued=lambda i: q["in"])
e.start(0, 50, 1440, now=T0, mono=0)
check("dans la file : on attend", e.step(st(ace(0)), T0 + 60, 60) == [])
q["in"] = False
acts = e.step(st(ace(0)), T0 + 62, 62)
check("retiré de la file -> plan annulé", kinds(acts) == ["note"] and not e.active())

f = plans("c.json")
f.start(1, 55, 5 * 1440, now=T0, mono=0)
g = plans("c.json")
check("plan relu après redémarrage d'Orca", g.active() == {1} and g.plan_of(1)["temp"] == 55)
check("ACE qui sèche encore : rien", g.step(st(ace(1, dry=(55, 9000))), T0 + 3600, 3600) == [])
h = plans("c.json")
acts = h.step(st(ace(1)), T0 + 7200, 7200)
check("ACE arrêté pendant qu'Orca était fermé -> reprise", kinds(acts) == ["dry_run"] and acts[0][3] == 600)
check("Arrêter efface le plan", h.clear(1) and not plans("c.json").active())

with open(os.path.join(TMP, "bad.json"), "w") as fh:
    json.dump({"0": {"temp": 99, "start": 0, "end": 10}, "1": {"temp": 45, "start": 10, "end": 5}, "x": {},
               "2": {"temp": 45, "start": 0, "end": 10 ** 9}, "3": "oui"}, fh)
check("fichier abîmé ignoré", plans("bad.json").active() == set())
check("vue pour le panneau", set(d.view()["1"]) == {"temp", "start", "end", "paused"})
check("libellé de file : la durée choisie", P.action_label("ACE_DRY", {"ACE": 0, "TEMP": 45, "DURATION": 240})
      == "Séchage ACE 1 (45 °C, 4 h)")

# ---------------------------------------------------------------- 2. fausse U1, vraie file, vrai fil
state = {"aces": [{"idx": 0, "connected": True, "dryer": {"status": "stop"}},
                  {"idx": 1, "connected": True, "dryer": {"status": "stop"}}],
         "toolheads": [], "printer_state": "printing", "active_device": 0, "swap_in_progress": False}
macros = []

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def j(self, obj):
        b = json.dumps(obj).encode(); self.send_response(200)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path == "/multiace/api/state": return self.j(state)
        if self.path.startswith("/printer/objects/query"):
            return self.j({"result": {"status": {"toolhead": {"extruder": "extruder", "homed_axes": "xyz"}}}})
        self.send_response(404); self.end_headers()
    def do_POST(self):
        m = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        macros.append(m)
        a = m.get("args") or {}
        if m["name"] == "ACE_DRY":
            state["aces"][int(a["ACE"])]["dryer"] = {"status": "drying", "target_temp": a["TEMP"],
                                                     "remain_time": a["DURATION"] * 60, "duration": a["DURATION"]}
        if m["name"] == "ACE_STOP_DRYING":
            state["aces"][int(a["ACE"])]["dryer"] = {"status": "stop"}
        self.j({"result": "ok"})

srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
host = "127.0.0.1:%d" % srv.server_address[1]
P.load_settings = lambda: {"host": host, "ace_guard": False}
P.GUARD_POLL, P.DRY_START_WAIT, P.DRY_BACK_SETTLE = 0.1, 1.5, 0.3
P._DRY = P.DryPlans(path_fn=lambda: os.path.join(TMP, "live.json"))
posts = []
P._PANEL._post = posts.append
def dry_macros():
    return [m for m in macros if m["name"] == "ACE_DRY"]
def wait(cond, t=4.0):
    end = time.time() + t
    while time.time() < end and not cond():
        time.sleep(0.05)
    return cond()

P._PANEL.on_message({"command": "dry", "ace": 0, "temp": 50, "duration": 4320})
q = [x for x in posts if x.get("command") == "queue"]
check("file : « 3 j par cycles de 10 h »", q and any(i["label"] == "Séchage ACE 1 (50 °C, 3 j par cycles de 10 h)"
                                                     for i in q[0]["items"]))
check("premier cycle de 10 h envoyé", wait(lambda: len(dry_macros()) == 1) and dry_macros()[0]["args"] ==
      {"ACE": 0, "TEMP": 50, "DURATION": 600})
check("plan actif, enregistré, fil lancé (case Garde-fou décochée)", P._DRY.active() == {0}
      and os.path.exists(os.path.join(TMP, "live.json")) and P._GUARD._thread is not None and P._GUARD._thread.is_alive())
time.sleep(0.4)
state["aces"][0]["dryer"].update(remain_time=60)          # fin du cycle
time.sleep(0.4)
state["aces"][0]["dryer"] = {"status": "stop"}
check("fin du cycle -> le plugin lance le suivant", wait(lambda: len(dry_macros()) == 2) and dry_macros()[1]["args"]["DURATION"] == 600)
check("message « nouveau cycle »", wait(lambda: any("nouveau cycle" in p.get("text", "") for p in posts)))
time.sleep(0.4)
state["aces"][0]["dryer"] = {"status": "stop"}            # arrêté depuis la U1, cycle à peine commencé
check("arrêt depuis la U1 -> question", wait(lambda: any(p.get("ask") == 0 for p in posts)))
time.sleep(0.5)
check("pas de relance toute seule", len(dry_macros()) == 2 and P._DRY.view()["0"]["paused"])
P._PANEL.on_message({"command": "guard_dry", "ace": 0})
check("« Relancer » -> cycle relancé", wait(lambda: len(dry_macros()) == 3)
      and wait(lambda: any("séchage relancé" in p.get("text", "") for p in posts)))
P._PANEL.on_message({"command": "stopdry", "ace": 0})
check("« Arrêter » : arrêt envoyé, plan effacé", wait(lambda: any(m["name"] == "ACE_STOP_DRYING" for m in macros))
      and not P._DRY.active() and json.load(open(os.path.join(TMP, "live.json"))) == {})
time.sleep(0.5)
n = len(dry_macros())
P._PANEL.on_message({"command": "dry", "ace": 1, "temp": 45, "duration": 240})
check("4 h : un seul séchage, pas de plan", wait(lambda: len(dry_macros()) == n + 1) and dry_macros()[-1]["args"]["DURATION"] == 240
      and not P._DRY.active())
time.sleep(0.3)
n = len(macros)
P._PANEL.on_message({"command": "dry", "ace": 1, "temp": 45, "duration": 10081})
P._PANEL.on_message({"command": "dry", "ace": 1, "temp": 45, "duration": "3 jours"})
time.sleep(0.4)
check("plus de 7 jours ou durée illisible : refusé", len(macros) == n and not P._DRY.active())
P._PANEL._paused = True                                    # file en pause : le séchage reste dans la file
P._PANEL.on_message({"command": "dry", "ace": 1, "temp": 45, "duration": 2880})
P._PANEL.on_message({"command": "stopdry", "ace": 1})
time.sleep(0.3)
check("Arrêter retire aussi le séchage en attente", not any(it["name"] == "ACE_DRY" for it in P._PANEL._queue)
      and not P._DRY.active())
P._PANEL._paused = False

# ---------------------------------------------------------------- 3. panneau
from playwright.sync_api import sync_playwright
FAKE = """<script>window.__h=[];window.__p=[];window.orca={postMessage:function(m){window.__p.push(typeof m==="string"?JSON.parse(m):m)},onMessage:function(f){window.__h.push(f)}};</script>"""
def slot(i, col):
    return {"idx": i, "state": "ready", "color": col, "material": "PLA", "source": "rfid"}
def pstate(dry0):
    return {"display_index_base": 1, "mode": "multi", "printer_state": "printing",
            "aces": [{"idx": 0, "connected": True, "temp": 31, "dryer": dry0, "slots": [slot(i, "#E53935") for i in range(4)]},
                     {"idx": 1, "connected": True, "temp": 24, "dryer": {"status": "stop"}, "slots": [slot(i, "#2F80D1") for i in range(4)]}],
            "toolheads": [{"idx": i, "filament_detected": False, "ace": None, "slot": None} for i in range(4)],
            "spools": {}, "spool_binding": {}}
for lang in ("fr", "en"):
    P._LANG["v"] = lang
    html = P.i18n_page(P.PANEL.replace("__VERSION__", P.VERSION).replace("<head>", "<head>" + FAKE, 1))
    path = os.path.join(TMP, "panel_%s.html" % lang)
    open(path, "w", encoding="utf-8").write(html)
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path="/usr/bin/google-chrome")
        pg = b.new_page(viewport={"width": 400, "height": 900})
        errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto("file://" + path); pg.wait_for_timeout(200)
        send = lambda m: pg.evaluate("m=>window.__h.forEach(f=>f(m))", m)
        send({"command": "prefs", "host": "x", "screen": "off", "camera": "off", "compact": False, "auto_home": True, "folds": {}})
        now = pg.evaluate("Date.now()/1000")
        start = now - 10 * 3600 + 30
        plan = {"temp": 50, "start": start, "end": start + 3 * DAY, "paused": False}
        send({"command": "state", "state": pstate({"status": "drying", "target_temp": 50, "remain_time": 20000, "duration": 600}),
              "dry": {"0": plan}, "printer": "U1"}); pg.wait_for_timeout(250)
        gut = pg.locator('.tray[data-ace="0"] .gut').inner_text()
        tip = pg.locator('.tray[data-ace="0"] .gut .drying').get_attribute("title")
        if lang == "fr":
            check("FR : reste total du plan", "50 °C" in gut and "2 j 14 h" in gut and "Arrêter" in gut)
            check("FR : info-bulle", tip.startswith("Durée choisie : 3 jours.") and "tant qu’OrcaSlicer est ouvert" in tip)
        else:
            check("EN : total left", "2 d 14 h" in gut and "Stop" in gut and "Arrêter" not in gut)
            check("EN : tooltip", tip.startswith("Chosen time: 3 days.") and "while OrcaSlicer is open" in tip)
        w = pg.locator('.tray[data-ace="0"] .dprog i').get_attribute("style")
        check(lang + " : barre du plan (14 %)", "width:14%" in w.replace(" ", ""))
        pg.locator('.tray[data-ace="0"] button[data-act="stopdry"]').click()
        pg.locator('.tray[data-ace="0"] button[data-act="stopdry"]').click()
        check(lang + " : Arrêter -> stopdry", {"command": "stopdry", "ace": 0} in pg.evaluate("window.__p"))
        send({"command": "state", "state": pstate({"status": "stop"}), "dry": {"0": dict(plan, paused=True)}}); pg.wait_for_timeout(200)
        gut = pg.locator('.tray[data-ace="0"] .gut').inner_text()
        check(lang + " : plan en pause", ("En\u00a0pause" in gut and "Relancer" in gut) if lang == "fr" else ("Paused" in gut and "Restart" in gut))
        pg.locator('.tray[data-ace="0"] button[data-act="redry"]').click()
        pg.locator('.tray[data-ace="0"] button[data-act="redry"]').click()
        check(lang + " : Relancer -> guard_dry", {"command": "guard_dry", "ace": 0} in pg.evaluate("window.__p"))
        send({"command": "state", "state": pstate({"status": "stop"}), "dry": {"0": plan}}); pg.wait_for_timeout(200)
        gut = pg.locator('.tray[data-ace="0"] .gut').inner_text()
        check(lang + " : entre deux cycles", ("démarrage…" in gut) if lang == "fr" else ("starting…" in gut))
        pg.locator('[data-dry="1"]').click(); pg.wait_for_timeout(150)
        opts = pg.locator('select[data-dd="1"] option').all_inner_texts()
        check(lang + " : durées jusqu'à 7 jours", opts == (["1 h", "2 h", "4 h", "6 h", "8 h", "12 h", "1 jour", "2 jours", "3 jours", "5 jours", "7 jours"]
              if lang == "fr" else ["1 h", "2 h", "4 h", "6 h", "8 h", "12 h", "1 day", "2 days", "3 days", "5 days", "7 days"]))
        check(lang + " : pas de note à 4 h", pg.locator('.tray[data-ace="1"] .dnote').count() == 0)
        pg.select_option('select[data-dd="1"]', "4320"); pg.wait_for_timeout(150)
        note = pg.locator('.tray[data-ace="1"] .dnote').inner_text()
        check(lang + " : note au-delà de 10 h", note.startswith("Plus de 10 h") if lang == "fr" else note.startswith("Over 10 h: the ACE dries in 10 h cycles"))
        pg.locator('.tray[data-ace="1"] button[data-act="dry"]').click()
        pg.locator('.tray[data-ace="1"] button[data-act="dry"]').click()
        check(lang + " : Lancer -> dry 3 jours", {"command": "dry", "ace": 1, "temp": 45, "duration": 4320} in pg.evaluate("window.__p"))
        check(lang + " : pas d'erreur JS", not errs)
        if lang == "en":
            fr_left = [t for t in pg.locator("body").inner_text().splitlines() if any(x in t for x in ("jour", "Durée", "démarrage", "relanc", "Arrêter"))]
            check("EN : plus de français", not fr_left)
        b.close()
P._LANG["v"] = None
print("\n%s" % ("TOUT OK" if not fails else "%d FAIL" % fails))
sys.exit(1 if fails else 0)
