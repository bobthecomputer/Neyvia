"""Kronos 3D turntable clips for the launch film (headless Blender, nothing on screen).

Usage: python video_kronos_turntable.py [--assets emblem,backpack] [--mode still|clip] [--fps 60]
       [--frames 210] [--size 1920x1080] [--sweep 35|360] [--transparent] [--samples 48]
All output lives under D:/NeyviaRuns/video/track-video/v3work/kronos/. Writes receipt.json (clip mode).
"""
import argparse, hashlib, json, os, subprocess, time

OUT = "D:/NeyviaRuns/video/track-video/v3work/kronos"
GLB = "D:/NeyviaRuns/laya-3d/kronos/out/{n}/{n}.glb"
BLENDER = "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe"
FFMPEG = "C:/Users/user/Documents/Codex/2026-08-10/openai-has-opened-multiple-positions-to/work/ffmpeg-portable/ffmpeg-8.1.1-essentials_build/bin/ffmpeg.exe"
CF = subprocess.CREATE_NO_WINDOW

BLENDER_SCRIPT = r'''
import bpy, sys, json, math, mathutils
a = json.loads(sys.argv[sys.argv.index("--") + 1])
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
bpy.ops.import_scene.gltf(filepath=a["glb"])
meshes = [o for o in sc.objects if o.type == "MESH"]
pts = []
for o in meshes:
    pts += [o.matrix_world @ mathutils.Vector(c) for c in o.bound_box]
mn = mathutils.Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
mx = mathutils.Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
ctr = (mn + mx) / 2
H = mx.z - mn.z
rad = max(mx.x - mn.x, mx.y - mn.y) / 2
pivot = bpy.data.objects.new("pivot", None); sc.collection.objects.link(pivot)
for o in list(sc.objects):
    if o.parent is None and o is not pivot:
        o.parent = pivot
pivot.location = (-ctr.x, -ctr.y, -ctr.z)
# rotate about the object's own centre: use a second parent at origin
rot = bpy.data.objects.new("rot", None); sc.collection.objects.link(rot)
pivot.parent = rot
zmin = mn.z - ctr.z
W, Hpx = a["w"], a["h"]; asp = W / Hpx
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam)
sc.camera = cam
cam.data.sensor_fit = "VERTICAL"; cam.data.sensor_height = 24; cam.data.lens = 70
vis = max(H / a["fill"], (2 * rad * 1.05) / (0.8 * asp))
d = vis * cam.data.lens / 24 + rad
el = math.radians(a["elev"]); cam.location = (0, -d * math.cos(el), d * math.sin(el)); cam.rotation_euler = (math.radians(90) - el, 0, 0)
w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True
bg = w.node_tree.nodes["Background"]
bg.inputs[0].default_value = a["bgrgba"]; bg.inputs[1].default_value = 1.0
bpy.ops.mesh.primitive_plane_add(size=1, location=(0, 0, zmin - 0.002 * H))
fl = bpy.context.object
fl.scale = (rad * 3.2, rad * 3.2, 1)
m = bpy.data.materials.new("shadowblob"); m.use_nodes = True
nt = m.node_tree; nt.nodes.clear()
tc = nt.nodes.new("ShaderNodeTexCoord"); gr = nt.nodes.new("ShaderNodeTexGradient"); gr.gradient_type = "SPHERICAL"
mp = nt.nodes.new("ShaderNodeMapping"); mp.inputs["Location"].default_value = (-1, -1, 0); mp.inputs["Scale"].default_value = (2, 2, 2)
cr = nt.nodes.new("ShaderNodeValToRGB")
cr.color_ramp.elements[0].position = 0.0; cr.color_ramp.elements[0].color = (0, 0, 0, 1); cr.color_ramp.interpolation = "EASE"
cr.color_ramp.elements[1].position = 1.0; cr.color_ramp.elements[1].color = (1, 1, 1, 1)
mt = nt.nodes.new("ShaderNodeMath"); mt.operation = "MULTIPLY"; mt.inputs[1].default_value = a["blob"]
tr = nt.nodes.new("ShaderNodeBsdfTransparent"); bk = nt.nodes.new("ShaderNodeEmission"); bk.inputs[0].default_value = (0, 0, 0, 1)
mx2 = nt.nodes.new("ShaderNodeMixShader"); out = nt.nodes.new("ShaderNodeOutputMaterial")
inv = nt.nodes.new("ShaderNodeMath"); inv.operation = "SUBTRACT"; inv.inputs[0].default_value = 1.0
nt.links.new(tc.outputs["Generated"], mp.inputs[0]); nt.links.new(mp.outputs[0], gr.inputs[0])
nt.links.new(gr.outputs[0], cr.inputs[0]); nt.links.new(cr.outputs[0], mt.inputs[0]); nt.links.new(mt.outputs[0], mx2.inputs[0])
nt.links.new(tr.outputs[0], mx2.inputs[1]); nt.links.new(bk.outputs[0], mx2.inputs[2]); nt.links.new(mx2.outputs[0], out.inputs[0])
m.surface_render_method = "BLENDED"
fl.data.materials.append(m)
fl.visible_shadow = False
def light(name, loc, energy, color, size):
    L = bpy.data.lights.new(name, "AREA"); L.energy = energy; L.color = color; L.size = size
    o = bpy.data.objects.new(name, L); sc.collection.objects.link(o); o.location = loc
    o.rotation_euler = (-mathutils.Vector(loc)).to_track_quat("-Z", "Y").to_euler()
s = max(H, rad * 2)
G = (0x46 / 255, 0xb0 / 255, 0x77 / 255)
light("key", (-1.6 * s, -2.2 * s, 1.8 * s), a["key"] * s * s, (1, 0.96, 0.9), 2.2 * s)
light("fill", (2.2 * s, -1.8 * s, 0.4 * s), a["fillE"] * s * s, (0.85, 0.92, 1), 3 * s)
light("rim", (1.4 * s, 2.0 * s, 1.0 * s), a["rim"] * s * s, G, 1.6 * s)
light("rim2", (-2.0 * s, 1.6 * s, 0.6 * s), a["rim"] * 0.6 * s * s, G, 1.6 * s)
sc.render.engine = a["engine"]
if a["engine"] == "CYCLES":
    sc.cycles.samples = a["samples"]; sc.cycles.use_denoising = True; sc.cycles.device = "CPU"
else:
    sc.eevee.taa_render_samples = a["samples"]
sc.render.resolution_x = W; sc.render.resolution_y = Hpx; sc.render.resolution_percentage = 100
sc.render.fps = a["fps"]
sc.render.film_transparent = a["transparent"]
sc.view_settings.view_transform = "AgX"; sc.view_settings.look = "None"
sc.render.image_settings.file_format = "PNG"
sc.render.image_settings.color_mode = "RGBA" if a["transparent"] else "RGB"
sc.render.image_settings.compression = 15
n = a["frames"]
def ang(i):
    t = i / max(1, n - 1)
    if a["sweep"] >= 360: return math.radians(360 * i / n)
    return math.radians(-a["sweep"] * math.cos(math.pi * t) + a.get("yaw", 0))
if a["mode"] == "still":
    for deg in a["still_angles"]:
        rot.rotation_euler.z = math.radians(deg)
        sc.render.filepath = a["out"] + "/still_%d.png" % deg
        bpy.ops.render.render(write_still=True)
else:
    for i in range(n):
        rot.rotation_euler.z = ang(i)
        sc.render.filepath = a["out"] + "/f_%04d.png" % i
        bpy.ops.render.render(write_still=True)
print("DONE", n)
'''


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def run_blender(args):
    os.makedirs(OUT + "/tmp", exist_ok=True)
    sp = OUT + "/blender_turntable.py"
    open(sp, "w").write(BLENDER_SCRIPT)
    env = dict(os.environ, TEMP=OUT + "/tmp", TMP=OUT + "/tmp")
    t = time.time()
    r = subprocess.run([BLENDER, "--background", "--factory-startup", "--python", sp, "--", json.dumps(args)],
                       env=env, capture_output=True, text=True, creationflags=CF)
    if r.returncode or "DONE" not in r.stdout:
        print(r.stdout[-2500:], r.stderr[-1500:])
        raise SystemExit("blender failed")
    return time.time() - t


