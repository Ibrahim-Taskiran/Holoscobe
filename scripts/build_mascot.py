"""Build assets/mascot/cat.npz from the CC BY 4.0 model "3d modelling my cat: Fripouille" (guillaume bolis).

Developer tool, not needed at run time. Run it inside Blender (any version with Subdivision Surface):

    blender -b --factory-startup -P scripts/build_mascot.py -- <fripouille.glb> <assets/mascot>

It straightens the export (mesh and skeleton use different spaces), smooths the mesh once, and adds what the
renderer needs: a jaw weight, ear weights, fur length and a comb direction per vertex. The three-value "extra"
attribute is (jaw, fur length, ear: -1 left .. +1 right).
"""
import json
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np

BODY_MATERIAL = 1
HEAD, NECK, ARM_L, ARM_R = 5, 4, 7, 12
MOUTH_Y = 3.545


def read_glb(path):
    data = Path(path).read_bytes()
    size = int.from_bytes(data[12:16], "little")
    doc, blob = json.loads(data[20:20 + size]), data[20 + size + 8:]
    types = {5126: np.float32, 5123: np.uint16, 5125: np.uint32, 5121: np.uint8}
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

    def accessor(i):
        a = doc["accessors"][i]
        view = doc["bufferViews"][a["bufferView"]]
        start = view.get("byteOffset", 0) + a.get("byteOffset", 0)
        dtype, n = np.dtype(types[a["componentType"]]), width[a["type"]]
        stride = view.get("byteStride", 0) or dtype.itemsize * n
        rows = start + np.arange(a["count"])[:, None] * stride + np.arange(dtype.itemsize * n)
        return np.frombuffer(np.frombuffer(blob, np.uint8)[rows].tobytes(), dtype).reshape(a["count"], n)
    return doc, blob, accessor


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def canonical(path):
    """Positions and bone heads with +Z = where the cat looks, +Y = up and x = 0 on the midline."""
    doc, blob, accessor = read_glb(path)
    skin = doc["skins"][0]
    joints = skin["joints"]
    parent = {c: i for i, n in enumerate(doc["nodes"]) for c in n.get("children", [])}
    inverse = accessor(skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1).astype(float)
    heads = np.array([np.linalg.inv(m)[:3, 3] for m in inverse])
    parents = np.array([joints.index(parent[n]) if parent.get(n) in joints else -1 for n in joints])
    prim = next(m["primitives"][0] for m in doc["meshes"] if m["primitives"][0]["material"] == BODY_MATERIAL)
    at = prim["attributes"]
    pos = -0.01 * accessor(at["POSITION"]).astype(float) + [0.0125, 0.22, 0.068]
    x = heads[ARM_R] - heads[ARM_L]
    x /= np.linalg.norm(x)
    basis = np.array([x, [0, 1, 0], np.cross(x, [0, 1, 0])])
    origin = (heads[ARM_L] + heads[ARM_R]) / 2
    origin[1] = 0
    pos, heads = (pos - origin) @ basis.T, (heads - origin) @ basis.T
    pos[:, 0] += 0.03 * smoothstep(0.2, 1.2, pos[:, 2])          # the head sits a little off the skeleton midline
    for i, n in enumerate(joints):                                # leaf "_end" bones have no bind matrix
        if "_end" in doc["nodes"][n]["name"]:
            p = parents[i]
            heads[i] = heads[p] + (heads[p] - heads[parents[p]]) * 0.5
    joint, weight = accessor(at["JOINTS_0"]).astype(int), accessor(at["WEIGHTS_0"]).astype(float)
    dense = np.zeros((len(pos), len(joints)))
    for c in range(4):
        np.add.at(dense, (np.arange(len(pos)), joint[:, c]), weight[:, c])
    dense /= dense.sum(1, keepdims=True)
    faces = accessor(prim["indices"]).reshape(-1, 3).astype(int)
    a, b, c = (pos[faces[:, k]] for k in range(3))
    if (a * np.cross(b - a, c - a)).sum() < 0:
        faces = faces[:, ::-1]
    material = doc["materials"][BODY_MATERIAL]["pbrMetallicRoughness"]["baseColorTexture"]["index"]
    view = doc["bufferViews"][doc["images"][doc["textures"][material]["source"]]["bufferView"]]
    png = blob[view.get("byteOffset", 0):][:view["byteLength"]]
    return pos, accessor(at["TEXCOORD_0"]).astype(float), faces, dense, heads, parents, png


