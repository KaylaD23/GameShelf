"""GameShelf Big Picture gamepad input.

SDL2 supports standard mapped gamepads and raw DirectInput joysticks on Windows.
Native XInput and WinMM legacy joystick readers are independent fallbacks.
No Qt imports: detection, navigation, repeat and disconnect are unit-testable.
"""
from __future__ import annotations

import ctypes
import os
import sys
import time

UP=0x0001
DOWN=0x0002
LEFT=0x0004
RIGHT=0x0008
START=0x0010
BACK=0x0020
LB=0x0100
RB=0x0200
A=0x1000
B=0x2000
X=0x4000
Y=0x8000
NAV=UP|DOWN|LEFT|RIGHT


class _XInputPad(ctypes.Structure):
    _fields_=[('buttons',ctypes.c_ushort),('left_trigger',ctypes.c_ubyte),
              ('right_trigger',ctypes.c_ubyte),('lx',ctypes.c_short),
              ('ly',ctypes.c_short),('rx',ctypes.c_short),('ry',ctypes.c_short)]


class _XInputState(ctypes.Structure):
    _fields_=[('packet',ctypes.c_uint32),('pad',_XInputPad)]


class XInputBackend:
    """Native XInput, polling all four ports for activity and hot-plugging."""
    def __init__(self, dll=None, platform=None):
        self.dll=dll
        self._connected_ports=0
        if platform is None:platform=sys.platform
        if self.dll is None and platform=='win32':
            for name in ('xinput1_4.dll','xinput1_3.dll','xinput9_1_0.dll'):
                try:self.dll=ctypes.WinDLL(name);break
                except (OSError,AttributeError):pass
        if self.dll is not None:
            fn=self.dll.XInputGetState
            if hasattr(fn,'argtypes'):
                fn.argtypes=[ctypes.c_uint32,ctypes.POINTER(_XInputState)]
                fn.restype=ctypes.c_uint32

    def read(self):
        if self.dll is None:return None
        combined=0
        self._connected_ports=0
        for port in range(4):
            state=_XInputState()
            try:err=self.dll.XInputGetState(port,ctypes.byref(state))
            except (OSError,ValueError,AttributeError):return None
            if err!=0:continue
            self._connected_ports+=1
            pad=state.pad
            buttons=pad.buttons
            if pad.ly>18000:buttons|=UP
            if pad.ly<-18000:buttons|=DOWN
            if pad.lx<-18000:buttons|=LEFT
            if pad.lx>18000:buttons|=RIGHT
            combined|=buttons
        return combined if self._connected_ports else None

    def name(self):
        return f'XInput ({self._connected_ports} connected)' if self._connected_ports else 'XInput controller'


class JOYINFOEX(ctypes.Structure):
    """Windows WinMM JOYINFOEX. All fields are DWORD (32-bit)."""
    _fields_=[(name,ctypes.c_uint32) for name in (
        'dwSize','dwFlags','dwXpos','dwYpos','dwZpos','dwRpos',
        'dwUpos','dwVpos','dwButtons','dwButtonNumber','dwPOV',
        'dwReserved1','dwReserved2')]


class JOYCAPSW(ctypes.Structure):
    """Windows JOYCAPSW layout (Windows wchar_t is 2 bytes)."""
    _fields_=[('wMid',ctypes.c_ushort),('wPid',ctypes.c_ushort),
              ('szPname',ctypes.c_wchar*32),
              ('wXmin',ctypes.c_uint),('wXmax',ctypes.c_uint),
              ('wYmin',ctypes.c_uint),('wYmax',ctypes.c_uint),
              ('wZmin',ctypes.c_uint),('wZmax',ctypes.c_uint),
              ('wNumButtons',ctypes.c_uint),('wPeriodMin',ctypes.c_uint),
              ('wPeriodMax',ctypes.c_uint),('wRmin',ctypes.c_uint),
              ('wRmax',ctypes.c_uint),('wUmin',ctypes.c_uint),
              ('wUmax',ctypes.c_uint),('wVmin',ctypes.c_uint),
              ('wVmax',ctypes.c_uint),('wCaps',ctypes.c_uint),
              ('wMaxAxes',ctypes.c_uint),('wNumAxes',ctypes.c_uint),
              ('wMaxButtons',ctypes.c_uint),
              ('szRegKey',ctypes.c_wchar*32),('szOEMVxD',ctypes.c_wchar*260)]


