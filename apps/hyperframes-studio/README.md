# HyperFrames Studio (hosted app)

[HyperFrames](https://github.com/heygen-com/hyperframes) and `@hyperframes/studio` are by HeyGen,
Apache-2.0. This app hosts the upstream Studio unmodified: `neyvia.video.studio` starts
`hyperframes preview --foreground --no-open --port <49121-49129>` as a hidden child and the app
frames `http://127.0.0.1:<port>/`. No browser window opens.

Agents edit the same project through `manuals/cl/video.cl` (`neyvia.video.*`): each EDL edit
recompiles `index.html` in HyperFrames' format, so Studio shows the agent's edits live.

Install from Marketplace → Apps & mods (it installs switched off; enable it after reading the
manual and contracts). Requires the HyperFrames CLI in `D:/NeyviaRuns/video/hf`
(`npm install hyperframes gsap @fontsource-variable/geist`).
