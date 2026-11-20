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
# --- 0.35.2 : 1er export de la session, Orca demande l'autorisation « open » et refuse le fil d'arriere-plan
real_load = mb._load_source; cnt = {"n": 0}
def denied(name, path):
    if cnt["n"] < 2:
        cnt["n"] += 1; raise PermissionError("operation not permitted by audit hook")
    return real_load(name, path)
mb._load_source = denied; mb._u1code.update(sha=None); mb.U1ACCESS_WAIT = 60
W = mb._U1PF; sent = []; W._send = lambda d: sent.append(d); UP.clear()
W.start(g, "real.gcode", host, delay=0); time.sleep(16)
ok(any("autorisation" in (d.get("loading") or "") for d in sent), "autorisation en attente -> message « réponds Oui »")
ok(sent and sent[-1].get("report") and not UP, "après la réponse : fenêtre normale, rien envoyé au Preflight de multiACE")
mb._load_source = real_load
e = PermissionError(13, "denied", "/x"); ok(mb._denied(RuntimeError("x")) is False and mb._denied(e), "détection d'un refus d'accès")
# --- 0.35.3 : plan Optimise de multiACE 1.27b = disposition proposee
rp = {"plans": {"slicer": {"mapping": [{"t": 0, "slot": {"ace": 1, "slot": 3}}, {"t": 1, "slot": {"ace": 0, "slot": 3}}]},
                "optimize": {"mapping": [{"t": 0, "tier": "planned", "slot": {"ace": 0, "slot": 0}}, {"t": 1, "tier": "planned", "slot": {"ace": 0, "slot": 3}}]},
                "layer": {"mapping": [{"t": 0, "tier": "exact_hex", "slot": {"ace": 0, "slot": 0}}]}}}
ok(mb.placement_todo(rp, "optimize") == [0], "disposition proposée : filament 1 pas encore à sa place")
ok(mb.placement_todo(rp, "slicer") == [] and mb.placement_todo(rp, "layer") == [], "plans calculés sur les bobines chargées : rien à placer")
W = mb._U1PF; sent = []; W._reply = lambda ok_, text, final=False: sent.append({"done": ok_, "text": text}); W.report = rp; UP.clear()
W._print("optimize", {}); ok(not UP and "place d'abord" in sent[-1]["text"], "lancement refusé tant que les bobines ne sont pas en place : %s" % sent[-1]["text"])
# --- 0.35.4 : chargement automatique verifie, etape Preflight ajoutee au profil
rep, live, sha = mb.u1_report(c, g, "real.gcode")
f = mb.u1_prepare(c, g, "real.gcode", "slicer", {}, mb._signature(live))
ok(mb.autoload_heads(f) == [0, 1, 2, 3], "chargement automatique au départ lu dans le fichier préparé : %s" % mb.autoload_heads(f))
ok(mb.autoload_heads(g) is None, "fichier sans bloc de chargement : signalé")
import types as _t
CFG = {"slicing_pipeline_plugin": '"Autre plugin"'}; TX = []
class Pr:
    def config_value(self, k): return CFG.get(k)
    def label(self, *a): return "PLA - U1 - TEST"
class Prn:
    def config_value(self, k): return "Snapmaker U1" if k == "printer_model" else None
class Tx:
    def set(self, k, v): TX.append((k, v))
    def commit(self):
        CFG["slicing_pipeline_plugin"] = TX[-1][1]; return _t.SimpleNamespace(target_name="PLA - U1 - TEST")
mb.orca.host.preset_bundle = lambda: _t.SimpleNamespace(current_printer_preset=lambda: Prn(), prints=_t.SimpleNamespace(edited_preset=lambda: Pr()))
mb.orca.host.preset = _t.SimpleNamespace(process=_t.SimpleNamespace(begin_update=lambda *a: Tx()))
st = mb.pipeline_status(force=True)
ok(st["state"] == "added" and TX[-1][1] == '"Autre plugin";"multiACE : envoyer au Preflight"', "étape ajoutée au profil U1, autres plugins gardés : %s" % TX[-1][1])
st = mb.pipeline_status(force=True); ok(st["state"] == "present" and len(TX) == 1, "déjà présente : rien n'est touché")
mb.note_pipeline_ran(); st = mb.pipeline_status(force=True); ok(st.get("ran_here") is True and st.get("ran_version") == mb.VERSION, "dernier export préparé par cette copie (v%s)" % st.get("ran_version"))
open(mb._ran_path(), "w").write(json.dumps({"version": "0.34.3", "storage": "/autre/copie"})); st = mb.pipeline_status(force=True)
ok(st.get("ran_here") is False and st.get("ran_version") == "0.34.3", "autre copie du plugin détectée")
Prn.config_value = lambda self, k: "Bambu Lab P1S"; CFG["slicing_pipeline_plugin"] = ""; TX.clear()
st = mb.pipeline_status(force=True); ok(st["state"] == "not_u1" and not TX, "profil d'une autre imprimante : jamais modifié")
