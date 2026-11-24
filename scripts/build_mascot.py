"""Exports the Blender cat of cat_model.py to assets/mascot/cat.npz. Run with:

    blender -b --python scripts/cat_model.py --python scripts/build_mascot.py

Blender is Z up and looks along +Y; the mascot is +Y up and +Z towards the viewer: (x, y, z) -> (x, z, -y).
The eyes are drawn by a shader, so their spheres stay out of the file.
"""
from pathlib import Path

import bpy
import numpy as np

OUT = Path(__file__).resolve().parents[1] / "assets" / "mascot" / "cat.npz"
BONES = ("spine", "neck", "head", "jaw", "ear.R", "ear.L", "upper_arm.R", "forearm.R", "hand.R",
         "upper_arm.L", "forearm.L", "hand.L")             # rig.py order; "R" is on the left of the screen
GLOSS = {"Pati": 0.25, "Dil": 0.6, "Dis": 0.8, "Biyik": 0.4}
PARTS = ("Govde_Bas", "Kollar", "Alt_Cene", "Detay", "Dil", "Tuyler", "Tuyler_Kol", "Tuyler_Cene")
LIDS = ("Kapak_R", "Kapak_L")


def srgb(c):
    c = np.clip(np.asarray(c, float), 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def array(items, name, width, kind=np.float32):
    out = np.empty(len(items) * width, kind)
    items.foreach_get(name, out)
    return out.reshape(-1, width) if width > 1 else out


def axes(v):
    return np.stack((v[:, 0], v[:, 2], -v[:, 1]), 1)


def colors(ob):
    """sRGB color and gloss (0..1) of every vertex."""
    me, n = ob.data, len(ob.data.vertices)
    out = np.zeros((n, 4))
    if "Col" in me.color_attributes:
        out[:, :3] = srgb(array(me.color_attributes["Col"].data, "color", 4)[:, :3])
        return out
    for p in me.polygons:
        m = me.materials[p.material_index]
        rgb = srgb(m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value[:3])
        out[list(p.vertices)] = (*rgb, GLOSS.get(m.name, 0.0))
    return out


def part(name):
    ob = bpy.data.objects[name]
    me, n = ob.data, len(ob.data.vertices)
    assert np.allclose(ob.matrix_world, np.eye(4), atol=1e-6), name
    me.calc_loop_triangles()
    loops = array(me.loops, "vertex_index", 1, np.int32)
    normal = np.zeros((n, 3))
    np.add.at(normal, loops, array(me.corner_normals, "vector", 3))
    normal /= np.maximum(1e-9, np.linalg.norm(normal, axis=1, keepdims=True))
    weights = np.zeros((n, len(BONES)))
    index = {g.index: BONES.index(g.name) for g in ob.vertex_groups}
    for v in me.vertices:
        for g in v.groups:
            weights[v.index, index[g.group]] += g.weight
    joints = np.argsort(-weights, axis=1)[:, :4]
    top = np.take_along_axis(weights, joints, 1)
    top /= top.sum(1, keepdims=True)
    joints[top == 0] = 0
    byte = np.round(top * 255).astype(int)
    byte[:, 0] += 255 - byte.sum(1)                         # weights add up to exactly 255
    return dict(position=axes(array(me.vertices, "co", 3)).astype(np.float16),
                normal=np.round(axes(normal) * 127).astype(np.int8),
                color=np.round(colors(ob) * 255).astype(np.uint8),
                joints=joints.astype(np.uint8), weights=byte.astype(np.uint8),
                triangles=array(me.loop_triangles, "vertices", 3, np.int32))


def lid(name):
    """The closed position of every vertex, and +1 for the upper lid or -1 for the lower one."""
    ob = bpy.data.objects[name]
    basis, closed = (axes(array(ob.data.shape_keys.key_blocks[k].data, "co", 3)) for k in (0, 1))
    eye = 2.10                                               # height of the eyeballs
    side = np.sign(basis[:, 1] + closed[:, 1] - 2 * eye)
    # Tufts and sheet vertices belong to connected pieces; a piece follows the lid most of it lies on.
    group = np.arange(len(basis))
    edges = array(ob.data.edges, "vertices", 2, np.int32)
    while True:
        low = np.minimum(group[edges[:, 0]], group[edges[:, 1]])
        new = group.copy()
        np.minimum.at(new, edges[:, 0], low)
        np.minimum.at(new, edges[:, 1], low)
        if np.array_equal(new, group):
            break
        group = new
    total = np.bincount(group, side, minlength=len(basis))
    return closed.astype(np.float16), np.where(total[group] >= 0, 1, -1).astype(np.int8)


parts = [part(name) for name in PARTS + LIDS]
offset = np.cumsum([0] + [len(p["position"]) for p in parts])
for p, o in zip(parts, offset):
    p["triangles"] = (p["triangles"] + o).astype(np.uint32)
data = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
closed, upper = zip(*(lid(name) for name in LIDS))
np.savez_compressed(OUT, lid_start=offset[len(PARTS)], lid_closed=np.concatenate(closed), lid_upper=np.concatenate(upper), **data)
print("SAVED", OUT, OUT.stat().st_size, len(data["position"]), len(data["triangles"]),
      {n: np.median(p["color"], axis=0).tolist() for n, p in zip(PARTS + LIDS, parts)})
