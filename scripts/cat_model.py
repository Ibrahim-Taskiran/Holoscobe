"""The user's cat model (kedi_uret.py), built in an empty Blender scene; scripts/build_mascot.py exports it.

Differs from the original: the arms are separate meshes, because arms fused with the flank stretch like a bat's wing when they
are raised; they are made half open, which keeps elbows and wrists smooth; no texture baking or rendering.
"""
import bpy, math, numpy as np, openvdb as vdb
from mathutils import Vector, Quaternion
rng = np.random.default_rng(7)

# ---------- palette: retune here to match the real cat ----------
def hexc(h):
    v = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return np.array([((x + .055) / 1.055) ** 2.4 if x > .04 else x / 12.92 for x in v])
FUR, DARKFUR, LIGHT, EARPINK, NOSE, PAD, LINER, MOUTH, IRIS1, IRIS2 = map(
    hexc, ('434448', '28292c', '77787c', '554c50', '17181b', '64505a', '161618', '3a1018', 'bfbe62', '85893a'))
BODY, SILVER, HEADBACK = map(hexc, ('38383b', '505155', '3a3a3d'))
STRIPES = 0.0

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
col = sc.collection
ss = lambda a, b, x: (lambda t: t * t * (3 - 2 * t))(np.clip((x - a) / (b - a), 0, 1))

# ---------- SDF ----------
def ell(P, c, r):
    q = [P[i] - c[i] for i in range(3)]
    k0 = np.sqrt(sum((q[i] / r[i]) ** 2 for i in range(3)))
    k1 = np.sqrt(sum((q[i] / r[i] ** 2) ** 2 for i in range(3))) + 1e-6
    return k0 * (k0 - 1) / k1
def rc(P, a, b, r1, r2):
    ba = [b[i] - a[i] for i in range(3)]
    t = np.clip(sum((P[i] - a[i]) * ba[i] for i in range(3)) / sum(x * x for x in ba), 0, 1)
    return np.sqrt(sum((P[i] - a[i] - t * ba[i]) ** 2 for i in range(3))) - (r1 + (r2 - r1) * t)
def smin(a, b, k):
    h = np.clip(.5 + .5 * (b - a) / k, 0, 1)
    return b + (a - b) * h - k * h * (1 - h)
def smax(a, b, k): return -smin(-a, -b, k)

EYE = (.41, -.555, 2.10); ER = .305
GAZE = Vector((.28, -.96, .02)).normalized()
SH, EL, WR, PW = (.66, .10, .72), (1.0, .0, -.12), (.86, -.58, .16), (.80, -.74, .40)
def mouth_z(ax): return 1.525 + 2.6 * (np.minimum(ax, .5) - .17) ** 2
def ear(P, shift=0., r=.43, tip=.095):
    Q = (P[0], (P[1] - .06 + shift + .10 * (P[2] - 2.5)) * 1.75, P[2])
    return rc(Q, (.55, 0, 2.46), (.97, 0, 3.26), r, tip) / 1.35
def nose(P):
    return smin(ell(P, (.034, -1.12, 1.852), (.075, .062, .042)), ell(P, (0, -1.115, 1.815), (.045, .055, .05)), .03)
def skull(P):
    d = ell(P, (0, .04, 2.12), (.93, .86, .77))
    d = smin(d, ell(P, (.45, -.24, 1.80), (.50, .50, .42)), .22)           # cheeks
    d = smin(d, ell(P, (0, -.70, 1.80), (.35, .40, .27)), .18)             # muzzle base
    d = smin(d, ell(P, (.165, -.95, 1.69), (.22, .19, .165)), .06)         # puffs
    d = smin(d, rc(P, (0, -.60, 2.25), (0, -1.02, 1.87), .20, .115), .16)    # nose bridge
    d = smin(d, nose(P), .025)
    d = smin(d, ell(P, (0, -.84, 1.50), (.21, .21, .125)), .08)             # chin
    return d
def eyedist(P):
    o = [EYE[i] + GAZE[i] * .31 - (.018 if i == 2 else 0) for i in range(3)]
    return smin(ell(P, o, (.268, .27, .238)), ell(P, (o[0] + .07, o[1] + .02, o[2] + .045), (.20, .22, .165)), .08)
def jawzone(P):
    return np.maximum(P[2] - mouth_z(P[0]), rc(P, (0, -.66, 1.44), (0, -1.07, 1.50), .30, .25))
def cavity(P): return rc(P, (0, -.66, 1.575), (0, -.86, 1.565), .11, .08)
def paw(P):
    d = ell(P, PW, (.25, .185, .24))
    for dx, dz in ((-.15, .13), (-.055, .20), (.055, .20), (.15, .13)):
        d = smin(d, ell(P, (PW[0] + dx, PW[1] - .03, PW[2] + dz), (.085, .12, .10)), .035)
    return d
