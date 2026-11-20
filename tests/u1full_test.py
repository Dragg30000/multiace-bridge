"""0.35 : fenetre U1 complete (bobines imposees, buses, PA, maillage zone, envoi sans lancer)."""
import sys, re, json, time, tempfile, shutil
exec(open("/home/claude/multiace_bridge/test/u1code_test.py").read().split("plans = {k")[0])
# --- infos du fichier
info = mb.slice_info(g)
ok(info["order"][:2] == [0, 1] and len(info["sliced"]) == 5 and info["sliced"][4]["head"] == 0, "ordre d'utilisation et tête tranchée par filament : %s" % info["order"])
ok(info["sliced"][0]["nozzle"] == "Standard" and info["grams"][2] == 62.0, "buse tranchée et grammes lus dans l'en-tête")
ok(info["thumb"] and info["thumb"].startswith("data:image/png;base64,"), "vignette trouvée")
# --- bobines imposees -> remap_override du code de la U1
rep, live, sha = mb.u1_report(c, g, "real.gcode")
ok(mb._u1code["caps"].get("remap"), "le code de la U1 accepte les bobines imposées (remap_override)")
rm = mb.forced_remap(rep, {"2": 1 * 4 + 2}, live["live_slots"])
ok(rm.get("2") == 6, "filament 3 imposé sur ACE 2 slot 3 -> remap %s" % rm)
for bad in ({"2": 1 * 4 + 0}, {"9": 0}, {"2": "x"}):
    try: mb.forced_remap(rep, bad, live["live_slots"]); ok(False, "bad %s" % bad)
    except mb.MultiAceError: ok(True, "choix refusé (bobine absente / filament inconnu / illisible) %s" % bad)
final = mb.u1_prepare(c, g, "real.gcode", "slicer", {}, mb._signature(live), report=rep, forced={"2": 6})
used = {tuple(x) for x in mb._u1code["core"].used_ace_slots_file(final)}
ok((1, 2) in used, "fichier préparé par la U1 avec la bobine imposée (ACE 2 slot 3 utilisé)")
try: mb.u1_prepare(c, g, "real.gcode", "optimize", {}, mb._signature(live), report=rep, forced={"2": 6}); ok(False, "opt")
except mb.MultiAceError as e: ok("Comme tranché" in str(e), "bobines imposées refusées hors « Comme tranché »")
# --- maillage sur la zone imprimee
full = g + ".full.gcode"
txt = open(g, encoding="utf-8", errors="replace").read()
txt = re.sub(r"^BED_MESH_CALIBRATE mesh_min=.*$", "BED_MESH_CALIBRATE PROBE_COUNT=11,11 Z_OFFSET=-0.07", txt, count=1, flags=re.M)
open(full, "w", encoding="utf-8").write(txt)
out = full + ".o"; line = mb.mesh_on_print_zone(full, out)
m = re.search(r"MESH_MIN=([\d.]+),([\d.]+) MESH_MAX=([\d.]+),([\d.]+) PROBE_COUNT=(\d+),(\d+) Z_OFFSET=-0.07", line)
ok(m and 3 <= float(m.group(1)) < 100 and float(m.group(3)) <= 267 and int(m.group(5)) < 11, "plateau entier -> zone imprimée : %s" % line)
o = open(out, encoding="utf-8").read(); ok(o.count("\nBED_MESH_CALIBRATE") == 1 and len(o) > len(txt), "une seule commande de maillage, le reste intact")
ok(mb.mesh_on_print_zone(g, out) == "" and open(out, encoding="utf-8", errors="replace").read() == open(g, encoding="utf-8", errors="replace").read(), "profil déjà adaptatif -> rien ne change")
# --- calibration du flux limitee aux tetes cochees
src = tempfile.mktemp(); open(src, "w").write("; multiACE auto-load: end\n; multiACE preflight: flow calibration (moved behind the auto-load, heads loaded)\nT1 A0\nFLOW_CALIBRATE EXTRUDER=1\nT3 A0\nFLOW_CALIBRATE EXTRUDER=3\nT0 A0\nFLOW_CALIBRATE EXTRUDER=0\nT0\n; multiACE preflight: flow calibration end\nT1\n")
mb.limit_flow_heads(src, src + ".o", [0, 3]); o = open(src + ".o").read()
ok("; multiACE Bridge skipped: T1 A0" in o and "\nFLOW_CALIBRATE EXTRUDER=3" in o and o.endswith("end\nT1\n"), "flux mesuré seulement sur T1/T4 cochées, T2 garde son PA")
# --- fenetre : donnees, envoi sans lancer, imprimer avec choix
W = mb._U1PF; sent = []; W._send = lambda d: sent.append(d); W._reply = lambda ok_, text, final=False: sent.append({"done": ok_, "text": text})
W.start(g, "real.gcode", host, delay=0); time.sleep(8)
d = sent[-1]; ok(d.get("report") and d.get("info") and d.get("load") and d.get("can_force"), "fenêtre : rapport + infos + chargement + forçage")
UP.clear(); W._print("slicer", {"bed": True, "zone": True}, {"2": 6}, True)
ok(UP and UP[-1][0].endswith("/server/files/upload") and "sans lancer" in sent[-1]["text"], "Envoyer sans lancer -> Moonraker : %s" % sent[-1]["text"])
UP.clear(); W._print("slicer", {"bed": True}, {"2": 6}); ok(UP and UP[-1][0].endswith("/upload-and-print") and "imposées" in sent[-1]["text"], "Lancer avec bobines imposées : %s" % sent[-1]["text"])
calls = []; mb._PANEL._run = lambda n, a, **k: calls.append((n, a))
W.on_message({"a": "precal", "head": 2, "ace": 0, "slot": 2}); ok(calls == [("ACE_LOAD_HEAD", {"HEAD": 2, "ACE": 0, "SLOT": 2}), ("ACE_PA_CALIBRATE", {"HEAD": 2, "FORCE": 1})], "Calibrer avant -> file du panneau")
W.on_message({"a": "precal", "head": 9, "ace": 0, "slot": 2}); ok(len(calls) == 2, "tête invalide ignorée")
# --- 0.35.1 : depart en douceur, U1 lente
o2 = g + ".soft"; n = mb.soft_start(g, o2); t2 = open(o2, encoding="utf-8", errors="replace").read()
ok(n > 0 and "G1 Z5 F1200" in t2 and "acceleration d'origine" in t2, "départ en douceur : %d déplacement(s) ralenti(s) avant la 1re couche" % n)
first = t2.index(";LAYER_CHANGE") if ";LAYER_CHANGE" in t2 else len(t2)
ok(t2.count("ralenti") == n and t2.rindex("ralenti") < first, "seulement avant la 1re couche")
calls2 = {"n": 0}; real_get = mb.MultiAce.get_json
def slow(self, path, timeout=8):
    if path == "/preflight/pysrc" and calls2["n"] < 1:
        calls2["n"] += 1; raise mb.MultiAceError("U1 injoignable (timed out)")
    return real_get(self, path, timeout)
mb.MultiAce.get_json = slow; mb._u1code.update(sha=None)
try: mb.u1_code(c); ok(calls2["n"] == 1, "U1 lente au 1er export : nouvel essai, pas de repli")
except mb.U1CodeError as e: ok(False, "repli %s" % e)
mb.MultiAce.get_json = real_get
