"""Read-only Xbox One game folder diagnosis for bundled WinDurango."""
import argparse
from pathlib import Path
from windurango_diagnostics import create_diagnostic_report


def main(argv=None):
    parser=argparse.ArgumentParser(description='Read-only GameShelf WinDurango game preparation check')
    parser.add_argument('game_exe',help='Path to the prepared/extracted Xbox One game executable')
    parser.add_argument('--runtime',default=str(Path(__file__).resolve().parent/'Emulators'/'WinDurango'/'WinDurango.Common.dll'))
    args=parser.parse_args(argv)
    print(create_diagnostic_report(args.game_exe,args.runtime))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
