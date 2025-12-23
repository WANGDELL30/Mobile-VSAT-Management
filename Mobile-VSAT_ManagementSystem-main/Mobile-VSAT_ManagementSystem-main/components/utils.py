# components/utils.py
import os
import sys
from PySide6.QtCore import QUrl


def _project_root() -> str:
    """
    Returns the folder that contains your 'assets/' directory.
    Assumes this file lives in: <root>/components/utils.py
    """
    here = os.path.dirname(os.path.abspath(__file__))      # <root>/components
    root = os.path.abspath(os.path.join(here, ".."))       # <root>
    return root


def resource_path(relative_path: str) -> str:
    """
    Works in dev (python main.py) and in PyInstaller builds.
    """
    base_path = getattr(sys, "_MEIPASS", None)
    if base_path:
        return os.path.join(base_path, relative_path)

    return os.path.join(_project_root(), relative_path)


def resource_url(relative_path: str) -> str:
    """
    file:// URL for Qt stylesheets (url(...)) and HTML.
    Handles Windows paths correctly.
    """
    return QUrl.fromLocalFile(resource_path(relative_path)).toString()
