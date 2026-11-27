"""0.47.0 : fenêtre d'envoi vivante (vrai code multiACE sur une fausse U1, fenêtre dans Chrome).
1. bobines relues toutes les 3 s pendant que la fenêtre est ouverte : nouvelle analyse sans message d'attente ni
   d'erreur, jamais de renvoi au Preflight ; en pause pendant un envoi, le placement pas à pas, et arrêtée une fois
   l'impression lancée ou la fenêtre fermée ;
2. grammes par couleur et par bobine, purge comprise (estimation de la U1), alerte de filament purge comprise ;
3. « Regarder la U1 » : écran (toucher, glisser), caméras, lumière, panneau multiACE ;
4. alerte quand deux filaments ont la même couleur sur l'aperçu ;
et la fenêtre en français et en anglais."""
import base64, copy, json, os, re, struct, sys, threading, time, zlib
exec(open("/home/claude/prive/test/couleurs_scenario.py").read().split('if __name__ == "__main__":')[0])
from playwright.sync_api import sync_playwright

fails = 0
def check(c_, m):
    global fails
    print(("PASS " if c_ else "FAIL ") + m)
    fails += 0 if c_ else 1

def png(w, h, fn):
    raw = b"".join(b"\x00" + b"".join(bytes(fn(x, y)) for x in range(w)) for y in range(h))
    def chunk(t, data):
        return struct.pack(">I", len(data)) + t + data + struct.pack(">I", zlib.crc32(t + data) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))

SCREEN_PNG = png(480, 272, lambda x, y: (40, 60 + y % 100, 90, 255))
CAM_PNG = png(320, 180, lambda x, y: (120, 90, 60, 255))
TAPS, LPOST, CAMREQ = [], [], []
CAMS = {"info": {"available": True, "cameras": [{"name": "U1", "kind": "mjpeg"}]}}
LIGHT = {"v": 0, "fail": False}
SCREEN = {"ok": True}
_get0, _post0 = H.do_GET, H.do_POST

def _bin(self, code, data, ctype):
    self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(data)))
    self.end_headers(); self.wfile.write(data)

def do_GET(self):
    p = self.path
    if p.startswith("/screen/snapshot"):
        return _bin(self, 200, SCREEN_PNG, "image/png") if SCREEN["ok"] else self._j(404, {})
    if p.startswith("/webcam/snapshot.jpg"):
        return _bin(self, 200, CAM_PNG, "image/png")
    if p.startswith("/multiace/api/webcam/snapshot"):
        CAMREQ.append(p); return _bin(self, 200, CAM_PNG, "image/png")
    if p.endswith("/webcam/info"):
        return self._j(200, CAMS["info"]) if CAMS["info"] is not None else self._j(404, {"detail": "Not Found"})
    if p.endswith("/print-control"):
        return self._j(200, {"light": LIGHT["v"], "speed": 100}) if LIGHT["v"] is not None else self._j(404, {})
    if p.startswith("/multiace/?") or p == "/multiace/":
        return _bin(self, 200, b"<html><body>multiACE mini</body></html>", "text/html")
    return _get0(self)

def do_POST(self):
    p = self.path
    if p.startswith("/screen/touch"):
        n = int(self.headers.get("Content-Length") or 0); self.rfile.read(n)
        TAPS.append(p); return self._j(200, {"ok": True})
    if p.endswith("/print-control"):
        n = int(self.headers.get("Content-Length") or 0); body = json.loads(self.rfile.read(n) or b"{}")
        LPOST.append(body)
        if LIGHT["fail"]:
            return self._j(502, {"detail": "moonraker: timeout"})
        LIGHT["v"] = body.get("value"); return self._j(200, {"verb": "light", "value": LIGHT["v"]})
    return _post0(self)
H.do_GET, H.do_POST = do_GET, do_POST
ORIGIN = "http://" + host
BASE_LIVE = copy.deepcopy(LIVE["live_slots"])

