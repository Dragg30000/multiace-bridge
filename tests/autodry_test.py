"""0.46.0 : séchage auto selon l'humidité (ACE 2 simulé, l'imprimante de test n'en a pas).
1. réglages vérifiés côté Python ; 2. fausse U1 (HTTP) : la commande part tout de suite, aussi pendant une
impression, refus de multiACE affiché ; 3. panneau (FR et EN) dans Chrome : rien sans ACE 2, réglages ACE 2 et
ACE Pro suiveur, choix impossibles absents, pas d'erreur JS."""
import http.server, json, os, sys, tempfile, threading, time, types
STORE = tempfile.mkdtemp()
sys.modules["orca"] = types.SimpleNamespace(
    plugin=lambda c: c, base=object, pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
    script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
    slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object),
    host=types.SimpleNamespace(plugin=types.SimpleNamespace(storage=lambda: STORE)))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import multiace_bridge_any as P

fails = 0
def check(name, cond):
    global fails
    print(("OK   " if cond else "FAIL ") + name)
    fails += 0 if cond else 1

# ---------------------------------------------------------------- 1. réglages vérifiés
A = P.auto_dry_args
check("activer", A(0, {"ENABLE": 1}) == {"ACE": 0, "ENABLE": 1})
check("seuils ACE 2", A(1, {"RH_START": 50, "RH_END": 35}) == {"ACE": 1, "RH_START": 50, "RH_END": 35})
check("nombre entier écrit 50.0", A(1, {"TEMP": 50.0}) == {"ACE": 1, "TEMP": 50})
check("suiveur : maître, durée en plus", A(1, {"MASTER": 0}) == {"ACE": 1, "MASTER": 0}
      and A(1, {"MASTER": -1}) == {"ACE": 1, "MASTER": -1} and A(1, {"ADD_TIME": 90}) == {"ACE": 1, "ADD_TIME": 90})
check("arrêt au-dessus du départ : refusé", A(0, {"RH_START": 40, "RH_END": 40}) is None
      and A(0, {"RH_START": 40, "RH_END": 45}) is None)
check("hors bornes : refusé", all(A(0, {k: v}) is None for k, v in
      (("TEMP", 80), ("TEMP", 30), ("RH_START", 96), ("RH_END", 0), ("ADD_TIME", 601), ("MASTER", 4), ("ENABLE", 2))))
check("suivre lui-même : refusé", A(2, {"MASTER": 2}) is None)
check("valeurs bizarres : refusées", all(A(0, {"TEMP": v}) is None for v in (True, "50", 50.5, None, float("nan"), float("inf"), [50])))
check("ACE invalide : refusé", all(A(x, {"ENABLE": 1}) is None for x in (-1, 4, "x", None, True, 1.5)))
check("réglage inconnu, vide ou trop : refusé", A(0, {"DURATION": 60}) is None and A(0, {}) is None
      and A(0, "ENABLE=1") is None and A(0, {"ENABLE": 1, "TEMP": 50, "RH_START": 50, "RH_END": 30}) is None)
P._LANG["v"] = "fr"
L = P.action_label
check("libellés", L("ACE_SET_AUTO_DRY", {"ACE": 0, "ENABLE": 1}) == "Séchage auto ACE 1 activé"
      and L("ACE_SET_AUTO_DRY", {"ACE": 1, "ENABLE": 0}) == "Séchage auto ACE 2 désactivé"
      and L("ACE_SET_AUTO_DRY", {"ACE": 1, "MASTER": 0}) == "Réglage du séchage auto ACE 2")
P._LANG["v"] = "en"
check("libellé anglais", P.tr("Terminé : " + L("ACE_SET_AUTO_DRY", {"ACE": 0, "ENABLE": 1})) == "Done: Auto-dry ACE 1 on")
P._LANG["v"] = "fr"

