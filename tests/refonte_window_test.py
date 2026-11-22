"""0.41 (refonte, privée) : fenêtre de préparation sur une vraie proposition du code multiACE."""
import json, time
exec(open("/home/claude/prive/test/u1code_test.py").read().split("plans = {k")[0])
from playwright.sync_api import sync_playwright
def ok(c, m):
    print(("PASS " if c else "FAIL ") + m)
    if not c: sys.exit(1)
LIVE["head_ctx"] = {"mode": "multi", "head_nozzle_types": {"0": "high_flow", "1": "high_flow", "2": "standard", "3": "high_flow"}}
mb._u1code.update(sha=None); mb._LANG["v"] = "fr"
W = mb._U1PF; sent = []; W._send = lambda d: sent.append(d)
W.start(g, "real.gcode", host, delay=0)
for _ in range(60):
    time.sleep(0.5)
    if sent and sent[-1].get("report"): break
d = sent[-1]; plans = d["report"]["plans"]
ok(d.get("n_ev") and d.get("ev_t") and len(d["ev_t"]) == d["n_ev"], "rubans : place de chaque changement d'outil envoyée (%s)" % d.get("n_ev"))
ok(all(0 <= x <= 1 for x in d["ev_t"]) and d["ev_t"] == sorted(d["ev_t"]), "places entre 0 et 1, dans l'ordre")
withtl = [k for k, v in plans.items() if v.get("feasible") and v.get("timeline")]
FAKE = """<script>window.__h=[];window.__p=[];window.orca={postMessage:function(m){window.__p.push(typeof m==="string"?JSON.parse(m):m)},onMessage:function(f){window.__h.push(f)}};</script>"""
html = mb.U1_PAGE.replace("<head>", "<head>" + FAKE, 1).replace("__DATA__", json.dumps(d).replace("</", "<\\/"))
open("/home/claude/testdata/refonte_win.html", "w").write(html)
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome"); pg = b.new_page(viewport={"width": 1220, "height": 1400})
    pg.goto("file:///home/claude/testdata/refonte_win.html"); pg.wait_for_timeout(300)
    send = lambda m: pg.evaluate("m=>window.__h.forEach(f=>f(m))", m)
    ok(pg.locator(".pr[data-plan]").count() == len(plans) and pg.locator("input[name=p]").count() == len(plans), "une ligne et un bouton radio par plan")
    ok(pg.locator(".ribw").count() == len(withtl) and len(withtl) >= 1, "un ruban par plan qui a sa chronologie (%s)" % withtl)
    ok(pg.locator("#pmap .tray").count() >= 1 and pg.locator("#pmap .head").count() == 4, "carte des bobines utilisées")
    if pg.locator('input[name=p][value=layer]').count():
        ok(pg.is_disabled('input[name=p][value=layer]') == (not plans["layer"].get("feasible")), "plan impossible : non sélectionnable")
    pg.click("#mo"); ok(all(pg.locator(s).count() == 1 for s in ("#up", "#pf", "#rl", "#x")), "menu : envoyer sans lancer, Preflight multiACE, recharger, fermer")
    pg.click("#mo")
    if plans.get("optimize", {}).get("suggested"):
        pg.click("input[value=optimize]"); pg.wait_for_timeout(100)
        n = pg.locator("ul.st li").count()
        ok(n >= 1 and pg.locator("#pmap .badge").count() >= 1, "Optimisé : %d geste(s) et numéros sur la carte" % n)
        ok(pg.is_disabled("#go"), "lancement bloqué tant que les bobines ne sont pas en place")
        pg.click("#place"); pg.wait_for_timeout(100)
        ok(pg.locator(".cur").count() == 1 and "1 / %d" % n in pg.inner_text(".prog"), "placement pas à pas : geste 1 / %d" % n)
        f0 = pg.get_attribute(".cur [data-mv]", "data-f") if pg.locator(".cur [data-mv]").count() else None
        ok(pg.locator(".cur [data-unl]").count() == 0 and "décharge-la d’abord dans le panneau" in pg.inner_text(".cur"),
           "têtes inconnues : pas de bouton Décharger, rappel général")
        ok(pg.locator("#pmap svg.arrows path").count() >= 1, "flèche du geste en cours sur la carte")
        for i in range(n):
            pg.locator(".cur [data-mv],.cur [data-nw]").click(); m = pg.evaluate("window.__p")[-1]
            ok(m["a"] in ("moved", "newspool") and m["step"] == i, "geste %d envoyé (%s)" % (i + 1, m["a"]))
            send({"type": "done", "ok": True, "text": "Bobine notée", "step": m["step"]}); pg.wait_for_timeout(80)
        ok(pg.evaluate("window.__p")[-1]["a"] == "reload" and pg.locator(".plh").count() == 0, "tous les gestes faits : rechargement, retour au plan")
    send({"type": "done", "ok": True, "text": "Impression lancée", "final": True}); pg.wait_for_timeout(200)
    ok(pg.locator("#m3ov").count() == 1, "animation Mange-3MF au lancement")
    b.close()
