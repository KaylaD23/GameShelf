"""GameShelf v0.9.11 DirectInput-compatible/SDL, XInput, WinMM and UI regressions."""
import ast
import ctypes
from pathlib import Path
from types import SimpleNamespace

import pytest

from controller_input import (
    A, B, BACK, DOWN, LEFT, RIGHT, START, UP, X, Y,
    Controller, SDLBackend, WinMMBackend, XInputBackend,
    JOYINFOEX, JOYCAPSW, _XInputState, _pov_direction,
)


class FakeBackend:
    def __init__(self, name, states):
        self.device_name=name
        self.states=list(states)
        self.calls=0
    def read(self):
        self.calls+=1
        return self.states.pop(0) if self.states else None
    def name(self):return self.device_name


def test_idle_sdl_no_longer_masks_active_xinput():
    sdl=FakeBackend('Idle SDL DirectInput',[0,0,A])
    xi=FakeBackend('XInput Xbox',[B,0,0])
    legacy=FakeBackend('Legacy',[0,0,0])
    c=Controller(sdl=sdl,xinput=xi,legacy=legacy,clock=lambda:1)
    assert c.pressed()==B
    assert c.device=='XInput Xbox'
    assert c.pressed()==0
    assert c.connected
    assert c.pressed()==A
    assert c.device=='Idle SDL DirectInput'
    assert (sdl.calls,xi.calls,legacy.calls)==(3,3,3)


def test_directinput_legacy_backend_works_without_pygame():
    sdl=FakeBackend('SDL unavailable',[None,None])
    xi=FakeBackend('XInput unavailable',[None,None])
    legacy=FakeBackend('DirectInput-style USB pad',[RIGHT|A,0])
    c=Controller(sdl=sdl,xinput=xi,legacy=legacy,clock=lambda:3)
    assert c.pressed()==RIGHT|A
    assert c.connected
    assert 'USB' in c.device
    assert c.pressed()==0


def test_no_duplicate_play_when_backend_changes_while_button_held():
    sdl=FakeBackend('SDL',[A,None,None])
    xi=FakeBackend('XInput',[None,A,None])
    legacy=FakeBackend('Legacy',[None,None,A])
    c=Controller(sdl=sdl,xinput=xi,legacy=legacy,clock=lambda:1)
    assert c.pressed()==A
    assert c.pressed()==0
    assert c.pressed()==0


def test_disconnect_reconnect_rearms_action_edge():
    sdl=FakeBackend('SDL',[A,None,A])
    xi=FakeBackend('XInput',[None,None,None])
    legacy=FakeBackend('Legacy',[None,None,None])
    c=Controller(sdl=sdl,xinput=xi,legacy=legacy,clock=lambda:1)
    assert c.pressed()==A
    assert c.pressed()==0
    assert not c.connected
    assert c.pressed()==A
    assert c.connected


class FakeXInputDLL:
    def __init__(self):self.states={}
    def XInputGetState(self,port,state_pointer):
        if port not in self.states:return 1167
        st=ctypes.cast(state_pointer,ctypes.POINTER(_XInputState)).contents
        buttons,lx,ly=self.states[port]
        st.pad.buttons=buttons
        st.pad.lx=lx
        st.pad.ly=ly
        return 0


def test_xinput_reads_every_port_not_only_first_idle_port():
    dll=FakeXInputDLL()
    dll.states={0:(0,0,0),2:(A,0,20000),3:(B,-24000,0)}
    x=XInputBackend(dll=dll)
    assert x.read()==(A|B|UP|LEFT)
    assert '3 connected' in x.name()
    dll.states={}
    assert x.read() is None


class FakeWinMM:
    def __init__(self):self.devices={}
    def joyGetNumDevs(self):return 4
    def joyGetPosEx(self,port,out):
        if port not in self.devices:return 167
        buttons,x,y,pov=self.devices[port]
        state=ctypes.cast(out,ctypes.POINTER(JOYINFOEX)).contents
        assert state.dwSize==ctypes.sizeof(JOYINFOEX)
        assert state.dwFlags==0xff
        state.dwButtons=buttons
        state.dwXpos=x
        state.dwYpos=y
        state.dwPOV=pov
        return 0
    def joyGetDevCapsW(self,port,out,length):
        caps=ctypes.cast(out,ctypes.POINTER(JOYCAPSW)).contents
        caps.wXmin=0
        caps.wXmax=65535
        caps.wYmin=0
        caps.wYmax=65535
        caps.wCaps=0x10
        caps.szPname='Legacy USB Pad'
        return 0


def test_winmm_native_legacy_joystick_buttons_axes_pov_and_hotplug():
    dll=FakeWinMM()
    x=WinMMBackend(dll=dll)
    assert x.read() is None
    dll.devices[1]=(0,32767,32767,0xffff)
    assert x.read()==0
    dll.devices[1]=((1<<0)|(1<<7),0,65535,9000)
    assert x.read()==(A|START|LEFT|DOWN|RIGHT)
    assert 'Legacy USB Pad' in x.name()
    dll.devices.clear()
    assert x.read() is None
    dll.devices[2]=(1<<1,32767,32767,18000)
    assert x.read()==(B|DOWN)