# ---------------------------------------------------------------- 1. ce que la fenêtre peut montrer de la U1
c = mb.MultiAce(host)
check(mb.live_sources(c) == {"origin": ORIGIN, "cams": ["U1"], "light": 0}, "U1 : une caméra listée, lumière éteinte")
CAMS["info"] = {"available": True, "cameras": [{"name": "Chambre", "kind": "mjpeg"}, {"name": "Plateau", "kind": "webrtc"},
                                               {"name": "Page", "kind": "iframe"}, {"kind": "mjpeg"}]}
LIGHT["v"] = 42.4
check(mb.live_sources(c) == {"origin": ORIGIN, "cams": ["Chambre", "Plateau"], "light": 42},
      "caméras listées par multiACE (pas les pages iframe ni les sans-nom), lumière en %")
CAMS["info"], LIGHT["v"] = None, None
check(mb.live_sources(c) == {"origin": ORIGIN, "cams": [], "light": None}, "multiACE sans ces accès (avant 1.90) : rien")
for bad in (True, "50", [1]):
    LIGHT["v"] = bad
    check(mb.live_sources(c)["light"] is None, "lumière illisible (%r) : pas d'interrupteur" % (bad,))
CAMS["info"] = {"available": True, "cameras": [{"name": "U1", "kind": "mjpeg"}]}; LIGHT["v"] = 0
TAPS.clear()
c.screen_touch("down", 10, 20); c.screen_touch("tap", 5, 6)
check(TAPS == ["/screen/touch?a=down&x=10&y=20", "/screen/touch?a=tap&x=5&y=6"], "geste envoyé à l'écran de la U1 : %s" % TAPS)

# ---------------------------------------------------------------- 2. relecture des bobines (fenêtre ouverte)
class FW:
    def __init__(s): s.open = True; s.posts = []
    def is_open(s): return s.open
    def post(s, m): s.posts.append(json.loads(json.dumps(m)))
    def close(s): s.open = False
def autos(fw): return [p for p in fw.posts if p.get("type") == "data" and (p.get("data") or {}).get("auto")]
def wait(f, t=10.0):
    end = time.time() + t
    while time.time() < end:
        if f(): return True
        time.sleep(0.05)
    return False

mb.WATCH_S = 0.25
fw = FW(); W.window = fw
sent.clear()
W.start(gpath, "watch.gcode", host, delay=0)
check(wait(lambda: sent and sent[-1].get("report")), "fenêtre ouverte : analyse de la U1")
d0 = sent[-1]
check(d0.get("auto") is False and d0.get("live") == {"origin": ORIGIN, "cams": ["U1"], "light": 0}, "données : pas une relecture, sources d'images")
n_sent = len(sent)
time.sleep(1.2)
check(not autos(fw) and len(sent) == n_sent, "bobines inchangées : rien de relu")

LIVE["live_slots"] = BASE_LIVE[:-1]           # une bobine retirée de la U1
check(wait(lambda: autos(fw)), "bobine retirée : nouvelle analyse")
a1 = autos(fw)[-1]["data"]
check(len(a1["report"]["live_slots"]) == len(BASE_LIVE) - 1 and W.report is not d0["report"]
      and W.live_sig == mb._signature(LIVE) and a1["live"] == d0["live"],
      "fenêtre mise à jour avec les bobines de la U1 (%d bobines)" % len(a1["report"]["live_slots"]))
check(len(sent) == n_sent and not any(x.get("loading") for x in sent[n_sent:]), "sans message d'attente ni nouvelle fenêtre")
time.sleep(1.0)
check(len(autos(fw)) == 1, "une seule relecture par changement")

W.on_message({"a": "watch", "on": False})
LIVE["live_slots"] = BASE_LIVE
time.sleep(1.2)
check(len(autos(fw)) == 1, "placement pas à pas (pause demandée par la fenêtre) : pas de relecture")
W.on_message({"a": "watch", "on": True})
check(wait(lambda: len(autos(fw)) == 2) and len(autos(fw)[-1]["data"]["report"]["live_slots"]) == len(BASE_LIVE), "reprise : relue")

with W._lock:
    W._busy = True