def body(P):
    d = ell(P, (0, .28, .55), (.74, .60, .80))
    d = smin(d, ell(P, (0, .30, -.45), (.86, .72, .95)), .30)
    d = smin(d, rc(P, (0, .25, .9), (0, .10, 1.6), .62, .64), .25)
    d = smin(d, ell(P, (0, -.10, 1.02), (.52, .42, .50)), .22)
    return d
# The arm mesh is made half open at the elbow and the wrist, so neither stretching nor folding it bends the skin far.
# "Modelled" is the original pose (elbow folded 112 degrees); rig.py folds the arm back into it.
_el, _wr = np.array(EL), np.array(WR)
def unit(v): return v / np.linalg.norm(v)
def turn(axis, deg):
    k = unit(axis); K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]]); t = math.radians(deg)
    return np.eye(3) + math.sin(t) * K + (1 - math.cos(t)) * K @ K
D_UP, D_FORE, D_HAND = unit(_el - np.array(SH)), unit(_wr - _el), unit(np.array([0, -.25, .97]))
R_FORE = turn(np.cross(D_UP, D_FORE), -56)
R_HAND = R_FORE @ turn(np.cross(D_FORE, D_HAND), -25)
WR_BIND = R_FORE @ (_wr - _el) + _el
def move(P, R, frm, to):                                   # points as a tuple of coordinate arrays
    q = [P[i] - frm[i] for i in range(3)]
    return tuple(sum(R[i, j] * q[j] for j in range(3)) + to[i] for i in range(3))
def fore_back(P): return move(P, R_FORE.T, _el, _el)
def hand_back(P): return move(P, R_HAND.T, WR_BIND, _wr)
def arms(P):
    F, H = fore_back(P), hand_back(P)
    d = smin(rc(P, SH, EL, .33, .25), rc(F, EL, WR, .25, .20), .05)
    d = smin(d, rc(H, WR, PW, .20, .20), .05)
    return smin(d, paw(H), .05)
def arm_blend(P):                                          # weight of everything below the elbow, below the wrist
    n1, n2 = unit(D_UP + R_FORE @ D_FORE), unit(R_FORE @ D_FORE + R_HAND @ D_HAND)
    return ss(-.30, .30, sum((P[i] - EL[i]) * n1[i] for i in range(3))), ss(-.17, .17, sum((P[i] - WR_BIND[i]) * n2[i] for i in range(3)))
def modelled(co, no):
    sx = np.where(co[:, 0] < 0, -1., 1.); m = np.stack([sx, np.ones(len(sx)), np.ones(len(sx))], 1); q, nq = co * m, no * m
    P = tuple(q.T); fo, ha = (w[:, None] for w in arm_blend(P)); ha = ha * fo
    out = q * (1 - fo) + np.stack(fore_back(P), 1) * (fo - ha) + np.stack(hand_back(P), 1) * ha
    nn = nq * (1 - fo) + nq @ R_FORE * (fo - ha) + nq @ R_HAND * ha
    return out * m, nn * m
def top(P):
    s = skull(P)
    eh = smax(ear(P), -ear(P, .17, .35, .035), .035)
    s = smin(s, smax(eh, 2.36 - P[2], .12), .14)
    s = smax(s, -(jawzone(P) - .004), .010)
    s = smax(s, -cavity(P), .03)
    s = smax(s, -ell(P, (.062, -1.185, 1.838), (.028, .05, .016)), .015)       # nostrils
    b = np.maximum(body(P), -np.maximum(jawzone(P) - .03, -.5 + 0 * P[2]))
    d = smin(s, b, .14)
    e = np.sqrt(sum((P[i] - EYE[i]) ** 2 for i in range(3)))
    d = smin(d, np.maximum(e - ER - .058, P[1] + .46), .12)
    d = smax(d, -(e - ER - .018), .01)
    d = smax(d, -eyedist(P), .05)
    return smax(d, -(P[2] + 1.15), .12)
def jaw(P):
    s = smax(skull(P), jawzone(P), .02)
    return smax(s, -cavity(P), .03)

def act(o):
    bpy.ops.object.select_all(action='DESELECT'); o.select_set(True); bpy.context.view_layer.objects.active = o
def fixn(o):
    act(o); bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.normals_make_consistent(inside=False); bpy.ops.object.mode_set(mode='OBJECT'); bpy.ops.object.shade_smooth()
