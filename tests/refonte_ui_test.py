"""0.41 (refonte, privée) : panneau en carte des voies + fenêtre (plans, rubans, gestes, placement pas à pas)."""
import json, os, sys, types, importlib.util, tempfile
STORE = tempfile.mkdtemp()
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
  slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
  base=object, plugin=lambda c: c, host=types.SimpleNamespace(plugin=types.SimpleNamespace(storage=lambda: STORE)))
spec = importlib.util.spec_from_file_location("mb", "/home/claude/prive/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)
def ok(c, m):
    print(("PASS " if c else "FAIL ") + m)
    if not c: sys.exit(1)
from playwright.sync_api import sync_playwright
FAKE = """<script>window.__h=[];window.__p=[];window.orca={postMessage:function(m){window.__p.push(typeof m==="string"?JSON.parse(m):m)},onMessage:function(f){window.__h.push(f)}};</script>"""
ok('version = "0.44.0"' in open("/home/claude/prive/multiace_bridge_any.py").read() and mb.VERSION == "0.44.0", "version 0.44.0")
_head = open("/home/claude/prive/multiace_bridge_any.py").read(1000)
_nm = [l for l in _head.splitlines() if l.startswith("# name = ")][0]
ok(("(privé)" in _nm) != ("(Snapmaker U1)" in _nm), "nom : copie privée ou version publique")
ok("MB Display" in mb.PANEL and "MB Text" in mb.U1_PAGE and "MB Hubot" not in mb.PANEL + mb.U1_PAGE and "/*__FONTS__*/" not in mb.PANEL + mb.U1_PAGE, "polices intégrées dans les deux pages")
ok(mb.action_label("ACE_LOAD_HEAD", {"HEAD": 1, "ACE": 1, "SLOT": 1}) == "Chargement de T2 : ACE 2, voie 2", "file : vocabulaire des voies")
ok(mb.event_fractions(None) == (None, None) and mb.event_fractions({"events": [1, 2, 3]}) == (3, None), "rubans : sans minutes M73, rang des échanges")
n, f = mb.event_fractions({"events": [1, 2, 3, 4], "ctx": {"event_times": [100, None, 50, 0]}})
ok(n == 4 and f == [0.0, 0.0, 0.5, 1.0], "rubans : place des échanges d'après les minutes restantes %s" % f)

def slot(i, col, mat="PLA", src="rfid"):
    if not col: return {"idx": i, "state": "empty", "color": None, "material": "", "source": "empty"}
    return {"idx": i, "state": "ready", "color": col, "material": mat, "source": src}
def state(**kw):
    s = {"display_index_base": 1, "mode": "multi", "printer_state": "ready",
         "aces": [{"idx": 0, "connected": True, "humidity": 61, "temp": 26, "dryer": {"status": "stop"},
                   "slots": [slot(0, "#F4F4F4"), slot(1, "#8B5E3C"), slot(2, None), slot(3, "#2F80D1", "PETG")]},
                  {"idx": 1, "connected": True, "humidity": 31, "temp": 26, "dryer": {"status": "stop"},
                   "slots": [slot(0, None), slot(1, "#FFC83A"), slot(2, "#E5483F"), slot(3, "#1B1D21")]}],
         "toolheads": [{"idx": 0, "filament_detected": True, "ace": 0, "slot": 0, "color": "#F4F4F4", "material": "PLA"},
                       {"idx": 1, "filament_detected": False, "ace": None, "slot": None},
                       {"idx": 2, "filament_detected": True, "ace": 1, "slot": 2, "color": "#E5483F", "material": "PLA"},
                       {"idx": 3, "filament_detected": True, "ace": 1, "slot": 3, "color": "#1B1D21", "material": "PLA"}],
         "spools": {"3": {"id": 3, "weight_g": 720, "color": "F4F4F4", "material": "PLA"}, "4": {"id": 4, "weight_g": 880, "color": "2F80D1", "material": "PETG"},
                    "5": {"id": 5, "weight_g": 640, "color": "FFC83A", "material": "PLA"}},
         "spool_binding": {"0_0": 3, "0_3": 4}}
    s.update(kw); return s
real = ["Haut débit", "Haut débit", "Standard", "Haut débit"]
st = state(swap_in_progress=True)
prep = dict(mb.slicing_advice(st, real, ["#1B1D21", "#FFC83A", "#E5483F", "#F4F4F4"], ["Standard", "Haut débit", "Standard", "Haut débit"]), real=real, real_src="u1", manual=["", "", "", ""])
html = mb.PANEL.replace("__VERSION__", mb.VERSION).replace("<head>", "<head>" + FAKE, 1)
open("/home/claude/testdata/refonte_panel.html", "w").write(html)
P = lambda pg: [m for m in pg.evaluate("window.__p") if m.get("command") not in ("refresh", "prefs_get")]
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome"); pg = b.new_page(viewport={"width": 360, "height": 1500})
    pg.goto("file:///home/claude/testdata/refonte_panel.html"); pg.wait_for_timeout(200)
    send = lambda m: pg.evaluate("m=>window.__h.forEach(f=>f(m))", m)
    send({"command": "prefs", "host": "x", "screen": "off", "camera": "off", "compact": False, "auto_home": True, "folds": {}})
    send({"command": "state", "state": st, "prep": prep, "calib": {"0_3": False, "1_1": True}, "printer": "U1", "printer_tip": "Nom de la U1 : U1"})
    ok(pg.locator("#map .tray").count() == 2 and pg.locator("#map .head").count() == 4 and pg.locator("#map .spw").count() == 8, "carte : 2 ACE, 4 têtes, 8 voies")
    ok(pg.locator("#map svg.paths line").count() >= 8, "un chemin par voie")
    ok(pg.locator("#map svg.paths rect").count() == 1, "un chemin non calibré marqué")
    ok(pg.locator('.head[data-h="0"].warn').count() == 1, "T1 signalée : buse d'Orca différente de la U1")
    ok("Buse à régler dans Orca" in pg.inner_text("#prep") and pg.locator("#prep .cnt").inner_text() == "1", "avant de trancher : un point à régler")
    # bobine non chargée : bouton actif pendant un échange multiACE
    pg.click('[data-pk="s:0:3"]'); pg.wait_for_timeout(50)
    ok(pg.is_visible("#sheet") and pg.locator('#sheet button[data-act=swap][data-head="3"]:not([disabled])').count() == 1, "fiche : Échanger dans T4 actif pendant un échange multiACE")
    ok("Config, puis Calibration" in pg.inner_text("#sheet"), "fiche : chemin non calibré expliqué")
    ok(pg.locator('#sheet button[data-act=calpa]:not([disabled])').count() == 1, "calibration PA possible (bobine associée)")
    pg.click('[data-pk="s:1:1"]'); pg.wait_for_timeout(50)
    ok(pg.locator('#sheet button[data-act=calpa][disabled]').count() == 1, "calibration PA impossible sans bobine associée")
    pg.click('#sheet button[data-act=load]'); pg.click('#sheet button[data-act=load]')
    send({"command": "queue", "paused": False, "items": [{"id": 1, "label": "x", "status": "en cours", "name": "ACE_LOAD_HEAD", "args": {"HEAD": 1, "ACE": 1, "SLOT": 1}}]})
    send({"command": "state", "state": st, "prep": prep})
    pg.click('[data-pk="h:0"]'); pg.wait_for_timeout(50)
    pg.click('#sheet button[data-act=unload][data-head="0"]'); pg.click('#sheet button[data-act=unload][data-head="0"]')
    pg.click("#ua"); pg.click("#ua")
    cmds = [m["command"] for m in P(pg)]
    ok(cmds == ["load", "unload", "unload_all"], "trois actions à la suite : %s" % cmds)
    ok(pg.inner_text("#queue .qa b") == "x" and pg.is_visible("#queue .pbar"), "file : action en cours avec sa barre")
    ok(pg.evaluate("getComputedStyle(document.querySelector('button')).userSelect") == "none", "boutons non sélectionnables")
    # état prévu après la file : la tête T2 recevra le jaune
    ok(pg.locator('.head[data-h="1"] .nx').count() == 1, "tête : « ensuite » d'après la file")
    # séchage : armer, rafraîchir, confirmer
    pg.click('[data-dry="0"]'); pg.click('button[data-act=dry][data-ace="0"]')
    send({"command": "done", "ok": True, "text": "Terminé : x"}); send({"command": "state", "state": st, "prep": prep})
    ok(pg.inner_text('button[data-act=dry][data-ace="0"]') == "Confirmer ?", "confirmation gardée après un rafraîchissement")
    pg.click('button[data-act=dry][data-ace="0"]')
    d = [m for m in P(pg) if m["command"] == "dry"]
    ok(d and d[-1]["ace"] == 0 and d[-1]["temp"] == 45 and d[-1]["duration"] == 240, "séchage envoyé : %s" % d[-1:])
    # séchage en cours : statut et arrêt dans la bande de l'ACE
    st2 = json.loads(json.dumps(st)); st2["aces"][1]["dryer"] = {"status": "drying", "target_temp": 50, "remain_time": 12660, "duration": 240}
    send({"command": "state", "state": st2, "prep": prep})
    import re as _re
    ok(_re.search(r"50\s*°C", pg.inner_text('.tray[data-ace="1"] .gut')) and pg.locator('button[data-act=stopdry][data-ace="1"]').count() == 1, "séchage en cours affiché avec Arrêter")
    # options
    ok(pg.is_checked("#ah") and not pg.is_visible("#ah"), "options repliées par défaut")
    pg.click("#opt"); pg.click("#ah")
    pr = [m for m in P(pg) if m["command"] == "prefs_set"]
    ok(pr and pr[-1] == {"command": "prefs_set", "auto_home": False}, "homing auto : %s" % pr[-1:])
    pg.click("#optX")
    # plateau
    send({"command": "queue", "paused": False, "items": []})
    pg.select_option("#bt", "60"); pg.click('button[data-act=calbed]'); pg.click('button[data-act=calbed]')
    cb = [m for m in P(pg) if m["command"] == "calib_bed"]
    ok(cb and cb[-1]["temp"] == 60, "calibration du plateau à 60 °C")
    # éditeur de voie
    pg.click('[data-pk="s:0:3"]'); pg.click('[data-ed="0_3"]')
    ok(pg.locator(".ed").count() == 1, "éditeur ouvert dans la fiche")
    pg.click('[data-ed="0_3"]'); ok(pg.locator(".ed").count() == 0, "2e clic sur Modifier : refermé")
    pg.click('[data-ed="0_3"]'); pg.click("#e_spbtn"); pg.locator('#e_splist .spo[data-v="5"]').click()
    ok(pg.input_value("#e_w") == "640", "bobine choisie : son poids est repris")
    # 0.43.1 : la bobine #3 est dans ACE 1 voie 1 (occupée) : choisie ici, elle donne une bobine pareille
    pg.click("#e_spbtn"); row = pg.locator('#e_splist .spo[data-v="copy:3"]')
    ok(row.count() == 1 and "Une bobine pareille sera créée pour cette voie." in row.inner_text(), "bobine dans une autre voie occupée : copie proposée")
    row.click()
    ok(pg.input_value("#e_spid") == "copy:3" and "Copie de" in pg.inner_text("#e_spbtn") and pg.input_value("#e_w") == "1000"
       and pg.is_visible("#e_cpn") and "#3" in pg.inner_text("#e_cpn"), "copie : bouton, poids d'une bobine neuve, explication")
    pg.click("#e_ok"); e = [m for m in P(pg) if m["command"] == "edit"]
    ok(e and e[-1]["ace"] == 0 and e[-1]["slot"] == 3 and e[-1]["spool"] == "copy:3", "édition envoyée : %s" % e[-1:])
    send({"command": "state", "state": st, "prep": prep})
    # repli de la carte « Avant de trancher » et mode réduit
    pg.click("#prep .ah h2"); f2 = [m for m in P(pg) if m["command"] == "prefs_set"]
    ok(f2[-1] == {"command": "prefs_set", "fold": {"k": "prep", "on": True}} and not pg.is_visible("#prep .pbody"), "carte repliée et mémorisée")
    pg.click("#cmp"); c2 = [m for m in P(pg) if m["command"] == "prefs_set"]
    ok(pg.evaluate("document.body.classList.contains('compact')") and c2[-1].get("compact") is True and pg.locator("#map .spw").count() == 8, "mode réduit : la carte reste")
    pg.click("#cmp")
    # mode tête : rendu en liste
    send({"command": "state", "state": state(mode="head", head_ace={"0": 0, "1": 1}), "prep": prep})
    ok(pg.is_visible("#legacy") and not pg.is_visible("#map"), "mode tête : rendu en liste")
    send({"command": "state", "state": st, "prep": prep})
    ok(pg.is_visible("#map"), "retour en mode multi")
    pg.keyboard.press("Escape")
    b.close()

# anglais
mb._LANG["v"] = "en"
html = mb.i18n_page(mb.PANEL.replace("__VERSION__", mb.VERSION)).replace("<head>", "<head>" + FAKE, 1)
open("/home/claude/testdata/refonte_panel_en.html", "w").write(html)
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome"); pg = b.new_page(viewport={"width": 360, "height": 1500})
    pg.goto("file:///home/claude/testdata/refonte_panel_en.html"); pg.wait_for_timeout(200)
    pg.evaluate("m=>window.__h.forEach(f=>f(m))", {"command": "state", "state": state(), "prep": prep, "calib": {"0_3": False}})
    pg.click('[data-pk="s:0:3"]'); pg.wait_for_timeout(100)
    t = pg.inner_text("body")
    ok("Swap into T4" in t and "Nozzle to set in Orca" in t and "Calibrate flow" in t and "lane 4" in t, "panneau traduit")
    ok("Échanger" not in t and "voie" not in t and "Buse à régler" not in t, "plus de français dans le panneau anglais")
    b.close()
mb._LANG["v"] = None
print("refonte OK")