def _axis_direction(position, minimum, maximum, low_flag, high_flag):
    """Normalize device-specific DirectInput-style joystick axis ranges."""
    span=maximum-minimum
    if span<=0:return 0
    if position<minimum+span*0.30:return low_flag
    if position>maximum-span*0.30:return high_flag
    return 0


def _pov_direction(pov):
    """POV is hundredths of a degree, with 0xffff meaning centred."""
    if pov>=36000:return 0
    result=0
    if pov>=31500 or pov<=4500:result|=UP
    if 4500<=pov<=13500:result|=RIGHT
    if 13500<=pov<=22500:result|=DOWN
    if 22500<=pov<=31500:result|=LEFT
    return result


class WinMMBackend:
    """Native Windows legacy joystick fallback, useful for DirectInput-style pads.

    WinMM is not DirectInput8; SDL provides the actual DirectInput reader.
    This independent legacy HID path works even if pygame/SDL cannot initialise.
    """
    JOY_RETURNALL=0xff
    JOYCAPS_HASPOV=0x10

    def __init__(self, dll=None, platform=None):
        self.dll=dll
        if platform is None:platform=sys.platform
        if self.dll is None and platform=='win32':
            try:self.dll=ctypes.WinDLL('winmm.dll')
            except (OSError,AttributeError):pass
        self._active_name='Windows legacy joystick'
        self._caps={}
        if self.dll is not None:
            for name,argtypes,restype in (
                ('joyGetNumDevs',[],ctypes.c_uint),
                ('joyGetPosEx',[ctypes.c_uint,ctypes.POINTER(JOYINFOEX)],ctypes.c_uint),
                ('joyGetDevCapsW',[ctypes.c_size_t,ctypes.POINTER(JOYCAPSW),ctypes.c_uint],ctypes.c_uint)):
                fn=getattr(self.dll,name,None)
                if fn is not None and hasattr(fn,'argtypes'):
                    fn.argtypes=argtypes;fn.restype=restype

    def _capabilities(self,port):
        if port in self._caps:return self._caps[port]
        caps=None
        fn=getattr(self.dll,'joyGetDevCapsW',None)
        if fn is not None:
            value=JOYCAPSW()
            try:
                if fn(port,ctypes.byref(value),ctypes.sizeof(value))==0:
                    caps=value
            except (OSError,ValueError,AttributeError):pass
        self._caps[port]=caps
        return caps

    def read(self):
        if self.dll is None:return None
        try:count=min(16,int(self.dll.joyGetNumDevs()))
        except (OSError,ValueError,AttributeError):return None
        connected=0
        combined=0
        selected_name=None
        for port in range(count):
            state=JOYINFOEX()
            state.dwSize=ctypes.sizeof(JOYINFOEX)
            state.dwFlags=self.JOY_RETURNALL
            try:code=self.dll.joyGetPosEx(port,ctypes.byref(state))
            except (OSError,ValueError,AttributeError):continue
            if code!=0:
                self._caps.pop(port,None)
                continue
            connected+=1
            caps=self._capabilities(port)
            buttons=0
            for index,flag in ((0,A),(1,B),(2,X),(3,Y),(4,LB),(5,RB),(6,BACK),(7,START)):
                if state.dwButtons & (1<<index):buttons|=flag
            xmin,xmax,ymin,ymax=(caps.wXmin,caps.wXmax,caps.wYmin,caps.wYmax) if caps else (0,65535,0,65535)
            buttons|=_axis_direction(state.dwXpos,xmin,xmax,LEFT,RIGHT)
            buttons|=_axis_direction(state.dwYpos,ymin,ymax,UP,DOWN)
            if caps is None or caps.wCaps & self.JOYCAPS_HASPOV:
                buttons|=_pov_direction(state.dwPOV)
            combined|=buttons
            if (buttons or selected_name is None) and caps is not None:
                selected_name=caps.szPname.strip('\x00')
        if selected_name:self._active_name='Legacy joystick: '+selected_name
        return combined if connected else None

    def name(self):return self._active_name


