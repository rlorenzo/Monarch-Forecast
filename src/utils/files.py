"""Filesystem helpers shared by the erase paths."""

from pathlib import Path


def erase_file(path: Path) -> bool:
    """Delete ``path``, reporting whether it is gone afterwards.

    Absence is success — most of these files are never written, and a user
    who never opened demo mode has not failed to erase it. Everything else
    is failure: a permissions error, a read-only disk, or a directory
    planted where a file belongs all leave something the user asked to
    destroy sitting on disk, and the caller needs to know that before it
    tells them the erase was complete.

    Never raises. Callers erase several stores in a row and one wedged
    file must not strand the rest.
    """
    try:
        path.unlink()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True
