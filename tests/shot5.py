import json, sys, types, importlib.util, tempfile
STORE = tempfile.mkdtemp()
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
  slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
  base=object, plugin=lambda c: c, host=types.SimpleNamespace(plugin=types.SimpleNamespace(storage=lambda: STORE)))
spec = importlib.util.spec_from_file_location("mb", "/home/claude/multiace_bridge/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)
def slot(i, col, src="rfid", brand=""):
    return {"idx": i, "state": "ready" if col else "empty", "color": col, "material": "PLA" if col else "", "source": src if col else "empty", "brand": brand}
st = {"aces": [{"idx": 0, "slots": [slot(0,"#eff0f1"), slot(1,"#000000",brand="Elegoo"), slot(2,"#8d6e63"), slot(3,"#43a047")]},
               {"idx": 1, "slots": [slot(0,None), slot(1,None), slot(2,"#e53935",brand="Snapmaker"), slot(3,"#f48fb1")]}],
      "toolheads": [{"idx": i, "manual": False} for i in range(4)], "device_count": 2}
g = open("eight.gcode").read()
pages = []
try: mb.analyze_gcode(g, st)
except mb.AttributionError as e:
    pages.append(({"name": "Gingerbread dragon.gcode", "error": str(e), "matches": e.matches, "slots": mb.all_slots_from_state(st), "forced": {}}, "force_err.png"))
r = mb.analyze_gcode(g, st, "loaded", {6: (1, 3), 7: (0, 3)}); r.pop("gcode")
pages.append(({"name": "Gingerbread dragon.gcode", "result": r, "slots": mb.all_slots_from_state(st), "forced": {"6": "1_3", "7": "0_3"}}, "force_ok.png"))
fake = "<script>window.orca={postMessage:function(){},onMessage:function(){}};</script>"
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome")
    for d, out in pages:
        open("assign.html", "w").write(mb.ASSIGN_PAGE.replace("<head>", "<head>" + fake, 1).replace("__DATA__", json.dumps(d, ensure_ascii=False)))
        pg = b.new_page(viewport={"width": 980, "height": 760}); pg.goto("file:///home/claude/multiace_bridge/test/assign.html")
        pg.screenshot(path=out, full_page=True)
        if out == "force_err.png":
            pg.click(".pick[data-t='6'] .pk"); pg.screenshot(path="force_menu.png", full_page=True)
            pg.click(".pick[data-t='6'] .menu div[data-v='1_3']"); pg.screenshot(path="force_pick.png", full_page=True)
        pg.close()
    b.close()

