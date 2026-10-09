"""Native Godot/Unity Scene adapter journeys; private headless editors, no installs.

Each engine: register an Edit bridge session, transcribe a seeded scene with native
facts, judge it with the shared core, then scene.improve with engine.scale only.
"""
import argparse
import json
import os
from pathlib import Path
import time
from laya3d_harness import Harness
from laya3d_contracts import save

SEEDED={'wrong-scale':'Subject','missing-collider':'MissingCollider'}
GODOT_SCENE='''[gd_scene load_steps=2 format=3]

[sub_resource type="BoxMesh" id="Box"]

[node name="Root" type="Node3D"]

[node name="Subject" type="MeshInstance3D" parent="."]
mesh = SubResource("Box")
transform = Transform3D(2, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0)

[node name="MissingCollider" type="Node3D" parent="."]
metadata/laya_requires_collider = true

[node name="BrokenShape" type="CollisionShape3D" parent="."]
'''
UNITY_SEED='''using UnityEngine; using UnityEditor; using UnityEditor.SceneManagement;
[InitializeOnLoad] public static class Laya3DSeed {
 static Laya3DSeed(){EditorApplication.delayCall+=Seed;}
 static void Seed(){
  if(System.IO.File.Exists("Assets/Laya3D.unity")){if(EditorSceneManager.GetActiveScene().path!="Assets/Laya3D.unity")EditorSceneManager.OpenScene("Assets/Laya3D.unity");return;}
  var scene=EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);
  var subject=GameObject.CreatePrimitive(PrimitiveType.Cube);subject.name="Subject";subject.transform.localScale=new Vector3(2,1,1);
  var missing=new GameObject("MissingCollider");missing.AddComponent<Rigidbody>();
  var broken=new GameObject("BrokenMesh");broken.AddComponent<MeshFilter>();broken.AddComponent<MeshRenderer>();
  EditorSceneManager.SaveScene(scene,"Assets/Laya3D.unity");}
}'''


def installed_unity():
    from grant_agent.neyvia_gamedev import installed_editor
    return installed_editor('unity')


def prepare(engine,project):
    if engine=='godot':
        (project/'project.godot').write_text('config_version=5\n\n[application]\n\nconfig/name="LAYA3D private contract"\nrun/main_scene="res://scene.tscn"\n\n[editor_plugins]\n\nenabled=PackedStringArray("res://addons/neyvia_bridge/plugin.cfg")\n\n[rendering]\n\nrenderer/rendering_method="gl_compatibility"\n',encoding='utf-8')
        (project/'scene.tscn').write_text(GODOT_SCENE,encoding='utf-8')
        return ['--headless','--editor','--path',str(project),'res://scene.tscn'],{**SEEDED,'broken-reference':'BrokenShape'}
    (project/'Assets/Editor').mkdir(parents=True,exist_ok=True)
    (project/'Packages').mkdir(exist_ok=True)
    # Deliberately minimal: the bridge package must declare the modules it compiles against.
    (project/'Packages/manifest.json').write_text('{"dependencies":{}}',encoding='utf-8')
    # Without ProjectVersion.txt Unity treats the folder as a new project, switches UPM to
    # updateDependencies, adds the whole default template set and downloads registry
    # packages (run2: purchasing alone took 189 s), so registration missed its deadline.
    (project/'ProjectSettings').mkdir(exist_ok=True)
    (project/'ProjectSettings/ProjectVersion.txt').write_text('m_EditorVersion: '+Path(installed_unity()).parents[1].name+'\n',encoding='utf-8')
    (project/'Assets/Editor/Laya3DSeed.cs').write_text(UNITY_SEED,encoding='utf-8')
    return ['-batchmode','-nographics','-disableManagedDebugger','-projectPath',str(project),'-logFile',str(project/'editor.log')],{**SEEDED,'broken-reference':'BrokenMesh'}


