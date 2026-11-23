"""0.43.0 : rapport « par tête » de la U1, vrai code multiACE (fausse U1).
Python : rapport accepté et complété, recalcul avec tes choix = calcul de la U1, fichier préparé identique à celui du
Preflight web dans le navigateur (mode « head »), plan proposé refusé tant que les bobines ne sont pas posées, file
d'impression. Fenêtre : carte par tête, plans, gestes, choix à la main, anglais."""
import json, os, sys, time, tempfile, shutil
exec(open("/home/claude/prive/test/head_scenario.py").read())
FAILS = []
def ok(c, m):
    print(("PASS " if c else "FAIL ") + m)
    if not c: FAILS.append(m)
pp, core, _sha = mb.u1_code(c)
colors, types, naces, _u, _plan, meta = core.parse_meta(pp, mb._read_lines(g))
PREFS = {"bed": False, "zone": False, "flow": False, "cam": False, "soft": False}
TMP = tempfile.mkdtemp()

def direct(plan, assignment=None, copies=None):
    """Le chemin du Preflight web dans le navigateur (preflight_pyodide_worker.js : rewrite_pipeline mode « head »)."""
    a, b = os.path.join(TMP, "a.gcode"), os.path.join(TMP, "b.gcode")
    out = core.rewrite_pipeline(pp, src_path=g, tmp_a=a, tmp_b=b, slicer_colors=colors, slicer_types=types,
                                num_aces=naces, live_slots=LIVE["live_slots"], head_ctx=LIVE["head_ctx"], mode="head",
                                head_assignment=assignment, head_plan=plan, meta=meta, head_copies=copies)
    return open(out, "rb").read()

def plugin(d, plan, forced=None):
    rep = d["report"]
    ids = mb.head_ids(rep, forced) if plan == "loadout" else None
    final = mb.u1_prepare(c, g, "head.gcode", plan, PREFS, mb._signature(LIVE), report=rep,
                          head={"plan": plan, "assignment": {str(t): v for t, v in ids.items()} if ids else None})
    return open(final, "rb").read()

# ---------- 1. mode tête : 2 ACE (T3, T4) + chargeurs latéraux T1, T2
d = run(LIVE_H2, head_ctx(), LOAD_H2)
rep = d.get("report") or {}
ok(rep.get("head_mode") and rep.get("topology") == "head" and rep.get("_h"), "mode tête : rapport de la U1 accepté (plus de renvoi au Preflight web)")
hx_ = rep["_h"]
ok(hx_["head_ace"] == {"2": 0, "3": 1} and hx_["feeders"] == [0, 1] and hx_["can_force"], "câblage ACE -> tête et chargeurs lus dans le code de la U1 (head_maps)")
ok(set(rep["plans"]) >= {"loadout", "optimize", "layer"}, "plans de la U1 : %s" % sorted(rep["plans"]))
pl = hx_["place"]["optimize"]
ok(pl and all(set(r) >= {"t", "kind", "ok", "src"} for r in pl) and any(r["kind"] == "pin" for r in pl), "plan proposé : état du placement de chaque bobine")
# recalcul « avec tes choix » sans rien changer = valeurs du rapport de la U1
ctx = mb._LAST_HEAD[g]
same = mb.head_forced(pp, core, rep, ctx, mb._LAST_CAPTURE[g], {})
lo = rep["plans"]["loadout"]
ok(same["swaps"] == lo["swaps"] and abs(same["estimate"]["total_s"] - lo["estimate"]["total_s"]) < 1e-6 and same["feasible"],
   "recalcul sans choix = rapport de la U1 (%s échanges, %.0f s)" % (same["swaps"], same["estimate"]["total_s"]))
