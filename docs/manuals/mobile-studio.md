<!-- Generated from manuals/cl/mobile-studio.cl; edit that source, then run scripts/cl_compile_manuals.py and scripts/render_manuals.py. -->
# mobile-studio

## fixcl3-local
CL 1
L mobile-studio v1 -- Exact retained local admission and supervision
T t1 json:"{\"type\":\"object\"}"
A neyvia.mobile.create(path:str name:str bundleId?:str) -> t1 ! -- Exact retained mobile.create
F verify-neyvia-mobile-create "No authored observer check is bound to neyvia.mobile.create" -> ask operator blocks:neyvia.mobile.create
X Fresh owner state differs from this action subject -> Reconcile the specific retained effect; never replay an uncertain launch.
F Admission, arming and local starter bytes do not prove provider execution, rendered preview, device build or installation. Active provider controls require a terminal provider witness.
F After mobile.create requests approval, its durable artifact identity can remain uncertain. Reconcile the exact unchanged empty target and use a distinct recovery action ID; automatic replay is refused.
M mobile-studio "CL completion re-reads the owner and compares the exact task graph, source hash, retained control or starter bytes." src:"authored manual" state:verified
-- @proof {"checkedAt":["ios_studio.create_ios_app -> proofs_c_mobile.check_project"],"claim":"Created Expo authoring files retain requested identity, entrypoint and supported dependency versions.","id":"proofs-c.mobile.project","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"post"}
-- @proof {"checkedAt":["ios_studio._safe_child"],"claim":"Creation rejects paths outside selected root before any effects.","id":"proofs-c.mobile.scope","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"pre"}
-- @proof {"checkedAt":["ios_studio.create_ios_app"],"claim":"Creation requires a valid reverse-domain bundle identifier before writing.","id":"proofs-c.mobile.bundle-id","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"pre"}
-- @proof {"checkedAt":["ios_studio.create_ios_build_capsule -> proofs_c_mobile.check_capsule"],"claim":"Each capsule retains its source root and exact manifest, excluding generated paths, confidential suffixes and links.","id":"proofs-c.mobile.capsule","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"post"}
-- @proof {"checkedAt":["ios_studio.save_ios_builder -> proofs_c_mobile.check_config"],"claim":"Builder metadata persists only the allowed fields and signing references, without passwords.","id":"proofs-c.mobile.builder-config","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"post"}
-- @proof {"checkedAt":["windows_ios_compiler.save_windows_ios_config -> proofs_c_mobile.check_config"],"claim":"Compiler preferences validate before writing and persist exactly, without signing passwords.","id":"proofs-c.mobile.compiler-config","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"post"}
-- @proof {"checkedAt":["windows_ios_compiler._download_verified"],"claim":"Downloaded bytes match the expected digest before atomic promotion; mismatch never promotes a destination.","id":"proofs-c.mobile.download-digest","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"post"}
-- @proof {"checkedAt":["windows_ios_compiler._write_info_plist -> proofs_c_mobile.check_plist"],"claim":"Persisted plist exactly matches identity and iPhoneOS platform metadata.","id":"proofs-c.mobile.metadata","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"post"}
-- @proof {"checkedAt":["windows_ios_compiler._zip_payload -> proofs_c_mobile.check_package"],"claim":"IPA archive contains exactly the app files under Payload with unchanged bytes.","id":"proofs-c.mobile.package","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"post"}
-- @proof {"checkedAt":["windows_ios_compiler._safe_copy_web_assets -> proofs_c_mobile.check_web_assets"],"claim":"Assets stage inside the app www directory and root-relative links become local links.","id":"proofs-c.mobile.web-assets","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"post"}
-- @proof {"checkedAt":["windows_ios_compiler._clean_error"],"claim":"Failure receipts strip terminal control codes and retain bounded useful text.","id":"proofs-c.mobile.error-text","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"post"}
-- @proof {"checkedAt":["web_backend.FluxioWebBackend.dispatch -> proofs_c_mobile.check_backend"],"claim":"Mobile authoring, status and compiler configuration commands retain requested workspace, app identity, current recognition and preferences.","id":"proofs-c.mobile.backend-wiring","impact":["authenticated command API","Mobile Studio source and status","compiler preferences"],"phase":"post"}

## overview
CL 1
L mobile-studio v1 -- Phone preview of a web app (HTML/CSS/JS, Capacitor or Expo web) with hot reload, plus iPhone .ipa and Android .apk builds; not a native editor or simulator
T t1{device:str orientation:str dark:bool jobs:json:"{\"type\":\"array\"}" ..}
T t2 json:"{\"type\":\"string\",\"enum\":[\"ios\",\"android\"]}"
T t3 json:"{\"type\":\"object\"}"
T t4 json:"{\"type\":\"string\",\"enum\":[\"iphone-16-pro\",\"iphone-16-pro-max\",\"iphone-16\",\"iphone-se\",\"pixel-9\",\"pixel-9-pro-xl\"]}"
T t5 json:"{\"type\":\"string\",\"enum\":[\"portrait\",\"landscape\"]}"
T t6 json:"{\"type\":\"string\",\"enum\":[\"ios-compiler\"]}"
S mobile-studio.current:t1=neyvia.mobile.status()
A neyvia.mobile.status(project?:str) -> t1 -- Read app shape/existence, frame, detected SDKs/devices, jobs and latest build receipts
C neyvia.mobile.status orientation-saved:neyvia.mobile.status() .orientation == orientation
C neyvia.mobile.status device-probe-disabled:neyvia.mobile.status() .android.deviceProbeEnabled == false
A neyvia.mobile.build(platform:t2 project?:str waitSeconds?:0..900 addShell?:bool) -> t3 ! -- Start build job; Android may prebuild/install Capacitor and Gradle dependencies; success writes APK/IPA receipt, not install
F verify-mobile-build "No authored observer check is bound to neyvia.mobile.build" -> ask operator blocks:neyvia.mobile.build
A neyvia.mobile.create(path:str name:str bundleId?:str) -> t3 ! -- Create local app scaffold and select it; does not prove build or installed app
F verify-mobile-create "No authored observer check is bound to neyvia.mobile.create" -> ask operator blocks:neyvia.mobile.create
A neyvia.mobile.install(target:str project?:str avd?:str waitSeconds?:0..600) -> t3 ! -- Return iPhone sideload steps or start adb install/launch job; waitSeconds may return pending job
F verify-mobile-install "No authored observer check is bound to neyvia.mobile.install" -> ask operator blocks:neyvia.mobile.install
A neyvia.mobile.preview(device?:t4 project?:str orientation?:t5 dark?:bool startExpo?:bool) -> t3 ! -- Persist phone frame and expose preview; startExpo starts existing Expo dev server without installing dependencies
C neyvia.mobile.preview device-saved:neyvia.mobile.status() .device == device
A neyvia.mobile.setup(part:t6 project?:str) -> t3 ! -- Start compiler download job; status/receipt report outcome, no implicit system setup
F verify-mobile-setup "No authored observer check is bound to neyvia.mobile.setup" -> ask operator blocks:neyvia.mobile.setup
C neyvia.mobile.status device-saved:neyvia.mobile.status() .device == device
C neyvia.mobile.status orientation-saved:neyvia.mobile.status() .orientation == orientation
C neyvia.mobile.status device-probe-disabled:neyvia.mobile.status() .android.deviceProbeEnabled == false
P set-phone-frame(device:t4 orientation:t5):before=neyvia.mobile.status(); J phone-frame=preview; preview=neyvia.mobile.preview(device:device orientation:orientation) C device-saved; after=neyvia.mobile.status() C orientation-saved -- Read current phone settings, choose a device and rotation, then verify retained frame
V P set-phone-frame -> script why:"typed manual runner; stops at every judgement"
P build-chosen-platform(project:str platform:t2):readiness=neyvia.mobile.status(project:project); J build-target=build; job=neyvia.mobile.build(platform:platform project:project); progress=neyvia.mobile.status(project:project) -- Inspect selected app toolchains, review platform and start a real build job
V P build-chosen-platform -> script why:"typed manual runner; stops at every judgement"
P inspect-without-devices():installed=neyvia.mobile.status() C device-probe-disabled -- Inspect installed tools in an explicitly isolated session with NEYVIA_MOBILE_PROBE_DEVICES=0; no adb daemon, emulator or device discovery
V P inspect-without-devices -> script why:"typed manual runner; stops at every judgement"
J phone-frame preview|leave:"Which tested phone frame and rotation matches the target audience?" -- Input device is one of mobile.preview enum; choose based on target screen/safe areas. Frame state does not prove touch, keyboard, build or install behavior.
V J phone-frame -> human:operator why:"explicit choice required"
J build-target build|leave:"Build with the installed platform toolchain now?" -- Check status missing[] and project kind first. Do not install SDKs automatically. Android shell generation/Gradle dependency downloads change project and may exceed current download authorization; stop until separately authorized.
V J build-target -> human:operator why:"explicit choice required"
X Android tools missing / needsShell true -> Report exact missing SDK sizes; addShell creates project files and downloads dependencies only after authority
X Gradle exits but APK absent -> Inspect job error and output path; do not invent artifact
X USB unauthorized or multiple phones -> Unlock/approve debugging or supply exact serial from status; do not guess
X iPhone install returns status=manual -> Give IPA path and AltStore/SideStore steps; no adb-style automatic iPhone installation
X Preview state saved but app blank -> Verify webRoot/index.html or Expo server separately and inspect actual preview
X Person expects a native iPhone or Android editor or simulator -> Say plainly: Mobile Studio previews the web export in a phone frame and builds it; for native screens use Android's emulator (Android Studio) or a real iPhone via the build/sideload path
F Native Swift/SwiftUI or Kotlin/Compose editing, Xcode or Android Studio layouts and an iOS Simulator are not part of Mobile Studio; the preview is a web view in a phone frame
F Store signing/submission, real-device gestures and accessibility need separate proof
F Compiler setup downloads 864 MB; current 200 MB scope does not authorize it
F Completed job is build evidence; UI/device launch needs a separate journey
M mobile-studio "Source: src/grant_agent/neyvia_mobile_studio.py (preview, build, install, call); tests/test_neyvia_mobile_studio.py." src:"authored manual" state:verified
M mobile-studio "Private headless verification may set NEYVIA_MOBILE_PROBE_DEVICES=0. Device discovery is explicitly disabled and reported as deviceProbeEnabled:false; installed SDK and Java discovery still run. Ordinary sessions retain existing device discovery." src:"authored manual" state:verified
-- @proof {"checkedAt":["ios_studio.create_ios_app -> proofs_c_mobile.check_project"],"claim":"Created Expo authoring files retain requested identity, entrypoint and supported dependency versions.","id":"proofs-c.mobile.project","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"post"}
-- @proof {"checkedAt":["ios_studio._safe_child"],"claim":"Creation rejects paths outside selected root before any effects.","id":"proofs-c.mobile.scope","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"pre"}
-- @proof {"checkedAt":["ios_studio.create_ios_app"],"claim":"Creation requires a valid reverse-domain bundle identifier before writing.","id":"proofs-c.mobile.bundle-id","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"pre"}
-- @proof {"checkedAt":["ios_studio.create_ios_build_capsule -> proofs_c_mobile.check_capsule"],"claim":"Each capsule retains its source root and exact manifest, excluding generated paths, confidential suffixes and links.","id":"proofs-c.mobile.capsule","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"post"}
-- @proof {"checkedAt":["ios_studio.save_ios_builder -> proofs_c_mobile.check_config"],"claim":"Builder metadata persists only the allowed fields and signing references, without passwords.","id":"proofs-c.mobile.builder-config","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"post"}
-- @proof {"checkedAt":["windows_ios_compiler.save_windows_ios_config -> proofs_c_mobile.check_config"],"claim":"Compiler preferences validate before writing and persist exactly, without signing passwords.","id":"proofs-c.mobile.compiler-config","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"post"}
-- @proof {"checkedAt":["windows_ios_compiler._download_verified"],"claim":"Downloaded bytes match the expected digest before atomic promotion; mismatch never promotes a destination.","id":"proofs-c.mobile.download-digest","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"post"}
-- @proof {"checkedAt":["windows_ios_compiler._write_info_plist -> proofs_c_mobile.check_plist"],"claim":"Persisted plist exactly matches identity and iPhoneOS platform metadata.","id":"proofs-c.mobile.metadata","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"post"}
-- @proof {"checkedAt":["windows_ios_compiler._zip_payload -> proofs_c_mobile.check_package"],"claim":"IPA archive contains exactly the app files under Payload with unchanged bytes.","id":"proofs-c.mobile.package","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"post"}
-- @proof {"checkedAt":["windows_ios_compiler._safe_copy_web_assets -> proofs_c_mobile.check_web_assets"],"claim":"Assets stage inside the app www directory and root-relative links become local links.","id":"proofs-c.mobile.web-assets","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"post"}
-- @proof {"checkedAt":["windows_ios_compiler._clean_error"],"claim":"Failure receipts strip terminal control codes and retain bounded useful text.","id":"proofs-c.mobile.error-text","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"post"}
-- @proof {"checkedAt":["web_backend.FluxioWebBackend.dispatch -> proofs_c_mobile.check_backend"],"claim":"Mobile authoring, status and compiler configuration commands retain requested workspace, app identity, current recognition and preferences.","id":"proofs-c.mobile.backend-wiring","impact":["authenticated command API","Mobile Studio source and status","compiler preferences"],"phase":"post"}

## proofs-c-local-authoring
CL 1
L mobile-studio v1 -- PROOFS-c local authoring and package contracts
X A package receipt is mistaken for native compilation or installation. -> Require separate compiler/signing and device receipts.
F Native signing/device and remote builder require their hosts.
M mobile-studio "proofs-c.mobile.project: Created Expo authoring files retain requested identity, entrypoint and supported dependency versions. Checked: ios_studio.create_ios_app -> proofs_c_mobile.check_project" src:"authored manual" state:verified
M mobile-studio "proofs-c.mobile.scope: Creation rejects paths outside selected root before any effects. Checked: ios_studio._safe_child" src:"authored manual" state:verified
M mobile-studio "proofs-c.mobile.bundle-id: Creation requires a valid reverse-domain bundle identifier before writing. Checked: ios_studio.create_ios_app" src:"authored manual" state:verified
M mobile-studio "proofs-c.mobile.capsule: Each capsule retains its source root and exact manifest, excluding generated paths, confidential suffixes and links. Checked: ios_studio.create_ios_build_capsule -> proofs_c_mobile.check_capsule" src:"authored manual" state:verified
M mobile-studio "proofs-c.mobile.builder-config: Builder metadata persists only the allowed fields and signing references, without passwords. Checked: ios_studio.save_ios_builder -> proofs_c_mobile.check_config" src:"authored manual" state:verified
M mobile-studio "proofs-c.mobile.compiler-config: Compiler preferences validate before writing and persist exactly, without signing passwords. Checked: windows_ios_compiler.save_windows_ios_config -> proofs_c_mobile.check_config" src:"authored manual" state:verified
M mobile-studio "proofs-c.mobile.download-digest: Downloaded bytes match the expected digest before atomic promotion; mismatch never promotes a destination. Checked: windows_ios_compiler._download_verified" src:"authored manual" state:verified
M mobile-studio "proofs-c.mobile.metadata: Persisted plist exactly matches identity and iPhoneOS platform metadata. Checked: windows_ios_compiler._write_info_plist -> proofs_c_mobile.check_plist" src:"authored manual" state:verified
M mobile-studio "proofs-c.mobile.package: IPA archive contains exactly the app files under Payload with unchanged bytes. Checked: windows_ios_compiler._zip_payload -> proofs_c_mobile.check_package" src:"authored manual" state:verified
M mobile-studio "proofs-c.mobile.web-assets: Assets stage inside the app www directory and root-relative links become local links. Checked: windows_ios_compiler._safe_copy_web_assets -> proofs_c_mobile.check_web_assets" src:"authored manual" state:verified
M mobile-studio "proofs-c.mobile.error-text: Failure receipts strip terminal control codes and retain bounded useful text. Checked: windows_ios_compiler._clean_error" src:"authored manual" state:verified
M mobile-studio "proofs-c.mobile.backend-wiring: Mobile authoring, status and compiler configuration commands retain requested workspace, app identity, current recognition and preferences. Checked: web_backend.FluxioWebBackend.dispatch -> proofs_c_mobile.check_backend" src:"authored manual" state:verified
-- @proof {"checkedAt":["ios_studio.create_ios_app -> proofs_c_mobile.check_project"],"claim":"Created Expo authoring files retain requested identity, entrypoint and supported dependency versions.","id":"proofs-c.mobile.project","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"post"}
-- @proof {"checkedAt":["ios_studio._safe_child"],"claim":"Creation rejects paths outside selected root before any effects.","id":"proofs-c.mobile.scope","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"pre"}
-- @proof {"checkedAt":["ios_studio.create_ios_app"],"claim":"Creation requires a valid reverse-domain bundle identifier before writing.","id":"proofs-c.mobile.bundle-id","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"pre"}
-- @proof {"checkedAt":["ios_studio.create_ios_build_capsule -> proofs_c_mobile.check_capsule"],"claim":"Each capsule retains its source root and exact manifest, excluding generated paths, confidential suffixes and links.","id":"proofs-c.mobile.capsule","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"post"}
-- @proof {"checkedAt":["ios_studio.save_ios_builder -> proofs_c_mobile.check_config"],"claim":"Builder metadata persists only the allowed fields and signing references, without passwords.","id":"proofs-c.mobile.builder-config","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"post"}
-- @proof {"checkedAt":["windows_ios_compiler.save_windows_ios_config -> proofs_c_mobile.check_config"],"claim":"Compiler preferences validate before writing and persist exactly, without signing passwords.","id":"proofs-c.mobile.compiler-config","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"post"}
-- @proof {"checkedAt":["windows_ios_compiler._download_verified"],"claim":"Downloaded bytes match the expected digest before atomic promotion; mismatch never promotes a destination.","id":"proofs-c.mobile.download-digest","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"post"}
-- @proof {"checkedAt":["windows_ios_compiler._write_info_plist -> proofs_c_mobile.check_plist"],"claim":"Persisted plist exactly matches identity and iPhoneOS platform metadata.","id":"proofs-c.mobile.metadata","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"post"}
-- @proof {"checkedAt":["windows_ios_compiler._zip_payload -> proofs_c_mobile.check_package"],"claim":"IPA archive contains exactly the app files under Payload with unchanged bytes.","id":"proofs-c.mobile.package","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"post"}
-- @proof {"checkedAt":["windows_ios_compiler._safe_copy_web_assets -> proofs_c_mobile.check_web_assets"],"claim":"Assets stage inside the app www directory and root-relative links become local links.","id":"proofs-c.mobile.web-assets","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"post"}
-- @proof {"checkedAt":["windows_ios_compiler._clean_error"],"claim":"Failure receipts strip terminal control codes and retain bounded useful text.","id":"proofs-c.mobile.error-text","impact":["local app source","Mobile Studio authoring","build capsule","package receipts"],"phase":"post"}
-- @proof {"checkedAt":["web_backend.FluxioWebBackend.dispatch -> proofs_c_mobile.check_backend"],"claim":"Mobile authoring, status and compiler configuration commands retain requested workspace, app identity, current recognition and preferences.","id":"proofs-c.mobile.backend-wiring","impact":["authenticated command API","Mobile Studio source and status","compiler preferences"],"phase":"post"}
