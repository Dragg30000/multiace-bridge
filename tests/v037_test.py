"""0.37.0 : outils virtuels (filaments 5+), « C'est fait » de la Disposition finale, file multiACE, calibration du chemin."""
import sys, re, json, time, os
exec(open("/home/claude/prive/test/u1code_test.py").read().split("plans = {k")[0])
from playwright.sync_api import sync_playwright
ok_ = ok
def ok(c, m):
    ok_(c, m)
    if not c:
        sys.exit(1)

# ---------- fausse U1 : file, config, etat, slot-override, macros
QUEUE, POSTS, DELS, CFG = [], [], [], {"per_ace_params": {}}
STATE = {"printer_state": "ready", "aces": [], "toolheads": []}
_get, _post = H.do_GET, H.do_POST
def do_GET(self):
    if self.path.endswith("/queue"):
        return self._j(200, {"queue": QUEUE}) if MODE.get("queue", True) else self._j(404, {"detail": "Not Found"})
    if self.path.endswith("/config"):
        return self._j(200, CFG)
    if self.path.endswith("/state"):
        return self._j(200, STATE)
    return _get(self)
def do_POST(self):
    n = int(self.headers.get("Content-Length") or 0); data = self.rfile.read(n); UP.append((self.path, data))
    if self.path.endswith("/server/files/upload"):
        m = re.search(rb'filename="([^"]+)"', data)
        if b'name="path"' in data:
            return self._j(201, {"result": {"item": {"path": "multiace_queue/" + m.group(1).decode(), "root": "gcodes"}}})
        return self._j(201, {"result": {"item": {"path": m.group(1).decode()}}})
    if self.path.endswith("/queue"):
        body = json.loads(data); POSTS.append(body)
        if MODE.get("qfail"):
            return self._j(400, {"detail": "invalid queue path"})
        QUEUE.append(dict(body, id="q1")); return self._j(200, {"ok": True})
    POSTS.append({"_path": self.path, **(json.loads(data) if data[:1] == b"{" else {})})
    return self._j(200, {"ok": True})
def do_DELETE(self):
    DELS.append(self.path); self._j(200, {"ok": True})
H.do_GET, H.do_POST, H.do_DELETE = do_GET, do_POST, do_DELETE

# ---------- 1. outils virtuels
def slot(i, col, src="rfid"):
    return {"idx": i, "state": "ready" if col else "empty", "color": col, "material": "PLA" if col else "",
            "source": src if col else "empty"}
HD, SD = "Haut débit", "Standard"
st = {"aces": [{"idx": 0, "slots": [slot(i, c) for i, c in enumerate(["#FFFFFF", "#000000", "#E53935", "#43A047"])]},
               {"idx": 1, "slots": [slot(i, c) for i, c in enumerate(["#F7D959", None, "#1E88E5", "#8D6E63"])]}],
      "mode": "multi", "tool_map": {"6": [1, 2]}, "device_count": 2}
cols = ["#FFFFFFFF", "#000000FF", "#E53935FF", "#43A047FF", "#FFFFFFFF", "#123456FF", "#1E88E5FF", "#43A047FF", "#F7D959FF", "#00FF00FF"]
real = [HD, HD, SD, HD]
a = mb.slicing_advice(st, real, cols, [HD, HD, SD, HD])
v = {r["t"]: r for r in a["virtual"]}
ok(a["extra"] == 0 and sorted(v) == [4, 5, 6, 7, 8, 9], "filaments 5 à 10 vérifiés (plus « non vérifiés »)")
ok((v[4]["ace"], v[4]["slot"], v[4]["head"], v[4]["match"], v[4]["mapped"]) == (0, 0, 0, True, False), "filament 5 -> formule multiACE : MMU 1 slot 1 -> T1, blanc ✓")
ok(not v[5]["match"] and v[5]["spool_color"] == "#000000", "filament 6 -> MMU 1 slot 2 : bobine noire ≠ bleu nuit")
ok(v[6]["mapped"] and (v[6]["ace"], v[6]["slot"], v[6]["head"], v[6]["need"]) == (1, 2, 2, SD) and v[6]["match"], "filament 7 -> table multiACE : MMU 2 slot 3 -> T3 Standard, bleu ✓")
ok((v[8]["ace"], v[8]["slot"], v[8]["match"]) == (1, 0, True), "filament 9 -> MMU 2 slot 1 jaune ✓")
ok(v[9]["empty"] and (v[9]["ace"], v[9]["slot"]) == (1, 1), "filament 10 -> MMU 2 slot 2 vide signalé")
st_head = dict(st, mode="head", head_ace={"0": 1, "1": 0})
ok(mb.virtual_tool_rows(st_head, real, cols, [])[0]["head"] == 1 and mb.virtual_tool_rows(st_head, real, cols, [])[4]["head"] == 0, "mode tête : la tête câblée à l'ACE")
old = dict(st); old.pop("tool_map")
ok(mb.slicing_advice(old, real, cols, [])["virtual"] is None and mb.slicing_advice(old, real, cols, [])["extra"] == 6, "multiACE 1.27b (pas d'outils virtuels) : comme avant")
ok(mb.slicing_advice(st, real, cols[:4], [])["virtual"] is None, "4 filaments : rien de plus")

# ---------- 4. calibration du chemin (lecture de /api/config)
CFG["per_ace_params"] = {"0": {"retract_length": "900", "swap_retract_length": "850"},
                         "1": {"retract_length_2": "800", "swap_retract_length_2": "760", "retract_length_3": "800"}}
cal = mb.path_calibration(c, force=True)
ok(all(cal["0_%d" % s] for s in range(4)), "ACE 1 calibré au niveau de l'ACE -> 4 slots calibrés")
ok(cal["1_2"] and not cal["1_3"] and not cal["1_0"], "ACE 2 : slot 3 calibré, slot 4 incomplet, slot 1 non : %s" % {k: cal[k] for k in ("1_0", "1_2", "1_3")})
ok(not cal["2_0"], "ACE absent du fichier -> non calibré (la valeur globale [ace] ne compte pas)")
CFG["per_ace_params"] = {"0": {"retract_length": "0", "swap_retract_length": "850"}}
ok(not mb.path_calibration(c, force=True)["0_0"], "valeur 0 = non calibré")
ok(mb.path_calibration(c) is mb._CALIB_CACHE[c.host][1], "gardé 60 s")

