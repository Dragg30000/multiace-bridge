import sys, types, tempfile, importlib.util, os, re
S = tempfile.mkdtemp()
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object), slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object), base=object, plugin=lambda c: c, host=types.SimpleNamespace(plugin=types.SimpleNamespace(storage=lambda: S)))
sp = importlib.util.spec_from_file_location("mb", "/home/claude/multiace_bridge/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(sp); sp.loader.exec_module(mb)
def slot(i, col):
    return {"idx": i, "state": "ready" if col else "empty", "color": col, "material": "PLA" if col else "", "source": "rfid" if col else "empty", "brand": ""}
st = {"aces": [{"idx": 0, "slots": [slot(0,"#eff0f1"), slot(1,"#000000"), slot(2,"#e02020"), slot(3,"#009639")]},
               {"idx": 1, "slots": [slot(0,None), slot(1,"#f7d959"), slot(2,"#927968"), slot(3,"#ff8da1")]}],
      "toolheads": [{"idx": i, "manual": False} for i in range(4)], "device_count": 2,
      "spools": {"6": {"id": "6", "color": "000000", "pa_matrix": {"0.4_standard": 0.0312}}, "8": {"id": "8", "color": "F7D959"}},
      "spool_binding": {"0_1": "6", "1_1": "8"}}
g = open("/tmp/g/real.gcode", encoding="utf-8", errors="replace").read(); meta = mb.gcode_meta(g)
print("nozzle_raw", meta["nozzle_raw"])
r = mb.analyze_gcode(g, st, "loaded", None, meta); out = r.pop("gcode")
print("start", r["start_heads"]); print("pa", r["pa_info"])
assert r["start_heads"] and all("head" in x for x in r["start_heads"])
blk = re.search(r"; multiACE auto-load: load.*?; multiACE auto-load: end", out, re.S).group(0)
assert len(r["start_heads"]) == blk.count("ACE_SWAP_HEAD")
black = [p for p in r["pa_info"] if p["color"].upper().startswith("#000000")][0]
assert black["pa"] == 0.0312 and black["spool"] == "6", black
src = os.path.join(S, "a.gcode"); open(src, "w").write(out)
dst = os.path.join(S, "b.gcode")
# 1) plateau oui, flux non
mb.apply_print_prefs(src, dst, bed_mesh=True, flow_cal=False, camera=False)
o = open(dst).read()
assert o.split("\n")[1] == "SET_PRINT_PREFERENCES BED_LEVEL=1 FLOW_CALIBRATE=0 TIME_LAPSE_CAMERA=0 FORCE=1"
assert "FLOW_CALIBRATE EXTRUDER=" not in o.replace("SM_PRINT_FLOW_CALIBRATE EXTRUDER", "")
assert len(o) > len(out) and re.search(r"^SET_PRINT_AUTO_BED_LEVELING ENABLE=1", o, re.M)
# 2) flux sur T1 et T3 seulement, deplace apres le chargement auto
mb.apply_print_prefs(src, dst, bed_mesh=False, flow_cal=True, camera=True, heads={0, 2})
o = open(dst).read(); L = o.split("\n")
assert L[1] == "SET_PRINT_PREFERENCES BED_LEVEL=0 FLOW_CALIBRATE=1 TIME_LAPSE_CAMERA=1 FORCE=1"
assert not re.search(r"^SET_PRINT_AUTO_BED_LEVELING", o, re.M) and "; multiACE Bridge disabled: SET_PRINT_AUTO_BED_LEVELING" in o
cal = re.findall(r"^FLOW_CALIBRATE EXTRUDER=(\d)$", o, re.M); print("calibrated heads", cal)
assert sorted(cal) == ["0", "2"]
end = o.index("; multiACE auto-load: end"); assert re.search(r"^FLOW_CALIBRATE EXTRUDER=", o, re.M).start() > end
assert not re.search(r"^\s*SM_PRINT_FLOW_CALIBRATE", o, re.M) and "; multiACE moved: SM_PRINT_FLOW_CALIBRATE" in o
assert not re.search(r"^SET_PRINT_PREFERENCES", "\n".join(L[2:]), re.M)
print("PREFS OK")
