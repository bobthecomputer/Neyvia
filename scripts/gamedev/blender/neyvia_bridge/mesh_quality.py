"""Blender observations and named operations for the shared Plan 23 Scene core.

No judge or improvement loop lives here. All measurements are native mesh facts;
intent (closed surface, symmetry, density) must be supplied by the caller.
"""
import hashlib
import json
import math
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree


def _components(bm):
    remaining = set(bm.verts)
    groups = []
    while remaining:
        group, todo = set(), [remaining.pop()]
        while todo:
            vertex = todo.pop()
            group.add(vertex)
            for edge in vertex.link_edges:
                other = edge.other_vert(vertex)
                if other in remaining:
                    remaining.remove(other)
                    todo.append(other)
        groups.append(group)
    return sorted(groups, key=len, reverse=True)


def _uv(mesh, matrix):
    mesh.calc_loop_triangles()
    uv = mesh.uv_layers.active
    total, mapped, area_uv, ratios = 0., 0., 0., []
    outside = 0
    if uv:
        outside = sum(not (0 <= row.uv.x <= 1 and 0 <= row.uv.y <= 1) for row in uv.data)
    for tri in mesh.loop_triangles:
        a, b, c = [matrix @ mesh.vertices[i].co for i in tri.vertices]
        area = (b-a).cross(c-a).length / 2
        total += area
        if not uv or area < 1e-12:
            continue
        x, y, z = [uv.data[i].uv for i in tri.loops]
        ua = abs((y-x).cross(z-x)) / 2
        area_uv += ua
        if ua > 1e-12:
            mapped += area
            # Scale-independent triangle edge anisotropy, not a conformal proof.
            r = [(v-u).length / max((q-p).length, 1e-12)
                 for u, v, p, q in ((x,y,a,b),(y,z,b,c),(z,x,c,a))]
            ratios.append(max(r) / max(min(r), 1e-12))
    return {'uvCoverage': mapped / total if total else 0., 'uvAreaSum': area_uv,
            'uvOutsideLoops': outside, 'uvStretchMax': max(ratios, default=None),
            'worldSurfaceArea': total, 'uvOverlap': None}


def _mesh_node(obj, targets):
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    bm.normal_update()
    groups = _components(bm)
    world = [obj.matrix_world @ v.co for v in bm.verts]
    lo = [min((p[i] for p in world), default=0) for i in range(3)]
    hi = [max((p[i] for p in world), default=0) for i in range(3)]
    diagonal = (Vector(hi)-Vector(lo)).length
    tolerance = max(diagonal * 1e-6, 1e-8)
    duplicates = bmesh.ops.find_doubles(bm, verts=list(bm.verts), dist=tolerance)['targetmap']
    closed = bool(bm.faces) and all(e.is_manifold for e in bm.edges)
    # Recalculation comparison detects inconsistent orientation; outward sign is
    # defined only for a closed manifold. Open surfaces intentionally abstain.
    originals = {f.index: f.normal.copy() for f in bm.faces}
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.normal_update()
    flipped = sum(originals[f.index].dot(f.normal) < 0 for f in bm.faces) if closed else None
    kd = KDTree(len(world))
    for i, point in enumerate(world):
        kd.insert(point, i)
    kd.balance()
    center_x = (lo[0]+hi[0])/2
    symmetry = max((kd.find(Vector((2*center_x-p.x,p.y,p.z)))[2] for p in world), default=0)
    boundary = sum(e.is_boundary for e in bm.edges)
    facts = {'vertices':len(bm.verts), 'faces':len(bm.faces),
             'boundaryEdges':boundary, 'nonManifoldEdges':sum(not e.is_manifold for e in bm.edges),
             'wireEdges':sum(e.is_wire for e in bm.edges), 'duplicateVertices':len(duplicates),
             'closedManifold':closed, 'flippedNormals':flipped,
             'components':len(groups), 'looseVertices':sum(not v.link_faces for v in bm.verts),
             'smallComponentVertices':sum(len(g) for g in groups[1:] if len(g) <= targets.get('floaterMaxVertices', 0) and any(v.link_faces for v in g)),
             'symmetryErrorRelative':symmetry / max(diagonal,1e-12),
             'nonQuadFaces':sum(len(f.verts)!=4 for f in bm.faces),
             'extraordinaryVertices':sum(len(v.link_edges)!=4 for v in bm.verts),
             'flatFaces':sum(not p.use_smooth for p in mesh.polygons),
             'scaleError':max(abs(abs(s)-1) for s in obj.scale),
             'originOffsetRelative':(obj.matrix_world.translation-(Vector(lo)+Vector(hi))/2).length/max(diagonal,1e-12),
             'boundsMin':lo, 'boundsMax':hi, 'dimensions':[hi[i]-lo[i] for i in range(3)],
             'longestEdgeRelative':max((e.calc_length() for e in bm.edges), default=0)/max(diagonal,1e-12),
             'topologyFlow':None, 'silhouetteMatch':None, **_uv(mesh,obj.matrix_world)}
    bm.free()
    textures = []
    for material in mesh.materials:
        if material and material.use_nodes:
            for node in material.node_tree.nodes:
                if node.type=='TEX_IMAGE' and node.image:
                    textures.append({'name':node.image.name,'resolution':list(node.image.size),'source':node.image.source})
    facts['textureMinResolution'] = min((min(t['resolution']) for t in textures), default=None)
    facts['texelDensity'] = (math.sqrt(facts['uvAreaSum']/facts['worldSurfaceArea'])*facts['textureMinResolution']
                             if facts['worldSurfaceArea'] and facts['textureMinResolution'] else None)
    facts['textureResolutionDeficit'] = max(0,targets.get('textureResolution',0)-facts['textureMinResolution']) if facts['textureMinResolution'] is not None else None
    facts['texelDensityDeficit'] = max(0,targets.get('texelDensity',0)-facts['texelDensity']) if facts['texelDensity'] is not None else None
    facts['vertexBudgetExcess'] = max(0,facts['vertices']-targets['maxVertices']) if targets.get('maxVertices') else 0
    facts['uvStretchExcess'] = max(0,facts['uvStretchMax']-targets.get('maxUVStretch',5)) if facts['uvStretchMax'] is not None else None
    facts['missingMaterials'] = sum(m is None for m in mesh.materials) if mesh.materials else 1
    return {'id':obj.name,'kind':'mesh','role':'mesh','text':obj.name,'certainty':'observed',
            'attributes':{'scale':list(obj.scale),'materials':[m.name if m else None for m in mesh.materials],
                          'textures':textures,'modifiers':[m.type for m in obj.modifiers]},
            'relations':{'parent':obj.parent.name if obj.parent else None}, 'facts':facts}


