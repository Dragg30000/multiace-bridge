"""0.48.0 : multiACE 1.94 (vrai code de la U1 sur une fausse U1, fenêtre dans Chrome).
En mode multi, la U1 calcule ses plans « par tête » et propose deux portées pour Optimisé, Par couche et Moins de
mélange : « Bobines chargées » (plans_reorder, par défaut dans son Preflight web) et « Toutes les voies » (plans).
La fenêtre montre le même choix, « Bobines chargées » par défaut, et l'impression passe la même portée au code de la U1."""
import copy, json, os, re, sys, time
src = open("/home/claude/prive/test/u1code_test.py").read()
exec(src.split('ALL = {"bed": True, "flow": True, "cam": True}')[0])
from playwright.sync_api import sync_playwright

fails = 0
def check(c_, m):
    global fails
    print(("PASS " if c_ else "FAIL ") + m)
    fails += 0 if c_ else 1

def use(ref):
    SRC.clear(); SRC.update(_git_src(ref)); LIVE.clear(); LIVE.update(LIVE_NOW); mb._u1code.update(sha=None)

# ---------------------------------------------------------------- 1. côté plugin
use("v1.94")
rep, live, sha = mb.u1_report(c, g, "real.gcode")
pr = rep.get("plans_reorder") or {}
check(rep.get("head_mode") is True and set(pr) >= {"optimize", "color"} and mb._u1code["caps"].get("scope") is True,
      "multiACE 1.94 : plans par tête, portée « bobines chargées » dans le rapport, head_scope accepté")
check(mb.plan_scope_of(rep, {}) == "reorder" and mb.plan_scope_of(rep, {"scope": "all"}) == "all"
      and mb.plan_scope_of(rep, {"scope": "x"}) == "reorder" and mb.plan_scope_of({"plans": {}}, {"scope": "all"}) is None,
      "portée : « bobines chargées » par défaut, « toutes les voies » au choix, rien avant 1.94")

pp_, core_, _sha = mb.u1_code(c)
CALLS = []
_orig = core_.rewrite_pipeline
def spy(*a, **k):
    CALLS.append({x: k.get(x) for x in ("head_plan", "head_scope", "head_assignment")})
    return _orig(*a, **k)
core_.rewrite_pipeline = spy
W.report, W.live_sig = rep, mb._signature(live)
W.job = {"path": g, "name": "real.gcode", "host": host}

def head_print(plan, scope, how="print", prefs=None):
    CALLS.clear(); UP.clear(); sent.clear()
    W._print_head(plan, dict(prefs or {"bed": False}, scope=scope), None, how)
    return (sent[-1] if sent else {}), [p for p, _ in UP]

r_, paths = head_print("optimize", "reorder")
check(r_.get("done") and CALLS and CALLS[-1]["head_scope"] == "reorder" and CALLS[-1]["head_plan"] == "optimize"
      and paths == ["/server/files/upload"],
      "Optimisé, bobines chargées : rien à poser, imprimé avec head_scope=reorder : %s" % r_.get("text", "")[:90])
todo_all = [x["t"] for x in ((rep.get("_h") or {}).get("place") or {}).get("optimize") or [] if not x.get("ok")]
r_, paths = head_print("optimize", "all")
check(todo_all and not r_.get("done") and "place d'abord les bobines" in r_.get("text", "") and not paths,
      "Optimisé, toutes les voies : bobines à poser d'abord (filament %s), rien envoyé" % ", ".join(str(t + 1) for t in todo_all))
r_, paths = head_print("loadout", "reorder", prefs={"bed": True, "flow": True, "cam": True})
body = UP[-1][1].decode("utf-8", "replace") if UP else ""
check(r_.get("done") and CALLS[-1]["head_plan"] == "loadout" and CALLS[-1]["head_scope"] == "reorder" and CALLS[-1]["head_assignment"]
      and paths == ["/multiace/api/preflight/prefs", "/server/files/upload"] and 'name="print"' in body[:1024]
      and "; multiACE preflight prefs: BED_LEVEL=1 FLOW_CALIBRATE=1 TIME_LAPSE_CAMERA=1" in body and "; multiACE processed:" in body[:2 << 20],
      "multiACE 1.94, Comme chargé : options de départ envoyées, fichier marqué, impression lancée")
r_, paths = head_print("loadout", "reorder", how="upload")
check(r_.get("done") and paths == ["/server/files/upload"] and b'name="print"' not in UP[-1][1][:1024],
      "multiACE 1.94 : envoyer sans lancer")
inf = [k for k, v in pr.items() if not v.get("feasible")]
if inf:
    r_, paths = head_print(inf[0], "reorder")
    check(not r_.get("done") and "n'est pas possible" in r_.get("text", ""), "plan impossible avec les bobines chargées : refusé (%s)" % inf[0])
core_.rewrite_pipeline = _orig

