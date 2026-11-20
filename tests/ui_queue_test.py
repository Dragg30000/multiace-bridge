import json, sys, types, importlib.util, copy
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
  slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
  base=object, plugin=lambda c: c)
spec = importlib.util.spec_from_file_location("mb", "/home/claude/multiace_bridge/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)
st = json.load(open("/home/claude/src/multiACE/tests/fixtures/mock_state.json"))
a2 = copy.deepcopy(st["aces"][0]); a2["idx"] = 1; a2["humidity"] = 31
for s, (c, m, src) in zip(a2["slots"], [("#e53935","PLA","rfid"),("#fdd835","PETG","override"),("#1e88e5","PLA","derived"),(None,"","empty")]):
    s.update(color=c, material=m, source=src, state="empty" if src == "empty" else "ready", brand="SUNLU" if m else "")
a2["dryer"]={"status":"drying","target_temp":50,"duration":240,"remain_time":12677}
st["aces"].append(a2); st["mode"]="multi"; st["aces"][0]["slots"][0]["source"]="override"; st["printer_state"]="ready"
for t in st["toolheads"][1:]: t["filament_detected"]=False
fake = """<script>window.__h=[];window.orca={postMessage:function(){},onMessage:function(f){window.__h.push(f)}};</script>"""
fake = """<script>window.__h=[];window.__p=[];window.orca={postMessage:function(m){window.__p.push(typeof m==="string"?JSON.parse(m):m)},onMessage:function(f){window.__h.push(f)}};</script>"""
open("panel_t.html","w").write(mb.PANEL.replace("<head>","<head>"+fake,1))
st["swap_in_progress"] = True
from playwright.sync_api import sync_playwright
def send(pg, m): pg.evaluate("m=>window.__h.forEach(f=>f(m))", m)
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome"); pg = b.new_page(viewport={"width": 360, "height": 1400})
    pg.goto("file:///home/claude/multiace_bridge/test/panel_t.html"); pg.wait_for_timeout(200)
    send(pg, {"command": "state", "state": st})
    n = pg.evaluate("document.querySelectorAll('button[data-act=swap]:not([disabled]),button[data-act=load]:not([disabled])').length")
    assert n > 0, "head buttons enabled during a multiACE swap"
    # 3 actions a la suite pendant qu'un echange tourne
    for sel in ['button[data-act=unload][data-head="0"]', 'button[data-act=load],button[data-act=swap]']:
        pg.click(sel); pg.click(sel)
        send(pg, {"command": "queue", "paused": False, "items": [{"id": 1, "label": "x", "status": "en cours"}]})
        send(pg, {"command": "state", "state": st})
    pg.click("#ua"); pg.click("#ua")
    cmds = [m["command"] for m in pg.evaluate("window.__p") if m.get("command") not in ("refresh", "prefs_get")]
    print(cmds); assert cmds == ["unload", "load", "unload_all"] or cmds[:3] in (["unload", "swap", "unload_all"], ["unload", "load", "unload_all"]), cmds
    # sechage : armer, un rafraichissement arrive, le 2e clic doit partir
    pg.click('button[data-act=dry][data-ace="0"]')
    send(pg, {"command": "done", "ok": True, "text": "Terminé : x"}); send(pg, {"command": "state", "state": st})
    assert pg.inner_text('button[data-act=dry][data-ace="0"]') == "Confirmer ?", "arm survives refresh"
    pg.click('button[data-act=dry][data-ace="0"]')
    last = [m for m in pg.evaluate("window.__p") if m.get("command") == "dry"]
    assert last and last[-1]["ace"] == 0, last
    send(pg, {"command": "prefs", "host": "x", "screen": "off", "compact": False, "auto_home": True})
    assert pg.is_checked("#ah")
    assert not pg.is_visible("#ah"), "options repliees par defaut"
    pg.click("#opt")
    pg.click("#ah")
    pr = [m for m in pg.evaluate("window.__p") if m.get("command") == "prefs_set"]
    assert pr and pr[-1] == {"command": "prefs_set", "auto_home": False}, pr
    # etat prevu apres la file
    st2 = json.loads(json.dumps(st)); st2["swap_in_progress"] = False
    send(pg, {"command": "queue", "paused": False, "items": []}); send(pg, {"command": "state", "state": st2})
    assert pg.locator('.badge', has_text="sur T1").count() >= 1
    send(pg, {"command": "queue", "paused": False, "items": [{"id": 9, "label": "Échange T1 ← ACE 2 slot 1", "status": "attente", "name": "ACE_SWAP_HEAD", "args": {"HEAD": 0, "ACE": 1, "SLOT": 0}}]})
    pg.wait_for_timeout(100)
    assert pg.locator('.badge', has_text="prévue sur T1").count() == 1, "queued spool shown as planned"
    assert pg.locator('button[data-act=swap][data-ace="0"][data-slot="0"]').count() == 1, "spool leaving T1 gets a button again"
    assert "après la file : ACE 2 · slot 1" in pg.inner_text("#heads")
    us = pg.evaluate("getComputedStyle(document.querySelector('#queue')).userSelect")
    assert us == "none", us
    pg.screenshot(path="v171_plan.png", clip={"x": 0, "y": 0, "width": 360, "height": 1100})
    # calibration plateau
    send(pg, {"command": "queue", "paused": False, "items": []})
    pg.select_option("#bt", "60"); pg.click('button[data-act=calbed]'); pg.click('button[data-act=calbed]')
    cb = [m for m in pg.evaluate("window.__p") if m.get("command") == "calib_bed"]
    assert cb and cb[-1]["temp"] == 60, cb
    # editeur de slot : choix de bobine + calibration PA
    pg.click('.item.click[data-edit="0_1"] .t')
    pg.click("#e_spbtn")
    opts = pg.eval_on_selector_all("#e_splist .spo", "els=>els.map(e=>e.dataset.v)")
    assert opts[0] == "" and opts[-1] == "new" and len(opts) > 3, opts
    bg = pg.evaluate("getComputedStyle(document.querySelector('#e_splist')).backgroundColor"); fg = pg.evaluate("getComputedStyle(document.querySelector('#e_splist .spo')).color")
    assert bg != fg and "28, 31, 36" in bg, (bg, fg)
    assert pg.locator("#e_splist .spo .sw").count() >= 3, "colour swatches in the list"
    assert pg.locator('button[data-act=calpa]').count() == 1
    pg.screenshot(path="v190_editor.png", full_page=True)
    pg.screenshot(path="v191_list.png", full_page=True)
    pg.click('#e_splist .spo[data-v="3"]')
    assert pg.input_value("#e_spid") == "3" and not pg.is_visible("#e_splist")
    sp3 = st["spools"]["3"]
    assert pg.input_value("#e_hex") == "#" + sp3["color"].lower(), (pg.input_value("#e_hex"), sp3)
    assert pg.input_value("#e_m") == sp3["material"].upper() and pg.input_value("#e_b") == (sp3.get("vendor") or "")
    pg.click("#e_ok")
    ed = [m for m in pg.evaluate("window.__p") if m.get("command") == "edit"]
    assert ed and ed[-1]["spool"] == "3" and ed[-1]["color"] == "#" + sp3["color"].lower() and ed[-1]["apply_spool"] is False, ed
    print("UI QUEUE OK"); b.close()
