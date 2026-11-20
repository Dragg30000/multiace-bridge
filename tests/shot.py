import json, sys, types, importlib.util
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
  slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
  base=object, plugin=lambda c: c)
spec = importlib.util.spec_from_file_location("mb", "/home/claude/multiace_bridge/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)
state = json.load(open("/home/claude/src/multiACE/tests/fixtures/mock_state.json"))
# make a 2-ACE scenario realiste
import copy
a2 = copy.deepcopy(state["aces"][0]); a2["idx"] = 1; a2["humidity"] = 31; a2["model"] = "ACE Pro"
for s, (c, m, src) in zip(a2["slots"], [("#e53935","PLA","rfid"),("#fdd835","PETG","override"),("#1e88e5","PLA","derived"),(None,"","empty")]):
    s.update(color=c, material=m, source=src, state="empty" if src == "empty" else "ready", brand="SUNLU" if m else "")
state["aces"].append(a2)
state["preflight_inbox"] = {"pending": True, "name": "Dragon.gcode", "size": 48_200_000}
fake = """<script>window.__h=[];window.orca={postMessage:function(){},onMessage:function(f){window.__h.push(f)}};</script>"""
html = mb.PAGE.replace("<head>", "<head>" + fake, 1)
open("page.html", "w").write(html)
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome"); pg = b.new_page(viewport={"width": 1280, "height": 860})
    pg.goto("file:///home/claude/multiace_bridge/test/page.html")
    pg.evaluate("""s=>{window.__h.forEach(f=>f({type:'settings',host:'192.168.1.50',nozzle:'0.4',last:{name:'Dragon.gcode',size:48200000,ts:Date.now()/1000}}));
                     window.__h.forEach(f=>f({type:'state',host:'192.168.1.50',version:'1.50-pre',state:s}))}""", state)
    pg.screenshot(path="stock.png", full_page=True)
    pg.click("nav button[data-view=send]"); pg.screenshot(path="send.png")
    b.close()
print(json.dumps(state["toolheads"][0])[:300])
