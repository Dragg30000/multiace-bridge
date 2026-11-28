"""0.51.0 : le plugin en allemand et en chinois.
1. dictionnaires : chaque texte traduit en anglais l'est aussi en allemand et en chinois, %s / %d dans le même ordre ;
2. tr() : notifications et résultats dans la langue choisie (guillemets, ponctuation chinoise sans espace) ;
3. langue automatique (Windows ou environnement), réglage enregistré (fr, en, de, zh), durées (j / d / T / 天) ;
4. pages dans Chrome en allemand et en chinois : panneau, fenêtre d'impression ; aucune erreur, presque plus de français."""
import json, os, re, sys, tempfile, types, importlib.util
FILE = os.environ.get("MB_FILE", "/home/claude/prive/multiace_bridge_any.py")
S = tempfile.mkdtemp()
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object), slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object),
    script=types.SimpleNamespace(ScriptPluginCapabilityBase=object), base=object, plugin=lambda c: c, host=types.SimpleNamespace(plugin=types.SimpleNamespace(storage=lambda: S)))
sp = importlib.util.spec_from_file_location("mb", FILE); mb = importlib.util.module_from_spec(sp); sp.loader.exec_module(mb)
fails = 0
def check(c, m):
    global fails
    print(("PASS " if c else "FAIL ") + m, flush=True)
    fails += 0 if c else 1

# ---- 1. dictionnaires
check(mb.LANGS == ("auto", "fr", "en", "de", "zh") and set(mb._I18N) == {"en", "de", "zh"}, "langues : auto, fr, en, de, zh")
for lang in ("de", "zh"):
    d = mb._I18N[lang]
    miss = [k for k in mb._I18N_EN if k not in d]
    check(not miss, "%s : tout le dictionnaire anglais est traduit (%d textes, manquants : %s)" % (lang, len(d), miss[:5]))
    bad = [k for k, v in d.items() if re.findall(r"%[sd]", k) != re.findall(r"%[sd]", v) or not v.strip()]
    check(not bad, "%s : %%s / %%d dans le même ordre, rien de vide : %s" % (lang, bad[:3]))
    check(list(d) == sorted(d, key=lambda k: -len(k)), "%s : règles les plus longues d'abord" % lang)
check(mb._I18N["zh"]["Pause"] == "暂停" and mb._I18N["de"]["filament"] == "Filament", "mots identiques en français et en anglais traduits quand même")

# ---- 2. tr()
T = {"de": {"Terminé : Déchargement T2": "Fertig: Entladen T2",
            "ACE 2 : séchage terminé (3 h 20).": "ACE 2: Trocknung beendet (3 h 20).",
            "multiACE : \"x.gcode\" envoye au Preflight de 10.0.0.5": "multiACE: \"x.gcode\" gesendet an den Preflight von 10.0.0.5",
            "Calibration de ACE 1 · slot 2 sur T3 ajoutée à la file du panneau multiACE. Attends qu'elle soit finie, puis « Recharger » : le PA est mémorisé sur la bobine.":
                "Kalibrierung von ACE 1 · Slot 2 auf T3 zur Warteschlange des multiACE-Panels hinzugefügt. Warte, bis sie fertig ist, dann „Neu laden“: der PA wird auf der Spule gespeichert."},
     "zh": {"Terminé : Déchargement T2": "完成：卸载 T2",
            "ACE 2 : séchage terminé (3 h 20).": "ACE 2：干燥完成（3 h 20）。",
            "multiACE : \"x.gcode\" envoye au Preflight de 10.0.0.5": "multiACE：\"x.gcode\" 已发送至 Preflight：10.0.0.5",
            "Panneau multiACE masqué.": "multiACE 面板已隐藏。"}}
for lang, cases in T.items():
    mb._LANG["v"] = lang
    for fr, want in cases.items():
        got = mb.tr(fr)
        check(got == want, "%s : %s -> %s" % (lang, fr[:40], got))