# ---------------------------------------------------------------- 2. fausse U1
state = {"aces": [{"idx": 0, "connected": True, "dryer": {"status": "stop"}, "has_humidity": True},
                  {"idx": 1, "connected": True, "dryer": {"status": "stop"}, "has_humidity": False}],
         "toolheads": [], "printer_state": "printing", "active_device": 0, "swap_in_progress": False}
macros = []

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def j(self, obj, code=200):
        b = json.dumps(obj).encode(); self.send_response(code)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path == "/multiace/api/state": return self.j(state)
        self.send_response(404); self.end_headers()
    def do_POST(self):
        m = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        macros.append(m)
        a = m.get("args") or {}
        if m["name"] == "ACE_SET_AUTO_DRY" and "RH_START" in a and int(a["RH_START"]) <= 35:
            return self.j({"detail": "RH_END (35) must be BELOW RH_START (%d)" % int(a["RH_START"])}, 400)
        self.j({"result": "ok"})

srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
host = "127.0.0.1:%d" % srv.server_address[1]
P.load_settings = lambda: {"host": host, "ace_guard": False}
posts = []
P._PANEL._post = posts.append
def wait(cond, t=4.0):
    end = time.time() + t
    while time.time() < end and not cond():
        time.sleep(0.05)
    return cond()
def auto_macros():
    return [m for m in macros if m["name"] == "ACE_SET_AUTO_DRY"]
def dones():
    return [p for p in posts if p.get("command") == "done"]

P._PANEL.on_message({"command": "autodry", "ace": 0, "args": {"ENABLE": 1}})
check("pendant une impression : envoyé tout de suite", wait(lambda: len(auto_macros()) == 1)
      and auto_macros()[0]["args"] == {"ACE": 0, "ENABLE": 1})
check("message « Terminé »", wait(lambda: any(d.get("ok") and d.get("text") == "Terminé : Séchage auto ACE 1 activé" for d in dones())))
check("pas dans la file d'attente", not any(it["name"] == "ACE_SET_AUTO_DRY" for it in P._PANEL._queue)
      and not any(p.get("command") == "queue" for p in posts))
n = len(macros)
for bad in ({"command": "autodry", "ace": 0, "args": {"RH_START": 40, "RH_END": 45}},
            {"command": "autodry", "ace": 5, "args": {"ENABLE": 1}},
            {"command": "autodry", "ace": 0, "args": {"G28": 1}},
            {"command": "autodry", "ace": 0, "args": {"TEMP": "50; G28"}},
            {"command": "autodry", "ace": 0}):
    P._PANEL.on_message(bad)
time.sleep(0.4)
check("réglages invalides : rien n'est envoyé", len(macros) == n)
P._PANEL.on_message({"command": "autodry", "ace": 0, "args": {"RH_START": 30}})
check("refus de multiACE affiché", wait(lambda: any(not d.get("ok") and "must be BELOW RH_START" in (d.get("text") or "")
                                                    and d["text"].startswith("Echec de Réglage du séchage auto ACE 1")
                                                    for d in dones())))
P._PANEL.on_message({"command": "autodry", "ace": 1, "args": {"MASTER": 0}})
check("suiveur : maître envoyé", wait(lambda: auto_macros()[-1]["args"] == {"ACE": 1, "MASTER": 0}))

# ---------------------------------------------------------------- 3. panneau
from playwright.sync_api import sync_playwright
FAKE = """<script>window.__h=[];window.__p=[];window.orca={postMessage:function(m){window.__p.push(typeof m==="string"?JSON.parse(m):m)},onMessage:function(f){window.__h.push(f)}};</script>"""
SHOTS = os.environ.get("AUTODRY_SHOTS")
def slot(i, col):
    return {"idx": i, "state": "ready", "color": col, "material": "PLA", "source": "rfid"}
def ad(**k):
    d = {"enabled": False, "rh_start": 45.0, "rh_end": 35.0, "temp": 50, "master": -1, "add_time": 60}
    d.update(k)
    return d
