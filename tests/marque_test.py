"""Correctif 0.46.3 : « le fichier préparé n'a pas la marque multiACE : envoi annulé » sur un fichier bon.
La marque de multiACE est juste avant la 1re couche, après les vignettes d'aperçu : avec une vignette lourde elle
était après les 64 Ko que lisait le Bridge. Vrai code multiACE (fausse U1) sur un vrai export de la U1."""
import base64, os, random, re, tempfile
src = open("/home/claude/prive/test/u1code_test.py").read().split("rep, live, sha = mb.u1_report")[0]
exec(src)

fails = 0
def check(c_, m):
    global fails
    print(("PASS " if c_ else "FAIL ") + m)
    fails += 0 if c_ else 1

# ---- 1. où le Bridge cherche la marque
def fake(pad, marker=True):
    p = tempfile.mktemp(suffix=".gcode")
    with open(p, "w") as f:
        f.write("; HEADER_BLOCK_START\n; THUMBNAIL_BLOCK_START\n")
        n = 0
        while n < pad:
            f.write("; " + "A" * 76 + "\n"); n += 79
        f.write("; THUMBNAIL_BLOCK_END\n; EXECUTABLE_BLOCK_START\nG28\n")
        if marker:
            f.write("; multiACE auto-load: load 2 head(s)\n; multiACE processed: format=13\n; multiACE auto-load: end\n")
        f.write(";LAYER_CHANGE\nG1 X1 E1\n" * 20000)
        f.write("; filament used [mm] = 10.5, 0, 3.2\nT3\n")
    return p
for pad, want in ((2000, True), (100 << 10, True), (500 << 10, True), (900 << 10, True), (1100 << 10, False)):
    p = fake(pad)
    fx = mb.gcode_facts(p)
    check(fx["processed"] is want, "marque à %d Ko : %s" % (pad >> 10, "trouvée" if want else "au-delà de 1 Mo, pas lue (multiACE lui-même : 512 Ko)"))
    check(fx["filaments_used"] == 2 and fx["u1control"] is False and fx["max_tool_seen"] == 3, "  et le reste lu comme avant (filaments utilisés, U1 Control, outils)")
check(mb.gcode_facts(fake(100 << 10, marker=False))["processed"] is False, "sans marque : refusé comme avant")

# ---- 2. vrai export de la U1 avec une vignette plus lourde, préparé par le vrai code multiACE
b = open("/tmp/g/real.gcode", "rb").read()
cut = b.find(b"\n", b.find(b"; THUMBNAIL_BLOCK_END")) + 1
random.seed(1)
for kb in (30, 260):
    blob = base64.b64encode(bytes(random.getrandbits(8) for _ in range(kb << 10))).decode()
    extra = ("; THUMBNAIL_BLOCK_START\n; thumbnail begin 512x512 %d\n" % len(blob)
             + "".join("; %s\n" % blob[i:i + 78] for i in range(0, len(blob), 78))
             + "; thumbnail end\n; THUMBNAIL_BLOCK_END\n").encode()
    g2 = tempfile.mktemp(suffix=".gcode")
    open(g2, "wb").write(b[:cut] + extra + b[cut:])
    rep, live, sha = mb.u1_report(c, g2, "vignette.gcode")
    try:
        final = mb.u1_prepare(c, g2, "vignette.gcode", "slicer", {}, mb._signature(live))
        err = None
    except Exception as e:
        final, err = None, str(e)
    pos = -1
    if final:
        with open(final, "rb") as fh:
            pos = fh.read(2 << 20).find(b"; multiACE processed:")
    check(err is None and pos > 65536, "vignette de +%d Ko : préparé et envoyé (marque à %d Ko, erreur : %s)" % (kb, pos >> 10, err))
print("\n%s" % ("TOUT OK" if not fails else "%d FAIL" % fails))
sys.exit(1 if fails else 0)