class SDLBackend:
    """SDL2 mapped gamepads plus RAW DirectInput/joystick fallback on Windows.

    Keeps all connected devices instead of getting stuck on the first idle pad.
    """
    def __init__(self, pg=None, mapping=None, clock=None):
        if pg is None:
            os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT','1')
            import pygame as pg
        if mapping is None:
            from pygame._sdl2 import controller as mapping
        self.pg=pg;self.mapping=mapping
        self.clock=clock or time.monotonic
        previous=os.environ.get('SDL_VIDEODRIVER')
        if previous is None and not pg.display.get_init():
            os.environ['SDL_VIDEODRIVER']='dummy'
        os.environ.setdefault('SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS','1')
        try:
            if not pg.display.get_init():pg.display.init()
            if not pg.joystick.get_init():pg.joystick.init()
            if not mapping.get_init():mapping.init()
        finally:
            if previous is None:os.environ.pop('SDL_VIDEODRIVER',None)
        self.pads=[]
        self.joysticks=[]
        self._slots={}
        self._last_probe=float('-inf')
        self._name='SDL controller'

    def _discover(self):
        now=self.clock()
        if now-self._last_probe<0.5:return
        self._last_probe=now
        # SDL enumerates DirectInput, XInput and other raw HID joysticks on
        # Windows. A mapped idle pad MUST NOT prevent checking an unmapped pad.
        mapped=[];raw=[];new_slots={}
        for index in range(min(32,self.pg.joystick.get_count())):
            try:
                probe=self.pg.joystick.Joystick(index)
                instance=probe.get_instance_id()
            except (RuntimeError,self.pg.error,AttributeError):
                probe=None
                instance=None
            try:is_mapped=bool(self.mapping.is_controller(index))
            except (RuntimeError,self.pg.error,AttributeError):is_mapped=False
            old=self._slots.get(index)
            if is_mapped:
                try:
                    if (old and old[0]=='mapped' and old[1]==instance
                            and old[2].attached()):
                        pad=old[2]
                    else:
                        pad=self.mapping.Controller(index)
                    name=self.mapping.name_forindex(index) or 'SDL gamepad'
                    new_slots[index]=('mapped',instance,pad,name)
                    mapped.append((pad,name))
                    continue
                except (RuntimeError,self.pg.error,AttributeError):pass
            try:
                if (old and old[0]=='raw' and old[1]==instance
                        and old[2].get_init()):
                    pad=old[2]
                else:
                    pad=probe if probe is not None else self.pg.joystick.Joystick(index)
                    if not pad.get_init():pad.init()
                name=pad.get_name() or 'SDL raw joystick'
                new_slots[index]=('raw',instance,pad,name)
                raw.append((pad,name))
            except (RuntimeError,self.pg.error,AttributeError):pass
        self._slots=new_slots
        self.pads=mapped
        self.joysticks=raw

    def read(self):
        try:
            self.pg.event.pump()
            self._discover()
            seen=False
            combined=0
            first_name=None
            active_name=None
            for pad,name in self.pads:
                try:
                    if not pad.attached():continue
                    state=self._mapped_buttons(pad)
                except (RuntimeError,self.pg.error,AttributeError,ValueError):continue
                seen=True
                first_name=first_name or name
                if state:active_name=active_name or name
                combined|=state
            for pad,name in self.joysticks:
                try:
                    if not pad.get_init():continue
                    state=self._raw_buttons(pad)
                except (RuntimeError,self.pg.error,AttributeError,ValueError):continue
                seen=True
                first_name=first_name or name
                if state:active_name=active_name or name
                combined|=state
            if seen:
                self._name=active_name or first_name or 'SDL controller'
                return combined
        except (RuntimeError,self.pg.error,AttributeError,ValueError):
            self.pads=[];self.joysticks=[];self._slots={};self._last_probe=float('-inf')
        return None

    def _mapped_buttons(self,pad):
        ctl=self.mapping
        buttons=0
        for attr,flag in (
            ('CONTROLLER_BUTTON_DPAD_UP',UP),('CONTROLLER_BUTTON_DPAD_DOWN',DOWN),
            ('CONTROLLER_BUTTON_DPAD_LEFT',LEFT),('CONTROLLER_BUTTON_DPAD_RIGHT',RIGHT),
            ('CONTROLLER_BUTTON_A',A),('CONTROLLER_BUTTON_B',B),
            ('CONTROLLER_BUTTON_X',X),('CONTROLLER_BUTTON_Y',Y),
            ('CONTROLLER_BUTTON_START',START),('CONTROLLER_BUTTON_BACK',BACK),
            ('CONTROLLER_BUTTON_LEFTSHOULDER',LB),('CONTROLLER_BUTTON_RIGHTSHOULDER',RB)):
            if pad.get_button(getattr(ctl,attr)):buttons|=flag
        lx=pad.get_axis(ctl.CONTROLLER_AXIS_LEFTX)
        ly=pad.get_axis(ctl.CONTROLLER_AXIS_LEFTY)
        if lx<-18000:buttons|=LEFT
        if lx>18000:buttons|=RIGHT
        if ly<-18000:buttons|=UP
        if ly>18000:buttons|=DOWN
        return buttons

    def _raw_buttons(self,pad):
        buttons=0
        for index,flag in ((0,A),(1,B),(2,X),(3,Y),(6,BACK),(7,START),(4,LB),(5,RB)):
            if index<pad.get_numbuttons() and pad.get_button(index):buttons|=flag
        if pad.get_numhats():
            horizontal,vertical=pad.get_hat(0)
            if horizontal<0:buttons|=LEFT
            if horizontal>0:buttons|=RIGHT
            if vertical>0:buttons|=UP
            if vertical<0:buttons|=DOWN
        if pad.get_numaxes()>1:
            x,y=pad.get_axis(0),pad.get_axis(1)
            if x<-0.55:buttons|=LEFT
            if x>0.55:buttons|=RIGHT
            if y<-0.55:buttons|=UP
            if y>0.55:buttons|=DOWN
        return buttons

    def name(self):return self._name


