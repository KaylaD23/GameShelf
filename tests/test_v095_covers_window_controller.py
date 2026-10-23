"""v0.9.5 regressions for cropping, controller mappings and window restoration."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from cover_geometry import crop_retention, crop_to_fill,fit_inside,fitted_size,scaled_to_fill,should_fit_inside
from controller_input import Controller, SDLBackend, UP,DOWN,LEFT,RIGHT,A,B,X,Y,LB,RB,START
from window_geometry import safe_desktop_rect

ROOT=Path(__file__).resolve().parents[1]
MAIN=(ROOT/'main.py').read_text(encoding='utf-8')
VIEW=(ROOT/'library_view.py').read_text(encoding='utf-8')

@pytest.mark.parametrize('image,frame,expected',[
    ((400,600),(200,300),(0,0,400,600)),
    ((1000,1000),(200,300),(166,0,667,1000)),
    ((1600,900),(200,300),(500,0,600,900)),
    ((300,600),(200,300),(0,75,300,450)),
    ((192,248),(192,248),(0,0,192,248)),
])
def test_full_bleed_crop_geometry_is_stable(image,frame,expected):
    assert crop_to_fill(*image,*frame)==expected

@pytest.mark.parametrize('shape,frame',[
    ((720,1280),(173,235)), ((3840,2160),(192,248)),
    ((700,1050),(205,277)), ((256,256),(173,235)),
])
def test_fill_geometry_preserves_source_aspect(shape,frame):
    x,y,w,h=crop_to_fill(*shape,*frame)
    assert x>=0 and y>=0 and x+w<=shape[0] and y+h<=shape[1]
    assert abs(w/h -frame[0]/frame[1])<0.03
    sw,sh=scaled_to_fill(*shape,*frame)
    assert sw>=frame[0] and sh>=frame[1]


def test_near_matching_covers_are_fitted_instead_of_cropped():
    image=(214,300)
    frame=(173,235)
    assert crop_retention(*image,*frame) >= 0.965
    assert should_fit_inside(*image,*frame)
    assert fit_inside(*image,*frame)==(2,0,168,235)
    assert fitted_size(*image,*frame)==(168,235)


def test_mismatched_covers_still_crop_to_fill():
    image=(256,256)
    frame=(173,235)
    assert crop_retention(*image,*frame) < 0.9
    assert not should_fit_inside(*image,*frame)

@pytest.mark.parametrize('bad',[(0,100,30,40),(10,-1,2,3)])
def test_invalid_artwork_geometry_fails_cleanly(bad):
    with pytest.raises(ValueError):crop_to_fill(*bad)
    with pytest.raises(ValueError):should_fit_inside(*bad)


def test_details_and_virtualized_grid_fill_frames_without_cropping():
    assert 'p.drawPixmap(self.rect(), self.pix, self.pix.rect())' in MAIN
    assert 'reader.setScaledSize(QSize(width,height))' in VIEW
    assert 'pix.scaled(width,height,Qt.AspectRatioMode.IgnoreAspectRatio,' in VIEW
    assert 'painter.drawPixmap(poster,pix,pix.rect())' in VIEW
    assert 'pix.fill(Qt.GlobalColor.transparent)' not in VIEW
    assert 'crop_to_fill(' not in MAIN and 'crop_to_fill(' not in VIEW
    assert 'poster_fit_rect' not in MAIN and 'poster_fit_rect' not in VIEW


def test_screen_restoration_and_default_position():
    screen=(0,0,2048,1280)
    assert safe_desktop_rect(screen)==(102,64,1843,1152)
    assert safe_desktop_rect(screen,[-4000,-200,1700,900])==(0,0,1700,900)
    assert safe_desktop_rect((1920,0,1280,768),[100,10,1800,1200])==(1920,0,1280,768)
    assert safe_desktop_rect((0,0,1400,900),[40,50,800,600])==(40,50,800,600)
    with pytest.raises(ValueError):safe_desktop_rect((0,0,0,900))


def test_desktop_opens_maximized_and_remembers_windowed_bounds():
    assert "'desktop_maximized':True" in (ROOT/'core.py').read_text(encoding='utf-8')
    assert 'self.showMaximized()' in MAIN
    assert 'self.remember_desktop_window()' in MAIN
    assert 'self.open_desktop()' in MAIN
    assert "if self.isFullScreen():self.showNormal()" in MAIN


class FakeBackend:
    def __init__(self,states):self.states=iter(states)
    def read(self):return next(self.states,None)
    def name(self):return 'Fake gamepad'


def test_gamepad_buttons_debounce_but_navigation_repeats():
    current=[1.0]
    pad=Controller(sdl=FakeBackend([UP|A,UP|A,UP|A,UP|A,UP|A,0,UP|A]),xinput=FakeBackend([]),clock=lambda:current[0])
    assert pad.pressed()==UP|A
    current[0]=1.15
    assert pad.pressed()==0
    current[0]=1.35
    assert pad.pressed()==UP   # held D-pad repeats but NOT held launch action
    current[0]=1.42
    assert pad.pressed()==0
    current[0]=1.5
    assert pad.pressed()==UP
    current[0]=1.6
    assert pad.pressed()==0
    current[0]=1.7
    assert pad.pressed()==UP|A


def test_fallback_when_sdl_has_no_device():
    pad=Controller(sdl=FakeBackend([None,0]),xinput=FakeBackend([A]),clock=lambda:0)
    assert pad.pressed()==A
    assert pad.connected
    assert pad.pressed()==0
    assert pad.connected  # connected and idle is not the same as disconnected


class FakePad:
    def __init__(self):self.buttons=set();self.axes={0:0,1:0};self.is_attached=True
    def get_button(self,index):return index in self.buttons
    def get_axis(self,index):return self.axes[index]
    def attached(self):return self.is_attached


class FakeMapping:
    def __init__(self,pad):
        self.pad=pad
        for index,name in enumerate(('DPAD_UP','DPAD_DOWN','DPAD_LEFT','DPAD_RIGHT','A','B','X','Y','START','BACK','LEFTSHOULDER','RIGHTSHOULDER')):
            setattr(self,'CONTROLLER_BUTTON_'+name,index)
        self.CONTROLLER_AXIS_LEFTX=0
        self.CONTROLLER_AXIS_LEFTY=1
    def get_init(self):return True
    def is_controller(self,index):return index==0
    def Controller(self,index):return self.pad
    def name_forindex(self,index):return 'PlayStation controller'


class FakeSDLSystem:
    error=RuntimeError
    def __init__(self):
        self.pumps=0
        self.display=SimpleNamespace(get_init=lambda:True)
        self.joystick=SimpleNamespace(get_init=lambda:True,get_count=lambda:1)
        self.event=SimpleNamespace(pump=self.pump)
    def pump(self):self.pumps+=1


def test_sdl_button_mapping_axis_sign_and_connection(monkeypatch):
    fake_pad=FakePad()
    sdl=FakeSDLSystem()
    mapping=FakeMapping(fake_pad)
    backend=SDLBackend(pg=sdl,mapping=mapping)
    fake_pad.buttons={mapping.CONTROLLER_BUTTON_A,mapping.CONTROLLER_BUTTON_X,mapping.CONTROLLER_BUTTON_DPAD_RIGHT}
    fake_pad.axes={0:-24000,1:-20000}
    assert backend.read()==(A|X|RIGHT|LEFT|UP)
    assert sdl.pumps==1
    assert backend.name()=='PlayStation controller'
    fake_pad.is_attached=False
    assert backend.read() is None


def test_big_picture_input_connected_to_existing_actions():
    tree=ast.parse(MAIN)
    main=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Main')
    poll=next(n for n in main.body if isinstance(n,ast.FunctionDef) and n.name=='poll')
    body=ast.unparse(poll)
    assert 'self.controller.pressed()' in body
    assert 'QApplication.activeModalWidget()' in body
    assert 'self.change_big_console(-1)' in body
    assert 'self.launch_selected(' in body
    assert 'self.edit_ps3_settings()' in body
    assert 'self.favorite_id(' in body
