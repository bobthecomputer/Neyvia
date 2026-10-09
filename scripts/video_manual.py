"""Author/compile the video manual (manuals/cl/video.cl): HyperFrames editing actions, the LAYA video
observers, fast outcome contracts and the predicate vocabulary with named fixes. No test files."""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from grant_agent.cl.manuals import manual_to_cl, cl_to_manual
from grant_agent.neyvia_video import DEFINITIONS, mutability

# Predicates: one per line, evaluated by the shared Scene core over observed nodes (field paths are node paths).
# "node" guards the node kind; "domain" is video (a render) or video-edit (the composition before rendering).
P = []
def bug(type_, node, predicate, fix, means, severity='error', domain='video', instruction=''):
    P.append({'type': type_, 'domain': domain, 'node': node, 'predicate': predicate, 'fix': fix, 'severity': severity,
              'means': means, **({'instruction': instruction} if instruction else {})})
f = lambda field, op, value=None: {'field': field, 'op': op, **({} if value is None and op == 'nonempty' else {'value': value})}
ALL = lambda *c: {'all': list(c)}
ANY = lambda *c: {'any': list(c)}
bug('render-failed', 'video', f('measurements.renderOk', 'eq', False), 'video.render',
    'The render is missing, empty or has no decodable video stream.', instruction='Run video.timeline, clear lint errors, render again.')
bug('duration-off', 'video', f('measurements.durationErrorS', 'gt', 0.1), 'edl.fit-duration', 'Rendered length differs from the brief by more than 0.1 s.')
bug('frame-count-off', 'video', f('measurements.frameDelta', 'gt', 2), 'edl.fit-duration', 'Frame count differs from duration x fps by more than 2 frames.')
bug('wrong-aspect', 'video', f('measurements.aspectOk', 'eq', False), 'edl.set-canvas', 'The frame is not the aspect ratio the brief asks for.',
    instruction='Create the project at the brief width/height; the canvas is fixed per project.')
bug('black-frames', 'black-run', f('measurements.intended', 'eq', False), 'edl.fill-gap', 'Black frames outside the allowed fade-in/fade-out head and tail.')
bug('frozen-frames', 'freeze-run', f('measurements.intended', 'eq', False), 'edl.add-motion', 'Identical frames for longer than the brief allows, not marked as a hold.')
bug('jump-cut', 'cut', ALL(f('measurements.intended', 'eq', False), f('measurements.type', 'eq', 'hard'), f('measurements.similarity', 'ge', 0.92)),
    'edl.crossfade-cut', 'A hard cut between two nearly identical frames that nobody asked for.', 'warning')
bug('audio-clipping', 'audio', ALL(f('measurements.present', 'eq', True), ANY(f('measurements.clippedSamples', 'gt', 0), f('measurements.truePeakOver', 'gt', 0))),
    'edl.music-gain', 'Samples at full scale or a true peak above the brief ceiling (default -1 dBTP).')
bug('loudness-off', 'audio', ALL(f('measurements.present', 'eq', True), f('measurements.loudnessOffBy', 'gt', 2)), 'edl.music-gain',
    'Integrated loudness more than 2 LU from the brief target.', 'warning')
bug('dead-air', 'silence', ALL(f('measurements.musicExpected', 'eq', True), f('measurements.intended', 'eq', False)), 'edl.extend-music',
    'Silence (< -50 dBFS) for 2 s or more while the brief asks for sound.')
bug('caption-not-rendered', 'caption', f('measurements.observed', 'eq', False), 'edl.caption-readable',
    'An authored caption cannot be read back from the rendered frame.')
bug('caption-outside-safe-area', 'caption', ALL(f('measurements.observed', 'eq', True), f('measurements.insideSafeArea', 'eq', False)), 'edl.caption-band',
    'The caption as rendered crosses the title-safe margin (5% by default).')
bug('caption-overlap', 'caption', ALL(f('measurements.observed', 'eq', True), f('measurements.overlapsText', 'nonempty')), 'edl.caption-band',
    'The rendered caption touches other on-screen text (UI text behind or beside it).')
bug('caption-unreadable', 'caption', ALL(f('measurements.observed', 'eq', True), ANY(f('measurements.contrastRatio', 'lt', 3.0), f('measurements.lineHeightPx', 'lt', 22),
    f('measurements.charsPerSecond', 'gt', 17))), 'edl.caption-readable',
    'Pixel-measured caption contrast below 3:1 (anti-aliasing lowers pixel contrast), lines under 22 px, or more than 17 characters per second.')
