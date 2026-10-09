"""Executable UIFIX2 manual procedures: the private-beta UI repairs, checked through the real code.

run(n) executes one contract and writes scripts/evidence/UIFIX2-<n>.json; run(0) runs all.
Confined fixtures only (a scratch LOCALAPPDATA); nothing is downloaded or installed for the user.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))


def node(source):
    subprocess.run(["node", "--input-type=module", "-e", source], cwd=REPO, check=True)


def c1_pdf_opens_and_names_plainly():
    """PDFs open where module workers don't, and are named by their file, never an encoded route."""
    node("""
import assert from 'node:assert/strict';
import {displayName} from './web/src/neyvia/next/nxPdfModel.js';
assert.equal(displayName({value:'http://127.0.0.1:1/api/ui/files/raw?path=D%3A%5CRuns%5Ctour-fixtures%5CINTN.pdf'}),'INTN.pdf');
assert.equal(displayName({value:'/api/apps/pdf/file?path=C%3A%5Cdocs%5CReport%20Q3.pdf'}),'Report Q3.pdf');
assert.equal(displayName({value:'raw?path=D%3A%5C'}),'document.pdf');
assert.equal(displayName({file:{name:'Field notes.pdf'}}),'Field notes.pdf');
""")
    model = (REPO / "web/src/neyvia/next/nxPdfModel.js").read_text(encoding="utf-8")
    assert "globalThis.pdfjsWorker" in model and "moduleWorkersWork" in model, "main-thread pdf.js fallback is missing"
    app = (REPO / "web/src/neyvia/next/NxPdfApp.jsx").read_text(encoding="utf-8")
    assert "split(/[\\\\/]/).pop()" not in app and "displayName(source)" in app, "PDF name is not derived through displayName"
    assert "It took too long to open" in app, "an endless Opening state is possible"


def c2_cua_helper_plain_and_shared():
    """The screen-control helper is found in a shared per-user runtime, and its absence reads plainly."""
    with tempfile.TemporaryDirectory(dir=REPO / ".agent_control") as scratch:
        os.environ["LOCALAPPDATA"] = scratch
        os.environ.pop("NEYVIA_CUA_DRIVER_DIR", None)
        from grant_agent import cua_upstream as cua
        candidates = cua.runtime_candidates()
        assert candidates[0] == Path(scratch) / "Neyvia/runtimes/cua-driver" / cua.DRIVER_VERSION, candidates
        assert candidates[-1] == cua.checkout_runtime()
        status = cua.runtime_status(Path(scratch) / "nothing-here")
        assert not status["available"] and status["code"] == "missing", status
        for word in ("cua-driver.exe", "install_cua_driver", "T16", "--source"):
            assert word not in status["reason"], (word, status["reason"])
        assert status["setup"]["canInstall"] and "install_cua_driver.py" in status["detail"]
        bad = Path(scratch) / "bad"
        bad.mkdir()
        (bad / "cua-driver.exe").write_bytes(b"not the pinned driver")
        (bad / "cua-driver-uia.exe").write_bytes(b"not the pinned driver")
        driver = bad / 'cua-driver.exe'
        first_digest = cua._digest(driver)
        stamp = driver.stat().st_mtime_ns
        driver.write_bytes(b'bad the pinned driver')
        os.utime(driver, ns=(stamp + 1000000, stamp + 1000000))
        assert cua._digest(driver) != first_digest, 'a changed helper retained its old cached digest'
        try:
            cua.install_runtime(bad, Path(scratch) / "target")
            raise AssertionError("an unverified helper was staged")
        except RuntimeError as exc:
            assert "hash mismatch" in str(exc)
        try:
            cua.install_runtime(target=Path(scratch) / "target", fetch=lambda: b"not the release")
            raise AssertionError("an unverified download was staged")
        except RuntimeError as exc:
            assert "SHA256" in str(exc)
        assert not (Path(scratch) / "target" / "cua-driver.exe").exists()
    pane = (REPO / "web/src/neyvia/next/NxPreviewPane.jsx").read_text(encoding="utf-8")
    assert "Set up the helper" in pane and 'call("install_driver"' in pane and "nx-pv-idle-reason" not in pane


