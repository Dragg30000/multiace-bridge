import json, sys, types, importlib.util, tempfile, re
STORE = tempfile.mkdtemp()
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
  slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
  base=object, plugin=lambda c: c, host=types.SimpleNamespace(plugin=types.SimpleNamespace(storage=lambda: STORE)))
spec = importlib.util.spec_from_file_location("mb", "/home/claude/multiace_bridge/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)
def slot(i, col, brand=""):
    return {"idx": i, "state": "ready" if col else "empty", "color": col, "material": "PLA" if col else "", "source": "rfid" if col else "empty", "brand": brand}
def st(a1, a2): return {"aces": [{"idx": 0, "slots": [slot(i, c) for i, c in enumerate(a1)]}, {"idx": 1, "slots": [slot(i, c) for i, c in enumerate(a2)]}],
                        "toolheads": [{"idx": i, "manual": False} for i in range(4)], "device_count": 2}
g5 = open("five.gcode").read()
fake = "<script>window.orca={postMessage:function(){},onMessage:function(){}};</script>"
pages = []
for state, mode, out in ((st(["#ffffff", "#000000", "#e53935", "#43a047"], [None, "#f7d959", None, None]), "loaded", "plan.png"),
                         (st(["#ffffff", "#000000", "#e53935", "#43a047"], [None, "#f7d959", None, None]), "optimize", "plan_applied.png"),
                         (st(["#ffffff", "#000000", "#e53935", "#43a047"], ["#000000", "#f7d959", None, None]), "loaded", "dup.png")):
    r = mb.analyze_gcode(g5, state, mode); r.pop("gcode")
    pages.append(({"name": "4 inch new grinch nutcracker.gcode", "result": r, "slots": mb.all_slots_from_state(state), "forced": {}}, out))
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome")
    for d, out in pages:
        open("assign.html", "w").write(mb.ASSIGN_PAGE.replace("<head>", "<head>" + fake, 1).replace("__DATA__", json.dumps(d, ensure_ascii=False)))
        pg = b.new_page(viewport={"width": 900, "height": 760}); pg.goto("file:///home/claude/multiace_bridge/test/assign.html")
        if out == "plan.png": pg.click("#mode")
        pg.screenshot(path=out, full_page=True); pg.close()
    b.close()
