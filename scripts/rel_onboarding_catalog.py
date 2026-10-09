"""Keep feature copy in Neyvia's shared onboarding catalog."""
import json
from pathlib import Path

path = Path(__file__).resolve().parents[1] / 'config/neyvia_onboarding.json'
data = json.loads(path.read_text(encoding='utf-8'))
chapters = data['tutorial']['chapters']
copy = {
    'basics': ('Your CLI chats, together', 'Open Claude Code, Codex or another installed CLI as a chat. Pick a model and sign in with its provider.'),
    'notes': ('Local streaming dictation', 'Speak into a note or chat. Text arrives as you talk; local engine status and any fallback stay visible.'),
    'studio': ('Live mobile preview', 'Preview a web app in phone frames. Native builds require the matching toolchain and your signing setup.'),
    'missions': ('Watch a mission', 'Follow agent tasks and their receipts. Provider access, permissions and approvals still apply.'),
    'lab': ('Your decision', 'Review requests that need permission. A browser human check pauses the agent and opens the live page for you.'),
}
for row in chapters:
    if row['id'] in copy: row['title'], row['caption'] = copy[row['id']]
    if row['id'] in {'basics','runtimes','notes','studio'}: row['interests'] = []
new = [
    ('laya', 'LAYA, in view', 'Open LAYA from the activity strip or Apps. Its panel shows local decisions, verification and availability; its advice is evidence to inspect.'),
    ('look', 'Make it yours', 'Settings → Look changes fonts, text size and backgrounds. Readability controls keep your text clear.'),
    ('placement', 'Apps anywhere', 'Use the title-bar controls or drag an app beside chat, into a side panel, full screen or a bubble. Its open state stays with it.'),
    ('watching', 'Watch and replay agents', 'Open Agents at work to watch an agent desktop. Open a recorded run for its time-lapse and receipts; recording must be available.'),
    ('factory', 'App Factory frames', 'Build and preview app frames in App Factory. Running and exporting an app needs its actual files, toolchain and permissions.'),
    ('connectors', '3D Studio and editors', 'Use Browser 3D or connect Unity, Roblox, Godot and Blender. Each connector shows its real setup and session status.'),
    ('images', 'Images and live preview', 'Open Image Studio to generate with a configured provider, inspect the live preview, edit pixels and export. Generation needs provider access.'),
]
ids = {row[0] for row in new}
chapters = [row for row in chapters if row['id'] not in ids]
at = next(i for i,row in enumerate(chapters) if row['id'] == 'studio')
chapters[at:at] = [dict(id=identity,title=title,caption=caption,durationMs=7500,interests=[]) for identity,title,caption in new]
data['tutorial']['chapters'] = chapters
path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
