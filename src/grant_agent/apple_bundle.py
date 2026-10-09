"""Apple artifact outcomes and portable ad-hoc signing. No host-execution claim.

Parse bytes independently of compiler logs; verify every code page and sealed
resource. macOS signing uses the public Mach-O and Code Signing blob formats.
"""
from __future__ import annotations
import hashlib
import math
import plistlib
import struct
from pathlib import Path

ARCHES = {0x100000C: "arm64", 0x1000007: "x86_64"}


def slices(data: bytes) -> list[bytes]:
    if data[:4] == b"\xca\xfe\xba\xbe":
        count = struct.unpack_from(">I", data, 4)[0]
        if count != 2:
            raise ValueError("Universal app must have exactly two slices")
        result, ranges = [], []
        for i in range(count):
            cpu, subtype, offset, size, align = struct.unpack_from(">5I", data, 8 + 20 * i)
            if offset % (1 << align) or offset < 8 + 20 * count or offset + size > len(data):
                raise ValueError("Invalid universal slice range")
            if any(offset < end and start < offset + size for start, end in ranges):
                raise ValueError("Overlapping universal slices")
            part = data[offset:offset + size]
            if struct.unpack_from("<II", part, 4) != (cpu, subtype):
                raise ValueError("Fat header differs from contained architecture")
            ranges.append((offset, offset + size)); result.append(part)
        return result
    return [data]


def commands(data: bytes) -> list[tuple[int, int, bytes]]:
    if data[:4] != b"\xcf\xfa\xed\xfe" or len(data) < 32:
        raise ValueError("Expected 64-bit little-endian Mach-O")
    _, cpu, _, kind, count, size, _, _ = struct.unpack_from("<8I", data)
    if cpu not in ARCHES or kind != 2 or 32 + size > len(data):
        raise ValueError("Invalid Mach-O executable header")
    offset, result = 32, []
    for _ in range(count):
        command, length = struct.unpack_from("<II", data, offset)
        if length < 8 or length % 8 or offset + length > 32 + size:
            raise ValueError("Invalid Mach-O load command")
        result.append((command, offset, data[offset:offset + length])); offset += length
    if offset != 32 + size:
        raise ValueError("Mach-O command size mismatch")
    return result


def _digest(kind: int, data: bytes) -> bytes:
    if kind == 1:
        return hashlib.sha1(data).digest()
    if kind in {2, 3}:
        return hashlib.sha256(data).digest()[:20 if kind == 3 else 32]
    raise ValueError("Unsupported code-signing hash algorithm")


def verify_signature(data: bytes, info: bytes, resources: bytes) -> dict:
    signature = next((part for cmd, _, part in commands(data) if cmd == 0x1D), None)
    if signature is None:
        raise ValueError("Missing LC_CODE_SIGNATURE")
    offset, size = struct.unpack_from("<II", signature, 8)
    if offset + size != len(data):
        raise ValueError("Signature does not seal the whole executable")
    blob = data[offset:offset + size]
    magic, length, count = struct.unpack_from(">III", blob)
    if magic != 0xFADE0CC0 or length > size or 12 + count * 8 > length:
        raise ValueError("Invalid signature SuperBlob")
    directories = []
    for i in range(count):
        slot, position = struct.unpack_from(">II", blob, 12 + 8 * i)
        if position < 12 + count * 8 or position + 8 > length:
            raise ValueError("Invalid signature blob offset")
        submagic, sublength = struct.unpack_from(">II", blob, position)
        if position + sublength > length:
            raise ValueError("Signature blob extends outside seal")
        if submagic != 0xFADE0C02:
            continue
        cd = blob[position:position + sublength]
        _, _, version, flags, hashes, identity, specials, pages, limit = struct.unpack_from(">9I", cd)
        hash_size, hash_type, _, page_log = struct.unpack_from(">4B", cd, 36)
        page_size = 1 << page_log
        if page_log > 16 or limit != offset or pages != math.ceil(limit / page_size):
            raise ValueError("CodeDirectory coverage mismatch")
        if hashes - specials * hash_size < 44 or hashes + pages * hash_size > len(cd):
            raise ValueError("CodeDirectory hash table out of bounds")
        if len(_digest(hash_type, b"")) != hash_size or identity >= len(cd):
            raise ValueError("Invalid CodeDirectory header")
        for page in range(pages):
            expected = cd[hashes + page * hash_size:hashes + (page + 1) * hash_size]
            if _digest(hash_type, data[page * page_size:min(limit, (page + 1) * page_size)]) != expected:
                raise ValueError("Executable page hash mismatch")
        for special, value in ((1, info), (3, resources)):
            if specials < special or not value:
                raise ValueError("Bundle metadata/resources are not sealed")
            if cd[hashes - special * hash_size:hashes - (special - 1) * hash_size] != _digest(hash_type, value):
                raise ValueError("Bundle special-slot hash mismatch")
        directories.append({"hashType": hash_type, "pages": pages, "adhoc": bool(flags & 2)})
    if not directories:
        raise ValueError("No verified CodeDirectory")
    return {"verified": True, "directories": directories, "trust": "hash integrity only; Apple trust/installation untested"}


