"""Refresh only computer-use guidance; compile its authored CL artifact."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from grant_agent.cl.manuals import cl_to_manual


def run():
    path=ROOT/'manuals/cl/computer-use.cl'
    rows=path.read_text(encoding='utf-8').splitlines()
    replacements={
        ('deadline-driver','frontier','4'):
            'C11f is historical: nine apps and four learned flows. C11g re-enables visibility diagnostics and proves inactive Bureau placement on Explorer Default even when input is Screen-saver. Calculator CoreWindow lacks injected hook coverage and is refused; shared broker adoption and general Office rendered preview remain unproven.',
        ('deadline-driver','guidance','13'):
            'Office tasks use a new hidden COM instance with PID/birth ownership and save/reopen/package checks. Registered neyvia.nativeapp.open/edit/persist/observe/close drive the native-applications manual. Three grounded runs feed manual.compile; replay uses manual.script.run with fresh checks and zero model tokens. These are application-native tool flows, not UIA or pixel workflows.',
    }
    for i,line in enumerate(rows):
        if not line.startswith('-- @record '):continue
        record=json.loads(line[len('-- @record '):])
        key=(record['chapter'],record['section'],record['key'])
        if key not in replacements:continue
        record['data']=replacements[key]
        rows[i]='-- @record '+json.dumps(record,ensure_ascii=False,separators=(',',':'))
        rows[i+1]=('F '+record['data']) if record['section']=='frontier' else (
            'M computer-use '+json.dumps(record['data'],ensure_ascii=False)+' src:"authored manual" state:verified')
    additions=[
        'Bureau uses Explorer Default, not the current input desktop, which can be Screen-saver. The guard observes both desktops continuously. Private desktop windows need no lease. Only a new owned HWND receives one nonrenewable move lease, capped at three seconds.',
        'New Bureau windows are held hidden before launch resumes. Token-bearing documents must finish loading before admission. Registration stays offscreen with native focus vetoes; pixels reach normal bounds only after actual target GUID membership and DWM Shell cloak are independently verified. DeleteTab is forbidden after placement because it destroys the Shell view and membership.',
        'Preview images are immutable by advertised sequence and capture identity. The pane swaps loaded pixels and their metadata together. Coordinates and forwarded input use the displayed frame; expired frames and foreign windows refuse. Identical pixels may retain earlier semantic controls, but each selected control is freshly validated before dispatch.',
        'Preview scroll resolves the observed scrollable ancestor. Classic owned ListBox scroll uses bounded WM_VSCROLL and fresh LB_GETTOPINDEX effect readback. A degraded observation may be retried as a read only; an uncertain dispatched action is never retried.',
    ]
    base=cl_to_manual('\n'.join(rows)+'\n')
    existing=base['chapters']['deadline-driver'].get('guidance',[])
    for value in additions:
        if value in existing:continue
        record={'chapter':'deadline-driver','section':'guidance','key':str(len(existing)),'data':value}
        rows.extend(['-- @record '+json.dumps(record,ensure_ascii=False,separators=(',',':')),
            'M computer-use '+json.dumps(value,ensure_ascii=False)+' src:"authored manual" state:verified'])
        existing.append(value)
    authored='\n'.join(rows)+'\n'
    compiled=cl_to_manual(authored)
    path.write_text(authored,encoding='utf-8',newline='\n')
    (ROOT/'manuals/computer-use.manual.json').write_text(json.dumps(compiled,indent=2,ensure_ascii=False)+'\n',encoding='utf-8',newline='\n')
    contract=ROOT/'config/cua-desktop-contract.json'
    data=json.loads(contract.read_text(encoding='utf-8'))
    data['inputDesktopPolicy']['visibleAgentWindows']='Zero windows composited for the user. Visibility diagnostics stay enabled. A new owned Bureau HWND may register offscreen during its single nonrenewable three-second move lease; normal bounds require verified inactive membership and Shell cloak. Private Windows desktop objects need no lease.'
    data['inputDesktopPolicy']['observerThread']='Observe the input desktop and Explorer Default on separately bound threads; never switch desktops'
    data['inputDesktopPolicy']['observation'][-1]='Native previsibility containment, offscreen Shell registration, HWND-only move lease <=3 seconds total, independently verified inactive membership and DWM Shell cloak before normal bounds'
    data['registrationDiagnostics']='always_enabled; input + Explorer Default events and samples; failures retained'
    data['bureauMoveLease']='HWND only; one lease per new window; lifetime <=3 seconds; no private-desktop leases'
    contract.write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'manual':'computer-use','chapters':len(compiled['chapters']),'guidanceAdded':len(additions)}))


if __name__=='__main__':run()