def lin(c):
    c /= 255
    return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", default="emblem,main-weapon,backpack,boot,body-turnaround,gun-mode,body-tpose")
    ap.add_argument("--mode", default="still")
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--frames", type=int, default=210)
    ap.add_argument("--size", default="1920x1080")
    ap.add_argument("--sweep", type=int, default=35)
    ap.add_argument("--yaw", type=float, default=0, help="centre yaw offset deg")
    ap.add_argument("--transparent", action="store_true")
    ap.add_argument("--engine", default="BLENDER_EEVEE")
    ap.add_argument("--samples", type=int, default=48)
    ap.add_argument("--bgk", type=float, default=1.0, help="world colour gain to hit #0d1612 after AgX")
    ap.add_argument("--fill", type=float, default=0.6)
    ap.add_argument("--key", type=float, default=60)
    ap.add_argument("--fillE", type=float, default=12)
    ap.add_argument("--angles", default="0,45,90,135,180,225,270,315")
    ap.add_argument("--blob", type=float, default=0.8)
    ap.add_argument("--elev", type=float, default=8)
    ap.add_argument("--rim", type=float, default=90)
    o = ap.parse_args()
    w, h = map(int, o.size.split("x"))
    bgl = [lin(0x0d), lin(0x16), lin(0x12)]
    receipts = []
    for n in o.assets.split(","):
        tag = "stills" if o.mode == "still" else ("alpha" if o.transparent else "rgb")
        d = f"{OUT}/{n}_{tag}"
        os.makedirs(d, exist_ok=True)
        a = dict(w=w, h=h, fps=o.fps, frames=o.frames, sweep=o.sweep, yaw=o.yaw, samples=o.samples, fill=o.fill,
                 bgrgba=[c * o.bgk for c in bgl] + [1], floorrgba=[c * 1.5 for c in bgl] + [1],
                 key=o.key, fillE=o.fillE, rim=o.rim, engine=o.engine, glb=GLB.format(n=n), out=d, mode=o.mode,
                 transparent=o.transparent, still_angles=[int(x) for x in o.angles.split(",")], blob=o.blob, elev=o.elev)
        sec = run_blender(a)
        print(n, o.mode, round(sec, 1), "s", flush=True)
        if o.mode == "clip":
            mp4 = f"{OUT}/{n}_kronos{'_alpha' if o.transparent else ''}.{'mov' if o.transparent else 'mp4'}"
            if o.transparent:
                cmd = [FFMPEG, "-y", "-framerate", str(o.fps), "-i", d + "/f_%04d.png", "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", mp4]
            else:
                cmd = [FFMPEG, "-y", "-framerate", str(o.fps), "-i", d + "/f_%04d.png", "-c:v", "libx264", "-preset", "slow", "-crf", "14",
                       "-pix_fmt", "yuv420p", "-vf", "scale=out_color_matrix=bt709:out_range=tv", "-color_primaries", "bt709",
                       "-color_trc", "bt709", "-colorspace", "bt709", mp4]
            subprocess.run(cmd, creationflags=CF, capture_output=True, check=True)
            receipts.append(dict(asset=n, glb=a["glb"], glb_sha256=sha(a["glb"]), blender="5.2", engine=o.engine,
                                 samples=o.samples, resolution=o.size, fps=o.fps, frames=o.frames, sweep_deg=o.sweep,
                                 transparent=o.transparent, render_seconds=round(sec, 1), output=mp4, output_sha256=sha(mp4)))
    if receipts:
        rp = OUT + "/receipt.json"
        old = json.load(open(rp)) if os.path.exists(rp) else []
        json.dump(old + receipts, open(rp, "w"), indent=2)


if __name__ == "__main__":
    main()