def sign_macos_slice(path: Path, identifier: str, info: bytes, resources: bytes) -> None:
    data = bytearray(path.read_bytes())
    signature = next((row for row in commands(data) if row[0] == 0x1D), None)
    if not signature:
        raise ValueError("Link with -adhoc_codesign to reserve a signature load command")
    _, command_offset, command = signature
    limit = struct.unpack_from("<I", command, 8)[0]
    identity = identifier.encode() + b"\0"
    pages = math.ceil(limit / 4096)
    hash_offset = 88 + len(identity) + 3 * 32
    cd_size = hash_offset + pages * 32
    blob_size = 20 + cd_size
    struct.pack_into("<II", data, command_offset + 8, limit, blob_size)
    text_base, text_size = 0, 0
    for cmd, pos, part in commands(data):
        if cmd == 0x19 and part[8:24].rstrip(b"\0") == b"__TEXT":
            text_base, text_size = struct.unpack_from("<QQ", part, 40)
        if cmd == 0x19 and part[8:24].rstrip(b"\0") == b"__LINKEDIT":
            file_offset = struct.unpack_from("<Q", part, 40)[0]
            file_size = limit + blob_size - file_offset
            struct.pack_into("<Q", data, pos + 32, math.ceil(file_size / 16384) * 16384)
            struct.pack_into("<Q", data, pos + 48, file_size)
    cd = struct.pack(">9I4B4I4Q", 0xFADE0C02, cd_size, 0x20400, 2, hash_offset, 88, 3, pages, limit,
                     32, 2, 0, 12, 0, 0, 0, 0, 0, text_base, text_size, 1)
    # Special hashes are stored in reverse slot order: resources, requirements, Info.
    cd += identity + hashlib.sha256(resources).digest() + bytes(32) + hashlib.sha256(info).digest()
    cd += b"".join(hashlib.sha256(data[i:min(i + 4096, limit)]).digest() for i in range(0, limit, 4096))
    blob = struct.pack(">5I", 0xFADE0CC0, blob_size, 1, 0, 20) + cd
    path.write_bytes(data[:limit] + blob)
    verify_signature(path.read_bytes(), info, resources)


def seal_resources(contents: Path) -> bytes:
    files = {}
    for path in sorted(contents.rglob("*")):
        if path.is_symlink():
            raise ValueError("Bundle resources must not contain symlinks")
        if path.is_file() and path.name != "Info.plist" and not {"MacOS", "_CodeSignature"}.intersection(path.relative_to(contents).parts):
            files[path.relative_to(contents).as_posix()] = {"hash2": hashlib.sha256(path.read_bytes()).digest()}
    return plistlib.dumps({"files2": files, "rules2": {"^Resources/": True, "^.*": True,
                          "^Info\\.plist$": {"omit": True, "weight": 20}}}, sort_keys=True)


