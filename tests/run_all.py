"""Lance tous les tests du plugin (simulation : fausse U1 + faux OrcaSlicer). Usage : python run_all.py"""
import subprocess, sys, os
here = os.path.dirname(os.path.abspath(__file__))
# 0.41 (refonte privée) : ui_queue_test, mini_test, fold_test et pop_test testaient l'ancienne interface
# (tuiles des têtes, mini-panneau, cartes repliables, bulles) ; refonte_ui_test et refonte_window_test les remplacent.
tests = ["security_test", "harness", "home_test", "pipeline_test", "stable_test", "cleanup_test",
         "guard_test", "guard_live_test", "prep_test", "u1nozzle_test", "cam_test", "u1code_test", "host_test", "u1full_test", "v037_test",
         "refonte_ui_test", "refonte_window_test", "couleurs_test", "conseil_test", "depart_test"]
bad = []
env = dict(os.environ, PYTHONPATH=os.path.dirname(here))  # le moteur multiace_engine_127.py est a cote du plugin
for t in tests:
    r = subprocess.run([sys.executable, os.path.join(here, t + ".py")], cwd=here, capture_output=True, text=True, env=env)
    ok = r.returncode == 0 and "FAIL" not in r.stdout
    print(("OK   " if ok else "ECHEC"), t)
    if not ok:
        bad.append(t); print(r.stdout[-1500:], r.stderr[-1500:])
sys.exit(1 if bad else 0)
