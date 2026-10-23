"""Track a launched emulator until its process (or spawned emulator child) exits.

No GUI dependency. The Popen handle is authoritative for a direct launch.
psutil adds best-effort tracking for wrappers that hand off to a child process
and then quit, including on Windows when the former parent PID is retained.
"""
from __future__ import annotations

import time

try:
    import psutil
except ImportError:  # Direct executables remain trackable without psutil.
    psutil = None


class EmulatorProcessMonitor:
    """Observe one launch without waiting, killing processes or stealing focus."""

    def __init__(self, process, *, process_api=None, clock=None):
        self.process = process
        self.api = psutil if process_api is None else process_api
        self.clock = clock or time.monotonic
        self.pid = getattr(process, 'pid', None)
        self._children = {}  # Retain process handles, not bare PIDs (PID reuse).
        self._last_scan = float('-inf')
        self._orphan_scan_done = False
        self._started = time.time() - 5.0

    def _remember(self, processes):
        for child in processes:
            try:
                pid = child.pid
                if pid != self.pid:
                    self._children[pid] = child
            except (AttributeError, OSError):
                continue

    def _discover_children(self, root_alive):
        if self.api is None or self.pid is None:
            return
        now = self.clock()
        # Scan immediately after an exit, then periodically while a process is alive.
        if root_alive and now - self._last_scan < 0.4:
            return
        self._last_scan = now
        if root_alive:
            try:
                self._remember(self.api.Process(self.pid).children(recursive=True))
            except (OSError, ValueError, AttributeError):
                pass
            except self.api.Error:
                pass
        elif not self._orphan_scan_done:
            self._orphan_scan_done = True
            # Windows can retain the parent PID after a launcher exits. Discover
            # its child before losing the original process tree's identity.
            try:
                listing = list(self.api.process_iter(attrs=['pid', 'ppid', 'create_time']))
                family = {self.pid, *self._children.keys()}
                todo = listing
                changed = True
                while changed:
                    changed = False
                    remaining = []
                    for child in todo:
                        try:
                            info = child.info
                            created = info.get('create_time')
                            if info.get('ppid') in family and (created is None or created >= self._started):
                                if child.pid not in family:
                                    family.add(child.pid)
                                    self._remember([child])
                                    changed = True
                            else:
                                remaining.append(child)
                        except (OSError, AttributeError, ValueError):
                            pass
                    todo = remaining
            except (OSError, ValueError, AttributeError):
                pass
            except self.api.Error:
                pass

    def _child_alive(self, child):
        try:
            if not child.is_running():
                return False
            zombie = getattr(self.api, 'STATUS_ZOMBIE', 'zombie')
            return child.status() != zombie
        except (OSError, ValueError, AttributeError):
            return False
        except self.api.Error:
            return False

    def running(self):
        """True until direct emulator/descendant has exited; nonblocking."""
        # Popen.poll() reaps the child and keeps the original PID from being reused.
        root_alive = self.process.poll() is None
        self._discover_children(root_alive)
        self._children = {pid: child for pid, child in self._children.items()
                          if self._child_alive(child)}
        return root_alive or bool(self._children)
