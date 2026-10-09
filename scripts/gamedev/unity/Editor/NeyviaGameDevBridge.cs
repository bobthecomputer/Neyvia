using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.SceneManagement;

namespace Neyvia.GameDev
{
    [InitializeOnLoad]
    public static class NeyviaGameDevBridge
    {
        [Serializable] class Config { public string httpUrl, token, projectPath; }
        [Serializable] class Args { public string path, component, property, value, source, expectedSha256, mode; public float[] vector; public bool save; }
        [Serializable] class Request { public string requestId, action; public Args args; }
        [Serializable] class Response { public bool ok; public Data data; }
        [Serializable] class Data { public string sessionId; public Request request; }
        [Serializable] class Register { public string engine="unity", projectPath, context="Edit", clientId; public string[] capabilities; }
        [Serializable] class Poll { public string sessionId; public bool busy; }
        [Serializable] class Completion { public string sessionId, requestId, status, error; public Result result; }
        [Serializable] public class Result { public string engineVersion, scene, state, path, sha256, source; public string[] objects, components, console; public float[] position; public int passed, failed, skipped; public string schema,domain,surface; public NeyviaSceneObserver.Node[] nodes; public bool truncated; }
        const string PendingKey = "Neyvia.GameDev.Pending", SessionKey = "Neyvia.GameDev.Session", CompletionKey = "Neyvia.GameDev.Completion";
        static Config config;
        static string session;
        static string clientId;
        static UnityWebRequest network;
        static Action<string> networkDone;
        static double nextPoll, waitUntil;
        static Request active;
        static Completion completion;
        static readonly Queue<string> logs = new Queue<string>();
        static readonly string[] BaseCapabilities = {"inspect", "transcribe", "select", "edit", "reload", "run", "stop", "console", "load_asset"};
        public static Action<string, Action<Result, string>> TestRunner;
        static NeyviaGameDevBridge()
        {
            session = SessionState.GetString(SessionKey, "");
            clientId = SessionState.GetString(SessionKey + ".client", "");
            if (string.IsNullOrEmpty(clientId)) { clientId = Guid.NewGuid().ToString("N"); SessionState.SetString(SessionKey + ".client", clientId); }
            var pending = SessionState.GetString(PendingKey, "");
            if (!string.IsNullOrEmpty(pending)) active = JsonUtility.FromJson<Request>(pending);
            var completed = SessionState.GetString(CompletionKey, "");
            if (!string.IsNullOrEmpty(completed)) completion = JsonUtility.FromJson<Completion>(completed);
            Application.logMessageReceived += (message, stack, kind) => {
                logs.Enqueue(kind + ": " + message); while (logs.Count > 200) logs.Dequeue();
            };
            EditorApplication.update += Tick;
            AssemblyReloadEvents.beforeAssemblyReload += () => { if (network != null) network.Dispose(); };
        }
        static void ReadConfig()
        {
            var project = Path.GetFullPath(Path.Combine(Application.dataPath, ".."));
            var file = Path.Combine(project, ".neyvia", "gamedev-bridge.json");
            if (!File.Exists(file)) return;
            config = JsonUtility.FromJson<Config>(File.ReadAllText(file));
            Uri endpoint;
            if (config == null || !Uri.TryCreate(config.httpUrl, UriKind.Absolute, out endpoint)
                || endpoint.Scheme != "http" || endpoint.Host != "127.0.0.1" || endpoint.Port < 1024 || endpoint.Port == 47881
                || !string.IsNullOrEmpty(endpoint.UserInfo) || !string.IsNullOrEmpty(endpoint.Query) || !string.IsNullOrEmpty(endpoint.Fragment) || endpoint.AbsolutePath != "/"
                || string.IsNullOrEmpty(config.token)
                || !string.Equals(Path.GetFullPath(config.projectPath).TrimEnd(Path.DirectorySeparatorChar), project.TrimEnd(Path.DirectorySeparatorChar), StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Bridge config must target this project and an explicit non-public literal loopback HTTP port");
        }
        static void Send(string endpoint, object body, Action<string> done)
        {
            network = new UnityWebRequest(config.httpUrl + "/api/gamedev/bridge/" + endpoint, "POST");
            network.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(JsonUtility.ToJson(body)));
            network.downloadHandler = new DownloadHandlerBuffer();
            network.SetRequestHeader("Content-Type", "application/json");
            network.SetRequestHeader("Authorization", "Bearer " + config.token);
            network.timeout = 10;
            networkDone = done;
            network.SendWebRequest();
        }
        static void Tick()
        {
            try
            {
                if (network != null)
                {
                    if (!network.isDone) return;
                    var done = networkDone;
                    var valid = network.result == UnityWebRequest.Result.Success;
                    var json = valid ? network.downloadHandler.text : null;
                    network.Dispose(); network = null; nextPoll = EditorApplication.timeSinceStartup + 1;
                    done(json); return;
                }
                if (EditorApplication.timeSinceStartup < nextPoll) return;
                if (config == null) { ReadConfig(); if (config == null) { nextPoll = EditorApplication.timeSinceStartup + 3; return; } }
                if (completion != null)
                {
                    Send("complete", completion, json => { if (json != null && JsonUtility.FromJson<Response>(json).ok) { completion = null; active = null; SessionState.EraseString(PendingKey); SessionState.EraseString(CompletionKey); } }); return;
                }
                if (string.IsNullOrEmpty(session))
                {
                    var capabilities = BaseCapabilities.ToList(); if (TestRunner != null) capabilities.Add("test");
                    Send("register", new Register {projectPath=config.projectPath, capabilities=capabilities.ToArray(), clientId=clientId}, json => {
                        if (json == null) return; var response=JsonUtility.FromJson<Response>(json);
                        if (response.ok && response.data != null) { session=response.data.sessionId; SessionState.SetString(SessionKey, session); }
                    }); return;
                }
                if (active != null)
                {
                    var started=SessionState.GetFloat(PendingKey+".started",(float)EditorApplication.timeSinceStartup);
                    if(EditorApplication.timeSinceStartup-started > (active.action=="test"?600:120)) { Complete(null,"Editor operation exceeded its deadline; inspect native editor state before retrying"); return; }
                    if (active.action == "test" || EditorApplication.isCompiling || EditorApplication.isUpdating || EditorApplication.timeSinceStartup < waitUntil
                        || (active.action == "run" && !EditorApplication.isPlaying) || (active.action == "stop" && EditorApplication.isPlayingOrWillChangePlaymode))
                    {
                        Send("poll",new Poll {sessionId=session,busy=true},json=>{}); return;
                    }
                    Complete(new Result { state=EditorApplication.isPlaying ? "playing" : "idle", console=logs.ToArray() }); return;
                }
                Send("poll", new Poll {sessionId=session}, json => {
                    if (json == null) return; var response=JsonUtility.FromJson<Response>(json);
                    if (!response.ok) { session=""; SessionState.EraseString(SessionKey); return; }
                    // JsonUtility can materialize an empty nested Request for
                    // JSON null. An idle poll must never become an operation.
                    if (response.data != null && response.data.request != null
                        && !string.IsNullOrEmpty(response.data.request.requestId)
                        && !string.IsNullOrEmpty(response.data.request.action)) Execute(response.data.request);
                });
            }
            catch (Exception e) { if (active != null) Complete(null, e.Message); else { Debug.LogWarning("Neyvia bridge: " + e.Message); config=null; nextPoll=EditorApplication.timeSinceStartup+5; } }
        }
        static void Complete(Result result, string error=null)
        {
            completion=new Completion {sessionId=session, requestId=active.requestId, status=error == null ? "succeeded" : "failed", error=error, result=result ?? new Result()};
            SessionState.SetString(CompletionKey,JsonUtility.ToJson(completion));
        }
        public static void FinishTest(Result result, string error) { if(active != null && active.action == "test") Complete(result,error); }
        static string AssetPath(string path)
        {
            if (string.IsNullOrEmpty(path) || !path.Replace('\\','/').StartsWith("Assets/", StringComparison.Ordinal)) throw new ArgumentException("path must be project-relative Assets/...");
            var full=Path.GetFullPath(Path.Combine(config.projectPath,path));
            var root=Path.GetFullPath(Application.dataPath)+Path.DirectorySeparatorChar;
            if (!full.StartsWith(root,StringComparison.OrdinalIgnoreCase)) throw new ArgumentException("Asset path leaves project Assets");
            // Refuse links in all existing parents; the bridge must not write through project junctions.
            for (var parent=full; parent.Length>=root.TrimEnd(Path.DirectorySeparatorChar).Length; parent=Path.GetDirectoryName(parent))
                if ((File.Exists(parent)||Directory.Exists(parent)) && (File.GetAttributes(parent)&FileAttributes.ReparsePoint)!=0) throw new ArgumentException("Linked asset paths are not supported");
            return path.Replace('\\','/');
        }
        static GameObject ObjectAt(string path)
        {
            if (string.IsNullOrEmpty(path)) throw new ArgumentException("Scene object path required");
            var pieces=path.Split('/');
            var roots=SceneManager.GetActiveScene().GetRootGameObjects().Where(o=>o.name==pieces[0]).ToArray();
            if (roots.Length!=1) throw new ArgumentException("Root path missing or ambiguous");
            var current=roots[0].transform;
            foreach(var part in pieces.Skip(1)) { var children=current.Cast<Transform>().Where(t=>t.name==part).ToArray(); if(children.Length!=1)throw new ArgumentException("Child path missing or ambiguous"); current=children[0]; }
            return current.gameObject;
        }
        static string ObjectPath(Transform value) { return value.parent == null ? value.name : ObjectPath(value.parent)+"/"+value.name; }
        static string Hash(string path) { using(var sha=SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(File.ReadAllBytes(path))).Replace("-","").ToLowerInvariant(); }
        static void Execute(Request request)
        {
            active=request; request.args=request.args ?? new Args(); var a=request.args;
            SessionState.SetString(PendingKey,JsonUtility.ToJson(active));
            SessionState.SetFloat(PendingKey+".started",(float)EditorApplication.timeSinceStartup);
            try
            {
                switch(request.action)
                {
                    case "transcribe":
                        var nodes=NeyviaSceneObserver.Observe();
                        Complete(new Result {schema="neyvia.scene.v1",domain="unity",surface="native-editor",nodes=nodes,truncated=nodes.Length==2000}); break;
                    case "inspect":
                        if (!string.IsNullOrEmpty(a.path) && a.path.Replace('\\','/').StartsWith("Assets/",StringComparison.Ordinal))
                        {
                            var inspectedPath=AssetPath(a.path); var inspectedFull=Path.Combine(config.projectPath,inspectedPath);
                            if(!File.Exists(inspectedFull))throw new ArgumentException("Asset file missing");
                            Complete(new Result {path=inspectedPath, sha256=Hash(inspectedFull), source=inspectedPath.EndsWith(".cs",StringComparison.OrdinalIgnoreCase)?File.ReadAllText(inspectedFull):null}); break;
                        }
                        var scene=SceneManager.GetActiveScene(); var objects=scene.GetRootGameObjects().SelectMany(o=>o.GetComponentsInChildren<Transform>(true)).Take(1000).Select(ObjectPath).ToArray();
                        var result=new Result {engineVersion=Application.unityVersion, scene=scene.path, state=EditorApplication.isCompiling?"compiling":EditorApplication.isPlaying?"playing":"idle", objects=objects};
                        if (!string.IsNullOrEmpty(a.path)) { var go=ObjectAt(a.path); result.path=a.path; result.components=go.GetComponents<Component>().Where(c=>c!=null).Select(c=>c.GetType().FullName).ToArray(); var p=go.transform.localPosition; result.position=new[]{p.x,p.y,p.z}; }
                        Complete(result); break;
                    case "select": Selection.activeGameObject=ObjectAt(a.path); Complete(new Result {path=a.path}); break;
                    case "console": Complete(new Result {console=logs.ToArray()}); break;
                    case "edit":
                        if (EditorApplication.isPlayingOrWillChangePlaymode || EditorApplication.isCompiling) throw new InvalidOperationException("Wait for idle Edit mode before editing");
                        if (a.source != null)
                        {
                            var path=AssetPath(a.path); if(!path.EndsWith(".cs",StringComparison.OrdinalIgnoreCase))throw new ArgumentException("Source edits require a .cs path");
                            var full=Path.Combine(config.projectPath,path);
                            if(string.IsNullOrEmpty(a.expectedSha256)||!File.Exists(full)||Hash(full)!=a.expectedSha256)throw new InvalidOperationException("Existing source SHA256 must match expectedSha256");
                            File.WriteAllText(full,a.source,new UTF8Encoding(false)); AssetDatabase.ImportAsset(path); Complete(new Result {path=path,sha256=Hash(full)}); break;
                        }
                        var target=ObjectAt(a.path); var component=target.GetComponents<Component>().FirstOrDefault(c=>c!=null&&(c.GetType().Name==a.component||c.GetType().FullName==a.component));
                        if(component==null)throw new ArgumentException("Component not found");
                        var serialized=new SerializedObject(component); var property=serialized.FindProperty(a.property); if(property==null)throw new ArgumentException("Serialized property not found");
                        Undo.RecordObject(component,"Neyvia component edit");
                        switch(property.propertyType) {
                            case SerializedPropertyType.String: property.stringValue=a.value; break;
                            case SerializedPropertyType.Boolean: property.boolValue=bool.Parse(a.value); break;
                            case SerializedPropertyType.Integer: property.intValue=int.Parse(a.value,System.Globalization.CultureInfo.InvariantCulture); break;
                            case SerializedPropertyType.Float: property.floatValue=float.Parse(a.value,System.Globalization.CultureInfo.InvariantCulture); break;
                            case SerializedPropertyType.Vector3: if(a.vector==null||a.vector.Length!=3)throw new ArgumentException("vector needs three numbers"); property.vector3Value=new Vector3(a.vector[0],a.vector[1],a.vector[2]); break;
                            default: throw new ArgumentException("Property type unsupported: "+property.propertyType);
                        }
                        serialized.ApplyModifiedProperties(); EditorSceneManager.MarkSceneDirty(target.scene);
                        if(a.save && !EditorSceneManager.SaveScene(target.scene))throw new InvalidOperationException("Scene save cancelled or failed");
                        Complete(new Result {path=a.path,state="edited"}); break;
                    case "reload":
                        SessionState.SetString(PendingKey,JsonUtility.ToJson(active)); waitUntil=EditorApplication.timeSinceStartup+1; AssetDatabase.Refresh(); break;
                    case "run":
                    case "stop":
                        SessionState.SetString(PendingKey,JsonUtility.ToJson(active)); waitUntil=EditorApplication.timeSinceStartup+1; EditorApplication.isPlaying=request.action=="run"; break;
                    case "load_asset":
                        var assetPath=AssetPath(a.path); var asset=AssetDatabase.LoadAssetAtPath<GameObject>(assetPath); if(asset==null)throw new ArgumentException("Import a GameObject asset first; glTF requires a project importer");
                        var instance=PrefabUtility.InstantiatePrefab(asset) as GameObject; if(instance==null)throw new InvalidOperationException("Asset instantiation failed"); Undo.RegisterCreatedObjectUndo(instance,"Neyvia load asset"); Selection.activeGameObject=instance; Complete(new Result {path=ObjectPath(instance.transform)}); break;
                    case "test": if(TestRunner==null)throw new InvalidOperationException("Unity Test Framework adapter is not enabled"); TestRunner(a.mode,Complete); break;
                    default: throw new ArgumentException("Unsupported action: "+request.action);
                }
            }
            catch(Exception e) { Complete(null,e.Message); }
        }
    }
}
