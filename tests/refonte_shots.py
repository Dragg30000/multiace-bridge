"""Captures de la refonte (0.41.x privée) : fenêtre de préparation (vraies données du code multiACE) et panneau."""
import json, os, sys, time
exec(open("/home/claude/prive/test/u1code_test.py").read().split("plans = {k")[0])
from playwright.sync_api import sync_playwright
OUT = "/home/claude/prive/test/shots"
os.makedirs(OUT, exist_ok=True)
LANG = sys.argv[1] if len(sys.argv) > 1 else "fr"
mb._LANG["v"] = LANG

# --- fenêtre : vraie proposition de la U1 (estimation + timeline) sur le G-code de test
LIVE["head_ctx"] = {"mode": "multi", "head_nozzle_types": {"0": "high_flow", "1": "high_flow", "2": "standard", "3": "high_flow"}}
SRC["swap_cost"] = open(ROOT + "/tools/swap_cost.py").read()
mb._u1code.update(sha=None)
W = mb._U1PF; sent = []; W._send = lambda d: sent.append(d)
W.start(g, "Grinch_nutcracker_U1_PLA.gcode", host, delay=0)
for _ in range(60):
    time.sleep(0.5)
    if sent and sent[-1].get("report"):
        break
sent[-1]["version"] = "1.90"
for _ in range(60):
    time.sleep(0.5)
    if sent and sent[-1].get("report"):
        break
d = sent[-1]
# têtes chargées comme sur la machine (T1..T4 depuis l'ACE 1) : le placement pas à pas propose « Décharger »
d["load"]["heads"] = [{"idx": i, "ace": 0, "slot": i, "loaded": True, "manual": False} for i in range(4)]
plans = d["report"]["plans"]
print("plans", {k: (v.get("feasible"), v.get("swaps"), (v.get("estimate") or {}).get("total_s"), len(v.get("timeline") or []), v.get("suggested")) for k, v in plans.items()})
print("n_ev", d.get("n_ev"), "ev_t", (d.get("ev_t") or [])[:5], "...")
open("/home/claude/prive/test/shots/window_data.json", "w").write(json.dumps(d))
html = mb.i18n_page(mb.U1_PAGE.replace("__DATA__", json.dumps(d).replace("</", "<\\/")))
open(OUT + "/window.html", "w").write(html)

FAKE = """<script>window.__h=[];window.__p=[];window.orca={postMessage:function(m){window.__p.push(typeof m==="string"?JSON.parse(m):m)},onMessage:function(f){window.__h.push(f)}};</script>"""

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1220, "height": 2000}, device_scale_factor=2)
    pg.goto("file://" + OUT + "/window.html"); pg.wait_for_timeout(600)
    pg.screenshot(path=OUT + "/w_plan_%s.png" % LANG, full_page=True)
    opt = pg.locator('.pr[data-plan="optimize"]:not(.off)')
    if opt.count():
        opt.click(); pg.wait_for_timeout(300)
        pg.screenshot(path=OUT + "/w_opt_%s.png" % LANG, full_page=True)
        if pg.locator("#place").count():
            pg.click("#place"); pg.wait_for_timeout(300)
            pg.screenshot(path=OUT + "/w_place_%s.png" % LANG, full_page=True)
    b.close()

# --- panneau : état proche de la machine de Dragg (2 ACE, Grinch ouvert dans Orca)
def slot(i, col, mat="PLA", src="rfid", state="ready", brand="", sub=""):
    if not col:
        return {"idx": i, "state": "empty", "color": None, "material": "", "source": "empty"}
    return {"idx": i, "state": state, "color": col, "material": mat, "source": src, "brand": brand, "subtype": sub}
