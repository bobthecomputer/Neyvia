CL 1
L brief-neyvia-launch v2 -- Neyvia launch cut from fresh populated captures (recaptured privately in Obscura) plus the tour; LAYA judges and fixes it
S length {"min":30,"max":60,"target":40} -- seconds
S aspect {"width":1920,"height":1080}
S tone "calm and exact; dark green stage; one green accent meaning 'checked'; the sunset mark only on the end card (brand-supplied)"
S music {"bpm":120,"sync":true,"lufs":-14,"tailS":2.0} -- cuts land on the beat
S captions {"maxWords":5,"safe":0.9,"minHeightFrac":0.05,"minContrast":4.5}
S pacing {"medianShotS":[1.5,4.0]}
S brand {"stage":"#0d1612","ink":"#e9eef0","accent":"#46b077","font":"Inter"}
S must ["agent-view","app-factory","laya","kronos","store","notes"]
S bans "invoice|billing|subscription|payment|pricing" -- no billing imagery on screen
S sources [{"glob":"D:/NeyviaRuns/video/track-video/recapture/dark/agent-view-full.png"},{"glob":"D:/NeyviaRuns/video/track-video/recapture/dark/laya-full.png"},{"glob":"D:/NeyviaRuns/video/track-video/recapture/dark/notes-full.png"},{"glob":"D:/NeyviaRuns/video/track-video/recapture/dark/files-full.png"},{"glob":"D:/NeyviaRuns/video/track-video/recapture/dark/pdf-full.png"},{"glob":"D:/NeyviaRuns/video/track-video/recapture/dark/3d-studio-full.png"},{"glob":"D:/NeyviaRuns/laya-3d/kronos/out/overview.png","surface":"kronos","crop":{"x":0,"y":630,"width":600,"height":337}},{"glob":"D:/NeyviaRuns/tour/final-verified-theme/dark/*.png"},{"glob":"D:/NeyviaRuns/tour/ready-apps-preseal/dark/*.png"},{"glob":"D:/NeyviaRuns/tour/complete-placements-preseal/dark/*.png"},{"glob":"D:/NeyviaRuns/tour/pre-seal/dark/*.png"},{"glob":"D:/NeyviaRuns/store/shots/store-dark-1440-*.png","surface":"store"},{"glob":"D:/NeyviaRuns/laya-3d/kronos/out/*/before-after.png","surface":"kronos-sheet"}]
S story [{"surface":"agent-view","variant":"full","caption":"Ask once."},{"surface":"browser","variant":"full","caption":"It reads the web."},{"surface":"app-factory","variant":"full","caption":"Builds the app."},{"surface":"app-preview","variant":"full","caption":"Runs it."},{"surface":"pdf","variant":"full","caption":"Opens your files."},{"surface":"laya","variant":"full","caption":"Then checks its work."},{"surface":"kronos","caption":"Sketch sheets become 3D."},{"surface":"3d-studio","variant":"full","caption":"Judged in the engine."},{"surface":"notes","variant":"full","caption":"Notes stay yours."},{"surface":"mobile-studio","variant":"full","caption":"Phones too."},{"surface":"store","variant":"shots/store-dark-1440-browse","caption":"Add apps and mods."}]
S excluded "recapture app-factory-full.png (iframe drawn blank by Obscura) and 3d-studio-browser-full.png (no WebGL): excluded by hand; the judge does not see a blank framed panel inside dense UI" -- editorial note
S alternates {"pdf":["files"],"3d-studio":["godot","playtest"]} -- when a surface has no clean capture
S end {"line":"The workspace that checks its work."}
C brief duration: video.durationS >= 30 and video.durationS <= 60 -- block length inside the brief
C brief aspect: video.aspectError <= 0.01 -- block 16:9 master
C brief loudness: video.truePeakDbtp <= -1.0 and video.clippedSamples == 0 -- block no clipping
C brief coverage: len(video.missingMustInclude) == 0 -- block every must-include surface is on screen
