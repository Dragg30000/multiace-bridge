"""0.45.0 : référence Python de l'aperçu repeint (même calcul que repaint() de la fenêtre, ui/u1.html).

Modèle des vignettes d'OrcaSlicer, mesuré sur de vraies vignettes : la couleur du filament est mélangée de
blanc, puis ombrée : pixel = s · (α·C + 1 − α) (+ reflet). Repeindre = multiplier chaque pixel par
(α·bobine + 1 − α) / (α·projet + 1 − α). Les étapes :
1. chaque pixel va à la couleur du projet qui l'explique le mieux (ombre comprise) ; filtre de majorité 3×3 ;
2. α est réglé sur les filaments colorés (le noir, le gris et le blanc n'en disent rien) ;
3. noir, gris et blanc ne diffèrent que par la clarté : on les départage par zones d'ombre continue ;
4. chaque pixel est multiplié par le rapport de son filament.

0.46.1 : aperçu plus vif.
- Le noir, le gris et le blanc (et les couleurs très sombres) : le modèle les voit trop clairs (le noir d'Orca n'est pas
  « blanc × ombre »). Leur clarté est mesurée sur l'image : luminance médiane ÷ ombrage typique des couleurs vives de la
  même image (0,47 sans couleur vive). Sans assez de pixels : droite mesurée sur de vraies vignettes (0,19 + 0,73 · Y).
- La bobine est rendue avec moins de blanc (α ≥ 0,85) : couleurs plus proches de la bobine, sur toute l'image.
"""
import math
import numpy as np

LUT = np.array([(c / 12.92) if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in np.arange(256) / 255.0])
GRID = [0.25 + 0.05 * i for i in range(16)]
A0 = GRID[7]
YW = np.array([0.2126, 0.7152, 0.0722])
S_DEF, K0, K1, AV = 0.47, 0.19, 0.73, 0.85        # mesurés sur une vraie vignette d'OrcaSlicer (0.46.1)


def lin_hex(h):
    h = h.lstrip("#")[:6]
    return np.array([LUT[int(h[i:i + 2], 16)] for i in (0, 2, 4)])


def to_byte(v):
    v = np.clip(v, 0.0, 1.0)
    v = np.where(v <= 0.0031308, v * 12.92, 1.055 * np.power(v, 1 / 2.4) - 0.055)
    return np.floor(v * 255 + 0.5).astype(np.uint8)


def mix(B, a):
    return a * B + (1 - a)


def classer(X, M):
    den = (M * M).sum(1)
    out = np.empty(len(X), dtype=np.int64)
    best = np.full(len(X), np.inf)
    for i in range(len(M)):
        s = np.clip((X @ M[i]) / den[i], 0.02, 1.6)
        d = X - s[:, None] * M[i]
        c = (d * d).sum(1) / (s * s * den[i] + 1e-4) + 0.035 * np.log(s / 0.55) ** 2
        m = c < best
        out[m], best[m] = i, c[m]
    return out


def majorite(E, K):
    h, w = E.shape
    pad = np.pad(E, 1, constant_values=-1)
    votes = np.zeros((K, h, w), dtype=np.int32)
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            v = pad[dy:dy + h, dx:dx + w]
            for k in range(K):
                votes[k] += (v == k)
    out = np.full(E.shape, -1)
    best = np.full(E.shape, -1)
    for k in range(K):
        m = votes[k] > best
        out[m], best[m] = k, votes[k][m]
    return np.where(E >= 0, out, -1)


