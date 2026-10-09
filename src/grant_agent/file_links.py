"""Materialize an owned local dependency without requiring symlink privilege."""
from __future__ import annotations
import errno
import os
import shutil
from pathlib import Path


def link_or_copy(source: str | Path, destination: str | Path) -> str:
    """Prefer a symlink, then a file hardlink, then an independent copy.

    Never overwrite a destination. Only permission/unsupported-link errors
    select a fallback; missing inputs, full disks and other failures propagate.
    Callers must authorize the source tree before materializing a directory.
    """
    source, destination = Path(source).resolve(strict=True), Path(destination)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    directory = source.is_dir()
    try:
        destination.symlink_to(source, target_is_directory=directory)
        return "symlink"
    except OSError as error:
        if getattr(error, "winerror", None) != 1314 and error.errno not in {errno.EPERM, errno.EACCES, errno.ENOTSUP}:
            raise
    if not directory:
        try:
            os.link(source, destination)
            return "hardlink"
        except OSError as error:
            if error.errno not in {errno.EPERM, errno.EACCES, errno.ENOTSUP, errno.EXDEV}:
                raise
        # Exclusive creation preserves the no-overwrite contract under races.
        with source.open("rb") as incoming, destination.open("xb") as outgoing:
            shutil.copyfileobj(incoming, outgoing)
        shutil.copystat(source, destination)
    else:
        shutil.copytree(source, destination)
    return "copy"