W.prefs = {"bed": True}
W.on_message({"a": "scope", "v": "all"}); s1 = W.prefs.get("scope")
W.on_message({"a": "scope", "v": "tout"}); s2 = W.prefs.get("scope")
check(s1 == "all" and s2 == "all" and W.prefs.get("bed") is True, "choix de portée gardé pour la prochaine fenêtre, valeur inconnue ignorée")

# multiACE 1.91 : pas de portée, rien ne change
use("v1.91")
rep91, live91, _ = mb.u1_report(c, g, "real.gcode")
pp91, core91, _ = mb.u1_code(c)
check(not rep91.get("plans_reorder") and mb._u1code["caps"].get("scope") is False and mb.plan_scope_of(rep91, {"scope": "all"}) is None,
      "multiACE 1.91 : pas de portée (plans d'avant)")
CALLS.clear(); _o91 = core91.rewrite_pipeline
def spy91(*a, **k):
    CALLS.append(dict(k)); return _o91(*a, **k)
core91.rewrite_pipeline = spy91
W.report, W.live_sig = rep91, mb._signature(live91); UP.clear(); sent.clear()
W._print("slicer", {"bed": False, "scope": "reorder"}, how="print")
check(sent and sent[-1].get("done") and CALLS and "head_scope" not in CALLS[-1], "multiACE 1.91 : impression sans head_scope")
core91.rewrite_pipeline = _o91

# ---------------------------------------------------------------- 2. fenêtre dans Chrome
FAKE = """<script>window.__h=[];window.__p=[];window.orca={postMessage:function(m){window.__p.push(typeof m==="string"?JSON.parse(m):m)},onMessage:function(f){window.__h.push(f)}};</script>"""
os.makedirs("/home/claude/testdata", exist_ok=True)
def url(dd, nm, en=False):
    h = mb.U1_PAGE.replace("<head>", "<head>" + FAKE, 1).replace("__DATA__", json.dumps(dd).replace("</", "<\\/"))
    open("/home/claude/testdata/%s.html" % nm, "w").write(mb.i18n_page(h) if en else h)
    return "file:///home/claude/testdata/%s.html" % nm

use("v1.94")
W.window = None; sent.clear()
W.start(g, "real.gcode", host, delay=0)
for _ in range(160):
    time.sleep(0.25)
    if sent and sent[-1].get("report"):
        break
d94 = copy.deepcopy(sent[-1])
d94["prefs"] = {"bed": True, "zone": True, "flow": False, "cam": False, "soft": True, "unload": None}
d94["report"]["plans_reorder"]["optimize"]["swaps"] = 77          # pour savoir quel jeu de plans est affiché
ALL_OPT = d94["report"]["plans"]["optimize"]["swaps"]
keys = sorted({"%d_%d" % (m["ace"], m["slot"]) for p_ in (d94["report"]["plans"]["loadout"],) for m in p_.get("mapping") or []
               if m.get("kind") == "ace" and m.get("ace") is not None})
d94["load"]["slots"] = {k: {"grams": 500, "spool": None, "pa": {}} for k in ["0_0", "0_1", "0_2", "0_3", "1_1", "1_2", "1_3"]}

def cards(pg):
    return {e["k"]: e for e in pg.eval_on_selector_all(".pr[data-plan]", "a=>a.map(x=>({k:x.dataset.plan,sw:(x.querySelectorAll('.cell .v')[1]||{}).textContent,d:(x.querySelector('.pd')||{}).textContent||'',off:x.classList.contains('off')}))")}