def smooth_mesh(pos, uv, faces, dense):
    _, first, weld = np.unique(pos.round(4), axis=0, return_index=True, return_inverse=True)
    weld = weld.ravel()
    mesh = bpy.data.meshes.new("cat")
    obj = bpy.data.objects.new("cat", mesh)
    bpy.context.scene.collection.objects.link(obj)
    bm = bmesh.new()
    layer, deform = bm.loops.layers.uv.new("uv"), bm.verts.layers.deform.new("w")
    verts = []
    for v in first:
        bv = bm.verts.new(pos[v])
        for b in np.nonzero(dense[v] > 1e-3)[0]:
            bv[deform][int(b)] = float(dense[v, b])
        verts.append(bv)
    for tri in faces:
        ids = weld[tri]
        if len(set(ids)) < 3:
            continue
        try:
            f = bm.faces.new([verts[i] for i in ids])
        except ValueError:
            continue
        f.smooth = True
        for loop, v in zip(f.loops, tri):
            loop[layer].uv = uv[v]
    bmesh.ops.join_triangles(bm, faces=bm.faces[:], angle_face_threshold=0.7, angle_shape_threshold=0.9, cmp_uvs=True)
    bm.to_mesh(mesh)
    bm.free()
    for b in range(dense.shape[1]):
        obj.vertex_groups.new(name=str(b))
    mod = obj.modifiers.new("s", "SUBSURF")
    mod.levels = 1
    mod.uv_smooth = "PRESERVE_BOUNDARIES"
    m = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh()
    m.calc_loop_triangles()
    co = np.array([v.co[:] for v in m.vertices])
    nr = np.array([v.normal[:] for v in m.vertices])
    wt = np.zeros((len(co), dense.shape[1]))
    for v in m.vertices:
        for g in v.groups:
            wt[v.index, g.group] = g.weight
    lu = np.array([d.uv[:] for d in m.uv_layers[0].data])
    tri_v = np.array([t.vertices[:] for t in m.loop_triangles])
    tri_l = np.array([t.loops[:] for t in m.loop_triangles])
    corner = np.c_[tri_v.ravel(), lu[tri_l.ravel()].round(5)]
    uniq, inv = np.unique(corner, axis=0, return_inverse=True)
    vi = uniq[:, 0].astype(int)
    return co[vi], nr[vi], uniq[:, 1:], wt[vi], inv.reshape(-1, 3)


