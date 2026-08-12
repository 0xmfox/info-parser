"""A signal scored under the bar is not scored again while it stays in the window.

Without this the same repo was re-judged every run, and since a score at this model
tier is a roll of the dice, sooner or later it rolled a 70 and reached the feed:
47 of the 70 GitHub topics on 2026-09-21 were repos that had been rejected before.
"""
from datetime import datetime, timedelta, timezone

import topicparser.store as store
from topicparser import prefilter
from topicparser.models import Signal
from topicparser.pipeline import run

FRESH = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ')


def _sig(url="https://github.com/foo/bar", stars=100):
    return Signal.make(source="github", title="foo/bar", description="d", url=url,
                       date=FRESH, profile="AI", stars=stars)


def _db(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db")
    store.init_db()


# ---- store ---------------------------------------------------------------

def test_rejected_round_trip_keeps_score_and_stars(tmp_path):
    _db(tmp_path)
    store.record_rejected([("u1", 55, 120), ("u2", 40, None)])
    assert store.rejected_links(days=30) == {"u1": (55, 120), "u2": (40, None)}


def test_rejected_upsert_keeps_the_latest_verdict(tmp_path):
    _db(tmp_path)
    store.record_rejected([("u1", 55, 120)])
    store.record_rejected([("u1", 62, 300)])
    assert store.rejected_links(days=30) == {"u1": (62, 300)}


def test_rejected_outside_the_window_is_forgotten(tmp_path):
    _db(tmp_path)
    store.record_rejected([("old", 50, 10), ("new", 50, 10)])
    store._backdate_rejected("old", days=40)
    assert set(store.rejected_links(days=30)) == {"new"}
    store.prune_rejected(days=30)
    assert set(store.rejected_links(days=365)) == {"new"}


def test_topics_wipe_clears_the_rejected_memory_too(tmp_path):
    # it is dedup state, like shown_topics: a wipe that left it behind would keep
    # hiding signals from a DB the user believes is clean
    _db(tmp_path)
    store.record_rejected([("u1", 50, 10)])
    store.reset_all(topics=True, tracked=False, banned=False)
    assert store.rejected_links(days=30) == {}


# ---- prefilter -------------------------------------------------------------

def test_drop_rejected_skips_a_signal_judged_under_the_bar():
    dropped = []
    kept = prefilter.drop_rejected([_sig("a"), _sig("b")], {"a": (55, 100)},
                                   threshold=70, dropped=dropped.append)
    assert [s.url for s in kept] == ["b"]
    assert dropped == ["a"]


def test_drop_rejected_rescores_a_repo_whose_stars_doubled():
    # a repo that took off since it was judged is a different signal now
    kept = prefilter.drop_rejected([_sig("a", stars=250)], {"a": (55, 100)}, threshold=70)
    assert [s.url for s in kept] == ["a"]
    kept = prefilter.drop_rejected([_sig("a", stars=150)], {"a": (55, 100)}, threshold=70)
    assert kept == []


def test_drop_rejected_rescores_when_the_bar_was_lowered():
    # the verdict is stored as a SCORE, not a yes/no: dropping SCORE_THRESHOLD to 60
    # must bring back what scored 65, or the knob is wired to nothing for a month
    kept = prefilter.drop_rejected([_sig("a")], {"a": (65, 100)}, threshold=60)
    assert [s.url for s in kept] == ["a"]


def test_drop_rejected_without_star_counts_still_skips():
    kept = prefilter.drop_rejected([_sig("a", stars=None)], {"a": (55, None)}, threshold=70)
    assert kept == []


# ---- pipeline --------------------------------------------------------------

class _Collector:
    source = "github"
    def collect(self, name, cfg):
        return [_sig()]


class _LowClient:
    # nothing clears the bar, so the score call is the only call a run makes
    def __init__(self):
        self.score_calls = 0
    def make(self, messages):
        self.score_calls += 1
        return '{"scored":[{"i":0,"score":50,"reason":"r"}],"groups":[]}'


def _run(client, threshold=70):
    return run(selected=["AI"], profiles={"AI": {"github": {"topics": ["mcp"]}}},
               collectors=[_Collector()], client=client, threshold=threshold,
               x_days=3, gh_days=21)


def test_second_run_does_not_pay_to_rescore_a_rejected_signal(tmp_path):
    _db(tmp_path)
    client = _LowClient()
    _run(client)
    first = client.score_calls
    assert first >= 1
    assert "https://github.com/foo/bar" in store.rejected_links(days=30)
    _run(client)
    assert client.score_calls == first
