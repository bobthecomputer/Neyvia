"""Local image eyes: mask -> CL parts, outlines, proportions and colour, never a mesh generator."""
import hashlib
from pathlib import Path

import numpy as np
from PIL import Image

SIZE=128
WORLD=2.56


def components(mask):
    remaining=set(map(tuple,np.argwhere(mask))); groups=[]
    while remaining:
        todo=[remaining.pop()]; group=[]
        while todo:
            y,x=todo.pop(); group.append((y,x))
            for key in ((y-1,x),(y+1,x),(y,x-1),(y,x+1)):
                if key in remaining: remaining.remove(key); todo.append(key)
        if len(group)>=4: groups.append(group)
    return sorted(groups,key=len,reverse=True)


def outline(mask):
    """Trace directed pixel-cell boundaries, including holes; no hull shortcut."""
    edges={}
    height,width=mask.shape
    def edge(a,b): edges.setdefault(a,[]).append(b)
    for y,x in np.argwhere(mask):
        if y==0 or not mask[y-1,x]: edge((x,y),(x+1,y))
        if x==width-1 or not mask[y,x+1]: edge((x+1,y),(x+1,y+1))
        if y==height-1 or not mask[y+1,x]: edge((x+1,y+1),(x,y+1))
        if x==0 or not mask[y,x-1]: edge((x,y+1),(x,y))
    loops=[]
    while edges:
        start=next(iter(edges)); point=start; loop=[]
        while True:
            loop.append(point); next_point=edges[point].pop()
            if not edges[point]: del edges[point]
            point=next_point
            if point==start: break
        simplified=[p for i,p in enumerate(loop) if (p[0]-loop[i-1][0],p[1]-loop[i-1][1]) !=
                    (loop[(i+1)%len(loop)][0]-p[0],loop[(i+1)%len(loop)][1]-p[1])]
        if len(simplified)>=3:
            loops.append([[round((x/width-.5)*WORLD,6),round((.5-y/height)*WORLD,6)] for x,y in simplified])
    return loops


def describe(image,mask,name,path):
    yy,xx=np.where(mask); rgb=np.asarray(image.convert('RGB'))
    groups=components(mask)
    bounds=[int(xx.min()),int(yy.min()),int(xx.max()+1),int(yy.max()+1)]
    colour=np.median(rgb[mask],axis=0)/255
    regions=[]
    for index,group in enumerate(groups):
        part=np.zeros_like(mask); coordinates=np.asarray(group); part[coordinates[:,0],coordinates[:,1]]=True
        py,px=np.where(part)
        regions.append({'id':'part-'+str(index),'bounds':[int(px.min()),int(py.min()),int(px.max()+1),int(py.max()+1)],
                        'area':int(part.sum()),'colour':(np.median(rgb[part],axis=0)/255).tolist(),
                        'outline':outline(part)})
    return {'view':name,'path':str(path),'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            'maskHex':hex(sum(1<<int(i) for i,v in enumerate(mask.ravel()) if v)), 'pixels':mask.size,
            'bounds':bounds,'proportion':(bounds[2]-bounds[0])/(bounds[3]-bounds[1]),
            'colour':colour.tolist(),'parts':len(groups),'symmetryIoU':float(np.logical_and(mask,mask[:,::-1]).sum()/np.logical_or(mask,mask[:,::-1]).sum()),
            'outline':outline(mask),'regions':regions}
