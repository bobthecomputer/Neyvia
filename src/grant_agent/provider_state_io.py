from __future__ import annotations

import ctypes
import errno
import os
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


PROVIDER_STATE_MAX_BYTES = 8 * 1024 * 1024
_CONTROL_DIRECTORY_NAME = ".agent_control"


def _link_like(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(callable(is_junction) and is_junction())


class ProviderStateDirectory:
    """Anchored `.agent_control` directory used for one state transaction."""

    def __init__(
        self,
        path: Path,
        *,
        descriptor: int | None = None,
        windows_handles: tuple[int, ...] = (),
    ) -> None:
        self.path = path
        self.descriptor = descriptor
        self.windows_handles = windows_handles

    @staticmethod
    def _clean_name(name: str) -> str:
        clean = str(name or "")
        if not clean or clean in {".", ".."} or Path(clean).name != clean:
            raise RuntimeError("Provider state file name is invalid.")
        return clean

    def _full_path(self, name: str) -> Path:
        return self.path / self._clean_name(name)

    def _stat(self, name: str) -> os.stat_result | None:
        clean = self._clean_name(name)
        try:
            if self.descriptor is not None:
                return os.stat(
                    clean,
                    dir_fd=self.descriptor,
                    follow_symlinks=False,
                )
            target = self._full_path(clean)
            if _link_like(target):
                raise RuntimeError(
                    "Provider authentication state is a symbolic link or junction. "
                    "Neyvia refused to follow it."
                )
            return target.lstat()
        except FileNotFoundError:
            return None
        except RuntimeError:
            raise
        except OSError as exc:
            raise RuntimeError(
                "Provider authentication state cannot be inspected safely: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    def exists(self, name: str) -> bool:
        info = self._stat(name)
        if info is None:
            return False
        if stat.S_ISLNK(info.st_mode):
            raise RuntimeError(
                "Provider authentication state is a symbolic link. Neyvia refused "
                "to follow it."
            )
        if not stat.S_ISREG(info.st_mode):
            raise RuntimeError(
                "Provider authentication state is not a regular file. Neyvia "
                "preserved it for recovery."
            )
        return True

    def open_file(
        self,
        name: str,
        flags: int,
        *,
        mode: int = 0o600,
        create_new: bool = False,
        create_if_missing: bool = False,
    ) -> int:
        clean = self._clean_name(name)
        open_flags = flags | getattr(os, "O_BINARY", 0)
        if create_new:
            open_flags |= os.O_CREAT | os.O_EXCL
        elif create_if_missing:
            open_flags |= os.O_CREAT
        if os.name == "nt":
            descriptor = _open_windows_regular_file(
                self._full_path(clean),
                open_flags,
                create_new=create_new,
                create_if_missing=create_if_missing,
            )
        elif self.descriptor is not None:
            open_flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            try:
                descriptor = os.open(
                    clean,
                    open_flags,
                    mode,
                    dir_fd=self.descriptor,
                )
            except OSError as exc:
                if exc.errno in {errno.ELOOP, errno.EMLINK}:
                    raise RuntimeError(
                        "Provider authentication state is a symbolic link. Neyvia "
                        "refused to follow it."
                    ) from exc
                raise
        else:
            target = self._full_path(clean)
            if _link_like(target):
                raise RuntimeError(
                    "Provider authentication state is a symbolic link or junction. "
                    "Neyvia refused to follow it."
                )
            descriptor = os.open(target, open_flags, mode)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            os.close(descriptor)
            raise RuntimeError(
                "Provider authentication state is not a regular file. Neyvia "
                "preserved it for recovery."
            )
        return descriptor

    def read_text(
        self,
        name: str,
        *,
        missing_ok: bool = False,
        max_bytes: int = PROVIDER_STATE_MAX_BYTES,
    ) -> str | None:
        try:
            descriptor = self.open_file(name, os.O_RDONLY)
        except FileNotFoundError:
            if missing_ok:
                return None
            raise
        try:
            if os.fstat(descriptor).st_size > max_bytes:
                raise RuntimeError(
                    "Provider authentication state exceeds the bounded read limit. "
                    "Neyvia preserved it for recovery."
                )
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                data = handle.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise RuntimeError(
                    "Provider authentication state exceeds the bounded read limit. "
                    "Neyvia preserved it for recovery."
                )
            try:
                return data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise RuntimeError(
                    "Provider authentication state is not valid UTF-8. Neyvia "
                    "preserved it for recovery."
                ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def atomic_write_text(self, name: str, text: str) -> None:
        clean = self._clean_name(name)
        temporary_name = f".{clean}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
        descriptor = -1
        try:
            descriptor = self.open_file(
                temporary_name,
                os.O_WRONLY,
                mode=0o600,
                create_new=True,
            )
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(text.encode("utf-8"))
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
            self.exists(clean)
            if self.descriptor is not None:
                os.replace(
                    temporary_name,
                    clean,
                    src_dir_fd=self.descriptor,
                    dst_dir_fd=self.descriptor,
                )
                try:
                    os.chmod(
                        clean,
                        0o600,
                        dir_fd=self.descriptor,
                        follow_symlinks=False,
                    )
                except (NotImplementedError, OSError, TypeError):
                    pass
                try:
                    os.fsync(self.descriptor)
                except OSError:
                    pass
            else:
                destination = self._full_path(clean)
                os.replace(self._full_path(temporary_name), destination)
                try:
                    os.chmod(destination, 0o600)
                except OSError:
                    pass
        finally:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            self.unlink(temporary_name, missing_ok=True)

    def unlink(self, name: str, *, missing_ok: bool) -> None:
        clean = self._clean_name(name)
        try:
            if self.descriptor is not None:
                os.unlink(clean, dir_fd=self.descriptor)
            else:
                self._full_path(clean).unlink()
        except FileNotFoundError:
            if not missing_ok:
                raise


def _provider_state_path_parts(path: Path) -> tuple[Path, Path]:
    target = Path(path)
    control = target.parent
    workspace = control.parent
    if control.name != _CONTROL_DIRECTORY_NAME or not target.name:
        raise RuntimeError(
            "Provider state path must be a direct child of the workspace "
            "`.agent_control` directory."
        )
    return workspace, control


def _directory_error(exc: OSError) -> RuntimeError:
    if exc.errno in {errno.ELOOP, errno.EMLINK}:
        return RuntimeError(
            "Provider authentication control directory is a symbolic link. "
            "Neyvia refused to read or write provider state outside the workspace."
        )
    if exc.errno == errno.ENOTDIR:
        return RuntimeError(
            "Provider authentication control path is not a directory. Neyvia "
            "preserved the workspace instead of replacing or following it."
        )
    return RuntimeError(
        "Provider authentication control directory cannot be anchored safely: "
        f"{type(exc).__name__}: {exc}"
    )


if os.name == "nt":
    import msvcrt as _msvcrt
    from ctypes import wintypes as _wintypes

    class _WindowsFileTime(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", _wintypes.DWORD),
            ("dwHighDateTime", _wintypes.DWORD),
        ]

    class _WindowsByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", _wintypes.DWORD),
            ("ftCreationTime", _WindowsFileTime),
            ("ftLastAccessTime", _WindowsFileTime),
            ("ftLastWriteTime", _WindowsFileTime),
            ("dwVolumeSerialNumber", _wintypes.DWORD),
            ("nFileSizeHigh", _wintypes.DWORD),
            ("nFileSizeLow", _wintypes.DWORD),
            ("nNumberOfLinks", _wintypes.DWORD),
            ("nFileIndexHigh", _wintypes.DWORD),
            ("nFileIndexLow", _wintypes.DWORD),
        ]

    _WINDOWS_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _WINDOWS_CREATE_FILE = _WINDOWS_KERNEL32.CreateFileW
    _WINDOWS_CREATE_FILE.argtypes = [
        _wintypes.LPCWSTR,
        _wintypes.DWORD,
        _wintypes.DWORD,
        _wintypes.LPVOID,
        _wintypes.DWORD,
        _wintypes.DWORD,
        _wintypes.HANDLE,
    ]
    _WINDOWS_CREATE_FILE.restype = _wintypes.HANDLE
    _WINDOWS_GET_FILE_INFORMATION = _WINDOWS_KERNEL32.GetFileInformationByHandle
    _WINDOWS_GET_FILE_INFORMATION.argtypes = [
        _wintypes.HANDLE,
        ctypes.POINTER(_WindowsByHandleFileInformation),
    ]
    _WINDOWS_GET_FILE_INFORMATION.restype = _wintypes.BOOL
    _WINDOWS_CLOSE_HANDLE = _WINDOWS_KERNEL32.CloseHandle
    _WINDOWS_CLOSE_HANDLE.argtypes = [_wintypes.HANDLE]
    _WINDOWS_CLOSE_HANDLE.restype = _wintypes.BOOL
else:  # pragma: no cover - Windows declarations are exercised on Windows CI
    _msvcrt = None
    _wintypes = None
    _WINDOWS_CREATE_FILE = None
    _WINDOWS_GET_FILE_INFORMATION = None
    _WINDOWS_CLOSE_HANDLE = None

_WINDOWS_GENERIC_READ = 0x80000000
_WINDOWS_GENERIC_WRITE = 0x40000000
_WINDOWS_FILE_READ_ATTRIBUTES = 0x00000080
_WINDOWS_FILE_SHARE_READ = 0x00000001
_WINDOWS_FILE_SHARE_WRITE = 0x00000002
_WINDOWS_FILE_SHARE_DELETE = 0x00000004
_WINDOWS_CREATE_NEW = 1
_WINDOWS_CREATE_ALWAYS = 2
_WINDOWS_OPEN_EXISTING = 3
_WINDOWS_OPEN_ALWAYS = 4
_WINDOWS_TRUNCATE_EXISTING = 5
_WINDOWS_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_WINDOWS_FILE_ATTRIBUTE_NORMAL = 0x00000080
_WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_WINDOWS_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_WINDOWS_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_WINDOWS_ERROR_FILE_NOT_FOUND = 2
_WINDOWS_ERROR_PATH_NOT_FOUND = 3
_WINDOWS_ERROR_ACCESS_DENIED = 5
_WINDOWS_ERROR_FILE_EXISTS = 80
_WINDOWS_ERROR_ALREADY_EXISTS = 183


def _windows_handle_value(handle: object) -> int:
    if isinstance(handle, int):
        return handle
    value = getattr(handle, "value", None)
    if value is None:
        return 0
    return int(value)


def _windows_error_message(error: int) -> str:
    try:
        message = ctypes.FormatError(error).strip()
    except (AttributeError, OSError):
        message = ""
    return message or os.strerror(error)


def _raise_windows_open_error(error: int, path: Path) -> None:
    message = _windows_error_message(error)
    if error in {_WINDOWS_ERROR_FILE_NOT_FOUND, _WINDOWS_ERROR_PATH_NOT_FOUND}:
        raise FileNotFoundError(error, message, str(path))
    if error in {_WINDOWS_ERROR_FILE_EXISTS, _WINDOWS_ERROR_ALREADY_EXISTS}:
        raise FileExistsError(error, message, str(path))
    if error == _WINDOWS_ERROR_ACCESS_DENIED:
        raise PermissionError(error, message, str(path))
    raise OSError(error, message, str(path))


def _close_windows_handle(handle: int) -> None:
    if os.name != "nt" or handle in {0, _WINDOWS_INVALID_HANDLE_VALUE}:
        return
    assert _WINDOWS_CLOSE_HANDLE is not None
    assert _wintypes is not None
    _WINDOWS_CLOSE_HANDLE(_wintypes.HANDLE(handle))


def _windows_file_information(handle: int) -> object:
    assert _WINDOWS_GET_FILE_INFORMATION is not None
    assert _wintypes is not None
    information = _WindowsByHandleFileInformation()
    if not _WINDOWS_GET_FILE_INFORMATION(
        _wintypes.HANDLE(handle),
        ctypes.byref(information),
    ):
        error = ctypes.get_last_error()
        raise OSError(error, _windows_error_message(error))
    return information


def _open_windows_handle(
    path: Path,
    *,
    desired_access: int,
    share_mode: int,
    creation_disposition: int,
    flags_and_attributes: int,
) -> int:
    assert _WINDOWS_CREATE_FILE is not None
    handle = _WINDOWS_CREATE_FILE(
        str(path),
        desired_access,
        share_mode,
        None,
        creation_disposition,
        flags_and_attributes,
        None,
    )
    handle_value = _windows_handle_value(handle)
    if handle_value == _WINDOWS_INVALID_HANDLE_VALUE:
        _raise_windows_open_error(ctypes.get_last_error(), path)
    return handle_value


def _open_windows_directory(path: Path) -> int:
    handle = _open_windows_handle(
        path,
        desired_access=_WINDOWS_FILE_READ_ATTRIBUTES,
        share_mode=_WINDOWS_FILE_SHARE_READ | _WINDOWS_FILE_SHARE_WRITE,
        creation_disposition=_WINDOWS_OPEN_EXISTING,
        flags_and_attributes=(
            _WINDOWS_FILE_FLAG_BACKUP_SEMANTICS
            | _WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT
        ),
    )
    try:
        information = _windows_file_information(handle)
        attributes = int(information.dwFileAttributes)
        if attributes & _WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT:
            raise RuntimeError(
                "Provider authentication control directory is a symbolic link or "
                "junction. Neyvia refused to follow it."
            )
        if not attributes & _WINDOWS_FILE_ATTRIBUTE_DIRECTORY:
            raise RuntimeError(
                "Provider authentication control path is not a directory. Neyvia "
                "preserved the workspace instead of replacing or following it."
            )
        return handle
    except BaseException:
        _close_windows_handle(handle)
        raise


def _open_windows_regular_file(
    path: Path,
    flags: int,
    *,
    create_new: bool,
    create_if_missing: bool,
) -> int:
    """Open the exact Windows leaf without following a reparse-point swap."""

    assert _msvcrt is not None
    access_mode = flags & (os.O_WRONLY | os.O_RDWR)
    if access_mode == os.O_RDONLY:
        desired_access = _WINDOWS_GENERIC_READ
        share_mode = (
            _WINDOWS_FILE_SHARE_READ
            | _WINDOWS_FILE_SHARE_WRITE
            | _WINDOWS_FILE_SHARE_DELETE
        )
    elif access_mode == os.O_WRONLY:
        desired_access = _WINDOWS_GENERIC_WRITE
        share_mode = _WINDOWS_FILE_SHARE_READ | _WINDOWS_FILE_SHARE_WRITE
    elif access_mode == os.O_RDWR:
        desired_access = _WINDOWS_GENERIC_READ | _WINDOWS_GENERIC_WRITE
        share_mode = _WINDOWS_FILE_SHARE_READ | _WINDOWS_FILE_SHARE_WRITE
    else:  # pragma: no cover - O_WRONLY/O_RDWR bits are exhaustive
        raise RuntimeError("Unsupported provider-state file access mode.")

    if create_new:
        disposition = _WINDOWS_CREATE_NEW
    elif flags & os.O_TRUNC:
        disposition = (
            _WINDOWS_CREATE_ALWAYS
            if create_if_missing
            else _WINDOWS_TRUNCATE_EXISTING
        )
    elif create_if_missing:
        disposition = _WINDOWS_OPEN_ALWAYS
    else:
        disposition = _WINDOWS_OPEN_EXISTING

    handle = _open_windows_handle(
        path,
        desired_access=desired_access,
        share_mode=share_mode,
        creation_disposition=disposition,
        flags_and_attributes=(
            _WINDOWS_FILE_ATTRIBUTE_NORMAL
            | _WINDOWS_FILE_FLAG_BACKUP_SEMANTICS
            | _WINDOWS_FILE_FLAG_OPEN_REPARSE_POINT
        ),
    )
    try:
        information = _windows_file_information(handle)
        attributes = int(information.dwFileAttributes)
        if attributes & _WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT:
            raise RuntimeError(
                "Provider authentication state is a symbolic link or junction. "
                "Neyvia refused to follow it."
            )
        if attributes & _WINDOWS_FILE_ATTRIBUTE_DIRECTORY:
            raise RuntimeError(
                "Provider authentication state is not a regular file. Neyvia "
                "preserved it for recovery."
            )
        descriptor_flags = access_mode | getattr(os, "O_BINARY", 0)
        if flags & getattr(os, "O_APPEND", 0):
            descriptor_flags |= os.O_APPEND
        if hasattr(os, "O_NOINHERIT"):
            descriptor_flags |= os.O_NOINHERIT
        descriptor = _msvcrt.open_osfhandle(handle, descriptor_flags)
        handle = _WINDOWS_INVALID_HANDLE_VALUE
        return descriptor
    finally:
        _close_windows_handle(handle)


@contextmanager
def open_provider_state_directory(
    path: Path,
    *,
    create: bool,
) -> Iterator[ProviderStateDirectory | None]:
    """Anchor workspace/control directories before relative provider-state I/O."""

    workspace, control = _provider_state_path_parts(Path(path))
    if os.name == "nt":
        handles: list[int] = []
        try:
            handles.append(_open_windows_directory(workspace))
            try:
                if _link_like(control):
                    raise RuntimeError(
                        "Provider authentication control directory is a symbolic "
                        "link or junction. Neyvia refused to follow it."
                    )
                if not control.exists():
                    if not create:
                        yield None
                        return
                    try:
                        control.mkdir(mode=0o700)
                    except FileExistsError:
                        pass
                handles.append(_open_windows_directory(control))
            except FileNotFoundError:
                if not create:
                    yield None
                    return
                raise
            yield ProviderStateDirectory(
                control,
                windows_handles=tuple(handles),
            )
        except RuntimeError:
            raise
        except OSError as exc:
            raise _directory_error(exc) from exc
        finally:
            for handle in reversed(handles):
                _close_windows_handle(handle)
        return

    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    workspace_descriptor = -1
    control_descriptor = -1
    try:
        workspace_descriptor = os.open(workspace, flags)
        try:
            control_info = os.stat(
                _CONTROL_DIRECTORY_NAME,
                dir_fd=workspace_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            if not create:
                yield None
                return
            try:
                os.mkdir(
                    _CONTROL_DIRECTORY_NAME,
                    mode=0o700,
                    dir_fd=workspace_descriptor,
                )
            except FileExistsError:
                pass
            control_info = os.stat(
                _CONTROL_DIRECTORY_NAME,
                dir_fd=workspace_descriptor,
                follow_symlinks=False,
            )
        if stat.S_ISLNK(control_info.st_mode):
            raise RuntimeError(
                "Provider authentication control directory is a symbolic link. "
                "Neyvia refused to read or write provider state outside the workspace."
            )
        if not stat.S_ISDIR(control_info.st_mode):
            raise RuntimeError(
                "Provider authentication control path is not a directory. Neyvia "
                "preserved the workspace instead of replacing or following it."
            )
        control_descriptor = os.open(
            _CONTROL_DIRECTORY_NAME,
            flags,
            dir_fd=workspace_descriptor,
        )
        if not stat.S_ISDIR(os.fstat(control_descriptor).st_mode):
            raise RuntimeError(
                "Provider authentication control path is not a directory. Neyvia "
                "preserved the workspace instead of replacing or following it."
            )
        try:
            os.fchmod(control_descriptor, 0o700)
        except OSError:
            pass
        yield ProviderStateDirectory(
            control,
            descriptor=control_descriptor,
        )
    except RuntimeError:
        raise
    except OSError as exc:
        raise _directory_error(exc) from exc
    finally:
        if control_descriptor >= 0:
            try:
                os.close(control_descriptor)
            except OSError:
                pass
        if workspace_descriptor >= 0:
            try:
                os.close(workspace_descriptor)
            except OSError:
                pass
