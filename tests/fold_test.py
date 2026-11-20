"""Replier module par module (Avant de trancher, Tetes, chaque ACE) + memorisation."""
import os, sys, types, importlib.util, tempfile
STORE = tempfile.mkdtemp()
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
  slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
  base=object, plugin=lambda c: c, host=types.SimpleNamespace(plugin=types.SimpleNamespace(storage=lambda: STORE)))
spec = importlib.util.spec_from_file_location("mb", "/home/claude/multiace_bridge/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))
# reglage cote plugin : seules des cles connues et des booleens
mb.save_settings(dict(mb.load_settings(), folds={"heads": True, "ace1": True, "evil": True, "prep": "oui"}))
ok(mb.load_settings()["folds"] == {"heads": True, "ace1": True}, "réglage nettoyé : %s" % mb.load_settings()["folds"])
fake = """<script>window.__h=[];window.__p=[];window.orca={postMessage:function(m){window.__p.push(typeof m==="string"?JSON.parse(m):m)},onMessage:function(f){window.__h.push(f)}};</script>"""
open("fold.html", "w").write(mb.PANEL.replace("__VERSION__", mb.VERSION).replace("<head>", "<head>" + fake, 1).replace("<body>", '<body style="background:#2b2d30">', 1))
def slot(i, col): return {"idx": i, "state": "ready" if col else "empty", "color": col, "material": "PLA" if col else "", "source": "rfid" if col else "empty"}
st = {"aces": [{"idx": 0, "connected": True, "humidity": 18, "dryer": {"status": "drying", "target_temp": 45, "remain_time": 8820, "duration": 240},
                "slots": [slot(0, "#FFFFFF"), slot(1, "#8D6E63"), slot(2, None), slot(3, "#2E9E4F")]},
               {"idx": 1, "connected": True, "humidity": 41, "dryer": {"status": "stop"},
                "slots": [slot(0, None), slot(1, "#F7D51D"), slot(2, "#E02020"), slot(3, "#111111")]}],
      "toolheads": [{"idx": i, "ace": a, "slot": s_, "filament_detected": True, "color": c, "material": "PLA"}
                    for i, (a, s_, c) in enumerate([(0, 0, "#FFFFFF"), (0, 1, "#8D6E63"), (1, 2, "#E02020"), (1, 3, "#111111")])],
      "spools": {}, "spool_binding": {}, "printer_state": "ready", "device_count": 2, "display_index_base": 1}
prep = {"rows": [], "todo": [], "shared": [], "real_known": True, "extra": 0, "real": ["Haut débit"] * 4, "real_src": "u1"}
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome")
    pg = b.new_page(viewport={"width": 330, "height": 1300}); pg.goto("file://" + os.path.abspath("fold.html")); pg.wait_for_timeout(200)
    send = lambda m: pg.evaluate("m=>window.__h.forEach(f=>f(m))", m)
    send({"command": "prefs", "host": "u1", "screen": "off", "compact": False, "prep_pos": "top", "folds": {}, "auto_home": True})
    send({"command": "state", "state": st, "prep": prep})
    ok(pg.is_visible("#heads") and pg.locator(".card.ace.folded").count() == 0, "tout déplié au départ")
    pg.click('h4[data-fold="heads"] >> text=Têtes')
    ok(not pg.is_visible("#heads") and pg.locator("#headsMini .spool").count() == 4, "Têtes replié : 4 pastilles dans l'en-tête")
    ok(pg.is_visible("#ua"), "« Tout décharger » reste accessible")
    pg.click('h4[data-fold="ace0"]')
    ok(pg.locator(".card.ace.folded").count() == 1 and pg.locator('h4[data-fold="ace0"] .fmini .spool').count() == 4, "ACE 1 replié : ses 4 bobines en pastilles")
    ok("🔥" in pg.inner_text('h4[data-fold="ace0"]'), "séchage en cours signalé replié")
    pg.click('[data-fold="prep"]')
    ok(not pg.is_visible("#prep .pbody") and "✓" in pg.inner_text("#prep"), "Avant de trancher replié : titre + ✓")
    folds = [m["fold"] for m in pg.evaluate("window.__p") if "fold" in m]
    ok(folds == [{"k": "heads", "on": True}, {"k": "ace0", "on": True}, {"k": "prep", "on": True}], "chaque repli envoyé au plugin : %s" % folds)
    send({"command": "state", "state": st, "prep": prep})
    ok(not pg.is_visible("#heads") and pg.locator(".card.ace.folded").count() == 1 and not pg.is_visible("#prep .pbody"), "reste replié à l'actualisation")
    pg.screenshot(path="v300_fold.png", clip={"x": 0, "y": 0, "width": 330, "height": 560})
    send({"command": "prefs", "host": "u1", "screen": "off", "compact": False, "prep_pos": "top", "folds": {"ace1": True}, "auto_home": True})
    send({"command": "state", "state": st, "prep": prep})
    ok(pg.is_visible("#heads") and pg.locator('.card.ace.folded h4[data-fold="ace1"]').count() == 1, "état restauré depuis le plugin au démarrage")
    pg.click('h4[data-fold="ace1"]')
    ok(pg.locator(".card.ace.folded").count() == 0, "redéplier")
    b.close()
print("ALL OK")
