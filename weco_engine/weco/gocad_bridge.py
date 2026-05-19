"""
§5.2-5.4 — GOCAD Integration Stubs.

This module provides the Python-side infrastructure for GOCAD ↔ WeCo
integration via the C ABI (``weco_plugin.h``).

Phase 2 (§5.2): Load/unload .so/.dll plugins at runtime.
Phase 3 (§5.4): Bidirectional API bridge for embedded use in GOCAD.

The actual C ABI plugin loading is also used by the Studio PluginPage (§3.44).
"""

import ctypes
import logging
import os
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


class GocadPlugin:
    """Wrapper around a GOCAD plugin shared library using weco_plugin.h C ABI."""

    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self._lib = ctypes.CDLL(self.path)
        self.name = self._get_name()
        self.version = self._get_version()
        logger.info(f"Loaded GOCAD plugin: {self.name} v{self.version} from {self.path}")

    def _get_name(self) -> str:
        fn = getattr(self._lib, "weco_plugin_name", None)
        if fn:
            fn.restype = ctypes.c_char_p
            return fn().decode("utf-8", errors="replace")
        return os.path.basename(self.path)

    def _get_version(self) -> str:
        fn = getattr(self._lib, "weco_plugin_version", None)
        if fn:
            fn.restype = ctypes.c_char_p
            return fn().decode("utf-8", errors="replace")
        return "0.0.0"

    def unload(self):
        """Unload the plugin (best-effort on Linux)."""
        if hasattr(ctypes, "dlclose"):
            ctypes.dlclose(self._lib._handle)
        self._lib = None


class GocadBridge:
    """
    §5.4 — Bidirectional GOCAD API bridge.

    Allows WeCo to be embedded inside GOCAD as a plugin,
    or GOCAD objects to be passed into WeCo workflows.

    This is a stub — full implementation requires the GOCAD SDK.
    """

    def __init__(self):
        self._plugins: List[GocadPlugin] = []

    def load_plugin(self, path: str) -> GocadPlugin:
        p = GocadPlugin(path)
        self._plugins.append(p)
        return p

    def unload_all(self):
        for p in self._plugins:
            try:
                p.unload()
            except Exception:
                pass
        self._plugins.clear()

    def list_plugins(self) -> List[Dict[str, str]]:
        return [{"name": p.name, "version": p.version, "path": p.path}
                for p in self._plugins]


class PluginManager:
    """
    Lightweight plugin manager for discovering and loading .so/.dll plugins.

    Scans directories for shared libraries matching the weco_plugin ABI.
    """

    def __init__(self):
        self._plugins: List[GocadPlugin] = []

    def scan(self, directory: str) -> int:
        """Scan a directory for plugin shared libraries.

        Returns the number of plugins loaded.
        """
        if not os.path.isdir(directory):
            logger.warning(f"Plugin directory not found: {directory}")
            return 0
        count = 0
        for entry in os.listdir(directory):
            if entry.endswith((".so", ".dll", ".dylib")):
                path = os.path.join(directory, entry)
                try:
                    self.load(path)
                    count += 1
                except OSError as exc:
                    logger.debug(f"Skipping {entry}: {exc}")
        return count

    def load(self, path: str) -> GocadPlugin:
        """Load a single plugin from a file path."""
        plugin = GocadPlugin(path)
        self._plugins.append(plugin)
        return plugin

    def list_plugins(self) -> List[Dict[str, str]]:
        """Return metadata for all loaded plugins."""
        return [{"name": p.name, "version": p.version, "path": p.path}
                for p in self._plugins]

    def unload_all(self):
        """Unload all plugins."""
        for p in self._plugins:
            try:
                p.unload()
            except Exception:
                pass
        self._plugins.clear()