def mesh_from(f, lo, hi, h, name, target):
    n = [int((hi[i] - lo[i]) / h) + 1 for i in range(3)]
    ax = [(lo[i] + h * np.arange(n[i])).astype(np.float32) for i in range(3)]
    X, Y, Z = np.meshgrid(*ax, indexing='ij')
    g = vdb.FloatGrid(1.0); g.copyFromArray(f((np.abs(X), Y, Z)).astype(np.float32))
    pts, quads = g.convertToQuads(0.0)
    me = bpy.data.meshes.new(name); me.from_pydata((np.asarray(pts) * h + np.array(lo)).tolist(), [], np.asarray(quads).tolist())
    ob = bpy.data.objects.new(name, me); col.objects.link(ob); act(ob)
    bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.separate(type='LOOSE'); bpy.ops.object.mode_set(mode='OBJECT')
    obs = list(bpy.context.selected_objects); big = max(obs, key=lambda o: len(o.data.vertices))
    print('ISLANDS', name, sorted(len(o.data.vertices) for o in obs)[::-1][:5])
    for o in obs:
        if o != big: bpy.data.objects.remove(o)
    big.name = name; fixn(big)
    m = big.modifiers.new('s', 'SMOOTH'); m.factor = .5; m.iterations = 3; bpy.ops.object.modifier_apply(modifier='s')
    nt = len(big.data.polygons) * 2
    if nt > target:
        m = big.modifiers.new('d', 'DECIMATE'); m.ratio = target / nt; bpy.ops.object.modifier_apply(modifier='d')
    bpy.ops.object.shade_smooth(); return big
def mat(n, c, r=.6):
    M = bpy.data.materials.new(n); M.use_nodes = True; b = M.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*c, 1); b.inputs['Roughness'].default_value = r; return M

h = .022
bd = mesh_from(top, (-1.4, -1.4, -1.3), (1.4, 1.15, 3.6), h, 'Govde_Bas', 70000)
ar = mesh_from(lambda P: arms(P), (.2, -1.4, -1.3), (1.7, .6, 1.2), .022, 'Kol', 18000)
jw = mesh_from(jaw, (-.5, -1.35, 1.05), (.5, -.1, 1.75), .014, 'Alt_Cene', 9000)

# ---------- colour as a function of position ----------
def mix(c, b, t): return c * (1 - t[:, None]) + np.asarray(b) * t[:, None]
def arrs(ob):
    me = ob.data; n = len(me.vertices); co = np.empty(n * 3, np.float32); no = np.empty(n * 3, np.float32)
    me.vertices.foreach_get('co', co); me.vertex_normals.foreach_get('vector', no)
    return co.reshape(-1, 3).astype(float), no.reshape(-1, 3).astype(float)
def color(co, no):
    x, y, z = np.abs(co[:, 0]), co[:, 1], co[:, 2]; P = (x, y, z); n = len(x)
    w = .035 * np.sin(x * 11 + z * 7 + y * 5) + .025 * np.sin(z * 19 - y * 13)
    c = np.tile(FUR, (n, 1))
    c = mix(c, HEADBACK, ss(-.25, .45, y))
    c = mix(c, BODY, ss(1.9, .5, z))
    c = mix(c, SILVER, .75 * (z < 1.2) * ss(.06, -.02, rc(P, EL, WR, .24, .19)) * ss(.1, -.4, y))
    c = mix(c, DARKFUR, .28 * ss(.1, .9, no[:, 1] * .7 + no[:, 2] * .5))
    head = ss(1.25, 1.4, z)
    fore = head * ss(2.32, 2.42, z) * ss(.25, -.1, y) * (z < 2.95)
    st = np.maximum.reduce([ss(.035, .012, np.abs(x - a - .30 * (z - 2.4))) for a in (.0, .15, .31)])
    ch = head * ss(.62, .72, x) * (z < 2.2) * (z > 1.45) * ss(.045, .015, np.abs(((z - .25 * x) % .2) - .1))
    armz = (x > .55) * (z < .75)
    bands = (1 - head) * (armz | (no[:, 1] > .1)) * ss(.06, .02, np.abs(((z + w) % .30) - .15))
    c = mix(c, DARKFUR, STRIPES * np.clip(fore * st + ch + bands * .8, 0, 1))
    c = mix(c, LIGHT, .30 * head * ss(1.80, 1.62, z + w + x * .3) * ss(-.45, -.70, y))
    c = mix(c, LIGHT, .62 * head * ss(1.25, .55, np.sqrt((x / .15) ** 2 + ((z - 1.96) / .13) ** 2)) * ss(-.6, -.75, y))
    c = mix(c, SILVER, .12 * (1 - head) * ss(.48, .25, x + w) * ss(.0, -.5, no[:, 1]) * (x < .55))
    c = mix(c, SILVER, .8 * ss(.06, -.02, paw(P)))
    ed = eyedist(P); fr = ss(-.35, -.5, y)
    c = mix(c, LIGHT, .14 * head * fr * ss(.12, .06, ed) * ss(2.0, 2.35, z))
    c = mix(c, LINER, head * fr * ss(.030, .008, ed))
    inner = ss(.030, .004, ear(P, .17, .35, .035)) * (z > 2.5) * ss(.04, .015, ear(P))
    c = mix(c, EARPINK, inner)
    c = mix(c, NOSE, ss(.022, .008, nose(P)) * ss(-1.0, -1.06, y))
    c = mix(c, LINER, .8 * ss(.014, .004, x) * (z < 1.80) * (z > 1.55) * ss(-.8, -.9, y))
    c = mix(c, MOUTH, ss(.022, .0, cavity(P)))
    return c
