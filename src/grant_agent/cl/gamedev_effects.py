"""Project package and affinity-bound native request observers for CL."""
from .effects import _call

SUPPORTED = {'neyvia.gamedev.setup', 'neyvia.gamedev.action'}
READS = {'neyvia.gamedev.project_status', 'neyvia.gamedev.receipt', 'neyvia.gamedev.receipts', 'neyvia.gamedev.status', 'neyvia.gamedev.state'}


def readonly(name, args):
    return True if name in READS else None


def snapshot_for(protocol, name, args):
    if name.endswith('.setup'):
        return _call(protocol, 'neyvia.gamedev.project_status', args)
    return _call(protocol, 'neyvia.gamedev.sessions', {})


def checks_for(protocol, name, args):
    def verify(arguments, value, previous):
        if name.endswith('.setup'):
            fresh = _call(protocol, 'neyvia.gamedev.project_status', arguments)
            return fresh['configured'] and fresh['engine'] == arguments['engine'] and fresh['projectPath'] == value.get('projectPath')
        identity = arguments.get('requestId') or value.get('requestId')
        if not identity:
            return False
        fresh = _call(protocol, 'neyvia.gamedev.receipt', {'requestId': identity})
        if (fresh.get('sessionId') != arguments['sessionId'] or fresh.get('action') != arguments['action']
                or fresh.get('args') != arguments.get('args', {})):
            return False
        if fresh['status'] in {'queued', 'running'}:
            return None
        return fresh['status'] == 'succeeded'
    return [{'name': 'native-project-effect', 'observer': True, 'effect': True,
             'deferred': name.endswith('.action'), 'subjectKey': name + ':' + str(args.get('requestId') or args.get('projectPath')),
             'subject': dict(args), 'observerTool': 'neyvia.gamedev.receipt' if name.endswith('.action') else 'neyvia.gamedev.project_status',
             'expectation': 'Fresh package hashes or exact native completed operation; queue admission is pending',
             'check': verify}]