def pstate(ace2=True, a0=None, a1=None, running=False):
    a = [{"idx": 0, "connected": True, "temp": 36 if running else 24, "humidity": 52.0 if ace2 else None,
          "has_humidity": ace2, "protocol": "v2" if ace2 else "v1", "has_dryer": True,
          "auto_dry": a0 or ad(enabled=True), "auto_dry_running": running,
          "dryer": {"status": "drying", "target_temp": 50, "remain_time": 7000, "duration": 600} if running else {"status": "stop"},
          "slots": [slot(i, c) for i, c in enumerate(("#E53935", "#2F80D1", "#F2F2F2", "#1E1E1E"))]},
         {"idx": 1, "connected": True, "temp": 23, "humidity": None, "has_humidity": False, "protocol": "v1",
          "has_dryer": True, "auto_dry": a1 or ad(), "auto_dry_running": False, "dryer": {"status": "stop"},
          "slots": [slot(i, c) for i, c in enumerate(("#43A047", "#FDD835", "#8E24AA", "#FB8C00"))]}]
    return {"display_index_base": 1, "mode": "multi", "printer_state": "standby", "aces": a,
            "auto_dry_masters": [0] if ace2 else [],
            "toolheads": [{"idx": i, "filament_detected": False, "ace": None, "slot": None} for i in range(4)],
            "spools": {}, "spool_binding": {}}