def paint(ob):
    co, no = arrs(ob); c = color(*(modelled(co, no) if ob.name == 'Kollar' else (co, no))); n = len(co)
    a = ob.data.color_attributes.new('Col', 'BYTE_COLOR', 'POINT')
    a.data.foreach_set('color', np.hstack([c, np.ones((n, 1))]).astype(np.float32).ravel()); return co, no
# One arm is meshed; the other one is its mirror image.
me = ar.data; n = len(me.vertices); V = [tuple(v.co) for v in me.vertices]; F = [tuple(p.vertices) for p in me.polygons]
two = bpy.data.meshes.new('Kollar'); two.from_pydata(V + [(-x, y, z) for x, y, z in V], [], F + [tuple(i + n for i in f[::-1]) for f in F])
bpy.data.objects.remove(ar); ar = bpy.data.objects.new('Kollar', two); col.objects.link(ar); act(ar); bpy.ops.object.shade_smooth()
cb, nb = paint(bd); cj, nj = paint(jw); ca, na = paint(ar)

# ---------- weights ----------
X, Y, Z = cb.T; ax = np.abs(X); P = (ax, Y, Z)
hd = ss(1.2, 1.55, Z); nk = ss(.8, 1.15, Z) * (1 - hd); rest = 1 - hd - nk
sp = rest
earw = hd * ss(2.62, 2.9, Z) * ss(.35, .5, ax)
WT = {'head': hd - earw, 'neck': nk, 'spine': sp}
for s, sg in (('L', X > 0), ('R', X <= 0)): WT['ear.' + s] = earw * sg
fo, ha = arm_blend((np.abs(ca[:, 0]), ca[:, 1], ca[:, 2])); AW = {}
for s, sg in (('L', ca[:, 0] > 0), ('R', ca[:, 0] <= 0)):
    AW['upper_arm.' + s] = sg * (1 - fo); AW['forearm.' + s] = sg * fo * (1 - ha); AW['hand.' + s] = sg * fo * ha
def setw(ob, d):
    for g, w in d.items():
        vg = ob.vertex_groups.new(name=g)
        for i in np.nonzero(w > .004)[0]: vg.add([int(i)], float(w[i]), 'REPLACE')
setw(bd, WT); setw(ar, AW); JW = {'jaw': np.ones(len(cj))}; setw(jw, JW)

# ---------- fur tufts (real geometry, gives a furry outline) ----------
def flow(co, limb):
    x = np.abs(co[:, 0]); sx = np.sign(co[:, 0])[:, None] + 0
    f = co - np.array([0, -1.18, 1.85]); f[:, 2] -= .15
    d = np.tile(np.array([0, .12, -1.0]), (len(co), 1))
    ef = np.stack([np.full(len(co), .25), np.full(len(co), .35), np.ones(len(co))], 1)
    is_head = co[:, 2] > 1.3; is_ear = (co[:, 2] > 2.72) & (x > .4)
    d[is_head] = f[is_head]; d[is_ear] = ef[is_ear] * np.hstack([np.sign(co[is_ear][:, :1]), np.ones((is_ear.sum(), 2))])
    if limb:
        fo, ha = (w[:, None] for w in arm_blend((x, co[:, 1], co[:, 2]))); ha = ha * fo
        d = (D_UP * (1 - fo) + R_FORE @ D_FORE * (fo - ha) + R_HAND @ D_HAND * ha) * np.hstack([sx, np.ones((len(co), 2))])
    return d / np.linalg.norm(d, axis=1, keepdims=True)
