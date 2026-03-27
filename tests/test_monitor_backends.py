from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from core import (
    MacOSFSEventsMonitorBackend,
    NativeLinuxMonitorBackend,
    PollingMonitorBackend,
    WatchfilesMonitorBackend,
    build_monitor_backend,
)


class MonitorBackendSelectionTests(unittest.TestCase):
    def test_auto_prefers_linux_native_backend(self) -> None:
        with patch("core.monitor_backends.sys.platform", "linux"), patch(
            "core.monitor_backends.NativeLinuxMonitorBackend", return_value=SentinelBackend("inotify")
        ):
            backend = build_monitor_backend()
        self.assertEqual(backend.name, "inotify")

    def test_auto_prefers_macos_backend(self) -> None:
        with patch("core.monitor_backends.sys.platform", "darwin"), patch(
            "core.monitor_backends.MacOSFSEventsMonitorBackend", return_value=SentinelBackend("fsevents")
        ):
            backend = build_monitor_backend()
        self.assertEqual(backend.name, "fsevents")

    def test_auto_falls_back_to_polling(self) -> None:
        with patch("core.monitor_backends.sys.platform", "linux"), patch(
            "core.monitor_backends.NativeLinuxMonitorBackend", side_effect=RuntimeError("missing")
        ), patch("core.monitor_backends.WatchfilesMonitorBackend", side_effect=RuntimeError("missing")):
            backend = build_monitor_backend()
        self.assertIsInstance(backend, PollingMonitorBackend)

    def test_explicit_backend_names_construct_expected_types(self) -> None:
        with patch("core.monitor_backends.NativeLinuxMonitorBackend", return_value=SentinelBackend("inotify")):
            self.assertEqual(build_monitor_backend("linux-native").name, "inotify")
        with patch("core.monitor_backends.MacOSFSEventsMonitorBackend", return_value=SentinelBackend("fsevents")):
            self.assertEqual(build_monitor_backend("macos-fsevents").name, "fsevents")


class NativeMonitorDependencyTests(unittest.TestCase):
    def test_linux_native_backend_requires_inotify_dependency(self) -> None:
        with patch.dict(sys.modules, {"inotify_simple": None}):
            backend_module = __import__("core.monitor_backends", fromlist=["NativeLinuxMonitorBackend"])
            original = sys.modules.pop("inotify_simple", None)
            try:
                with patch.dict(sys.modules, {"inotify_simple": None}):
                    with self.assertRaises(RuntimeError):
                        backend_module.NativeLinuxMonitorBackend()
            finally:
                if original is not None:
                    sys.modules["inotify_simple"] = original

    def test_macos_backend_requires_watchdog_dependency(self) -> None:
        with patch.dict(sys.modules, {"watchdog.events": None, "watchdog.observers": None}):
            backend_module = __import__("core.monitor_backends", fromlist=["MacOSFSEventsMonitorBackend"])
            original_events = sys.modules.pop("watchdog.events", None)
            original_observers = sys.modules.pop("watchdog.observers", None)
            try:
                with patch.dict(sys.modules, {"watchdog.events": None, "watchdog.observers": None}):
                    with self.assertRaises(RuntimeError):
                        backend_module.MacOSFSEventsMonitorBackend()
            finally:
                if original_events is not None:
                    sys.modules["watchdog.events"] = original_events
                if original_observers is not None:
                    sys.modules["watchdog.observers"] = original_observers


class SentinelBackend:
    def __init__(self, name: str) -> None:
        self.name = name

