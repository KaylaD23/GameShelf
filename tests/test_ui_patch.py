"""Static smoke tests that need no Qt installation."""
import ast
from pathlib import Path
import unittest

SRC=Path(__file__).resolve().parents[1]/'main.py'
TEXT=SRC.read_text(encoding='utf-8')

class LayoutPatchTests(unittest.TestCase):
    def test_compiles_without_qt(self):
        compile(TEXT,str(SRC),'exec')
    def test_scrollable_details(self):
        self.assertIn("self.details_scroller=QScrollArea()",TEXT)
        self.assertIn("self.details_scroller.setWidgetResizable(True)",TEXT)
        self.assertIn("self.div.addWidget(self.details_scroller)",TEXT)
    def test_multiline_title_not_single_elided_line(self):
        self.assertIn("multiline_title(game['title']",TEXT)
        self.assertIn('maximum_lines=3',TEXT)
        self.assertIn("self.title_label.setFixedHeight(61 if large else 54)",TEXT)
    def test_path_not_verbosely_inserted_in_details_label(self):
        self.assertNotIn("Location: {game['path']}",TEXT)
        self.assertIn('self.details_path.setToolTip(path)',TEXT)
    def test_cover_art_fills_poster_without_cropping(self):
        self.assertIn("p.drawPixmap(self.rect(), self.pix, self.pix.rect())",TEXT)
        self.assertNotIn("crop_to_fill(self.pix.width()",TEXT)
        self.assertNotIn("p.setOpacity(0.16)",TEXT)
    def test_nav_no_horizontal_scrollbar(self):
        self.assertIn('self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)',TEXT)
    def test_existing_game_launch_unchanged(self):
        tree=ast.parse(TEXT)
        cls=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='Main')
        self.assertIn('launch_selected',{m.name for m in cls.body if isinstance(m,ast.FunctionDef)})

if __name__=='__main__':unittest.main()
