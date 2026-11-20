import json, sys, types, importlib.util
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
  slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
  base=object, plugin=lambda c: c)
spec = importlib.util.spec_from_file_location("mb", "/home/claude/multiace_bridge/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)
data = json.load(open("/tmp/attrib_result.json"))
err = {"name": "Gingerbread dragon.gcode", "error": "pas de bobine de la bonne couleur pour : filament 7 (PLA #FDD835), filament 8 (PLA #1E88E5). Le G-code utilise 8 couleurs, 6 bobines sont identifiées, 2 slot(s) libre(s). Charge ces couleurs dans les ACE (ou corrige la couleur d'un slot dans le panneau) puis réexporte."}
fake = """<script>window.orca={postMessage:function(){},onMessage:function(){}};</script>"""
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome")
    for d, out in ((data, "assign.png"), (err, "assign_err.png")):
        open("assign.html", "w").write(mb.ASSIGN_PAGE.replace("<head>", "<head>" + fake, 1).replace("__DATA__", json.dumps(d, ensure_ascii=False)))
        pg = b.new_page(viewport={"width": 860, "height": 720}); pg.goto("file:///home/claude/multiace_bridge/test/assign.html")
        pg.screenshot(path=out, full_page=True); pg.close()
    b.close()