def tufts(ob, WTD, N, name):
    me = ob.data; me.calc_loop_triangles(); T = np.empty(len(me.loop_triangles) * 3, np.int32); me.loop_triangles.foreach_get('vertices', T); T = T.reshape(-1, 3)
    co, no = arrs(ob); A = np.linalg.norm(np.cross(co[T[:, 1]] - co[T[:, 0]], co[T[:, 2]] - co[T[:, 0]]), axis=1)
    k = rng.choice(len(T), N, p=A / A.sum()); r = rng.random((N, 2)); m = r.sum(1) > 1; r[m] = 1 - r[m]; b = np.c_[1 - r.sum(1), r]
    p = (co[T[k]] * b[..., None]).sum(1); nn = (no[T[k]] * b[..., None]).sum(1); nn /= np.linalg.norm(nn, axis=1, keepdims=True)
    limb = ob is ar; q, nq = modelled(p, nn) if limb else (p, nn)
    x = np.abs(q[:, 0]); PP = (x, q[:, 1], q[:, 2]); y, z = q[:, 1], q[:, 2]
    e = np.sqrt((x - EYE[0]) ** 2 + (y - EYE[1]) ** 2 + (z - EYE[2]) ** 2)
    nz = nose(PP)
    pads = (paw(PP) < .03) & (nq[:, 1] < -.45)
    ok = (eyedist(PP) > .030) & (e > ER + .035) & (nz > .022) & (cavity(PP) > .03) & (z > -1.08) & ~pads
    ok &= ~((np.abs(z - mouth_z(x)) < .03) & (rc(PP, (0, -.66, 1.44), (0, -1.07, 1.50), .30, .25) < .05))
    ok &= ~((ear(PP, .17, .35, .035) < .025) & (z > 2.5) & (ear(PP) < .03))
    if limb: ok &= body(PP) > -.12
    p, nn, k, b, q, nq = p[ok], nn[ok], k[ok], b[ok], q[ok], nq[ok]; x, y, z = np.abs(q[:, 0]), q[:, 1], q[:, 2]; N = len(p)
    d = flow(p, limb); d -= nn * (d * nn).sum(1, keepdims=True); d /= np.linalg.norm(d, axis=1, keepdims=True) + 1e-6
    L = .105 * np.ones(N); L = np.where(z > 1.3, .085, L); L *= np.where((z > 1.3) & (y < -.45), .45 + .55 * ss(-1.08, -.45, y), 1)
    L = np.where((z > 1.3) & (z < 2.1) & (x > .7), .13, L); L = np.where((z > 2.72) & (x > .4), .06, L)
    L = np.where((x < .5) & (y < 0) & (z < 1.25) & (z > .3), .14, L); L = np.where(limb & (y < -.3), .06, L)
    L *= .65 + .6 * rng.random(N); s = np.cross(d, nn); W = .0065 + .045 * L * rng.random(N)
    d = d + s * (rng.random((N, 1)) - .5) * .55; lift = .10 + .28 * rng.random(N)
    q0 = p - nn * .005; q2 = p + d * L[:, None] + nn * (L * lift)[:, None]
    V = np.stack([q0 - s * W[:, None], q0 + s * W[:, None], q2], 1).reshape(-1, 3)
    F = np.arange(N * 3).reshape(-1, 3)
    c = color(q, nq); br = (.86 + .28 * rng.random(N))[:, None]; C = np.repeat(c, 3, 0).reshape(N, 3, 3) * br[:, None]
    C *= np.array([[.84, .82, .81], [.84, .82, .81], [1.24, 1.24, 1.25]])[None]; C = np.clip(C, 0, 1).reshape(-1, 3)
    me = bpy.data.meshes.new(name); me.from_pydata(V.tolist(), [], F.tolist())
    a = me.color_attributes.new('Col', 'BYTE_COLOR', 'POINT'); a.data.foreach_set('color', np.c_[C, np.ones(len(C))].astype(np.float32).ravel())
    me.polygons.foreach_set('use_smooth', [True] * len(F)); me.normals_split_custom_set_from_vertices(np.repeat(nn, 3, 0).tolist())
    ob2 = bpy.data.objects.new(name, me); col.objects.link(ob2); src = T[k, 0]
    for g, w in WTD.items():
        wv = w[src]; idx = np.nonzero(wv > .004)[0]
        if len(idx):
            vg = ob2.vertex_groups.new(name=g)
            for i in idx: vg.add([int(i) * 3 + j for j in range(3)], float(wv[i]), 'REPLACE')
    M = bpy.data.materials.new('Tuy'); M.use_nodes = True; b_ = M.node_tree.nodes['Principled BSDF']; b_.inputs['Roughness'].default_value = .85
    v = M.node_tree.nodes.new('ShaderNodeVertexColor'); v.layer_name = 'Col'; M.node_tree.links.new(v.outputs['Color'], b_.inputs['Base Color']); me.materials.append(M)
    return ob2
fur = tufts(bd, WT, 88000, 'Tuyler'); fura = tufts(ar, AW, 34000, 'Tuyler_Kol'); furj = tufts(jw, JW, 7000, 'Tuyler_Cene')