def run(harness,engine,project):
    from grant_agent import scene_core
    arguments,expected=prepare(engine,project)
    timings={}; started=time.perf_counter()
    session=harness.launch(engine,project,arguments)
    timings['registration']=time.perf_counter()-started
    source={'root':str(harness.state),'domain':engine,'sessionId':session,'targets':{'unitScale':True}}
    deadline=time.monotonic()+(300 if engine=='unity' else 120)
    while True:
        try:
            before=scene_core.transcribe(engine,source)
            if any(n['id'].split('/')[-1]=='Subject' for n in before['nodes']): break
        except RuntimeError as exc:
            if 'Open a scene' not in str(exc): raise
        if time.monotonic()>deadline: raise RuntimeError('Seeded native scene did not open')
        time.sleep(.5)
    timings['sceneReady']=time.perf_counter()-started
    verdict=scene_core.judge(before,root=harness.state)
    found={(f['predicate'],f['node'].split('/')[-1]) for f in verdict['findings']}
    t=time.perf_counter()
    outcome=scene_core.improve(engine,source,{'max_steps':2,'max_seconds':120,'allowed_fixes':['engine.scale'],'guards':{}},root=harness.state)
    timings['improve']=time.perf_counter()-t
    after=scene_core.transcribe(engine,source)
    remaining={(f['predicate'],f['node'].split('/')[-1]) for f in scene_core.judge(after,root=harness.state,record=False)['findings']}
    subject=next(n for n in after['nodes'] if n['id'].split('/')[-1]=='Subject')
    gates={'registeredEdit':True,
           'nativeFacts':all(isinstance(n.get('measurements'),dict) for n in before['nodes']) and len(before['nodes'])>=len(expected),
           'seededFound':{name:(name,node) in found for name,node in expected.items()},
           'falsePositives':sorted(f'{p}:{n}' for p,n in found if (p,n) not in set(expected.items())),
           'scaleKept':[s['status'] for s in outcome['steps']][:1]==['kept'] and subject['attributes']['scale']==[1,1,1],
           'reviewOnlyRemain':sorted(f'{p}:{n}' for p,n in remaining)}
    timings['total']=time.perf_counter()-started
    return {'session':session,'gates':gates,'before':before,'verdict':verdict,'upgrade':outcome,'after':after,
            'seconds':timings['total'],'timings':timings}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=None,help='default D:/NeyviaRuns/laya3d/engines (or <scratch>/laya3d/engines)')
    parser.add_argument('--engines',default='godot,unity')
    parser.add_argument('--suffix',default='-run2',help='fresh project folder suffix; earlier projects stay as evidence')
    parser.add_argument('--port',type=int,default=None,help='default 49105, or the first pair of --port-block')
    from grant_agent.assigned_ports import add_arguments,apply,choose_port,under
    add_arguments(parser)
    args=parser.parse_args(); apply(args,'CORE')
    root=args.root or under('laya3d/engines',Path('D:/NeyviaRuns/laya3d/engines')); args.port=choose_port(args.port,49105)
    godot=next(Path(os.environ['LOCALAPPDATA']).glob('Microsoft/WinGet/Packages/GodotEngine.GodotEngine_*/Godot*_console.exe'))
    os.environ['NEYVIA_GAMEDEV_GODOT']=str(godot)
    harness=Harness(root,port=args.port)
    path=root/'results.json'
    results=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    results={k:v for k,v in results.items() if isinstance(v,dict) and 'gates' in v}  # earlier failures stay in logs
    try:
        harness.tool('neyvia.manual.load',{'id':'game-dev','chapter':'bridges'})
        for engine in args.engines.split(','):
            project=root/(engine+args.suffix); project.mkdir(parents=True,exist_ok=True)
            started=time.perf_counter()
            try:
                results[engine]=run(harness,engine,project)
            except Exception as exc:
                results[engine]={'error':f'{type(exc).__name__}: {exc}','seconds':time.perf_counter()-started,'project':str(project)}
            save(path,results)
            print(engine,json.dumps(results[engine].get('gates',results[engine])),round(results[engine]['seconds'],1),flush=True)
        results['roblox']={'executed':False,'seconds':0,
                           'reason':'Roblox Studio is not installed (winget hash check failed; install not bypassed or retried). '
                                    'Observer and plugin code only; no Roblox fact is claimed.'}
        save(path,results)
    finally: harness.close()


if __name__=='__main__': main()
