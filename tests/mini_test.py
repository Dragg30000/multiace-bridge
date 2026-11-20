import sys, types, importlib.util
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
  slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
  base=object, plugin=lambda c: c)
spec = importlib.util.spec_from_file_location("mb", "/home/claude/multiace_bridge/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)
fake = """<script>window.__h=[];window.__p=[];window.orca={postMessage:function(m){window.__p.push(typeof m==="string"?JSON.parse(m):m)},onMessage:function(f){window.__h.push(f)}};</script>"""
open("panel29.html","w").write(mb.PANEL.replace("__VERSION__", mb.VERSION).replace("<head>","<head>"+fake,1).replace("<body>",'<body style="background:#2b2d30">',1))
def slot(i, col, mat="PLA", brand=""):
    return {"idx": i, "state": "ready" if col else "empty", "color": col, "material": mat if col else "", "source": "rfid" if col else "empty", "brand": brand}
st = {"aces": [{"idx": 0, "connected": True, "humidity": 18, "dryer": {"status": "drying", "target_temp": 45, "remain_time": 8820, "duration": 240},
                "slots": [slot(0, "#FFFFFF"), slot(1, "#8D6E63"), slot(2, None), slot(3, "#2E9E4F")]},
               {"idx": 1, "connected": True, "humidity": 41, "dryer": {"status": "drying", "target_temp": 45, "remain_time": 8820, "duration": 240},
                "slots": [slot(0, None), slot(1, "#F7D51D", "PLA", "Snapmaker"), slot(2, "#E02020"), slot(3, "#111111", "PLA", "Elegoo")]}],
      "toolheads": [{"idx": 0, "ace": 0, "slot": 0, "filament_detected": True, "color": "#FFFFFF", "material": "PLA"},
                    {"idx": 1, "ace": 0, "slot": 1, "filament_detected": True, "color": "#8D6E63", "material": "PLA"},
                    {"idx": 2, "ace": 1, "slot": 2, "filament_detected": True, "color": "#E02020", "material": "PLA"},
                    {"idx": 3, "ace": 1, "slot": 3, "filament_detected": True, "color": "#111111", "material": "PLA"}],
      "spools": {}, "spool_binding": {}, "printer_state": "printing", "device_count": 2, "display_index_base": 1}
prep = {"rows": [], "todo": [], "shared": [], "real_known": True, "extra": 0, "real": ["Haut débit"] * 2 + ["Standard", "Haut débit"], "real_src": "u1"}
from playwright.sync_api import sync_playwright
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome")
    pg = b.new_page(viewport={"width": 330, "height": 400}); pg.goto("file:///home/claude/multiace_bridge/test/panel29.html"); pg.wait_for_timeout(200)
    send = lambda m: pg.evaluate("m=>window.__h.forEach(f=>f(m))", m)
    send({"command": "prefs", "host": "u1", "screen": "off", "compact": True, "prep_pos": "top", "auto_home": True})
    send({"command": "state", "state": st, "prep": prep})
    t = pg.inner_text("#mini")
    ok(pg.is_visible("#mini") and not pg.is_visible("#full"), "mode réduit")
    ok(pg.locator("#mini .mrow").count() == 3 and pg.locator("#mini .spool").count() == 12, "têtes + 2 ACE × 4 bobines en couleur")
    ok("✓ Buses OK" in t and "18 %" in t and "41 %" in t and "🔥 45°" in t, "buses, humidité, séchage visibles")
    pg.screenshot(path="v290_mini.png", full_page=True)
    send({"command": "prefs", "host": "u1", "screen": "off", "compact": False, "prep_pos": "top", "auto_home": True})
    send({"command": "state", "state": st, "prep": prep})
    pg.set_viewport_size({"width": 330, "height": 1300})
    ok(pg.evaluate("document.getElementById('prep').parentElement.id") == "prepTop", "carte en haut par défaut")
    pg.click("[data-pmv]")
    ok(pg.evaluate("document.getElementById('prep').parentElement.id") == "prepBottom", "carte déplacée en bas")
    ok({"command": "prefs_set", "prep_pos": "bottom"} in pg.evaluate("window.__p"), "choix mémorisé")
    send({"command": "state", "state": st, "prep": prep})
    ok(pg.evaluate("document.getElementById('prep').parentElement.id") == "prepBottom" and "↑ en haut" in pg.inner_text("#prep"), "reste en bas à l'actualisation")
    pg.screenshot(path="v290_bottom.png", full_page=True)
    b.close()
print("ALL OK")
