"""Declared path classes and outcome ownership from the track/mod registry."""
from collections import Counter, defaultdict
import ast
from fnmatch import fnmatchcase
import json
from pathlib import PurePosixPath
import re


class SymbolOwners:
    """Resolve named Python reexports and inherited methods without importing code.

    An import alone is not an outcome binding. Only the exact symbol named by
    the authored contract follows a reexport or a class's method resolution.
    """
    def __init__(self, repo, files):
        self.repo = repo
        self.modules = {}
        self.parsed = {}
        self.references = {}
        for name in files:
            if name.startswith('src/grant_agent/') and name.endswith('.py'):
                module = name[len('src/'):].removesuffix('.py').replace('/', '.')
                if module.endswith('.__init__'):
                    module = module.removesuffix('.__init__')
                self.modules[module] = name

    def parse(self, module):
        if module in self.parsed:
            return self.parsed[module]
        path = self.repo / self.modules[module]
        try:
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        except (OSError, SyntaxError):
            self.parsed[module] = ({}, {})
            return self.parsed[module]
        names, imports = {}, {}
        package = module if path.name == '__init__.py' else module.rsplit('.', 1)[0]
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names[node.name] = node
            elif isinstance(node, ast.ImportFrom):
                base = package.split('.')[:len(package.split('.')) - node.level + 1] if node.level else []
                target = '.'.join(base + ([node.module] if node.module else []))
                for alias in node.names:
                    imports[alias.asname or alias.name] = target + '.' + alias.name
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports[alias.asname or alias.name.split('.')[0]] = alias.name if alias.asname else alias.name.split('.')[0]
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names[target.id] = node.value
        self.parsed[module] = names, imports
        return self.parsed[module]

    def resolve(self, reference, seen=None):
        seen = set() if seen is None else seen
        if reference in seen:
            return set()
        seen.add(reference)
        parts = reference.split('.')
        for end in range(len(parts), 0, -1):
            module = '.'.join(parts[:end])
            if module not in self.modules:
                continue
            remaining = parts[end:]
            result = {self.modules[module]}
            if not remaining:
                return result
            names, imports = self.parse(module)
            name, *tail = remaining
            if name in imports:
                return result | self.resolve('.'.join([imports[name], *tail]), seen)
            node = names.get(name)
            if isinstance(node, ast.ClassDef) and tail:
                member = next((n for n in node.body if getattr(n, 'name', None) == tail[0]), None)
                if member is None:
                    implementations = set()
                    for base in node.bases:
                        symbol = ast.unparse(base)
                        head, *rest = symbol.split('.')
                        target = imports.get(head, module + '.' + head)
                        inherited = self.resolve('.'.join([target, *rest, *tail]), seen)
                        # Retain every statically declared base that supplies
                        # the method. Unknown/dynamic bases add no coverage.
                        implementations.update(inherited)
                    return result | implementations if implementations else set()
                return result
            if isinstance(node, (ast.Name, ast.Attribute)):
                symbol = ast.unparse(node)
                head, *rest = symbol.split('.')
                target = imports.get(head, module + '.' + head)
                return result | self.resolve('.'.join([target, *rest, *tail]), seen)
            return result if node is not None else set()
        return set()

    def sites(self, text):
        if text in self.references:
            return self.references[text]
        result = set()
        for reference in re.findall(r'\b(?:grant_agent\.)?[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+', text):
            if not reference.startswith('grant_agent.'):
                reference = 'grant_agent.' + reference
            result.update(self.resolve(reference))
        for path, symbol in re.findall(r'(src/grant_agent/[\w/]+)\.py:([\w.]+)', text):
            result.update(self.resolve(path[len('src/'):].replace('/', '.') + '.' + symbol))
        self.references[text] = result
        return result


def classify(path, policy):
    path=str(PurePosixPath(path.replace('\\','/')))
    if path.startswith('/') or ':' in path or '..' in PurePosixPath(path).parts:
        return {'kind':'unknown','reason':'Not a repository-relative path'}
    if (path.startswith('.github/workflows/') and
            PurePosixPath(path).suffix.lower() in {'.yml', '.yaml'}):
        return {'kind':'configuration','reason':'CI workflow configuration; validated by workflow checks'}
    for row in policy.get('noBehaviourGlobs',[]):
        if fnmatchcase(path,row['glob']):return {'kind':'no behaviour','reason':row['reason']}
    for row in policy['generated']:
        if fnmatchcase(path,row['glob']):return {'kind':'generated','generator':row['generator'],'reason':'Covered through its generator'}
    if path in policy.get('noBehaviourPaths',{}):
        return {'kind':'no behaviour','reason':policy['noBehaviourPaths'][path]}
    for prefix,reason in policy['noBehaviourPrefixes'].items():
        if path.startswith(prefix):return {'kind':'no behaviour','reason':reason}
    name=PurePosixPath(path).name;suffix=PurePosixPath(path).suffix.lower()
    if name in policy['noBehaviourNames']:return {'kind':'no behaviour','reason':'Declared metadata or lockfile'}
    if suffix in policy['noBehaviourExtensions']:return {'kind':'no behaviour','reason':'Documentation, binary asset or recorded input'}
    if suffix in policy['behaviourExtensions']:return {'kind':'behaviour','reason':'Executable source or production configuration'}
    return {'kind':'unknown','reason':'No declared path class'}


