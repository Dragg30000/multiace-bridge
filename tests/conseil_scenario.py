"""0.41.4 : quoi poser quand « Optimisé » ne donne pas les bonnes couleurs (vrai code multiACE)."""
import json, sys, time
exec(open("/home/claude/prive/test/couleurs_scenario.py").read().split('if __name__ == "__main__":')[0])
def run(live, conn, name):
    LIVE["live_slots"] = live
    LIVE["head_ctx"] = {"mode": "multi", "connected_aces": conn, "head_nozzle_types": {str(i): "standard" for i in range(4)}}
    sent.clear(); W.start(gpath, name, host, delay=0)
    for _ in range(60):
        time.sleep(0.5)
        if sent and sent[-1].get("report"): break
    return sent[-1]
P_ = P = lambda a, s, c: {"ace": a, "slot": s, "material": "PLA", "color": c}
# cas 1 (capture de Dragg) : Blanc, Jaune, Vert en ACE 1, 4 bobines inconnues en ACE 2 que la U1 ne compte pas
d_cas1 = run([P(0, 0, "#f4f4f4"), P(0, 1, "#ffd23f"), P(0, 2, "#2e9e4f")], [0], "cas1.gcode")
d_cas1["load"]["ident"] = {"1_%d" % i: {"material": "", "brand": "", "color": "", "source": "", "subtype": "", "spool": None} for i in range(4)}
# cas 2 : 8 voies pleines, 3 mauvaises couleurs (Gris pas utilisé, Violet qui ne fait que le bleu, Rose pas utilisé)
d_cas2 = run([P(0, 0, "#f4f4f4"), P(0, 1, "#6a4fcf"), P(0, 2, "#2e9e4f"), P(0, 3, "#9e9e9e"),
              P(1, 0, "#8b5e3c"), P(1, 1, "#ffd23f"), P(1, 2, "#ff8da1"), P(1, 3, "#111111")], [0, 1], "cas2.gcode")
