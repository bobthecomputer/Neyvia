"""Prepare the task-local Obscura iframe paint patch; never edit the source donor."""
from pathlib import Path
import difflib
import hashlib
import json

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / '.agent_control/fixcl7/obscura-source'
changes = []
receipt_path = REPO / 'scripts/evidence/FIXCL7-renderer-patch.json'
if receipt_path.is_file():
    previous = json.loads(receipt_path.read_bytes())
    if all(hashlib.sha256((SOURCE / row['path']).read_bytes()).hexdigest() == row['afterSha256']
           for row in previous['changes']):
        print(json.dumps({'status':'current','files':len(previous['changes'])}))
        raise SystemExit(0)

def edit(relative, transform):
    path = SOURCE / relative
    before = path.read_text(encoding='utf-8')
    after = transform(before)
    if before == after: raise ValueError('Patch anchor missing: ' + relative)
    path.write_text(after, encoding='utf-8', newline='\n')
    changes.append((relative, before, after))

surface = '''
/// Browser-owned child document raster. It is painted as replaced content,
/// through the existing transforms, clipping, border radius and stacking order.
#[cfg(feature = "render")]
pub(crate) struct EmbeddedFrameSurface {
    pub width: u32,
    pub height: u32,
    pub pixels: Vec<u8>,
}
'''
render_frames = '''
    #[cfg(feature = "render")]
    pub(crate) fn render_embedded_frames(&self, parent: &SharedState, depth: usize) {
        if depth > 64 { return; }
        let children: Vec<_> = self.frame_timers.iter().filter_map(|(id, timers)| {
            let (owner, node, generation) = timers.owner.as_ref()?;
            let owner = owner.upgrade()?;
            if !Rc::ptr_eq(&owner, parent) || timers.cancel.is_canceled() { return None; }
            let state = owner.try_borrow().ok()?;
            if state.document_generation != *generation
                || !state.dom.as_ref()?.is_connected(*node) { return None; }
            Some((*node, self.by_frame_id(*id)?))
        }).collect();
        parent.borrow_mut().embedded_surfaces.clear();
        for (node, child) in children {
            self.render_embedded_frames(&child, depth + 1);
            let raster = {
                let mut state = child.borrow_mut();
                if ensure_resolved_scroll(&mut state).is_none() { continue; }
                let ObscuraState { dom, prepared_render, render_resources,
                    resolved_scroll, canvas_surfaces, embedded_surfaces, .. } = &mut *state;
                let Some((_, scroll)) = resolved_scroll.as_ref() else { continue; };
                let surfaces = crate::runtime::RuntimeCanvasSurfaceSource(canvas_surfaces, embedded_surfaces);
                let (Some(dom), Some(prepared)) = (dom.as_ref(), prepared_render.as_mut()) else { continue; };
                obscura_render::paint_prepared_with_scroll_and_surface_color_and_canvas_surfaces(
                    dom, prepared, render_resources, scroll, [255,255,255,255], &surfaces)
            };
            if let Some(raster) = raster {
                parent.borrow_mut().embedded_surfaces.insert(node, EmbeddedFrameSurface {
                    width:raster.width(), height:raster.height(), pixels:raster.data().to_vec() });
            }
        }
    }
'''

def ops(t):
    t = t.replace('const NAVIGATION_TIMING_FIELDS:', surface + '\nconst NAVIGATION_TIMING_FIELDS:', 1)
    t = t.replace('pub(crate) canvas_surfaces: HashMap<NodeId, CanvasBackingSurface>,',
        'pub(crate) canvas_surfaces: HashMap<NodeId, CanvasBackingSurface>,\n    #[cfg(feature = "render")]\n    pub(crate) embedded_surfaces: HashMap<NodeId, EmbeddedFrameSurface>,')
    t = t.replace('canvas_surfaces: HashMap::new(),', 'canvas_surfaces: HashMap::new(),\n            #[cfg(feature = "render")]\n            embedded_surfaces: HashMap::new(),')
    return t.replace('impl RealmStates {', 'impl RealmStates {\n' + render_frames, 1)
edit('crates/obscura-js/src/ops.rs', ops)

def runtime(t):
    t = t.replace("struct RuntimeCanvasSurfaceSource<'a>(&'a HashMap<NodeId, crate::ops::CanvasBackingSurface>);",
        "pub(crate) struct RuntimeCanvasSurfaceSource<'a>(pub &'a HashMap<NodeId, crate::ops::CanvasBackingSurface>, pub &'a HashMap<NodeId, crate::ops::EmbeddedFrameSurface>);")
    t = t.replace('        let surface = self.0.get(&node)?;', '''        if let Some(surface) = self.1.get(&node) {
            return obscura_render::CanvasSurface::from_rgba8(surface.width, surface.height, &surface.pixels);
        }
        let surface = self.0.get(&node)?;''', 1)
    t = t.replace('                canvas_surfaces,\n', '                canvas_surfaces,\n                embedded_surfaces,\n')
    t = t.replace('RuntimeCanvasSurfaceSource(canvas_surfaces)', 'RuntimeCanvasSurfaceSource(canvas_surfaces, embedded_surfaces)')
    anchor = '''    pub fn screenshot_prepared_with_surface_color(
        &self,
        viewport: (f32, f32),
        base_url: Option<&str>,
        surface_color: [u8; 4],
    ) -> Option<Vec<u8>> {'''
    assert t.count(anchor) == 1
    return t.replace(anchor, anchor + '\n        self.realm_states().borrow().render_embedded_frames(&self.state, 0);')
edit('crates/obscura-js/src/runtime.rs', runtime)
edit('crates/obscura-render/src/paint.rs', lambda t:t.replace('if box_on_surface && name.local.as_ref() == "canvas" {',
    'if box_on_surface && matches!(name.local.as_ref(), "canvas" | "iframe") {', 1))

patch = ''.join(''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
    fromfile='a/'+name, tofile='b/'+name)) for name,before,after in changes)
(REPO / 'scripts/obscura-FIXCL7-iframe-paint.patch').write_text(patch,encoding='utf-8',newline='\n')
receipt = {'schema':'neyvia.FIXCL7.renderer-patch.v1', 'source':str(SOURCE), 'changes':[
    {'path':name, 'beforeSha256':hashlib.sha256(before.encode()).hexdigest(), 'afterSha256':hashlib.sha256(after.encode()).hexdigest()}
    for name,before,after in changes], 'boundary':'Actual child realm DOM, native retained resources and existing replaced-content painter; no synthetic pixels, no origin grant or separate page context'}
(REPO / 'scripts/evidence/FIXCL7-renderer-patch.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'files':len(changes),'patchBytes':len(patch)}))
