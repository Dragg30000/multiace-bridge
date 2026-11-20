import json, sys, types, importlib.util, tempfile, time, re
STORE = tempfile.mkdtemp()
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
  slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
  base=object, plugin=lambda c: c, host=types.SimpleNamespace(plugin=types.SimpleNamespace(storage=lambda: STORE)))
spec = importlib.util.spec_from_file_location("mb", "/home/claude/multiace_bridge/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)
exec(open("shot7.py").read().split("def slot")[1].join(["def slot",""]) if False else "")
def slot(i, col, brand=""):
    return {"idx": i, "state": "ready" if col else "empty", "color": col, "material": "PLA" if col else "", "source": "rfid" if col else "empty", "brand": brand}
st = {"aces": [{"idx": 0, "slots": [slot(0,"#eff0f1"), slot(1,"#000000","Elegoo"), slot(2,"#e02020","Snapmaker"), slot(3,"#009639")]},
               {"idx": 1, "slots": [slot(0,None), slot(1,"#f7d959"), slot(2,"#927968"), slot(3,"#ff8da1")]}],
      "toolheads": [{"idx": i, "manual": False} for i in range(4)], "device_count": 2,
      "spools": {"1": {"weight_g": 640}, "2": {"weight_g": 415}, "3": {"weight_g": 40}, "4": {"weight_g": 723}, "5": {"weight_g": 994}},
      "spool_binding": {"0_0": "1", "0_1": "2", "0_2": "3", "0_3": "4", "1_1": "5"}}
g = open("/tmp/g/real.gcode", encoding="utf-8", errors="replace").read()
t=time.time(); meta = mb.gcode_meta(g); print("meta %.2fs" % (time.time()-t))
print({k: v for k, v in meta.items() if k not in ("thumb", "matrix_raw")}, "thumb", bool(meta["thumb"]), len(meta["thumb"] or ""))
eng = mb.load_engine(); M = mb.flush_matrices(meta, eng)
print("matrices", len(M), [row[:5] for row in M[0]][:2], "head2 row0", M[1][0])
for mode in ("loaded", "optimize"):
    t=time.time(); r = mb.analyze_gcode(g, st, mode, None, meta); out = r.pop("gcode")
    print(mode, "%.1fs" % (time.time()-t), "changes", r["changes"], "swaps", r["swaps"], "stamps", r["purge_stamps"], "plan", r["plan"] and r["plan"]["swaps"], r["alerts"])
    lens = [int(x) for x in re.findall(r"ACE_SET_PURGE LENGTH=(\d+)", out)]
    print("  purge mm min/max/n", min(lens) if lens else None, max(lens) if lens else None, len(lens))
for m in r["matches"]: print("  ", m["t"]+1, m["color"], "->", m.get("ace"), m.get("slot"), m.get("how") or m.get("tier"), round(m["grams"]), m["remaining"], m["sliced_head"], m["sliced_type"], m["head_type"])
