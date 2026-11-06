"""v0.9.14: imported Roman numerals and existing SQLite titles."""
import sqlite3
from pathlib import Path

import pytest

from core import Library, safe_name, scan_games


@pytest.mark.parametrize('filename, expected', [
    ('Phantasy Star Online Episode I & II.iso', 'Phantasy Star Online Episode I & II'),
    ('Grandia II.iso', 'Grandia II'),
    ('Final Fantasy VII.chd', 'Final Fantasy VII'),
    ('Metal Gear Solid IV.iso', 'Metal Gear Solid IV'),
    ('Final Fantasy VIII.iso', 'Final Fantasy VIII'),
    ('Episode IX.iso', 'Episode IX'),
    ('Episode XII.iso', 'Episode XII'),
    ('Crash Bandicoot.iso', 'Crash Bandicoot'),
    ('music mix.iso', 'Music Mix'),
    ('MUSIC MIX.iso', 'Music Mix'),
    ('A Train 6.iso', 'A Train 6'),
    ('Tony Hawk\'s Pro Skater 2.iso', "Tony Hawk'S Pro Skater 2"),
])
def test_title_formatter(filename, expected):
    assert safe_name(filename) == expected


def test_scanning_disc_keeps_roman_numerals(tmp_path):
    game = tmp_path/'Phantasy Star Online Episode I & II.iso'
    game.touch()
    scanned = scan_games(tmp_path, 'xbox')
    assert scanned == [("Phantasy Star Online Episode I & II", 'xbox', str(game))]


def test_existing_database_upgrades_only_automatically_generated_titles(tmp_path):
    path=tmp_path/'db.sqlite3'
    db=Library(path)
    p1=tmp_path/'Phantasy Star Online Episode I & II.iso'
    p2=tmp_path/'Grandia II.iso'
    p3=tmp_path/'Final Fantasy VII.iso'
    for f in (p1,p2,p3):f.touch()
    assert db.add('Phantasy Star Online Episode I & Ii','xbox','xemu',str(p1))
    assert db.add('Grandia Ii','ps2','pcsx2',str(p2))
    assert db.add('Final Fantasy VII Remastered','ps1','duckstation',str(p3))
    r1=db.all()[0]
    target=next(g for g in db.all() if g['path']==str(p1))
    db.edit(target['id'],artwork='my-custom-cover.png',favorite=1,seconds_played=115,ps3_args='')
    db.close()
    db=Library(path)
    games={g['path']:g for g in db.all()}
    assert games[str(p1)]['title']=='Phantasy Star Online Episode I & II'
    assert games[str(p2)]['title']=='Grandia II'
    assert games[str(p3)]['title']=='Final Fantasy VII Remastered'
    assert games[str(p1)]['artwork']=='my-custom-cover.png'
    assert games[str(p1)]['favorite']==1
    assert games[str(p1)]['seconds_played']==115
    db.close()
    # Reopening is idempotent; no title loss.
    db=Library(path)
    assert db.get(games[str(p1)]['id'])['title']=='Phantasy Star Online Episode I & II'
    db.close()


def test_manually_edited_title_never_overwritten(tmp_path):
    path=tmp_path/'db.sqlite3'
    db=Library(path)
    f=tmp_path/'Final Fantasy VII.iso';f.touch()
    db.add('Some personal name','ps1','duckstation',str(f))
    db.close()
    db=Library(path)
    assert db.all()[0]['title']=='Some personal name'
    db.close()