LIVE["live_slots"] = BASE_LIVE[1:]
time.sleep(1.2)
check(len(autos(fw)) == 2, "envoi en cours : pas de relecture")
W._busy = False
check(wait(lambda: len(autos(fw)) == 3), "envoi fini : relue")

# erreur pendant une relecture : rien affiché, rien envoyé au Preflight
orig_rep = mb.u1_report
def boom(*a, **k): raise mb.U1CodeError("code de test")
mb.u1_report = boom
n_up, n_posts = len(UP), len(fw.posts)
LIVE["live_slots"] = BASE_LIVE[2:]
time.sleep(1.5)
check(len(fw.posts) == n_posts and len(sent) == n_sent and not any("/preflight/inbox" in p or "upload" in p for p, _ in UP[n_up:]),
      "erreur du code de la U1 en relecture : rien affiché, rien envoyé au Preflight")
mb.u1_report = orig_rep
check(wait(lambda: len(autos(fw)) == 4), "code de nouveau lisible : relue")

# relecture lancée pendant qu'un envoi démarre : résultat jeté
seen = []
orig_print = W._print
def slow_print(*a):
    seen.append(W._busy); time.sleep(0.6)
W._print = slow_print
W.on_message({"a": "upload", "plan": "slicer", "bed": True})
check(W._busy is True, "« Envoyer » : relecture suspendue dès le clic")
check(wait(lambda: seen and not W._busy, 3) and seen == [True], "relecture reprise une fois l'envoi fini")
W._print = orig_print

W._reply(True, "Impression lancée avec le plan.", final=True)
check(W.job.get("final") is True, "impression lancée : fichier marqué")
n_a = len(autos(fw))
LIVE["live_slots"] = BASE_LIVE
time.sleep(1.2)
check(len(autos(fw)) == n_a and not (W._watcher and W._watcher.is_alive()), "impression lancée : plus de relecture")

fw2 = FW(); W.window = fw2; sent.clear()
W.start(gpath, "watch2.gcode", host, delay=0)
check(wait(lambda: sent and sent[-1].get("report")), "nouveau fichier : analyse")
check(wait(lambda: W._watcher is not None and W._watcher.is_alive(), 2), "nouveau fichier : relecture active")
fw2.open = False
LIVE["live_slots"] = BASE_LIVE[:-1]
time.sleep(1.2)
check(not autos(fw2) and not W._watcher.is_alive(), "fenêtre fermée : relecture arrêtée, aucune fenêtre rouverte")
LIVE["live_slots"] = BASE_LIVE
W.window = fw2 = FW(); sent.clear()
W._watch = False
W.on_message({"a": "reload"})
check(wait(lambda: sent and sent[-1].get("report")) and W._watch is True, "« Recharger » : relecture de nouveau active")

# toucher et lumière depuis la fenêtre
TAPS.clear()
for m in ({"ev": "tap", "x": 100, "y": 50}, {"ev": "down", "x": 1, "y": 2}, {"ev": "move", "x": 3, "y": 4}, {"ev": "up", "x": 5, "y": 6},
          {"ev": "click", "x": 1, "y": 1}, {"ev": "tap", "x": -1, "y": 1}, {"ev": "tap", "x": 5000, "y": 1}, {"ev": "tap", "x": True, "y": 1},
          {"ev": "tap", "x": "1", "y": 1}, {"ev": "tap", "x": 1.5, "y": 1}, {"ev": "tap", "x": 1}):
    W.on_message(dict(m, a="touch"))
time.sleep(1.0)
check(TAPS == ["/screen/touch?a=tap&x=100&y=50", "/screen/touch?a=down&x=1&y=2", "/screen/touch?a=move&x=3&y=4",
               "/screen/touch?a=up&x=5&y=6"], "toucher : gestes envoyés dans l'ordre, les autres refusés : %s" % TAPS)
fw2.posts.clear(); LPOST.clear(); LIGHT["v"] = 0
W.on_message({"a": "light", "on": True})
check(wait(lambda: any(p.get("type") == "light" for p in fw2.posts), 4), "lumière : réponse à la fenêtre")
lp = [p for p in fw2.posts if p.get("type") == "light"]
check(LPOST == [{"verb": "light", "value": 100}] and lp[-1] == {"type": "light", "value": 100} and W.job["lv"]["light"] == 100,
      "lumière allumée (POST /print-control light 100)")
