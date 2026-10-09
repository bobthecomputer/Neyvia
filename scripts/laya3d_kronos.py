"""LAYA 3D on Paul's KRONOS sheets: SEE -> CL shape program -> Blender -> compare -> fix.

Private Blender background session through the production GameDev bridge; the shared
Scene core judges and keeps or reverts every program edit. Writes models, per-view IoU,
seconds per object and before/after renders to D:\\NeyviaRuns\\laya-3d\\kronos\\out.
"""
import argparse
import json
from pathlib import Path
import shutil
import time

import numpy as np
from PIL import Image, ImageDraw

from laya3d_harness import Harness, REPO

KRONOS = Path('D:/NeyviaRuns/laya-3d/kronos')
OUT = KRONOS / 'out'
# Transcription of sheet 09 captions (agent-read) with coarse camera readings. Physical
# cell index = row-major position in the detected grid; printed numbers are recorded only.
OBJECTS = {
    'main-weapon': {'sheet': 'sheet-09.png', 'cells': [
        {'cell': 3, 'printed': 3, 'caption': 'Main Weapon (Top)', 'role': 'top', 'camera': {'yaw': 0, 'elevation': 90, 'roll': 0}},
        {'cell': 1, 'printed': 1, 'caption': 'Main Weapon (Side L)', 'role': 'left-34', 'camera': {'yaw': 0, 'elevation': 20, 'roll': 30},
         'note': 'three-quarter view, not an orthographic side'},
        {'cell': 2, 'printed': 2, 'caption': 'Main Weapon (Side R)', 'role': 'right-34', 'camera': {'yaw': 0, 'elevation': 20, 'roll': 30},
         'note': 'drawn like Side L; not a right view'},
        {'cell': 4, 'printed': 4, 'caption': 'Main Weapon (Bottom)', 'role': 'bottom', 'camera': {'yaw': 0, 'elevation': -90, 'roll': [0, 180]}},
        {'cell': 5, 'printed': 5, 'caption': 'Main Weapon (Front)', 'role': 'top-upright', 'camera': {'yaw': 0, 'elevation': 90, 'roll': [90, -90]},
         'note': 'drawn as the top view turned upright, not muzzle-on'},
        {'cell': 6, 'printed': 6, 'caption': 'Main Weapon (Back)', 'role': 'bottom-upright', 'camera': {'yaw': 0, 'elevation': -90, 'roll': [90, -90]},
         'note': 'drawn as the bottom view turned upright'},
        {'cell': 7, 'printed': 7, 'caption': 'Main Weapon (Detail)', 'role': 'detail', 'illustrationOnly': True}]},
    'gun-mode': {'sheet': 'sheet-09.png', 'cells': [
        {'cell': 13, 'printed': 13, 'caption': 'Gun Mode (Top)', 'role': 'top', 'camera': {'yaw': 0, 'elevation': 90, 'roll': 0}},
        {'cell': 11, 'printed': 11, 'caption': 'Gun Mode (Left)', 'role': 'left-34', 'camera': {'yaw': [-25, 155], 'elevation': 15, 'roll': [10, -10]},
         'note': 'three-quarter view'},
        {'cell': 12, 'printed': 12, 'caption': 'Gun Mode (Right)', 'role': 'right-34', 'camera': {'yaw': [-25, 155, 25, 205], 'elevation': 15, 'roll': [10, -10]},
         'note': 'barrel points the same way as Left'},
        {'cell': 14, 'printed': 14, 'caption': 'Gun Mode (Bottom)', 'role': 'bottom', 'camera': {'yaw': 0, 'elevation': -90, 'roll': [0, 180]}}]},
    'backpack': {'sheet': 'sheet-09.png', 'cells': [
        {'cell': 31, 'printed': 31, 'caption': 'Backpack (Front)', 'role': 'front', 'camera': {'yaw': -20, 'elevation': 15, 'roll': 0},
         'note': 'three-quarter front-left from slightly above'},
        {'cell': 32, 'printed': 32, 'caption': 'Backpack (Side)', 'role': 'side', 'camera': {'yaw': [90, -90], 'elevation': 10, 'roll': 0}},
        {'cell': 33, 'printed': 33, 'caption': 'Backpack (Back)', 'role': 'back', 'camera': {'yaw': [160, -20], 'elevation': 15, 'roll': 0},
         'note': 'drawn almost like the front'},
        {'cell': 34, 'printed': 34, 'caption': 'Backpack Open', 'role': 'open', 'illustrationOnly': True},
        {'cell': 35, 'printed': 35, 'caption': 'Backpack Detail', 'role': 'detail', 'illustrationOnly': True}]},
    'boot': {'sheet': 'sheet-09.png', 'cells': [
        {'cell': 55, 'printed': 55, 'caption': 'Boot (Back)', 'role': 'back', 'camera': {'yaw': 180, 'elevation': 10, 'roll': 0}},
        {'cell': 53, 'printed': 53, 'caption': 'Boot (Front)', 'role': 'front-34', 'camera': {'yaw': [-45, -60], 'elevation': 15, 'roll': 0},
         'note': 'three-quarter front-left'},
        {'cell': 54, 'printed': 54, 'caption': 'Boot (Side)', 'role': 'side-34', 'camera': {'yaw': [-70, -100], 'elevation': 15, 'roll': 0},
         'note': 'three-quarter side'},
        {'cell': 56, 'printed': 56, 'caption': 'Boot Sole', 'role': 'sole', 'camera': {'yaw': 0, 'elevation': -80, 'roll': [-35, 145]},
         'note': 'perspective bottom view turned diagonally'},
        {'cell': 57, 'printed': 57, 'caption': 'Boot Detail', 'role': 'detail', 'illustrationOnly': True}]},
    'emblem': {'sheet': 'sheet-09.png', 'cells': [
        {'cell': 71, 'printed': 71, 'caption': 'Emblem (Front)', 'role': 'front', 'camera': {'yaw': 0, 'elevation': 0, 'roll': 0}},
        {'cell': 72, 'printed': 72, 'caption': 'Emblem (Side)', 'role': 'side-34', 'camera': {'yaw': [70, -70], 'elevation': 0, 'roll': 0},
         'note': 'three-quarter, not edge-on'},
        {'cell': 73, 'printed': 73, 'caption': 'Emblem (Back)', 'role': 'back', 'camera': {'yaw': 180, 'elevation': 0, 'roll': [0, 45]},
         'note': 'open quadrants where the front is filled: drifted detail'},
        {'cell': 74, 'printed': 74, 'caption': 'Emblem (Exploded)', 'role': 'exploded', 'illustrationOnly': True}]},
    'body-turnaround': {'sheet': 'sheet-01.png', 'cells': [
        {'cell': 1, 'printed': 1, 'caption': 'Front', 'role': 'front', 'camera': {'yaw': 0, 'elevation': 0, 'roll': 0}},
        {'cell': 2, 'printed': 2, 'caption': 'Back', 'role': 'back', 'camera': {'yaw': 180, 'elevation': 0, 'roll': 0}},
        {'cell': 3, 'printed': 3, 'caption': 'Left', 'role': 'left', 'camera': {'yaw': [-90, 90], 'elevation': 0, 'roll': 0}},
        {'cell': 4, 'printed': 4, 'caption': 'Right', 'role': 'right', 'camera': {'yaw': [90, -90], 'elevation': 0, 'roll': 0}},
        {'cell': 5, 'printed': 5, 'caption': 'Front 3/4', 'role': 'front-34', 'camera': {'yaw': [-40, 40], 'elevation': 0, 'roll': 0}},
        {'cell': 6, 'printed': 6, 'caption': 'Back 3/4', 'role': 'back-34', 'camera': {'yaw': [140, -140], 'elevation': 0, 'roll': 0}},
        {'cell': 7, 'printed': 7, 'caption': 'Left 3/4', 'role': 'left-34', 'camera': {'yaw': [-50, 50, -130, 130], 'elevation': 0, 'roll': 0}},
        {'cell': 8, 'printed': 8, 'caption': 'Right 3/4', 'role': 'right-34', 'camera': {'yaw': [50, -50, 130, -130], 'elevation': 0, 'roll': 0}},
        {'cell': 97, 'printed': 97, 'caption': 'Topology Guide', 'role': 'topology', 'illustrationOnly': True},
        {'cell': 98, 'printed': 98, 'caption': 'Model Sheet', 'role': 'model-sheet', 'illustrationOnly': True}]},
    # T-pose: only one view exists. Arms along +/-X hide inside a side silhouette, so the
    # turnaround's side views still constrain depth; front/back views (arms down) would carve them.
    'body-tpose': {'sheet': 'sheet-01.png', 'cells': [
        {'cell': 9, 'printed': 9, 'caption': 'T-Pose', 'role': 'front', 'camera': {'yaw': 0, 'elevation': 0, 'roll': 0}},
        {'cell': 3, 'printed': 3, 'caption': 'Left', 'role': 'left', 'camera': {'yaw': [-90, 90], 'elevation': 0, 'roll': 0},
         'note': 'arms-down side view; valid for depth because T-pose arms project inside it'},
        {'cell': 4, 'printed': 4, 'caption': 'Right', 'role': 'right', 'camera': {'yaw': [90, -90], 'elevation': 0, 'roll': 0}}]},
}
PRESENT = {'yaw': -35, 'elevation': 22, 'roll': 0}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str), encoding='utf-8')


