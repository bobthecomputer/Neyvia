"""Exact Apple build, preview-state and dormant cloud effects for canonical CL."""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
from ..apple_targets import TARGETS, latest, verify
from .effects import _bus

SUPPORTED = {'neyvia.mobile.build', 'neyvia.mobile.preview', 'neyvia.mobile.simulate'}


def readonly(name, args):
    if name == 'neyvia.mobile.install' and args.get('target') in ('iphone','ipad','mac'):
        return True
    if name == 'neyvia.mobile.simulate' and args.get('tier') == 'device':
        return True
    if name == 'neyvia.mobile.build' and args.get('platform') in ('watchos','tvos','visionos'):
        return True
    return None


def _root(protocol, args):
    from ..neyvia_mobile_studio import _project
    from ..neyvia_workspace_tools import workspace_for
    return _project(workspace_for(protocol.gateway.root), args)


def snapshot_for(protocol, name, args):
    root = _root(protocol, args)
    return {'project': str(root), 'before': deepcopy(_bus(protocol).get('app:mobile-studio', {})),
            'receipt': latest(root, args.get('platform', 'ios')).get('receiptPath')}


def _preview(protocol, args, expected):
    from ..neyvia_mobile_studio import project_info, _preview
    from ..neyvia_workspace_tools import workspace_for
    service = workspace_for(protocol.gateway.root)
    saved = service.bus.get('app:mobile-studio', {})
    if any(saved.get(key) != value for key, value in expected.items()):
        return False
    root = _root(protocol, args)
    fresh = _preview(service, root, project_info(root))
    return bool(fresh.get('ready') and fresh.get('url'))


def _verify(protocol, name, args, value, before):
    root = _root(protocol, args)
    if str(root) != before['project']:
        return False
    if name == 'neyvia.mobile.build':
        target = args['platform']
        job = value.get('job', {})
        receipt = latest(root, target)
        if job.get('status') != 'done' or job.get('platform') != target or job.get('project') != str(root):
            return False
        if job.get('receipt') != receipt.get('receiptPath') or job.get('receipt') == before['receipt']:
            return False
        return receipt.get('status') == 'completed' and verify(root, target)['ok'] is True
    if name == 'neyvia.mobile.preview':
        expected = {key: args[key] for key in ('device','orientation','dark','textScale','keyboard') if key in args}
        if args.get('project'): expected['project'] = str(root)
        return _preview(protocol, args, expected)
    tier, target = args['tier'], args.get('platform','ios')
    if tier == 'instant':
        return _preview(protocol,args,{'project':str(root),'device':TARGETS[target]['device']})
    if tier == 'cloud' and args.get('results'):
        fresh = _bus(protocol).get('app:mobile-studio', {}).get('cloudResult', {})
        image = Path(fresh.get('screenshotPath',''))
        image.resolve().relative_to((root/'.agent_control/apple_cloud/imports').resolve())
        receipt = json.loads(image.with_name('cloud-outcome.json').read_text())
        from ..windows_ios_compiler import _file_sha256
        return fresh.get('project') == str(root) and _file_sha256(image) == receipt['screenshotSha256'] and fresh.get('runUrl') == value.get('runUrl')
    if tier == 'cloud':
        path = Path(value.get('path','')).resolve()
        path.relative_to((root/'.agent_control/apple_cloud').resolve())
        capsule = json.loads((path/'capsule.json').read_text())
        from ..windows_ios_compiler import _file_sha256
        return (value.get('enabled') is False and value.get('dispatched') is False and capsule.get('enabled') is False
                and all((path/key).is_file() and _file_sha256(path/key) == digest for key,digest in capsule['files'].items()))
    return False


def checks_for(protocol, name, args):
    if name not in SUPPORTED or readonly(name,args):
        return []
    if name == 'neyvia.mobile.build' and (args.get('platform') not in {'ios','ipados','macos'} or not args.get('waitSeconds')):
        return []  # No asynchronous admission is presented as a completed build.
    root = str(_root(protocol,args))
    # All frame selections replace the same preview subject, including a
    # manual preview followed by instant simulation. Cloud/build are separate.
    subject = ('preview' if name.endswith('.preview') or args.get('tier') == 'instant' else
               'cloud-import' if args.get('results') else 'cloud-prepare' if args.get('tier') == 'cloud' else 'build')
    subject_key = 'apple:'+root+':'+subject
    if subject in {'build','cloud-prepare'}: subject_key += ':'+str(args.get('platform','ios'))
    return [{'name':'effect-apple-'+name.split('.')[-1], 'observer':True, 'effect':True,
             'observerTool':'neyvia.mobile.status', 'subject':dict(args),
             'subjectKey':subject_key,
             'expectation':'Fresh target-bound artifact hashes or retained preview state; cloud remains undispatched',
             'check':lambda arguments,value,before:_verify(protocol,name,arguments,value,before)}]