ok((same.get("bg") or {}).get("bg_ok") == (lo.get("bg") or {}).get("bg_ok"), "arrière-plan recalculé = rapport (%s)" % (same.get("bg") or {}).get("bg_ok"))
# un choix : le blanc (filament 4) sur l'ACE 2 voie 1 au lieu du chargeur T1
f1 = mb.head_forced(pp, core, rep, ctx, mb._LAST_CAPTURE[g], {"3": "slot-1-0"})
asg = core.assignment_from_target_ids({str(t): v for t, v in mb.head_ids(rep, {"3": "slot-1-0"}).items()}, rep["targets"])
ok(f1["feasible"] and f1["swaps"] == pp.head_mode_swap_count(rep["events"], asg) and f1["estimate"]["total_s"] != lo["estimate"]["total_s"],
   "choix à la main : échanges et durée recalculés par la U1 (%s échanges)" % f1["swaps"])
for bad, word in (({"3": "slot-9-9"}, "illisible"), ({"9": "slot-1-0"}, "illisible"), ({"3": 5}, "illisible")):
    try:
        mb.head_forced(pp, core, rep, ctx, mb._LAST_CAPTURE[g], bad); ok(False, "refus %s" % bad)
    except mb.MultiAceError as e:
        ok(word in str(e), "choix refusé %s : %s" % (bad, e))
rep_pe = json.loads(json.dumps(rep)); rep_pe["targets"].append({"id": "slot-1-3", "kind": "ace", "head": 3, "ace": 1, "slot": 3, "material": "PETG", "color": "#ffffff"})
try:
    mb.head_ids(rep_pe, {"3": "slot-1-3"}); ok(False, "matière")
except mb.MultiAceError as e:
    ok("PLA" in str(e), "choix d'une autre matière refusé : %s" % e)

# fichier préparé = Preflight web (navigateur) pour le même choix
ids = {str(t): v for t, v in mb.head_ids(rep).items()}
ok(plugin(d, "loadout") == direct("loadout", ids, rep.get("copies") or {}), "Comme chargé : fichier identique au Preflight web")
ids2 = {str(t): v for t, v in mb.head_ids(rep, {"3": "slot-1-0"}).items()}
ok(plugin(d, "loadout", {"3": "slot-1-0"}) == direct("loadout", ids2, {}), "Comme chargé avec ton choix : fichier identique au Preflight web")
txt = plugin(d, "loadout").decode("utf-8", "replace")
ok("; multiACE processed: format=" in txt and "ACE_BG_SWAP" in txt, "fichier marqué multiACE, avec changements en arrière-plan")
ok("ACE_SWAP_HEAD HEAD=2" in txt and "ACE_SWAP_HEAD HEAD=0" not in txt, "T1 (chargeur latéral) jamais chargée par multiACE")

# plan proposé : refusé tant que les bobines ne sont pas posées
W.report, W.info, W.live_sig, W.job = rep, d["info"], mb._signature(LIVE), {"path": g, "name": "head.gcode", "host": host, "id": 1}
replies = []; W._reply = lambda ok_, text, final=False, step=None: replies.append((ok_, text))
UP.clear(); W._print("optimize", dict(PREFS), None, "upload")
ok(replies and not replies[-1][0] and "place d'abord les bobines" in replies[-1][1] and not UP, "Optimisé sans les bobines en place : refusé (%s)" % replies[-1][1][:90])
# on pose les bobines comme proposé, puis la U1 relit
by = {(x["ace"], x["slot"]): dict(x) for x in LIVE_H2}
feeders = [dict(f) for f in head_ctx()["feeders"]]
cols = {cc["t"]: cc for cc in rep["slicer_colors"]}
for r in pl:
    cc = cols[r["t"]]
    if r["kind"] == "ace":
        by[(r["ace"], r["slot"])] = P(r["ace"], r["slot"], cc["hex"][:7])
    else:
        for f in feeders:
            if f["head"] == r["head"]:
                f["color"] = cc["hex"][:7]