fake = """<script>window.__h=[];window.__p=[];window.orca={postMessage:function(m){window.__p.push(typeof m==="string"?JSON.parse(m):m)},onMessage:function(f){window.__h.push(f)}};</script>"""
open("/home/claude/testdata/v037_panel.html", "w").write(mb.PANEL.replace("__VERSION__", mb.VERSION).replace("<head>", "<head>" + fake, 1))
pst = json.load(open("/home/claude/src/multiACE/tests/fixtures/mock_state.json"))
pst["tool_map"] = {}
calib = {"%d_%d" % (a_["idx"], s_["idx"]): (s_["idx"] != 1) for a_ in pst["aces"] for s_ in a_["slots"]}
prep = dict(mb.slicing_advice(pst, real, cols[:6], [HD, HD, SD, HD]), real=real, real_src="u1", manual=real)
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome")
    pg = b.new_page(viewport={"width": 340, "height": 1400}); pg.goto("file:///home/claude/testdata/v037_panel.html"); pg.wait_for_timeout(200)
    send = lambda msg: pg.evaluate("m=>window.__h.forEach(f=>f(m))", msg)
    send({"command": "state", "state": pst, "prep": prep, "calib": calib}); pg.wait_for_timeout(100)
    body = pg.inner_text("body")
    nonempty = sum(1 for a_ in pst["aces"] for s_ in a_["slots"] if s_["idx"] == 1 and not (s_.get("state") == "empty" or s_.get("source") == "empty"))
    ok(pg.locator("#map svg.paths rect").count() == nonempty and nonempty > 0, "« chemin non calibré » sur les voies non calibrées (%d)" % nonempty)
    first_nc = [a_["idx"] for a_ in pst["aces"] for s_ in a_["slots"] if s_["idx"] == 1 and not (s_.get("state") == "empty" or s_.get("source") == "empty")][0]
    pg.click('[data-pk="s:%d:1"]' % first_nc); pg.wait_for_timeout(50)
    ok("Config, puis Calibration" in pg.inner_text("#sheet"), "renvoi vers multiACE Config, puis Calibration")
    pg.click("#sheet [data-close]")
    ok("Filaments 5 et plus" in pg.inner_text("#prep"), "carte « Avant de trancher » : section filaments 5+")
    pg.click("text=Filaments 5 et plus"); pg.wait_for_timeout(50)
    t = pg.inner_text("#prep")
    ok("Filament 5" in t and "Filament 6" in t and "Slicer filament → MMU / Slot" in t, "filaments 5 et 6 listés avec leur slot multiACE")
    pg.screenshot(path="/home/claude/prive/test/v370_panel.png")
    send({"command": "state", "state": pst, "prep": prep}); pg.wait_for_timeout(50)
    ok(pg.locator(".badge.nocal").count() == 0, "sans lecture de la config : aucun badge")
    b.close()

# ---------- 3. file multiACE
W = mb._U1PF; sent = []
W._send = lambda d: sent.append(d)
W._reply = lambda ok__, text, final=False, step=None: sent.append({"done": ok__, "text": text, "step": step})
W.start(g, "real.gcode", host, delay=0); time.sleep(8)
d = [x for x in sent if x.get("report")][-1]
ok(d.get("can_queue") is True, "file multiACE détectée (/api/queue)")
UP.clear(); POSTS.clear(); W._print("slicer", {"bed": True}, {}, "queue")
up = [u for u in UP if u[0].endswith("/server/files/upload")]
ok(up and b'name="path"\r\n\r\nmultiace_queue\r\n' in up[-1][1] and b"print" not in up[-1][1].split(b"Content-Type: application/octet-stream")[0].split(b'name="path"')[0], "fichier préparé déposé dans gcodes/multiace_queue, sans lancer")
q = POSTS[-1]
ok(q["path"].startswith("multiace_queue/") and q["filename"] == "real_multiACE.gcode" and q["mode"] == "slicer", "entrée de file : %s" % {k: q[k] for k in ("filename", "path", "mode")})
ok(isinstance(q["used_slots"], list) and q["used_slots"] and all(len(x) == 2 for x in q["used_slots"]), "slots utilisés envoyés (vérifiés par la U1 au lancement) : %s" % q["used_slots"])
ok(sent[-1]["done"] and "file multiACE" in sent[-1]["text"] and "Print Hub" in sent[-1]["text"], "message : %s" % sent[-1]["text"])
ok(re.fullmatch(r"multiace_queue/[0-9a-f]{12}_real_multiACE\.gcode", q["path"]), "nom unique comme multiACE (12 hex + nom)")
MODE["qfail"] = True; DELS.clear(); W._print("slicer", {}, {}, "queue"); MODE["qfail"] = False
ok(not sent[-1]["done"] and DELS and DELS[-1].startswith("/server/files/gcodes/multiace_queue/"), "file refusée -> fichier retiré de la U1, erreur affichée")
UP.clear(); W._print("slicer", {}, {"2": 6}, "queue")
ok(POSTS[-1]["estimate"] is None and POSTS[-1]["swaps"] is None, "bobines imposées : pas d'estimation « avant tes choix » dans la file")
MODE["queue"] = False; sent.clear(); W.start(g, "real.gcode", host, delay=0); time.sleep(8)
ok([x for x in sent if x.get("report")][-1].get("can_queue") is False, "multiACE sans file (1.27b) : bouton absent")
MODE["queue"] = True