mb._LANG["v"] = "fr"
check(mb.tr("Terminé : Déchargement T2") == "Terminé : Déchargement T2", "fr : inchangé")
# ---- 3. langue automatique, réglage, durées
for env, want in (("de_DE.UTF-8", "de"), ("zh_CN.UTF-8", "zh"), ("fr_FR.UTF-8", "fr"), ("en_US.UTF-8", "en"), ("pt_BR.UTF-8", "en")):
    old = {k: os.environ.get(k) for k in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE")}
    for k in old: os.environ.pop(k, None)
    os.environ["LANG"] = env
    got = mb.system_lang()
    for k, v in old.items():
        os.environ.pop(k, None)
        if v is not None: os.environ[k] = v
    check(got == want, "langue de l'environnement %s -> %s" % (env, got))
for v, want in (("de", "de"), ("zh", "zh"), ("xx", "auto")):
    json.dump({"lang": v}, open(mb._settings_path(), "w"))
    check(mb.load_settings()["lang"] == want, "réglage langue %s -> %s" % (v, want))
for lang, unit in (("fr", "j"), ("en", "d"), ("de", "T"), ("zh", "天")):
    mb._LANG["v"] = lang
    check(mb.fmt_left(26 * 3600).startswith("1 " + unit), "%s : durée de séchage longue en %s : %s" % (lang, unit, mb.fmt_left(26 * 3600)))
# ---- 4. pages
from playwright.sync_api import sync_playwright
FAKE = """<script>window.__h=[];window.__p=[];window.orca={postMessage:function(m){window.__p.push(typeof m==="string"?JSON.parse(m):m)},onMessage:function(f){window.__h.push(f)}};</script>"""
os.makedirs("/home/claude/testdata", exist_ok=True)
U1D = None
for f in ("couleurs_t.html", "ch_fr.html", "depart1.html"):
    p = "/home/claude/testdata/" + f
    if os.path.exists(p):
        m = re.search(r"\nvar D=(.*);\n", open(p, encoding="utf-8").read())
        if m:
            U1D = m.group(1); break
FRENCH = re.compile(r"\b([Bb]obines?|[Tt]êtes?|[Ii]mpression|[Aa]ucune?|[Cc]hargée?s?|[Dd]échargement|[Ss]échage|[Rr]églages?|[Vv]oie|[ÉéEe]changes?|filaments?)\b")
with sync_playwright() as pw:
    br = pw.chromium.launch(executable_path="/usr/bin/google-chrome")
    for lang in ("de", "zh"):
        mb._LANG["v"] = lang
        pg = br.new_page(viewport={"width": 340, "height": 1200}); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        open("/home/claude/testdata/lg_panel_%s.html" % lang, "w").write(mb.i18n_page(mb.PANEL.replace("__VERSION__", mb.VERSION)).replace("<head>", "<head>" + FAKE, 1))
        pg.goto("file:///home/claude/testdata/lg_panel_%s.html" % lang); pg.wait_for_timeout(150)
        send = lambda m: pg.evaluate("m=>window.__h.forEach(f=>f(m))", m)
        send({"command": "prefs", "host": "10.0.0.5", "progress": True, "folds": {}, "lang": lang})
        st = json.load(open("/home/claude/src/multiACE/tests/fixtures/mock_state.json")); st["printer_state"] = "printing"
        send({"command": "state", "state": st, "printer": "U1", "prog": {"state": "printing", "file": "Bear.gcode", "p": 0.42, "elapsed": 7800, "layer": 120, "layers": 650}})
        pg.wait_for_timeout(150); pg.click("#opt"); pg.wait_for_timeout(100)
        body = pg.inner_text("body")
        check(pg.evaluate("document.documentElement.lang") == lang and not errs, "%s : panneau sans erreur (%s)" % (lang, errs[:2]))
        want = {"de": ["Druck läuft", "Optionen", "Automatisches Homing bei Bedarf", "Bettkalibrierung"],
                "zh": ["正在打印", "选项", "需要时自动归零", "热床校准", "暂停"]}[lang]
        check(all(w in body for w in want), "%s : textes du panneau traduits : %s" % (lang, [w for w in want if w not in body]))
        left = sorted(set(FRENCH.findall(body)))
        check(not left, "%s : plus de mots français dans le panneau : %s" % (lang, left))
        check(pg.evaluate("document.getElementById('lang').value") == lang and pg.evaluate("[].map.call(document.querySelectorAll('#lang option'),o=>o.value)") == ["auto", "fr", "en", "de", "zh"],
              "%s : choix de la langue : auto, fr, en, de, zh" % lang)
        if U1D:
            pg2 = br.new_page(viewport={"width": 1220, "height": 900}); e2 = []; pg2.on("pageerror", lambda e: e2.append(str(e)))
            open("/home/claude/testdata/lg_u1_%s.html" % lang, "w").write(mb.i18n_page(mb.U1_PAGE.replace("__DATA__", U1D)).replace("<head>", "<head>" + FAKE, 1))
            pg2.goto("file:///home/claude/testdata/lg_u1_%s.html" % lang); pg2.wait_for_timeout(500)
            b2 = pg2.inner_text("body")
            left = sorted(set(FRENCH.findall(b2)))
            check(not e2 and not left, "%s : fenêtre d'impression sans erreur, sans mot français : %s %s" % (lang, e2[:2], left))
            pg2.screenshot(path="/home/claude/prive/test/shots/v051_u1_%s.png" % lang)
        pg.screenshot(path="/home/claude/prive/test/shots/v051_panel_%s.png" % lang, full_page=True)
    br.close()
mb._LANG["v"] = "fr"
print("TOUT OK" if not fails else "%d ÉCHEC(S)" % fails)
