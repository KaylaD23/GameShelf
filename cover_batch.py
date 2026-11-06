"""Thread-independent batch progress and error accounting.

Qt workers and command-line tests can share this, so early interruptions do not
masquerade as 100% completed jobs and one missing cover never stops a full run.
"""
from __future__ import annotations
from dataclasses import dataclass
from collections.abc import Callable, Sequence


@dataclass
class BatchOutcome:
    processed: int = 0
    saved: int = 0
    skipped: int = 0
    failed: int = 0
    cancelled: bool = False
    last_error: str = ''


def run_batch(
    games: Sequence[dict],
    choose: Callable[[dict], object | None],
    save: Callable[[dict, object], None],
    notify: Callable[[int, str], None],
    interrupted: Callable[[], bool],
    error_formatter: Callable[[Exception], str],
    fallback_used: Callable[[], bool] = lambda: False,
) -> BatchOutcome:
    """Process every queued game unless cancelled, counting actual work only."""
    result = BatchOutcome()
    total = len(games)
    for number, game in enumerate(games, 1):
        if interrupted():
            result.cancelled = True
            break
        notify(number - 1, f'Checking {number}/{total}: {game["title"]}')
        try:
            candidate = choose(game)
            if candidate is None:
                result.skipped += 1
            else:
                save(game, candidate)
                result.saved += 1
        except Exception as exc:
            result.failed += 1
            result.last_error = error_formatter(exc)
        result.processed = number
        note = ' | Redump unavailable, using other sources' if fallback_used() else ''
        notify(number, f'Processed {number}/{total}: '
                       f'{result.saved} downloaded, {result.skipped} skipped, '
                       f'{result.failed} failed{note}')
    return result
