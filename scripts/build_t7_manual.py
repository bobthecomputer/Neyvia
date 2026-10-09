"""Build the backend-owned executable sidebar manual from its live tool schemas."""
import json
import sys
from pathlib import Path
repo = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo / 'src'))
from grant_agent.neyvia_sidebar import DEFINITIONS, IDS
from grant_agent.manual_contracts import obj

actions, schemas = {}, {}
for name, description, props, required in DEFINITIONS:
    tool = 'neyvia.' + name
    schemas[tool] = {'type': 'object', 'properties': props, 'required': required}
    actions[name] = {'tool': tool, 'schema': tool, 'returns': {'type': 'object', 'properties': {'previewId': {'type': 'string'}, 'undoId': {'type': ['string', 'null']}}},
                     'pre': 'Authenticated owner and readable local conversations; confirmation uses an unchanged preview',
                     'effect': description, 'reversible': True}
manual = {'schema': 'neyvia.manual.v1', 'id': 'sidebar', 'kind': 'environment', 'schemas': schemas,
 'chapters': {'overview': {
  'title': 'Actual agent trees, event lanes and reversible semantic subject folders',
  'state': {'current': {'tool': 'neyvia.sidebar.state', 'args': {'ids': {'$input': 'ids'}}, 'inputs': obj({'ids': IDS}),
                      'shape': {'type': 'object', 'required': ['sessions', 'subjectFolders', 'errors']}}},
  'actions': actions,
  'checks': {'observed': {'tool': 'neyvia.sidebar.state', 'args': {'ids': {'$input': 'ids'}}, 'expect': {'path': 'ok', 'op': 'eq', 'value': True}}},
  'procedures': {
   'preview-subjects': {'goal': 'Observe actual conversations and preview semantic subject groups without moving them',
      'inputs': obj({'ids': IDS}), 'steps': [
       {'action': 'sidebar.state', 'args': {'ids': {'$input': 'ids'}}, 'save': 'observed', 'check': 'observed'},
       {'action': 'sidebar.preview', 'args': {'ids': {'$input': 'ids'}}, 'save': 'preview'}, {'judge': 'review'}]},
   'confirm-preview': {'goal': 'Apply a reviewed preview exactly once; stop on stale or active conversations',
      'inputs': obj({'previewId': {'type': 'string'}}), 'steps': [
       {'action': 'sidebar.confirm', 'args': {'previewId': {'$input': 'previewId'}, 'confirmed': True}, 'save': 'receipt'}]},
   'undo-grouping': {'goal': 'Restore prior assignments while preserving later moves',
      'inputs': obj({'undoId': {'type': 'string'}}), 'steps': [
       {'action': 'sidebar.undo', 'args': {'undoId': {'$input': 'undoId'}}, 'save': 'receipt'}]}},
  'judge': {'review': {'question': 'Do the proposed groups describe the same work?', 'options': ['accept', 'keep'],
                     'constraints': 'Compare actual prompts and semantic scores; use confirm-preview only after the owner accepts. Never move during preview.'}},
  'pitfalls': [
   {'failure': 'model_unavailable', 'recovery': 'Run scripts/setup_t7_embeddings.py in this worktree; bounded pinned model only, no package install'},
   {'failure': 'stale_preview', 'recovery': 'Observe again and create a fresh preview; do not retry changed intent as confirmed'},
   {'failure': 'Incomplete transcript', 'recovery': 'Keep Other; completeness and read errors are exposed, never guess from title or age'}],
  'frontier': ['Collapsed rail and rendered controls belong to the UI handoff', 'English embedding model; French semantic quality is unmeasured', 'Subject folders are sidebar overlays, not disk directories'],
  'guidance': ['Images requires an actual generation event; Quick requires a complete transcript with fewer than three user turns', 'CPU only; no runtime network or automatic downloads', 'Undo survives restart and never overwrites a later move']}}}
(repo / 'manuals/sidebar.manual.json').write_text(json.dumps(manual, indent=2)+'\n', encoding='utf-8')
