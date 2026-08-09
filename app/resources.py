import os
import sys


def app_dir() -> str:
    """The directory containing the `app/` package's data files (templates/,
    static/), whether running normally from source or as a PyInstaller
    --onefile bundle. Frozen builds extract their bundled data into a
    temporary directory at sys._MEIPASS at runtime -- __file__-relative
    paths alone only work when running from real source files, not inside
    that extracted bundle, so this needs its own frozen-aware branch."""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "app")  # type: ignore[attr-defined]
    return os.path.dirname(__file__)
