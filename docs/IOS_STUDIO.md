# Neyvia iOS Studio

iOS Studio makes a Windows PC the authoring and compilation machine for a
useful class of iPhone apps. Its default **Windows Native** engine compiles
Neyvia's original clean-room runtime into a real ARM64 Mach-O executable,
packages an Apple `.app`, signs it locally, and emits an `.ipa`. It does not
contact a Mac, start Xcode, or call a hosted build vendor.

The implementation is original Neyvia code, not a fork of another app builder.
It uses LLVM's Mach-O linker and a pinned, separately built signing utility as
toolchain components.

## What “compiled on Windows” means

The default compiler processes are native Windows executables: `clang.exe`,
`ld64.lld.exe`, `llvm-objdump.exe`, and `zsign.exe`. They run directly on the
Windows host. WSL2 is not installed, started, or path-mapped by this engine.
An explicit WSL2 compatibility engine remains available for machines that
already rely on the earlier toolchain.

The current runtime is a small native iOS executable that starts UIKit, creates
a `WKWebView`, and loads the app's bundled Expo/web export. The executable is
native ARM64 iOS code. The product UI is HTML, CSS, and JavaScript inside that
native container. This is deliberately narrower than compiling an arbitrary
SwiftUI or React Native native-module graph.

The Windows Native engine:

1. Uses the project's existing `dist`, `web-build`, or `build/web` export. If
   none exists, it runs a real Expo web export.
2. Compiles `native/ios/neyvia_runtime.c` for `arm64-apple-ios` with Clang.
3. Links a Mach-O executable with `ld64.lld` against clean-room text stubs for
   the public iOS runtime entry points it uses.
4. Generates a binary `Info.plist` and a standard `Payload/AppName.app` bundle.
5. Ad-hoc signs the proof build, or development-signs it with the configured
   private key/P12 and provisioning profile.
6. Packages the signed bundle as an IPA and records compiler, linker, target,
   signature, load-command, artifact hash, and executable hash evidence.

## Apple SDK and Xcode boundary

This lane does not copy or install Xcode, Apple SDK headers, or Apple SDK
libraries on Windows. That avoids pretending Xcode is a Windows application and
avoids making Apple's separately licensed SDK the hidden foundation of the
local compiler.

For full SwiftUI, CocoaPods, Expo native generation, arbitrary React Native
modules, App Store validation, and the Apple simulator, use iOS Studio's
optional private-Mac/Xcode compatibility lane. Apple controls those tools and
their distribution terms.

## Prerequisites

On Windows:

- 64-bit Windows 10/11 and enough free disk space for the LLVM archive and
  extracted tools.
- Node.js when the project needs Neyvia to create an Expo export.
- An existing Expo/React Native project with `expo.ios.bundleIdentifier`, or an
  app created in iOS Studio.

The setup action downloads the pinned official LLVM 22.1.6 Windows archive and
zsign 1.0.8 Windows release, verifies their SHA-256 digests before extraction,
and installs them under `%LOCALAPPDATA%\Neyvia\toolchains\ios-win32`. It does
not require administrator rights or modify the global `PATH`.

## First Windows-native build

1. Start Neyvia with `npm run tauri:dev` and open **iOS Studio**.
2. Select an existing app folder or create a new Expo app.
3. In **Windows Native**, choose **Direct Windows only** to enforce a build with
   no WSL process. **Automatic** also prefers Direct Windows and uses WSL2 only
   when its compatibility toolchain is already available.
4. Select **Install direct compiler**. The action stops on any download, checksum,
   extraction, compiler,
   linker, or signer failure; it does not mark a partial setup as complete.
5. Select **Compile on Windows**.
6. Inspect the completed receipt in
   `.agent_control/windows_ios_builds/<job-id>/receipt.json`.

The output folder also contains `compile.log`, `signing.log`, and
`macho-inspection.txt`. The IPA is only reported as completed after it exists,
its SHA-256 is calculated, and its executable has passed the Mach-O magic check.

## Signing for a registered iPhone

An ad-hoc signature proves the local code-signing pipeline but cannot install
the app on a normal, non-jailbroken iPhone. A device build needs assets from an
Apple Developer account:

- a private key or P12 file;
- its certificate when it is not included in the identity file;
- a provisioning profile containing the app identifier and target device.

Set those paths in **Windows Native**. If the private key or P12 has a password,
provide it only for the current process:

```powershell
$env:NEYVIA_IOS_SIGNING_PASSWORD = "temporary-password"
npm run tauri:dev
```

Neyvia never writes that password to project configuration or build logs. Real
signing assets must not be committed to source control.

## Build modes

### Compile on Windows

Produces a device-architecture ARM64 Mach-O and IPA locally. With no identity,
the result is ad-hoc signed for artifact verification. With a valid identity
and provisioning profile, the result is development signed.

### iOS Simulator (optional Mac)

Produces an unsigned `.app.zip` for Apple's iOS Simulator on a Mac. Apple does
not ship that simulator for Windows.

### Registered iPhone (optional Mac/Xcode)

Produces a development-signed IPA through Xcode. Use this for projects that
depend on arbitrary Apple frameworks, CocoaPods, or native modules outside the
Windows runtime's supported surface.

