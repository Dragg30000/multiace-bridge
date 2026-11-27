"""Preflight execute avec le code fourni par la U1 (fausse U1 servant les vraies sources multiACE)."""
import sys, types, tempfile, importlib.util, json, http.server, threading, os, glob, shutil
S = tempfile.mkdtemp()
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object), slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object), base=object, plugin=lambda c: c, host=types.SimpleNamespace(plugin=types.SimpleNamespace(storage=lambda: S)))
sp = importlib.util.spec_from_file_location("mb", "/home/claude/prive/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(sp); sp.loader.exec_module(mb)
ROOT = "/home/claude/src/multiACE/multiace"
SRC = {"postprocess": open(ROOT + "/tools/post_process_virtual_toolheads.py").read(),
       "core": open(ROOT + "/web/backend/preflight_core.py").read(),
       "swap_cost": open(ROOT + "/tools/swap_cost.py").read()}
def ok(c, m): print(("PASS " if c else "FAIL ") + m)
LIVE = {"live_slots": [{"ace": 0, "slot": i, "material": "PLA", "color": c} for i, c in enumerate(["#eff0f1", "#000000", "#e02020", "#009639"])]
        + [{"ace": 1, "slot": i, "material": "PLA", "color": c} for i, c in [(1, "#f7d959"), (2, "#927968"), (3, "#ff8da1")]],
        "head_ctx": {"mode": "multi"}, "cost_params": {}}
MODE = {"pysrc": "ok", "live": "ok"}; UP = []
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _j(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path.endswith("/preflight/pysrc"):
            if MODE["pysrc"] == "404": return self._j(404, {"detail": "Not Found"})
            src = dict(SRC)
            if MODE["pysrc"] == "nocore": src.pop("core")
            if MODE["pysrc"] == "changed": src["core"] = src["core"].replace("def build_report(pp, *, slicer_colors", "def build_report(pp, *, colours")
            return self._j(200, src)
        if self.path.endswith("/preflight/livedata"):
            if MODE["live"] == "manual": return self._j(409, {"detail": "manual head"})
            return self._j(200, LIVE)
        if self.path.endswith("/state"): return self._j(200, {"printer_state": "ready", "aces": [], "toolheads": []})
        if self.path.endswith("/version"): return self._j(200, {"web": "1.90-test"})
        self._j(404, {})
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0); data = self.rfile.read(n); UP.append((self.path, data))
        if self.path.endswith("/preflight/prefs") and MODE.get("prefs") == "409":
            return self._j(409, {"detail": "print preferences not accepted: Klipper busy"})
        self._j(200, {"ok": True})
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
host = "127.0.0.1:%d" % srv.server_address[1]; c = mb.MultiAce(host)
g = tempfile.mktemp(suffix=".gcode"); shutil.copy("/tmp/g/real.gcode", g)
rep, live, sha = mb.u1_report(c, g, "real.gcode")
plans = {k: v.get("swaps") for k, v in rep["plans"].items() if v.get("feasible")}
ok(plans and "slicer" in plans, "rapport calculé par le code de la U1 : plans %s, empreinte %s" % (plans, sha))
ok(all(m.get("slot") for m in rep["plans"]["slicer"]["mapping"]), "chaque filament a une bobine")
final = mb.u1_prepare(c, g, "real.gcode", "slicer", {"bed": True, "flow": False, "cam": False}, mb._signature(live))
txt = open(final, encoding="utf-8", errors="replace").read()
ok("ACE_SWAP_HEAD" in txt or "multiACE" in txt, "fichier préparé par le code de la U1")
ok(("SET_PRINT_PREFERENCES BED_LEVEL=1 " in txt or "; multiACE preflight prefs: BED_LEVEL=1 " in txt),
   "préférences de lancement de multiACE ajoutées (ligne, ou marque depuis multiACE 1.90.2)")
ok(open(g, encoding="utf-8", errors="replace").read() == open("/tmp/g/real.gcode", encoding="utf-8", errors="replace").read(), "export d'origine jamais modifié")
# verifications
try: mb.u1_prepare(c, g, "real.gcode", "slicer", {}, "autre"); ok(False, "x")
except mb.MultiAceError as e: ok("changé" in str(e), "bobines changées -> envoi refusé")
for mode, word in (("404", "ne fournit pas"), ("nocore", "absent"), ("changed", "version de multiACE non prise en charge")):
    MODE["pysrc"] = mode; mb._u1code.update(sha=None)
    try: mb.u1_code(c); ok(False, mode)
    except mb.U1CodeError as e: ok(word in str(e), "%s -> rien n'est exécuté : %s" % (mode, e))
MODE["pysrc"] = "ok"; MODE["live"] = "manual"
try: mb.u1_report(c, g, "real.gcode"); ok(False, "manual")
except mb.U1CodeError as e: ok("manuel" in str(e), "tête manuelle -> Preflight multiACE")
MODE["live"] = "ok"
# fichier deja traite -> refuse
open(g + "2", "w").write(txt); 
try: mb.u1_report(c, g + "2", "x.gcode"); ok(False, "processed")
except mb.MultiAceError as e: ok("processed" in str(e).lower() or "déjà" in str(e) or "already" in str(e), "fichier déjà traité refusé")
# fenetre : repli vers le Preflight de multiACE si la verification echoue
W = mb._U1PF; sent = []; W._send = lambda d: sent.append(d)
mb._POPUP.request = lambda *a: None; mb._POPUP.show_pending = lambda: None
MODE["pysrc"] = "404"; mb._u1code.update(sha=None); UP.clear()
W.start(g, "real.gcode", host, delay=0); import time; time.sleep(3)
ok(UP and UP[-1][0].endswith("/preflight/inbox") and b"ACE_SWAP_HEAD" not in UP[-1][1], "vérification échouée -> fichier d'origine au Preflight multiACE")
ok(any("Vérification" in (d.get("banner") or "") for d in sent), "l'utilisateur voit pourquoi")
MODE["pysrc"] = "ok"; UP.clear(); sent.clear(); W.start(g, "real.gcode", host, delay=0); time.sleep(6)
ok(sent and sent[-1].get("report"), "vérifications OK -> proposition affichée")
W._reply = lambda ok_, text, final=False: sent.append({"done": ok_, "text": text})
W._print("slicer", {"bed": True, "flow": False, "cam": False}); 
ok(UP and UP[-1][0].endswith("/upload-and-print") and sent[-1].get("done"), "Imprimer -> fichier préparé envoyé à la U1: %s" % sent[-1].get("text"))
# 0.46.2 : préférences de lancement avec le code de chaque version de multiACE (1.25b à 1.91). multiACE 1.90.2 et plus :
# marque en tête du fichier, préférences envoyées par /preflight/prefs juste avant « Imprimer » (imprimante à l'arrêt) ;
# avant : ligne SET_PRINT_PREFERENCES … FORCE=1 dans le fichier (celle du code de la U1, ou celle de 1.27b du plugin).
import subprocess
def _git_src(ref):
    def gs(p):
        try:
            return subprocess.check_output(["git", "-C", "/home/claude/src/multiACE", "show", "%s:multiace/%s" % (ref, p)],
                                           stderr=subprocess.DEVNULL).decode()
        except subprocess.CalledProcessError:
            return None                                   # fichier absent de cette version (swap_cost avant 1.90)
    out = {k: gs(p) for k, p in (("postprocess", "tools/post_process_virtual_toolheads.py"),
                                 ("core", "web/backend/preflight_core.py"), ("swap_cost", "tools/swap_cost.py"))}
    return {k: v for k, v in out.items() if v is not None}
SRC_NOW, LIVE_NOW = dict(SRC), dict(LIVE)
def _send(ref, prefs, how="print"):
    """Code de la U1 de la version ref, fenêtre rechargée, puis « Imprimer » (ou « Envoyer sans lancer ») :
    (rapport calculé ?, envois à la U1 dans l'ordre, fichier envoyé, réponse de la fenêtre, préférences envoyées)."""
    SRC.clear(); SRC.update(_git_src(ref))
    LIVE.clear(); LIVE.update(LIVE_NOW)
    if "swap_cost" not in SRC:
        LIVE.pop("cost_params", None)                    # multiACE avant 1.90 : pas de coût d'échange
    mb._u1code.update(sha=None)
    sent.clear(); W.start(g, "real.gcode", host, delay=0)
    for _ in range(80):
        time.sleep(0.25)
        if sent and sent[-1].get("report"):
            break
    rep_ok = bool(sent and sent[-1].get("report"))
    UP.clear(); W._print("slicer", prefs, how=how)
    body = UP[-1][1].decode("utf-8", "replace") if UP else ""
    return (rep_ok, [p for p, _b in UP], body, (sent[-1] if sent else {}),
            [json.loads(b) for p, b in UP if p.endswith("/preflight/prefs")])
ALL = {"bed": True, "flow": True, "cam": True}
for ref in ("v1.25b", "v1.26b", "v1.27b", "v1.90", "v1.90.1", "v1.90.2", "v1.91"):
    marque = "def read_print_prefs" in _git_src(ref)["core"]
    rep_ok, paths, body, rep_, pp_ = _send(ref, ALL)
    if marque:
        good = (paths == ["/multiace/api/preflight/prefs", "/multiace/api/upload-and-print"]
                and pp_ == [{"bed_mesh": True, "camera": True, "flow_cal": True}]
                and "; multiACE preflight prefs: BED_LEVEL=1 FLOW_CALIBRATE=1 TIME_LAPSE_CAMERA=1" in body
                and "\nSET_PRINT_PREFERENCES" not in body)
    else:
        good = (paths == ["/multiace/api/upload-and-print"] and not pp_
                and "\nSET_PRINT_PREFERENCES BED_LEVEL=1 FLOW_CALIBRATE=1 TIME_LAPSE_CAMERA=1 FORCE=1\n" in body)
    ok(rep_ok and rep_.get("done") and "FLOW_CALIBRATE EXTRUDER=" in body and good,
       "multiACE %s : rapport, impression, options de départ (%s)"
       % (ref[1:], "marque, envoyées juste avant" if marque else "ligne dans le fichier"))
    rep_ok, paths, body, rep_, pp_ = _send(ref, ALL, how="upload")
    ok(rep_.get("done") and not pp_ and paths == ["/server/files/upload"]
       and (("choisis-les sur l'écran de la U1" in rep_.get("text", "")) == marque),
       "multiACE %s, « Envoyer sans lancer » : rien d'envoyé avant, %s" % (ref[1:], "note sur les options" if marque else "pas de note"))
rep_ok, paths, body, rep_, pp_ = _send("v1.91", {"bed": False, "flow": False, "cam": False})
ok(rep_ok and paths == ["/multiace/api/upload-and-print"] and not pp_ and rep_.get("done"),
   "multiACE 1.91, aucune option : rien envoyé avant")
MODE["prefs"] = "409"
rep_ok, paths, body, rep_, pp_ = _send("v1.91", {"bed": True, "flow": False, "cam": False})
ok(paths == ["/multiace/api/preflight/prefs"] and rep_.get("done") is False
   and "préférences de lancement refusées par la U1" in rep_.get("text", ""),
   "multiACE 1.91, options refusées par la U1 : impression non lancée (%s)" % rep_.get("text"))
MODE["prefs"] = None
SRC.clear(); SRC.update(SRC_NOW); LIVE.clear(); LIVE.update(LIVE_NOW); mb._u1code.update(sha=None)
# multiACE 1.27b (version de la U1 de Dragg) : API plus ancienne, sans options de lancement dans le code partage
SRC.update(postprocess=open("/tmp/v127/pp.py").read(), core=open("/tmp/v127/core.py").read()); SRC.pop("swap_cost", None)
LIVE.pop("cost_params", None); mb._u1code.update(sha=None); MODE["pysrc"] = "ok"
rep, live, sha = mb.u1_report(c, g, "real.gcode")
ok(rep["plans"]["slicer"]["feasible"] and rep["_prefs_ok"] is False, "1.27b : rapport calculé (options de lancement par la méthode de multiACE 1.27b)")
final = mb.u1_prepare(c, g, "real.gcode", "slicer", {"bed": True}, mb._signature(live))
t2 = open(final, encoding="utf-8", errors="replace").read()
ok(t2.startswith("; multiACE preflight: print preferences\nSET_PRINT_PREFERENCES BED_LEVEL=1 FLOW_CALIBRATE=0 TIME_LAPSE_CAMERA=0 FORCE=1") and mb.gcode_facts(final)["processed"], "1.27b : fichier préparé par le code de la U1, options de lancement comme multiACE 1.27b")
import subprocess, re as _re
_src = subprocess.check_output(["git", "-C", "/home/claude/src/multiACE", "show", "v1.27b:multiace/web/backend/main.py"]).decode()
_ns = {"re": _re}; exec(_src[_src.index("_FLOW_CAL_LINE_RE = re.compile"):_src.index("def _prune_old_jobs")], _ns)
for _o in [(True, False, False), (True, True, True), (False, False, True)]:
    _ns["_prepend_print_prefs"](g, g + ".a", *_o); mb.prepend_print_prefs_127(g, g + ".b", *_o)
    ok(open(g + ".a").read() == open(g + ".b").read(), "options %s : résultat identique à la fonction de multiACE 1.27b" % (_o,))
srv.shutdown(); print("U1CODE OK")