# ---------- 2. « C'est fait » : l'identite suit la bobine deplacee
W.load = {"ident": {"0_1": {"material": "PETG", "brand": "SUNLU", "subtype": "Matte", "color": "#123456", "source": "override", "spool": "5"},
                    "0_2": {"material": "PLA", "brand": "", "subtype": "", "color": "#e02020", "source": "rfid", "spool": None}}}
STATE.update(aces=[{"idx": 0, "slots": [slot(0, "#cccccc", None), slot(1, None), slot(2, "#e02020"), slot(3, None)]}],
             spool_binding={"0_1": 5})
POSTS.clear(); DELS.clear(); sent.clear()
W._moved({"step": 2, "from_ace": 0, "from_slot": 1, "to_ace": 0, "to_slot": 0})
ov = [x for x in POSTS if x.get("_path", "").endswith("/slot-override")]
mac = [(x.get("name"), x.get("args")) for x in POSTS if x.get("_path", "").endswith("/macro")]
ok(ov and ov[0]["ace"] == 0 and ov[0]["slot"] == 0 and ov[0]["material"] == "PETG" and ov[0]["color"] == "#123456" and ov[0]["subtype"] == "Matte", "identité posée sur le nouveau slot (slot-override)")
ok(DELS == ["/multiace/api/slot-override/0/1"], "étiquette retirée de l'ancien slot : %s" % DELS)
ok(mac[:2] == [("ACE_SPOOL_ASSIGN", {"ACE": 0, "SLOT": 1}), ("ACE_SPOOL_ASSIGN", {"ACE": 0, "SLOT": 0, "ID": "5"})] and mac[-1][0] == "MULTIACE_REFRESH_OVERRIDES", "bobine de la table déplacée : %s" % mac)
ok(sent[-1]["done"] and sent[-1]["step"] == 2, "étape notée")
POSTS.clear(); sent.clear(); W._moved({"step": 1, "from_ace": 0, "from_slot": 1, "to_ace": 0, "to_slot": 3})
ok(not sent[-1]["done"] and "vide" in sent[-1]["text"] and not POSTS, "slot d'arrivée vide -> rien écrit, « pose d'abord la bobine »")
POSTS.clear(); DELS.clear(); W._moved({"step": 0, "from_ace": 0, "from_slot": 2, "to_ace": 0, "to_slot": 0})
ok(not [x for x in POSTS if x.get("_path", "").endswith("/slot-override")] and not DELS and sent[-1]["done"], "bobine RFID : pas d'étiquette, elle se relit seule")
POSTS.clear(); W._moved({"step": 0, "from_ace": 0, "from_slot": 1, "to_ace": 0, "to_slot": 1}); W._moved({"step": "x"}); W._moved({"step": 0, "from_ace": 9, "from_slot": 1, "to_ace": 0, "to_slot": 0})
ok(not POSTS, "demandes invalides ignorées")
STATE["printer_state"] = "printing"; POSTS.clear(); W._moved({"step": 0, "from_ace": 0, "from_slot": 1, "to_ace": 0, "to_slot": 0})
ok(not POSTS and not sent[-1]["done"], "pendant une impression : refusé"); STATE["printer_state"] = "ready"

# rendu : boutons par etape, rechargement quand tout est fait
rep = {"plans": {"slicer": {"feasible": True, "swaps": 6, "mapping": [{"t": 0, "slot": {"ace": 0, "slot": 1, "color": "#123456", "material": "PETG"}, "tier": "exact_hex"},
                                                                        {"t": 1, "slot": {"ace": 0, "slot": 2, "color": "#e02020", "material": "PLA"}, "tier": "exact_hex"}]},
                 "optimize": {"feasible": True, "swaps": 1, "mapping": [{"t": 0, "slot": {"ace": 0, "slot": 0, "color": "#123456"}, "tier": "planned"},
                                                                         {"t": 1, "slot": {"ace": 0, "slot": 3, "color": "#e02020"}, "tier": "planned"}]}},
       "slicer_colors": [{"t": 0, "hex": "#123456"}, {"t": 1, "hex": "#e02020"}],
       "live_slots": [{"ace": 0, "slot": 1, "color": "#123456", "material": "PETG"}, {"ace": 0, "slot": 2, "color": "#e02020", "material": "PLA"}], "num_aces": 1}
D = {"name": "x.gcode", "report": rep, "labels": mb.PLAN_LABELS, "prefs": {}, "info": {"sliced": [], "grams": [], "order": []}, "load": {"slots": {}, "real": real, "dia": "0.4"}, "can_force": True, "can_queue": True}
open("/home/claude/testdata/v037_u1.html", "w").write(mb.U1_PAGE.replace("<head>", "<head>" + fake, 1).replace("__DATA__", json.dumps(D)))
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome")
    pg = b.new_page(viewport={"width": 1100, "height": 1300}); pg.goto("file:///home/claude/testdata/v037_u1.html"); pg.wait_for_timeout(200)
    pg.click("input[value=optimize]"); pg.wait_for_timeout(50)
    ok(pg.locator("[data-mv]").count() == 2, "un bouton « C’est fait » par déplacement")
    ok(pg.is_visible("#qu") and pg.is_disabled("#qu"), "« Mettre dans la file multiACE » visible, bloqué tant que les bobines ne sont pas en place")
    pg.screenshot(path="/home/claude/prive/test/v370_layout.png", full_page=True)
    pg.locator("[data-mv]").first.click(); msgs = pg.evaluate("window.__p")
    ok(msgs[-1]["a"] == "moved" and (msgs[-1]["from_slot"], msgs[-1]["to_slot"]) in ((1, 0), (2, 3)), "clic -> message « moved » : %s" % msgs[-1])
    s0 = msgs[-1]["step"]
    pg.evaluate("m=>window.__h.forEach(f=>f(m))", {"type": "done", "ok": True, "text": "Bobine notée", "step": s0}); pg.wait_for_timeout(50)
    ok(pg.locator("text=✓ fait").count() == 1 and pg.locator("[data-mv]").count() == 1, "étape marquée « ✓ noté »")
    pg.locator("[data-mv]").first.click(); s1 = pg.evaluate("window.__p")[-1]["step"]
    pg.evaluate("m=>window.__h.forEach(f=>f(m))", {"type": "done", "ok": True, "text": "Bobine notée", "step": s1}); pg.wait_for_timeout(50)
    ok(pg.evaluate("window.__p")[-1]["a"] == "reload", "toutes les étapes faites -> rechargement automatique")
    pg.click("input[value=slicer]") if not pg.is_disabled("input[value=slicer]") else None
    b.close()