bug('caption-too-long', 'caption', f('measurements.wordsOver', 'gt', 0), 'edl.caption-shorten', 'More words in one caption than the brief allows.', 'warning')
bug('stock-phrase', 'caption', f('measurements.stockPhrase', 'eq', True), 'edl.plain-copy', 'Template copy (seamless, unlock, AI-powered, introducing...).', 'warning')
bug('pacing-off', 'shot', ANY(f('measurements.tooShortBy', 'gt', 0.05), f('measurements.tooLongBy', 'gt', 0.05)), 'edl.retime-shot',
    'A shot is shorter or longer than the brief pacing allows.', 'warning')
bug('cut-off-beat', 'cut', ALL(f('measurements.syncRequested', 'eq', True), f('measurements.offBeatS', 'gt', 0.09)), 'edl.snap-cuts-to-beats',
    'The brief asks for cuts on the beat and this cut is more than 90 ms from the nearest detected beat.', 'warning')
bug('must-include-missing', 'brief-item', f('measurements.covered', 'eq', False), 'edl.add-must-include', 'Something the brief requires is not on screen long enough.')
bug('screen-too-small', 'shot', ALL(f('measurements.isScreen', 'eq', True), f('measurements.screenCoverage', 'lt', 0.4)), 'edl.reframe',
    'The product screen fills less than 40% of the frame (a tall or phone capture floating in a 16:9 field).', 'warning')
bug('ui-defect-on-screen', 'shot', f('measurements.uiDefects', 'nonempty'), 'edl.swap-asset',
    'LAYA\'s calibrated UI glance finds a viewer-visible defect (see-through, raw error, blank render, encoded path, internal id) on a screen that is not meant to show one.', 'warning')
bug('compare-not-legible', 'compare-pair', f('measurements.cutSeen', 'eq', False), 'edl.punch-in',
    'A before/after pair (a defect, then its fix) reads as one unchanged shot: the change is too small at full-frame scale.')
bug('brand-type-off', 'brand', f('measurements.fontOnGuide', 'eq', False), 'edl.brand-style', 'Caption type is not a brand typeface.')
bug('brand-colour-off', 'brand', f('measurements.captionColourDistance', 'gt', 60), 'edl.brand-style', 'Measured caption ink is far from every brand colour.', 'warning')
bug('product-named-late', 'naming', f('measurements.namedLateByS', 'gt', 0), 'edl.name-early', 'The product name is not readable on screen within the first quarter.', 'warning')
bug('timeline-overrun', 'timeline-clip', f('measurements.overrunS', 'gt', 0.01), 'edl.fit-duration', 'A HyperFrames clip ends after the composition.')
bug('composition-lint-error', 'lint', f('measurements.errors', 'gt', 0), 'video.lint', 'HyperFrames lint reports errors.', instruction='Read the lint codes and fix the EDL or composition.')
# before rendering: the composition and timeline Scene
bug('edit-duration-off', 'composition', f('measurements.durationErrorS', 'gt', 0.05), 'edl.fit-duration', 'Timeline length differs from the brief.', domain='video-edit')
bug('edit-aspect', 'composition', f('measurements.aspectOk', 'eq', False), 'edl.set-canvas', 'Canvas aspect differs from the brief.', domain='video-edit')
bug('visual-gap', 'composition', f('measurements.gaps', 'nonempty'), 'edl.fill-gap', 'No visual clip covers part of the timeline (it will render black).', domain='video-edit')
bug('caption-collision', 'clip-caption', f('measurements.collidesWith', 'nonempty'), 'edl.retime-caption', 'Two captions are on screen at once.', domain='video-edit')
bug('edit-caption-too-long', 'clip-caption', f('measurements.wordsOver', 'gt', 0), 'edl.caption-shorten', 'Caption longer than the brief allows.', 'warning', 'video-edit')
bug('edit-caption-too-fast', 'clip-caption', f('measurements.charsPerSecond', 'gt', 17), 'edl.caption-readable', 'Caption shown too briefly to read.', 'warning', 'video-edit')
bug('edit-stock-phrase', 'clip-caption', f('measurements.stockPhrase', 'eq', True), 'edl.plain-copy', 'Template copy in a caption.', 'warning', 'video-edit')
bug('edit-overrun', 'timeline-clip', f('measurements.overrunS', 'gt', 0.01), 'edl.fit-duration', 'A clip ends after the composition.', domain='video-edit')
bug('edit-lint-error', 'lint', f('measurements.errors', 'gt', 0), 'video.lint', 'HyperFrames lint reports errors.', domain='video-edit')

