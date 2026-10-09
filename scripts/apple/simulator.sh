#!/usr/bin/env bash
# Copied with the self-contained web capsule. No dependency installs/downloads.
set -euo pipefail
test "$(uname -s)" = Darwin || { echo 'Apple hardware/Xcode runner required'; exit 1; }
mkdir -p output/App.app
app="$PWD/output/App.app"
python3 - <<'PY'
import json, plistlib, pathlib
c=json.loads(pathlib.Path('apple-cloud.json').read_text())
p={'CFBundleIdentifier':c['bundleIdentifier'],'CFBundleName':c['name'],'CFBundleDisplayName':c['name'],
   'CFBundleExecutable':'NeyviaApp','CFBundlePackageType':'APPL','CFBundleVersion':'1','CFBundleShortVersionString':'1.0',
   'CFBundleSupportedPlatforms':['iPhoneSimulator'],'MinimumOSVersion':'16.0','LSRequiresIPhoneOS':True,
   'UIDeviceFamily':[2] if c['target']=='ipados' else [1],'UIRequiresFullScreen':False,'UILaunchScreen':{},
   'UISupportedInterfaceOrientations':['UIInterfaceOrientationPortrait','UIInterfaceOrientationLandscapeLeft','UIInterfaceOrientationLandscapeRight']}
pathlib.Path('output/App.app/Info.plist').write_bytes(plistlib.dumps(p))
PY
cp -R www "$app/www"
bundle=$(python3 -c "import json;print(json.load(open('apple-cloud.json'))['bundleIdentifier'])")
target=$(python3 -c "import json;print(json.load(open('apple-cloud.json'))['target'])")
arch=$(uname -m)
xcrun --sdk iphonesimulator clang -target "${arch}-apple-ios16.0-simulator" -O2 -fno-builtin -fno-stack-protector \
  -isysroot "$(xcrun --sdk iphonesimulator --show-sdk-path)" neyvia_runtime.c \
  -framework UIKit -framework Foundation -framework WebKit -lobjc -o "$app/NeyviaApp"
codesign --force --sign - "$app"
codesign --verify --deep --strict "$app"
xcrun simctl list --json > output/simulators.json
# Select an available device of the exact requested idiom, then create our own.
read -r device_type runtime < <(python3 - "$target" <<'PY'
import json,sys,subprocess
devices=json.loads(subprocess.check_output(['xcrun','simctl','list','devices','available','--json']))['devices']
types=json.loads(subprocess.check_output(['xcrun','simctl','list','devicetypes','--json']))['devicetypes']
prefix='iPad' if sys.argv[1]=='ipados' else 'iPhone'
for runtime, rows in reversed(list(devices.items())):
    for row in rows:
        if row['name'].startswith(prefix) and row.get('isAvailable'):
            kind=next((t['identifier'] for t in types if t['name']==row['name']),None)
            if kind: print(kind,runtime);sys.exit(0)
raise SystemExit('No available Simulator for requested idiom')
PY
)
udid=$(xcrun simctl create 'Neyvia owned outcome' "$device_type" "$runtime")
trap 'xcrun simctl shutdown "$udid" >/dev/null 2>&1 || true; xcrun simctl delete "$udid" >/dev/null 2>&1 || true' EXIT
xcrun simctl boot "$udid"
xcrun simctl bootstatus "$udid" -b
xcrun simctl install "$udid" "$app"
xcrun simctl launch "$udid" "$bundle" > output/launch.txt
xcrun simctl io "$udid" recordVideo output/video.mp4 > output/video.log 2>&1 &
video_pid=$!
sleep 5
xcrun simctl io "$udid" screenshot output/screenshot.png
kill -INT "$video_pid"
wait "$video_pid" || true
export NEYVIA_SIM_UDID="$udid" NEYVIA_SIM_RUNTIME="$runtime" NEYVIA_SIM_DEVICE="$device_type"
python3 - <<'PY'
import json,hashlib,os,pathlib
c=json.loads(pathlib.Path('apple-cloud.json').read_text())
o={'schema':'neyvia.apple_simulator.v1','status':'completed','target':c['target'],'bundleIdentifier':c['bundleIdentifier'],
   'device':os.environ['NEYVIA_SIM_DEVICE'],'runtime':os.environ['NEYVIA_SIM_RUNTIME'],
   'runUrl':f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}",
   'screenshotSha256':hashlib.sha256(pathlib.Path('output/screenshot.png').read_bytes()).hexdigest()}
pathlib.Path('output/cloud-outcome.json').write_text(json.dumps(o,indent=2))
PY
