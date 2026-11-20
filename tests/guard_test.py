"""Tests du garde-fou ACE (logique pure, sans U1 ni Orca)."""
import os, sys, types
sys.modules.setdefault("orca", types.SimpleNamespace(
    plugin=lambda c: c, base=object,
    pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
    script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
    slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import importlib
P = importlib.import_module("multiace_bridge_any")

def ace(i, conn=True, dry=None, fa=-1, auto=False):
    d = {"status": "drying", "target_temp": dry[0], "remain_time": dry[1]} if dry else {"status": "stop"}
    return {"idx": i, "connected": conn, "dryer": d, "feed_assist": fa, "auto_dry_running": auto}

def st(aces, printing=False, heads=None, active=0, swap=False):
    return {"aces": aces, "printer_state": "printing" if printing else "ready", "toolheads": heads or [],
            "active_device": active, "swap_in_progress": swap}

def head(t, a, s):
    return {"idx": t, "ace": a, "slot": s, "head_source_known": True}

ok = 0
def check(name, cond):
    global ok
    assert cond, name
    ok += 1
    print("OK", name)

kinds = lambda acts: [a[0] for a in acts if a[0] != "note"]

# 1. deconnexion vue puis retour : sechage relance tout seul, apres le delai
g = P.AceGuard(); t = 0
g.step(st([ace(1, dry=(55, 7200))]), None, t)
g.step(st([ace(1, conn=False)]), None, t + 2)
g.step(st([ace(1)]), None, t + 4)
check("pas de relance avant le delai", kinds(g.step(st([ace(1)]), None, t + 6)) == [])
acts = g.step(st([ace(1)]), None, t + 13)
check("relance sure apres le delai", acts and acts[0][0] == "dry" and acts[0][1] == 1 and acts[0][2] == 55
      and 115 <= acts[0][3] <= 120)
check("une seule relance", kinds(g.step(st([ace(1)]), None, t + 30)) == [])

# 2. arret sans deconnexion vue : on demande seulement
g = P.AceGuard()
g.step(st([ace(0, dry=(50, 3600))]), None, 0)
g.step(st([ace(0)]), None, 2)
acts = [a for a in g.step(st([ace(0)]), None, 11) if a[0] != "note"]
check("arret inexplique -> question", acts and acts[0][0] == "ask_dry")

# 3. arret demande depuis le panneau : rien
g = P.AceGuard()
g.step(st([ace(0, dry=(50, 3600))]), None, 0)
g.expect_stop(0, 1)
g.step(st([ace(0)]), None, 2)
check("arret volontaire ignore", kinds(g.step(st([ace(0)]), None, 20)) == [])

# 4. sechage presque fini ou sechage automatique : rien
g = P.AceGuard()
g.step(st([ace(0, dry=(50, 100)), ace(1, dry=(50, 3600), auto=True)]), None, 0)
g.step(st([ace(0, conn=False), ace(1, conn=False)]), None, 2)
g.step(st([ace(0), ace(1)]), None, 4)
check("fin normale / auto-dry ignores", kinds(g.step(st([ace(0), ace(1)]), None, 20)) == [])

# 5. ACE qui revient en sechant deja : rien
g = P.AceGuard()
g.step(st([ace(0, dry=(50, 3600))]), None, 0)
g.step(st([ace(0, conn=False)]), None, 2)
g.step(st([ace(0, dry=(50, 3590))]), None, 4)
check("deja relance par multiACE", kinds(g.step(st([ace(0, dry=(50, 3580))]), None, 20)) == [])

# 6. poussee : seulement la tete qui imprime, apres GUARD_FA_LOST
heads = [head(0, 0, 0), head(1, 0, 2), head(2, 1, 1)]
g = P.AceGuard()
s1 = st([ace(0, fa=-1), ace(1, fa=-1)], printing=True, heads=heads, active=0)
check("pas tout de suite", kinds(g.step(s1, 1, 0)) == [])
acts = g.step(s1, 1, 13)
check("relance de T2 seulement (ACE 1 slot 3)", [a for a in acts if a[0] == "fa"] == [("fa", 0, 2, 1)])
check("pas de rafale", kinds(g.step(s1, 1, 20)) == [])
check("nouvel essai apres 60 s", kinds(g.step(s1, 1, 74)) == ["fa"])
g.step(s1, 1, 135)
acts = g.step(s1, 1, 200)
check("abandon apres 3 essais, une alerte", kinds(acts) == [] and any(a[0] == "note" for a in acts))
check("alerte une seule fois", g.step(s1, 1, 300) == [])

# 7. poussee active ou autres cas : rien
g = P.AceGuard()
s2 = st([ace(0, fa=2)], printing=True, heads=heads, active=0)
check("poussee active", g.step(s2, 1, 0) == [] and g.step(s2, 1, 30) == [])
g = P.AceGuard()
s3 = st([ace(0, fa=-1), ace(1, fa=-1)], printing=True, heads=heads, active=0)
g.step(s3, 2, 0)
acts = g.step(s3, 2, 20)
check("ACE pas actif -> rien envoye", kinds(acts) == [] and any(a[0] == "note" for a in acts))
g = P.AceGuard()
s4 = st([ace(0, fa=-1)], printing=True, heads=heads, active=0, swap=True)
g.step(s4, 1, 0)
check("pendant un echange -> rien", g.step(s4, 1, 30) == [])
g = P.AceGuard()
s5 = st([ace(0, fa=-1)], printing=False, heads=heads, active=0)
g.step(s5, 1, 0)
check("hors impression -> rien", g.step(s5, 1, 30) == [])
g = P.AceGuard()
s6 = st([ace(0, fa=-1)], printing=True, heads=[dict(head(1, 0, 2), manual=True)], active=0)
g.step(s6, 1, 0)
check("tete manuelle -> rien", g.step(s6, 1, 30) == [])

# 8. poussee qui revient apres un essai : message
g = P.AceGuard()
g.step(s1, 1, 0); g.step(s1, 1, 13)
s7 = st([ace(0, fa=2), ace(1, fa=-1)], printing=True, heads=heads, active=0)
check("poussee revenue signalee", any(a[0] == "note" for a in g.step(s7, 1, 20)))

# 9. etat bizarre : pas de plantage
g = P.AceGuard()
check("etat vide", g.step({}, None, 0) == [])
check("valeurs fausses", g.step({"aces": [{"idx": "x"}, {"idx": 0, "connected": True, "dryer": "?"}],
                                  "printer_state": "printing", "toolheads": [{"idx": 0, "ace": None}]}, 0, 0) == [])
print("\n%d tests OK" % ok)
