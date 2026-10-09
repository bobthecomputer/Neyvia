"""Execute the bounded CL shape vocabulary, without Python eval or external generators."""
import json
import math
import re
import uuid
import hashlib
import bpy

COLLECTION='LAYA shape program'


def material(obj,colour):
    if len(colour)!=3 or any(not 0<=c<=1 for c in colour): raise ValueError('Colour must be normalized RGB')
    linear=[c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4 for c in colour]
    mat=bpy.data.materials.new(obj.name+' source colour'); mat.diffuse_color=(*linear,1); mat.use_nodes=True
    nodes=mat.node_tree.nodes; nodes.clear()
    output=nodes.new('ShaderNodeOutputMaterial'); emission=nodes.new('ShaderNodeEmission')
    emission.inputs['Color'].default_value=(*linear,1); emission.inputs['Strength'].default_value=1
    mat.node_tree.links.new(emission.outputs[0],output.inputs['Surface']); obj.data.materials.append(mat)


def extrude(args):
    curve=bpy.data.curves.new(args['name'],'CURVE'); curve.dimensions='2D'; curve.resolution_u=1
    curve.fill_mode='BOTH'; curve.extrude=float(args['depth'])/2
    for loop in args['loops']:
        if len(loop)<3: raise ValueError('An outline loop requires three points')
        spline=curve.splines.new('POLY'); spline.points.add(len(loop)-1)
        for point,(x,z) in zip(spline.points,loop): point.co=(x,z,0,1)
        spline.use_cyclic_u=True
    obj=bpy.data.objects.new(args['name'],curve); bpy.context.collection.objects.link(obj)
    obj.rotation_euler=(0,0,0) if args.get('view')=='top' else (math.pi/2,0,{'side':math.pi/2,'back':math.pi}.get(args.get('view'),0))
    bpy.context.view_layer.objects.active=obj; obj.select_set(True)
    bpy.ops.object.convert(target='MESH'); obj=bpy.context.object
    bpy.ops.object.transform_apply(location=False,rotation=True,scale=True)
    return obj


def sweep(args):
    # Sections = [z, center_x, center_y, radius_x, radius_y]. A lathe is the
    # same native construction with equal radii; endpoints are capped.
    sections=args['sections']; sides=int(args.get('sides',32))
    if not 3<=sides<=128 or not 2<=len(sections)<=256: raise ValueError('Sweep resolution exceeds limits')
    vertices=[]
    for z,cx,cy,rx,ry in sections:
        vertices.extend((cx+rx*math.cos(i*2*math.pi/sides),cy+ry*math.sin(i*2*math.pi/sides),z) for i in range(sides))
    faces=[tuple(reversed(range(sides)))]
    for j in range(len(sections)-1):
        for i in range(sides):
            nxt=(i+1)%sides; faces.append((j*sides+i,j*sides+nxt,(j+1)*sides+nxt,(j+1)*sides+i))
    faces.append(tuple((len(sections)-1)*sides+i for i in range(sides)))
    mesh=bpy.data.meshes.new(args['name']); mesh.from_pydata(vertices,[],faces); mesh.update()
    obj=bpy.data.objects.new(args['name'],mesh); bpy.context.collection.objects.link(obj); return obj


def project_views(obj,args,project_path):
    """Per-face source-view colour from the fitted cameras (occlusion is not modelled)."""
    import numpy as np
    from .hull_math import project,rotation,FRAME
    mesh=obj.data
    uv=mesh.uv_layers.new(name='SourceView') if not mesh.uv_layers else mesh.uv_layers.active
    views=args['views']
    if not 1<=len(views)<=8: raise ValueError('Texture projection needs one to eight fitted views')
    base=mesh.materials[0] if mesh.materials else None
    slots=[]; toward=[]
    for view in views:
        image=bpy.data.images.load(str(project_path(view['path'])),check_existing=True)
        image.colorspace_settings.name='sRGB'
        mat=base.copy() if base else bpy.data.materials.new('LAYA view'); mat.name=obj.name+' '+view['view']
        mesh.materials.append(mat); slots.append(len(mesh.materials)-1)
        texture=mat.node_tree.nodes.new('ShaderNodeTexImage'); texture.image=image; texture.interpolation='Closest'
        emission=next(n for n in mat.node_tree.nodes if n.type=='EMISSION')
        mat.node_tree.links.new(texture.outputs['Color'],emission.inputs['Color'])
        mat.node_tree.nodes.active=texture
        toward.append(rotation(view['camera'])[2])
    toward=np.asarray(toward)
    count=len(mesh.polygons)
    normals=np.zeros(count*3); mesh.polygons.foreach_get('normal',normals); normals=normals.reshape(-1,3)
    matrix=np.asarray(obj.matrix_world.to_3x3()); normals=normals@matrix.T
    # Earlier views are the more trusted readings (anchor first): small priority margin.
    choice=np.argmax(normals@toward.T-.12*np.arange(len(views))[None,:],axis=1)
    mesh.polygons.foreach_set('material_index',np.asarray(slots)[choice].astype(np.int32))
    coords=np.zeros(len(mesh.vertices)*3); mesh.vertices.foreach_get('co',coords)
    world=coords.reshape(-1,3)@matrix.T+np.asarray(obj.matrix_world.translation)
    loops=np.zeros(len(mesh.loops),np.int32); mesh.loops.foreach_get('vertex_index',loops)
    starts=np.zeros(count,np.int32); totals=np.zeros(count,np.int32)
    mesh.polygons.foreach_get('loop_start',starts); mesh.polygons.foreach_get('loop_total',totals)
    order=np.concatenate([np.arange(s,s+t) for s,t in zip(starts,totals)]) if count else np.zeros(0,int)
    owner=np.empty(len(mesh.loops),np.int32); owner[order]=np.repeat(np.arange(count),totals)
    result=np.zeros((len(mesh.loops),2))
    for index,view in enumerate(views):
        selected=choice[owner]==index
        u,v,_=project(world[loops[selected]],view['camera'])
        result[selected]=np.stack([u/FRAME,1-v/FRAME],1)
    uv.data.foreach_set('uv',result.astype(np.float32).ravel())


