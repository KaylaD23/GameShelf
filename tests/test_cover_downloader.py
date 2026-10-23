"""Cover downloader tests use deterministic mocked HTTP, not live providers."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cover_downloader as art

PNG = b'\x89PNG\r\n\x1a\n' + b'fake_png_for_httptest'


class FakeResponse:
    def __init__(self, body, url, length=None):
        self.body, self.url = body, url
        self.headers = {'Content-Length': str(len(body) if length is None else length)}
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def read(self, n): return self.body[:n]
    def geturl(self): return self.url


class DownloadTests(unittest.TestCase):
    def test_clean_platform_codes(self):
        self.assertEqual(art.clean_title('Taiko no Tatsujin Rhythm Festival 01.000.000 PPSA16441'),
                         'Taiko no Tatsujin Rhythm Festival')

    def test_match_exact_variant(self):
        self.assertEqual(art.similarity('Final Fantasy VII', 'Final Fantasy VII (video game)'), 1.0)
        self.assertIsNone(art.best_bulk_match('Crash Bandicoot', [art.CoverCandidate(
            'Crash Team Racing','u','v','Wikipedia',score=.52)], 'Wikipedia'))

    def test_search_wikipedia_results_rank(self):
        def reply(url, *args, **kwargs):
            data={'query':{'pages':[
                {'pageid':22,'title':'Mario Kart (disambiguation)','thumbnail':{'source':'https://upload.wikimedia.org/intro.png'}},
                {'pageid':21,'title':'Mario Kart 8 (video game)','thumbnail':{'source':'https://upload.wikimedia.org/box.jpg'}}
            ]}}
            return json.dumps(data).encode()
        with patch.object(art, '_get', side_effect=reply):
            candidates = art.search_wikipedia('Mario Kart 8')
        self.assertEqual(candidates[0].title, 'Mario Kart 8 (video game)')
        self.assertEqual(len(candidates), 2)
        self.assertIn('curid=21', candidates[0].page_url)

    def test_search_steamgrid_with_key(self):
        seen = []
        def reply(url, headers=None):
            seen.append((url, headers))
            if '/search/' in url:
                return {'success':True,'data':[{'id':1,'name':'Mara Kart'}, {'id':2,'name':'Mario Kart 8'}]}
            if '/grids/game/2' in url:
                return {'success':True,'data':[{'url':'https://cdn2.steamgriddb.com/grid/test.png','thumb':'https://cdn2.steamgriddb.com/thumb/test.jpg'}]}
            return {'success':True,'data':[]}
        with patch.object(art, '_json',side_effect=reply):
            items=art.search_steamgriddb('Mario Kart 8', 'sample-token')
        self.assertEqual(len(items),1)
        self.assertEqual(items[0].title,'Mario Kart 8')
        self.assertTrue(all(header.get('Authorization')=='Bearer sample-token' for _,header in seen))
        self.assertIn('600x900', seen[1][0])

    def test_missing_key(self):
        with self.assertRaises(art.CoverError):
            art.search_steamgriddb('A game','')

    def test_refuse_http_and_untrusted_hosts(self):
        self.assertFalse(art._valid_host('http://upload.wikimedia.org/x.png','Wikipedia'))
        self.assertFalse(art._valid_host('https://upload.wikimedia.org.attacker.invalid/x.png','Wikipedia'))
        self.assertFalse(art._valid_host('https://evil.example/x.jpg','SteamGridDB'))
        self.assertTrue(art._valid_host('https://cdn2.steamgriddb.com/grid/hi.webp','SteamGridDB'))

    def test_block_redirect_to_wrong_host(self):
        c=art.CoverCandidate('Test','https://upload.wikimedia.org/wikipedia/x.jpg','', 'Wikipedia')
        with patch.object(art,'urlopen',return_value=FakeResponse(PNG,'https://evil.example/image.png')):
            with self.assertRaises(art.CoverError):
                art.save_cover(c,4,Path(tempfile.gettempdir()))

    def test_validate_image_magic(self):
        self.assertEqual(art.image_type(PNG),'.png')
        self.assertEqual(art.image_type(b'\xff\xd8\xffhello'),'.jpg')
        with self.assertRaises(art.CoverError):
            art.image_type(b'<html>error</html>')

    def test_atomic_cover_preserve_on_failure(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root);previous=path/'16.png';previous.write_bytes(PNG)
            c=art.CoverCandidate('Test','https://upload.wikimedia.org/a.png','', 'Wikipedia')
            with patch.object(art,'_get',return_value=b'NO IMAGE'):
                with self.assertRaises(art.CoverError):
                    art.save_cover(c,16,path)
            self.assertEqual(previous.read_bytes(),PNG)
            with patch.object(art,'_get',return_value=PNG):
                final=art.save_cover(c,16,path)
            self.assertEqual(final,previous)
            self.assertEqual(final.read_bytes(),PNG)
            self.assertEqual(len(list(path.iterdir())),1)

    def test_urlopen_size_limit(self):
        with patch.object(art,'urlopen',return_value=FakeResponse(b'12345','https://upload.wikimedia.org/x.jpg',length=99)):
            with self.assertRaises(art.CoverError):
                art._get('https://upload.wikimedia.org/x.jpg',limit=6,provider='Wikipedia')

    def test_overly_broad_bulk_skip(self):
        items=[art.CoverCandidate('Spider-Man 2 (film)', 'u','u','Wikipedia',score=.9)]
        self.assertIsNone(art.best_bulk_match('Spider-Man 2',items,'Wikipedia'))
        self.assertIsNotNone(art.best_bulk_match('Spider-Man 2', [art.CoverCandidate(
            'Spider-Man 2 (video game)','u','u','Wikipedia',score=1)],'Wikipedia'))


if __name__=='__main__': unittest.main()