def present_camera(observation):
    low, high = (np.asarray(b) for b in observation['bounds'])
    return {**PRESENT, 'scale': 0.6 * 128 / max(observation['baselineHalfExtents']) / 2, 'offset': [0, 0]}


def contact_sheet(rows, destination):
    """Rows of (label, [image paths]) -> one PNG for Paul to look at."""
    tile = 160
    width = max(len(images) for _, images in rows) * tile + 170
    sheet = Image.new('RGB', (width, tile * len(rows)), (24, 26, 30)); draw = ImageDraw.Draw(sheet)
    for r, (label, images) in enumerate(rows):
        draw.text((8, r * tile + 8), label, fill=(230, 230, 230))
        for c, path in enumerate(images):
            image = Image.open(path).convert('RGBA'); background = Image.new('RGBA', image.size, (205, 208, 214, 255))
            image = Image.alpha_composite(background, image).convert('RGB').resize((tile - 6, tile - 6), Image.Resampling.NEAREST)
            sheet.paste(image, (170 + c * tile, r * tile + 3))
    sheet.save(destination)


def summarize(state):
    """Evaluate the CL contract (manuals/cl/laya-3d-image.cl) over every modelled object."""
    from grant_agent.cl_skill import _parse_skill, _Expr
    from grant_agent.laya_instant import store
    data = json.loads((OUT / 'results.json').read_text(encoding='utf-8'))
    objects = data['objects']
    held = [v['heldOutIoU'] for r in objects.values() for v in r['views'].values() if v['heldOutIoU'] is not None]
    steps = [s for r in objects.values() for s in r['steps']]
    memory = store(str(state)); memory.refresh()
    illustration = {(r['program'], i['cell']) for r in objects.values() for i in r['issues'] if i['kind'] == 'illustration-only'}
    used = {(r['program'], v['cell']) for r in objects.values() for v in r['views'].values()}
    summary = {'objects': len(objects), 'training': False, 'paidCalls': 0, 'externalGenerators': 0,
               'improvedObjects': sum(r['modelAfter']['outlineIoUMean'] > r['modelBefore']['outlineIoUMean'] for r in objects.values()),
               'minimumMeanAfterIoU': min(r['modelAfter']['outlineIoUMean'] for r in objects.values()),
               'meanHeldOutIoU': sum(held) / len(held), 'keptEdits': sum(s['status'] == 'kept' for s in steps),
               'revertedEdits': sum(s['status'] == 'reverted' for s in steps),
               'issuesRecorded': sum(len(r['issues']) for r in objects.values()), 'illustrationCellsUsed': len(illustration & used),
               'maxSecondsPerObject': max(r['seconds'] for r in objects.values()), 'episodes': len(memory.rows),
               'blenderStartupSeconds': data['blenderStartupSeconds'],
               'perObject': {name: {'seconds': round(r['seconds'], 1), 'meanIoU': [r['modelBefore']['outlineIoUMean'], r['modelAfter']['outlineIoUMean']],
                                    'perViewIoU': {k: round(v['afterIoU'], 3) for k, v in r['views'].items()},
                                    'heldOutIoU': {k: round(v['heldOutIoU'], 3) for k, v in r['views'].items() if v['heldOutIoU'] is not None},
                                    'colourError': [r['modelBefore']['colourErrorMean'], r['modelAfter']['colourErrorMean']]}
                             for name, r in objects.items()}}
    skill = _parse_skill(REPO / 'manuals/cl/laya-3d-image.cl')
    summary['checks'] = [{'name': c.name, 'passed': bool(_Expr(c.expr, {'proof': summary}, {}).run())} for c in skill.checks]
    save(OUT / 'summary.json', summary)
    return summary