live_ok = [by[k] for k in sorted(by)]
d2 = run(live_ok, head_ctx(feeders=feeders), LOAD_H2)
rep2 = d2["report"]
ok(all(r["ok"] for r in rep2["_h"]["place"]["optimize"]), "bobines posées : placement complet")
ok(plugin(d2, "optimize") == direct("optimize"), "Optimisé : fichier identique au Preflight web")
W.report, W.info, W.live_sig = rep2, d2["info"], mb._signature(LIVE)
replies.clear(); UP.clear(); W._print("optimize", dict(PREFS), None, "upload")
ok(replies and replies[-1][0] and UP and UP[-1][0].endswith("/server/files/upload"), "Optimisé avec les bobines en place : envoyé (%s)" % replies[-1][1][:80])
# file d'impression multiACE : mode « head »
POSTS = []
_post0 = mb.MultiAce.post_json
mb.MultiAce.post_json = lambda self, path, body, timeout=None: POSTS.append((path, body)) or {"ok": True}
try:
    replies.clear(); UP.clear(); W._print("loadout", dict(PREFS), None, "queue")
finally:
    mb.MultiAce.post_json = _post0
ok(POSTS and POSTS[-1][1]["mode"] == "head" and replies[-1][0], "file multiACE : entrée en mode « head »")
# une voie vide n'est pas une cible du rapport : refusée avant toute réécriture
try:
    mb.head_ids(rep, {"0": "slot-1-3"}); ok(False, "voie vide")
except mb.MultiAceError as e:
    ok("illisible" in str(e), "choix d'une voie vide refusé")

# ---------- 2. mode tête avec 4 ACE, l'ACE 4 non connecté
LIVE4 = LIVE_H2 + [P(2, 0, "#000000"), P(2, 1, "#ffffff")]
ctx4 = head_ctx(ace_heads=[0, 1, 2, 3], head_ace={"0": 2, "1": 3, "2": 0, "3": 1}, feeders=[], connected_aces=[0, 1, 2],
                bg_heads=[0, 1, 2, 3])
d4 = run(LIVE4, ctx4, {0: (2, 0), 1: None, 2: (0, 0), 3: None})
r4 = d4.get("report") or {}
ok(r4.get("_h") and r4["_h"]["offline"] == [1] and r4["_h"]["head_ace"].get("1") == 3 and r4["_h"]["feeders"] == [],
   "4 ACE : l'ACE 4 (T2) signalé non connecté")

# ---------- 3. mode multi avec copies de couleur
LIVE_C = [P(0, 0, "#eff0f1"), P(0, 1, "#000000"), P(0, 2, "#e02020"), P(0, 3, "#009639"),
          P(1, 0, "#f7d959"), P(1, 1, "#ffffff"), P(1, 2, "#111111")]
ctx_c = {"mode": "multi", "connected_aces": [0, 1], "head_nozzle_types": dict(NOZ), "max_copies": 2,
         "empty_slots": [{"ace": 1, "slot": 3}], "manual_heads": []}
dc = run(LIVE_C, ctx_c, {0: (0, 0), 1: (0, 1), 2: (0, 2), 3: (1, 3)})
rc = dc.get("report") or {}
ok(rc.get("topology") == "multi" and rc.get("copies"), "multi + copies : rapport « par tête » de la U1 (copies %s)" % rc.get("copies"))
same_c = mb.head_forced(pp, core, rc, mb._LAST_HEAD[g], mb._LAST_CAPTURE[g], {})
ok(same_c["swaps"] == rc["plans"]["loadout"]["swaps"] and same_c["copies"] == rc["copies"], "copies recalculées = rapport de la U1")
ids_c = {str(t): v for t, v in mb.head_ids(rc).items()}
ok(plugin(dc, "loadout") == direct("loadout", ids_c, rc["copies"]), "multi + copies : fichier identique au Preflight web")

# ---------- 4. mode multi avec une tête alimentée à la main
LIVE_M = [P(0, 0, "#eff0f1"), P(0, 1, "#000000"), P(0, 3, "#f7d959"), P(1, 0, "#e02020"), P(1, 1, "#ffffff")]
ctx_m = {"mode": "multi", "connected_aces": [0, 1], "head_nozzle_types": dict(NOZ), "max_copies": 1,
         "manual_heads": [{"head": 2, "material": "PLA", "color": "#009639"}], "empty_slots": []}
