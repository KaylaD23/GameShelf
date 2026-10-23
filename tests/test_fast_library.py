"""Regression guards for GameShelf's large-library performance rewrite."""
import ast
from pathlib import Path
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
MAIN=ast.parse((ROOT/'main.py').read_text(encoding='utf-8'))
VIEW=ast.parse((ROOT/'library_view.py').read_text(encoding='utf-8'))


def method(tree,cls_name,func_name):
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==cls_name)
    return next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==func_name)


class VirtualLibraryTests(unittest.TestCase):
    def test_models_exist_in_both_modes(self):
        body=(ROOT/'main.py').read_text(encoding='utf-8')
        self.assertIn('self.scroller,self.desktop_model=make_game_view()',body)
        self.assertIn('self.bigscroll,self.big_model=make_game_view(large=True)',body)

    def test_refresh_never_constructs_game_tiles(self):
        node=method(MAIN,'Main','refresh')
        calls=[n for n in ast.walk(node) if isinstance(n,ast.Call)]
        self.assertFalse(any(isinstance(n.func,ast.Name) and n.func.id in ('Tile','Poster') for n in calls))
        self.assertFalse(any(isinstance(n.func,ast.Attribute) and n.func.attr=='addWidget' for n in calls))
        self.assertTrue(any(isinstance(n.func,ast.Attribute) and n.func.attr=='set_games' for n in calls))

    def test_big_mode_refresh_is_deferred(self):
        node=method(MAIN,'Main','refresh')
        calls=[n for n in ast.walk(node) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='refresh_big']
        self.assertEqual(len(calls),1)
        self.assertTrue(any(isinstance(n,ast.If) and any(x in ast.unparse(n.test) for x in ('self.big','root.currentWidget')) for n in ast.walk(node)))

    def test_artwork_caches_scaled_images(self):
        content=(ROOT/'library_view.py').read_text(encoding='utf-8')
        self.assertIn('QPixmapCache.find(key)',content)
        self.assertIn('reader.setScaledSize(QSize(width,height))',content)
        self.assertIn('QPixmapCache.insert(key,pix)',content)
        self.assertIn('QListView.LayoutMode.Batched',content)

    def test_search_uses_debounce(self):
        node=method(MAIN,'Main','set_search')
        self.assertIn('search_debounce.start(180)',ast.unparse(node))
        self.assertNotIn('self.refresh()',ast.unparse(node))

    def test_update_one_cover_does_not_rebuild_library(self):
        node=method(MAIN,'Main','cover_saved')
        self.assertIn('self.update_game_in_views(game_id, cover_changed=True)',ast.unparse(node))
        self.assertNotIn('self.refresh()',ast.unparse(node))

    def test_launch_logic_still_uses_existing_launcher(self):
        # Portable invariant: never rely on an old temp directory on the
        # maintainer's computer. Guard the actual launch contract instead.
        src=ast.unparse(method(MAIN,'Main','launch_selected'))
        self.assertIn('launch(',src)
        self.assertIn("kyty_mode='direct'",src)
        self.assertIn('self.sessions[identifier]',src)
        self.assertIn('executable_path(executable)',src)

    def test_large_game_database(self):
        from core import Library
        with tempfile.TemporaryDirectory() as temp:
            lib=Library(Path(temp)/'games.sqlite3')
            for i in range(1000):
                self.assertTrue(lib.add(f'Test game {i:04}', 'ps2', 'pcsx2',str(Path(temp)/f'g{i:04}.iso')))
            t0=time.perf_counter()
            for _ in range(5):
                rows=lib.all()
                self.assertEqual(len(rows),1000)
            elapsed=time.perf_counter()-t0
            self.assertLess(elapsed,5.0)
            lib.close()


if __name__=='__main__':unittest.main()

class UpdatePersistenceTests(unittest.TestCase):
    def test_cover_replace_invalidates_detail(self):
        src=ast.unparse(method(MAIN,'Main','update_game_in_views'))
        self.assertIn('self.details_poster_game = None',src)
        self.assertIn('cover_changed',src)
    def test_desktop_arrow_navigation_refreshes_details(self):
        src=(ROOT/'main.py').read_text(encoding='utf-8')
        self.assertIn('self.scroller.selectionModel().currentChanged.connect(self.on_desktop_index)',src)
    def test_emulators_still_direct_launch_kyty(self):
        src=ast.unparse(method(MAIN,'Main','launch_selected'))
        self.assertIn("kyty_mode='direct'",src)
