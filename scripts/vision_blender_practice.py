"""Blender background script: 3D renders with known faults (plan 24 practice, 3D half).

Run privately (no window):
  blender.exe -b --factory-startup --python scripts/vision_blender_practice.py -- <out_dir>

Subjects: the seven LAYA 3D Kronos models (D:/NeyviaRuns/laya-3d/kronos/out/*/*.glb) and five
procedural props. Each subject is normalised to its declared real-world height, stands on a
floor next to a 1.8 m reference mannequin, and is rendered (Workbench, backface culling on, as
a game engine draws it) in four conditions x two views (stage with reference, close on the declared size):
  clean            -- as built;
  flipped-normals  -- a contiguous third of the faces reversed (they vanish under culling);
  floaters         -- 1-3 small detached chunks joined into the object, off its surface;
  wrong-scale      -- the object scaled x6 or x0.12 (it still stands on the floor).
LAYA made every fault, so every render is a perfect episode. Writes <out>/renders.json.
"""
import json
import math
from pathlib import Path
import random
import sys

import bpy
import bmesh
from mathutils import Vector

OUT = Path(sys.argv[sys.argv.index('--') + 1]).resolve()
OUT.mkdir(parents=True, exist_ok=True)
KRONOS = Path('D:/NeyviaRuns/laya-3d/kronos/out')
HEIGHTS = {'backpack': 0.55, 'body-tpose': 1.75, 'body-turnaround': 1.75, 'boot': 0.32, 'emblem': 0.25,
           'gun-mode': 0.9, 'main-weapon': 1.1, 'chair': 0.9, 'table': 0.75, 'mug': 0.11, 'lamp': 1.6, 'crate': 0.6}
OBJECT_COLOR = (0.95, 0.45, 0.12, 1)
REFERENCE_COLOR = (0.35, 0.45, 0.75, 1)
BACKGROUND = (0.07, 0.08, 0.11)
_ARGS = sys.argv[sys.argv.index('--') + 1:]
SEED = int(_ARGS[_ARGS.index('--seed') + 1]) if '--seed' in _ARGS else 26
VIEWS = tuple(_ARGS[_ARGS.index('--views') + 1].split(',')) if '--views' in _ARGS else ('front', 'close', 'close-high')
rnd = random.Random(SEED)


def clear():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for block in (bpy.data.meshes, bpy.data.materials):
        for item in list(block):
            if item.users == 0:
                block.remove(item)


def join(objs, name):
    bpy.ops.object.select_all(action='DESELECT')
    meshes = [o for o in objs if o.type == 'MESH']
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    obj.name = name
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for o in list(bpy.data.objects):
        if o.type != 'MESH' and o.name != obj.name:
            bpy.data.objects.remove(o, do_unlink=True)
    return obj


def prop(kind):
    parts = []
    add = lambda op, **kw: (op(**kw), parts.append(bpy.context.object))
    if kind == 'chair':
        add(bpy.ops.mesh.primitive_cube_add, size=1, location=(0, 0, 0.45)); parts[-1].scale = (0.45, 0.45, 0.05)
        for x in (-0.2, 0.2):
            for y in (-0.2, 0.2):
                add(bpy.ops.mesh.primitive_cylinder_add, radius=0.025, depth=0.45, location=(x, y, 0.225))
        add(bpy.ops.mesh.primitive_cube_add, size=1, location=(0, 0.21, 0.7)); parts[-1].scale = (0.45, 0.04, 0.45)
    elif kind == 'table':
        add(bpy.ops.mesh.primitive_cube_add, size=1, location=(0, 0, 0.73)); parts[-1].scale = (1.2, 0.7, 0.04)
        for x in (-0.55, 0.55):
            for y in (-0.3, 0.3):
                add(bpy.ops.mesh.primitive_cube_add, size=1, location=(x, y, 0.36)); parts[-1].scale = (0.05, 0.05, 0.72)
    elif kind == 'mug':
        add(bpy.ops.mesh.primitive_cylinder_add, radius=0.045, depth=0.1, location=(0, 0, 0.05), vertices=32)
        add(bpy.ops.mesh.primitive_torus_add, major_radius=0.03, minor_radius=0.008, location=(0.05, 0, 0.055), rotation=(math.pi / 2, 0, 0))
    elif kind == 'lamp':
        add(bpy.ops.mesh.primitive_cylinder_add, radius=0.15, depth=0.03, location=(0, 0, 0.015))
        add(bpy.ops.mesh.primitive_cylinder_add, radius=0.015, depth=1.4, location=(0, 0, 0.72))
        add(bpy.ops.mesh.primitive_cone_add, radius1=0.22, radius2=0.1, depth=0.25, location=(0, 0, 1.45))
    elif kind == 'crate':
        add(bpy.ops.mesh.primitive_cube_add, size=0.6, location=(0, 0, 0.3))
        bpy.ops.object.modifier_add(type='BEVEL'); parts[-1].modifiers[-1].width = 0.03
        bpy.ops.object.modifier_apply(modifier=parts[-1].modifiers[-1].name)
    return join(parts, 'Subject')


