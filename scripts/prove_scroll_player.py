"""Production T18 browser + CL 1.1 goals against the generated running feed.

This is a user journey artifact producer, not a Python test suite. The browser
driver is Neyvia's real owned DOM/action session and the app's A1 state bridge.
"""
from pathlib import Path
import argparse
import hashlib
import json
import sys
import time

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from grant_agent.perception_browser import BrowserSessions
import grant_agent
CL_SOURCE=REPO.parent/'nx-integrate-cl'/'src'/'grant_agent'
grant_agent.__path__.append(str(CL_SOURCE))
from grant_agent.cl.goals import evaluate_goal


class ScrollBrowser(BrowserSessions):
    def _scroll(self,sid,name,args=None):
        page=self.sessions[sid]['page']
        page.wait_for_function('!!window.neyviaApp || !!window.SS_LOAD_ERROR',timeout=15000)
        if page.evaluate('() => window.SS_LOAD_ERROR || null'):
            raise ValueError(page.evaluate('() => window.SS_LOAD_ERROR'))
        if name=='state':return page.evaluate('() => JSON.parse(JSON.stringify(window.neyviaApp.state()))')
        if name=='viewport':page.set_viewport_size({'width':390,'height':844});return True
        if name=='checks':return page.evaluate('() => window.neyviaApp.checks()')
        if name=='act':return page.evaluate('p => window.neyviaApp.act(p.name,p.args||{},p.options||{})',args)
        if name=='correct':return page.evaluate('() => window.scrollStudy.correct()')
        if name=='progress':return page.evaluate('() => window.scrollStudy.exportProgress()')
        if name=='import':return page.evaluate('async p => JSON.parse(JSON.stringify(await window.scrollStudy.importProgress(p)))',args)
        if name=='save':return page.evaluate('() => window.scrollStudy.save()')
        if name=='stale':return page.evaluate('async r => {try{await window.neyviaApp.act("seeNow",{}, {expectedRevision:r});return {refused:false};}catch(e){return {refused:true,error:e.message};}}',args)
        if name=='reload':page.reload(wait_until='domcontentloaded');page.wait_for_function('!!window.neyviaApp');return self._scroll(sid,'state')
        if name=='capture':page.screenshot(path=args,full_page=True);return {'path':args}
        if name=='feedback':
            return page.locator('.ss-page[aria-hidden="false"] [data-answer-area]').inner_text()
        if name=='click':
            current=page.locator('.ss-page[aria-hidden="false"]')
            current.locator(args).click(timeout=5000)
            return self._observe(sid)
        if name=='key':page.keyboard.press(args);return self._observe(sid)
        if name=='mutate':
            # Disposable running-app mutation of the actual planner used by plan().
            return page.evaluate('''async () => {
              const state=window.scrollStudy.state();
              const bad=window.SS_PACK.cards.find(c=>c.type==='flashcard' && c.concepts.tests.some(id=>state.ledger[id].state==='unseen'));
              if(!bad)throw Error('No unseen concept remains for the negative goal check');
              window.SSFeed.buildBlock=()=>[structuredClone(bad)];
              await window.neyviaApp.act('next');
              await window.neyviaApp.act('next');
              return JSON.parse(JSON.stringify({checks:window.neyviaApp.checks(),state:window.neyviaApp.state()}));
            }''')
        raise ValueError('Unknown Scroll Study bridge observation')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',required=True);parser.add_argument('--project',required=True);parser.add_argument('--preview-url')
    args=parser.parse_args()
    project=Path(args.project).resolve()
    output=REPO/'scripts/evidence/A3B-player.json'
    folder=REPO/'scripts/evidence/A3B-runs';folder.mkdir(parents=True,exist_ok=True)
    proof={'schema':'neyvia.A3B.player.v1','at':time.time(),'url':args.url,'checks':[],
           'driver':'production T18 BrowserSessions + app CL 1.1 bridge; owned headless Chromium',
           'sdk':'A1 conventions 0e4aab00, device-local specialization',
           'clRuntime':{'path':str(CL_SOURCE/'cl/goals.py'),'sha256':hashlib.sha256((CL_SOURCE/'cl/goals.py').read_bytes()).hexdigest()},
           'sourceHashes':{str(p.relative_to(project)):hashlib.sha256(p.read_bytes()).hexdigest() for p in project.rglob('*') if p.is_file() and '.neyvia' not in p.parts}}
    def record(name,data):
        proof['checks'].append({'name':name,'data':data});output.write_text(json.dumps(proof,indent=2,default=str),encoding='utf-8');print(name,flush=True)
    browser=ScrollBrowser()
    try:
        sid=browser.run('open',args.url)['browserId']
        def call(name,args=None):return browser.run('scroll',sid,name,args)
        call('viewport')
        contract=json.loads((REPO/'apps/scroll-study/host-contract.json').read_text())
        def observe(name,pos,kwargs):
            if name=='app.state':return call('state')
            if name=='app.checks':return call('checks')
            if name=='web.text':return browser.run('observe',sid)['text']
            raise ValueError('Unknown goal observer')
        initial=call('state');assert initial['pack']=='learning-notes';assert not initial['storageError'];record('actual generated pack loaded in running player',initial)
        untouched=evaluate_goal(contract['goal'],observe,lambda name:name in {'app.state','app.checks','web.text'})
        assert not untouched['passed'];record('CL completion refuses an untouched feed',untouched)
        # First interaction through the visible Start control, then natural exposure.
        obs=browser.run('observe',sid)
        record('rendered initial DOM',obs)
        call('key','ArrowDown')
        stale=call('stale',initial['revision']);assert stale['refused'];record('visible user navigation invalidates a stale agent revision',stale)
        first=call('state');assert first['card'] and first['card']['type'] in {'fact','explainer'}
        before=first['ledger'];call('act',{'name':'next'})
        flick=call('state');assert flick['ledger']==before;record('fast flick does not expose a teach card',flick['card'])
        call('act',{'name':'prev'})
        # Real player exposure timer: 60% of the generated 30s teach card.
        time.sleep(19)
        exposed=call('state');assert exposed['card']['seen'];record('real reading timer exposes the first concept',exposed['ledger'])
        call('capture',str(folder/'player-teaching.png'))
        answered=0;wrong_done=False;visited=[]
        for step in range(45):
            state=call('state');card=state['card'];visited.append(card)
            if not card or card['type'] in {'end','goal'}:break
            if card['type'] in {'fact','explainer','worked','recap'}:
                call('act',{'name':'seeNow'})
            else:
                correct=call('correct')
                value=correct
                if answered>=5 and not wrong_done and card['type'] in {'flashcard','cloze','why'}:value=False;wrong_done=True
                result=call('act',{'name':'answer','args':{'value':value},'options':{'actionId':'answer-'+str(step)}})
                assert result['ok'];feedback=call('feedback');state=call('state')
                assert state['feedback'] and 'Answer:' in feedback and 'Show me where' in feedback and state['feedback']['reason']
                assert state['schedule'];answered+=1
                if answered==1:
                    record('rendered answer, reason and source with actual FSRS state',{'text':feedback,'state':state});call('capture',str(folder/'player-answer.png'))
                    source_observation=call('click','[data-source]')
                    assert 'Rowland' in source_observation['text'];record('visible source control opens the actual imported research notes',source_observation)
                    call('key','Escape')
                duplicate=call('act',{'name':'answer','args':{'value':value},'options':{'actionId':'answer-'+str(step)}});assert duplicate['replayed'];assert duplicate['after']['revision']==result['after']['revision']
            checks=call('checks');assert all(checks.values()),json.dumps(checks)
            call('act',{'name':'next'})
        record('observed feed teach/answer/miss loop',{'answers':answered,'visited':visited,'state':call('state')})
        assert answered>=5;assert wrong_done
        if call('state')['card']['type']=='goal':call('click','[data-finish]')
        contract=json.loads((REPO/'apps/scroll-study/host-contract.json').read_text())
        def observe(name,pos,kwargs):
            if name=='app.state':return call('state')
            if name=='app.checks':return call('checks')
            if name=='web.text':return browser.run('observe',sid)['text']
            raise ValueError('Unknown goal observer')
        goal=evaluate_goal(contract['goal'],observe,lambda name:name in {'app.state','app.checks','web.text'})
        assert goal['passed'],json.dumps(goal);record('CL 1.1 running-app G1-G11 completion goal passed',goal)
        backup=call('progress');call('save');saved=call('state')
        reloaded=call('reload');assert reloaded['ledger']==saved['ledger'];assert reloaded['schedule']==saved['schedule'];record('IndexedDB ledger and FSRS survived actual browser reload',reloaded)
        restored=call('import',backup);assert restored['ledger']==saved['ledger'];assert restored['schedule']==saved['schedule'];record('progress export/import roundtrip uses same app store',True)
        call('act',{'name':'next'})
        mutated=call('mutate');assert not mutated['checks']['G1'];record('deliberately broken real buildBlock detected by G1',mutated)
        refusal=evaluate_goal(contract['goal'],observe,lambda name:name in {'app.state','app.checks','web.text'});assert not refusal['passed'];record('CL goal refuses completion of the mutated running app',refusal)
        if args.preview_url:
            mobile=browser.run('open',args.preview_url)['browserId']
            browser.run('scroll',mobile,'act',{'name':'next'})
            mobile_state=browser.run('scroll',mobile,'state');assert mobile_state['pack']=='learning-notes'
            assert mobile_state['card']['type'] in {'fact','explainer'}
            record('Mobile Studio sandbox plays the same generated pack',{'state':mobile_state,'observation':browser.run('observe',mobile)})
        proof['ok']=True
    except Exception as error:
        proof.update(ok=False,error=str(error));raise
    finally:
        browser.close();output.write_text(json.dumps(proof,indent=2,default=str),encoding='utf-8')


if __name__=='__main__':main()