W.on_message({"a": "light", "on": "oui"}); W.on_message({"a": "light"})
time.sleep(0.5)
check(len(LPOST) == 1, "demande de lumière illisible : rien")
LIGHT["fail"] = True; fw2.posts.clear()
W.on_message({"a": "light", "on": False})
check(wait(lambda: any(p.get("type") == "light" for p in fw2.posts), 4), "lumière refusée : réponse")
lp = [p for p in fw2.posts if p.get("type") == "light"][-1]
check(lp.get("error", "").startswith("Lumière non changée : ") and "value" not in lp, "lumière refusée : %s" % lp)
LIGHT["fail"] = False

# ---------------------------------------------------------------- 3. fenêtre dans Chrome
FAKE = """<script>window.__h=[];window.__p=[];window.orca={postMessage:function(m){window.__p.push(typeof m==="string"?JSON.parse(m):m)},onMessage:function(f){window.__h.push(f)}};</script>"""
os.makedirs("/home/claude/testdata", exist_ok=True)
def url(dd, nm, en=False):
    h = mb.U1_PAGE.replace("<head>", "<head>" + FAKE, 1).replace("__DATA__", json.dumps(dd).replace("</", "<\\/"))
    open("/home/claude/testdata/%s.html" % nm, "w").write(mb.i18n_page(h) if en else h)
    return "file:///home/claude/testdata/%s.html" % nm

THUMB = "data:image/png;base64," + base64.b64encode(png(48, 48, lambda x, y: (0, 0, 0, 255) if x < 24 else (253, 216, 53, 255))).decode()
dd = copy.deepcopy(d)          # 8 couleurs, 2 ACE, plans de la U1 (vrai code multiACE)
dd["info"]["thumb"] = THUMB
dd["live"] = {"origin": ORIGIN, "cams": [], "light": 0}
plan = dd["report"]["plans"]["slicer"]
pc = {x["t"]: x for x in plan["estimate"]["per_color"]}
def fmtg(v): return ("%.1f" % (round(v * 10) / 10)) if v < 10 else str(int(round(v)))
need = {t: pc[t]["print_g"] + pc[t]["purge_g"] for t in pc}
spools = {}
for m in plan["mapping"]:
    if m.get("slot"):
        k = "%d_%d" % (m["slot"]["ace"], m["slot"]["slot"])
        spools.setdefault(k, []).append(m["t"])
keys = sorted(spools)
small = keys[0]
dd["load"]["slots"] = {k: {"grams": 500, "spool": None, "pa": {}} for k in keys}
dd["load"]["slots"][small]["grams"] = 1
check(len(keys) >= 4 and all(pc[t]["purge_g"] > 0 for t in pc), "projet : %d bobines, purge sur chaque couleur" % len(keys))

def plain(s): return s.replace(" ", " ")

