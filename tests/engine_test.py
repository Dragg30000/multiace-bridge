import sys, types, tempfile, importlib.util, json, http.server, threading, glob
S = tempfile.mkdtemp()
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object), slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object), base=object, plugin=lambda c: c, host=types.SimpleNamespace(plugin=types.SimpleNamespace(storage=lambda: S)))
sp = importlib.util.spec_from_file_location("mb", "/home/claude/multiace_bridge/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(sp); sp.loader.exec_module(mb)
SRC = open(glob.glob("/home/claude/src/multiACE/**/post_process_virtual_toolheads.py", recursive=True)[0]).read()
def slot(i, col):
    return {"idx": i, "state": "ready" if col else "empty", "color": col, "material": "PLA" if col else "", "source": "rfid" if col else "empty", "brand": ""}
st = {"aces": [{"idx": 0, "slots": [slot(0,"#eff0f1"), slot(1,"#000000"), slot(2,"#e02020"), slot(3,"#009639")]},
               {"idx": 1, "slots": [slot(0,None), slot(1,"#f7d959"), slot(2,"#927968"), slot(3,"#ff8da1")]}],
      "toolheads": [{"idx": i, "manual": False} for i in range(4)], "device_count": 2, "spools": {}, "spool_binding": {}}
g = open("/tmp/g/real.gcode", encoding="utf-8", errors="replace").read(); meta = mb.gcode_meta(g)
# 1) le plugin n'utilise que le moteur livre avec lui, sans aucun reseau
info = mb.prepare_engine("127.0.0.1:1"); assert info["source"] == "embedded", info
eng = mb.load_engine(); assert eng.__name__.endswith("multiace_engine_127"), eng.__name__
# 2) ce moteur est exactement le post-processeur de multiACE (decay71), sans modification
own = open("/home/claude/multiace_bridge/multiace_engine_127.py", encoding="utf-8").read()
import hashlib
body = own.split("\n\n", 1)[1].encode("utf-8")
assert hashlib.sha256(body).hexdigest() == "3a5f52966b431460d32a879d5d0c9234adc132e6de3a0da31fab90575d49f477", "moteur 1.27b modifie"
r1 = mb.analyze_gcode(g, st, "loaded", None, meta); out = r1.pop("gcode")
assert "ACE_SWAP_HEAD" in out
# 3) plus aucun code telecharge ni execute depuis le reseau
code = open("/home/claude/multiace_bridge/multiace_bridge_any.py", encoding="utf-8").read()
for bad in ("pysrc", "exec_module", "b64decode", "zlib", "printer_engine"):
    assert bad not in code, bad
print("swaps", r1["swaps"]); print("ENGINE OK")
