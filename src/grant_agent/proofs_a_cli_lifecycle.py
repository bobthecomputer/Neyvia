"""Asset import, first-run choices and continuity policy runtime contracts."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from .proofs_a_cli import require
from .proofs_a_cli_scheduler import substitute


def check(identity, args, result):
    if identity == 'a-cli.assets.config':
        allowed = {'model', 'model_reasoning_effort', 'personality', 'approval_policy', 'sandbox_mode', 'service_tier', 'desktop', 'features', 'plugins', 'marketplaces', 'mcpServers', 'projectCount'}
        require(set(result) <= allowed, identity, 'configuration exposed an undeclared field')
        require(all(set(server) == {'name', 'configured', 'hasEnvironment'} for server in result['mcpServers']), identity, 'MCP command or environment content exposed')
        require([server['name'] for server in result['mcpServers']] == sorted(args['config'].get('mcp_servers', {})), identity, 'MCP identity inventory differs')
    elif identity == 'a-cli.assets.audit':
        require(result['counts']['personalSkills'] == len(result['personalSkills']) and result['counts']['systemSkills'] == len(result['systemSkills']) and result['counts']['enabledPlugins'] == sum(plugin['enabled'] for plugin in result['plugins']), identity, 'asset inventory counts differ')
        require(all(skill['scope'] == 'system' and not skill['importEligible'] for skill in result['systemSkills']), identity, 'system skill became import eligible')
    elif identity == 'a-cli.assets.import':
        path = Path(result['catalogPath'])
        require(path.resolve().is_relative_to(args['self'].import_root.resolve()) and hashlib.sha256(path.read_bytes()).hexdigest() == result['catalogSha256'], identity, 'import catalog digest or scoped destination differs')
        catalog = json.loads(path.read_text(encoding='utf-8'))
        require(result['secretsImported'] is False and result['rawSessionsImported'] is False and result['importedSkillCount'] == len(catalog['importedSkills']) and result['linkedPluginSkillCount'] == len(catalog['linkedPluginSkills']), identity, 'import receipt overstated safe content')
        require(all(skill['enabled'] is False and Path(skill['source']['path']).is_file() for skill in catalog['importedSkills']), identity, 'personal skill activated before review or source missing')
        from .codex_import import SENSITIVE_NAME_PARTS
        copied = Path(result['snapshotRoot']) / 'skills'
        require(not any(any(word in item.relative_to(copied).as_posix().lower() for word in SENSITIVE_NAME_PARTS) for item in copied.rglob('*') if item.is_file()), identity, 'sensitive filename copied into skills')
    elif identity == 'a-cli.setup.state':
        from .progressive_setup import _state_path
        require(json.loads(_state_path(Path(args['root'])).read_text(encoding='utf-8')) == result, identity, 'first-run choices were not persisted')
    elif identity == 'a-cli.setup.view':
        require(result['shellCanOpen'] is True and result['resumable'] is True and len(result['stages']) == 3 and result['stages'][1]['continueWithoutAny'] is True, identity, 'optional setup blocked shell')
        blocked = [item['itemId'] for item in result['stages'][0]['items'] if item['requiredForMission'] and item['status'] != 'ready']
        require(result['blockingItemIds'] == blocked and result['missionCanStart'] == (not blocked), identity, 'mission readiness does not follow essential requirements')
        require(all(item['selected'] == (item['itemId'].removeprefix('runtime:') not in result['state']['skippedRuntimeIds']) for item in result['stages'][1]['items']), identity, 'skipped runtime selection restored incorrectly')
    elif identity == 'a-cli.continuity.attempt':
        record = result['record']; key = str(args['idempotency_key']).strip()
        if result['duplicateSuppressed']:
            require(key and key in record['completedIdempotencyKeys'], identity, 'duplicate suppressed without durable completed key')
        elif args['outcome'] in {'completed', 'succeeded', 'verified'} and key:
            require(key in record['completedIdempotencyKeys'] and record['latestSafeCheckpoint']['idempotencyKey'] == key and record['latestSafeCheckpoint']['evidence'] == (args['evidence'] or {}), identity, 'successful tool attempt lost duplicate protection or evidence')
    elif identity == 'a-cli.continuity.recovery':
        if result['status'] != 'missing':
            require(isinstance(result['duplicateProtection'], list), identity, 'restart omitted completed action identities')
    elif identity == 'a-cli.continuity.verification':
        kind = str(args['action'].get('kind') or args['action'].get('action') or '').lower()
        if 'transfer' in kind or 'copy' in kind:
            require(result['checks'] == ['target_exists', 'size_or_hash_matches'], identity, 'file transfer verification omitted existence or integrity')
    elif identity == 'a-cli.continuity.gpu-label':
        text = ' '.join(str(args['control_label'] or '').lower().split())
        groups = [('delete_instance', ('delete','destroy','remove','wipe')), ('stop_instance', ('stop','close','terminate','shut down','shutdown','release')), ('resume_instance', ('resume','continue')), ('start_instance', ('start','launch','create','allocate'))]
        expected = next((action for action, words in groups if any(word in text for word in words)), 'inspect_gpu')
        require(result == expected, identity, 'GPU control label changed action authority')
    elif identity == 'a-cli.continuity.gpu':
        proposal, observed, policy = args['proposal'], args['observed'], result['policy']
        action = str(proposal.get('action') or proposal.get('kind') or '').lower()
        require(result['allowed'] == (not result['blockers']), identity, 'GPU blockers did not govern permission')
        require(result['preferResume'] == bool(policy['preferExistingCheckpoint'] and observed.get('validCheckpoint')), identity, 'existing checkpoint preference lost')
        paid = action in {'start','start_instance','allocate_gpu','resume','resume_instance','resume_training','continue_training'} and bool(proposal.get('paid', True))
        destructive = any(word in action for word in ('delete','destroy','wipe'))
        require(result['approvalRequired'] == bool(paid and policy['requireApprovalForPaidStart'] or destructive and policy['requireApprovalForDestructiveAction']), identity, 'GPU paid/destructive authority bypassed')
        if action in {'start','start_instance','allocate_gpu'}:
            capacity = int(observed.get('runningInstances') or 0) >= int(policy['maxConcurrentInstances'])
            price = policy.get('maxEstimatedHourlyCost') is not None and proposal.get('estimatedHourlyCost') is not None and float(proposal['estimatedHourlyCost']) > float(policy['maxEstimatedHourlyCost'])
            require(not (capacity or price) or not result['allowed'], identity, 'GPU capacity/cost limits allowed start')
        override = proposal.get('urgent') or proposal.get('stateChangeExpected') or observed.get('stateChangeExpected')
        if action in {'inspect','inspect_gpu','observe','observe_gpu','poll','poll_gpu','status'}:
            rapid = observed.get('secondsSinceLastObservation') is not None and float(observed['secondsSinceLastObservation']) < float(policy['minObservationIntervalSeconds'])
            unchanged = int(observed.get('consecutiveUnchangedObservations') or 0) >= int(policy['maxConsecutiveUnchangedObservations'])
            require(result['pollBackoffRequired'] == bool(not override and (rapid or unchanged)), identity, 'GPU observation backoff ignored state-change exception')


def procedure(root, goal, rejects):
    from .codex_import import CodexAssetImporter, load_latest_codex_import_rows
    from .skills import SkillRegistry
    from .skill_library import SkillLibrary
    from .mission_control import ControlRoomStore
    from .continuity_policy import MissionContinuityStore, proportional_verification, classify_gpu_control_action
    from . import progressive_setup as p
    root = Path(root) / 'asset-lifecycle'; root.mkdir()
    home = root / 'synthetic-codex-home'
    for rel, text in {
        'skills/useful/SKILL.md': '---\nname: useful\ndescription: Bounded local proof.\n---\n',
        'skills/useful/references/guide.md': 'Local guide',
        'skills/useful/secret-token.txt': 'synthetic exclusion marker only',
        'skills/.system/core/SKILL.md': '---\nname: core\ndescription: Core fixture\n---\n',
        'plugins/cache/market/demo/1/.codex-plugin/plugin.json': json.dumps({'name':'demo','version':'1','skills':'./skills/'}),
        'plugins/cache/market/demo/1/skills/plugin/SKILL.md': '---\nname: plugin\ndescription: Linked fixture\n---\n',
        'AGENTS.md': 'Synthetic instructions for local fixture.',
        'config.toml': 'model="fixture-model"\n[plugins."demo@market"]\nenabled=true\n[mcp_servers.private]\ncommand="synthetic-command-marker"\n[mcp_servers.private.env]\nAPI_KEY="synthetic-redaction-marker"\n',
    }.items():
        path = home / rel; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text, encoding='utf-8')
    workspace = root / 'workspace'; workspace.mkdir()
    importer = CodexAssetImporter(workspace, home)
    audit = importer.audit(); serialized = json.dumps(audit)
    goal('a-cli.assets.config', audit['safeConfig']['mcpServers'][0]['name'] == 'private' and 'synthetic-command-marker' not in serialized and 'synthetic-redaction-marker' not in serialized)
    goal('a-cli.assets.audit', audit['counts']['personalSkills'] == 1 and audit['counts']['systemSkills'] == 1 and audit['counts']['enabledPlugins'] == 1)
    receipt = importer.import_assets(); catalog = json.loads(Path(receipt['catalogPath']).read_text())
    rows = load_latest_codex_import_rows(workspace / '.agent_control')
    source = next(row for row in rows if row['originType'] == 'codex_import')
    library = SkillLibrary(workspace, SkillRegistry(Path(__file__).resolve().parents[2] / 'config' / 'skills.json')).build_catalog()
    fast = ControlRoomStore(workspace)._fast_summary_skill_catalog_payload()
    goal('a-cli.assets.import', receipt['importedSkillCount'] == receipt['linkedPluginSkillCount'] == 1 and not receipt['secretsImported'] and any(row['reason'] == 'sensitive_filename' for row in catalog['skippedFiles']) and {row['originType'] for row in rows} == {'codex_import','codex_plugin_link'} and not source['enabled'] and Path(source['source']['path']).exists())
    goal('a-cli.assets.import', library['codexImportSummary']['personalSkillCount'] == library['codexImportSummary']['linkedPluginSkillCount'] == 1 and library['codexImportSummary']['progressiveDisclosure'] and fast['codexImportSummary']['personalSkillCount'] == fast['codexImportSummary']['linkedPluginSkillCount'] == 1 and [row['originType'] for row in fast['userInstalledSkills']] == ['codex_import','codex_plugin_link'])
    setup_catalog = {'entries':[{'runtimeId':'claude-code','label':'Claude Code','state':'available_to_install','usefulFor':'Project code','actions':['install','skip']}], 'optional':True, 'continueWithoutAny':True}
    with substitute(p, 'build_catalog', lambda *args, **kwargs: setup_catalog), substitute(p, 'connection_status', lambda root: {'state':'setup_required','detail':'Controlled absent browser'}):
        initial = p.build_progressive_setup(workspace, provider_presence={'openai':False})
        p.update_first_run_state(workspace, {'goals':['software'], 'permissionsReviewed':True, 'skippedRuntimeIds':['claude-code']})
        resumed = p.build_progressive_setup(workspace, provider_presence={'openai':True})
    goal('a-cli.setup.state', resumed['state']['permissionsReviewed'] and resumed['state']['skippedRuntimeIds'] == ['claude-code'])
    goal('a-cli.setup.view', initial['shellCanOpen'] and len(initial['stages']) == 3 and initial['stages'][1]['continueWithoutAny'] and resumed['missionCanStart'] and not resumed['stages'][1]['items'][0]['selected'])
    store = MissionContinuityStore(root)
    store.create_or_update('continuity', goal='Finish', patch={'status':'running','currentStep':'Transfer'})
    first = store.record_tool_attempt('continuity', tool='file-transfer', idempotency_key='transfer-1', action={'kind':'file_transfer'}, outcome='verified', evidence={'targetExists':True,'sizeMatches':True})
    restarted = MissionContinuityStore(root)
    duplicate = restarted.record_tool_attempt('continuity', tool='file-transfer', idempotency_key='transfer-1', action={'kind':'file_transfer'}, outcome='verified')
    recovery = restarted.recover('continuity')
    goal('a-cli.continuity.attempt', not first['duplicateSuppressed'] and duplicate['duplicateSuppressed'])
    goal('a-cli.continuity.recovery', recovery['status'] == 'resume' and 'transfer-1' in recovery['duplicateProtection'])
    goal('a-cli.continuity.verification', proportional_verification({'kind':'file_transfer'})['checks'] == ['target_exists','size_or_hash_matches'])
    store.create_or_update('gpu', patch={'gpuPolicy':{'maxConcurrentInstances':1,'maxEstimatedHourlyCost':2.,'preferExistingCheckpoint':True}})
    decision = store.evaluate_gpu_action('gpu', {'action':'start_instance','paid':True,'estimatedHourlyCost':1.5}, {'runningInstances':0,'validCheckpoint':True})
    blocked = store.evaluate_gpu_action('gpu', {'action':'start_instance','paid':True,'estimatedHourlyCost':3.}, {'runningInstances':1,'validCheckpoint':False})
    goal('a-cli.continuity.gpu', decision['allowed'] and decision['approvalRequired'] and decision['preferResume'] and not blocked['allowed'] and len(blocked['blockers']) == 2)
    store.create_or_update('observe', patch={'gpuPolicy':{'minObservationIntervalSeconds':15,'maxConsecutiveUnchangedObservations':3}})
    rapid = store.evaluate_gpu_action('observe', {'action':'inspect_gpu'}, {'secondsSinceLastObservation':2,'consecutiveUnchangedObservations':1})
    unchanged = store.evaluate_gpu_action('observe', {'action':'inspect_gpu'}, {'secondsSinceLastObservation':30,'consecutiveUnchangedObservations':3})
    urgent = store.evaluate_gpu_action('observe', {'action':'inspect_gpu','stateChangeExpected':True}, {'secondsSinceLastObservation':2,'consecutiveUnchangedObservations':3})
    goal('a-cli.continuity.gpu', not rapid['allowed'] and rapid['pollBackoffRequired'] and not unchanged['allowed'] and unchanged['pollBackoffRequired'] and urgent['allowed'] and not urgent['pollBackoffRequired'])
    goal('a-cli.continuity.gpu-label', classify_gpu_control_action('Close all GPUs') == 'stop_instance' and classify_gpu_control_action('Resume checkpoint') == 'resume_instance' and classify_gpu_control_action('Inspect instance') == 'inspect_gpu')
