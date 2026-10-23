"""Optional command-line controller test for GameShelf; no Qt needed.

Run from an existing installation using TEST_CONTROLLERS.bat to identify which
Windows input provider reports the controller and button/stick activity.
"""
from __future__ import annotations

import argparse
import time
from controller_input import SDLBackend, XInputBackend, WinMMBackend, A, B, X, Y, UP, DOWN, LEFT, RIGHT, START, BACK, LB, RB

BUTTON_NAMES=((UP,'UP'),(DOWN,'DOWN'),(LEFT,'LEFT'),(RIGHT,'RIGHT'),
              (A,'A'),(B,'B'),(X,'X'),(Y,'Y'),(START,'START'),
              (BACK,'BACK'),(LB,'LB'),(RB,'RB'))


def main(argv=None):
    parser=argparse.ArgumentParser(description='Display Big Picture gamepad detection and inputs')
    parser.add_argument('--seconds',type=float,default=20.0,help='Test duration, default 20 seconds')
    args=parser.parse_args(argv)
    if args.seconds<=0:
        parser.error('--seconds must be positive')
    try:
        sdl=SDLBackend()
    except Exception as error:
        print('SDL / DirectInput: unavailable ('+str(error)+')')
        sdl=None
    readers=[('SDL (DirectInput/raw + mapped)',sdl),('Native XInput',XInputBackend()),
             ('Windows legacy joystick',WinMMBackend())]
    print('GameShelf controller diagnostics. Press controller buttons / D-pad / sticks.')
    print('Multiple backends may see the same controller. That is normal.')
    last=None
    deadline=time.monotonic()+args.seconds
    try:
        while time.monotonic()<deadline:
            lines=[]
            for desc,backend in readers:
                if backend is None:
                    lines.append(desc+': unavailable')
                    continue
                try:state=backend.read()
                except Exception as exc:
                    lines.append(desc+': ERROR '+str(exc));continue
                if state is None:
                    lines.append(desc+': not detected')
                else:
                    pressed=', '.join(name for mask,name in BUTTON_NAMES if state&mask) or 'idle'
                    lines.append(desc+': '+backend.name()+' | '+pressed)
            snapshot=tuple(lines)
            if snapshot!=last:
                for line in lines:print(line)
                print('---',flush=True)
                last=snapshot
            time.sleep(0.10)
    except KeyboardInterrupt:
        pass
    print('Controller check complete.')
    return 0


if __name__=='__main__':raise SystemExit(main())