def execute(program,project_path):
    if len(program)>500_000: raise ValueError('CL shape program exceeds 500 KB')
    operations=[]
    for line in program.splitlines():
        if not line.strip() or line.startswith(('CL ','L ','--')): continue
        match=re.fullmatch(r'shape\.([a-z_]+)\((\{.*\})\)',line)
        if not match: raise ValueError('Expected a literal shape operation')
        args=json.loads(match[2],parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Nonfinite number')))
        operations.append((match[1],args))
    if not 1<=len(operations)<=100: raise ValueError('Shape program needs 1..100 operations')
    previous=bpy.data.collections.get(COLLECTION)
    collection=bpy.data.collections.new(COLLECTION+' candidate '+uuid.uuid4().hex)
    bpy.context.scene.collection.children.link(collection)
    try:
        result=build(operations,collection,project_path)
    except Exception:
        for obj in list(collection.objects): bpy.data.objects.remove(obj,do_unlink=True)
        bpy.data.collections.remove(collection)
        raise
    if previous:
        for obj in list(previous.objects): bpy.data.objects.remove(obj,do_unlink=True)
        bpy.data.collections.remove(previous)
    collection.name=COLLECTION
    collection['laya_program_sha256']=hashlib.sha256(program.encode()).hexdigest()
    return result


def build(operations,collection,project_path):
    created={}
    for operation,args in operations:
        bpy.ops.object.select_all(action='DESELECT')
        if operation in {'extrude','sweep','lathe','primitive','visual_hull'}:
            if args['name'] in created: raise ValueError('Duplicate shape identity')
            if operation=='visual_hull':
                from .visual_hull import build as hull
                obj=hull(args)
            elif operation=='extrude': obj=extrude(args)
            elif operation in {'sweep','lathe'}:
                if operation=='lathe': args={**args,'sections':[[z,0,0,r,r] for z,r in args['profile']]}
                obj=sweep(args)
            else:
                primitive=args['kind']
                operators={'box':bpy.ops.mesh.primitive_cube_add,'sphere':bpy.ops.mesh.primitive_uv_sphere_add,
                           'cylinder':bpy.ops.mesh.primitive_cylinder_add,'cone':bpy.ops.mesh.primitive_cone_add}
                if primitive not in operators: raise ValueError('Unknown primitive')
                operators[primitive](); obj=bpy.context.object; obj.name=args['name']
                obj.scale=args.get('scale',[1,1,1]); obj.location=args.get('location',[0,0,0])
            for owner in list(obj.users_collection): owner.objects.unlink(obj)
            collection.objects.link(obj); created[args['name']]=obj; material(obj,args.get('colour',[.5,.5,.5]))
            continue
        obj=created[args['target']]; obj.select_set(True); bpy.context.view_layer.objects.active=obj
        if operation=='boolean':
            modifier=obj.modifiers.new('CL boolean','BOOLEAN'); modifier.operation=args['operation']; modifier.solver='EXACT'
            modifier.object=created[args['operand']]; bpy.ops.object.modifier_apply(modifier=modifier.name)
            bpy.data.objects.remove(created.pop(args['operand']),do_unlink=True)
        elif operation in {'bevel','subdivide','mirror','displace'}:
            kind={'bevel':'BEVEL','subdivide':'SUBSURF','mirror':'MIRROR','displace':'DISPLACE'}[operation]
            modifier=obj.modifiers.new('CL '+operation,kind)
            if operation=='bevel': modifier.width=max(0,min(.2,float(args.get('width',.02)))); modifier.segments=2
            elif operation=='subdivide': modifier.levels=min(2,max(1,int(args.get('levels',1))))
            elif operation=='mirror': modifier.use_axis=tuple(i==int(args.get('axis',0)) for i in range(3))
            else:
                image=bpy.data.images.load(str(project_path(args['path'])),check_existing=True)
                texture=bpy.data.textures.new('CL observed depth','IMAGE'); texture.image=image
                modifier.texture=texture; modifier.strength=min(.5,max(0,float(args.get('strength',.1)))); modifier.texture_coords='UV'
            bpy.ops.object.modifier_apply(modifier=modifier.name)
        elif operation=='smooth':
            # Voxel remesh at the hull pitch, then bounded Laplacian relaxation.
            step=float(obj.get('laya_hull_step',.02))
            remesh=obj.modifiers.new('CL remesh','REMESH'); remesh.mode='VOXEL'
            remesh.voxel_size=max(.002,min(.2,step*float(args.get('pitch',.75))))
            bpy.ops.object.modifier_apply(modifier=remesh.name)
            relax=obj.modifiers.new('CL relax','SMOOTH'); relax.factor=max(0.,min(1.,float(args.get('factor',.5))))
            relax.iterations=max(0,min(30,int(args.get('iterations',6))))
            bpy.ops.object.modifier_apply(modifier=relax.name)
            for polygon in obj.data.polygons: polygon.use_smooth=True
        elif operation=='project_texture':
            project_views(obj,args,project_path)
        else: raise ValueError('Unknown shape operation: '+operation)
    bpy.context.view_layer.update()
    return {'objects':list(created),'operations':len(operations),'vertices':sum(len(o.data.vertices) for o in created.values())}
