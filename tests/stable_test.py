import os, sys, types, importlib.util, tempfile, shutil, threading
DATA = tempfile.mkdtemp(); STORE = os.path.join(DATA, "orca_plugins", "storage", "multiace"); os.makedirs(STORE)
open(os.path.join(STORE, "settings.json"), "w").write('{"host": "192.168.1.50"}')
sys.modules["orca"] = types.SimpleNamespace(pages=types.SimpleNamespace(PagesPluginCapabilityBase=object),
  slicing=types.SimpleNamespace(SlicingPipelineCapabilityBase=object), script=types.SimpleNamespace(ScriptPluginCapabilityBase=object),
  base=object, plugin=lambda c: c, host=types.SimpleNamespace(plugin=types.SimpleNamespace(storage=lambda: STORE)))
spec = importlib.util.spec_from_file_location("mb", "/home/claude/multiace_bridge/multiace_bridge_any.py"); mb = importlib.util.module_from_spec(spec); spec.loader.exec_module(mb)
ok = lambda c, m: print(("PASS " if c else "FAIL ") + m) or (c or sys.exit(1))
p = mb._settings_path()
ok(p == os.path.join(DATA, "multiace_bridge", "settings.json") and mb.load_settings()["host"] == "192.168.1.50", "old settings migrated outside plugin folder")
shutil.rmtree(STORE); os.makedirs(STORE)   # uninstall + reinstall
ok(mb.load_settings()["host"] == "192.168.1.50", "host survives reinstall")
seen = []
mb.MultiAce.get_json = lambda self, path, timeout=0: seen.append(threading.current_thread() is threading.main_thread())
mb.probe_network("192.168.1.50"); mb.probe_network("192.168.1.50")
ok(seen == [True], "probe runs once, on the calling (UI) thread")
print("ALL OK")
