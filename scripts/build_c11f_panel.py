"""Replace administration probes with disposable everyday-app goals."""
import json
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def build():
    prior=json.loads((ROOT/'scripts/evidence/C11e-tasks.json').read_text(encoding='utf-8'))
    keep={'Notepad','Calculator','Paint','Character Map','File Explorer','Git GUI',
          'Visual Studio Code','Microsoft Edge','Google Chrome','Mozilla Firefox',
          'Microsoft Word','Microsoft Excel','Microsoft PowerPoint'}
    rows=[r for r in prior['apps'] if r['app'] in keep]
    package_root=Path('C:/Program Files/WindowsApps')
    packages={
        'Notepad':('Microsoft.WindowsNotepad_*_x64__8wekyb3d8bbwe','Notepad/Notepad.exe'),
        'Calculator':('Microsoft.WindowsCalculator_*_x64__8wekyb3d8bbwe','CalculatorApp.exe'),
        'Paint':('Microsoft.Paint_*_x64__8wekyb3d8bbwe','PaintApp/mspaint.exe'),
        'Photos':('Microsoft.Windows.Photos_*_x64__8wekyb3d8bbwe','Photos.exe'),
        'Snipping Tool':('Microsoft.ScreenSketch_*_x64__8wekyb3d8bbwe','SnippingTool/SnippingTool.exe'),
        'Sticky Notes':('Microsoft.MicrosoftStickyNotes_*_x64__8wekyb3d8bbwe','StickyNotesStub.exe'),
        'Windows Terminal':('Microsoft.WindowsTerminal_*_x64__8wekyb3d8bbwe','WindowsTerminal.exe')}
    found={}
    # WindowsApps directory enumeration can be denied while a known installed
    # executable remains readable. Package metadata gives its authoritative
    # path without aliases, launches or changing global configuration.
    probe = subprocess.run(['C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe',
        '-NoLogo', '-NoProfile', '-NonInteractive', '-Command',
        'Get-AppxPackage | Select-Object Name,InstallLocation | ConvertTo-Json -Compress'],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
    installed = json.loads(probe.stdout) if probe.returncode == 0 and probe.stdout.strip() else []
    if isinstance(installed, dict): installed = [installed]
    for app,(pattern,relative) in packages.items():
        found[app]=next((p/relative for p in sorted(package_root.glob(pattern),reverse=True) if (p/relative).is_file()),None)
        if not found[app]:
            package_name = pattern.split('_', 1)[0]
            found[app] = next((Path(row['InstallLocation']) / relative for row in installed
                if row.get('Name') == package_name and row.get('InstallLocation')
                and (Path(row['InstallLocation']) / relative).is_file()), None)
    for row in rows:
        if found.get(row['app']):row['exe']=str(found[row['app']]);row['route']='agent-bureau'
        if row['app']=='File Explorer':row['route']='agent-bureau'
        if row['category']=='office':row.update(route='hidden-com',scope='document_edit',task='Create, edit, save and reopen a disposable document with application-native readback')
    editor = next(row for row in rows if row['app'] == 'Visual Studio Code')
    for app, executable in [('Cursor', Path('C:/Users/user/AppData/Local/Programs/cursor/Cursor.exe')),
                            ('Antigravity', Path('C:/Users/user/AppData/Local/Programs/Antigravity/Antigravity.exe'))]:
        row = {**editor, 'app': app, 'exe': str(executable), 'available': executable.is_file(),
            'task': 'Search five fixture phrases in a disposable ' + app + ' editor profile',
            'mutationBoundary': 'Owned local fixture, new profile/extensions folder, no account or AI-provider action'}
        rows.append(row)
    extra=[('Photos','image_view','Open a generated image and inspect its zoom/details without changing user photos','select','Button|RadioButton','zoom|Zoom|agrand'),
           ('Snipping Tool','image_annotation','Open and annotate a generated image; never capture Paul\'s desktop','select','Button|RadioButton','pen|stylo|crayon'),
           ('Sticky Notes','draft_edit','Write a disposable note only if a separate disposable storage boundary can be established','value','Edit|Document',''),
           ('Windows Terminal','local_files','Create and search disposable text files in an explicitly new terminal window','value','Document|Edit','')]
    for app,scope,goal,action,roles,names in extra:
        rows.append({'app':app,'exe':str(found.get(app) or ''),'available':bool(found.get(app)),
            'category':'everyday','scope':scope,'task':goal,'route':'agent-bureau','repetitions':5,
            'action':action,'target':{'rolesRegex':roles,'nameRegex':names},'setupKey':None,
            'values':['C11 note '+str(i) for i in range(1,6)],
            'check':'Fresh application state and disposable file effects match the goal',
            'mutationBoundary':'New HWND or new hidden COM instance; only token-named disposable files',
            'competitorPolicy':'not_evaluated'})
    for app,exe,goals in [
        ('Command Prompt','C:/Windows/System32/cmd.exe', ['Write a disposable note','Copy a disposable note','Rename a disposable draft']),
        ('Windows PowerShell','C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe',
         ['Write a grocery list','Search disposable notes','Create and reopen a ZIP of disposable notes'])]:
        rows.append({'app':app,'exe':exe,'available':Path(exe).is_file(),
            'category':'everyday','scope':'local_files','route':'hidden-shell',
            'task':'; '.join(goals),'tasks':goals,'repetitions':5,'action':'file_command',
            'mutationBoundary':'CREATE_NO_WINDOW shell; token-named disposable files only',
            'check':'Independent exact-content and ZIP readback; scripts/prove_c11f_shell.py'})
    absent={name:str(path) for name,path in [('WordPad',Path('C:/Program Files/Windows NT/Accessories/wordpad.exe')),
        ('7-Zip File Manager',Path('C:/Program Files/7-Zip/7zFM.exe')),('VLC',Path('C:/Program Files/VideoLAN/VLC/vlc.exe'))] if not path.is_file()}
    value={'schema':'neyvia.c11f.everyday-tasks.v1','apps':rows,'repetitions':5,
        'correction':'Everyday apps and disposable user files only; administration removed',
        'removedApps':[r['app'] for r in prior['apps'] if r['app'] not in keep],
        'absentAlternatives':absent,'historicalPanel':'scripts/evidence/C11e-tasks.json',
        'timing':'Fresh observe -> action -> verified readback; failed dispatched calls included, startup reported separately'}
    path=ROOT/'config/cua-everyday-tasks.json'
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return value

if __name__=='__main__':
    value=build();print(json.dumps({'everydayApps':len(value['apps']),'removed':value['removedApps']}))