def model(repo, changed, contracts, sites, *, renames=None):
    """Generic map sentinels never count as a module's product outcomes."""
    policy=json.loads((repo/'config/contract_path_policy.json').read_text(encoding='utf-8'))
    registry=json.loads((repo/'config/neyvia.modules.json').read_text(encoding='utf-8'))
    modules={row['id']:row for row in registry['modules']}
    owners={path:row['id'] for row in modules.values() for path in row['files']}
    outcomes=defaultdict(set)
    for identity,row in contracts.items():
        if identity=='modules.verify-map':continue
        for ref in row.get('checkedAt',[])+row.get('impact',[]):
            # Reexports and inheritance are resolved once by the generator.
            # The release compiler verifies this registry's source currency;
            # selection only joins its compiled outcome ownership with direct
            # authored sites, rather than reparsing Python on every gate.
            for file in sites(ref):
                if file in owners:outcomes[owners[file]].add(identity)
    for module,row in modules.items():
        outcomes[module].update(identity for identity in row.get('outcomeContracts',row.get('contracts',[]))
                                if identity in contracts and identity!='modules.verify-map')
    bindings=repo/'config/contract_module_outcomes.json'
    if bindings.exists():
        for module,identities in json.loads(bindings.read_text(encoding='utf-8')).items():
            if module not in modules:raise ValueError('Outcome binding has no module: '+module)
            unknown=set(identities)-contracts.keys()
            if unknown:raise ValueError('Module names undeclared outcomes: '+str(sorted(unknown)))
            if 'modules.verify-map' in identities:raise ValueError('Module map integrity is not a product outcome: '+module)
            outcomes[module].update(identities)
    classifications={name:classify(name,policy) for name in changed}
    origins={name:row.get('generator',name) for name,row in classifications.items()
             if row['kind'] in {'behaviour','generated','unknown'}}
    for old,new in (renames or {}).items():
        if (old in origins and classifications[old]['kind']=='behaviour'
                and classify(new,policy)['kind']=='behaviour' and not (repo/old).exists()
                and (repo/new).is_file()):
            origins[old]=new
            classifications[old]['ownerPath']=new
    dependencies={file:{dep_file for dep in row['dependencies'] for dep_file in modules[dep]['files']}
                  for row in modules.values() for file in row['files']}
    return {'classes':classifications,'origins':origins,'owners':owners,'outcomes':outcomes,'dependencies':dependencies,
            'counts':dict(Counter(row['kind'] for row in classifications.values()))}


def uncovered_by_module(paths, classes, owners):
    grouped=defaultdict(list)
    for path in paths:
        target=classes[path].get('ownerPath',classes[path].get('generator',path))
        grouped[owners.get(target,'unmapped:'+str(PurePosixPath(target).parent))].append(path)
    return dict(sorted(grouped.items()))


def uncovered_by_surface(paths, classes, owners, modules):
    """Group uncovered paths by their registry-owned manual or product surface.

    This is a report-only view; it does not affect path classes, ownership,
    outcome admission, or coverage. A canonical manual is the narrowest useful
    work unit. Multi-manual modules receive one stable bounded manual-set key.
    """
    if isinstance(modules, dict) and isinstance(modules.get('modules'), list):
        rows = modules['modules']
        module_rows = {row.get('id'): row for row in rows if isinstance(row, dict) and row.get('id')}
    elif isinstance(modules, dict):
        module_rows = {key: value for key, value in modules.items()
                       if isinstance(value, dict)}
    else:
        module_rows = {row.get('id'): row for row in modules
                       if isinstance(row, dict) and row.get('id')}

    def fallback(path):
        parts = PurePosixPath(str(path).replace('\\', '/')).parts
        if len(parts) >= 2 and parts[0] == 'src' and parts[1] == 'grant_agent':
            return 'backend'
        if parts and parts[0] in {'tools', 'connectors', 'plugins'}:
            return 'tools'
        if parts and parts[0] in {'desktop-ui', 'src-tauri', 'rust'}:
            return 'desktop'
        if parts and parts[0] == 'web':
            return 'web'
        return 'unmapped' if not parts else 'unmapped:' + parts[0]

    grouped = defaultdict(set)
    for path in sorted(set(paths)):
        classification = classes.get(path, {})
        target = classification.get('ownerPath', classification.get('generator', path))
        module_id = owners.get(target)
        row = module_rows.get(module_id, {}) if module_id else {}
        canonical = row.get('manual')
        canonical = canonical.strip() if isinstance(canonical, str) else ''
        manuals = []
        declared = row.get('manuals', [])
        if isinstance(declared, str):
            declared = [declared]
        if isinstance(declared, (list, tuple, set)):
            manuals = sorted({value.strip() for value in declared
                              if isinstance(value, str) and value.strip()})
        if canonical:
            group = 'manual:' + canonical
        elif len(manuals) == 1:
            group = 'manual:' + manuals[0]
        elif manuals:
            # Keep labels stable and bounded even if a module spans many manuals.
            visible = manuals[:4]
            suffix = '+%d' % (len(manuals) - len(visible)) if len(manuals) > len(visible) else ''
            group = 'manuals:' + '|'.join(visible) + suffix
        else:
            surface = row.get('ownerSurface')
            group = 'surface:' + surface.strip() if isinstance(surface, str) and surface.strip() else fallback(path)
        grouped[group].add(path)
    return {group: sorted(grouped[group]) for group in sorted(grouped)}
