CL 1
L brief-practice v1 -- Self-made practice: a short real-capture cut that defects are injected into (plan 24)
S length {"min":8,"max":20,"target":12} -- seconds
S aspect {"width":1920,"height":1080}
S tone "calm and exact; dark green stage; one green accent meaning 'checked'; the sunset mark only on the end card (brand-supplied)"
S music {"bpm":120,"sync":true,"lufs":-14,"tailS":2.0} -- cuts land on the beat
S captions {"maxWords":5,"safe":0.9,"minHeightFrac":0.05,"minContrast":4.5}
S pacing {"medianShotS":[1.5,4.0]}
S brand {"stage":"#0d1612","ink":"#e9eef0","accent":"#46b077","font":"Inter"}
S must ["laya","kronos","store"]
S bans "invoice|billing|subscription|payment|pricing" -- no billing imagery on screen
S sources [{"glob":"D:/NeyviaRuns/tour/final-verified-theme/dark/*.png"},{"glob":"D:/NeyviaRuns/tour/ready-apps-preseal/dark/*.png"},{"glob":"D:/NeyviaRuns/tour/complete-placements-preseal/dark/*.png"},{"glob":"D:/NeyviaRuns/tour/pre-seal/dark/*.png"},{"glob":"D:/NeyviaRuns/store/shots/store-dark-1440-*.png","surface":"store"},{"glob":"D:/NeyviaRuns/laya-3d/kronos/out/*/before-after.png","surface":"kronos"}]
S story [{"surface":"laya","variant":"full","caption":"Then checks its work."},{"surface":"kronos","variant":"emblem/before-after","caption":"Sketch sheets become 3D."},{"surface":"store","variant":"shots/store-dark-1440-browse","caption":"Add apps and mods."}]
S end {"line":"The workspace that checks its work."}
C brief duration: video.durationS >= 8 and video.durationS <= 20 -- block length inside the brief
C brief aspect: video.aspectError <= 0.01 -- block 16:9 master
C brief loudness: video.truePeakDbtp <= -1.0 and video.clippedSamples == 0 -- block no clipping
C brief coverage: len(video.missingMustInclude) == 0 -- block every must-include surface is on screen