state = {"display_index_base": 1, "mode": "multi", "printer_state": "ready", "device_count": 2,
         "aces": [{"idx": 0, "connected": True, "humidity": 61, "temp": 26,
                   "dryer": {"status": "stop"},
                   "slots": [slot(0, "#F4F4F4", brand="Generic", sub="Basic"), slot(1, "#8B5E3C", brand="Generic"), slot(2, None), slot(3, "#2F80D1", "PETG", brand="Sunlu")]},
                  {"idx": 1, "connected": True, "humidity": 31, "temp": 26,
                   "dryer": {"status": "drying", "target_temp": 50, "remain_time": 12660, "duration": 240},
                   "slots": [slot(0, None), slot(1, "#FFC83A", brand="Sunlu"), slot(2, "#E5483F", brand="Sunlu"), slot(3, "#1B1D21", src="derived")]}],
         "toolheads": [{"idx": 0, "filament_detected": True, "ace": 0, "slot": 0, "color": "#F4F4F4", "material": "PLA"},
                       {"idx": 1, "filament_detected": False, "ace": None, "slot": None},
                       {"idx": 2, "filament_detected": True, "ace": 1, "slot": 2, "color": "#E5483F", "material": "PLA"},
                       {"idx": 3, "filament_detected": True, "ace": 1, "slot": 3, "color": "#1B1D21", "material": "PLA"}],
         "spools": {"3": {"id": 3, "weight_g": 720, "color": "F4F4F4", "material": "PLA"}, "4": {"id": 4, "weight_g": 880, "color": "2F80D1", "material": "PETG", "vendor": "Sunlu"},
                    "5": {"id": 5, "weight_g": 540, "color": "FFC83A", "material": "PLA"}, "6": {"id": 6, "weight_g": 1000, "color": "E5483F", "material": "PLA"}},
         "spool_binding": {"0_0": 3, "0_3": 4, "1_1": 5, "1_2": 6}}
real = ["Haut débit", "Haut débit", "Standard", "Haut débit"]
prep = dict(mb.slicing_advice(state, real, ["#1B1D21", "#FFC83A", "#E5483F", "#F4F4F4", "#8ED68C"], ["Standard", "Haut débit", "Standard", "Haut débit"]),
            real=real, real_src="u1", manual=["", "", "", ""])
queue = {"command": "queue", "paused": False, "items": [
    {"id": 1, "label": "Chargement de T2 : ACE 2, voie 2", "status": "en cours", "name": "ACE_LOAD_HEAD", "args": {"HEAD": 1, "ACE": 1, "SLOT": 1}},
    {"id": 2, "label": "Calibration du filament (PA) sur T2", "status": "en attente", "name": "ACE_PA_CALIBRATE", "args": {"HEAD": 1}},
    {"id": 3, "label": "Séchage ACE 1 (45 °C, 4 h)", "status": "en attente", "name": "ACE_DRY", "args": {"ACE": 0}}]}
msgs = [{"command": "prefs", "host": "192.168.1.50", "screen": "off", "camera": "off", "compact": False, "prep_pos": "top", "folds": {}, "lang": LANG},
        queue,
        {"command": "state", "state": state, "prep": prep, "calib": {"0_3": False, "0_0": True}, "printer": "U1",
         "printer_tip": "Snapmaker U1 avec multiACE 1.90"}]
phtml = mb.i18n_page(mb.PANEL.replace("__VERSION__", mb.VERSION)).replace("<head>", "<head>" + FAKE, 1)
open(OUT + "/panel.html", "w").write(phtml)
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 380, "height": 1000}, device_scale_factor=2)
    pg.goto("file://" + OUT + "/panel.html"); pg.wait_for_timeout(300)
    for m in msgs:
        pg.evaluate("m => window.__h.forEach(f => f(m))", m); pg.wait_for_timeout(150)
    pg.screenshot(path=OUT + "/p_main_%s.png" % LANG, full_page=True)
    pg.click('[data-pk="s:0:3"]'); pg.wait_for_timeout(200)
    pg.screenshot(path=OUT + "/p_sel_%s.png" % LANG, full_page=True)
    pg.click('[data-ed="0_3"]'); pg.wait_for_timeout(200)
    pg.screenshot(path=OUT + "/p_edit_%s.png" % LANG, full_page=True)
    pg.set_viewport_size({"width": 320, "height": 1000}); pg.click('[data-close]'); pg.wait_for_timeout(200)
    pg.evaluate("m => window.__h.forEach(f => f(m))", msgs[-1]); pg.wait_for_timeout(200)
    pg.screenshot(path=OUT + "/p_320_%s.png" % LANG, full_page=True)
    print("posted", pg.evaluate("window.__p.slice(-3)"))
    b.close()
print("ok")