D["report"]["plans"].pop("optimize"); D["can_queue"] = False
open("/home/claude/testdata/v037_u1b.html", "w").write(mb.U1_PAGE.replace("<head>", "<head>" + fake, 1).replace("__DATA__", json.dumps(D)))
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome"); pg = b.new_page(); pg.goto("file:///home/claude/testdata/v037_u1b.html"); pg.wait_for_timeout(200)
    ok(pg.locator("#qu").count() == 0, "sans file multiACE : pas de bouton")
    b.close()
# traduction anglaise : rien de francais dans les nouveaux textes
mb._LANG["v"] = "en"
html = mb.i18n_page(mb.U1_PAGE.replace("<head>", "<head>" + fake, 1).replace("__DATA__", json.dumps(dict(D, can_queue=True))))
open("/home/claude/testdata/v037_en.html", "w").write(html)
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome"); pg = b.new_page(); pg.goto("file:///home/claude/testdata/v037_en.html"); pg.wait_for_timeout(300)
    ok("Put in the multiACE queue" in pg.inner_text("body"), "bouton traduit : Put in the multiACE queue")
    b.close()
mb._LANG["v"] = None
print("v037 OK")

# ---------- 0.37.1 : 1er export d'une nouvelle copie -> attendre l'autorisation « open » d'Orca
mb.orca.slicing = types.SimpleNamespace(Step=types.SimpleNamespace(psGCodePostProcess="pp"), SlicingPipelineCapabilityBase=object)
mb.orca.PluginResult = types.SimpleNamespace(RecoverableError="rec")
_R = lambda k: (lambda *a: types.SimpleNamespace(kind=k, msg=a))
mb.orca.ExecutionResult = types.SimpleNamespace(success=_R("success"), failure=_R("failure"), skipped=_R("skipped"), skip=_R("skipped"))
tries = {"n": 0}; real_keep = mb.keep_last_gcode
def keep_denied(src, name):
    tries["n"] += 1
    if tries["n"] < 3:
        raise PermissionError(13, "audit: open pending", src)
    return real_keep(src, name)
mb.keep_last_gcode = keep_denied
started, inbox = [], []
mb._U1PF.start = lambda *a, **k: started.append(a)
_sg = mb.MultiAce.send_gcode; mb.MultiAce.send_gcode = lambda self, *a, **k: inbox.append(a)
mb.save_settings(dict(mb.load_settings(), host=host))
ctx = types.SimpleNamespace(step="pp", gcode_path=g, host="", output_name="perm.gcode")
pipe = mb.SendToPreflight(); pipe._config = lambda: {}
mb._recent_sends.clear(); r = pipe.execute(ctx)
ok(tries["n"] == 3 and started and not inbox, "autorisation en attente -> on attend (%d essais), fenêtre de la U1, pas le Preflight multiACE" % tries["n"])
mb.keep_last_gcode = lambda s, n: (_ for _ in ()).throw(OSError("disque plein")); started.clear(); mb._recent_sends.clear()
pipe.execute(ctx); ok(inbox and not started, "autre erreur de copie -> repli sur le Preflight multiACE comme avant")
mb.keep_last_gcode = real_keep; mb.MultiAce.send_gcode = _sg
print("v0371 OK")

# ---------- 0.38.0 : « Optimisé » impossible avec les bobines chargees -> proposition de disposition de la U1
LIVE["live_slots"] = [{"ace": 0, "slot": i, "material": "PLA", "color": c} for i, c in enumerate(["#eff0f1", "#000000", "#e02020", "#009639"])] + [{"ace": 1, "slot": i, "material": "PLA", "color": c} for i, c in [(1, "#f7d959"), (2, "#927968"), (3, "#ff8da1")]]
LIVE["head_ctx"] = {"mode": "multi"}
rep, live, sha = mb.u1_report(c, g, "real.gcode")
op = rep["plans"]["optimize"]
ok(op.get("feasible") and op.get("suggested") and op.get("live_reason") and all(m["tier"] == "planned" for m in op["mapping"]), "optimisé : disposition proposée par le code de la U1 (%s échanges au lieu de %s)" % (op["swaps"], rep["plans"]["slicer"]["swaps"]))
ok(mb.placement_todo(rep, "optimize", None), "lancement bloqué tant que les bobines ne sont pas déplacées")
ok(mb.core_restored if hasattr(mb, "core_restored") else mb._u1code["core"].build_one_plan.__name__ == "build_one_plan", "code de la U1 remis intact après l'analyse")
D2 = {"name": "x.gcode", "report": rep, "labels": mb.PLAN_LABELS, "prefs": {}, "info": mb.slice_info(g), "load": {"slots": {}, "real": real, "dia": "0.4"}, "can_force": True, "can_queue": True}
open("/home/claude/testdata/v038.html", "w").write(mb.U1_PAGE.replace("<head>", "<head>" + fake, 1).replace("__DATA__", json.dumps(D2)))
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome"); pg = b.new_page(viewport={"width": 1100, "height": 1400}); pg.goto("file:///home/claude/testdata/v038.html"); pg.wait_for_timeout(300)
    ok(not pg.is_disabled("input[value=optimize]"), "« Optimisé » n'est plus grisé")
    pg.click("input[value=optimize]"); pg.wait_for_timeout(100); t = pg.inner_text("body")
    ok("déplaçant des bobines" in t and "dans cet ordre" in t.lower() and "bobines pour le plan" in t.lower() and pg.locator("[data-mv]").count() >= 1, "carte Disposition finale avec étapes et « C’est fait »")
    pg.screenshot(path="/home/claude/prive/test/v380_optimize.png", full_page=True)
    b.close()