dm = run(LIVE_M, ctx_m, {0: (0, 0), 1: (0, 1), 2: "feeder", 3: (0, 3)})
rm = dm.get("report") or {}
ok(rm.get("_h") and rm["_h"]["manual"] == [2] and any(t["id"] == "feeder-2" for t in rm["targets"]), "multi + tête à la main : T3 cible fixe")
ok(plugin(dm, "loadout") == direct("loadout", {str(t): v for t, v in mb.head_ids(rm).items()}, {}), "tête à la main : fichier identique au Preflight web")

# ---------- 5. code de la U1 sans mode « head » dans rewrite_pipeline : renvoi au Preflight web
SRC_save = dict(SRC)
SRC["core"] = SRC["core"].replace("remap_override=None, head_assignment=None,", "remap_override=None, head_assign=None,")
mb._u1code.update(sha=None)
LIVE["head_ctx"] = head_ctx(); LIVE["live_slots"] = LIVE_H2
try:
    mb.u1_report(c, g, "head.gcode"); ok(False, "ancien code")
except mb.U1CodeError as e:
    ok("mode tête" in str(e) and "Orca" in str(e), "multiACE sans mode « head » : renvoi au Preflight web (%s)" % e)
SRC.clear(); SRC.update(SRC_save); mb._u1code.update(sha=None)

# ---------- 6. fenêtre (vraies données)
from playwright.sync_api import sync_playwright
FAKE = """<script>window.__h=[];window.__p=[];window.orca={postMessage:function(m){window.__p.push(typeof m==="string"?JSON.parse(m):m)},onMessage:function(f){window.__h.push(f)}};</script>"""
def url(dd, nm, en=False):
    h = mb.U1_PAGE.replace("<head>", "<head>" + FAKE, 1).replace("__DATA__", json.dumps(dd).replace("</", "<\\/"))
    open("/home/claude/testdata/%s.html" % nm, "w").write(mb.i18n_page(h) if en else h); return "file:///home/claude/testdata/%s.html" % nm