with sync_playwright() as pw:
    br = pw.chromium.launch(executable_path="/usr/bin/google-chrome")
    for lang in ("fr", "en"):
        mb._LANG["v"] = lang
        fr = lang == "fr"
        pg = br.new_page(viewport={"width": 1220, "height": 1500})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(url(dd, "vue_" + lang, en=not fr)); pg.wait_for_selector("#pmap .slot", timeout=8000)
        # -- grammes par couleur
        chips = pg.eval_on_selector_all(".fils div", "a=>a.map(x=>[x.querySelector('.n').textContent,(x.querySelector('.g')||{}).textContent||'',x.title])")
        want = [[str(t + 1), fmtg(need[t]) + " g"] for t in sorted(need)]
        check([c_[:2] for c_ in chips] == want, lang + " : grammes par couleur, purge comprise %s" % [c_[1] for c_ in chips])
        tip0 = ("impression %s g + purge %s g" if fr else "print %s g + purge %s g") % (fmtg(pc[0]["print_g"]), fmtg(pc[0]["purge_g"]))
        check(chips[0][2].endswith(tip0), lang + " : détail au survol : %r" % chips[0][2])
        facts = pg.inner_text(".tt p b")
        check((str(int(round(sum(need.values())))) + " g (purge comprise)" if fr else " g (purge included)") in plain(facts)
              and plain(facts).count(" g") == 1, lang + " : total purge comprise : %r" % facts)
        # -- grammes par bobine sur la carte
        gw = pg.eval_on_selector_all("#pmap .slot .gw", "a=>a.map(x=>[x.textContent,x.className,x.title])")
        exp = sorted([fmtg(sum(need[t] for t in spools[k])) + " g / " + ("1" if k == small else "500") + " g" for k in keys])
        check(sorted(x[0] for x in gw) == exp, lang + " : grammes par bobine : %s" % [x[0] for x in gw])
        bad = [x for x in gw if "bad" in x[1]]
        check(len(bad) == 1 and bad[0][0].endswith(" / 1 g"), lang + " : bobine qui ne suffit pas marquée")
        n_s = fmtg(sum(need[t] for t in spools[small]))
        check(bad[0][2] == ("Il faut environ %s g, purge comprise ; reste 1 g sur la bobine" if fr else
                            "About %s g needed, purge included; 1 g left on the spool") % n_s, lang + " : %r" % bad[0][2])
        al = pg.inner_text("ul.alerts")
        check(re.search((r"Pas assez de filament : .+ a encore 1 g, il en faut environ \d+ g, purge comprise \(filament [\d, ]+\)\."
                         if fr else r"Not enough filament: .+ has 1 g left, about \d+ g needed, purge included \(filament [\d, ]+\)\."), al) is not None,
              lang + " : alerte purge comprise : %r" % al.split("\n")[-1])
        # -- sans estimation de la U1 (multiACE avant 1.90) : grammes d'OrcaSlicer, comme avant
        d2 = copy.deepcopy(dd)
        for p_ in d2["report"]["plans"].values():
            p_.pop("estimate", None)
        pg.goto(url(d2, "vue2_" + lang, en=not fr)); pg.wait_for_selector("#pmap .slot", timeout=8000)
        g2 = pg.eval_on_selector_all(".fils .g", "a=>a.map(x=>x.textContent)")
        sg = d["info"]["grams"]
        check(g2 == [fmtg(g) + " g" for g in sg] and "purge" not in pg.inner_text(".tt p b"), lang + " : sans estimation, grammes d'OrcaSlicer")
        gw2 = pg.eval_on_selector_all("#pmap .slot .gw", "a=>a.map(x=>x.title)")
        check(gw2 and all("purge" not in x for x in gw2), lang + " : bobine sans « purge comprise »")
        check((re.search(r"il en faut environ \d+ g \(filament [\d, ]+\)\." if fr else r"about \d+ g needed \(filament [\d, ]+\)\.",
                         pg.inner_text("ul.alerts"))) is not None, lang + " : alerte d'avant")
        # -- couleurs identiques sur l'aperçu
        check(pg.query_selector("#tw") is None, lang + " : couleurs toutes différentes : pas d'alerte sur l'aperçu")
        d3 = copy.deepcopy(dd)
        sc = d3["report"]["slicer_colors"]
        sc[1]["hex"] = sc[0]["hex"]           # filaments 1 et 2 même couleur, bobines noire et jaune
        pg.goto(url(d3, "vue3_" + lang, en=not fr)); pg.wait_for_selector("#thumb", timeout=8000)
        tw = pg.get_attribute("#tw", "title") if pg.query_selector("#tw") else None
        tw_want = ("Filaments 1 + 2 : même couleur dans le projet, l’aperçu ne peut pas les séparer." if fr else
                   "Filaments 1 + 2: same colour in the project, the preview can’t tell them apart.")
        check(tw == tw_want, lang + " : alerte sur l'aperçu : %r" % tw)
        lab0 = pg.inner_text("#thumb .tl") if pg.query_selector("#thumb .tl") else None
        pg.click("#tw"); pg.wait_for_timeout(120)
        check(pg.inner_text(".bar .msg") == tw_want and (pg.inner_text("#thumb .tl") if pg.query_selector("#thumb .tl") else None) == lab0,
              lang + " : clic sur l'alerte : message, l'aperçu ne bascule pas")
        # -- relecture des bobines dans la page
        pg.goto(url(dd, "vue4_" + lang, en=not fr)); pg.wait_for_selector("#pmap .slot", timeout=8000)
        pg.uncheck("#bed")
        pg.click("#fo"); pg.wait_for_selector("[data-pk]", timeout=4000)
        pk = pg.eval_on_selector_all("[data-pk]", "a=>a.map(x=>+x.dataset.pk)")
        pg.click('[data-pk="%d"]' % pk[0]); pg.wait_for_selector("[data-ch]", timeout=4000)
        chs = pg.eval_on_selector_all('[data-ch="%d"]' % pk[0], "a=>a.map(x=>x.dataset.v)")
        keep_v = next(v for v in chs if v not in ("", None))
        pg.click('[data-ch="%d"][data-v="%s"]' % (pk[0], keep_v)); pg.wait_for_timeout(150)
        check(pg.query_selector("#unforce") is not None, lang + " : bobine imposée (filament %d -> %s)" % (pk[0] + 1, keep_v))
        kv = int(keep_v)
        nd = copy.deepcopy(dd); nd["auto"] = True
        gone = next(s for s in BASE_LIVE if s["ace"] * 4 + s["slot"] != kv)
        nd["report"]["live_slots"] = [s for s in nd["report"]["live_slots"] if (s["ace"], s["slot"]) != (gone["ace"], gone["slot"])]
        nd["prefs"] = dict(nd.get("prefs") or {}, bed=True)
        pg.evaluate("d=>window.__h.forEach(f=>f({type:'data',data:d}))", nd); pg.wait_for_timeout(150)
        note = pg.inner_text(".notice.auto") if pg.query_selector(".notice.auto") else ""
        check(note == ("Bobines changées sur la U1 : la fenêtre est à jour." if fr else "Spools changed on the U1: the window is up to date."),
              lang + " : relecture signalée : %r" % note)
        check(not pg.is_checked("#bed") and pg.query_selector("#unforce") is not None,
              lang + " : tes cases et ta bobine imposée (encore là) sont gardées")
        nd2 = copy.deepcopy(nd)
        nd2["report"]["live_slots"] = [s for s in nd2["report"]["live_slots"] if s["ace"] * 4 + s["slot"] != kv]
        pg.evaluate("d=>window.__h.forEach(f=>f({type:'data',data:d}))", nd2); pg.wait_for_timeout(150)
        check(pg.query_selector("#unforce") is None, lang + " : bobine imposée retirée de la U1 : choix enlevé")
        other = dict(nd, name="autre.gcode")
        pg.evaluate("d=>window.__h.forEach(f=>f({type:'data',data:d}))", other); pg.wait_for_timeout(100)
        check(pg.inner_text(".tt h1") == d["name"], lang + " : relecture d'un autre fichier : ignorée")
        pg.click("#go"); pg.wait_for_timeout(100)
        pg.evaluate("d=>window.__h.forEach(f=>f({type:'data',data:d}))", nd); pg.wait_for_timeout(150)
        check(pg.is_disabled("#go") and [x.get("a") for x in pg.evaluate("window.__p")][-1] == "print",
              lang + " : envoi en cours : relecture ignorée, bouton toujours bloqué")
        # placement pas à pas : relecture en pause
        pg.goto(url(dd, "vue5_" + lang, en=not fr)); pg.wait_for_selector("#pmap .slot", timeout=8000)
        pg.click('.pr[data-plan="optimize"]'); pg.wait_for_timeout(120)
        if pg.query_selector("#place"):
            pg.click("#place"); pg.wait_for_selector(".plh", timeout=4000)
            check({"a": "watch", "on": False} in pg.evaluate("window.__p"), lang + " : placement pas à pas : relecture mise en pause")
            check(pg.query_selector("#lk") is not None, lang + " : « Regarder la U1 » aussi pendant le placement")
            pg.evaluate("d=>window.__h.forEach(f=>f({type:'data',data:d}))", nd); pg.wait_for_timeout(120)
            check(pg.query_selector(".plh") is not None, lang + " : relecture ignorée pendant le placement")
            pg.click("#back"); pg.wait_for_timeout(120)
            check(pg.evaluate("window.__p")[-1] == {"a": "watch", "on": True}, lang + " : retour au plan : relecture reprise")
        else:
            check(False, lang + " : plan optimisé sans placement (scénario changé ?)")
        # -- « Regarder la U1 »
        pg.goto(url(dd, "vue6_" + lang, en=not fr)); pg.wait_for_selector("#lk", timeout=8000)
        check(pg.inner_text("#lk").strip() == ("Regarder la U1" if fr else "Look at the U1"), lang + " : bouton « Regarder la U1 »")
        pg.click("#lk"); pg.wait_for_selector("#lvov", timeout=3000)
        tabs = pg.eval_on_selector_all("#lvt button", "a=>a.map(x=>[x.textContent,x.className])")
        check([t[0] for t in tabs] == (["Écran", "Caméra", "Panneau multiACE"] if fr else ["Screen", "Camera", "multiACE panel"])
              and tabs[0][1] == "on", lang + " : onglets %s" % [t[0] for t in tabs])
        pg.wait_for_function("(()=>{var i=document.querySelector('#lvi');return i&&i.naturalWidth===480})()", timeout=5000)
        src = pg.get_attribute("#lvi", "src")
        check(src.startswith(ORIGIN + "/screen/snapshot?t="), lang + " : écran de la U1 : %s" % src[:60])
        box = pg.locator("#lvi").bounding_box()
        TAPS.clear(); pg.evaluate("window.__p.length=0")
        pg.mouse.click(box["x"] + box["width"] * 0.25, box["y"] + box["height"] * 0.5); pg.wait_for_timeout(120)
        t1 = [x for x in pg.evaluate("window.__p") if x.get("a") == "touch"]
        check(len(t1) == 1 and t1[0]["ev"] == "tap" and abs(t1[0]["x"] - 120) <= 1 and abs(t1[0]["y"] - 136) <= 1,
              lang + " : clic -> toucher à l'échelle de l'écran : %s" % t1)
        pg.evaluate("window.__p.length=0")
        pg.mouse.move(box["x"] + box["width"] * 0.2, box["y"] + box["height"] * 0.5); pg.mouse.down()
        for i in range(1, 9):
            pg.mouse.move(box["x"] + box["width"] * (0.2 + i * 0.07), box["y"] + box["height"] * 0.5); pg.wait_for_timeout(60)
        pg.mouse.up(); pg.wait_for_timeout(120)
        t2 = [x for x in pg.evaluate("window.__p") if x.get("a") == "touch"]
        check(t2 and t2[0]["ev"] == "down" and abs(t2[0]["x"] - 96) <= 1 and t2[-1]["ev"] == "up" and abs(t2[-1]["x"] - 365) <= 2
              and any(x["ev"] == "move" for x in t2) and all(x["ev"] in ("down", "move", "up") for x in t2),
              lang + " : glisser -> down, move, up : %s" % [(x["ev"], x["x"]) for x in t2])
        pg.click("#lvt button:nth-child(2)"); pg.wait_for_function("(()=>{var i=document.querySelector('#lvi');return i&&i.naturalWidth===320})()", timeout=5000)
        check(pg.get_attribute("#lvi", "src").startswith(ORIGIN + "/webcam/snapshot.jpg?t=") and pg.is_visible("#lvl")
              and not pg.is_checked("#lvli") and pg.inner_text("#lvl").strip() == ("Lumière" if fr else "Light"),
              lang + " : caméra du panneau, lumière éteinte")
        pg.evaluate("window.__p.length=0"); pg.check("#lvli"); pg.wait_for_timeout(80)
        check(pg.evaluate("window.__p") == [{"a": "light", "on": True}] and pg.is_disabled("#lvli"), lang + " : lumière demandée")
        pg.evaluate("()=>window.__h.forEach(f=>f({type:'light',value:100}))"); pg.wait_for_timeout(80)
        check(pg.is_checked("#lvli") and not pg.is_disabled("#lvli"), lang + " : lumière allumée")
        pg.evaluate("()=>window.__h.forEach(f=>f({type:'light',error:'Lumière non changée : moonraker'}))"); pg.wait_for_timeout(80)
        check(pg.inner_text("#lvm") == ("Lumière non changée : moonraker" if fr else "Light not changed: moonraker"), lang + " : lumière refusée affichée")
        pg.click("#lvt button:nth-child(3)"); pg.wait_for_selector("#lvc iframe", timeout=3000)
        check(pg.get_attribute("#lvc iframe", "src") == ORIGIN + "/multiace/?panel=1&theme=dark" and not pg.is_visible("#lvl"),
              lang + " : panneau multiACE")
        pg.evaluate("d=>window.__h.forEach(f=>f({type:'data',data:d}))", dict(copy.deepcopy(dd), auto=True)); pg.wait_for_timeout(120)
        check(pg.query_selector("#lvov") is not None, lang + " : relecture des bobines : la vue reste ouverte")
        pg.keyboard.press("Escape"); pg.wait_for_timeout(80)
        check(pg.query_selector("#lvov") is None, lang + " : Échap ferme")
        pg.click("#lk"); pg.wait_for_selector("#lvov"); pg.mouse.click(5, 5); pg.wait_for_timeout(80)
        check(pg.query_selector("#lvov") is None, lang + " : clic à côté ferme")
        pg.click("#lk"); pg.wait_for_selector("#lvx"); pg.click("#lvx"); pg.wait_for_timeout(80)
        check(pg.query_selector("#lvov") is None, lang + " : × ferme")
        # plusieurs caméras, pas de lumière, écran absent
        d7 = copy.deepcopy(dd); d7["live"] = {"origin": ORIGIN, "cams": ["Chambre", "Plateau"], "light": None}
        SCREEN["ok"] = False
        pg.goto(url(d7, "vue7_" + lang, en=not fr)); pg.wait_for_selector("#lk", timeout=8000)
        pg.click("#lk"); pg.wait_for_selector("#lvm.err", timeout=5000)
        check(plain(pg.inner_text("#lvm")).startswith("Écran distant indisponible." if fr else "Remote screen unavailable."),
              lang + " : écran indisponible : %r" % pg.inner_text("#lvm")[:60])
        tabs = pg.eval_on_selector_all("#lvt button", "a=>a.map(x=>x.textContent)")
        check(tabs == (["Écran", "Caméra Chambre", "Caméra Plateau", "Panneau multiACE"] if fr else
                       ["Screen", "Camera Chambre", "Camera Plateau", "multiACE panel"]), lang + " : une caméra par onglet %s" % tabs)
        CAMREQ.clear()
        pg.click("#lvt button:nth-child(3)"); pg.wait_for_function("(()=>{var i=document.querySelector('#lvi');return i&&i.naturalWidth===320})()", timeout=5000)
        check(pg.get_attribute("#lvi", "src").startswith(ORIGIN + "/multiace/api/webcam/snapshot?cam=Plateau&t=")
              and CAMREQ and not pg.is_visible("#lvl"), lang + " : caméra « Plateau » par multiACE, pas de lumière")
        SCREEN["ok"] = True
        d8 = copy.deepcopy(dd); d8.pop("live")
        pg.goto(url(d8, "vue8_" + lang, en=not fr)); pg.wait_for_selector("#pmap .slot", timeout=8000)
        check(pg.query_selector("#lk") is None, lang + " : sans adresse de la U1 : pas de bouton")
        check(not errs, lang + " : pas d'erreur JS %s" % errs)
        pg.close()
    br.close()
mb._LANG["v"] = None
print("\n%s" % ("TOUT OK" if not fails else "%d FAIL" % fails))
sys.exit(1 if fails else 0)