@pytest.mark.parametrize('pov,expected',[(0,UP),(9000,RIGHT),(18000,DOWN),(27000,LEFT),(4500,UP|RIGHT),(0xffff,0)])
def test_legacy_pov_cardinal_and_diagonal(pov,expected):
    assert _pov_direction(pov)==expected


class FakePad:
    def __init__(self,buttons=None):self.buttons=set(buttons or [])
    def attached(self):return True
    def get_button(self,i):return i in self.buttons
    def get_axis(self,i):return 0


class FakeSDLMapping:
    def __init__(self,pads):
        self.pads=pads
        for i,key in enumerate(('DPAD_UP','DPAD_DOWN','DPAD_LEFT','DPAD_RIGHT','A','B','X','Y','START','BACK','LEFTSHOULDER','RIGHTSHOULDER')):
            setattr(self,'CONTROLLER_BUTTON_'+key,i)
        self.CONTROLLER_AXIS_LEFTX=0
        self.CONTROLLER_AXIS_LEFTY=1
    def get_init(self):return True
    def is_controller(self,i):return True
    def Controller(self,i):return self.pads[i]
    def name_forindex(self,i):return f'SDL Pad {i+1}'


class FakeSDL:
    error=RuntimeError
    def __init__(self,pads):
        self.pumps=0
        self.display=SimpleNamespace(get_init=lambda:True)
        self.joystick=SimpleNamespace(get_init=lambda:True,get_count=lambda:len(pads))
        self.event=SimpleNamespace(pump=self.pump)
    def pump(self):self.pumps+=1


def test_sdl_detects_second_active_gamepad_behind_idle_first_pad():
    pads=[FakePad(),FakePad({4,1})]
    pg=FakeSDL(pads)
    mapping=FakeSDLMapping(pads)
    backend=SDLBackend(pg=pg,mapping=mapping,clock=lambda:1)
    assert backend.read()==A|DOWN
    assert backend.name()=='SDL Pad 2'
    assert pg.pumps==1


def test_big_picture_mode_hides_desktop_status_bar_and_restores_it():
    source=(Path(__file__).resolve().parents[1]/'main.py').read_text(encoding='utf-8')
    tree=ast.parse(source)
    cls=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='Main')
    enter=next(x for x in cls.body if isinstance(x,ast.FunctionDef) and x.name=='enter_big')
    leave=next(x for x in cls.body if isinstance(x,ast.FunctionDef) and x.name=='leave_big')
    enter_src=ast.unparse(enter)
    leave_src=ast.unparse(leave)
    assert "self.statusBar().showMessage('Big Picture mode')" in enter_src
    assert 'self.statusBar().hide()' in enter_src
    assert 'self.statusBar().show()' in leave_src
    assert "self.statusBar().showMessage('Desktop mode')" in leave_src

class RawJoystick:
    def __init__(self,instance,buttons=()):
        self.instance=instance
        self.buttons=set(buttons)
    def get_instance_id(self):return self.instance
    def get_init(self):return True
    def get_name(self):return f'DirectInput joystick #{self.instance}'
    def get_numbuttons(self):return 8
    def get_button(self,index):return index in self.buttons
    def get_numhats(self):return 0
    def get_numaxes(self):return 2
    def get_axis(self,index):return 0.0


class FakeRawSDL:
    error=RuntimeError
    def __init__(self,devices):
        self.devices=devices
        self.display=SimpleNamespace(get_init=lambda:True)
        self.joystick=SimpleNamespace(get_init=lambda:True,get_count=lambda:len(self.devices),
                                      Joystick=lambda i:self.devices[i])
        self.event=SimpleNamespace(pump=lambda:None)


class FakeRawMapping:
    def get_init(self):return True
    def is_controller(self,index):return index==0
    def __init__(self):self.opens=0
    def Controller(self,index):
        self.opens+=1
        return FakePad()
    def name_forindex(self,index):return 'Idle mapped controller'
    def __getattr__(self,name):
        if name.startswith('CONTROLLER_BUTTON_'):
            return {'CONTROLLER_BUTTON_A':4}.get(name,99)
        if name=='CONTROLLER_AXIS_LEFTX':return 0
        if name=='CONTROLLER_AXIS_LEFTY':return 1
        raise AttributeError(name)


def test_sdl_idle_mapped_controller_doesnt_block_directinput_raw_controller():
    devices=[RawJoystick(1),RawJoystick(2,{0})]
    mapping=FakeRawMapping()
    times=[0.0]
    backend=SDLBackend(pg=FakeRawSDL(devices),mapping=mapping,clock=lambda:times[0])
    assert backend.read()==A
    assert 'DirectInput joystick #2'==backend.name()
    assert mapping.opens==1
    times[0]=0.8
    assert backend.read()==A
    assert mapping.opens==1  # no repeated open of the already attached pad
    devices[1]=RawJoystick(3,{1})
    times[0]=1.6
    assert backend.read()==B  # same index, new device instance id


def test_controller_diagnostics_no_gui_required():
    source=(Path(__file__).resolve().parents[1]/'controller_diagnostics.py').read_text(encoding='utf-8')
    assert 'SDLBackend' in source and 'XInputBackend' in source and 'WinMMBackend' in source
    assert 'PySide6' not in source