def extras(pos, wt, uv, albedo):
    """Jaw, fur length, ear and comb direction."""
    x, y, z = pos.T
    head = wt[:, HEAD]
    h, w = albedo.shape[:2]
    rgb = albedo[np.clip((uv[:, 1] % 1 * h).astype(int), 0, h - 1), np.clip((uv[:, 0] % 1 * w).astype(int), 0, w - 1)]
    inside = (rgb.max(1) < 60) & (head > 0.4)                     # eye sockets and mouth interior are painted black
    jaw = np.where(y < MOUTH_Y, 1.0, 0.0) * smoothstep(0.95, 1.5, z) * (head > 0.3)
    ear = smoothstep(4.36, 4.62, y) * smoothstep(0.2, 0.34, np.abs(x)) * (head > 0.4) * np.sign(x)
    arms = wt[:, [8, 9, 10, 13, 14, 15]].sum(1)
    paws = wt[:, [10, 15, 27, 32]].sum(1)
    tail = wt[:, 18:23].sum(1)
    chest = smoothstep(-0.9, 0.2, z) * smoothstep(3.3, 2.4, y) * (1 - arms)
    ruff = smoothstep(0.2, 0.75, z) * smoothstep(1.25, 0.7, z) * smoothstep(0.35, 0.6, np.abs(x)) * smoothstep(4.3, 3.9, y)
    length = 0.085 + 0.07 * chest + 0.06 * ruff + 0.05 * tail
    length = length * (1 - 0.45 * arms) * (1 - 0.65 * paws)
    length *= 1 - 0.72 * smoothstep(1.15, 1.75, z) * (head > 0.4)
    eyes = np.minimum(np.linalg.norm(pos - [0.23, 4.0, 1.58], axis=1), np.linalg.norm(pos - [-0.23, 4.0, 1.58], axis=1))
    length *= smoothstep(0.10, 0.34, eyes) * 0.9 + 0.1
    nose = np.linalg.norm((pos - [0, 3.72, 1.94]) / [0.12, 0.09, 0.12], axis=1)
    length *= smoothstep(0.8, 1.5, nose)
    lips = np.abs(y - MOUTH_Y) + np.maximum(0, 1.5 - z)
    length *= 0.25 + 0.75 * smoothstep(0.02, 0.12, lips)
    length *= 1 - 0.80 * np.abs(ear)
    length[inside] = 0
    comb = np.tile([0.0, -0.35, -1.0], (len(pos), 1))             # towards the tail
    comb[arms > 0.3] = [0, -1, 0]
    face = head > 0.4
    comb[face] = np.c_[x * 0.9, (y - 3.85) * 0.9, np.full(len(x), -0.75)][face]
    comb[np.abs(ear) > 0.3] = [0, 1, -0.2]
    comb[chest > 0.4] = [0, -1, 0.1]
    comb /= np.linalg.norm(comb, axis=1, keepdims=True)
    return np.c_[jaw, np.clip(length, 0, None), ear], comb, inside


def main(src, dest):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    pos, uv, faces, dense, heads, parents, png = canonical(src)
    tmp = dest / "cat_albedo.png"
    tmp.write_bytes(png)
    image = bpy.data.images.load(str(tmp))
    px = np.array(image.pixels[:]).reshape(image.size[1], image.size[0], -1)[::-1, :, :3] * 255
    image.file_format = "JPEG"
    image.save(filepath=str(dest / "cat_albedo.jpg"), quality=93)
    tmp.unlink()
    pos, nrm, uv, wt, tri = smooth_mesh(pos, uv, faces, dense)
    extra, comb, inside = extras(pos, wt, uv, px)
    hidden = wt[:, [25, 26, 27, 28, 30, 31, 32, 33]].sum(1) > 0.5  # below the knee: never in the picture
    tri = tri[~hidden[tri].any(1)]
    keep, tri = np.unique(tri, return_inverse=True)
    pos, nrm, uv, wt, extra, comb, inside = (a[keep] for a in (pos, nrm, uv, wt, extra, comb, inside))
    tri = tri.reshape(-1, 3)
    order = np.argsort(-wt, axis=1)[:, :4]
    top = np.take_along_axis(wt, order, 1)
    top /= top.sum(1, keepdims=True)
    np.savez_compressed(
        dest / "cat.npz", pos=pos.astype(np.float32), nrm=nrm.astype(np.float32), uv=uv.astype(np.float32),
        joints=order.astype(np.uint8), weights=(top * 255).round().astype(np.uint8), extra=extra.astype(np.float32),
        comb=comb.astype(np.float32), inside=inside, tri=tri.astype(np.uint32), heads=heads.astype(np.float32),
        parents=parents.astype(np.int8))
    print("CAT", len(pos), "vertices", len(tri), "triangles", "jaw", int((extra[:, 0] > 0).sum()), "ear", int((extra[:, 2] != 0).sum()))


main(*sys.argv[sys.argv.index("--") + 1:][:2])