print("v038 OK")

# ---------- 0.38.1 : couleur du plan sur aucune bobine (cas du Grinch : vert absent, marron « même matière »)
def S_(a, s, c): return {"ace": a, "slot": s, "color": c, "material": "PLA"}
NO, JA, RO, BL, MA, BE, VE = "#000000", "#f7d959", "#e53935", "#ffffff", "#8d6e63", "#1e88e5", "#43a047"
repG = {"plans": {"slicer": {"feasible": True, "swaps": 97, "mapping": [
            {"t": 0, "slot": S_(1, 3, NO), "tier": "name_exact"}, {"t": 1, "slot": S_(1, 1, JA), "tier": "name_exact"},
            {"t": 2, "slot": S_(1, 2, RO), "tier": "name_exact"}, {"t": 3, "slot": S_(0, 0, BL), "tier": "name_exact"},
            {"t": 4, "slot": S_(0, 1, MA), "tier": "fallback"}]},
        "optimize": {"feasible": True, "suggested": True, "swaps": 33, "mapping": [
            {"t": 0, "slot": S_(0, 0, NO), "tier": "planned"}, {"t": 1, "slot": S_(0, 1, JA), "tier": "planned"},
            {"t": 2, "slot": S_(0, 2, RO), "tier": "planned"}, {"t": 4, "slot": S_(0, 3, VE), "tier": "planned"},
            {"t": 3, "slot": S_(1, 0, BL), "tier": "planned"}]}},
        "slicer_colors": [{"t": i, "hex": h + "ff", "material": "PLA"} for i, h in enumerate([NO, JA, RO, BL, VE])],
        "live_slots": [S_(0, 0, BL), S_(0, 1, MA), S_(0, 3, BE), S_(1, 1, JA), S_(1, 2, RO), S_(1, 3, NO)], "num_aces": 2}
ok(4 in mb.placement_todo(repG, "optimize"), "Python : le vert (absent des ACE) reste à faire même si le marron « même matière » est chargé")
D3 = dict(D2, report=repG, info={"sliced": [], "grams": [], "order": []})
open("/home/claude/testdata/v0381.html", "w").write(mb.U1_PAGE.replace("<head>", "<head>" + fake, 1).replace("__DATA__", json.dumps(D3)))
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome"); pg = b.new_page(viewport={"width": 1100, "height": 1500}); pg.goto("file:///home/claude/testdata/v0381.html"); pg.wait_for_timeout(300)
    pg.click("input[value=optimize]"); pg.wait_for_timeout(100)
    steps = pg.locator("ul.st li").all_inner_texts()
    print("\n".join(steps))
    ok(not any("Marron filament" in x for x in steps), "le marron n'est plus déplacé à la place du vert")
    ok(any("pose une bobine" in x and "Vert" in x and "Sors d’abord le Bleu" in x and "voie 4" in x for x in steps), "étape : retirer le bleu, poser une bobine verte dans ACE 1 · slot 4")
    ok(any("Sors d’abord le Marron" in x and "Jaune" in x for x in steps), "le marron est retiré pour le jaune")
    ok("1 à poser" in pg.inner_text("body"), "titre : 4 déplacées et 1 à poser")
    pg.screenshot(path="/home/claude/prive/test/v381_layout.png", full_page=True)
    pg.locator("[data-nw]").click(); m = pg.evaluate("window.__p")[-1]
    ok(m["a"] == "newspool" and (m["t"], m["to_ace"], m["to_slot"]) == (4, 0, 3), "clic -> newspool : %s" % m)
    b.close()
W.report = repG; POSTS.clear(); sent.clear()
STATE.update(printer_state="ready", aces=[{"idx": 0, "slots": [slot(0, None), slot(1, None), slot(2, None), slot(3, "#cccccc", None)]}])
W._newspool({"step": 4, "t": 4, "to_ace": 0, "to_slot": 3})
ov = [x for x in POSTS if x.get("_path", "").endswith("/slot-override")]
ok(ov and ov[0]["color"] == VE and ov[0]["material"] == "PLA" and (ov[0]["ace"], ov[0]["slot"]) == (0, 3) and sent[-1]["done"], "nouvelle bobine : vert PLA posé sur ACE 1 · slot 4")
POSTS.clear(); W._newspool({"step": 4, "t": 4, "to_ace": 0, "to_slot": 0})
ok(not POSTS and not sent[-1]["done"], "slot vide -> refusé")
print("v0381 OK")