# One video stack (7 Oct): rendered cuts are judged by laya_video with manuals/cl/laya-video.cl, which took over
# the render predicates above that it lacked (frame-count-off, loudness-off, caption-not-rendered, caption-too-long,
# stock-phrase). This manual keeps the neyvia.video.* actions and the pre-render video-edit vocabulary.
P = [p for p in P if p['domain'] == 'video-edit']
names = [r[0] for r in DEFINITIONS]
schemas = {'neyvia.' + name: {'type': 'object', 'properties': props, 'required': required} for name, _, props, required in DEFINITIONS}
actions = {name.replace('.', '-'): {'tool': 'neyvia.' + name, 'schema': 'neyvia.' + name, 'returns': {'type': 'object'},
           'pre': 'Project folder inside the workspace or D:/NeyviaRuns/video; HyperFrames CLI installed; nothing opens a window',
           'effect': description, 'reversible': mutability(name) == 'read' or name in {'video.add', 'video.caption', 'video.trim', 'video.split',
                                                                                        'video.transition', 'video.keyframe', 'video.remove'}}
           for name, description, _, _ in DEFINITIONS}
checks = {'contracts-fixture': {'tool': 'neyvia.video.contracts_proof', 'args': {}, 'expect': {'op': 'eq', 'path': 'passed', 'value': True}}}
I = lambda key: {'$input': key}
chapter = {
    'title': 'Video: HyperFrames compositions as edit decision lists, LAYA video observers and outcome contracts',
    'state': {}, 'actions': actions, 'checks': checks,
    'procedures': {
        'prove-contracts': {'goal': 'Render (or reuse) the 3 s fixture and show render ok, duration/frames, black, frozen, clipping and caption safe-area contracts each catch their defect and pass the clean section',
                            'inputs': {'type': 'object', 'properties': {}},
                            'steps': [{'action': 'video-contracts_proof', 'args': {}, 'save': 'proof', 'check': 'contracts-fixture'}]},
        'cut-from-screens': {'goal': 'Build a short cut by hand: new project, one screen with a push, a caption, read the timeline Scene, render, run the outcome contracts',
                             'inputs': {'type': 'object', 'properties': {'project': {'type': 'string'}, 'screen': {'type': 'string'}, 'caption': {'type': 'string'}},
                                        'required': ['project', 'screen', 'caption'], 'additionalProperties': False},
                             'steps': [{'action': 'video-new', 'args': {'project': I('project'), 'duration': 4}, 'save': 'project'},
                                       {'action': 'video-add', 'args': {'project': I('project'), 'kind': 'image', 'src': I('screen'), 'start': 0, 'duration': 4, 'id': 'shot-1'}, 'save': 'shot'},
                                       {'action': 'video-keyframe', 'args': {'project': I('project'), 'id': 'shot-1', 'property': 'scale', 'at': 4, 'value': 1.04}, 'save': 'push'},
                                       {'action': 'video-caption', 'args': {'project': I('project'), 'text': I('caption'), 'start': 0.5, 'duration': 3}, 'save': 'caption'},
                                       {'action': 'video-timeline', 'args': {'project': I('project')}, 'save': 'timeline'},
                                       {'action': 'video-render', 'args': {'project': I('project')}, 'save': 'render'}]},
        'edit-from-brief': {'goal': 'LAYA edits by itself from a brief: plan v1, render, transcribe, judge, fix, re-render, keep only improvements, write episodes',
                            'inputs': {'type': 'object', 'properties': {'brief': {'type': 'string'}, 'out': {'type': 'string'}},
                                       'required': ['brief', 'out'], 'additionalProperties': False},
                            'steps': [{'action': 'video-improve', 'args': {'brief': I('brief'), 'out': I('out')}, 'save': 'report'}]}},
    'judge': {},
    'pitfalls': [{'failure': 'Studio or preview opens a browser window', 'recovery': 'Always pass --no-open (video.studio does) and an explicit port 49165-49167 (track VIDEO block).'},
                 {'failure': 'An edit made in HyperFrames Studio is overwritten', 'recovery': 'Studio edits index.html; neyvia.video.* regenerates index.html from edl.json. Read the change back with video.timeline and mirror it into the EDL before the next EDL edit.'},
                 {'failure': 'Pixel-measured caption contrast reads low', 'recovery': 'Anti-aliasing lowers measured contrast; the predicate uses 3:1 on pixels, not the 4.5:1 CSS rule.'}],
    'frontier': ['Rendering uses a local chrome-headless-shell with a throwaway profile (HyperFrames has no connect-over-CDP); no window opens. The composition DOM (caption boxes, fonts) is read in headless Obscura.',
                 'A 33 s cut renders at 640x360@12 in about 1-3 minutes for a judge round and at 1920x1080@60 for the master; the fast outcome contracts on an existing render take seconds.',
                 'Speech-to-text is local Whisper (base, cached; nothing is downloaded); segments the model marks as non-speech are dropped, words keep start and end. Music-only cuts transcribe to no words.',
                 'HyperFrames normalises each <audio> clip, so its own renders do not clip; audio-clipping still guards raw muxes and other editors (the contracts fixture muxes a clipped tone to prove it).',
                 'Studio edits index.html; neyvia.video.* regenerates index.html from edl.json, so a hand edit in Studio must be mirrored into the EDL (read it back with video.timeline).',
                 "Taste is not a crisp predicate: Paul's A/B votes are written as personal episodes (video.vote); none were cast by agents."],
    'guidance': ['An agent edits a video through the EDL (video.new/add/trim/split/transition/caption/keyframe/remove); every edit recompiles index.html in HyperFrames\' own composition format, so HyperFrames Studio, lint, timeline and render all see the same project.',
                 'Observe before rendering with video.timeline (the composition and timeline as a Scene, judged with the video-edit predicates below), and after rendering with video.transcribe/video.judge: the one video judge (laya_video, vocabulary manuals/cl/laya-video.cl) measures shots, cuts, black and frozen runs, loudness and true peak, beats, Whisper words with start/end, keyframe OCR, caption DOM boxes and the LAYA glance plus source audit of every screen.',
                 'Run video.contracts on any render for the fast outcome contracts; video.contracts_proof shows each contract catching its defect on a fixture.',
                 'video.improve runs the whole loop from a CL brief (laya_video.improve_cut): one named EDL fix per round through scene_core.improve, kept only on a strict finding reduction with no guarded metric regression, otherwise edl.json and the re-observed Scene are restored exactly; every outcome is an episode.',
                 'Credit: HyperFrames by HeyGen (Apache-2.0) is the renderer and Studio; Neyvia adapts it through its CLI and file format, without a fork. The tools, free-form EDL, pre-render checks, contracts and Whisper word timings were written on track/laya-video; the judge, cut EDL, store entries and launch loop on track/video; both were reconciled into this one stack on 7 Oct.']}
