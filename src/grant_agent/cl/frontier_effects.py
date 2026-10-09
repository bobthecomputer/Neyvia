"""Dispatch additional CL effects to the module that owns each observer.

An absent family stays frontier. Imports are delayed until its action is used so
catalog construction does not import engines or connect to external runtimes.
"""
from __future__ import annotations

from importlib import import_module


_FAMILIES = {
    'comments': 'comments_effects',
    'parallel': 'parallel_effects',
    'memory': 'memory_effects',
    'session': 'frontier_local_effects', 'sidebar': 'frontier_local_effects',
    'folder': 'durable_effects', 'project': 'durable_effects',
    'mission': 'durable_effects', 'nightshift': 'durable_effects',
    'workflow': 'coordination_effects', 'intent': 'coordination_effects',
    'time': 'coordination_effects',
    'manual': 'manual_effects',
    'pdf': 'document_effects', 'scroll': 'document_effects',
    'web': 'document_effects', 'video': 'document_effects',
    'semantic': 'semantic_effects',
    'work': 'work_effects',
    'attention': 'creative_effects', 'situation': 'creative_effects',
    'browser': 'browser_effects',
    'pane': 'renderer_effects',
}

# New owner layers compose with the existing family instead of replacing it.
# Only a module's explicit SUPPORTED set can admit a mutation.
_ADDITIONAL = {
    'agents': ('agents_message_effects',),
    'message': ('agents_message_effects',),
    'host': ('fixcl4_host_effects',),
    'preview': ('fixcl4_media_effects', 'fixcl4_render_effects'),
    'app_sdk': ('fixcl4_browser_sdk_effects', 'fixcl4_render_effects'),
    'view': ('fixcl4_render_effects',),
    'notes': ('fixcl4_render_effects',),
    'notify': ('fixcl4_render_effects',),
    'voice': ('fixcl4_render_effects',),
    'perception': ('fixcl4_browser_sdk_effects', 'fixcl4_render_effects'),
    'browser': ('fixcl4_browser_sdk_effects', 'fixcl4_render_effects', 'renderer_effects'),
    'folder': ('fixcl4_render_effects',),
    'video': ('fixcl4_media_effects', 'fixcl4_render_effects'),
    'conductor': ('fixcl4_service_effects',),
    'native': ('fixcl4_service_effects',),
    'gamedev': ('gamedev_effects', 'fixcl4_service_effects'),
    'settings': ('fixcl4_service_effects',),
    'environment': ('environment_effects',),
    'manual': ('manual_execution_effects', 'manual_projection_effects'),
    **{family: ('configuration_effects',) for family in (
    'dictation', 'efficiency', 'impact', 'time')},
    'onboarding': ('fixcl4_render_effects', 'fixcl4_service_effects', 'configuration_effects'),
    'semantic': ('integrity_effects',),
    'devices': ('device_effects',), 'remote': ('remote_effects',),
    'app': ('app_open_effects',), 'artifact': ('app_open_effects',),
    'session': ('provider_effects',), 'claude': ('provider_effects',),
    'codex': ('fixcl4_host_effects', 'provider_effects'),
    'mission': ('jobs_effects',), 'nightshift': ('jobs_effects',),
    'mobile': ('apple_effects', 'jobs_effects'), 'autopilot': ('fixcl4_service_effects', 'jobs_effects'),
    'evolver': ('fixcl4_evolver_effects', 'fixcl4_service_effects', 'jobs_effects'),
    **{family: ('record_effects',) for family in (
        'behavior', 'experiment', 'experience', 'quality', 'taste',
        'orchestration', 'context')},
    'intelligence': ('fixcl4_evaluation_effects', 'record_effects'),
    'skill': ('fixcl4_media_effects', 'fixcl4_render_effects', 'record_effects'),
    'lab': ('fixcl4_evaluation_effects', 'lab_context_effects', 'record_effects'),
    'context': ('lab_context_effects', 'record_effects'),
}


def _family(name):
    return name.removeprefix('neyvia.').split('.', 1)[0]


def _additional(name):
    for owner in _ADDITIONAL.get(_family(name), ()):
        try:
            yield import_module('.' + owner, __package__)
        except ModuleNotFoundError as exc:
            if exc.name != __package__ + '.' + owner:
                raise


def _module(name):
    if name == 'terminal.exec':
        try:
            return import_module('.terminal_effects', __package__)
        except ModuleNotFoundError as exc:
            if exc.name != __package__ + '.terminal_effects':
                raise
            return None
    if name.startswith(('web.', 'video.', 'semantic.', 'work.', 'attention.', 'situation.')):
        family = name.split('.', 1)[0]
    elif name.startswith('neyvia.'):
        family = name.split('.', 2)[1]
    else:
        return None
    module_name = _FAMILIES.get(family)
    if not module_name:
        return None
    try:
        return import_module('.' + module_name, __package__)
    except ModuleNotFoundError as exc:
        if exc.name != __package__ + '.' + module_name:
            raise
        return None


def _owner(name):
    for module in _additional(name):
        if name in module.SUPPORTED:
            return module
    module = _module(name)
    return module if module is not None and name in module.SUPPORTED else None


def supported(name, args=None):
    return _owner(name) is not None


def snapshot_for(protocol, name, args):
    owner = _owner(name)
    return owner.snapshot_for(protocol, name, args) if owner else None


def checks_for(protocol, name, args):
    owner = _owner(name)
    return owner.checks_for(protocol, name, args) if owner else []


def readonly(name, args):
    """Override legacy `none` metadata only for audited argument shapes."""
    if name == 'work.state':
        # The owner creates its first JSON state file even on a nominal read.
        return False
    if name in {'neyvia.manual.validate', 'neyvia.manual.patches',
                'neyvia.manual.versions', 'neyvia.manual.compiled',
                'neyvia.app_sdk.describe'}:
        return True
    if name == 'neyvia.sidebar.policy' and 'policy' not in args:
        return True
    if name == 'neyvia.sidebar.tidy' and (args.get('dryRun') is True or args.get('confirmed') is not True) and args.get('undoLast') is not True:
        return True
    if name == 'neyvia.session.cluster' and args.get('apply') is not True and not args.get('undoId'):
        return True
    for owner in _additional(name):
        classifier = getattr(owner, 'readonly', None)
        result = classifier(name, args) if classifier else None
        if result is not None:
            return result
    module = _module(name)
    classifier = getattr(module, 'readonly', None) if module else None
    if classifier:
        return classifier(name, args)
    return None
