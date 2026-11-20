import sys, types, tempfile, importlib.util, re
S = tempfile.mkdtemp()
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object), slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object), base=object, plugin=lambda c: c, host=types.SimpleNamespace(plugin=types.SimpleNamespace(storage=lambda: S)))
sp = importlib.util.spec_from_file_location("mb", "/home/claude/multiace_bridge/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(sp); sp.loader.exec_module(mb)
def slot(i, col, brand=""):
    return {"idx": i, "state": "ready" if col else "empty", "color": col, "material": "PLA" if col else "", "source": "rfid" if col else "empty", "brand": brand}
st = {"aces": [{"idx": 0, "slots": [slot(0,"#eff0f1"), slot(1,"#000000"), slot(2,"#e02020"), slot(3,"#009639")]},
               {"idx": 1, "slots": [slot(0,None), slot(1,"#f7d959"), slot(2,"#927968"), slot(3,"#ff8da1")]}],
      "toolheads": [{"idx": i, "manual": False} for i in range(4)], "device_count": 2, "spools": {}, "spool_binding": {}}
g = open("/tmp/g/real.gcode", encoding="utf-8", errors="replace").read()
eng = mb.load_engine()
# 1) real file: no multiplier applied twice
g2 = g.replace("; flush_multiplier = 1,1,1,1", "; flush_multiplier = 1.5,1.5,1.5,1.5")
m1, m2 = mb.gcode_meta(g), mb.gcode_meta(g2)
assert mb.flush_matrices(m1, eng)[0] == mb.flush_matrices(m2, eng)[0], "multiplier must not be reapplied"
# 2) mixed slot 6 = 1 + 3 (0.7/0.3)
mat = re.search(r"^; flush_volumes_matrix = (.*)$", g, re.M).group(1).split(",")
new = []
for b in range(4):
    blk = mat[b*25:(b+1)*25]
    for i in range(6):
        for j in range(6):
            new.append("0" if i == j else (blk[i*5+j] if i < 5 and j < 5 else "300"))
g3 = (g.replace("; filament_colour = #000000FF;#F7D959FF;#DE4343FF;#FFFFFFFF;#61C680FF", "; filament_colour = #000000FF;#F7D959FF;#DE4343FF;#FFFFFFFF;#61C680FF;#6F2222FF")
       .replace("; filament_type = PLA;PLA;PLA;PLA;PLA", "; filament_type = PLA;PLA;PLA;PLA;PLA;PLA\n; filament_is_mixed = 0,0,0,0,0,1\n; filament_mixed_components = \"\";\"\";\"\";\"\";\"\";\"1,3\"\n; filament_mixed_sublayer_ratios = \"\";\"\";\"\";\"\";\"\";\"0.7,0.3\"")
       .replace(re.search(r"^; flush_volumes_matrix = .*$", g, re.M).group(0), "; flush_volumes_matrix = " + ",".join(new)))
m3 = mb.gcode_meta(g3)
print("mixed", m3["mixed"])
assert m3["mixed"] == {5: {"components": [0, 2], "ratios": [0.7, 0.3]}}
M = mb.flush_matrices(m3, eng); assert len(M) == 4 and len(M[0]) == 6
r = mb.analyze_gcode(g3, st, "loaded", None, m3); r.pop("gcode")
assert 5 not in r["used"], r["used"]
print(r["mixed_info"]); print(r["alerts"]); print("swaps", r["swaps"], "stamps", r["purge_stamps"], "plan", r["plan"] and r["plan"]["swaps"])
assert r["mixed_info"] and "filament 1 70 %" in r["mixed_info"][0]["text"]
assert any("Mélange filament 6" in a for a in r["alerts"])   # filament 1 shares T2 (black on slot 2) with ... check
# 3) wrong-size matrix -> no purge table
bad = dict(m1, colours={i: "#000000" for i in range(6)}); assert mb.flush_matrices(bad, eng) is None
print("MIXED OK")
