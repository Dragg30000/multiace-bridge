"""Buse par tete : risque detecte, envoi bloque sans confirmation, fenetre (liste triee, case a cocher)."""
import json, sys, types, importlib.util, tempfile
STORE = tempfile.mkdtemp()
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
  slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
  base=object, plugin=lambda c: c, host=types.SimpleNamespace(plugin=types.SimpleNamespace(storage=lambda: STORE)))
spec = importlib.util.spec_from_file_location("mb", "/home/claude/multiace_bridge/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))

def slot(i, col):
    return {"idx": i, "state": "ready" if col else "empty", "color": col, "material": "PLA" if col else "", "source": "rfid" if col else "empty"}
def st(a1, a2):
    return {"aces": [{"idx": 0, "slots": [slot(i, c) for i, c in enumerate(a1)]}, {"idx": 1, "slots": [slot(i, c) for i, c in enumerate(a2)]}],
            "toolheads": [{"idx": i, "manual": False} for i in range(4)], "device_count": 2, "printer_state": "ready"}
def gc(grams):
    return open("five.gcode").read().replace("; filament_type = PLA;PLA;PLA;PLA;PLA", "; filament_type = PLA;PLA;PLA;PLA;PLA\n; filament used [g] = " + grams +
        "\n; nozzle_volume_type = Standard,Standard,High Flow,Standard\n; filament_map = 1,2,3,4,4")
g = gc("50.0,70,10,10,10")
good = st(["#ffffff", "#000000", "#e53935", "#43a047"], [None, "#f7d959", None, None])
bad = st(["#ffffff", "#000000", "#43a047", "#e53935"], [None, "#f7d959", None, None])   # rouge (tranche T3 Haut debit) sur T4 Standard
r = mb.analyze_gcode(g, good); ok(r["nozzle_risk"] == [], "bonnes buses -> aucun risque")
r = mb.analyze_gcode(g, bad); ok(r["nozzle_risk"] == [2, 4], "rouge et vert (10 g) sur la mauvaise buse -> risque : %s" % r["nozzle_risk"])
r = mb.analyze_gcode(gc("50.0,70,2,10,2"), bad); ok(r["nozzle_risk"] == [], "moins de 5 g -> pas de blocage (alerte seulement)")
ok(any("buse" in a for a in r["alerts"]), "l'alerte reste affichee")

# envoi bloque cote plugin
w = mb.AssignmentWindow(); w.job = {"id": 1, "path": "x", "name": "a.gcode", "host": "127.0.0.1:9"}
w.result = {"path": "x", "signature": "s", "job": 1, "mode": "loaded", "nozzle_risk": [2, 4]}
replies = []; w._reply = lambda okk, text, **k: replies.append((okk, text)); w._busy = True
w._send_file("print", 1, None, False)
ok(replies and not replies[-1][0] and "mauvais type de buse" in replies[-1][1], "lancement refusé sans confirmation : %s" % replies[-1][1])
w._busy = True; w._send_file("upload", 1, None, False)
ok(not replies[-1][0] and "mauvais type de buse" in replies[-1][1], "envoi sans lancer refusé aussi")
w._busy = True; w._send_file("upload", 1, None, True)
ok("mauvais type de buse" not in replies[-1][1], "avec confirmation : on passe à la suite (%s)" % replies[-1][1])

# fenetre
r = mb.analyze_gcode(g, bad); r.pop("gcode")
nozzle = mb.gcode_meta(g)["nozzle"]
slots = [dict(x, weight=None, head_type=nozzle[x["slot"]]) for x in mb.all_slots_from_state(bad)]
d = {"name": "test.gcode", "result": r, "slots": slots, "forced": {}, "busy": False, "banner": None, "prefs": {"bed": True}}
fake = "<script>window.__p=[];window.orca={postMessage:function(m){window.__p.push(typeof m==='string'?JSON.parse(m):m)},onMessage:function(){}};</script>"
open("nozzle.html", "w").write(mb.ASSIGN_PAGE.replace("<head>", "<head>" + fake, 1).replace("__DATA__", json.dumps(d, ensure_ascii=False)))
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome")
    pg = b.new_page(viewport={"width": 900, "height": 1000}); pg.goto("file://" + __import__("os").path.abspath("nozzle.html")); pg.wait_for_timeout(300)
    ok("Buses de la U1 : T1 Standard · T2 Standard · T3 Haut débit · T4 Standard" in pg.inner_text("body"), "ligne des buses par tête")
    ok(pg.is_disabled("button[data-a=print]") and pg.is_disabled("button[data-a=upload]"), "lancer / envoyer désactivés")
    ok("Mauvais type de buse" in pg.inner_text(".card.stop") and "sous-extrusion" in pg.inner_text(".card.stop"), "carte d'arrêt explicite")
    # menu du rouge (filament 3) : la couleur d'abord, puis la buse
    pick = pg.locator('.pick[data-t="2"]'); pick.locator(".pk").click()
    items = pick.locator(".menu div[data-v]").all_inner_texts()
    ok(items[1].startswith("Rouge") and "buse ≠" in items[1], "pas de rouge sur une tête Haut débit : le rouge reste en premier (avec l'avertissement)")
    ok(not any(x.startswith("Vert") for x in items[1:2]), "jamais une autre couleur avant la bonne")
    ok("bonne buse" in items[2] and "→ T3" in items[2], "ensuite les autres couleurs avec la bonne buse : %s" % items[2][:50])
    pick.locator(".pk").click()
    pg.screenshot(path="v230_block.png", full_page=True)
    pg.check("#nozok")
    ok(not pg.is_disabled("button[data-a=print]") and not pg.is_disabled("button[data-a=upload]"), "case cochée -> boutons actifs")
    pg.click("button[data-a=print]"); pg.click("button[data-a=print]")
    sent = [m for m in pg.evaluate("window.__p") if m.get("a") == "print"]
    ok(sent and sent[-1]["nozzle_ok"] is True, "confirmation transmise au plugin")
    b.close()
two = st(["#ffffff", "#000000", "#43a047", "#e53935"], [None, "#f7d959", "#e53935", None])
r2 = mb.analyze_gcode(g, two); r2.pop("gcode")
slots2 = [dict(x, weight=None, head_type=nozzle[x["slot"]]) for x in mb.all_slots_from_state(two)]
d2 = dict(d, result=r2, slots=slots2)
open("nozzle2.html", "w").write(mb.ASSIGN_PAGE.replace("<head>", "<head>" + fake, 1).replace("__DATA__", json.dumps(d2, ensure_ascii=False)))
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome")
    pg = b.new_page(viewport={"width": 900, "height": 1000}); pg.goto("file://" + __import__("os").path.abspath("nozzle2.html")); pg.wait_for_timeout(300)
    m3 = [m for m in r2["matches"] if m["t"] == 2][0]
    ok((m3["ace"], m3["slot"]) == (1, 2) and not m3["nozzle_warn"], "deux rouges : l'automatique prend celui de la bonne buse (ACE 2 slot 3)")
    pick = pg.locator('.pick[data-t="2"]'); pick.locator(".pk").click()
    items = pick.locator(".menu div[data-v]").all_inner_texts()
    ok(items[1].startswith("Rouge") and "bonne buse" in items[1] and items[2].startswith("Rouge") and "buse ≠" in items[2], "rouge bonne buse, puis rouge mauvaise buse")
    pick.locator(".pk").click()
    b.close()
print("ALL OK")