for lang in ("fr", "en"):
    P._LANG["v"] = lang
    html = P.i18n_page(P.PANEL.replace("__VERSION__", P.VERSION).replace("<head>", "<head>" + FAKE, 1))
    path = os.path.join(STORE, "panel_%s.html" % lang)
    open(path, "w", encoding="utf-8").write(html)
    fr = lang == "fr"
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path="/usr/bin/google-chrome")
        pg = b.new_page(viewport={"width": 420, "height": 900}, device_scale_factor=2)
        errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto("file://" + path); pg.wait_for_timeout(200)
        send = lambda m: pg.evaluate("m=>window.__h.forEach(f=>f(m))", m)
        sent = lambda: [x for x in pg.evaluate("window.__p") if x.get("command") == "autodry"]
        send({"command": "prefs", "host": "x", "screen": "off", "camera": "off", "compact": False, "auto_home": True, "folds": {}})
        send({"command": "state", "state": pstate(ace2=False), "dry": {}}); pg.wait_for_timeout(200)
        check(lang + " : deux ACE Pro, pas d'ACE 2 : pas de bouton Auto", pg.locator("[data-adry]").count() == 0
              and pg.locator(".tray").count() == 2)
        send({"command": "state", "state": pstate(running=True), "dry": {}}); pg.wait_for_timeout(200)
        b0, b1 = pg.locator('[data-adry="0"]'), pg.locator('[data-adry="1"]')
        check(lang + " : ACE 2 détecté : bouton Auto sur les deux ACE", b0.count() == 1 and b1.count() == 1)
        check(lang + " : ACE 2 activé : « Auto ✓ » allumé", b0.inner_text() == "Auto ✓" and "on" in b0.get_attribute("class")
              and b1.inner_text() == "Auto" and "on" not in (b1.get_attribute("class") or ""))
        tip = b0.get_attribute("title")
        check(lang + " : info-bulle des seuils", tip == ("Séchage auto : démarre au-dessus de 45 %, s’arrête sous 35 % (50 °C)"
              if fr else "Auto-dry: starts above 45 %, stops below 35 % (50 °C)"))
        gut = pg.locator('.tray[data-ace="0"] .gut .drying').inner_text()
        check(lang + " : cycle lancé par le séchage auto", gut.startswith("Auto") and "50" in gut)
        b0.click(); pg.wait_for_timeout(150)
        row = pg.locator('.adrow[data-adrow="0"]')
        txt = row.inner_text()
        check(lang + " : réglages de l'ACE 2", row.count() == 1 and pg.is_checked('[data-ad="0"][data-k="ENABLE"]')
              and pg.input_value('[data-ad="0"][data-k="RH_START"]') == "45" and pg.input_value('[data-ad="0"][data-k="RH_END"]') == "35"
              and pg.input_value('[data-ad="0"][data-k="TEMP"]') == "50" and pg.locator('[data-ad="0"][data-k="MASTER"]').count() == 0)
        check(lang + " : textes ACE 2", (("démarre au-dessus de" in txt and "s’arrête sous" in txt and "chauffe à" in txt and "même OrcaSlicer fermé" in txt)
              if fr else ("starts above" in txt and "stops below" in txt and "heats to" in txt and "even with OrcaSlicer closed" in txt and "Auto-dry" in txt)))
        ends = [int(v) for v in pg.eval_on_selector_all('[data-ad="0"][data-k="RH_END"] option', "o=>o.map(x=>x.value)")]
        starts = [int(v) for v in pg.eval_on_selector_all('[data-ad="0"][data-k="RH_START"] option', "o=>o.map(x=>x.value)")]
        check(lang + " : seuils impossibles absents", max(ends) < 45 and min(starts) > 35)
        pg.select_option('[data-ad="0"][data-k="RH_START"]', "55"); pg.wait_for_timeout(150)
        check(lang + " : départ changé -> envoyé", sent()[-1] == {"command": "autodry", "ace": 0, "args": {"RH_START": 55}})
        ends = [int(v) for v in pg.eval_on_selector_all('[data-ad="0"][data-k="RH_END"] option', "o=>o.map(x=>x.value)")]
        check(lang + " : la liste d'arrêt suit le nouveau départ", pg.input_value('[data-ad="0"][data-k="RH_START"]') == "55"
              and max(ends) == 50)
        send({"command": "state", "state": pstate(running=True), "dry": {}}); pg.wait_for_timeout(150)
        check(lang + " : en attendant la U1, la valeur choisie reste", pg.input_value('[data-ad="0"][data-k="RH_START"]') == "55")
        send({"command": "done", "ok": True, "text": "Terminé : Réglage du séchage auto ACE 1"})
        send({"command": "state", "state": pstate(running=True, a0=ad(enabled=True, rh_start=55)), "dry": {}}); pg.wait_for_timeout(150)
        check(lang + " : réponse de la U1 affichée", pg.input_value('[data-ad="0"][data-k="RH_START"]') == "55"
              and "Done: Auto-dry setting ACE 1" in pg.inner_text("body") if not fr else
              pg.input_value('[data-ad="0"][data-k="RH_START"]') == "55" and "Réglage du séchage auto ACE 1" in pg.inner_text("body"))
        pg.click('[data-ad="0"][data-k="ENABLE"]'); pg.wait_for_timeout(100)
        check(lang + " : décocher -> désactivé", sent()[-1] == {"command": "autodry", "ace": 0, "args": {"ENABLE": 0}})
        # ACE Pro : suit l'ACE 2
        b1.click(); pg.wait_for_timeout(150)
        cb = '[data-ad="1"][data-k="ENABLE"]'
        note = pg.locator('.adrow[data-adrow="1"] .dnote')
        check(lang + " : ACE Pro sans maître : case grisée, à choisir d'abord", pg.is_disabled(cb) and not pg.is_checked(cb)
              and "warnc" in note.get_attribute("class") and note.inner_text() == ("Choisis d’abord l’ACE 2 Pro à suivre." if fr
                                                                                  else "Pick the ACE 2 Pro to follow first."))
        opts = pg.eval_on_selector_all('[data-ad="1"][data-k="MASTER"] option', "o=>o.map(x=>[x.value,x.textContent])")
        check(lang + " : maîtres proposés", opts == [["-1", "aucun ACE 2 Pro" if fr else "no ACE 2 Pro"], ["0", "ACE 1"]])
        check(lang + " : pas de seuils pour l'ACE Pro", pg.locator('[data-ad="1"][data-k="RH_START"]').count() == 0)
        adds = pg.eval_on_selector_all('[data-ad="1"][data-k="ADD_TIME"] option', "o=>o.map(x=>x.textContent)")
        check(lang + " : durées en plus", adds == ["0 min", "15 min", "30 min", "1 h", "1 h 30", "2 h", "3 h", "4 h"]
              and pg.input_value('[data-ad="1"][data-k="ADD_TIME"]') == "60")
        pg.select_option('[data-ad="1"][data-k="MASTER"]', "0"); pg.wait_for_timeout(150)
        check(lang + " : maître choisi -> envoyé, case utilisable", sent()[-1] == {"command": "autodry", "ace": 1, "args": {"MASTER": 0}}
              and not pg.is_disabled(cb))
        pg.click(cb); pg.wait_for_timeout(100)
        check(lang + " : cocher -> activé", sent()[-1] == {"command": "autodry", "ace": 1, "args": {"ENABLE": 1}})
        pg.select_option('[data-ad="1"][data-k="ADD_TIME"]', "90"); pg.wait_for_timeout(100)
        check(lang + " : durée en plus -> envoyée", sent()[-1] == {"command": "autodry", "ace": 1, "args": {"ADD_TIME": 90}})
        send({"command": "done", "ok": True, "text": "ok"})
        st2 = pstate(running=False, a0=ad(enabled=True, rh_start=50, rh_end=40, temp=55),
                     a1=ad(enabled=True, master=0, temp=45, add_time=90))
        send({"command": "state", "state": st2, "dry": {}}); pg.wait_for_timeout(200)
        tip1 = pg.locator('[data-adry="1"]').get_attribute("title")
        check(lang + " : info-bulle du suiveur", tip1 == ("Séchage auto : suit l’humidité de ACE 1 (45 °C, prolongé de 1 h 30)"
              if fr else "Auto-dry: follows ACE 1 (45 °C, runs on for 1 h 30)"))
        check(lang + " : valeurs de la U1 après réponse", pg.input_value('[data-ad="1"][data-k="TEMP"]') == "45"
              and pg.input_value('[data-ad="0"][data-k="RH_END"]') == "40" and pg.is_checked(cb))
        if SHOTS:
            pg.wait_for_timeout(150)
            box = pg.locator("#map").bounding_box()
            pg.screenshot(path=os.path.join(SHOTS, "sechage_auto_%s.png" % lang),
                          clip={"x": 0, "y": box["y"] - 4, "width": 420, "height": box["height"] + 10})
        pg.locator('[data-adry="0"]').click(); pg.wait_for_timeout(100)
        check(lang + " : Auto referme la rangée", pg.locator('.adrow[data-adrow="0"]').count() == 0
              and pg.locator('.adrow[data-adrow="1"]').count() == 1)
        st3 = pstate(running=False, a1=ad(enabled=True, master=2, temp=60))
        send({"command": "state", "state": st3, "dry": {}}); pg.wait_for_timeout(150)
        opts = pg.eval_on_selector_all('[data-ad="1"][data-k="MASTER"] option', "o=>o.map(x=>x.value)")
        check(lang + " : maître absent et 60 °C gardés à l'affichage", "2" in opts and pg.input_value('[data-ad="1"][data-k="MASTER"]') == "2"
              and pg.input_value('[data-ad="1"][data-k="TEMP"]') == "60")
        check(lang + " : pas d'erreur JS", not errs)
        if not fr:
            left = [t for t in pg.locator("#map").inner_text().splitlines()
                    if any(x in t for x in ("Séchage", "démarre", "arrête", "suit", "aucun", "chauffe", "prolong", "Choisis", "capteur"))]
            check("EN : plus de français", not left)
        b.close()
P._LANG["v"] = None
print("\n%s" % ("TOUT OK" if not fails else "%d FAIL" % fails))
sys.exit(1 if fails else 0)
