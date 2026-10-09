"""Install bounded official Android SDK archives on D: and inspect native discovery."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
import time

SDK = Path(r'D:\Android\Sdk')
OUT = Path(r'D:\NeyviaRuns\INTN\android')
BASE = 'https://dl.google.com/android/repository/'
CAP = 200_000_000
PACKAGES = {'cmdline-tools;latest': 'cmdline-tools/latest', 'platform-tools': 'platform-tools', 'build-tools;35.0.0': 'build-tools/35.0.0', 'platforms;android-35': 'platforms/android-35'}


def download(url, path, limit, expected=None):
    with urllib.request.urlopen(url, timeout=90) as response, path.open('wb') as output:
        if int(response.headers.get('Content-Length', '0')) > limit:
            raise ValueError('Archive exceeds download cap')
        total = 0
        while block := response.read(1024*1024):
            total += len(block)
            if total > limit:
                raise ValueError('Download exceeded cap')
            output.write(block)
    if expected and hashlib.sha1(path.read_bytes()).hexdigest() != expected:
        raise ValueError('Official repository archive hash differs')
    return total


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    SDK.mkdir(parents=True, exist_ok=True)
    repository = OUT / 'repository.xml'
    download(BASE + 'repository2-3.xml', repository, 8_000_000)
    tree = ET.parse(repository).getroot()
    for node in tree.iter():
        node.tag = node.tag.split('}')[-1]
    records = []
    for identity, relative in PACKAGES.items():
        candidates = [node for node in tree.findall('remotePackage') if node.attrib['path'] == identity]
        if not candidates:
            raise ValueError('Official package missing: ' + identity)
        package = candidates[0]
        archives = [a for a in package.findall('./archives/archive') if a.findtext('host-os') in ('windows', None)]
        archive = archives[0].find('complete')
        size, checksum, name = int(archive.findtext('size')), archive.findtext('checksum'), archive.findtext('url')
        if size > CAP or '/' in name or '\\' in name:
            raise ValueError('Package exceeds cap or has unexpected archive path')
        target = (SDK / relative).resolve()
        target.relative_to(SDK.resolve())
        if target.exists() and any(target.iterdir()):
            records.append({'package': identity, 'path': str(target), 'status': 'existing-preserved'})
            continue
        compressed = OUT / name
        if not compressed.is_file() or hashlib.sha1(compressed.read_bytes()).hexdigest() != checksum:
            download(BASE + name, compressed, CAP, checksum)
        stage = OUT / ('unpack-' + identity.replace(';', '-'))
        stage.mkdir(exist_ok=True)
        with zipfile.ZipFile(compressed) as source:
            if sum(item.file_size for item in source.infolist()) > 1_000_000_000:
                raise ValueError('Unpacked package exceeds bound')
            for item in source.infolist():
                destination = (stage / item.filename).resolve()
                if not destination.is_relative_to(stage.resolve()) or (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('Archive traversal or linked entry refused')
            source.extractall(stage)
        contents = [p for p in stage.iterdir() if p.is_dir()]
        if len(contents) != 1:
            raise ValueError('SDK archive must contain one package folder')
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            retained = OUT / ('preserved-' + identity.replace(';', '-') + '-' + str(time.time_ns()))
            retained.resolve().relative_to(OUT.resolve())
            target.rename(retained)
        contents[0].resolve().relative_to(OUT.resolve())
        contents[0].rename(target)
        records.append({'package': identity, 'path': str(target), 'url': BASE + name, 'bytes': size, 'sha1': checksum, 'status': 'installed'})
        (OUT / 'downloads.json').write_text(json.dumps(records, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(records[-1]), flush=True)
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
    os.environ['ANDROID_HOME'] = os.environ['ANDROID_SDK_ROOT'] = str(SDK)
    from grant_agent.neyvia_mobile_studio import android_toolchain
    tools = android_toolchain(probe_devices=False)
    receipt = {'schema':'neyvia.intn.android-toolchain.v1', 'ok':tools['ready'], 'sdkRoot':str(SDK), 'downloads':records, 'toolchain':tools, 'appFactoryOwner':'neyvia_app_sdk.build_mobile imports this exact android_toolchain observer', 'boundary':'Native toolchain discovery only; no APK build, emulator download, device install or adb server launch'}
    (OUT/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    return 0 if receipt['ok'] else 1


if __name__=='__main__':
    raise SystemExit(main())
