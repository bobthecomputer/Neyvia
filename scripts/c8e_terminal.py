"""Scope the real private ConPTY shell to disposable profile and history state.

The production ConPTY owner uses a private process desktop and named pipes.
The retained explicit side-port argument is validated but no listener is opened.
Only the shell profile/history environment is changed for this proof.
"""
from pathlib import Path
import json


def install(port, root=None):
    import os
    from c8_scope import assigned_ports
    if port not in assigned_ports() or str(port) != os.environ.get('NEYVIA_C8_TERMINAL_PORT'):
        raise ValueError('C8e terminal reader requires its explicitly assigned task port')
    from grant_agent.private_conpty import PrivateConPTY
    if root is not None:
        root = Path(root).resolve()
        root.relative_to(Path(__file__).resolve().parents[1] / '.agent_control/proofs/C8')
        profile = root / 'c8/terminal-profile'
        scoped_environment = {
            'HOME': str(profile / 'user'), 'USERPROFILE': str(profile / 'user'),
            'APPDATA': str(profile / 'roaming'), 'LOCALAPPDATA': str(profile / 'local'),
        }
        for value in scoped_environment.values():
            Path(value).mkdir(parents=True, exist_ok=True)
        history = profile / 'roaming/PSReadLine-history.txt'
        setup = ("Import-Module PSReadLine; Set-PSReadLineOption -HistorySavePath '"
                 + str(history).replace("'", "''")
                 + "' -HistorySaveStyle SaveNothing -PredictionSource None")
        spawn = PrivateConPTY.spawn
        def scoped_spawn(argv, *values, **options):
            if (Path(options.get('cwd', '')).resolve() != root
                    or Path(argv[0]).stem.lower() not in {'pwsh', 'powershell'}
                    or list(argv[1:]) != ['-NoLogo']):
                raise PermissionError('C8e terminal requires the owned root and original installed PowerShell')
            launched_argv = [argv[0], '-NoLogo', '-NoProfile', '-NoExit', '-Command', setup]
            options['env'] = {**options.get('env', {}), **scoped_environment}
            created = spawn(launched_argv, *values, **options)
            try:
                (root / 'c8/terminal-launch.json').write_text(json.dumps({
                    'pid': created.pid, 'cwd': str(root), 'argv': launched_argv,
                    'scopedEnvironment': scoped_environment, 'historySavePath': str(history),
                    'historySaveStyle': 'SaveNothing', 'predictionSource': 'None',
                    'boundary': 'Actual installed ConPTY shell, task-only profile; no personal profile or history'},
                    indent=2) + '\n', encoding='utf-8')
            except Exception:
                created.terminate(force=True)
                raise
            return created
        PrivateConPTY.spawn = staticmethod(scoped_spawn)
