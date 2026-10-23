"""Exercise *actual* GameShelf cover-cache method using a minimal stand-in
for the unavailable Qt image classes. This tests full image pixel coverage,
including fallback if QImageReader returns an unexpectedly-sized image.

Qt GUI/hardware validation is still required on a Windows machine.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

Image = pytest.importorskip('PIL.Image')
ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT/'library_view.py').read_text(encoding='utf-8')


class FakeSize:
    def __init__(self,w,h):self.w,self.h=w,h
    def __eq__(self,o):return isinstance(o,FakeSize) and (self.w,self.h)==(o.w,o.h)


class FakeImage:
    def __init__(self,im):self.im=im
    def isNull(self):return False


class FakeReader:
    honor_scaled_size=True
    def __init__(self,path):self.path=path;self.scaled_size=None
    def setAutoTransform(self,_):pass
    def setScaledSize(self,size):self.scaled_size=size
    def read(self):
        im=Image.open(self.path).convert('RGB')
        if self.honor_scaled_size:
            im=im.resize((self.scaled_size.w,self.scaled_size.h),Image.Resampling.LANCZOS)
        return FakeImage(im)


class FakePixmap:
    def __init__(self,im):self.im=im
    @classmethod
    def fromImage(cls,im):return cls(im.im)
    def isNull(self):return False
    def size(self):return FakeSize(*self.im.size)
    def scaled(self,w,h,aspect_mode,transformation):
        assert aspect_mode=='ignore'
        assert transformation=='smooth'
        return FakePixmap(self.im.resize((w,h),Image.Resampling.LANCZOS))


class FakeCache:
    cache={}
    @staticmethod
    def cacheLimit():return 1024
    @staticmethod
    def setCacheLimit(_):pass
    @classmethod
    def find(cls,key):return cls.cache.get(key)
    @classmethod
    def insert(cls,key,value):cls.cache[key]=value


def cover_cache_class():
    tree=ast.parse(SRC)
    node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='CoverCache')
    code=compile(ast.Module(body=[node],type_ignores=[]),str(ROOT/'library_view.py'),'exec')
    g={'os':os,'QPixmapCache':FakeCache,'QImageReader':FakeReader,'QSize':FakeSize,
       'QPixmap':FakePixmap,'Qt':SimpleNamespace(
           AspectRatioMode=SimpleNamespace(IgnoreAspectRatio='ignore'),
           TransformationMode=SimpleNamespace(SmoothTransformation='smooth'))}
    exec(code,g)
    return g['CoverCache']


def make_test_art(path,w,h):
    # Four obvious corner colours, distinct from the card's background. The
    # small corners would disappear if crop-to-fill were accidentally restored.
    im=Image.new('RGB',(w,h),(180,160,130))
    im.paste((255,0,0),(0,0,w//6,h//6))
    im.paste((0,255,0),(w-w//6,0,w,h//6))
    im.paste((0,0,255),(0,h-h//6,w//6,h))
    im.paste((255,255,0),(w-w//6,h-h//6,w,h))
    im.save(path)


@pytest.mark.parametrize('source,target',[
    ((600,900),(173,235)),  # Typical PS2 game artwork
    ((210,300),(192,248)),  # Narrow cover where previous release left side bars
    ((214,300),(173,235)),  # Crash-like logo cropping regression
    ((512,512),(173,235)),  # Square downloaded grid
    ((640,360),(205,277)),  # Landscape: never silently crop content
])
@pytest.mark.parametrize('reader_honors_resize',[True,False])
def test_cached_cover_fills_frame_and_preserves_all_four_corners(tmp_path,source,target,reader_honors_resize):
    FakeCache.cache={}
    FakeReader.honor_scaled_size=reader_honors_resize
    art=tmp_path/'cover.png'
    make_test_art(art,*source)
    result=cover_cache_class()().get(str(art),*target)
    assert result is not None
    assert result.im.size == target
    pixel=result.im.load()
    width,height=target
    assert pixel[0,0] == (255,0,0)
    assert pixel[width-1,0] == (0,255,0)
    assert pixel[0,height-1] == (0,0,255)
    assert pixel[width-1,height-1] == (255,255,0)
    assert all(pixel[x,height//2] != (28,38,53) for x in range(width))


def test_every_grid_and_details_paint_passes_entire_image_into_full_frame():
    main=(ROOT/'main.py').read_text(encoding='utf-8')
    assert 'p.drawPixmap(self.rect(), self.pix, self.pix.rect())' in main
    assert 'painter.drawPixmap(poster,pix,pix.rect())' in SRC
    assert 'poster_fit_rect' not in SRC + main
    assert 'QPixmap(width,height)' not in SRC  # no transparent canvas / pillarbox