# ---------- 0.38.3 : bobines imposees -> echanges et duree recalcules par le code de la U1
LIVE["live_slots"] = [{"ace": 0, "slot": i, "material": "PLA", "color": c} for i, c in enumerate(["#eff0f1", "#000000", "#e02020", "#009639"])] + [{"ace": 1, "slot": i, "material": "PLA", "color": c} for i, c in [(1, "#f7d959"), (2, "#927968"), (3, "#ff8da1")]]
rep, live, sha = mb.u1_report(c, g, "real.gcode")
cap = mb._LAST_CAPTURE.get(g)
pp_, core_, _ = mb.u1_code(c)
sl = rep["plans"]["slicer"]
same = mb.forced_estimate(core_, rep, cap, {}, rep["live_slots"])
ok(same and same["swaps"] == sl["swaps"] and abs(same["estimate"]["total_s"] - sl["estimate"]["total_s"]) < 1, "sans choix : mêmes chiffres que la U1 (%s échanges)" % sl["swaps"])
t0 = sl["mapping"][0]["t"]; cur = sl["mapping"][0]["slot"]; other = next(x for x in rep["live_slots"] if (x["ace"], x["slot"]) != (cur["ace"], cur["slot"]))
fe = mb.forced_estimate(core_, rep, cap, {str(t0): other["ace"] * 4 + other["slot"]}, rep["live_slots"])
ok(fe and fe["swaps"] != sl["swaps"] or fe["estimate"]["total_s"] != sl["estimate"]["total_s"], "bobine imposée : recalculé (%s échanges, %d s au lieu de %s, %d s)" % (fe["swaps"], fe["estimate"]["total_s"], sl["swaps"], sl["estimate"]["total_s"]))
ok(mb.forced_estimate(core_, rep, cap, {str(t0): 31}, rep["live_slots"]) is None, "slot inconnu -> rien")
W.report = rep; W.job = dict(W.job, path=g); posted = []
W.window = types.SimpleNamespace(post=lambda d: posted.append(d))
W._forced_est({"forced": {str(t0): other["ace"] * 4 + other["slot"]}, "key": "k1"})
ok(posted and posted[-1]["type"] == "fest" and posted[-1]["key"] == "k1" and posted[-1]["res"]["swaps"] == fe["swaps"], "fenêtre : réponse « fest »")
W.window = None
D4 = {"name": "x.gcode", "report": rep, "labels": mb.PLAN_LABELS, "prefs": {}, "info": mb.slice_info(g), "load": {"slots": {}, "real": real, "dia": "0.4"}, "can_force": True}
open("/home/claude/testdata/v0383.html", "w").write(mb.U1_PAGE.replace("<head>", "<head>" + fake, 1).replace("__DATA__", json.dumps(D4)))
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome"); pg = b.new_page(viewport={"width": 1100, "height": 1300}); pg.goto("file:///home/claude/testdata/v0383.html"); pg.wait_for_timeout(300)
    pg.click("#fo"); pg.locator("[data-pk]").first.click(); pg.wait_for_timeout(100)
    pg.locator("[data-ch]:not([data-v=''])").nth(1).click(); pg.wait_for_timeout(100)
    m = pg.evaluate("window.__p")[-1]
    ok(m["a"] == "forced_est" and m["forced"], "choix d'une bobine -> demande de recalcul")
    ok("calcul avec tes choix" in pg.inner_text(".stats"), "en attente : « calcul avec tes choix… »")
    pg.evaluate("m=>window.__h.forEach(f=>f(m))", {"type": "fest", "key": m["key"], "res": {"swaps": 123, "estimate": {"total_s": 36000, "added_s": 3600}}}); pg.wait_for_timeout(100)
    t = pg.inner_text(".stats")
    ok("123" in t and "10h" in t and "avec tes choix" in t, "chiffres « avec tes choix » affichés")
    ok("123" in pg.inner_text(".plans"), "« Comme tranché » montre aussi 123 échanges")
    b.close()
print("v0383 OK")

# ---------- 0.39.0 : « Optimisé » / « Par couche » avec tes bobines imposees (optimiseur de la U1)
LIVE["live_slots"] = [{"ace": 0, "slot": i, "material": "PLA", "color": c} for i, c in enumerate(["#eff0f1", "#000000", "#e02020", "#009639"])] + [{"ace": 1, "slot": i, "material": "PLA", "color": c} for i, c in [(0, "#ffffff"), (1, "#f7d959"), (2, "#927968"), (3, "#ff8da1")]]
rep, live, sha = mb.u1_report(c, g, "real.gcode")
pp_, core_, _ = mb.u1_code(c)
cap, calls = mb._LAST_CAPTURE.get(g), mb._LAST_CALLS.get(g)
_a, _kw = calls["optimize"]
op = core_.build_one_plan(*_a, **_kw)          # plan « Optimisé » de la U1 avec les bobines en place
ok(calls and set(calls) == {"optimize", "layer"} and op.get("feasible"), "arguments des plans de la U1 gardés (optimisé en place : %s échanges)" % op.get("swaps"))
# 0.39.1 : bobines en place mais d'autres couleurs -> la disposition de la U1 est proposee
off = mb.colours_off(op, rep["plans"]["slicer"], mb.used_filaments(mb.slice_info(g)))
ro = rep["plans"]["optimize"]
ok(off and ro.get("suggested") and [x["t"] for x in ro.get("live_off") or []] == off and ro.get("live_swaps") == op["swaps"],
   "couleurs différentes avec les bobines en place (filaments %s) -> disposition de la U1 proposée" % [t + 1 for t in off])
okc = dict(op, mapping=[dict(r, slot=next(m["slot"] for m in rep["plans"]["slicer"]["mapping"] if m["t"] == r["t"])) for r in op["mapping"]])
ok(mb.colours_off(okc, rep["plans"]["slicer"], None) == [], "bonnes bobines -> rien à proposer")
row = op["mapping"][0]; t = row["t"]; h = row["slot"]["slot"]
alt = next(x for x in rep["live_slots"] if x["slot"] != h and x["material"] == "PLA")
forced = {str(t): alt["ace"] * 4 + alt["slot"]}
fp = mb.forced_plans(core_, calls, cap, forced, rep["live_slots"])
fo = fp.get("optimize") or {}
print("forcé", forced, "->", {k: (v.get("feasible"), v.get("swaps"), v.get("reason")) for k, v in fp.items()})
if fo.get("feasible"):
    r0 = next(r for r in fo["mapping"] if r["t"] == t)
    ok((r0["slot"]["ace"], r0["slot"]["slot"], r0["tier"]) == (alt["ace"], alt["slot"], "manual"), "filament %d sur la bobine imposée (ACE %d · slot %d)" % (t + 1, alt["ace"] + 1, alt["slot"] + 1))
    ok(fo["swaps"] >= op["swaps"] and fo.get("estimate", {}).get("total_s"), "optimisé avec ton choix : %s échanges (sans : %s), durée recalculée par la U1" % (fo["swaps"], op["swaps"]))
    heads = {}
    for r in fo["mapping"]:
        heads.setdefault(r["slot"]["slot"], set()).add((r["slot"]["ace"], r["slot"]["slot"]))
    ok(all(r["slot"]["slot"] in (0, 1, 2, 3) for r in fo["mapping"]), "disposition sur les bobines chargées")