with sync_playwright() as pw:
    br = pw.chromium.launch(executable_path="/usr/bin/google-chrome")
    for lang in ("fr", "en"):
        mb._LANG["v"] = lang
        fr = lang == "fr"
        pg = br.new_page(viewport={"width": 1220, "height": 1500})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(url(d94, "portee_" + lang, en=not fr)); pg.wait_for_selector(".pr[data-plan]", timeout=8000)
        seg = pg.eval_on_selector_all("[data-scope]", "a=>a.map(x=>[x.dataset.scope,x.textContent,x.getAttribute('aria-checked')])")
        check(seg == [["reorder", "Bobines chargées" if fr else "Loaded spools", "true"], ["all", "Toutes les voies" if fr else "All lanes", "false"]],
              lang + " : choix « Bobines chargées / Toutes les voies », bobines chargées par défaut %s" % seg)
        fog = pg.inner_text(".scope .fog")
        check(fog == ("Optimisé, Par couche et Moins de mélange gardent les bobines où elles sont, au besoin avec la couleur la plus proche." if fr else
                      "Optimized, Per layer and Less mixing keep the spools where they are, with the closest colour when needed."), lang + " : %r" % fog)
        cs = cards(pg)
        check(cs["optimize"]["sw"] == "77" and cs["loadout"]["sw"] == str(d94["report"]["plans"]["loadout"]["swaps"]),
              lang + " : plans « bobines chargées » affichés (Optimisé : %s échanges)" % cs["optimize"]["sw"])
        check(cs["optimize"]["d"].startswith("La U1 répartit les bobines en place" if fr else "The U1 spreads the loaded spools"),
              lang + " : description : %r" % cs["optimize"]["d"][:70])
        why = pg.inner_text('.pr[data-plan="layer"] .why') if pg.query_selector('.pr[data-plan="layer"] .why') else ""
        check(why.replace("\u00a0", " ") == ("Impossible ici : aucune disposition par couche possible avec les bobines chargées." if fr else
                                              "Not possible here: no per-layer layout possible with the loaded spools."),
              lang + " : Par couche impossible, raison traduite : %r" % why)
        pg.click('.pr[data-plan="optimize"]'); pg.wait_for_timeout(150)
        check(pg.query_selector("#place") is None and "posant les bobines" not in pg.inner_text(".plans"),
              lang + " : Optimisé, bobines chargées : rien à poser")
        pg.evaluate("window.__p.length=0"); pg.uncheck("#bed")
        pg.click("#go"); pg.wait_for_timeout(100)
        m_ = [x for x in pg.evaluate("window.__p") if x.get("a") == "print"]
        check(m_ and m_[-1]["plan"] == "optimize" and m_[-1]["scope"] == "reorder", lang + " : impression avec la portée : %s" % (m_[-1] if m_ else None))
        # toutes les voies
        pg.goto(url(d94, "portee2_" + lang, en=not fr)); pg.wait_for_selector(".pr[data-plan]", timeout=8000)
        pg.click('.pr[data-plan="optimize"]'); pg.wait_for_timeout(100)
        pg.evaluate("window.__p.length=0"); pg.click('[data-scope="all"]'); pg.wait_for_timeout(150)
        cs = cards(pg)
        check(pg.evaluate("window.__p") == [{"a": "scope", "v": "all"}] and cs["optimize"]["sw"] == str(ALL_OPT)
              and pg.get_attribute('[data-scope="all"]', "aria-checked") == "true",
              lang + " : « Toutes les voies » : plans d'origine (Optimisé : %s échanges), choix envoyé au plugin" % cs["optimize"]["sw"])
        check(("posant les bobines" if fr else "putting the spools") in cs["optimize"]["d"] or pg.query_selector("#place") is not None,
              lang + " : Optimisé, toutes les voies : bobines à poser : %r" % cs["optimize"]["d"][:90])
        pg.click('[data-scope="reorder"]'); pg.wait_for_timeout(120)
        check(cards(pg)["optimize"]["sw"] == "77", lang + " : retour à « Bobines chargées »")
        # choix gardé d'une fenêtre à l'autre, relecture des bobines
        d2 = copy.deepcopy(d94); d2["prefs"]["scope"] = "all"
        pg.goto(url(d2, "portee3_" + lang, en=not fr)); pg.wait_for_selector(".pr[data-plan]", timeout=8000)
        check(pg.get_attribute('[data-scope="all"]', "aria-checked") == "true" and cards(pg)["optimize"]["sw"] == str(ALL_OPT),
              lang + " : choix « Toutes les voies » gardé")
        nd = copy.deepcopy(d94); nd["auto"] = True; nd["report"]["plans_reorder"]["optimize"]["swaps"] = 55
        pg.click('[data-scope="reorder"]'); pg.wait_for_timeout(80)
        pg.evaluate("d=>window.__h.forEach(f=>f({type:'data',data:d}))", nd); pg.wait_for_timeout(150)
        check(cards(pg)["optimize"]["sw"] == "55" and pg.get_attribute('[data-scope="reorder"]', "aria-checked") == "true",
              lang + " : bobines relues : nouvelle analyse, portée gardée")
        # grammes par bobine en mode « par tête »
        gw = pg.eval_on_selector_all(".hmap .slot .gw, #pmap .slot .gw", "a=>a.map(x=>x.textContent)")
        check(gw and all(re.match(r"^[\d.]+ g / 500 g$", x) for x in gw), lang + " : grammes par bobine dans les colonnes par tête %s" % gw[:3])
        # multiACE avant 1.94 : pas de choix
        d3 = copy.deepcopy(d94); d3["report"].pop("plans_reorder")
        pg.goto(url(d3, "portee4_" + lang, en=not fr)); pg.wait_for_selector(".pr[data-plan]", timeout=8000)
        pg.evaluate("window.__p.length=0"); pg.uncheck("#bed"); pg.click("#go"); pg.wait_for_timeout(100)
        m_ = [x for x in pg.evaluate("window.__p") if x.get("a") == "print"]
        check(pg.query_selector("[data-scope]") is None and m_ and m_[-1]["scope"] is None, lang + " : rapport sans portée : pas de choix")
        check(not errs, lang + " : pas d'erreur JS %s" % errs)
        pg.close()
    br.close()
mb._LANG["v"] = None
print("\n%s" % ("TOUT OK" if not fails else "%d FAIL" % fails))
sys.exit(1 if fails else 0)