def pct(v, q):
    v = np.sort(v)
    pos = (len(v) - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def gris_zones(E, px, B, a):
    K = len(B)
    gris = [i for i in range(K) if np.ptp(B[i]) < 0.1]
    if len(gris) < 2:
        return E
    h, w = E.shape
    Y = LUT[px[..., :3]] @ YW
    M = mix(B, a)
    att = {j: 0.9 * float(M[j] @ YW) for j in gris}
    isg = np.isin(E, gris)
    seen = np.zeros((h, w), bool)
    out = E.copy()
    for y0 in range(h):
        for x0 in range(w):
            if seen[y0, x0] or not isg[y0, x0]:
                continue
            st, zone = [(y0, x0)], []
            seen[y0, x0] = True
            while st:
                y, x = st.pop()
                zone.append((y, x))
                for yy, xx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                    if 0 <= yy < h and 0 <= xx < w and not seen[yy, xx] and isg[yy, xx]:
                        hi = max(Y[y, x], Y[yy, xx])
                        lo = max(min(Y[y, x], Y[yy, xx]), 1e-4)
                        if hi / lo < 1.35:
                            seen[yy, xx] = True
                            st.append((yy, xx))
            if len(zone) < 4:
                continue
            ys, xs = zip(*zone)
            y90 = pct(Y[ys, xs], 0.9)
            bj, bd = gris[0], math.inf
            for j in gris:
                d = abs(math.log(max(y90, 1e-4) / att[j]))
                if d < bd:
                    bd, bj = d, j
            out[ys, xs] = bj
    return out


def apparences(B, T, X, lab, a):
    """Apparence de chaque couleur du projet (AS) et de sa bobine (AT), dans les unités du modèle (0.46.1)."""
    K = len(B)
    M = mix(B, a)
    av = max(a, AV)
    V = mix(T, av)
    med, cnt = {}, {}
    for k in range(K):
        sel = X[lab == k]
        cnt[k] = len(sel)
        if cnt[k] >= 20:
            med[k] = np.median(sel, 0)
    num = den = 0.0
    for k in range(K):
        if k in med and np.ptp(B[k]) >= 0.1:
            num += cnt[k] * float(med[k] @ M[k]) / float(M[k] @ M[k])
            den += cnt[k]
    sbar = num / den if den else S_DEF
    lum = {}
    AS = M.copy()
    for k in range(K):
        if np.ptp(B[k]) < 0.1:                  # noir, gris, blanc, couleurs très sombres : clarté mesurée
            v = float(med[k] @ YW) / sbar if k in med else K0 + K1 * float(B[k] @ YW)
            v = min(max(v, 0.01), 1.5)
            lum[k] = v
            w = mix(B[k:k + 1], min(a, 0.95))[0]
            AS[k] = w * (v / max(float(w @ YW), 1e-4))
    AT = V.copy()
    for k in range(K):
        if np.ptp(T[k]) < 0.1:
            same = [j for j in range(K) if j in lum and np.array_equal(B[j], T[k])]
            v = lum[same[0]] if same else min(max(K0 + K1 * float(T[k] @ YW), 0.01), 1.5)
            w = mix(T[k:k + 1], min(av, 0.95))[0]
            AT[k] = w * (v / max(float(w @ YW), 1e-4))
    return AS, AT


def masque(px):
    a = px[..., 3]
    m = a >= 6
    if not (a < 250).any():                   # image opaque (JPG) : fond = médiane du bord
        bord = np.concatenate([px[0, :, :3], px[-1, :, :3], px[:, 0, :3], px[:, -1, :3]])
        bg = np.median(bord, 0)
        m &= np.abs(px[..., :3].astype(float) - bg).max(-1) > 18
    return m


def repaint(px, base, target):
    """px : (H, W, 4) uint8. base / target : couleurs #rrggbb, même ordre.
    Renvoie (nouvelle image, étiquettes, α) ; None si rien à peindre."""
    K = len(base)
    m = masque(px)
    if not K or not m.any():
        return None
    B = np.array([lin_hex(c) for c in base])
    T = np.array([lin_hex(c) for c in target])
    X = LUT[px[..., :3][m]]

    def etiquettes(a):
        E = np.full(m.shape, -1)
        E[m] = classer(X, mix(B, a))
        return majorite(majorite(E, K), K)

    E = etiquettes(A0)
    lab = E[m]
    C, cnt = {}, {}
    for i in range(K):
        sel = X[lab == i]
        cnt[i] = len(sel)
        if len(sel) >= 20:
            C[i] = np.median(sel, 0)
    best, ba = None, A0
    for a in GRID:
        M = mix(B, a)
        err, nn = 0.0, 0
        for i in range(K):
            if i not in C or np.ptp(B[i]) < 0.1:
                continue
            mm = float(M[i] @ M[i])
            s = float(C[i] @ M[i]) / mm
            d = C[i] - s * M[i]
            err += cnt[i] * float(d @ d) / (s * s * mm + 1e-6)
            nn += cnt[i]
        if nn and (best is None or err / nn < best):
            best, ba = err / nn, a
    if ba != A0:
        E = etiquettes(ba)
    E = gris_zones(E, px, B, ba)
    lab = E[m]
    AS, AT = apparences(B, T, X, lab, ba)
    r = AT / AS
    out = px.copy()
    out[..., :3][m] = to_byte(X * r[lab])
    return out, E, ba


# ---------- vignette de test « façon OrcaSlicer » (objet simple, couleur mélangée de blanc puis ombrée)
def vignette_demo(couleurs, taille=300, ss=3, alpha=0.72):
    """Socle + boules + petites boules, une couleur par forme (couleurs[0] = socle). Renvoie (RGBA uint8,
    étiquettes vraies : n° de couleur par pixel, -1 = fond ; seulement les pixels pleins)."""
    k = len(couleurs)
    formes = [((0.0, -0.62, 0.0), (0.58, 0.14, 0.58), 0)]
    rayons = [0.40, 0.29, 0.20]
    y = -0.18
    for i in range(1, k):
        if i <= 3:
            r = rayons[i - 1]
            formes.append(((0.0, y, 0.0), (r, r, r), i))
            y += r + (rayons[i] if i < 3 else 0.2) * 0.85
        else:                                  # boutons sur le devant du corps
            a = (i - 4) * 0.55 - 0.8
            formes.append(((0.34 * np.sin(a), -0.18 + 0.15 * np.cos(a * 1.7), 0.33 * np.cos(a) + 0.05),
                           (0.075, 0.075, 0.075), i))
    n = taille * ss
    u, v = np.meshgrid(np.linspace(-1.05, 1.05, n), np.linspace(1.05, -1.05, n))
    a_, b_ = np.radians(28), np.radians(-22)
    fwd = np.array([np.sin(a_) * np.cos(b_), np.sin(b_), -np.cos(a_) * np.cos(b_)])
    right = np.cross(fwd, [0, 1, 0]); right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    o = (u[..., None] * right + v[..., None] * up) - 4 * fwd
    best = np.full(u.shape, np.inf)
    nrm = np.zeros(u.shape + (3,))
    col = np.full(u.shape, -1)
    for c, r, ci in formes:
        c, r = np.array(c), np.array(r)
        oo, dd = (o - c) / r, fwd / r
        A = (dd * dd).sum()
        Bq = 2 * (oo * dd).sum(-1)
        Cq = (oo * oo).sum(-1) - 1
        disc = Bq * Bq - 4 * A * Cq
        t = np.where(disc > 0, (-Bq - np.sqrt(np.maximum(disc, 0))) / (2 * A), np.inf)
        hit = (t > 0) & (t < best)
        p = o + t[..., None] * fwd
        nn = (p - c) / (r * r)
        with np.errstate(invalid="ignore", divide="ignore"):
            nn = nn / (np.linalg.norm(nn, axis=-1, keepdims=True) + 1e-9)
        best = np.where(hit, t, best)
        nrm[hit] = nn[hit]
        col[hit] = ci
    L = np.array([-0.45, 0.75, 0.5]); L /= np.linalg.norm(L)
    H = L - fwd; H /= np.linalg.norm(H)
    diff = np.clip((nrm * L).sum(-1), 0, 1)
    spec = np.clip((nrm * H).sum(-1), 0, 1) ** 40
    base = np.array([lin_hex(h) for h in couleurs])
    lin = np.zeros(u.shape + (3,))
    m = col >= 0
    lin[m] = (0.10 + 0.80 * diff[m, None]) * (alpha * base[col[m]] + 1 - alpha) + 0.12 * spec[m, None]
    srgb = np.where(np.clip(lin, 0, 1) <= 0.0031308, np.clip(lin, 0, 1) * 12.92,
                    1.055 * np.power(np.clip(lin, 0, 1), 1 / 2.4) - 0.055) * m[..., None]
    rgba = np.concatenate([srgb, m[..., None].astype(float)], -1).reshape(taille, ss, taille, ss, 4).mean((1, 3))
    a4 = rgba[..., 3:4]
    rgba[..., :3] = np.where(a4 > 0, rgba[..., :3] / np.maximum(a4, 1e-6), 0)
    img = (np.clip(rgba, 0, 1) * 255 + 0.5).astype(np.uint8)
    # étiquette vraie d'un pixel plein : la couleur majoritaire de ses sous-pixels
    sub = col.reshape(taille, ss, taille, ss).transpose(0, 2, 1, 3).reshape(taille, taille, ss * ss)
    vraie = np.full((taille, taille), -1)
    plein = img[..., 3] == 255
    for i in range(k):
        cnt = (sub == i).sum(-1)
        vraie = np.where(plein & (cnt == ss * ss), i, vraie)
    return img, vraie


def png_data_url(img):
    import base64, io
    from PIL import Image
    b = io.BytesIO()
    Image.fromarray(img, "RGBA").save(b, "PNG")
    return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()


def from_data_url(url):
    import base64, io
    from PIL import Image
    return np.array(Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGBA"))
