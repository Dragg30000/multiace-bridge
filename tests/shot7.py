import json, sys, types, importlib.util, tempfile, base64, re, struct, zlib
STORE = tempfile.mkdtemp()
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
  slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
  base=object, plugin=lambda c: c, host=types.SimpleNamespace(plugin=types.SimpleNamespace(storage=lambda: STORE)))
spec = importlib.util.spec_from_file_location("mb", "/home/claude/multiace_bridge/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)
# real PNG thumbnail from the user's screenshot
raw = open("/mnt/user-data/uploads/e5d66120-image.png", "rb").read()
from PIL import Image; import io
im = Image.open(io.BytesIO(raw)).crop((475, 110, 590, 225)).resize((200, 200)); buf = io.BytesIO(); im.save(buf, "PNG")
png = base64.b64encode(buf.getvalue()).decode()
thumb = "; thumbnail begin 200x200 %d\n" % len(png) + "\n".join("; " + png[i:i+78] for i in range(0, len(png), 78)) + "\n; thumbnail end\n"
g5 = thumb + open("five.gcode").read().replace("; filament_type = PLA;PLA;PLA;PLA;PLA", "; filament_type = PLA;PLA;PLA;PLA;PLA\n; filament used [g] = 39.1,35.2,61.0,53.3,36.3\n; nozzle_volume_type = Standard,Standard,High Flow,Standard\n; filament_map = 1,2,3,4,4\n; flush_volumes_matrix = " + ",".join(["0" if i == j else "240" for i in range(5) for j in range(5)]) + "\n; flush_multiplier = 1")
def slot(i, col, brand=""):
    return {"idx": i, "state": "ready" if col else "empty", "color": col, "material": "PLA" if col else "", "source": "rfid" if col else "empty", "brand": brand}
st = {"aces": [{"idx": 0, "slots": [slot(0,"#eff0f1"), slot(1,"#000000","Elegoo"), slot(2,"#e02020","Snapmaker"), slot(3,"#009639")]},
               {"idx": 1, "slots": [slot(0,None), slot(1,"#f7d959"), slot(2,"#927968"), slot(3,"#ff8da1")]}],
      "toolheads": [{"idx": i, "manual": False} for i in range(4)], "device_count": 2,
      "spools": {"1": {"weight_g": 640}, "2": {"weight_g": 415}, "3": {"weight_g": 40}, "4": {"weight_g": 723}, "5": {"weight_g": 994}},
      "spool_binding": {"0_0": "1", "0_1": "2", "0_2": "3", "0_3": "4", "1_1": "5"}}
G = open("/tmp/g/real.gcode", encoding="utf-8", errors="replace").read(); meta = mb.gcode_meta(G)
r = mb.analyze_gcode(G, st, "loaded", None, meta); r.pop("gcode")
nozzle = meta["nozzle"]; w = mb.slot_weights(st)
slots = [dict(x, weight=w.get((x["ace"], x["slot"])), head_type=nozzle[x["slot"]]) for x in mb.all_slots_from_state(st)]
d = {"name": "4 inch new grinch nutcracker v1-U1_PLA_11h10m.gcode", "thumb": meta["thumb"], "result": r, "slots": slots, "forced": {}, "busy": False,
     "banner": "Les bobines ont changé : attribution recalculée."}
fake = "<script>window.orca={postMessage:function(){},onMessage:function(){}};</script>"
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome")
    open("assign.html", "w").write(mb.ASSIGN_PAGE.replace("<head>", "<head>" + fake, 1).replace("__DATA__", json.dumps(d, ensure_ascii=False)))
    pg = b.new_page(viewport={"width": 900, "height": 900}); pg.goto("file:///home/claude/multiace_bridge/test/assign.html")
    pg.screenshot(path="v151.png", full_page=True)
    b.close()
print(r["alerts"], r["purge_stamps"], r["swaps"], r["plan"] and r["plan"]["swaps"])
