"""Actions au clic dans le mode reduit et sur les pastilles des modules replies."""
import os, sys, types, importlib.util
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
  slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
  base=object, plugin=lambda c: c)
spec = importlib.util.spec_from_file_location("mb", "/home/claude/multiace_bridge/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))
fake = """<script>window.__h=[];window.__p=[];window.orca={postMessage:function(m){window.__p.push(typeof m==="string"?JSON.parse(m):m)},onMessage:function(f){window.__h.push(f)}};</script>"""
open("pop.html", "w").write(mb.PANEL.replace("__VERSION__", mb.VERSION).replace("<head>", "<head>" + fake, 1).replace("<body>", '<body style="background:#2b2d30">', 1))
def slot(i, col): return {"idx": i, "state": "ready" if col else "empty", "color": col, "material": "PLA" if col else "", "source": "rfid" if col else "empty"}
st = {"aces": [{"idx": 0, "connected": True, "humidity": 18, "temp": 31.6, "dryer": {"status": "drying", "target_temp": 45, "remain_time": 8820, "duration": 240},
                "slots": [slot(0, "#FFFFFF"), slot(1, "#8D6E63"), slot(2, None), slot(3, "#2E9E4F")]},
               {"idx": 1, "connected": True, "humidity": 41, "dryer": {"status": "stop"},
                "slots": [slot(0, None), slot(1, "#F7D51D"), slot(2, "#E02020"), slot(3, "#111111")]}],
      "toolheads": [{"idx": i, "ace": a, "slot": s_, "filament_detected": True, "color": c, "material": "PLA"}
                    for i, (a, s_, c) in enumerate([(0, 0, "#FFFFFF"), (0, 1, "#8D6E63"), (1, 2, "#E02020"), (1, 3, "#111111")])],
      "spools": {}, "spool_binding": {}, "printer_state": "ready", "device_count": 2, "display_index_base": 1}
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome")
    pg = b.new_page(viewport={"width": 330, "height": 700}); pg.goto("file://" + os.path.abspath("pop.html")); pg.wait_for_timeout(200)
    send = lambda m: pg.evaluate("m=>window.__h.forEach(f=>f(m))", m)
    posted = lambda: [m for m in pg.evaluate("window.__p") if m.get("command") not in ("prefs_set", "prefs_get", "refresh", None)]
    send({"command": "prefs", "host": "u1", "screen": "off", "compact": True, "prep_pos": "top", "folds": {}, "auto_home": True})
    send({"command": "state", "state": st})
    ok("🌡 32 °C" in pg.inner_text("#mini") and "💧 18 %" in pg.inner_text("#mini") and "41 %" in pg.inner_text("#mini"), "mode réduit : température + humidité de l'ACE")
    pg.screenshot(path="v310_mini.png", full_page=True)
    pg.click('#mini [data-pk="s:0:3"]')
    ok(pg.is_visible("#pop") and "Échanger → T4" in pg.inner_text("#pop"), "bobine verte (slot 4) -> « Échanger → T4 »")
    pg.screenshot(path="v300_pop.png", clip={"x": 0, "y": 0, "width": 330, "height": 330})
    pg.click("#pop button.go")
    ok("Confirmer" in pg.inner_text("#pop") and not posted(), "1er clic : confirmation demandée, rien envoyé")
    pg.click("#pop button.go"); pg.wait_for_timeout(100)
    ok({"command": "swap", "head": 3, "ace": 0, "slot": 3} in posted() and not pg.is_visible("#pop"), "2e clic : échange mis en file, menu fermé")
    pg.click('#mini [data-pk="h:1"]')
    ok("Décharger T2" in pg.inner_text("#pop"), "tête T2 -> « Décharger T2 »")
    pg.mouse.click(5, 690)
    ok(not pg.is_visible("#pop"), "clic ailleurs : menu fermé")
    pg.click('#mini [data-pk="a:0"]')
    ok("🌡 32 °C" in pg.inner_text("#pop") and "💧 18 %" in pg.inner_text("#pop"), "menu de l'ACE : température + humidité")
    ok("Arrêter le séchage" in pg.inner_text("#pop") and "reste 2 h 27 min" in pg.inner_text("#pop"), "ACE 1 en séchage -> « Arrêter le séchage »")
    pg.keyboard.press("Escape"); ok(not pg.is_visible("#pop"), "Échap ferme le menu")
    pg.click('#mini [data-pk="a:1"]'); ok("Sécher 45 °C · 4 h" in pg.inner_text("#pop"), "ACE 2 -> « Sécher 45 °C · 4 h »"); pg.keyboard.press("Escape")
    pg.click('#mini [data-pk="s:1:0"]'); ok("vide" in pg.inner_text("#pop") and pg.locator("#pop button").count() == 0, "slot vide : pas d'action")
    pg.keyboard.press("Escape")
    pg.click('#mini [data-pk="s:0:1"]'); pg.click("#pop [data-pedit]")
    ok(pg.is_visible("#full") and pg.locator(".ed").count() == 1 and {"command": "prefs_set", "screen": "off", "camera": "off", "compact": False} in pg.evaluate("window.__p"),
       "« Modifier… » : panneau complet + éditeur de la bobine")
    # module replie : pastilles cliquables, le repli ne bascule pas
    ok("🌡 32 °C" in pg.inner_text('h4[data-fold="ace0"]'), "module complet : température dans l'en-tête")
    pg.click('h4[data-fold="ace0"]')
    ok("🌡 32 °C" in pg.inner_text('h4[data-fold="ace0"]') and "💧 18 %" in pg.inner_text('h4[data-fold="ace0"]'), "module replié : température + humidité")
    ok("🌡" not in pg.inner_text('h4[data-fold="ace1"]'), "ACE sans température connue : pas de pastille vide")
    pg.screenshot(path="v310_fold.png", clip={"x": 0, "y": 0, "width": 330, "height": 260})
    pg.click('h4[data-fold="ace1"]')
    pg.click('h4[data-fold="ace1"] [data-pk="s:1:1"]')
    ok(pg.is_visible("#pop") and "Échanger → T2" in pg.inner_text("#pop") and pg.locator(".card.ace.folded").count() == 2, "pastille d'un ACE replié : menu, le module reste replié")
    b.close()
print("ALL OK")