def transcribe(args):
    targets = args.get('targets', {})
    objects = list(bpy.context.scene.objects)
    nodes, trees = [], {}
    for obj in objects:
        if obj.type=='MESH':
            node = _mesh_node(obj, targets)
            node['facts']['targets'] = targets
            bm = bmesh.new(); bm.from_mesh(obj.data); bm.transform(obj.matrix_world)
            trees[obj.name] = BVHTree.FromBMesh(bm); bm.free()
        else:
            node = {'id':obj.name,'kind':obj.type.lower(),'role':obj.type.lower(),'certainty':'observed',
                    'attributes':{'scale':list(obj.scale)},'relations':{'parent':obj.parent.name if obj.parent else None},'facts':{}}
        nodes.append(node)
    pairs = []
    names = list(trees)
    for i, name in enumerate(names):
        for other in names[i+1:]:
            overlap = trees[name].overlap(trees[other])
            if overlap:
                pairs.append({'a':name,'b':other,'trianglePairs':len(overlap)})
    for node in nodes:
        if node['kind']=='mesh':
            node['facts']['intersectingObjects'] = [p['b'] if p['a']==node['id'] else p['a'] for p in pairs if node['id'] in (p['a'],p['b'])]
    return {'schema':'neyvia.scene.v1','domain':'blender','layer':'blender','surface':'native-scene',
            'nodes':nodes,'truncated':False,'measurements':{'unitScale':bpy.context.scene.unit_settings.scale_length,
            'intersectionPairs':pairs},'unknown':['Topology flow and semantic floaters need labelled intent.',
            'UV coverage is mapped surface fraction; overlap and UDIM semantics are not inferred.',
            'Intersection reports crossing surfaces, not fully contained solids.',
            'Base mesh measurements; modifiers are listed, not silently applied.']}