else:
    ok(fo.get("reason"), "pas possible -> raison donnée : %s" % fo.get("reason"))
same = mb.forced_plans(core_, calls, cap, {str(t): row["slot"]["ace"] * 4 + row["slot"]["slot"]}, rep["live_slots"])["optimize"]
ok(same["feasible"] and same["swaps"] == op["swaps"], "imposer la bobine que la U1 avait choisie : même optimisé (%s échanges)" % same["swaps"])
ok(mb.forced_plans(core_, calls, cap, {str(t): 30}, rep["live_slots"]) == {}, "bobine inconnue -> rien")
# envoi : imprime par le chemin des choix manuels de la U1, avec toute la disposition
seen = []
_prep = mb.u1_prepare
mb.u1_prepare = lambda client, path, name, plan_name, prefs, expected, report=None, forced=None: seen.append((plan_name, forced)) or (_ for _ in ()).throw(mb.MultiAceError("stop test"))
W.report = rep; W.job = dict(W.job, path=g); sent.clear()
W._reply = lambda ok__, text, final=False, step=None: sent.append({"done": ok__, "text": text})
W._print("optimize", {}, dict(same and {str(t): row["slot"]["ace"] * 4 + row["slot"]["slot"]}), "upload")
mb.u1_prepare = _prep
exp = {str(r["t"]): r["slot"]["ace"] * 4 + r["slot"]["slot"] for r in same["mapping"]}
ok(seen and seen[0][0] == "slicer" and seen[0][1] == exp, "envoi : plan « Comme tranché » de la U1 avec toute la disposition optimisée (remap)")
# le fichier prepare a le meme remap que le plan optimise de la U1 (sans choix) : meme fichier
import filecmp, shutil
f_opt = mb.u1_prepare(c, g, "real.gcode", "optimize", {}, mb._signature(live), report=rep); shutil.copy(f_opt, "/tmp/opt_a.gcode")
f_rm = mb.u1_prepare(c, g, "real.gcode", "slicer", {}, mb._signature(live), report=rep, forced={str(r["t"]): r["slot"]["ace"] * 4 + r["slot"]["slot"] for r in op["mapping"]})
ok(filecmp.cmp("/tmp/opt_a.gcode", f_rm, shallow=False), "même fichier imprimé que le plan « Optimisé » de la U1 (chemin des choix manuels)")
# fenetre : Optimise reste cliquable avec un choix
D5 = {"name": "x.gcode", "report": rep, "labels": mb.PLAN_LABELS, "prefs": {}, "info": mb.slice_info(g), "load": {"slots": {}, "real": real, "dia": "0.4"}, "can_force": True}
open("/home/claude/testdata/v0390.html", "w").write(mb.U1_PAGE.replace("<head>", "<head>" + fake, 1).replace("__DATA__", json.dumps(D5)))
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome"); pg = b.new_page(viewport={"width": 1100, "height": 1300}); pg.goto("file:///home/claude/testdata/v0390.html"); pg.wait_for_timeout(300)
    pg.click("input[value=optimize]"); pg.wait_for_timeout(100)
    pg.click("#fo"); pg.locator("[data-pk]").first.click(); pg.wait_for_timeout(100)
    pg.locator("[data-ch]:not([data-v=''])").nth(2).click(); pg.wait_for_timeout(100)
    m = pg.evaluate("window.__p")[-1]
    ok("calcul avec tes choix" in pg.inner_text(".plans"), "pendant le calcul : « calcul avec tes choix… »")
    res = mb.forced_estimate(core_, rep, cap, m["forced"], rep["live_slots"]) or {}
    res["plans"] = mb.forced_plans(core_, calls, cap, m["forced"], rep["live_slots"])
    pg.evaluate("m=>window.__h.forEach(f=>f(m))", {"type": "fest", "key": m["key"], "res": res}); pg.wait_for_timeout(150)
    feas = res["plans"]["optimize"].get("feasible")
    ok(pg.is_disabled("input[value=optimize]") != bool(feas), "« Optimisé » cliquable si possible avec ton choix (%s)" % feas)
    if feas:
        ok(pg.is_checked("input[value=optimize]") and "avec tes choix" in pg.inner_text(".plans"), "reste sur « Optimisé · avec tes choix »")
        pg.click("#mo"); pg.click("#up"); mm = pg.evaluate("window.__p")[-1]
        ok(mm["plan"] == "optimize" and mm["forced"] == m["forced"], "envoi : plan optimize + ton choix")
    pg.screenshot(path="/home/claude/prive/test/v390.png", full_page=True)
    b.close()
print("v0390 OK")

# ---------- 0.40.0 : animation Mange-3MF au lancement de l'impression
DA = {"name": "Grinch.gcode", "report": rep, "labels": mb.PLAN_LABELS, "prefs": {}, "info": mb.slice_info(g), "load": {"slots": {}, "real": real, "dia": "0.4"}, "can_force": True}
for lang in ("fr", "en"):
    mb._LANG["v"] = lang
    html = mb.U1_PAGE.replace("<head>", "<head>" + fake, 1).replace("__DATA__", json.dumps(DA))
    if lang == "en":
        html = mb.i18n_page(html)
    open("/home/claude/testdata/v0400_%s.html" % lang, "w").write(html)