# ---------- small parts ----------
def sweep(path, w, t, up, nseg=10):
    path = [Vector(p) for p in path]; V = []; F = []; n = len(path); up = Vector(up)
    for i, p in enumerate(path):
        tg = (path[min(i + 1, n - 1)] - path[max(i - 1, 0)]).normalized(); s = tg.cross(up).normalized(); u = s.cross(tg)
        for k in range(nseg):
            a = 2 * math.pi * k / nseg; V.append(p + s * (w[i] * math.cos(a)) + u * (t[i] * math.sin(a)))
    for i in range(n - 1):
        for k in range(nseg):
            k2 = (k + 1) % nseg; F.append((i * nseg + k, i * nseg + k2, (i + 1) * nseg + k2, (i + 1) * nseg + k))
    F += [tuple(range(nseg))[::-1], tuple((n - 1) * nseg + k for k in range(nseg))]
    return V, F
def on_paw(vf): return [Vector(R_HAND @ (np.array(v) - _wr) + WR_BIND) for v in vf[0]], vf[1]
def blob(c, r, n=14, m=10):
    V = [Vector((c[0] + r[0] * math.sin(math.pi * (i + .5) / m) * math.cos(2 * math.pi * k / n), c[1] + r[1] * math.cos(math.pi * (i + .5) / m), c[2] + r[2] * math.sin(math.pi * (i + .5) / m) * math.sin(2 * math.pi * k / n))) for i in range(m) for k in range(n)]
    F = [(i * n + k, i * n + (k + 1) % n, (i + 1) * n + (k + 1) % n, (i + 1) * n + k) for i in range(m - 1) for k in range(n)]
    return V, F + [tuple(range(n))[::-1], tuple((m - 1) * n + k for k in range(n))]
class Acc:
    def __init__(s, n): s.n, s.V, s.F, s.G, s.M, s.ms = n, [], [], [], [], []
    def add(s, vf, m, g, mirror=True):
        for sx in ((1, -1) if mirror else (1,)):
            V, F = vf; o = len(s.V); s.V += [(v.x * sx, v.y, v.z) for v in V]; s.F += [tuple(o + i for i in (f if sx > 0 else f[::-1])) for f in F]
            if m not in s.ms: s.ms.append(m)
            s.M += [s.ms.index(m)] * len(F); s.G += [g[:-1] + 'R' if sx < 0 and g.endswith('.L') else g] * len(V)
    def build(s):
        me = bpy.data.meshes.new(s.n); me.from_pydata(s.V, [], s.F)
        for m in s.ms: me.materials.append(m)
        me.polygons.foreach_set('material_index', s.M); ob = bpy.data.objects.new(s.n, me); col.objects.link(ob)
        for g in sorted(set(s.G)): ob.vertex_groups.new(name=g).add([i for i, x in enumerate(s.G) if x == g], 1, 'REPLACE')
        fixn(ob); return ob
M_pad, M_wh, M_to = mat('Pati', PAD, .55), mat('Biyik', hexc('eef0f2'), .4), mat('Dil', hexc('d9707c'), .35)
M_nose = mat('Burun', NOSE, .32)
D = Acc('Detay')
D.add(on_paw(blob((PW[0], PW[1] - .168, PW[2] - .045), (.105, .035, .078))), M_pad, 'hand.L')
for dx, dz in ((-.15, .13), (-.055, .20), (.055, .20), (.15, .13)):
    D.add(on_paw(blob((PW[0] + dx, PW[1] - .14, PW[2] + dz), (.042, .03, .052))), M_pad, 'hand.L')
for i in range(6):
    a = math.radians(16 - 8 * i); b0 = Vector((.22 + .05 * (i % 2), -1.08 + .03 * (i % 2), 1.755 - .025 * i)); L = .85 + .12 * (i % 3)
    D.add(sweep([b0 + Vector((L * t * math.cos(a), -.10 * t + .30 * t * t, L * t * math.sin(a) - .12 * t * t)) for t in np.linspace(0, 1, 9)], [.0065 * (1 - .9 * t) for t in np.linspace(0, 1, 9)], [.0065 * (1 - .9 * t) for t in np.linspace(0, 1, 9)], (0, 1, .1), 5), M_wh, 'head')
for i in range(2):
    b0 = Vector((.34 + .07 * i, -.70, 2.44))
    D.add(sweep([b0 + Vector(((.16 + .12 * i) * t, -.10 * t + .1 * t * t, .38 * t)) for t in np.linspace(0, 1, 7)], [.005 * (1 - .9 * t) for t in np.linspace(0, 1, 7)], [.005 * (1 - .9 * t) for t in np.linspace(0, 1, 7)], (0, 1, .1), 5), M_wh, 'head')
