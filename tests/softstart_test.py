"""Deplacement doux vers la ligne d'amorce + arret propre du plugin (on_unload)."""
import os, sys, time, types, importlib.util, tempfile
STORE = tempfile.mkdtemp()
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
  slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
  base=object, plugin=lambda c: c, host=types.SimpleNamespace(plugin=types.SimpleNamespace(storage=lambda: STORE)))
spec = importlib.util.spec_from_file_location("mb", "/home/claude/multiace_bridge/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))
# debut reel d'un G-code Snapmaker U1 (Orca), apres le maillage du plateau
START = """M204 S10000
G1 X10 Y10 F30000
BED_MESH_CALIBRATE mesh_min=13.7,38.1 mesh_max=226.5,234.8 ALGORITHM=bicubic PROBE_COUNT=6,5
; multiACE auto-load: load initial filaments
ACE_SET_PURGE RESET=1
ACE_SWAP_HEAD HEAD=0 ACE=0 SLOT=0 INITIAL=1
T1
; multiACE auto-load: end

;===== 画起始线 =================
G90
G1 Z1.5
G0 X85 Y1 Z2 F18000
M109 S215
G1 Z0.2
M83
G1 X185 E15 F360
G1 Z1.5
G91
G1 Z1.5 F600
G90
G1 F21000
M400
T1
G1 Z.25 F30000
;LAYER_CHANGE
;Z:0.25
G1 X30.93 Y157.905 F30000
G1 X55.43 Y157.905 E1.1366 F3000
"""
d = tempfile.mkdtemp(); src, dst = os.path.join(d, "a.gcode"), os.path.join(d, "b.gcode")
open(src, "w").write(START)
def run(text, **kw):
    open(src, "w").write(text); mb.apply_print_prefs(src, dst, **kw); return open(dst).read().splitlines()
out = run(START)
i = out.index("; multiACE Bridge: deplacement doux vers la ligne d'amorce")
ok(out[i + 1:i + 5] == ["M204 S3000", "G91", "G1 Z5 F1200", "G90"], "accélération réduite + buse remontée de 5 mm avant")
ok(out[i + 5].startswith("G0 X85 Y1 Z2 F6000"), "G0 X85 Y1 Z2 F18000 -> F6000 : %s" % out[i + 5])
ok("G1 X185 E15 F360" in out and "G1 F21000" in out and "G1 Z.25 F30000" in out, "extrusion, réglages de vitesse seuls et Z seul : intacts")
j = out.index(";LAYER_CHANGE")
ok(out[j - 1].startswith("M204 S10000"), "accélération d'origine remise avant la 1re couche")
ok("G1 X30.93 Y157.905 F30000" in out[j:], "impression elle-même : intacte")
ok("G1 X10 Y10 F30000" in out, "avant le chargement / maillage : intact")
ok(run(START, soft_start=False)[2:] == START.splitlines(), "option décochée -> fichier inchangé (hors préférences)")
no_load = "\n".join(l for l in START.splitlines() if "auto-load" not in l and not l.startswith("ACE_") and l != "T1")
ok(any("F6000" in l for l in run(no_load)), "sans chargement auto : à partir du maillage du plateau")
bare = "\n".join(l for l in no_load.splitlines() if not l.startswith("BED_MESH"))
ok(not any("multiACE Bridge: deplacement" in l for l in run(bare)), "ni maillage ni chargement : rien touché")
slow = START.replace("F18000", "F3000")
ok(not any("multiACE Bridge: deplacement" in l for l in run(slow)), "déplacement déjà lent : rien touché")

# arret propre : on_unload arrete le garde-fou et plus aucun appel ensuite
calls = []
mb.load_settings = lambda: (calls.append(1), {"host": "127.0.0.1:9", "ace_guard": True, "real_nozzles": ["", "", "", ""]})[1]
mb.GUARD_POLL = 0.05
g = mb.GuardRunner(); g.ensure(); time.sleep(0.3)
ok(g._thread.is_alive() and calls, "garde-fou actif")
mb.AcePanel().on_unload()
time.sleep(0.2); n = len(calls); time.sleep(0.3)
ok(not g._thread.is_alive() and len(calls) == n, "après on_unload : fil arrêté, plus aucun appel")
g2 = mb.GuardRunner(); g2.ensure()
ok(g2._thread is None, "pas de redémarrage après l'arrêt")
p = mb.AcePanelController(); p._post = lambda m: calls.append(m); n = len(calls); p._refresh(); time.sleep(0.2)
ok(len(calls) == n, "panneau : plus d'actualisation réseau après l'arrêt")
print("ALL OK")
