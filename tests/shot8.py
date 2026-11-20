import json, sys, types, importlib.util, copy
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
  slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
  base=object, plugin=lambda c: c)
spec = importlib.util.spec_from_file_location("mb", "/home/claude/multiace_bridge/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)
st = json.load(open("/home/claude/src/multiACE/tests/fixtures/mock_state.json"))
a2 = copy.deepcopy(st["aces"][0]); a2["idx"] = 1; a2["humidity"] = 31
for s, (c, m, src) in zip(a2["slots"], [("#e53935","PLA","rfid"),("#fdd835","PETG","override"),("#1e88e5","PLA","derived"),(None,"","empty")]):
    s.update(color=c, material=m, source=src, state="empty" if src == "empty" else "ready", brand="SUNLU" if m else "")
a2["dryer"]={"status":"drying","target_temp":50,"duration":240,"remain_time":12677}
st["aces"].append(a2); st["mode"]="multi"; st["aces"][0]["slots"][0]["source"]="override"; st["printer_state"]="ready"
for t in st["toolheads"][1:]: t["filament_detected"]=False
fake = """<script>window.__h=[];window.orca={postMessage:function(){},onMessage:function(f){window.__h.push(f)}};</script>"""
open("panel.html","w").write(mb.PANEL.replace("<head>","<head>"+fake,1).replace("<body>",'<body style="background:#25282c">',1))
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome"); pg = b.new_page(viewport={"width": 360, "height": 900})
    pg.goto("file:///home/claude/multiace_bridge/test/panel.html")
    pg.evaluate("s=>{window.__h.forEach(f=>f({command:'prefs',host:'127.0.0.1:8765',screen:'off',compact:false}));window.__h.forEach(f=>f({command:'state',state:s}))}", st)
    pg.evaluate("()=>{window.__h.forEach(f=>f({command:'done',ok:false,fix:'home',text:\"Échange T1 ← ACE 1 slot 1 : la U1 n'est pas référencée (homing). Clique « Faire le homing puis reprendre » : la U1 fait son Home puis reprend. File en pause (2 action(s) en attente).\"}));window.__h.forEach(f=>f({command:'queue',paused:true,items:[{id:1,label:'Échange T1 ← ACE 1 slot 1',status:'échec'},{id:2,label:'Chargement T2 ← ACE 2 slot 2',status:'attente'},{id:3,label:'Déchargement T3',status:'attente'}]}))}")
    pg.wait_for_timeout(600); pg.screenshot(path="v160_queue.png", clip={"x":0,"y":0,"width":360,"height":620}); b.close()