class Controller:
    """Poll at ~100ms; separate backend fallback, hotplug and held-button repeat."""
    def __init__(self,sdl=None,xinput=None,clock=None,legacy=None):
        if sdl is None:
            try:sdl=SDLBackend()
            except Exception:sdl=None
        self.sdl=sdl
        self.xinput=xinput if xinput is not None else XInputBackend()
        self.legacy=legacy if legacy is not None else WinMMBackend()
        self.clock=clock or time.monotonic
        self.previous=0
        self.repeat_direction=0
        self.repeat_at=0.0
        self.connected=False
        self.device='No controller detected'
        self._selected_backend=None
        self._await_neutral=False

    def _snapshot(self):
        # SDL DirectInput can sometimes report a connected idle controller even
        # while a different XInput/legacy device has active input. Poll all.
        connected=[]
        for backend in (self.sdl,self.xinput,self.legacy):
            if backend is None:continue
            try:raw=backend.read()
            except Exception:raw=None
            if raw is not None:
                connected.append((backend,raw))
        if not connected:return None,0
        active=[pair for pair in connected if pair[1]]
        choices=active or connected
        # Prefer whichever input backend was active previously, avoiding
        # reconnect flicker and mismatched button labels between backends.
        selected=next((pair for pair in choices if pair[0] is self._selected_backend),choices[0])
        return selected

    def require_release(self):
        """After leaving a game, ignore all buttons until every control is neutral.

        Prevents a still-held Play/B/Start from triggering a new UI action.
        """
        self._await_neutral=True
        self.previous=0
        self.repeat_direction=0
        self.repeat_at=0.0

    def pressed(self):
        backend,raw=self._snapshot()
        self.connected=backend is not None
        self.device=backend.name() if backend else 'No controller detected'
        self._selected_backend=backend
        now=self.clock()
        if self._await_neutral:
            if raw==0:
                self._await_neutral=False
            self.previous=raw
            return 0
        edges=raw & ~self.previous
        direction=raw & NAV
        if direction!=self.repeat_direction:
            self.repeat_direction=direction
            self.repeat_at=now+0.34
        elif direction and now>=self.repeat_at:
            edges|=direction
            self.repeat_at=now+0.13
        if direction==0:self.repeat_at=0.0
        self.previous=raw
        return edges