def c3_sidebar_sources_calm():
    """A chat source that can't be read becomes one plain line; raw errors stay in the tooltip."""
    from grant_agent.connected_sessions.broker import source_problem
    from grant_agent.connected_sessions.codex_rpc import ConnectionLost, CodexError
    from grant_agent.connected_sessions.registry import ConnectedError
    stopped = source_problem("codex", ConnectionLost())
    assert stopped["state"] == "offline" and stopped["reason"] == "Codex isn't responding right now.", stopped
    assert "app-server" not in stopped["reason"] and "app-server" in stopped["detail"]
    busy = source_problem("claude-code", ConnectedError("adapter_busy", "The app is still answering an earlier request.", 503))
    assert busy["state"] == "loading" and "earlier request" not in busy["reason"], busy
    backoff = source_problem("codex", CodexError("app_server_backoff", "Codex app-server keeps stopping; retrying shortly."))
    assert backoff["state"] == "offline" and "app-server" not in backoff["reason"]
    sidebar = (REPO / "web/src/neyvia/next/NxSidebar.jsx").read_text(encoding="utf-8")
    assert "<SourceStatus" in sidebar and 'source.state !== "missing"' in sidebar
    shots = (REPO / "scripts/placement_shots.py").read_text(encoding="utf-8")
    assert '"codex", "hermes", "claude"' in shots, "the tour must create CODEX_HOME so Codex can start"


def c4_gamedev_names_and_selection():
    """Game Dev sessions are named in words and a reloaded Browser 3D scene stays selected."""
    node("""
import assert from 'node:assert/strict';
import {sessionLabel, keepSelection, engineState, folderName} from './web/src/neyvia/next/nxGameDevModel.js';
assert.equal(sessionLabel({context:'Edit',environment:'browser-null'}),'Browser 3D editor · no 3D picture');
assert.equal(sessionLabel({context:'Edit',environment:'browser-webgl'}),'Browser 3D editor');
assert.equal(sessionLabel({context:'Edit',environment:'native-editor'}),'Editor');
for (const env of ['browser-null','weird-id',null,undefined]) assert.ok(!/null|undefined|-/.test(sessionLabel({context:'Edit',environment:env}).replace('3D','')), env);
const rows=[{sessionId:'old',environment:'browser-null',status:'disconnected',projectPath:'p',context:'Edit'},{sessionId:'new',environment:'browser-null',status:'connected',projectPath:'p',context:'Edit'}];
assert.equal(keepSelection('old',rows),'new');
assert.equal(keepSelection('n',[{sessionId:'n',environment:'native-editor',status:'disconnected'},{sessionId:'o',status:'connected'}]),'n');
assert.equal(engineState({engine:'godot'}).word,'Needs you');
assert.equal(folderName('D:/a/b/project'),'project');
""")


def c5_no_fixture_text_in_apps():
    """The tour proves state survives moves without typing fixture text into real fields."""
    journeys = (REPO / "scripts/placement_journeys.py").read_text(encoding="utf-8")
    mark = journeys.split('MARK = """', 1)[1].split('"""', 1)[0]
    assert "kept across moves" not in journeys and ".set.call(field" not in mark and "__placementMark = id" in mark
    assert 'state.get("fieldKept") is True' in journeys


def c6_layout_repairs():
    """No card over the App preview sample; prose fields wrap; CiteCraft hides internal ids."""
    css = (REPO / "web/src/neyvia/neyviaAppPreviewWorkspace.css").read_text(encoding="utf-8")
    rule = re.search(r"\.neyvia-app-preview-empty \{([^}]*)\}", css).group(1)
    assert "position: absolute" not in rule and "flex: none" in rule
    assert ".af-form textarea { white-space: pre-wrap;" in (REPO / "web/src/neyvia/neyviaAppFactoryStudio.css").read_text(encoding="utf-8")
    assert "white-space: pre-wrap" in (REPO / "web/src/neyvia/next/nxAwareness.css").read_text(encoding="utf-8")
    studios = (REPO / "web/src/neyvia/NeyviaNativeStudios.jsx").read_text(encoding="utf-8")
    assert 'name: "CiteCraft"' in studios and "<small>{source.id}</small>" not in studios and "source-a1" not in studios


