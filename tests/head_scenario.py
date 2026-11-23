"""0.43.0 : scénarios « rapport par tête » avec le vrai code multiACE servi par une fausse U1.
Mode tête (2 ACE + 2 chargeurs latéraux, 4 ACE dont un déconnecté), mode multi avec copies de couleur, tête
alimentée à la main. run(...) renvoie les données envoyées à la fenêtre, comme dans OrcaSlicer."""
import json, time
exec(open("/home/claude/prive/test/u1code_test.py").read().split("rep, live, sha = mb.u1_report")[0])
STATE = {"printer_state": "ready", "aces": [], "toolheads": []}
_get0 = H.do_GET
def _get(self):
    if self.path.endswith("/state"):
        return self._j(200, STATE)
    return _get0(self)
H.do_GET = _get
NOZ = {str(i): "standard" for i in range(4)}
P = lambda a, s, c, m="PLA": {"ace": a, "slot": s, "material": m, "color": c}
W = mb._U1PF; sent = []; W._send = lambda d: sent.append(d)
mb._POPUP.request = lambda *a: None; mb._POPUP.show_pending = lambda: None

def heads_state(loaded):
    """loaded : {tête: (ace, voie) | 'feeder' | None}"""
    th = []
    for h in range(4):
        v = loaded.get(h)
        th.append({"idx": h, "ace": v[0] if isinstance(v, tuple) else None, "slot": v[1] if isinstance(v, tuple) else None,
                   "filament_detected": v is not None, "feeder": v == "feeder", "manual": False})
    return th

def run(live, hctx, loaded, name="head.gcode", path=None):
    LIVE["live_slots"] = live
    LIVE["head_ctx"] = hctx
    STATE["toolheads"] = heads_state(loaded)
    mb._u1code.update(sha=None)
    sent.clear(); W.start(path or g, name, host, delay=0)
    for _ in range(120):
        time.sleep(0.25)
        if sent and (sent[-1].get("report") or sent[-1].get("banner") or sent[-1].get("error")):
            break
    return sent[-1]

def head_ctx(**kw):
    d = {"mode": "head", "ace_head": 3, "ace_heads": [2, 3], "head_ace": {"2": 0, "3": 1},
         "feeders": [{"head": 0, "material": "PLA", "color": "#ffffff"}, {"head": 1, "material": "PLA", "color": "#000000"}],
         "manual_heads": [], "connected_aces": [0, 1], "head_nozzle_types": dict(NOZ),
         "bg_available": True, "bg_heads": [2, 3], "max_copies": 1,
         "empty_slots": [{"ace": 0, "slot": 3}, {"ace": 1, "slot": 3}]}
    d.update(kw)
    return d

# mode tête : ACE 1 -> T3, ACE 2 -> T4, chargeurs latéraux T1 (blanc) et T2 (noir)
LIVE_H2 = [P(0, 0, "#f7d959"), P(0, 1, "#e02020"), P(0, 2, "#009639"),
           P(1, 0, "#eff0f1"), P(1, 1, "#927968"), P(1, 2, "#ff8da1")]
LOAD_H2 = {0: "feeder", 1: "feeder", 2: (0, 0), 3: None}
