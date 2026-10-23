"""Keep the SteamGridDB token in the user's OS credential vault.

Windows uses Credential Manager directly via ctypes (no extra dependency).
Other OSes can use an already configured Python keyring backend. No plaintext
credentials are written to GameShelf's settings, database, or distribution.
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from cover_downloader import normalise_api_key

_TARGET = 'GameShelf/SteamGridDB API Key'
_SERVICE = 'GameShelf - SteamGridDB'


class KeyStoreError(RuntimeError):
    """A user-facing failure without credential data in the message."""


# Explicit 32-bit Win32 fields, including on 64-bit Python.
_DWORD = ctypes.c_uint32


class _FILETIME(ctypes.Structure):
    _fields_ = [('low', _DWORD), ('high', _DWORD)]


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ('Flags', _DWORD), ('Type', _DWORD),
        ('TargetName', ctypes.c_wchar_p), ('Comment', ctypes.c_wchar_p),
        ('LastWritten', _FILETIME), ('CredentialBlobSize', _DWORD),
        ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)),
        ('Persist', _DWORD), ('AttributeCount', _DWORD),
        ('Attributes', ctypes.c_void_p), ('TargetAlias', ctypes.c_wchar_p),
        ('UserName', ctypes.c_wchar_p),
    ]


def _win_api():
    dll = ctypes.WinDLL('Advapi32.dll', use_last_error=True)
    dll.CredReadW.argtypes = [ctypes.c_wchar_p, _DWORD, _DWORD,
                               ctypes.POINTER(ctypes.POINTER(_CREDENTIALW))]
    dll.CredReadW.restype = wintypes.BOOL
    dll.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), _DWORD]
    dll.CredWriteW.restype = wintypes.BOOL
    dll.CredDeleteW.argtypes = [ctypes.c_wchar_p, _DWORD, _DWORD]
    dll.CredDeleteW.restype = wintypes.BOOL
    dll.CredFree.argtypes = [ctypes.c_void_p]
    dll.CredFree.restype = None
    return dll


def _read_windows() -> str:
    api = _win_api()
    ptr = ctypes.POINTER(_CREDENTIALW)()
    if not api.CredReadW(_TARGET, 1, 0, ctypes.byref(ptr)):
        if ctypes.get_last_error() == 1168:  # ERROR_NOT_FOUND
            return ''
        raise KeyStoreError('Cannot read the saved key from Windows Credential Manager.')
    try:
        credential = ptr.contents
        if not credential.CredentialBlobSize:
            return ''
        return ctypes.string_at(credential.CredentialBlob,
                                credential.CredentialBlobSize).decode('ascii')
    except (UnicodeError, ValueError) as exc:
        raise KeyStoreError('The saved key in Windows Credential Manager is invalid.') from exc
    finally:
        api.CredFree(ctypes.cast(ptr, ctypes.c_void_p))


def _write_windows(key: str) -> None:
    raw = key.encode('ascii')
    if len(raw) > 2560:  # Windows generic credential blob limit.
        raise KeyStoreError('The API key is too long for Windows Credential Manager.')
    blob = ctypes.create_string_buffer(raw)
    cred = _CREDENTIALW()
    cred.Type = 1  # CRED_TYPE_GENERIC
    cred.TargetName = _TARGET
    cred.UserName = 'GameShelf'
    cred.CredentialBlobSize = len(raw)
    cred.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
    cred.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE, scoped to this Windows user
    if not _win_api().CredWriteW(ctypes.byref(cred), 0):
        raise KeyStoreError('Could not save the key in Windows Credential Manager.')


def _delete_windows() -> None:
    if not _win_api().CredDeleteW(_TARGET, 1, 0):
        if ctypes.get_last_error() != 1168:
            raise KeyStoreError('Could not delete the saved key from Windows Credential Manager.')


def _keyring_module():
    try:
        import keyring
    except ImportError as exc:
        raise KeyStoreError('Secure key storage is unavailable on this system. ' 
                            'Install a system keyring or use the STEAMGRIDDB_API_KEY environment variable.') from exc
    return keyring


def _on_windows() -> bool:
    return os.name == 'nt'


def load_api_key() -> str:
    """Read stored credentials; preserve support for the existing env variable."""
    try:
        if _on_windows():
            saved = _read_windows()
        else:
            saved = _keyring_module().get_password(_SERVICE, 'SteamGridDB') or ''
    except KeyStoreError:
        # An environment variable remains a non-persistent escape hatch.
        if not os.environ.get('STEAMGRIDDB_API_KEY'):
            raise
        saved = ''
    except Exception as exc:
        if not os.environ.get('STEAMGRIDDB_API_KEY'):
            raise KeyStoreError('Unable to access the system credential store.') from exc
        saved = ''
    return saved or os.environ.get('STEAMGRIDDB_API_KEY', '')


def save_api_key(raw: str) -> str:
    """Validate and save. Return the clean token for the masked input widget."""
    key = normalise_api_key(raw)
    try:
        if _on_windows():
            _write_windows(key)
        else:
            _keyring_module().set_password(_SERVICE, 'SteamGridDB', key)
    except KeyStoreError:
        raise
    except Exception as exc:
        raise KeyStoreError('Unable to securely save the API key on this computer.') from exc
    return key


def forget_api_key() -> None:
    """Delete stored credentials without echoing the secret to a log or file."""
    try:
        if _on_windows():
            _delete_windows()
        else:
            vault = _keyring_module()
            if vault.get_password(_SERVICE, 'SteamGridDB') is not None:
                vault.delete_password(_SERVICE, 'SteamGridDB')
    except KeyStoreError:
        raise
    except Exception as exc:
        raise KeyStoreError('Unable to remove the saved API key.') from exc