def subject(name):
    clear()
    if name in ('chair', 'table', 'mug', 'lamp', 'crate'):
        obj = prop(name)
    else:
        bpy.ops.import_scene.gltf(filepath=str(KRONOS / name / (name + '.glb')))
        obj = join(list(bpy.context.scene.objects), 'Subject')
    # Normalise: declared height, centred on x/y, standing on z=0.
    xs = [ (obj.matrix_world @ v.co) for v in obj.data.vertices]
    lo = Vector((min(p.x for p in xs), min(p.y for p in xs), min(p.z for p in xs)))
    hi = Vector((max(p.x for p in xs), max(p.y for p in xs), max(p.z for p in xs)))
    size = max(hi.z - lo.z, 1e-6)
    s = HEIGHTS[name] / size
    for v in obj.data.vertices:
        v.co = Vector(((v.co.x - (lo.x + hi.x) / 2) * s, (v.co.y - (lo.y + hi.y) / 2) * s, (v.co.z - lo.z) * s))
    obj.data.update()
    return obj


def flip(obj):
    bm = bmesh.new(); bm.from_mesh(obj.data); bm.faces.ensure_lookup_table()
    axis = Vector((rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(-0.3, 0.3))).normalized()
    centres = sorted(bm.faces, key=lambda f: f.calc_center_median().dot(axis))
    chosen = centres[:max(1, len(centres) // 3)]
    bmesh.ops.reverse_faces(bm, faces=chosen)
    bm.to_mesh(obj.data); bm.free(); obj.data.update()
    return {'flippedFaces': len(chosen), 'faces': len(centres)}


def floaters(obj):
    h = max(v.co.z for v in obj.data.vertices)
    w = max(max(abs(v.co.x) for v in obj.data.vertices), max(abs(v.co.y) for v in obj.data.vertices), h * 0.2)
    count = rnd.randint(1, 3)
    parts = [obj]
    spots = []
    for _ in range(count):
        size = h * rnd.uniform(0.05, 0.1)
        ang = rnd.uniform(0, 2 * math.pi)
        dist = w * rnd.uniform(1.25, 1.7)
        loc = (math.cos(ang) * dist, math.sin(ang) * dist * 0.3, h * rnd.uniform(0.35, 1.05))
        if rnd.random() < 0.5:
            bpy.ops.mesh.primitive_cube_add(size=size, location=loc)
        else:
            bpy.ops.mesh.primitive_ico_sphere_add(radius=size / 2, subdivisions=1, location=loc)
        parts.append(bpy.context.object)
        spots.append([round(c, 3) for c in loc])
    join(parts, 'Subject')
    return {'floaters': count, 'locations': spots}


def setup(view, expected):
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x, scene.render.resolution_y = 640, 480
    scene.render.image_settings.file_format = 'PNG'
    shading = scene.display.shading
    shading.light = 'STUDIO'
    shading.color_type = 'OBJECT'
    shading.show_backface_culling = True
    shading.background_type = 'VIEWPORT' if hasattr(shading, 'background_type') else shading.background_type
    try:
        shading.background_color = BACKGROUND
    except Exception:
        pass
    scene.world = scene.world or bpy.data.worlds.new('World')
    scene.world.color = BACKGROUND
    bpy.ops.mesh.primitive_plane_add(size=14, location=(0, 0, 0)); floor = bpy.context.object; floor.name = 'Floor'
    floor.color = (0.42, 0.42, 0.42, 1)
    # Reference mannequin: 1.8 m capsule body + head, to the left of the subject.
    bpy.ops.mesh.primitive_cylinder_add(radius=0.16, depth=1.5, location=(-1.1, 0.4, 0.75)); body = bpy.context.object
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.13, location=(-1.1, 0.4, 1.67)); head = bpy.context.object
    for o in (body, head):
        o.color = REFERENCE_COLOR; o.name = 'Reference'
    cam_data = bpy.data.cameras.new('Cam'); cam_data.lens = 40
    cam = bpy.data.objects.new('Cam', cam_data); bpy.context.scene.collection.objects.link(cam)
    if view == 'front':  # the stage: subject beside the 1.8 m reference
        angle, dist, target, lift = -0.45, 5.2, Vector((-0.45, 0.2, 0.85)), 1.3
    else:  # close: framed on the subject's DECLARED height (a wrong scale over- or under-fills it)
        h = expected
        angle = {'close': 0.6, 'close-high': 2.3, 'close-back': 3.7, 'close-left': -1.2}.get(view, 0.6)
        dist = h * 2.6 + 0.3
        angle, target, lift = angle, Vector((0, 0, h * 0.5)), dist * (0.7 if view == 'close-high' else 0.35)
    cam.location = target + Vector((math.sin(angle) * dist, -math.cos(angle) * dist, lift))
    direction = target - cam.location
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    scene.camera = cam


def render(obj, name, view, condition, detail, rows):
    bpy.context.view_layer.update()
    obj = bpy.data.objects['Subject']
    obj.color = OBJECT_COLOR
    setup(view, HEIGHTS[name])
    path = OUT / f'{name}-{condition}-{view}-s{SEED}.png'
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    labels = {'flipped-normals': int(condition == 'flipped-normals'), 'floaters': int(condition == 'floaters'),
              'wrong-scale': int(condition.startswith('wrong-scale'))}
    rows.append({'image': str(path), 'subject': name, 'view': view, 'condition': condition, 'labels': labels, 'detail': detail,
                 'expectedHeightM': HEIGHTS[name], 'referenceHeightM': 1.8,
                 'labelSource': 'fault constructed by LAYA in Blender; not judged'})
    # Remove the stage so the next condition starts from the subject alone.
    for o in list(bpy.data.objects):
        if o.name != 'Subject':
            bpy.data.objects.remove(o, do_unlink=True)


def main():
    rows = []
    names = [p.name for p in sorted(KRONOS.iterdir()) if (p / (p.name + '.glb')).exists()] + ['chair', 'table', 'mug', 'lamp', 'crate']
    for name in names:
        for view in VIEWS:
            for condition in ('clean', 'flipped-normals', 'floaters', 'wrong-scale'):
                obj = subject(name)
                detail = {}
                if condition == 'flipped-normals':
                    detail = flip(obj)
                elif condition == 'floaters':
                    detail = floaters(obj)
                elif condition == 'wrong-scale':
                    factor = rnd.choice([6.0, 0.12])
                    for v in obj.data.vertices:
                        v.co *= factor
                    obj.data.update()
                    detail = {'factor': factor}
                render(obj, name, view, condition, detail, rows)
                print('rendered', name, view, condition, flush=True)
    (OUT / 'renders.json').write_text(json.dumps({'schema': 'neyvia.laya.render-practice.v1', 'renders': rows,
                                                  'colors': {'object': OBJECT_COLOR[:3], 'reference': REFERENCE_COLOR[:3],
                                                             'background': BACKGROUND}}, indent=1))


main()