def fix(args):
    obj = bpy.data.objects.get(args['object'])
    if obj is None or obj.type!='MESH' or obj.mode!='OBJECT':
        raise ValueError('An existing Object-mode mesh is required')
    if obj.modifiers:
        raise ValueError('Apply or resolve modifiers explicitly before mesh repair')
    operation = args['operation']
    allowed = {'normals','merge','fill_holes','remove_floaters','smooth','unwrap','pack_uv','scale','origin','subdivide','voxel_remesh','decimate','upscale_texture'}
    if operation not in allowed:
        raise ValueError('Unknown named mesh operation')
    for other in bpy.context.view_layer.objects:
        other.select_set(False)
    obj.select_set(True); bpy.context.view_layer.objects.active=obj
    # Detach shared mesh data so a repair cannot modify other instances.
    if obj.data.users>1:
        obj.data=obj.data.copy()
    if operation in {'normals','merge','fill_holes','remove_floaters'}:
        bm=bmesh.new(); bm.from_mesh(obj.data)
        try:
            if operation=='normals':
                bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
            elif operation=='merge':
                distance=float(args.get('distance',1e-6))
                if not 0<distance<=.01: raise ValueError('Merge distance must be in (0,.01] local units')
                bmesh.ops.remove_doubles(bm,verts=list(bm.verts),dist=distance)
            elif operation=='fill_holes':
                if args.get('closedSurface') is not True: raise ValueError('Hole filling requires explicit closedSurface intent')
                bmesh.ops.holes_fill(bm,edges=[e for e in bm.edges if e.is_boundary],sides=int(args.get('maxSides',32)))
                bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
            else:
                limit=int(args.get('maxVertices',0))
                if limit<=0: raise ValueError('Explicit floater component vertex limit required')
                groups=_components(bm)
                verts=[v for group in groups[1:] if len(group)<=limit for v in group]
                bmesh.ops.delete(bm,geom=verts,context='VERTS')
            bm.to_mesh(obj.data); obj.data.update()
        finally: bm.free()
    elif operation=='smooth':
        angle=float(args.get('angle',math.radians(30)))
        for polygon in obj.data.polygons: polygon.use_smooth=True
        bm=bmesh.new(); bm.from_mesh(obj.data)
        for edge in bm.edges: edge.smooth=bool(edge.is_manifold and edge.calc_face_angle()<=angle)
        bm.to_mesh(obj.data); bm.free()
    elif operation in {'unwrap','pack_uv'}:
        bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
        try:
            if operation=='unwrap': bpy.ops.uv.smart_project(island_margin=.02)
            else: bpy.ops.uv.pack_islands(margin=.02)
        finally: bpy.ops.object.mode_set(mode='OBJECT')
    elif operation=='scale': bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    elif operation=='origin': bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY',center='BOUNDS')
    elif operation in {'subdivide','voxel_remesh','decimate'}:
        kind={'subdivide':'SUBSURF','voxel_remesh':'REMESH','decimate':'DECIMATE'}[operation]
        modifier=obj.modifiers.new('LAYA named fix',kind)
        if operation=='subdivide': modifier.levels=min(2,max(1,int(args.get('levels',1))))
        elif operation=='voxel_remesh':
            modifier.mode='VOXEL'; modifier.voxel_size=max(.0001,float(args.get('voxelSize',.05)))
        else: modifier.ratio=min(1.,max(.01,float(args.get('ratio',.5))))
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    else:
        # Resampling is explicitly not neural detail recovery. Copy both material
        # and image so the snapshot/original textures remain intact.
        size=int(args.get('resolution',0))
        if not 1<=size<=4096: raise ValueError('Texture target must be 1..4096')
        for i,material in enumerate(obj.data.materials):
            if not material or not material.use_nodes: continue
            material=material.copy(); obj.data.materials[i]=material
            for node in material.node_tree.nodes:
                if node.type=='TEX_IMAGE' and node.image:
                    node.image=node.image.copy()
                    width,height=node.image.size
                    factor=max(1,size/max(1,min(width,height)))
                    node.image.scale(min(4096,round(width*factor)),min(4096,round(height*factor)))
                    node.image.pack()
    bpy.context.view_layer.update()
    # Observation stays a separate transcribe call with the caller's declared targets.
    return {'object':obj.name,'operation':operation,'vertices':len(obj.data.vertices),'faces':len(obj.data.polygons)}