### TestFlight / App Store (optional Mac/Xcode)

Produces a distribution-signed IPA through Xcode's App Store Connect export
method. Upload and release remain explicit operations.

## Security and proof

Windows compiler settings are stored in `.agent_control/windows_ios.json`.
Only paths and non-secret build settings are stored. Build receipts are stored
under `.agent_control/windows_ios_builds/` and include:

- `host: windows-native`, `engine: win32`, and `nativeProcess: true` for the
  direct engine (or the explicit WSL2 compatibility boundary);
- compiler and Mach-O linker identity;
- ARM64 target and minimum iOS version;
- `LC_CODE_SIGNATURE` inspection result;
- signature kind and signing description;
- exact executable and IPA SHA-256 values;
- compile, signing, and Mach-O inspection paths.

The optional Mac lane keeps its separate source-capsule filtering and SSH proof
model. It excludes secrets, dependency trees, build output, links, and signing
files before transfer.

## CLI operations

After `python -m pip install -e .`:

```powershell
python -m grant_agent.cli ios-studio-create --root C:\projects --name "Pocket Atlas" --directory pocket-atlas --bundle-id com.example.pocketatlas --install-dependencies
python -m grant_agent.cli ios-studio-windows-setup --root C:\projects\pocket-atlas --engine win32
python -m grant_agent.cli ios-studio-windows-save --root C:\projects\pocket-atlas --engine win32 --minimum-ios 16.0
python -m grant_agent.cli ios-studio-status --root C:\projects\pocket-atlas
python -m grant_agent.cli ios-studio-build --root C:\projects\pocket-atlas --mode windows-native
```

Optional development-signing paths:

```powershell
python -m grant_agent.cli ios-studio-windows-save `
  --root C:\projects\pocket-atlas `
  --identity-file C:\signing\development.p12 `
  --provisioning-profile C:\signing\PocketAtlas.mobileprovision