manual = {'schema': 'neyvia.manual.v1', 'id': 'video', 'kind': 'environment', 'schemas': schemas, 'chapters': {'video': chapter},
          'proofs': {'area': 'video', 'contracts': [
              {'id': 'video.outcome-contracts', 'phase': 'invariant',
               'checkedAt': ['grant_agent.video_contracts.proof', 'grant_agent.laya_video.observe_file', 'grant_agent.scene_core.judge'],
               'impact': ['src/grant_agent/video_contracts.py', 'src/grant_agent/laya_video.py', 'src/grant_agent/video_hyperframes.py', 'manuals/cl/video.cl'],
               'claim': 'A rendered fixture shows each fast outcome contract (render, duration/frames, black, frozen, clipping, caption safe area) catching its defect and passing the clean section.'}]}}
cl = manual_to_cl(manual) + '\n' + '\n'.join('-- @bug ' + json.dumps(p, ensure_ascii=False) for p in P) + '\n'
source = ROOT / 'manuals/cl/video.cl'
source.write_text(cl, encoding='utf-8', newline='\n')
artifact = cl_to_manual(cl)
(ROOT / 'manuals/video.manual.json').write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
index_path = ROOT / 'config/neyvia_manuals.json'
index = json.loads(index_path.read_text(encoding='utf-8'))
if not any(r['id'] == 'video' for r in index['manuals']):
    index['manuals'].append({'id': 'video', 'path': 'manuals/video.manual.json',
                             'description': 'HyperFrames video editing through EDLs, LAYA video observers, predicates with fixes and fast outcome contracts',
                             'clSource': 'manuals/cl/video.cl'})
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
print('Authored video manual with', len(P), 'predicates and', len(actions), 'actions')