mb._LANG["v"] = None
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome"); pg = b.new_page(viewport={"width": 1000, "height": 800})
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("file:///home/claude/testdata/v0400_fr.html"); pg.wait_for_timeout(300)
    send_ = lambda m: pg.evaluate("m=>window.__h.forEach(f=>f(m))", m)
    send_({"type": "done", "ok": True, "final": False, "text": "envoyé sur la U1 sans lancer"}); pg.wait_for_timeout(100)
    ok(pg.locator("#m3ov").count() == 0, "envoi sans lancer : pas d'animation")
    send_({"type": "done", "ok": False, "final": False, "text": "Envoi annulé"}); pg.wait_for_timeout(100)
    ok(pg.locator("#m3ov").count() == 0, "échec : pas d'animation")
    send_({"type": "done", "ok": True, "final": True, "text": "Impression lancée avec le plan « Optimisé »."}); pg.wait_for_timeout(3600)
    ok(pg.locator("#m3ov svg").count() == 1 and "Impression lancée !" in pg.inner_text("#m3ov") and "Grinch.gcode" in pg.inner_text("#m3ov"), "impression lancée : la mascotte mange le G-code")
    pg.screenshot(path="/home/claude/prive/test/v400_anim.png")
    pg.click("#m3ov"); pg.wait_for_timeout(100)
    ok(pg.locator("#m3ov").count() == 0 and "Impression lancée avec" in pg.inner_text("body"), "clic : fermée, le message reste")
    send_({"type": "done", "ok": True, "final": True, "text": "Impression lancée."}); pg.wait_for_timeout(6200)
    ok(pg.locator("#m3ov").count() == 0, "se ferme toute seule (~6 s)")
    ok(not errs, "aucune erreur JS : %s" % errs)
    pg2 = b.new_page(viewport={"width": 1000, "height": 800}); pg2.goto("file:///home/claude/testdata/v0400_en.html"); pg2.wait_for_timeout(300)
    pg2.evaluate("m=>window.__h.forEach(f=>f(m))", {"type": "done", "ok": True, "final": True, "text": "Impression lancée."}); pg2.wait_for_timeout(3700)
    ok("Print started!" in pg2.inner_text("#m3ov") and "Enjoy your meal, U1!" in pg2.inner_text("#m3ov"), "anglais : Print started! / Enjoy your meal, U1!")
    pg3 = b.new_page(viewport={"width": 1000, "height": 800}, reduced_motion="reduce"); pg3.goto("file:///home/claude/testdata/v0400_fr.html"); pg3.wait_for_timeout(300)
    pg3.evaluate("m=>window.__h.forEach(f=>f(m))", {"type": "done", "ok": True, "final": True, "text": "Impression lancée."}); pg3.wait_for_timeout(300)
    ok(pg3.is_visible("#m3ov h2"), "mouvements réduits (Windows) : image fixe")
    pg3.wait_for_timeout(3500); ok(pg3.locator("#m3ov").count() == 0, "mouvements réduits : fermée après 3,5 s")
    # « Sans rien deplacer » (0.39.1) dans la carte
    pg4 = b.new_page(viewport={"width": 1100, "height": 1300}); pg4.goto("file:///home/claude/testdata/v0400_fr.html"); pg4.wait_for_timeout(300)
    pg4.click("input[value=optimize]"); pg4.wait_for_timeout(100)
    ok("Sans rien déplacer, la U1 imprimerait" in pg4.inner_text(".lay"), "carte : ce que la U1 ferait sans rien déplacer")
    b.close()
print("v0400 OK")

# ---------- 0.40.0 : nom de l'imprimante en haut du panneau
_pb = getattr(mb.orca.host, "preset_bundle", None)
mb.orca.host.preset_bundle = lambda: types.SimpleNamespace(current_printer_preset=lambda: types.SimpleNamespace(name="Snapmaker U1 (0.4 nozzle) - multiACE (modified)"))
ok(mb.printer_label() == "Snapmaker U1 (0.4 nozzle) - multiACE", "nom de l'imprimante d'Orca, sans « (modified) »")
mb.orca.host.preset_bundle = lambda: (_ for _ in ()).throw(RuntimeError("x"))
ok(mb.printer_label() == "", "illisible -> vide")
if _pb is not None:
    mb.orca.host.preset_bundle = _pb
open("/home/claude/testdata/v0400_panel.html", "w").write(mb.PANEL.replace("__VERSION__", mb.VERSION).replace("<head>", "<head>" + fake, 1))
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome"); pg = b.new_page(viewport={"width": 340, "height": 900})
    pg.goto("file:///home/claude/testdata/v0400_panel.html"); pg.wait_for_timeout(200)
    ok(pg.inner_text("#pname") == "U1", "avant la 1re lecture : « U1 »")
    pg.evaluate("m=>window.__h.forEach(f=>f(m))", {"command": "state", "state": pst, "printer": "Snapmaker U1 (0.4 nozzle) - multiACE"}); pg.wait_for_timeout(100)
    ok(pg.inner_text("#pname") == "Snapmaker U1 (0.4 nozzle) - multiACE", "en haut du panneau : le nom de l'imprimante")
    box = pg.locator("#pname").bounding_box(); st_ = pg.locator("#st").bounding_box()
    ok(box["y"] + box["height"] <= st_["y"] + 1 and pg.is_visible("#hd"), "nom sur sa propre ligne, boutons toujours visibles")
    pg.screenshot(path="/home/claude/prive/test/v400_panel.png", clip={"x": 0, "y": 0, "width": 340, "height": 120})
    b.close()
print("v0400b OK")

# ---------- 0.40.0 : nom donne a la U1 (lu dans la U1 via /api/version de multiACE)
class _C:
    host = "h-dev"
    def __init__(self, v): self.v = v
    def get_json(self, path, timeout=None):
        assert path == "/version"
        if isinstance(self.v, Exception):
            raise self.v
        return self.v
mb._DEV_CACHE.clear()
d = mb.device_info(_C({"web": "1.90", "printer": {"device_name": "U1 Dragg\n", "firmware_version": "1.2.3", "machine_type": "U1"}}))
ok(d == {"name": "U1 Dragg", "fw": "1.2.3", "type": "U1"}, "nom de la U1 et firmware lus dans la U1 : %s" % d)
ok(mb.device_info(_C({"web": "1.90"})) is d, "gardé 60 s")
mb._DEV_CACHE.clear()
ok(mb.device_info(_C({"web": "1.27b", "printer": {}})) == {}, "pas de nom -> vide")
mb._DEV_CACHE.clear()
ok(mb.device_info(_C(OSError("x"))) == {}, "U1 injoignable -> vide")
print("v0400c OK")