```

Optional Xcode compatibility:

```powershell
python -m grant_agent.cli ios-studio-builder-save --root C:\projects\pocket-atlas --host mac-builder.local --user builder --remote-root "~/NeyviaBuilds"
python -m grant_agent.cli ios-studio-builder-check --root C:\projects\pocket-atlas
python -m grant_agent.cli ios-studio-build --root C:\projects\pocket-atlas --mode app-store
```

## Apple targets from Windows

Mobile Studio uses the same web-export engine for three artifact targets:

| Target | Local artifact | What is verified on Windows |
| --- | --- | --- |
| iPhone (`ios`) | ARM64 UIKit/WKWebView IPA | Payload layout, iPhoneOS load commands, metadata, executable page and resource hashes |
| iPad (`ipados`) | ARM64 IPA | Same checks, device family 2, full-screen false and tablet orientations |
| Mac (`macos`) | Universal ARM64/x86_64 AppKit/WKWebView `.app` and ZIP | Both Mach-O slices, macOS load commands, metadata, page/resource seals and ZIP execute permissions |
| Watch (`watchos`) | Unsupported | Web concept frame only; a native WatchKit renderer is required |
| Apple TV (`tvos`) | Unsupported | Web concept frame only; a native focus/remote renderer is required |
| Vision Pro (`visionos`) | Unsupported native build | Flat web concept frame only; spatial runtime/linker/signing are not implemented |

Apple documents web views on iOS, iPadOS, macOS and visionOS, and their absence
on watchOS/tvOS. Framework availability does not imply this builder implements
that platform. [Apple web-view guidance](https://developer.apple.com/design/human-interface-guidelines/web-views).

The Mac host is original C using the public Objective-C ABI. It dynamically
loads AppKit and WebKit; no Apple SDK headers/libraries are copied to Windows.
Both architectures start a window, load `Contents/Resources/www/index.html`,
support resize and standard edit/quit keys, and quit after the last window closes.
Windows checks its bytes; launch and Apple's `codesign`/Gatekeeper checks require
an actual Mac and remain unverified until exercised there.

Supply `native/AppIcon.icns` for project artwork. Otherwise the bundle uses the
existing Neyvia authoring icon. Local Mac signatures are ad-hoc, without a
Developer ID, hardened-runtime/distribution claim or notarization. Notarization
is an optional external Apple Developer workflow, not invoked by this builder.
The ZIP records Unix executable permissions; a DMG builder is not provided.

The executable chapter is `manuals/cl/mobile-studio.cl`, `apple-targets`.
`neyvia.mobile.build(platform,project,waitSeconds)` compiles, signs and packages
atomically. `neyvia.mobile.verify(platform,project)` re-reads all bundle/archive
bytes and independently verifies code-page, metadata and resource seals. Neither
action claims Apple trust, device installation, native execution or App Review.
Per-target `build-verify-preview-*` and `verify-retained-artifact-*` procedures
provide fast CL outcome contracts; successful repeated runs can be compiled
with `neyvia.manual.compile` and executed with `neyvia.manual.script.run`.

### Three simulation tiers

1. **Instant** — `neyvia.mobile.simulate(tier="instant",platform,project)` selects
   a browser frame. iPhone/iPad safe areas, rotation, dark mode, root/rem text-size
   scaling and an optional emulated web keyboard are available through
   `mobile.preview`. Mac retains fine-pointer behaviour and window chrome.
   Watch/TV/Vision are web layout concepts. These frames do not run Apple OS APIs,
   native IMEs, haptics, focus engines or spatial tracking. Fixed-pixel text may
   not respond to root/rem scaling.
2. **Optional Apple Simulator** — `mobile.simulate(tier="cloud",platform="ios"
   or "ipados",project)` creates a self-contained capsule under
   `.agent_control/apple_cloud/prepare_*`. Its workflow is outside this repo's
   active `.github/workflows` and has no push/PR schedule. The only trigger is
   manual dispatch, gated on owner `bobthecomputer`, repository variable
   `NEYVIA_APPLE_SIMULATOR_ENABLED=true`, and explicit minute/billing confirmation.
   No tool dispatches a run. Paul copies it to his own repository and reviews
   [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
   before enabling it. On a macOS runner it builds a **Simulator** executable
   (the device IPA cannot run in Simulator), creates an owned device, boots,
   installs, launches, captures PNG/video, then cleans up its device. Prepared,
   not executed in this Windows proof. Import downloaded results with
   `mobile.simulate(tier="cloud",results=<folder>,project)`; Mobile Studio shows
   the hash-checked screenshot. This is a downloaded snapshot, not live streaming
   or independent authentication of the runner receipt.
3. **Real devices** — `mobile.simulate(tier="device",platform,project)` returns
   the existing free-Apple-ID sideload guide for iPhone/iPad, or copy/extract/
   Apple-codesign/open steps for a Mac. Nothing is silently installed. A real
   iPhone/iPad needs re-signing or a valid provisioning identity; a Mac must
   accept the unnotarized bundle explicitly. Device behaviour needs device proof.

Neyvia never runs macOS in a VM on non-Apple hardware. No cloud run, publishing,
notarization or metered service is initiated by preparation.

### Portable compiler and Scroll Study proof

The default pinned setup downloads more than 200 MB and is not invoked under a
200 MB ceiling. An explicitly supplied portable installation can be used with
process-only `NEYVIA_WINDOWS_IOS_LLVM_BIN` (clang, ld64.lld, llvm-objdump) and
`NEYVIA_WINDOWS_IOS_ZSIGN`. Receipts name the actual compiler version. They do
not imply the portable compiler is the pinned default distribution.

Scroll Study's `neyvia.app.json` identity and existing `www` export are accepted
without adding Expo scaffolding: explicit `bundleIdentifier` wins; otherwise
its instance maps to `com.neyvia.<alphanumeric-instance>`. Bundle metadata is
written in build output; source remains unchanged. The local-harness fallback
is `scripts/apple_harness.py --prove --project <scroll-study> --receipt <json>`.
The isolated preview denies direct IndexedDB access: Scroll Study can render and navigate there, but reports a storage error; persisted progress in that frame is not proven. Do not remove the sandbox to hide this limit.

Final task receipts and rendered captures live under `scripts/evidence/APPLE*`;
actual bundles remain in Scroll Study's `.agent_control/windows_*_builds`.

## iOS-specific limits

- The Windows runtime hosts a web export; it does not yet compile arbitrary
  Swift, SwiftUI, Objective-C frameworks, CocoaPods, or React Native native
  modules.
- Windows cannot run Apple's iOS Simulator. Device testing needs a provisioned
  iPhone, and App Store submission should use the Xcode compatibility lane.
- App capabilities such as push notifications, HealthKit, iCloud, extensions,
  and associated domains require matching entitlements and are not yet exposed
  by Windows Native.
- A completed local receipt proves artifact construction and signature layout,
  not App Review acceptance.

## Troubleshooting

- **Download or checksum fails:** retry on a stable connection. Neyvia does not
  execute or extract a package whose SHA-256 differs from the pinned release.
- **An incomplete toolchain path exists:** preserve it for diagnosis, rename it,
  and rerun setup. Neyvia refuses to overwrite an unexpected partial install.
- **WSL2 compatibility was selected:** verify that WSL2 and a Debian-family
  distribution are installed, then enter that distribution or `default`.
- **Export fails:** install project dependencies and verify `npx expo export
  --platform web` in the project.
- **Development signing fails:** verify the P12/private key, certificate,
  provisioning profile, bundle identifier, registered device, and password.
- **The receipt is failed:** read its `error`, then inspect `compile.log` or
  `signing.log`; failed jobs remain visible instead of being hidden.

References:

- [LLVM 22.1.6 release](https://github.com/llvm/llvm-project/releases/tag/llvmorg-22.1.6)
- [LLVM Mach-O LLD](https://lld.llvm.org/MachO/index.html)
- [zsign 1.0.8](https://github.com/zhlynn/zsign/releases/tag/v1.0.8)
- [Apple Xcode and SDK agreement](https://www.apple.com/legal/sla/docs/xcode.pdf)
- [Apple Developer Program enrollment](https://developer.apple.com/help/account/membership/program-enrollment/)
