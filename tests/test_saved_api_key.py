"""Secure credential persistence, without network access or real API secrets."""
import ast
import ctypes
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from api_key_store import (
    _CREDENTIALW, KeyStoreError, load_api_key, save_api_key,
    forget_api_key, _read_windows, _write_windows, _delete_windows,
)
import api_key_store as vault
from cover_downloader import CoverError


class FakeWindowsCredAPI:
    """Simulates ctypes WinCred calls while inspecting actual marshalled bytes."""
    def __init__(self):
        self.buffer = None
        self.cred = None
        self.ptr = None
        self.token = None
        self.free_count = 0
        self.name = None

    def CredWriteW(self, address, flags):
        c = ctypes.cast(address, ctypes.POINTER(_CREDENTIALW)).contents
        self.name = c.TargetName
        assert c.Type == 1 and c.Persist == 2 and c.UserName == 'GameShelf'
        self.token = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize)
        return 1

    def CredReadW(self, target, type_code, flags, result_address):
        assert target == self.name and type_code == 1
        self.buffer = ctypes.create_string_buffer(self.token)
        self.cred = _CREDENTIALW()
        self.cred.CredentialBlobSize = len(self.token)
        self.cred.CredentialBlob = ctypes.cast(self.buffer, ctypes.POINTER(ctypes.c_ubyte))
        self.ptr = ctypes.pointer(self.cred)
        ctypes.cast(result_address, ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)))[0] = self.ptr
        return 1

    def CredFree(self, _):
        self.free_count += 1

    def CredDeleteW(self, target, type_code, flags):
        assert target == self.name and type_code == 1
        self.token = None
        return 1


class SavedKeyTests(unittest.TestCase):
    def test_windows_secure_round_trip_and_reopen(self):
        fake = FakeWindowsCredAPI()
        with patch.object(vault, '_on_windows', return_value=True), \
             patch.object(vault, '_win_api', return_value=fake), \
             patch.dict(os.environ, {}, clear=True):
            self.assertEqual(save_api_key('Bearer  "aTestToken_123"  '), 'aTestToken_123')
            self.assertEqual(fake.token, b'aTestToken_123')
            self.assertEqual(load_api_key(), 'aTestToken_123')
            self.assertEqual(load_api_key(), 'aTestToken_123')
            self.assertEqual(fake.free_count, 2)
            forget_api_key()
            self.assertIsNone(fake.token)

    def test_invalid_token_never_saved(self):
        with patch.object(vault, '_on_windows', return_value=True), \
             patch.object(vault, '_write_windows') as write:
            for raw in ('', 'has bad spaces', 'bad\nkey'):
                with self.assertRaises(CoverError):
                    save_api_key(raw)
            write.assert_not_called()

    def test_saved_key_preferred_over_environment(self):
        with patch.object(vault, '_on_windows', return_value=True), \
             patch.object(vault, '_read_windows', return_value='stored-token'), \
             patch.dict(os.environ, {'STEAMGRIDDB_API_KEY': 'env-token'}):
            self.assertEqual(load_api_key(), 'stored-token')

    def test_environment_variable_fallback_and_locked_vault(self):
        with patch.object(vault, '_on_windows', return_value=True), \
             patch.object(vault, '_read_windows', side_effect=KeyStoreError('locked')):
            with patch.dict(os.environ, {'STEAMGRIDDB_API_KEY': 'env-token'}):
                self.assertEqual(load_api_key(), 'env-token')
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(KeyStoreError):
                    load_api_key()

    def test_write_error_does_not_leak_secret(self):
        with patch.object(vault, '_on_windows', return_value=True), \
             patch.object(vault, '_write_windows', side_effect=OSError('SECRETINBACKEND')):
            with self.assertRaises(KeyStoreError) as error:
                save_api_key('hidden_api_token')
        self.assertNotIn('hidden_api_token', str(error.exception))
        self.assertNotIn('SECRETINBACKEND', str(error.exception))

    def test_key_storage_not_in_plain_json(self):
        root = Path(__file__).resolve().parents[1]
        core = (root/'core.py').read_text(encoding='utf-8')
        assert 'steamgriddb_api_key' not in core.lower()
        ui = (root/'cover_ui.py').read_text(encoding='utf-8')
        assert 'never stored in settings' not in ui
        assert 'setEchoMode(QLineEdit.EchoMode.Password)' in ui
        assert 'Save Key' in ui and 'Forget Key' in ui
        assert ui.count('store_field_key(') >= 5
        assert ui.count('initial_api_key()') >= 3
        tree = ast.parse(ui)
        assert any(isinstance(n, ast.ClassDef) and n.name == 'BulkCoverDialog' for n in tree.body)
        assert any(isinstance(n, ast.ClassDef) and n.name == 'CoverBrowser' for n in tree.body)

    def test_non_windows_vault_fallback_works_when_keyring_connected(self):
        class FakeKeyring:
            token = None
            def get_password(self, service, name): return self.token
            def set_password(self, service, name, token): self.token=token
            def delete_password(self, service, name): self.token=None
        fake=FakeKeyring()
        with patch.object(vault, '_on_windows', return_value=False), \
             patch.object(vault, '_keyring_module', return_value=fake), \
             patch.dict(os.environ, {}, clear=True):
            self.assertEqual(save_api_key('testtoken'), 'testtoken')
            self.assertEqual(load_api_key(), 'testtoken')
            forget_api_key()
            self.assertEqual(load_api_key(), '')


if __name__=='__main__':unittest.main()
