"""Private Blender bridge host and native labelled contract fixtures."""
import json
from pathlib import Path
import sys
import time
import bpy
import bmesh

project=Path(sys.argv[sys.argv.index('--')+1]).resolve()
sys.path.insert(0,str(project/'.neyvia/blender'))
import neyvia_bridge as bridge


def fixtures():
    rows=[]
    for shape in ('cube','sphere','cylinder'):
        for defect in ('clean','holes','flipped-normals','duplicate-vertices','missing-uv','flat-shading','unapplied-scale','floaters'):
            bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
            if shape=='cube': bpy.ops.mesh.primitive_cube_add()
            elif shape=='sphere': bpy.ops.mesh.primitive_uv_sphere_add(segments=16,ring_count=8)
            else: bpy.ops.mesh.primitive_cylinder_add(vertices=16)
            obj=bpy.context.object; obj.name='Subject'
            for face in obj.data.polygons: face.use_smooth=True
            labels=[]
            if defect in {'holes','flipped-normals','duplicate-vertices'}:
                bm=bmesh.new(); bm.from_mesh(obj.data); bm.faces.ensure_lookup_table(); bm.verts.ensure_lookup_table()
                if defect=='holes': bmesh.ops.delete(bm,geom=[bm.faces[0]],context='FACES_ONLY'); labels=['holes','non-manifold']
                elif defect=='flipped-normals': bmesh.ops.reverse_faces(bm,faces=[bm.faces[0]]); labels=[defect]
                else: bm.verts.new(bm.verts[0].co); labels=[defect]
                bm.to_mesh(obj.data); bm.free()
            elif defect=='missing-uv':
                for uv in list(obj.data.uv_layers): obj.data.uv_layers.remove(uv)
                labels=[defect]
            elif defect=='flat-shading':
                for face in obj.data.polygons: face.use_smooth=False
                labels=[defect]
            elif defect=='unapplied-scale': obj.scale=(1.4,1,1); labels=[defect]
            elif defect=='floaters':
                bpy.ops.mesh.primitive_cube_add(size=.06,location=(1.6,0,0)); part=bpy.context.object
                for face in part.data.polygons: face.use_smooth=True
                obj.select_set(True); bpy.context.view_layer.objects.active=obj; bpy.ops.object.join(); labels=[defect]
            folder=project/'fixtures'; folder.mkdir(exist_ok=True)
            path=folder/(shape+'-'+defect+'.blend')
            bpy.ops.wm.save_as_mainfile(filepath=str(path),copy=True)
            rows.append({'id':shape+'-'+defect,'path':str(path),'labels':labels,'shape':shape,
                         'labelSource':'native construction with one declared corruption; not judge-generated labels'})
    (project/'labels.json').write_text(json.dumps(rows,indent=2))


if '--fixtures' in sys.argv: fixtures()
else:
    bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
bridge.register()
bpy.context.scene.neyvia_project_path=str(project)
bpy.ops.neyvia.connect()
# Blender background does not pump application timers while this script runs.
while True:
    bridge._tick()
    time.sleep(.03)
