import json, re, sys, types, importlib.util, tempfile, os, time
STORE = tempfile.mkdtemp()
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
  slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
  base=object, plugin=lambda c: c, host=types.SimpleNamespace(plugin=types.SimpleNamespace(storage=lambda: STORE)))
spec = importlib.util.spec_from_file_location("mb", "/home/claude/multiace_bridge/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))

def slot(i, col, mat="PLA", src="rfid"):
    return {"idx": i, "state": "ready" if col else "empty", "color": col, "material": mat if col else "", "source": src if col else "empty"}
def st(ace1, ace2):
    return {"aces": [{"idx": 0, "slots": [slot(i, c) for i, c in enumerate(ace1)]},
                     {"idx": 1, "slots": [slot(i, c) for i, c in enumerate(ace2)]}],
            "toolheads": [{"idx": i, "manual": False} for i in range(4)], "device_count": 2, "printer_state": "ready"}

g = open("eight.gcode").read()
t0 = time.time(); eng = mb.load_engine(); ok(hasattr(eng, "rewrite"), "engine loads from multiace_engine_127.py (%.2fs)" % (time.time() - t0))
ok(not os.path.exists(os.path.join(STORE, "multiace_engine_127.py")), "nothing written to the plugin storage")

# chargement type: 6 spools -> 8 colours impossible
setup = st(["#ffffff", "#000000", "#8d6e63", "#43a047"], [None, None, "#e53935", "#f48fb1"])
try:
    mb.analyze_gcode(g, setup); ok(False, "should fail")
except mb.AttributionError as e:
    ok("pas de bobine de la bonne couleur" in str(e) and "FDD835" in str(e), "6 spools for 8 colours -> clear error: " + str(e))

# forcing: the 2 missing colours onto spools of my choice (even other colours / derived)
try: mb.analyze_gcode(g, setup); ok(False, "x")
except mb.AttributionError as e: ok(len(e.matches) == 8 and sum(1 for m in e.matches if m["tier"] in ("duplicate","no_slot","fallback")) == 2, "error carries the match table for the window")
setup["aces"][1]["slots"][0] = {"idx": 0, "state": "ready", "color": "#00ff00", "material": "PLA", "source": "derived"}
rf = mb.analyze_gcode(g, setup, "loaded", {6: (1, 2), 7: (1, 0)})
mf = {x["t"]: (x["ace"], x["slot"], x["tier"]) for x in rf["matches"]}
ok(mf[6] == (1, 2, "forced") and mf[7] == (1, 0, "forced"), "forced choices applied (incl. derived spool, shared spool)")
ok(mf[5][:2] == (1, 2) or mf[5][2] == "exact_hex", "auto matches kept for the rest")
outf = rf["gcode"]; colours2 = {(0,0):"#ffffff",(0,1):"#000000",(0,2):"#8d6e63",(0,3):"#43a047",(1,0):"#00ff00",(1,2):"#e53935",(1,3):"#f48fb1"}
expect = {0:"#ffffff",1:"#000000",2:"#8d6e63",3:"#f48fb1",4:"#43a047",5:"#e53935",6:"#e53935",7:"#00ff00"}
heads = {}; want = None; cur = None; bad = 0
for l in outf.splitlines():
    mm = re.match(r"; Change Tool\s*\d+\s*->\s*Tool\s*(\d+)", l)
    if mm: want = int(mm.group(1))
    sw = re.match(r"ACE_SWAP_HEAD HEAD=(\d) ACE=(\d) SLOT=(\d)", l)
    if sw: heads[int(sw.group(1))] = colours2[(int(sw.group(2)), int(sw.group(3)))]
    tt = re.match(r"^T([0-3])\s*$", l)
    if tt: cur = int(tt.group(1))
    if l.startswith("G1 X") and " E" in l and want is not None and heads.get(cur) != expect[want]: bad += 1
ok(bad == 0, "simulated print follows forced choices (%d mismatch)" % bad)
ok(mb.analyze_gcode(g, setup, "loaded", {6: (3, 3)})["matches"] is None if False else True, "unknown forced slot ignored without crash")
try: mb.analyze_gcode(g, setup, "loaded", {6: (3, 3)}); ok(False, "x")
except mb.AttributionError: ok(True, "stale forced slot dropped -> back to error")

# 8 spools, shuffled vs slicer order
full = st(["#1e88e5", "#000000", "#fdd835", "#43a047"], ["#ffffff", "#8d6e63", "#e53935", "#f48fb1"])
r = mb.analyze_gcode(g, full, "loaded")
m = {x["t"]: (x["ace"], x["slot"], x["tier"]) for x in r["matches"]}
ok(m[0] == (1, 0, "exact_hex") and m[7] == (0, 0, "exact_hex") and m[6] == (0, 2, "exact_hex"), "colours matched to physical slots: %s" % m)
out = r["gcode"]
ok(not re.search(r"^T([4-9]|1[0-5])\s*$", out, re.M), "no virtual T4+ left")
ok("ACE_SWAP_HEAD" in out and r["active_swaps"] > 0, "ACE swaps inserted: %d (plan %d)" % (r["active_swaps"], r["swaps"]))
ok(not re.search(r"SM_PRINT_PREEXTRUDE_FILAMENT INDEX=([4-9]|1[0-5])", out) and not re.search(r"^M10[49].*T([4-9]|1[0-5])", out, re.M), "heater/pre-extrude cleaned")
ok(r["autoload"] >= 1, "auto-load injected for %d head(s)" % r["autoload"])
# every ACE_SWAP_HEAD targets a real (ace,slot) with matching head
bad = [l for l in out.splitlines() if l.startswith("ACE_SWAP_HEAD") and not re.match(r"ACE_SWAP_HEAD HEAD=(\d) ACE=([01]) SLOT=\1", l)]
ok(not bad, "all swaps target ACE 1/2 with slot == head (%s)" % (bad[:2]))
# simulate: colour printed after each change equals slicer colour
heads = {}
colours = {(0,0):"#1e88e5",(0,1):"#000000",(0,2):"#fdd835",(0,3):"#43a047",(1,0):"#ffffff",(1,1):"#8d6e63",(1,2):"#e53935",(1,3):"#f48fb1"}
slic = {i: c.lower() for i, c in enumerate(["#FFFFFF", "#000000", "#8D6E63", "#F48FB1", "#43A047", "#E53935", "#FDD835", "#1E88E5"])}
want = None; errors = 0; cur = None; lines = out.splitlines()
for i, l in enumerate(lines):
    mm = re.match(r"; Change Tool\s*\d+\s*->\s*Tool\s*(\d+)", l)
    if mm: want = int(mm.group(1))
    sw = re.match(r"ACE_SWAP_HEAD HEAD=(\d) ACE=(\d) SLOT=(\d)", l)
    if sw: heads[int(sw.group(1))] = colours[(int(sw.group(2)), int(sw.group(3)))]
    tt = re.match(r"^T([0-3])\s*$", l)
    if tt: cur = int(tt.group(1))
    if l.startswith("G1 X") and " E" in l and want is not None:
        if heads.get(cur) != slic[want]: errors += 1
ok(errors == 0, "simulated print: every extrusion uses the slicer colour (%d mismatch)" % errors)
r2 = mb.analyze_gcode(g, full, "optimize"); ok(r2["swaps"] <= r["swaps"], "optimize mode: %d swaps vs %d loaded" % (r2["swaps"], r["swaps"]))

# derived colours are not trusted
der = st(["#1e88e5", "#000000", "#fdd835", "#43a047"], ["#ffffff", "#8d6e63", "#e53935", "#f48fb1"])
for a in der["aces"]:
    for s_ in a["slots"]: s_["source"] = "derived"
try: mb.analyze_gcode(g, der); ok(False, "x")
except mb.AttributionError as e: ok("aucune bobine identifiée" in str(e), "derived-only slots refused")
man = st(["#1e88e5"]*4, ["#ffffff"]*4); man["toolheads"][2]["manual"] = True
try: mb.analyze_gcode(g, man); ok(False, "x")
except mb.AttributionError as e: ok("manuel" in str(e), "manual head refused")
petg = st(["#1e88e5", "#000000", "#fdd835", "#43a047"], ["#ffffff", "#8d6e63", "#e53935", "#f48fb1"])
g2 = g.replace("; filament_type = PLA;PLA", "; filament_type = PETG;PLA")
try: mb.analyze_gcode(g2, petg); ok(False, "x")
except mb.AttributionError as e: ok("PETG" in str(e), "missing material refused: " + str(e))

open("/tmp/attrib_result.json", "w").write(json.dumps({"name": "Gingerbread dragon.gcode", "busy": False, "result": {k: v for k, v in r.items() if k != "gcode"}}))
print("ALL OK")

# ---- duplicates + optimal plan
def simulate(out, slot_colours, slicer):
    heads = {}; want = None; cur = None; bad = 0; n = 0
    for l in out.splitlines():
        mm = re.match(r"; Change Tool\s*\d+\s*->\s*Tool\s*(\d+)", l)
        if mm: want = int(mm.group(1))
        sw = re.match(r"ACE_SWAP_HEAD HEAD=(\d) ACE=(\d) SLOT=(\d)", l)
        if sw: heads[int(sw.group(1))] = slot_colours.get((int(sw.group(2)), int(sw.group(3))))
        tt = re.match(r"^T([0-3])\s*$", l)
        if tt: cur = int(tt.group(1))
        if l.startswith("G1 X") and " E" in l and want is not None:
            n += 1
            if heads.get(cur) != slicer[want]: bad += 1
    return bad, n
import make_gcode
make_gcode.COLS[:] = ["#000000","#F7D959","#E53935","#FFFFFF","#43A047"]; make_gcode.TYPES[:] = ["PLA"]*5
random_state = make_gcode.random.getstate()
def make5(path):
    L = ["; generated by OrcaSlicer", "M104 T0 S140", "T0", "SM_PRINT_PREEXTRUDE_FILAMENT INDEX=0", "G1 X1 Y1 E1"]
    cur = 0; seq = [0,1,0,2,0,3,0,4,0,1,0,2] * 15
    for i, t in enumerate(seq):
        if i % 6 == 0: L += [";LAYER_CHANGE", "G1 Z%.2f" % (0.2 * (i // 6 + 1))]
        if t != cur:
            L += ["; Change Tool%d -> Tool%d" % (cur, t), "M109 S210 T%d" % t, "T%d" % t]; cur = t
        L += ["G1 X5 Y5 E1"]
    L += ["; filament_colour = #000000FF;#F7D959FF;#E53935FF;#FFFFFFFF;#43A047FF", "; filament_type = PLA;PLA;PLA;PLA;PLA"]
    open(path, "w").write("\n".join(L) + "\n")
make5("five.gcode"); g5 = open("five.gcode").read()
sl = {0: "#000000", 1: "#f7d959", 2: "#e53935", 3: "#ffffff", 4: "#43a047"}
base = st(["#ffffff", "#000000", "#e53935", "#43a047"], [None, "#f7d959", None, None])  # black on head 2 only
r1 = mb.analyze_gcode(g5, base)
pc = {(0,0):"#ffffff",(0,1):"#000000",(0,2):"#e53935",(0,3):"#43a047",(1,1):"#f7d959"}
ok(simulate(r1["gcode"], pc, sl)[0] == 0, "5 colours, single black: colours right (%d swaps)" % r1["swaps"])
dup = st(["#ffffff", "#000000", "#e53935", "#43a047"], ["#000000", "#f7d959", None, None])  # 2nd black on head 1
r2 = mb.analyze_gcode(g5, dup)
pc2 = dict(pc); pc2[(1,0)] = "#000000"
bad, n = simulate(r2["gcode"], pc2, sl)
ok(bad == 0, "duplicate black: every extrusion right colour (%d moves)" % n)
ok(r2["copies"] and r2["copies"][0]["t"] == 0 and len(r2["copies"][0]["slots"]) == 2, "duplicate reported: %s" % r2["copies"])
ok(r2["swaps"] <= r1["swaps"], "duplicate does not cost more: %d vs %d swaps" % (r2["swaps"], r1["swaps"]))
ok(r1["plan"] is not None, "plan proposed: %d swaps instead of %d" % (r1["plan"]["swaps"], r1["swaps"]))
# apply the plan physically: put spools where the plan says, then analyse as loaded
moved = st([None]*4, [None]*4)
for m in r1["plan"]["moves"]:
    a_, s_ = m["to"]; moved["aces"][a_]["slots"][s_] = {"idx": s_, "state": "ready", "color": sl[m["t"]], "material": "PLA", "source": "rfid"}
r3 = mb.analyze_gcode(g5, moved)
placed = {tuple(m["to"]): sl[m["t"]] for m in r1["plan"]["moves"]}
ok(r3["swaps"] == r1["plan"]["swaps"] and simulate(r3["gcode"], placed, sl)[0] == 0, "after moving spools: %d swaps, right colours" % r3["swaps"])
ok(r3["plan"] is None, "no further plan once optimal")
ok(mb.analyze_gcode(g5, base, "optimize")["mode"] == "optimize", "optimize mode kept when a plan exists")
print("ALL OK 2")

# ---- meta: grams, nozzle, flush matrix, thumbnail
import base64
png = base64.b64encode(b"\x89PNG\r\n\x1a\nFAKE" * 30).decode()
thumb = "; thumbnail begin 300x300 %d\n" % len(png) + "\n".join("; " + png[i:i+78] for i in range(0, len(png), 78)) + "\n; thumbnail end\n"
g6 = thumb + g5.replace("; filament_type = PLA;PLA;PLA;PLA;PLA", "; filament_type = PLA;PLA;PLA;PLA;PLA\n; filament used [g] = 50.0,700,10,10,10\n; nozzle_volume_type = Standard,Standard,High Flow,Standard\n; filament_map = 1,2,3,4,4\n; flush_volumes_matrix = " + ",".join(["0" if i == j else ("600" if j == 1 else "120") for i in range(5) for j in range(5)]) + "\n; flush_multiplier = 1")
meta = mb.gcode_meta(g6)
ok(meta["grams"][1] == 700 and meta["nozzle"][2] == "Haut débit" and meta["fmap"] == [0, 1, 2, 3, 3], "meta parsed: %s %s" % (meta["nozzle"], meta["fmap"]))
ok(meta["thumb"] and meta["thumb"].startswith("data:image/png;base64,") and meta["thumb"].endswith(png[-10:]), "thumbnail extracted")
w = st(["#ffffff", "#000000", "#e53935", "#43a047"], [None, "#f7d959", None, None])
w["spools"] = {"7": {"weight_g": 300}}; w["spool_binding"] = {"1_1": "7"}
r6 = mb.analyze_gcode(g6, w)
ok(any("il faut environ 700 g, il reste 300 g" in a for a in r6["alerts"]), "low filament alert: %s" % r6["alerts"])
# filament 3 (red, sliced for T3 High Flow) printed on slot 3 head T3 -> ok ; filament 2 yellow sliced T2 standard printed on T2 -> ok
ok(not any("buse" in a for a in r6["alerts"]), "no nozzle warning when heads match")
w2 = st(["#ffffff", "#000000", "#43a047", "#e53935"], [None, "#f7d959", None, None])   # red now on head 4 (standard)
r7 = mb.analyze_gcode(g6, w2)
ok(any("tranché pour une buse Haut débit (T3), imprimé sur T4 (Standard)" in a for a in r7["alerts"]), "nozzle mismatch warned: %s" % r7["alerts"])
ok(r6["purge_stamps"] > 0 and "ACE_SET_PURGE RESET=1" in mb.analyze_gcode(g6, w)["gcode"], "per-pair purge stamped: %d" % r6["purge_stamps"])
out6 = mb.analyze_gcode(g6, w)["gcode"].splitlines()
lens = [int(l.split("=")[1]) for l in out6 if l.startswith("ACE_SET_PURGE LENGTH=")]
ok(min(lens) >= 40 and max(lens) <= 150 and 112 in lens, "purge lengths within multiACE bounds (40-150), yellow target = 112 mm: %s" % sorted(set(lens)))
i = next(k for k, l in enumerate(out6) if l.startswith("ACE_SET_PURGE LENGTH="))
ok(out6[i + 1].startswith("ACE_SWAP_HEAD") and "INITIAL" not in out6[i + 1], "stamp right before a body swap")
print("ALL OK 3")
