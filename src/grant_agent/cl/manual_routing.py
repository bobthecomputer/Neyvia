"""Current-source owner hints when the release's compiled index has drifted.

These hints select documents, never admit execution. Protocol still loads and
strictly grounds every selected manual against its source, artifact and tools.
"""
from functools import lru_cache
import json
import re


def source_owners():
    from ..neyvia_manuals import catalog_stamp
    stamp = catalog_stamp(include_manifest=True)
    owners = _source_owners_at(stamp)
    return owners if stamp == catalog_stamp(include_manifest=True) else None


@lru_cache(maxsize=2)
def _source_owners_at(stamp):
    from ..neyvia_manuals import REPO, records
    tools, procedures = {}, {}
    try:
        for record in records():
            identity = record['id']
            path = (REPO / record.get('clSource', record['path'])).resolve()
            path.relative_to((REPO / 'manuals').resolve())
            if record.get('clSource'):
                text = path.read_text(encoding='utf-8')
                actions = re.findall(r'^A\s+([\w.-]+)\s*\(', text, re.M)
                names = re.findall(r'^P\s+([\w.-]+)\s*\(', text, re.M)
            else:
                document = json.loads(path.read_text(encoding='utf-8'))
                actions = [row['tool'] for chapter in document['chapters'].values()
                           for row in chapter['actions'].values()]
                names = [name for chapter in document['chapters'].values()
                         for name in chapter['procedures']]
            for name in actions:
                # Core tools such as workspace.write retain their exact name;
                # CL also permits the short spelling of neyvia.* declarations.
                for exact in {name, name if name.startswith('neyvia.') else 'neyvia.' + name}:
                    tools.setdefault(exact, set()).add(identity)
            for name in names:
                procedures.setdefault(identity + '.' + name, set()).add(identity)
        return tools, procedures
    except (OSError, ValueError, KeyError, TypeError):
        return None  # Unknown routing keeps the original complete strict path.
