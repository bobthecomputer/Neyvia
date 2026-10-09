"""Observe production owner login followed by an actual Neyvia DOM refusal."""
from __future__ import annotations

import argparse
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def exercise_failure_truth(*, backend_url: str, username: str, password: str,
                           failed_tab_id: str, expected_origin: str,
                           category: str = 'unicode', timeout: float = 5) -> dict:
    """The caller supplies its owned real auth server and unavailable native tab.

    No authentication observation is supplied by the caller: the production CLI
    must obtain it over HTTP. Credentials are neither recorded nor read from disk.
    """
    if category not in {'empty','huge','unicode','concurrency','interrupted','permissions','offline','stale'}:
        raise ValueError('Unknown live-control failure category')
    if not username or not password or not failed_tab_id:
        raise ValueError('Explicit ephemeral owner credentials and failed native tab required')
    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('c7d_livecontrol_failure_owner', repo/'scripts/verify_authenticated_live_control.py')
    owner = importlib.util.module_from_spec(spec); spec.loader.exec_module(owner)
    def observe(_index):
        args = argparse.Namespace(neyvia_browser_backend=backend_url, neyvia_browser_tab=failed_tab_id,
                                  url=expected_origin+'/owned', headed=False, timeout=timeout,
                                  browser_transport='neyvia')
        rows, artifacts = owner._run_browser_checks(args, username=username, password=password, summary={})
        login = [row for row in rows if row['checkId']=='browser-account-login']
        dom = [row for row in rows if row['checkId'] in owner.DOM_CHECK_IDS]
        failure = [row for row in rows if row['checkId']=='browser-session']
        if (len(login)!=1 or login[0]['statusCode']!=200 or login[0]['passed'] is not True
                or len(failure)!=1 or failure[0]['passed'] is not False
                or len(dom)!=len(owner.DOM_CHECK_IDS)
                or not all(row['status']=='skipped' and row['measured'] is False and row['passed'] is None for row in dom)):
            raise AssertionError('Actual owner-login/DOM-failure journey lost login or admitted unobserved DOM claims')
        return {'actualOwnerLoginStatus':login[0]['statusCode'], 'completedLoginRetained':True,
                'actualDOMFailure':failure[0]['error'], 'domClaimCount':len(dom), 'anyDOMPass':False,
                'transport':artifacts['transport']}
    if category=='concurrency':
        with ThreadPoolExecutor(max_workers=8) as pool:
            observations=list(pool.map(observe,range(8)))
    else:
        observations=[observe(0)]
    return {'ok':True,'contract':'livecontrol.browser-failure-truth','category':category,
            'observations':observations,'renderedPositiveProof':False,'syntheticLoginPositiveCount':0,
            'boundary':'Actual production HTTP owner login plus actual selected Neyvia DOM refusal; unobserved claims remain skipped'}