mb._LANG["v"] = "fr"
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome"); pg = b.new_page(viewport={"width": 1220, "height": 1400})
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(url(d, "head1")); pg.wait_for_timeout(400)
    ok(pg.locator(".hmap .hcol").count() == 4 and pg.locator(".htr").count() == 4, "carte : une colonne par tête, 2 ACE et 2 chargeurs latéraux")
    ok(pg.locator('.hmap [data-sp="0_0"]').count() == 1 and pg.locator('.hmap [data-sp="f_0"]').count() == 1, "voies de l'ACE 1 et chargeur de T1 dessinés")
    ok(pg.locator("svg.paths line").count() > 4, "traits têtes -> bobines dessinés")
    names = pg.locator(".pr .pn").all_inner_texts()
    ok(names[:2] == ["Comme chargé", "Optimisé"] and "Par couche" in names, "plans : %s" % names)
    ok("En arrière-plan" in pg.inner_text('.pr[data-plan="loadout"]').replace(" ", " "), "arrière-plan affiché pour un plan")
    ok(pg.is_checked('input[value="loadout"]') and not pg.is_disabled("#go"), "Comme chargé choisi, lancement possible")
    pg.click('.pr[data-plan="optimize"]'); pg.wait_for_timeout(200)
    st = pg.inner_text(".steps").replace(" ", " ")
    ok("chargeur latéral de T1" in st and pg.locator(".steps [data-rl]").count() >= 1, "Optimisé : gestes, dont le chargeur latéral à charger")
    ok(pg.is_disabled("#go") and "Place les bobines d’abord" in pg.inner_text(".bar"), "Optimisé : lancement bloqué tant que les bobines ne sont pas posées")
    pg.click("#place"); pg.wait_for_timeout(250)
    ok(pg.locator(".cur").count() == 1 and pg.locator("svg.arrows path").count() >= 1, "placement pas à pas : geste en cours avec flèche")
    pg.click("#back"); pg.wait_for_timeout(150)
    pg.click('.pr[data-plan="loadout"]'); pg.wait_for_timeout(150)
    pg.click("#fo"); pg.wait_for_timeout(150)
    ok(pg.locator(".frow").count() == 5, "choix à la main : une ligne par filament")
    pg.click('[data-pk="3"]'); pg.wait_for_timeout(100)
    opts = pg.locator('.menu [data-ch="3"]').count()
    ok(opts == 1 + len(rep["targets"]), "choix à la main : Automatique + %d cibles PLA" % (opts - 1))
    pg.click('.menu [data-ch="3"][data-v="slot-1-0"]'); pg.wait_for_timeout(150)
    last = pg.evaluate("window.__p")[-1]
    ok(last.get("a") == "forced_est" and last.get("forced") == {"3": "slot-1-0"}, "choix envoyé à la U1 pour recalcul")
    res = dict(f1); key = last["key"]
    pg.evaluate("function(a){window.__orca_on_message({type:'fest',key:a[0],res:a[1]})}", [key, res]); pg.wait_for_timeout(200)
    ok(pg.inner_text('.pr[data-plan="loadout"] .v').split()[0] in pg.inner_text('.pr[data-plan="loadout"]') and
       str(f1["swaps"]) in pg.inner_text('.pr[data-plan="loadout"]'), "Comme chargé : échanges recalculés affichés (%s)" % f1["swaps"])
    pg.click("#go"); pg.wait_for_timeout(100)
    m = pg.evaluate("window.__p")[-1]
    ok(m.get("a") == "print" and m.get("plan") == "loadout" and m.get("forced") == {"3": "slot-1-0"}, "lancer : plan et choix envoyés")
    pg.evaluate("function(a){window.__orca_on_message({type:'fest',key:a,res:{error:'choix de bobine illisible'}})}", key); pg.wait_for_timeout(150)
    ok("Tes choix : choix de bobine illisible" in pg.inner_text(".h2s").replace(" ", " "), "erreur de choix affichée")
    pg.goto(url(dc, "headc")); pg.wait_for_timeout(400)
    ok(pg.locator(".hmap").count() == 0 and pg.locator(".tray").count() == 2 and "(copie)" in pg.inner_text("#pmap"), "multi + copies : carte des voies, copies marquées")
    pg.goto(url(dm, "headm")); pg.wait_for_timeout(400)
    pg.click('.pr[data-plan="optimize"]'); pg.wait_for_timeout(150)
    ok("T3, à la main" in pg.inner_text(".steps"), "tête à la main : geste « charge-la à la main »")
    pg.goto(url(d4, "head4")); pg.wait_for_timeout(400)
    ok("non connecté" in pg.inner_text("#pmap") and "l’ACE 4 n’est pas connecté" in pg.inner_text(".alerts"), "ACE non connecté signalé")
    ok(not errs, "aucune erreur JavaScript %s" % errs)
    b.close()
mb._LANG["v"] = "en"
FR = ("Chargeur", "chargeur", "Comme chargé", "Optimisé", "arrière-plan", "Mélange", "à charger", "Avant de lancer", "gestes", "voie", "tête")
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome"); pg = b.new_page(viewport={"width": 1220, "height": 1400})
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(url(d, "head1_en", en=True)); pg.wait_for_timeout(400)
    pg.click('.pr[data-plan="optimize"]'); pg.wait_for_timeout(250)
    t = pg.inner_text("body")
    left = [w for w in FR if w in t]
    ok("Side feeder" in t and "In the background" in t and "As loaded" in t and not left, "anglais : rien en français (%s)" % left)
    pg.click("#place"); pg.wait_for_timeout(250)
    t2 = pg.inner_text("body"); left2 = [w for w in FR if w in t2]
    ok(not left2, "anglais, placement pas à pas : rien en français (%s)" % left2)
    ok(not errs, "anglais : aucune erreur JavaScript %s" % errs)
    b.close()
mb._LANG["v"] = "fr"
shutil.rmtree(TMP, ignore_errors=True)
print("échecs :", len(FAILS))
sys.exit(1 if FAILS else 0)
