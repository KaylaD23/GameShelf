"""v0.9.12: emulator session ownership, input suspension, rearm, child processes."""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
import time

import pytest

from controller_input import Controller, A, B, RIGHT
from emulator_lifecycle import EmulatorProcessMonitor

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT/'main.py').read_text(encoding='utf-8')


class FakeProc:
    def __init__(self, pid=100):
        self.pid = pid
        self.returncode = None
    def poll(self):
        return self.returncode


class FakeChild:
    def __init__(self, pid, parent, *, created=None):
        self.pid = pid
        self.info = {'pid':pid, 'ppid':parent, 'create_time':time.time() if created is None else created}
        self.alive = True
    def is_running(self):
        return self.alive
    def status(self):
        return 'running' if self.alive else 'zombie'


class FakePsutil:
    Error = RuntimeError
    STATUS_ZOMBIE = 'zombie'
    def __init__(self, children=()):
        self.children = list(children)
        self.scans = 0
        self.iter_scans = 0
    def Process(self, pid):
        self.scans += 1
        return SimpleNamespace(children=lambda recursive: self.children)
    def process_iter(self, attrs):
        self.iter_scans += 1
        return iter(self.children)


def test_direct_emulator_alive_then_closed_without_descendants():
    proc = FakeProc()
    api = FakePsutil()
    watch = EmulatorProcessMonitor(proc, process_api=api, clock=lambda: 1.0)
    assert watch.running()
    proc.returncode = 0
    assert not watch.running()
    assert api.iter_scans == 1
    assert not watch.running()
    assert api.iter_scans == 1  # do not scan every frame after shutdown


def test_launcher_exits_but_spawned_emulator_keeps_lock():
    proc = FakeProc()
    child = FakeChild(101, 100)
    api = FakePsutil([child])
    watch = EmulatorProcessMonitor(proc, process_api=api, clock=lambda: 1.0)
    assert watch.running()
    proc.returncode = 0
    assert watch.running()
    child.alive = False
    assert not watch.running()


def test_fast_exiting_launcher_discovers_child_after_parent_closes():
    proc = FakeProc()
    child = FakeChild(102, 100)
    api = FakePsutil([child])
    watch = EmulatorProcessMonitor(proc, process_api=api)
    proc.returncode = 0
    assert watch.running()
    child.alive = False
    assert not watch.running()


def test_unrelated_or_stale_process_does_not_hold_input_lock():
    proc = FakeProc()
    unrelated = FakeChild(202, 300)
    stale = FakeChild(203, 100, created=0.0)
    api = FakePsutil([unrelated, stale])
    watch = EmulatorProcessMonitor(proc, process_api=api)
    proc.returncode = 7
    assert not watch.running()


def test_no_psutil_falls_back_to_direct_process_tracking():
    proc = FakeProc()
    watch = EmulatorProcessMonitor(proc, process_api=False)
    assert watch.running()
    proc.returncode = 1
    # psutil unavailable is an expected fallback; the code should still work.
    watch.api = None
    assert not watch.running()


class InputBackend:
    def __init__(self, states):
        self.states = iter(states)
        self.calls = 0
    def read(self):
        self.calls += 1
        return next(self.states, 0)
    def name(self):
        return 'Test controller'


def test_held_buttons_cannot_accidentally_launch_game_after_exit():
    backend = InputBackend([A, A, A, 0, RIGHT, 0, A])
    pad = Controller(sdl=backend, xinput=InputBackend([None]*7), legacy=InputBackend([None]*7),clock=lambda:1.0)
    assert pad.pressed() == A
    pad.require_release()
    assert pad.pressed() == 0  # still held, ignore
    assert pad.pressed() == 0
    assert pad.pressed() == 0  # neutral re-arms without firing
    assert pad.pressed() == RIGHT  # navigation returns
    assert pad.pressed() == 0
    assert pad.pressed() == A  # action returns after new press


def _extract_poll():
    module=ast.parse(MAIN)
    cls=next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name=='Main')
    node=next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name=='poll')
    source=compile(ast.Module(body=[node],type_ignores=[]),'<actual GameShelf Main.poll>','exec')
    namespace={
        'QApplication':SimpleNamespace(activeModalWidget=lambda:None),
        'time':time, 'Path':Path,
        'QMessageBox':SimpleNamespace(warning=lambda *a:None),
    }
    from controller_input import A, B, BACK, DOWN, LB, LEFT, RB, RIGHT, START, UP, X, Y
    namespace.update({k:v for k,v in locals().items() if k in ('A','B','BACK','DOWN','LB','LEFT','RB','RIGHT','START','UP','X','Y')})
    exec(source,namespace)
    return namespace['poll']