D.add(sweep([(-.15, -1.10 - .008 * t, 1.552 - .072 * t) for t in np.linspace(0, 1, 6)], [.022 * (1 - .85 * t) for t in np.linspace(0, 1, 6)], [.022 * (1 - .85 * t) for t in np.linspace(0, 1, 6)], (0, 1, 0), 8), mat('Dis', hexc('f3ead2'), .25), 'head', False)
det = D.build()
T_ = Acc('Dil')
T_.add(sweep([(0, -.62 - .28 * t, 1.505 + .02 * math.sin(3 * t)) for t in np.linspace(0, 1, 10)], [.085 * math.sqrt(max(.03, 1 - t ** 4)) for t in np.linspace(0, 1, 10)], [.022 * math.sqrt(max(.05, 1 - t ** 4)) for t in np.linspace(0, 1, 10)], (0, 0, 1), 12), M_to, 'jaw', False)
dil = T_.build()

# ---------- eyes ----------
s = 512; yy, xx = np.mgrid[0:s, 0:s]; u = (xx + .5) / s * 2 - 1; v = (yy + .5) / s * 2 - 1; r = np.hypot(u, v); th = np.arctan2(v, u)
img = np.ones((s, s, 4), np.float32); img[..., :3] = LINER
def lay(m, c): img[..., :3] = img[..., :3] * (1 - m[..., None]) + np.array(c) * m[..., None]
sm = lambda e, w, rr=None: np.clip((e - (r if rr is None else rr)) / w + .5, 0, 1)
lay(sm(.93, .05), IRIS2); lay(sm(.78, .30), IRIS1)
lay(sm(.90, .03) * (.5 + .5 * np.sin(th * 52 + 3 * np.sin(th * 7))) * .25, IRIS2 * .4)
lay(sm(.58, .03, np.hypot(u * 1.08, v * 1.0)), (.004, .004, .006))
lay(sm(.16, .03, np.hypot(u + .24, v - .30)), (1, 1, 1)); lay(sm(.07, .03, np.hypot(u - .22, v + .26)) * .8, (1, 1, 1))
img[..., :3] = np.where(img[..., :3] <= .0031, img[..., :3] * 12.92, 1.055 * np.clip(img[..., :3], 1e-6, 1) ** (1 / 2.4) - .055)
I = bpy.data.images.new('Goz', s, s); I.pixels.foreach_set(img.ravel()); I.update(); I.pack()
ME = mat('Goz', (1, 1, 1), .06); t = ME.node_tree.nodes.new('ShaderNodeTexImage'); t.image = I; ME.node_tree.links.new(t.outputs['Color'], ME.node_tree.nodes['Principled BSDF'].inputs['Base Color'])
M_lid = mat('Goz_Kapagi', FUR * .95, .85); M_rim = mat('Kirpik', LINER, .6); M_tuft = [mat('Kapak_Tuy%d' % q, FUR * v_, .85) for q, v_ in enumerate((.85, 1.0, 1.15))]; eyes = []; lids = []
for sfx, sg in (('L', 1), ('R', -1)):
    c = Vector((EYE[0] * sg, EYE[1], EYE[2])); g = Vector((GAZE.x * sg, GAZE.y, GAZE.z)); look = Vector((.20 * sg, -1, 0)).normalized()
    rt = Vector((0, 0, 1)).cross(look).normalized(); upv = look.cross(rt)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=32, radius=ER); e = bpy.context.object; e.name = 'Goz_' + sfx; bpy.ops.object.shade_smooth()
    e.data.materials.append(ME); uv = e.data.uv_layers.active.data
    for lp in e.data.loops:
        p = e.data.vertices[lp.vertex_index].co / ER; q = Vector((p.dot(rt), p.dot(upv)))
        if p.dot(look) < 0: q = q.normalized() * .99 if q.length > 1e-4 else Vector((.99, 0))
        uv[lp.index].uv = (.5 + q.x * .495, .5 + q.y * .495)
    e.location = c; act(e); bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    e.vertex_groups.new(name='eye.' + sfx).add(list(range(len(e.data.vertices))), 1, 'REPLACE'); eyes.append(e)
    R = math.radians; nu, nv = 28, 32; tl = Quaternion(g, R(6 * sg)); rt2 = Vector((0, 0, 1)).cross(g).normalized(); rt2 = tl @ rt2; up2 = g.cross(rt2)
    def wedge(a0, a1, r_):
        out = []
        for i in range(nv + 1):
            f = a0 + (a1 - a0) * i / nv
            for j in range(nu + 1):
                ph = R(-78 + 156 * j / nu); out.append(c + ((g * math.cos(f) + up2 * math.sin(f)) * math.cos(ph) + rt2 * math.sin(ph)) * r_)
        return out
    base, blink, F, MI = [], [], [], []
    for o0, o1, b0, b1 in ((R(66), R(130), R(-16), R(125)), (R(-68), R(-125), R(-14), R(-120))):
        o = len(base); t0 = wedge(o0, o1, ER * 1.04); n1 = len(t0); base += t0 + wedge(o0, o1, ER * 1.01); blink += wedge(b0, b1, ER * 1.105) + wedge(b0, b1, ER * 1.06)
        for off in (0, n1):
            for i in range(nv):
                for j in range(nu):
                    q = [o + off + i * (nu + 1) + j, o + off + i * (nu + 1) + j + 1, o + off + (i + 1) * (nu + 1) + j + 1, o + off + (i + 1) * (nu + 1) + j]
                    F.append(q if off == 0 else q[::-1]); MI.append(1 if i == 0 else 0)
        for j in range(nu): F.append([o + j, o + n1 + j, o + n1 + j + 1, o + j + 1]); MI.append(1)
    def pt(f, ph, r_): return c + ((g * math.cos(f) + up2 * math.sin(f)) * math.cos(ph) + rt2 * math.sin(ph)) * r_
    for o0, o1, b0, b1 in ((R(66), R(130), R(-16), R(125)), (R(-68), R(-125), R(-14), R(-120))):
        for _ in range(1500):
            a, l = rng.uniform(.06, .9), rng.uniform(.04, .10); ph = R(rng.uniform(-74, 74)); w = R(rng.uniform(.7, 1.6)); dp = R(rng.uniform(-3, 3)); lf = rng.uniform(.01, .045); o = len(base)
            for lst, x0, x1, rr in ((base, o0, o1, 1.04), (blink, b0, b1, 1.105)):
                f = lambda t: x0 + (x1 - x0) * t
                lst += [pt(f(a), ph - w, ER * rr), pt(f(a), ph + w, ER * rr), pt(f(min(1, a + l)), ph + dp, ER * (rr + (lf if lst is blink else 0)))]
            F.append([o, o + 1, o + 2]); MI.append(2 + int(rng.integers(3)))
    me = bpy.data.meshes.new('Kapak_' + sfx); me.from_pydata([tuple(q) for q in base], [], F); ob = bpy.data.objects.new('Kapak_' + sfx, me); col.objects.link(ob)
    [me.materials.append(q) for q in [M_lid, M_rim] + M_tuft]; me.polygons.foreach_set('material_index', MI); fixn(ob)
    ob.shape_key_add(name='Basis'); k = ob.shape_key_add(name='goz_kirp_' + sfx)
    for i, q in enumerate(blink): k.data[i].co = q
    k.value = 0; ob.vertex_groups.new(name='head').add(list(range(len(base))), 1, 'REPLACE'); lids.append(ob)