def canonical(args, project_path):
    """Fixed orthographic alpha renders. Reuse framing across candidate revisions."""
    objects=bpy.data.collections[args['collection']].objects if args.get('collection') else bpy.context.scene.objects
    meshes=[o for o in objects if o.type=='MESH' and not o.hide_render]
    if not meshes: raise ValueError('Cannot render an empty mesh scene')
    points=[o.matrix_world@Vector(c) for o in meshes for c in o.bound_box]
    framing=args.get('framing')
    if framing is None:
        low=Vector([min(p[i] for p in points) for i in range(3)])
        high=Vector([max(p[i] for p in points) for i in range(3)])
        framing={'center':list((low+high)/2),'size':max((high-low).length*1.2,.01)}
    center=Vector(framing['center']); size=float(framing['size'])
    if not math.isfinite(size) or size<=0: raise ValueError('Invalid canonical frame')
    directory=project_path(args['path']); directory.mkdir(parents=True,exist_ok=True)
    scene=bpy.data.scenes.new('LAYA canonical observation')
    camera_data=bpy.data.cameras.new('LAYA canonical camera')
    camera=bpy.data.objects.new('LAYA canonical camera',camera_data); scene.collection.objects.link(camera)
    scene.camera=camera; camera_data.type='ORTHO'; camera_data.ortho_scale=size
    scene.render.engine='BLENDER_WORKBENCH'; scene.render.film_transparent=True
    scene.display.shading.light='STUDIO'; scene.display.shading.color_type='SINGLE'
    scene.display.shading.single_color=(.55,.65,.8)
    scene.render.resolution_x=scene.render.resolution_y=128; scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG'; scene.render.image_settings.color_mode='RGBA'
    scene.display.render_aa='OFF'
    scene.view_settings.view_transform='Standard'; scene.view_settings.look='None'
    if args.get('sourceColour'):
        # Unlit texture/material colour: the comparison measures colour, not lighting.
        scene.display.shading.light='FLAT'; scene.display.shading.color_type='TEXTURE'
    resolution=int(args.get('resolution',128))
    if resolution not in (128,256,512,1024): raise ValueError('Canonical resolution must be 128, 256, 512 or 1024')
    scene.render.resolution_x=scene.render.resolution_y=resolution
    for obj in meshes: scene.collection.objects.link(obj)
    results=[]
    try:
        from .view_geometry import frame
        for name in args.get('views',['front','side','top']):
            path=directory/(name+'.png')
            if path.exists() and not args.get('replace'): raise ValueError('Canonical render directory must be new')
            spec=args.get('cameras',{}).get(name)
            if spec and 'scale' in spec:
                from mathutils import Matrix
                from .hull_math import blender_camera
                rows,ortho=blender_camera(spec)
                camera.matrix_world=Matrix(rows); camera_data.type='ORTHO'; camera_data.ortho_scale=ortho
                camera_data.clip_start=.01; camera_data.clip_end=100; camera_data.sensor_fit='HORIZONTAL'
            else:
                matrix,view_size,projection,lens=frame(name,framing,spec)
                camera.matrix_world=matrix; camera_data.ortho_scale=view_size
                camera_data.type='PERSP' if projection=='perspective' else 'ORTHO'
                camera_data.lens=lens; camera_data.sensor_width=36; camera_data.sensor_fit='HORIZONTAL'
            scene.render.filepath=str(path)
            bpy.ops.render.render(write_still=True,scene=scene.name)
            image=bpy.data.images.load(str(path),check_existing=False)
            try:
                import numpy as np
                pixels=np.empty(len(image.pixels),np.float32); image.pixels.foreach_get(pixels)
                alpha=pixels[3::4]
                # Same integer as sum(1<<i for alpha[i]>.5): Blender's bottom-up pixel order.
                mask=int.from_bytes(np.packbits(alpha>.5,bitorder='little').tobytes(),'little')
                if not 0<mask.bit_count()<len(alpha) and not args.get('allowBlank'):
                    raise RuntimeError('Canonical render is blank or fills the entire frame')
                results.append({'view':name,'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                                'maskHex':hex(mask),'pixels':len(alpha),'foreground':mask.bit_count()})
            finally: bpy.data.images.remove(image)
    finally:
        bpy.data.scenes.remove(scene); bpy.data.objects.remove(camera,do_unlink=True); bpy.data.cameras.remove(camera_data)
    return {'framing':framing,'views':results,'resolution':resolution,
            'programSha256':bpy.data.collections[args['collection']].get('laya_program_sha256') if args.get('collection') else None}


def execute(action,args,project_path):
    if action=='transcribe': return transcribe(args)
    if action=='mesh_fix': return fix(args)
    if action=='canonical': return canonical(args,project_path)
    path=project_path(args['path'],{'.blend'})
    if action=='snapshot':
        if path.exists(): raise ValueError('Snapshot must be a new file')
        path.parent.mkdir(parents=True,exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(path),copy=True)
        return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    if action=='restore':
        if hashlib.sha256(path.read_bytes()).hexdigest()!=args.get('sha256'): raise ValueError('Snapshot hash differs')
        bpy.ops.wm.open_mainfile(filepath=str(path),load_ui=False)
        return {'path':str(path),'restored':True}
    raise ValueError('Unknown mesh action')