class FakeMain:
    def __init__(self, session_count=1):
        self.controller=Controller(sdl=InputBackend([A, A, 0, RIGHT, 0, A]), xinput=InputBackend([None]*6), legacy=InputBackend([None]*6),clock=lambda:1.0)
        self.proc1=FakeProc(1);self.proc2=FakeProc(2)
        self.fake_monitors=[SimpleNamespace(running=lambda p=p: p.poll() is None) for p in (self.proc1,self.proc2)]
        self.sessions={'one':(self.proc1,time.monotonic(),True,None)}
        self.session_monitors={'one':self.fake_monitors[0]}
        if session_count == 2:
            self.sessions['two']=(self.proc2,time.monotonic(),True,None)
            self.session_monitors['two']=self.fake_monitors[1]
        self._game_input_paused=True
        self.big=object();self.desktop=object()
        self.root=SimpleNamespace(currentWidget=lambda:self.big)
        self.shortcut_states=[]
        self.big_shortcuts=[SimpleNamespace(setEnabled=lambda value:self.shortcut_states.append(value))]
        self.bigscroll=SimpleNamespace(setFocus=lambda:None)
        self.library=SimpleNamespace(add_playtime=lambda *a:None)
        self.updated=[];self.moved=[];self.footer=0
        self.big_games=[{'id':'one'}];self.big_index=0
        self.controller.device='Test controller'
        self._status=SimpleNamespace(showMessage=lambda *a:None)
    def statusBar(self):return self._status
    def update_game_in_views(self,key):self.updated.append(key)
    def update_gamepad_footer(self):self.footer+=1
    def big_move(self,amount):self.moved.append(amount)
    def big_columns(self):return 4
    def change_big_console(self,step):raise AssertionError('unexpected console switch')
    def launch_selected(self,ident):raise AssertionError('No auto launch allowed')
    def leave_big(self):raise AssertionError('unexpected exit')
    def edit_ps3_settings(self):raise AssertionError('unexpected settings')
    def favorite_id(self,ident):raise AssertionError('unexpected favourite')


def test_actual_main_poll_does_not_read_controller_while_emulator_active():
    gui=FakeMain()
    poll=_extract_poll()
    poll(gui)
    assert gui.controller.sdl.calls==0
    assert gui.sessions
    gui.proc1.returncode=0
    poll(gui)
    assert gui.sessions=={}
    assert gui.controller.sdl.calls==1
    assert gui.updated==['one']
    assert gui.shortcut_states==[True]
    assert not gui.moved
    poll(gui)
    assert gui.controller.sdl.calls==2
    assert not gui.moved
    poll(gui)
    assert gui.controller.sdl.calls==3
    assert not gui.moved
    poll(gui)
    assert gui.moved==[1]


def test_actual_main_poll_waits_for_last_of_two_emulators():
    gui=FakeMain(session_count=2)
    poll=_extract_poll()
    gui.proc1.returncode=0
    poll(gui)
    assert set(gui.sessions)=={'two'}
    assert gui.controller.sdl.calls==0
    assert gui.shortcut_states==[]
    gui.proc2.returncode=0
    poll(gui)
    assert gui.sessions=={}
    assert gui.shortcut_states==[True]
    assert gui.controller.sdl.calls==1


def test_release_installer_tracks_new_monitor_and_dependencies():
    installer=(ROOT.parent/'update_existing_gameshelf.py').read_text(encoding='utf-8')
    assert '"emulator_lifecycle.py"' in installer
    assert '"requirements.txt"' in installer
    assert 'RELEASE = "0.9.12"' in installer
    assert 'psutil>=5.9,<8' in (ROOT/'requirements.txt').read_text(encoding='utf-8')
    assert 'self.session_monitors[identifier]=EmulatorProcessMonitor(proc)' in MAIN
    assert 'self.controller.require_release()' in MAIN
    assert 'for shortcut in self.big_shortcuts:shortcut.setEnabled(False)' in MAIN