# ---------- rig ----------
arm = bpy.data.armatures.new('Iskelet'); rig = bpy.data.objects.new('Iskelet', arm); col.objects.link(rig); act(rig); bpy.ops.object.mode_set(mode='EDIT')
def bone(n, a, b, p=None):
    x = arm.edit_bones.new(n); x.head = a; x.tail = b
    if p: x.parent = arm.edit_bones[p]
bone('root', (0, .3, -1.15), (0, .3, -.8)); bone('spine', (0, .3, -.8), (0, .25, .8), 'root'); bone('neck', (0, .25, .8), (0, .12, 1.35), 'spine'); bone('head', (0, .12, 1.35), (0, .02, 2.8), 'neck'); bone('jaw', (0, -.46, 1.58), (0, -1.07, 1.50), 'head')
for sfx, g in (('L', 1), ('R', -1)):
    m = lambda p: (p[0] * g, p[1], p[2])
    bone('eye.' + sfx, m(EYE), m((EYE[0], EYE[1] - .4, EYE[2])), 'head'); bone('ear.' + sfx, m((.56, .04, 2.6)), m((.88, .04, 3.3)), 'head')
    bone('upper_arm.' + sfx, m(SH), m(EL), 'spine'); bone('forearm.' + sfx, m(EL), m(WR), 'upper_arm.' + sfx); bone('hand.' + sfx, m(WR), m((PW[0], PW[1] - .05, PW[2] + .25)), 'forearm.' + sfx)
bpy.ops.object.mode_set(mode='OBJECT')
allm = [bd, ar, jw, fur, fura, furj, det, dil] + eyes + lids
for o in allm: o.parent = rig; o.modifiers.new('Armature', 'ARMATURE').object = rig
print('ARM', 'WR_BIND', WR_BIND.round(4).tolist(), 'R_FORE', R_FORE.round(5).tolist(), 'R_HAND', R_HAND.round(5).tolist())