def c7_open_here_reaches_the_shell():
    """Library and Marketplace "Open here" open a real surface in the single shell; the audit reads that shell."""
    node("""
import assert from 'node:assert/strict';
import {embeddedRoute, EMBED_EVENT} from './web/src/neyvia/next/nxEmbedRoute.js';
assert.equal(EMBED_EVENT,'neyvia:open-embedded-workspace');
assert.deepEqual(embeddedRoute({adapterId:'pdf-reader'}),{kind:'app',app:'pdf',suite:'documents',target:null});
assert.equal(embeddedRoute({adapterId:'office-document'}).app,'office-suite');
assert.equal(embeddedRoute({adapterId:'image-playground'}).app,'image-playground');
assert.equal(embeddedRoute({adapterId:'app-preview',context:{jobId:'j1'}}).target,JSON.stringify({jobId:'j1',root:''}));
assert.deepEqual(embeddedRoute({adapterId:'marketplace-app',contentRef:{url:'https://x.test/a'}}),{kind:'app',app:'browser',suite:'',target:'https://x.test/a'});
assert.equal(embeddedRoute({adapterId:'marketplace-app'}).app,'marketplace');
assert.equal(embeddedRoute({adapterId:'runtime-window'}).pane,'runtime');
assert.equal(embeddedRoute({adapterId:'unknown'}),null);
""")
    host = (REPO / "web/src/neyvia/NeyviaEcosystemHost.jsx").read_text(encoding="utf-8")
    assert 'NEYVIA_EMBED_EVENT = "neyvia:open-embedded-workspace"' in host
    shell = (REPO / "web/src/neyvia/next/NxShell.jsx").read_text(encoding="utf-8")
    assert "useEmbeddedWorkspaceBridge();" in shell
    tools = (REPO / "web/src/neyvia/next/NxToolScreens.jsx").read_text(encoding="utf-8")
    assert "window.addEventListener(EMBED_EVENT, onOpen)" in tools
    from grant_agent.system_audit import _current_shell_text
    text = _current_shell_text(REPO, (".jsx", ".js", ".tsx", ".ts"))
    assert "useEmbeddedWorkspaceBridge" in text and len(_current_shell_text(REPO, (".css",))) > 1000
    audit = (REPO / "src/grant_agent/system_audit.py").read_text(encoding="utf-8")
    assert "NeyviaShell.jsx" not in audit and "stylesReference.css" not in audit


CONTRACTS = {1: c1_pdf_opens_and_names_plainly, 2: c2_cua_helper_plain_and_shared, 3: c3_sidebar_sources_calm,
             4: c4_gamedev_names_and_selection, 5: c5_no_fixture_text_in_apps, 6: c6_layout_repairs,
             7: c7_open_here_reaches_the_shell}


def run(number=0):
    (REPO / ".agent_control").mkdir(exist_ok=True)
    chosen = CONTRACTS if not number else {number: CONTRACTS[number]}
    results = {}
    for key, check in chosen.items():
        check()
        results[key] = check.__doc__.strip()
    path = REPO / "scripts/evidence" / ("UIFIX2.json" if not number else f"UIFIX2-{number}.json")
    path.write_text(json.dumps({"contracts": results, "passed": True}, indent=2) + "\n", encoding="utf-8")
    return {"passed": True, "contracts": sorted(results), "receipt": str(path)}


if __name__ == "__main__":
    print(json.dumps(run(int(sys.argv[1]) if len(sys.argv) > 1 else 0)))
