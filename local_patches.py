"""Local patches for Hermes (Windows/Chinese locale compatibility).

This file survives Hermes updates because it is NOT part of the upstream repo.
After updating Hermes, if the patches stop working:

  1. Check whether ``hermes_bootstrap.py`` still calls ``_apply_subprocess_utf8_patch()``.
  2. If not, add this line at the bottom (before the last line is fine)::

         from local_patches import apply_all; apply_all()

Usage
-----
At module level::

    from local_patches import apply_all
    apply_all()
"""

import os
import subprocess

_SUBPROCESS_PATCHED = False


def apply_subprocess_utf8_patch() -> None:
    """Monkey-patch ``subprocess.Popen`` to default ``encoding='utf-8'`` on Windows.

    On Chinese Windows, ``locale.getpreferredencoding()`` returns ``'gbk'``,
    which crashes ``subprocess`` pipes when output contains non-GBK characters.
    ``PYTHONUTF8=1`` only helps child *Python* processes — the parent's pipe
    reader still decodes with the system locale encoding.

    This patch auto-injects ``encoding='utf-8'`` and ``errors='replace'`` into
    every ``subprocess.Popen()`` / ``subprocess.run()`` call that uses
    ``text=True`` (``universal_newlines=True``) without an explicit encoding.

    Safe guards:
    - No-op on POSIX.
    - Does NOT override an explicit ``encoding=`` passed by the caller.
    - Does NOT affect binary mode (``text=False``).
    - Idempotent — safe to call multiple times.
    """
    global _SUBPROCESS_PATCHED

    if os.name != "nt":
        return
    if _SUBPROCESS_PATCHED:
        return

    _orig_init = subprocess.Popen.__init__

    def _patched_init(self, args, **kwargs):
        if (kwargs.get("text") or kwargs.get("universal_newlines")) and "encoding" not in kwargs:
            kwargs["encoding"] = "utf-8"
            kwargs.setdefault("errors", "replace")
        return _orig_init(self, args, **kwargs)

    subprocess.Popen.__init__ = _patched_init  # type: ignore[method-assign]
    _SUBPROCESS_PATCHED = True


def apply_all() -> None:
    """Apply all local patches."""
    apply_subprocess_utf8_patch()
