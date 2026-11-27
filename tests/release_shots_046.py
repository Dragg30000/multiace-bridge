"""0.46.0 : images 2x pour le README, Orca Cloud et la présentation (anglais et français).
- fenêtre d'envoi : en-tête + alerte (0.45), réglages de l'imprimante (0.45), « À la fin » (0.46) ;
- panneau : séchage auto avec un ACE 2 Pro simulé (0.46).
Usage : python3 release_shots_046.py <dossier>"""
import copy, json, os, sys
sys.path.insert(0, "/home/claude/prive/test")
exec(open("/home/claude/prive/test/envoi_shots.py").read().split("def page(")[0])     # mb, d (Bonhomme 8 couleurs), FAKE
from playwright.sync_api import sync_playwright
OUT = sys.argv[1] if len(sys.argv) > 1 else "/home/claude/shots046/release"
os.makedirs(OUT, exist_ok=True)
NAMES = {"en": "Snowman_8_colours.gcode", "fr": "Bonhomme_8_couleurs.gcode"}

def window(p, lang):
    mb._LANG["v"] = lang
    dd = copy.deepcopy(d)
    dd["name"] = NAMES[lang]
    h = mb.U1_PAGE.replace("<head>", "<head>" + FAKE, 1).replace("__DATA__", json.dumps(dd).replace("</", "<\\/"))
    h = mb.i18n_page(h) if lang == "en" else h
    open("/home/claude/testdata/rel046_%s.html" % lang, "w").write(h)
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome")
    pg = b.new_page(viewport={"width": 1220, "height": 900}, device_scale_factor=2)
    pg.goto("file:///home/claude/testdata/rel046_%s.html" % lang)
    pg.click('.pr[data-plan="slicer"]')
    pg.wait_for_selector("#thumb .tl", timeout=8000)
    pg.wait_for_timeout(500)
    return b, pg

def slot(i, col, mat="PLA"):
    return {"idx": i, "state": "ready", "color": col, "material": mat, "source": "rfid"}

ACE1 = ("#111111", "#F2F2F2", "#E53935", "#2F80D1")


def panel_state():
    ad0 = {"enabled": True, "rh_start": 45.0, "rh_end": 35.0, "temp": 50, "master": -1, "add_time": 60}
    ad1 = {"enabled": True, "rh_start": 45.0, "rh_end": 35.0, "temp": 45, "master": 0, "add_time": 90}
    return {"display_index_base": 1, "mode": "multi", "printer_state": "standby",
            "aces": [{"idx": 0, "connected": True, "temp": 41, "humidity": 47.0, "has_humidity": True, "protocol": "v2",
                      "has_dryer": True, "auto_dry": ad0, "auto_dry_running": True,
                      "dryer": {"status": "drying", "target_temp": 50, "remain_time": 4300, "duration": 120},
                      "slots": [slot(i, c) for i, c in enumerate(ACE1)]},
                     {"idx": 1, "connected": True, "temp": 38, "humidity": None, "has_humidity": False, "protocol": "v1",
                      "has_dryer": True, "auto_dry": ad1, "auto_dry_running": True,
                      "dryer": {"status": "drying", "target_temp": 45, "remain_time": 4300, "duration": 120},
                      "slots": [slot(0, "#FDD835"), slot(1, "#8B5E3C", "PETG"), slot(2, "#43A047"), {"idx": 3, "state": "empty"}]}],
            "auto_dry_masters": [0],
            "toolheads": [{"idx": i, "filament_detected": True, "ace": 0, "slot": i, "color": ACE1[i]} for i in range(4)],
            "spools": {}, "spool_binding": {}}

PFAKE = """<script>window.__h=[];window.__p=[];window.orca={postMessage:function(m){window.__p.push(typeof m==="string"?JSON.parse(m):m)},onMessage:function(f){window.__h.push(f)}};</script>"""

with sync_playwright() as p:
    for lang in ("en", "fr"):
        b, pg = window(p, lang)
        al = pg.locator(".alerts").bounding_box()
        pg.screenshot(path="%s/print_preview_%s.png" % (OUT, lang), clip={"x": 0, "y": 0, "width": 1220, "height": al["y"] + al["height"] + 14})
        pg.evaluate("document.querySelector('.pset').scrollIntoView({block:'center'})"); pg.wait_for_timeout(200)
        ps = pg.locator(".pset").bounding_box()
        pg.screenshot(path="%s/printer_settings_%s.png" % (OUT, lang),
                      clip={"x": ps["x"] - 14, "y": ps["y"] - 6, "width": ps["width"] + 28, "height": ps["height"] + 18})
        pg.select_option("#endu", "all"); pg.wait_for_timeout(150)
        pg.evaluate("document.querySelector('.fin').scrollIntoView({block:'center'})"); pg.wait_for_timeout(200)
        fn = pg.locator(".fin").bounding_box()
        y0 = pg.locator("label.cb:has(#soft)").bounding_box()["y"] - 12
        pg.screenshot(path="%s/unload_at_end_%s.png" % (OUT, lang),
                      clip={"x": fn["x"] - 14, "y": y0, "width": fn["width"] + 28, "height": fn["y"] + fn["height"] + 12 - y0})
        b.close()
        # panneau : séchage auto (ACE 2 Pro simulé + ACE Pro qui le suit)
        mb._LANG["v"] = lang
        html = mb.i18n_page(mb.PANEL.replace("__VERSION__", mb.VERSION).replace("<head>", "<head>" + PFAKE, 1))
        path = "/home/claude/testdata/rel046_panel_%s.html" % lang
        open(path, "w", encoding="utf-8").write(html)
        b = p.chromium.launch(executable_path="/usr/bin/google-chrome")
        pg = b.new_page(viewport={"width": 400, "height": 1100}, device_scale_factor=2)
        pg.goto("file://" + path); pg.wait_for_timeout(200)
        send = lambda m: pg.evaluate("m=>window.__h.forEach(f=>f(m))", m)
        send({"command": "prefs", "host": "x", "screen": "off", "camera": "off", "compact": False, "auto_home": True, "folds": {}})
        send({"command": "state", "state": panel_state(), "dry": {}}); pg.wait_for_timeout(250)
        pg.click('[data-adry="0"]'); pg.wait_for_timeout(120)
        pg.click('[data-adry="1"]'); pg.wait_for_timeout(250)
        bx = pg.locator("#map").bounding_box()
        pg.screenshot(path="%s/auto_dry_%s.png" % (OUT, lang), clip={"x": 0, "y": bx["y"] - 4, "width": 400, "height": bx["height"] + 10})
        b.close()
mb._LANG["v"] = None
print("ok", sorted(os.listdir(OUT)))