def main():
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--objects', default=','.join(OBJECTS))
    parser.add_argument('--port', type=int, default=None, help='default 49107, or the first pair of --port-block')
    parser.add_argument('--summary-only', action='store_true')
    parser.add_argument('--out', type=Path, default=None, help='results folder; sheets are always read from the Kronos folder')
    from grant_agent.assigned_ports import add_arguments, apply, choose_port, state, under
    add_arguments(parser)
    args = parser.parse_args(); apply(args, 'CORE')
    OUT = args.out or under('laya-3d/kronos/out', OUT); args.port = choose_port(args.port, 49107)
    if args.summary_only:
        summary = summarize(state('laya3d/run')); print(json.dumps({k: v for k, v in summary.items() if k != 'perObject'}, indent=1)); return
    run = OUT / 'run'; harness = Harness(run, port=args.port)
    previous = OUT / 'results.json'
    results = json.loads(previous.read_text(encoding='utf-8'))['objects'] if previous.exists() else {}
    try:
        project = run / 'blender'; (project / 'inputs').mkdir(parents=True, exist_ok=True)
        for sheet in KRONOS.glob('sheet-*.png'): shutil.copy2(sheet, project / 'inputs' / sheet.name)
        started = time.perf_counter()
        session = harness.launch('blender', project, ['--background', '--factory-startup', '--python',
                                                       str(REPO / 'scripts/gamedev/blender/laya3d_background.py'), '--', str(project)])
        startup = time.perf_counter() - started
        from grant_agent import scene_core
        from grant_agent.scene_core.image_model import next_edit, program
        for name in args.objects.split(','):
            spec = {**OBJECTS[name], 'object': name}
            began = time.perf_counter()
            source = {'root': str(harness.state), 'domain': 'laya3d', 'sessionId': session, '_allowBuild': True,
                      'sheet': str(project / 'inputs' / spec['sheet']), 'spec': spec}
            before = scene_core.transcribe('laya3d', source)
            steps = []
            while next_edit(source) is not None:
                edit = next_edit(source)[1]
                outcome = scene_core.improve('laya3d', source, {'max_steps': 1, 'max_seconds': 240, 'allowed_fixes': ['shape.refit'],
                                                                'guards': {'outline_iou_mean': 'min'}},
                                             root=harness.state)
                if not outcome['steps']: break
                step = outcome['steps'][-1]
                steps.append({'edit': edit,
                              'status': step['status'], 'findingsBefore': len(outcome['verdict']['findings']), 'receipt': outcome['receipt']})
            after = scene_core.transcribe('laya3d', source)
            seconds = time.perf_counter() - began
            directory = Path(source['_directory']); destination = OUT / name; destination.mkdir(parents=True, exist_ok=True)
            (destination / 'retained.cl').write_text(source['_program'], encoding='utf-8')
            asset = harness.action(session, 'export', {'path': str(directory / (name + '.glb'))})
            shutil.copy2(asset['path'], destination / (name + '.glb'))
            observation = source['_observation']
            cameras = {v['view']: v['camera'] for v in observation['views']}
            cameras['present'] = present_camera(observation)
            renders = {}
            for label, text in (('before', program(observation, {})), ('after', source['_program'])):
                harness.action(session, 'shape_program', {'program': text})
                for colour in (True, False):
                    shot = harness.action(session, 'canonical', {'path': str(directory / 'present' / (label + ('-colour' if colour else '-shape'))),
                                                                  'collection': 'LAYA shape program', 'framing': {'center': [0, 0, 0], 'size': 2.56},
                                                                  'views': list(cameras), 'cameras': cameras, 'sourceColour': colour,
                                                                  'replace': True, 'allowBlank': True, 'resolution': 256})
                    renders[label + ('-colour' if colour else '-shape')] = {v['view']: v['path'] for v in shot['views']}
            harness.action(session, 'shape_program', {'program': source['_program']})  # leave the retained model live
            rows = [('source cells', [v['path'] for v in observation['views']])]
            rows += [(key, [renders[key][v['view']] for v in observation['views']] + [renders[key]['present']]) for key in renders]
            contact_sheet(rows, destination / 'before-after.png')
            for key, paths in renders.items(): shutil.copy2(paths['present'], destination / (key + '.png'))
            for item in ('eyes/transcription.cl', 'eyes/transcription.json'):
                shutil.copy2(directory / item, destination / Path(item).name)
            view_rows = {n['id']: {'role': n['attributes']['role'], 'cell': n['attributes']['cell'], 'judged': n['kind'] == 'view-measurement',
                                   'beforeIoU': b['measurements']['outlineIoU'], 'afterIoU': n['measurements']['outlineIoU'],
                                   'beforeColourError': b['measurements']['colourError'], 'afterColourError': n['measurements']['colourError'],
                                   'heldOutIoU': observation['heldOutIoU'].get(n['id'])}
                         for b, n in zip(before['nodes'], after['nodes']) if n['kind'] != 'shape-model'}
            results[name] = {'seconds': seconds, 'views': view_rows, 'metricsBefore': before['metrics'], 'metricsAfter': after['metrics'],
                             'modelBefore': before['nodes'][-1]['measurements'], 'modelAfter': after['nodes'][-1]['measurements'],
                             'steps': steps, 'timing': observation['timing'], 'issues': observation['issues'],
                             'program': str(destination / 'retained.cl'), 'asset': str(destination / (name + '.glb')),
                             'modelPath': str(directory / 'model.json'), 'options': source['_options']}
            save(OUT / 'results.json', {'blenderStartupSeconds': startup, 'objects': results})
            print(name, round(seconds, 1), 'mean IoU', before['metrics']['outline_iou_mean'], '->', after['metrics']['outline_iou_mean'],
                  'colour', before['metrics']['colour_error_mean'], '->', after['metrics']['colour_error_mean'],
                  [s['status'] for s in steps], flush=True)
        summary = summarize(harness.state)
        print(json.dumps({k: v for k, v in summary.items() if k != 'perObject'}), flush=True)
    finally:
        harness.close()


if __name__ == '__main__': main()
