"""Stable console family navigation; doesn't require a graphical session."""
import ast
from pathlib import Path
from core import PLATFORMS, CONSOLE_GROUPS, EMULATORS


def test_console_families_have_expected_order():
    assert CONSOLE_GROUPS == (
        ('PLAYSTATION', ('ps1','ps2','ps3','ps4','ps5','psp','vita')),
        ('NINTENDO', ('gc','wii','wiiu','3ds','switch')),
        ('XBOX', ('xbox','xbox360')),
    )


def test_every_console_appears_once_and_only_once():
    keys=[key for _,platforms in CONSOLE_GROUPS for key in platforms]
    assert len(keys)==len(set(keys))
    assert keys==list(PLATFORMS)


def test_ps4_ps5_and_xbox360_remain_independent():
    assert PLATFORMS['ps4']=='PlayStation 4'
    assert PLATFORMS['ps5']=='PlayStation 5'
    assert PLATFORMS['xbox360']=='Xbox 360'
    keys={e.key for e in EMULATORS}
    assert {'kyty','sharpemu','shadps4','xemu','xenia','citron'}<=keys


def test_sidebar_renders_nonselectable_group_headings():
    source=(Path(__file__).resolve().parents[1]/'main.py').read_text(encoding='utf-8')
    tree=ast.parse(source)
    desktop=next(node for node in ast.walk(tree) if isinstance(node,ast.FunctionDef) and node.name=='make_desktop')
    body=ast.get_source_segment(source,desktop)
    assert 'for family,platform_keys in CONSOLE_GROUPS:' in body
    assert 'heading.setFlags(Qt.ItemFlag.NoItemFlags)' in body
    assert "item.setData(Qt.ItemDataRole.UserRole,key)" in body
    assert 'self.nav.setCurrentRow(0)' in body


def test_group_headers_are_not_selectable_filters():
    source=(Path(__file__).resolve().parents[1]/'main.py').read_text(encoding='utf-8')
    tree=ast.parse(source)
    change=next(node for node in ast.walk(tree) if isinstance(node,ast.FunctionDef) and node.name=='change_filter')
    statement=ast.get_source_segment(source,change)
    assert 'current.data(Qt.ItemDataRole.UserRole) is not None' in statement
