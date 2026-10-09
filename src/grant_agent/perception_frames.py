"""Compact, revision-bound semantic perception frames."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from .ui_graph import UiGraph, UiNode, diff_graphs

def _now() -> str: return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def _node(node: UiNode) -> dict[str, Any]:
    return {'id':node.id,'role':node.role,'name':node.name,'states':list(node.states),'actions':list(node.actions),'bounds':{'x':node.bounds.x,'y':node.bounds.y,'w':node.bounds.w,'h':node.bounds.h},'revision':node.revision,'source':node.source,'value':node.value}

class PerceptionFrame:
    def __init__(self, graph: UiGraph): self.graph=graph
    def build(self, *, since_revision: int | None = None, node_id: str = '', expected_revision: int | None = None) -> dict[str, Any]:
        if expected_revision is not None and expected_revision != self.graph.revision:
            return {'ok':False,'status':'stale_frame','expectedRevision':expected_revision,'revision':self.graph.revision}
        if since_revision is not None and since_revision > self.graph.revision: return {'ok':False,'status':'future_revision','revision':self.graph.revision}
        rows=[_node(n) for n in self.graph.ls(limit=200)]
        result={'schema':'neyvia.perception_frame.v1','frameId':f'frame_{self.graph.revision}_{self.graph.semantic_hash}','revision':self.graph.revision,'semanticHash':self.graph.semantic_hash,'url':self.graph.url,'title':self.graph.title,'source':self.graph.source,'observedAt':self.graph.observed_at or None,'assembledAt':_now(),'freshnessSeconds':max(0,(datetime.now(timezone.utc)-datetime.fromisoformat(self.graph.observed_at)).total_seconds()) if self.graph.observed_at else None,'nodes':rows,'nodeCount':len(rows),'provenance':{'graphRevision':self.graph.revision,'semanticHash':self.graph.semantic_hash}}
        if node_id:
            node=self.graph.get(node_id)
            if node is None: return {'ok':False,'status':'node_not_found','revision':self.graph.revision,'frameId':result['frameId']}
            result['selectedNode']=_node(node)
        if since_revision is not None and since_revision < self.graph.revision - 1: result['changes']=[]; result['requiresFullRefresh']=True
        elif since_revision is not None and since_revision == self.graph.revision: result['changes']=[]
        else: result['changes']=[{'kind':d.kind,'nodeId':d.node_id,'before':_node(d.before) if d.before else None,'after':_node(d.after) if d.after else None} for d in self.graph.last_delta]
        return result