def universal(paths: list[Path], output: Path) -> None:
    parts = [path.read_bytes() for path in paths]
    offset, entries, payload = 16384, [], bytearray(16384)
    for part in parts:
        cpu, subtype = struct.unpack_from("<II", part, 4)
        entries.append(struct.pack(">5I", cpu, subtype, offset, len(part), 14))
        payload.extend(part)
        offset += len(part)
        padding = (-offset) % 16384
        payload.extend(bytes(padding)); offset += padding
    header = struct.pack(">II", 0xCAFEBABE, len(parts)) + b"".join(entries)
    payload[:len(header)] = header
    output.write_bytes(payload)


def verify_bundle(app: str | Path, target: str) -> dict:
    app = Path(app).resolve()
    contents = app / "Contents" if target == "macos" else app
    info_bytes = (contents / "Info.plist").read_bytes()
    info = plistlib.loads(info_bytes)
    for key in ("CFBundleIdentifier", "CFBundleExecutable", "CFBundleName", "CFBundleVersion"):
        if not isinstance(info.get(key), str) or not info[key]:
            raise ValueError("Missing bundle key: " + key)
    executable_name = info["CFBundleExecutable"]
    if Path(executable_name).name != executable_name or info.get("CFBundlePackageType") != "APPL":
        raise ValueError("Invalid executable name or package type")
    executable = contents / "MacOS" / executable_name if target == "macos" else contents / executable_name
    resources_path = contents / "_CodeSignature/CodeResources"
    resources_bytes = resources_path.read_bytes()
    resources = plistlib.loads(resources_bytes)
    seals = resources.get("files2") or resources.get("files") or {}
    if not seals:
        raise ValueError("Empty resource seal")
    sealed_paths = set()
    for name, record in seals.items():
        resource = (contents / name).resolve()
        resource.relative_to(contents)
        value = resource.read_bytes()
        expected = record if isinstance(record, bytes) else record.get("hash2") or record.get("hash")
        if not expected or (hashlib.sha256(value).digest() if len(expected) == 32 else hashlib.sha1(value).digest()) != expected:
            raise ValueError("Resource hash mismatch: " + name)
        sealed_paths.add(resource)
    web = contents / "Resources/www" if target == "macos" else contents / "www"
    if not (web / "index.html").is_file():
        raise ValueError("Missing bundled web entry")
    if any(p.resolve() not in sealed_paths for p in web.rglob("*") if p.is_file()):
        raise ValueError("Unsealed web resource")
    data, outcomes = executable.read_bytes(), []
    for part in slices(data):
        platform, entry, dylibs = None, False, []
        for cmd, _, value in commands(part):
            if cmd == 0x32:
                platform = struct.unpack_from("<I", value, 8)[0]
            if cmd == 0x80000028:
                entry = struct.unpack_from("<Q", value, 8)[0] < len(part)
            if cmd == 0xC:
                name_offset = struct.unpack_from("<I", value, 8)[0]
                dylibs.append(value[name_offset:].split(b"\0")[0].decode())
        if platform != (1 if target == "macos" else 2) or not entry:
            raise ValueError("Wrong target platform or entrypoint")
        if "/usr/lib/libobjc.A.dylib" not in dylibs or "/usr/lib/libSystem.B.dylib" not in dylibs:
            raise ValueError("Missing public runtime dependencies")
        outcomes.append({"architecture": ARCHES[struct.unpack_from("<I", part, 4)[0]], "platform": platform,
                         "dylibs": dylibs, "signature": verify_signature(part, info_bytes, resources_bytes)})
    expected = {"arm64", "x86_64"} if target == "macos" else {"arm64"}
    if {row["architecture"] for row in outcomes} != expected or len(outcomes) != len(expected):
        raise ValueError("Unexpected architectures")
    if target == "ipados" and (info.get("UIDeviceFamily") != [2] or info.get("UIRequiresFullScreen") is not False):
        raise ValueError("iPad idiom/multitasking metadata missing")
    if target == "macos" and (info.get("CFBundleSupportedPlatforms") != ["MacOSX"] or not info.get("LSMinimumSystemVersion")):
        raise ValueError("Missing Mac platform metadata")
    return {"ok": True, "target": target, "bundle": str(app), "sha256": hashlib.sha256(data).hexdigest(),
            "slices": outcomes, "sealedResources": len(seals), "nativeExecutionVerified": False}
