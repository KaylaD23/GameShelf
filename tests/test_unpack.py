from pathlib import Path
import subprocess
import zipfile
from unittest.mock import patch
import pytest
from core import launch
from unpack_emulators import extract_safe


def test_archive_success(tmp_path):
    z=tmp_path/'test.zip'
    with zipfile.ZipFile(z,'w') as f:
        f.writestr('Emulators 1/Test/Test.exe',b'test binary')
    folder=tmp_path/'extract';folder.mkdir()
    extract_safe(z,folder)
    assert (folder/'Emulators 1'/'Test'/'Test.exe').read_bytes()==b'test binary'
    # The extractor is idempotent when the target entry has exactly the same size.
    extract_safe(z,folder)


def test_archive_traversal_rejected(tmp_path):
    z=tmp_path/'test.zip'
    with zipfile.ZipFile(z,'w') as f:
        f.writestr('../escape.txt',b'invalid')
    folder=tmp_path/'extract';folder.mkdir()
    with pytest.raises(ValueError,match='Unsafe archive path'):
        extract_safe(z,folder)
    assert not (tmp_path/'escape.txt').exists()


def test_archive_no_overwrite(tmp_path):
    z=tmp_path/'test.zip'
    with zipfile.ZipFile(z,'w') as f:
        f.writestr('emu/game.bin',b'updated')
    dest=tmp_path/'dest';(dest/'emu').mkdir(parents=True)
    (dest/'emu'/'game.bin').write_bytes(b'old')
    with pytest.raises(FileExistsError):extract_safe(z,dest)
    assert (dest/'emu'/'game.bin').read_bytes()==b'old'


def test_launch_never_uses_shell(tmp_path):
    exe=tmp_path/'Dolphin.exe';exe.write_bytes(b'dummy')
    rom=tmp_path/'game name & rem.iso';rom.write_bytes(b'rom')
    with patch('core.subprocess.Popen') as popen:
        launch(str(exe),'dolphin',str(rom),True)
        popen.assert_called_once()
        positional,kw=popen.call_args
        assert kw['shell'] is False
        assert positional[0][-1]==str(rom)
