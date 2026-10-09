CL 1
L brief-neyvia-launch v3 -- Neyvia launch cut v3: v2 plus a headless-Blender Kronos turntable beside its sketch sheet, phones in a device frame, no hint overlays; 60 fps master
S length {"min":30,"max":60,"target":40} -- seconds
S aspect {"width":1920,"height":1080}
S tone "calm and exact; dark green stage; one green accent meaning 'checked'; the sunset mark only on the end card (brand-supplied)"
S music {"bpm":120,"sync":true,"lufs":-14,"tailS":2.0} -- cuts land on the beat
S captions {"maxWords":5,"safe":0.9,"minHeightFrac":0.05,"minContrast":4.5}
S pacing {"medianShotS":[1.5,4.0]}
S brand {"stage":"#0d1612","ink":"#e9eef0","accent":"#46b077","font":"Inter"}
S must ["agent-view","app-factory","laya","kronos","store","notes"]
S bans "invoice|billing|subscription|payment|pricing" -- no billing imagery on screen
S sources [{"glob": "D:/NeyviaRuns/video/track-video/recapture/dark/agent-view-full.png"}, {"glob": "D:/NeyviaRuns/video/track-video/recapture/dark/laya-full.png"}, {"glob": "D:/NeyviaRuns/video/track-video/recapture/dark/notes-full.png"}, {"glob": "D:/NeyviaRuns/video/track-video/recapture/dark/files-full.png"}, {"glob": "D:/NeyviaRuns/tour/final-verified-theme/dark/*.png"}, {"glob": "D:/NeyviaRuns/tour/ready-apps-preseal/dark/*.png"}, {"glob": "D:/NeyviaRuns/tour/complete-placements-preseal/dark/*.png"}, {"glob": "D:/NeyviaRuns/tour/pre-seal/dark/*.png"}, {"glob": "D:/NeyviaRuns/store/shots/store-dark-1440-*.png", "surface": "store"}]
S story [{"surface": "agent-view", "variant": "full", "caption": "Ask once."}, {"surface": "browser", "variant": "full", "caption": "It reads the web."}, {"surface": "app-factory", "variant": "full", "caption": "Builds the app."}, {"surface": "files", "variant": "full", "caption": "Opens your files."}, {"surface": "laya", "variant": "full", "caption": "Then checks its work."}, {"surface": "kronos", "caption": "Sketch sheets become 3D.", "layout": {"name": "sheet-to-turntable", "layers": [{"src": "D:/NeyviaRuns/video/track-video/cache/derived/sheet-09-crop-ca9820732ddecde9453a.png", "box": [150, 330, 780, 240], "ui": false, "fit": "cover"}, {"kind": "video", "src": "D:/NeyviaRuns/video/track-video/v3work/sources/emblem_kronos.mp4", "box": [1010, 130, 760, 760], "ui": false, "auditAt": 1.7}]}}, {"surface": "notes", "variant": "full", "caption": "Notes stay yours."}, {"surface": "phones", "caption": "Phones too.", "layout": {"name": "phones", "layers": [{"src": "D:/NeyviaRuns/video/track-video/v3work/sources/laya-phone.png", "box": [620, 150, 330, 714], "frame": "phone"}, {"src": "D:/NeyviaRuns/video/track-video/v3work/sources/files-phone.png", "box": [1010, 110, 330, 714], "frame": "phone"}]}}, {"surface": "store", "variant": "shots/store-dark-1440-browse", "caption": "Add apps and mods."}]
S excluded "app-preview (every capture carries the floating Make an app hint or a blank Obscura iframe) and 3d-studio (an asset-check report, no viewport: Obscura has no WebGL) are left out by hand; Kronos is shown as its headless Blender render instead" -- editorial note
S alternates {"pdf":["files"]} -- when a surface has no clean capture
S end {"line":"The workspace that checks its work."}
C brief duration: video.durationS >= 30 and video.durationS <= 60 -- block length inside the brief
C brief aspect: video.aspectError <= 0.01 -- block 16:9 master
C brief loudness: video.truePeakDbtp <= -1.0 and video.clippedSamples == 0 -- block no clipping
C brief coverage: len(video.missingMustInclude) == 0 -- block every must-include surface is on screen