# 0.41.1 : la tête chargée depuis la voie du geste se décharge depuis le placement pas à pas
if plans.get("optimize", {}).get("suggested") and f0:
    a0, s0 = [int(x) for x in f0.split("_")]
    d2 = json.loads(json.dumps(d))
    d2["load"]["heads"] = [{"idx": i, "ace": a0 if i == s0 else None, "slot": s0 if i == s0 else None, "loaded": i == s0, "manual": False} for i in range(4)]
    open("/home/claude/testdata/refonte_win_unl.html", "w").write(mb.U1_PAGE.replace("<head>", "<head>" + FAKE, 1).replace("__DATA__", json.dumps(d2).replace("</", "<\\/")))
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/usr/bin/google-chrome"); pg = b.new_page(viewport={"width": 1220, "height": 1400})
        pg.goto("file:///home/claude/testdata/refonte_win_unl.html"); pg.wait_for_timeout(300)
        pg.click("input[value=optimize]"); pg.wait_for_timeout(100); pg.click("#place"); pg.wait_for_timeout(100)
        cur = pg.inner_text(".cur")
        ok(pg.locator('.cur [data-unl="%d"]' % s0).count() == 1 and "Décharger T%d" % (s0 + 1) in cur, "T%d chargée depuis la voie : bouton « Décharger T%d »" % (s0 + 1, s0 + 1))
        ok("T%d est chargée depuis cette voie" % (s0 + 1) in cur and "dans le panneau." not in cur, "explication précise, plus de rappel général")
        ok("go" not in (pg.get_attribute(".cur [data-mv]", "class") or ""), "« C’est fait » passe au second plan tant que la tête n’est pas déchargée")
        pg.click('.cur [data-unl="%d"]' % s0); pg.wait_for_timeout(80)
        ok(pg.evaluate("window.__p")[-1] == {"a": "unload", "head": s0}, "clic : déchargement demandé à la fenêtre")
        ok(pg.locator(".cur [data-unl]").count() == 0 and "Déchargement de T%d demandé" % (s0 + 1) in pg.inner_text(".cur")
           and "go" in (pg.get_attribute(".cur [data-mv]", "class") or ""), "déchargement noté, « C’est fait » redevient l’action suivante")
        b.close()
    calls, replies = [], []
    run0, rep0 = mb._PANEL._run, W._reply
    mb._PANEL._run = lambda n, a, allow_busy=False: calls.append((n, a))
    W._reply = lambda ok_, text, final=False, step=None: replies.append((ok_, text))
    try:
        for hv in (s0, "x", 7, None):
            W.on_message({"a": "unload", "head": hv})
    finally:
        mb._PANEL._run, W._reply = run0, rep0
    ok(calls == [("ACE_UNLOAD_HEAD", {"HEAD": s0})] and len(replies) == 1 and "T%d" % (s0 + 1) in replies[0][1],
       "déchargement : file du panneau, tête valide seulement (%s)" % calls)
mb._LANG["v"] = "en"
html = mb.i18n_page(mb.U1_PAGE.replace("<head>", "<head>" + FAKE, 1).replace("__DATA__", json.dumps(d).replace("</", "<\\/")))
open("/home/claude/testdata/refonte_win_en.html", "w").write(html)
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome"); pg = b.new_page(viewport={"width": 1220, "height": 1400})
    pg.goto("file:///home/claude/testdata/refonte_win_en.html"); pg.wait_for_timeout(300)
    if plans.get("optimize", {}).get("suggested"):
        pg.click("input[value=optimize]"); pg.wait_for_timeout(100)
    t = pg.inner_text("body")
    ok("Print plan" in t and "Over the print" in t and "At start" in t and "Start the print" in t, "fenêtre traduite")
    ok(not any(w in t for w in ("Durée", "Échanges", "Au départ", "voie", "Bobines pour")), "plus de français dans la fenêtre anglaise")
    if plans.get("optimize", {}).get("suggested") and f0:
        open("/home/claude/testdata/refonte_win_unl_en.html", "w").write(mb.i18n_page(mb.U1_PAGE.replace("<head>", "<head>" + FAKE, 1).replace("__DATA__", json.dumps(d2).replace("</", "<\\/"))))
        pg.goto("file:///home/claude/testdata/refonte_win_unl_en.html"); pg.wait_for_timeout(300)
        pg.click("input[value=optimize]"); pg.wait_for_timeout(100); pg.click("#place"); pg.wait_for_timeout(100)
        cur = pg.inner_text(".cur")
        ok("Unload T%d" % (s0 + 1) in cur and "is loaded from this lane" in cur and not any(w in cur for w in ("Décharger", "chargée", "voie")),
           "placement pas à pas traduit, bouton Unload compris")
        pg.click('.cur [data-unl="%d"]' % s0); pg.wait_for_timeout(80)
        ok("Unloading T%d requested (panel queue)." % (s0 + 1) in pg.inner_text(".cur"), "déchargement demandé : traduit")
    b.close()
mb._LANG["v"] = None
print("fenêtre refonte OK")
