"""One camera definition for native rendering and silhouette-cone construction."""
import math
from mathutils import Vector


def frame(name,framing,spec=None):
    spec=spec or {}; size=float(spec.get('size',framing['size']))
    if 'yaw' in spec or 'elevation' in spec:
        yaw=math.radians(float(spec.get('yaw',0))); elevation=math.radians(float(spec.get('elevation',0)))
        direction=Vector((math.sin(yaw)*math.cos(elevation),-math.cos(yaw)*math.cos(elevation),math.sin(elevation)))
    else: direction=Vector({'front':(0,-1,0),'side':(1,0,0),'back':(0,1,0),'top':(0,0,1)}[name])
    center=Vector(framing['center']); location=center+direction*float(spec.get('distance',size*2))
    matrix=(center-location).to_track_quat('-Z','Y').to_matrix().to_4x4(); matrix.translation=location
    return matrix,size,spec.get('projection','orthographic'),float(spec.get('lens',50))
