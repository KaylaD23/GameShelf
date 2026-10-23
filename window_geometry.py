"""Screen-safe window placement independent from Qt (testable without a display)."""
from __future__ import annotations


def safe_desktop_rect(available, stored=None):
    """Clamp restored window bounds to the available desktop work area.

    Inputs and result are (x,y,width,height). Defaults to a generous centred
    90% x 90% window if nothing has been saved, avoiding a corner launch.
    """
    sx,sy,sw,sh=available
    if sw<=0 or sh<=0:raise ValueError('Screen must have positive dimensions')
    fallback=(sx+round(sw*.05),sy+round(sh*.05),max(1,round(sw*.9)),max(1,round(sh*.9)))
    if not isinstance(stored,(list,tuple)) or len(stored)!=4 or not all(isinstance(i,int) for i in stored):
        stored=fallback
    x,y,w,h=stored
    w=max(1,min(w,sw))
    h=max(1,min(h,sh))
    x=max(sx,min(x,sx+sw-w))
    y=max(sy,min(y,sy+sh-h))
    return (x,y,w,h)
