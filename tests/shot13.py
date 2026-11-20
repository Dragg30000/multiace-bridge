import json, sys, types, importlib.util
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
  slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
  base=object, plugin=lambda c: c)
spec = importlib.util.spec_from_file_location("mb", "/home/claude/multiace_bridge/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)
fake = """<script>window.__h=[];window.orca={postMessage:function(){},onMessage:function(f){window.__h.push(f)}};</script>"""
open("panel28.html","w").write(mb.PANEL.replace("__VERSION__", mb.VERSION).replace("<head>","<head>"+fake,1).replace("<body>",'<body style="background:#2b2d30">',1))
def slot(i, col, mat="PLA", brand=""):
    return {"idx": i, "state": "ready" if col else "empty", "color": col, "material": mat if col else "", "source": "rfid" if col else "empty", "brand": brand}
st = {"aces": [{"idx": 0, "connected": True, "humidity": 18, "dryer": {"status": "drying", "target_temp": 45, "remain_time": 9480, "duration": 240},
                "slots": [slot(0, "#FFFFFF"), slot(1, "#8D6E63"), slot(2, None), slot(3, "#2E9E4F")]},
               {"idx": 1, "connected": True, "humidity": 41, "dryer": {"status": "stop"},
                "slots": [slot(0, None), slot(1, "#F7D51D", "PLA", "Snapmaker"), slot(2, "#E02020"), slot(3, "#111111", "PLA", "Elegoo")]}],
      "toolheads": [{"idx": 0, "ace": 0, "slot": 0, "filament_detected": True, "color": "#FFFFFF", "material": "PLA"},
                    {"idx": 1, "ace": 0, "slot": 1, "filament_detected": True, "color": "#8D6E63", "material": "PLA"},
                    {"idx": 2, "ace": 1, "slot": 2, "filament_detected": True, "color": "#E02020", "material": "PLA"},
                    {"idx": 3, "ace": 1, "slot": 3, "filament_detected": True, "color": "#111111", "material": "PLA", "subtype": "Basic"}],
      "spools": {"1": {"weight_g": 635}, "2": {"weight_g": 683}, "3": {"weight_g": 717}, "4": {"weight_g": 410}},
      "spool_binding": {"0_0": "1", "0_1": "2", "0_3": "3", "1_3": "4"}, "printer_state": "ready", "device_count": 2, "display_index_base": 1}
prep = {"rows": [], "todo": [], "shared": [], "real_known": True, "extra": 0, "real": ["Haut débit"] * 2 + ["Standard", "Haut débit"], "real_src": "u1"}
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome")
    pg = b.new_page(viewport={"width": 330, "height": 1180}); pg.goto("file:///home/claude/multiace_bridge/test/panel28.html"); pg.wait_for_timeout(200)
    send = lambda m: pg.evaluate("m=>window.__h.forEach(f=>f(m))", m)
    send({"command": "prefs", "host": "u1", "screen": "off", "compact": False, "auto_home": True, "printer_engine": True, "ace_guard": True})
    send({"command": "state", "state": st, "prep": prep})
    pg.wait_for_timeout(200)
    pg.screenshot(path="v280_panel.png", full_page=True)
    b.close()
print("OK")
