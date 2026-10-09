using System;
using System.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace Neyvia.GameDev
{
    public static class NeyviaSceneObserver
    {
        [Serializable] public class Attributes { public float[] scale; public bool requiresCollider; public string[] materials; }
        [Serializable] public class Measurements { public float scaleError; public int colliderCount, brokenReferences, vertices, triangles; public float lightIntensity; }
        [Serializable] public class Relations { public string parent; }
        [Serializable] public class Node { public string id, kind, certainty="observed"; public Attributes attributes; public Measurements measurements; public Relations relations; }
        static string PathOf(Transform t) => t.parent == null ? t.name : PathOf(t.parent)+"/"+t.name;
        public static Node[] Observe()
        {
            return SceneManager.GetActiveScene().GetRootGameObjects().SelectMany(o=>o.GetComponentsInChildren<Transform>(true)).Take(2000).Select(t=> {
                var go=t.gameObject; var s=t.localScale; var mesh=go.GetComponent<MeshFilter>(); var renderer=go.GetComponent<Renderer>();
                var materials=renderer == null ? Array.Empty<Material>() : renderer.sharedMaterials;
                var light=go.GetComponent<Light>();
                return new Node { id=PathOf(t), kind="GameObject",
                    attributes=new Attributes {scale=new[]{s.x,s.y,s.z},requiresCollider=go.GetComponent<Rigidbody>()!=null,
                        materials=materials.Select(m=>m==null?null:m.name).ToArray()},
                    measurements=new Measurements {scaleError=Mathf.Max(Mathf.Abs(s.x-1),Mathf.Abs(s.y-1),Mathf.Abs(s.z-1)),
                        colliderCount=go.GetComponents<Collider>().Count(c=>c.enabled),
                        brokenReferences=GameObjectUtility.GetMonoBehavioursWithMissingScriptCount(go)+materials.Count(m=>m==null)+(mesh!=null&&mesh.sharedMesh==null?1:0),
                        vertices=mesh!=null&&mesh.sharedMesh!=null?mesh.sharedMesh.vertexCount:0,
                        triangles=mesh!=null&&mesh.sharedMesh!=null?(int)Enumerable.Range(0,mesh.sharedMesh.subMeshCount).Sum(i=>(long)mesh.sharedMesh.GetIndexCount(i))/3:0,
                        lightIntensity=light!=null?light.intensity:0}, relations=new Relations {parent=t.parent==null?"":PathOf(t.parent)}};
            }).ToArray();
        }
    }
}
