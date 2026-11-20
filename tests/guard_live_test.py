"""Garde-fou ACE de bout en bout : fausse U1 (HTTP), vrai fil de fond du plugin."""
import http.server, json, os, sys, threading, time, types
sys.modules.setdefault("orca", types.SimpleNamespace(
    plugin=lambda c: c, base=object, pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
    script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
    slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import multiace_bridge_any as P

state = {"aces": [{"idx": 0, "connected": True, "dryer": {"status": "drying", "target_temp": 55, "remain_time": 5400},
                   "feed_assist": 1},
                  {"idx": 1, "connected": True, "dryer": {"status": "stop"}, "feed_assist": -1}],
         "toolheads": [{"idx": 0, "ace": 0, "slot": 1, "head_source_known": True},
                       {"idx": 2, "ace": 1, "slot": 0, "head_source_known": True}],
         "printer_state": "printing", "active_device": 0, "swap_in_progress": False}
extruder = ["extruder"]
macros = []

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def j(self, obj):
        b = json.dumps(obj).encode(); self.send_response(200)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path == "/multiace/api/state": return self.j(state)
        if self.path.startswith("/printer/objects/query?toolhead=extruder"):
            return self.j({"result": {"status": {"toolhead": {"extruder": extruder[0]}}}})
        self.send_response(404); self.end_headers()
    def do_POST(self):
        m = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        macros.append(m)
        if m["name"] == "ACE_ENABLE_FEED_ASSIST":
            state["aces"][0]["feed_assist"] = int(m["args"]["INDEX"])
        if m["name"] == "ACE_DRY":
            state["aces"][0]["dryer"] = {"status": "drying", "target_temp": m["args"]["TEMP"],
                                         "remain_time": m["args"]["DURATION"] * 60}
        self.j({"result": "ok"})

srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
host = "127.0.0.1:%d" % srv.server_address[1]
P.load_settings = lambda: {"host": host, "ace_guard": True}
P.GUARD_POLL, P.GUARD_SETTLE, P.GUARD_FA_LOST = 0.1, 0.4, 0.4
posts = []
P._PANEL._post = posts.append
P._GUARD.ensure(); P._GUARD.ensure()
assert sum(1 for t in threading.enumerate() if t is P._GUARD._thread) == 1
fails = 0
def check(name, cond):
    global fails
    print(("OK   " if cond else "FAIL ") + name); fails += 0 if cond else 1

time.sleep(0.6)
# coupure USB de l'ACE 1 : il redemarre sans sechage ni poussee
state["aces"][0].update(connected=False)
time.sleep(0.4)
state["aces"][0].update(connected=True, dryer={"status": "stop"}, feed_assist=-1)
time.sleep(1.6)
names = [m["name"] for m in macros]
check("sechage relance", any(m["name"] == "ACE_DRY" and m["args"]["ACE"] == 0 and m["args"]["TEMP"] == 55
                             and 85 <= m["args"]["DURATION"] <= 90 for m in macros))
check("poussee relancee sur le slot de la tete qui imprime", {"name": "ACE_ENABLE_FEED_ASSIST", "args": {"INDEX": 1}} in macros)
check("rien d'autre envoye", sorted(names) == ["ACE_DRY", "ACE_ENABLE_FEED_ASSIST"])
check("messages au panneau", any("revenu" in p.get("text", "") for p in posts)
      and any("poussée relancée" in p.get("text", "") for p in posts))
# l'ACE 2 (tete T3 au repos) n'a pas de poussee : jamais touche
time.sleep(1.0)
check("l'autre tete n'est jamais poussee", not any(m["name"] == "ACE_ENABLE_FEED_ASSIST" and m["args"]["INDEX"] == 0 for m in macros))
# garde-fou coupe : plus rien
P.load_settings = lambda: {"host": host, "ace_guard": False}
n = len(macros); state["aces"][0]["feed_assist"] = -1
time.sleep(1.2)
check("case decochee -> rien", len(macros) == n)
print("\n%s" % ("TOUT OK" if not fails else "%d FAIL" % fails))
sys.exit(1 if fails else 0)
