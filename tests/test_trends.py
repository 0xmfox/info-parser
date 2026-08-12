"""Trends: a separate scrape of a list of X authors into its own .md, no scoring.

The owner hands the file to Claude to read what the people who get views are posting
right now. Nothing is judged here: every fresh post of every listed author, with its
link, text and numbers."""
import threading

from topicparser import paths
from topicparser.api import Api
from topicparser.collectors.x import parse_tweet
from topicparser.models import Signal


class FakeEl:
    def __init__(self, label):
        self._label = label
    def links(self): return ["/someone/status/123"]
    def inner_text(self): return "hello"
    def tweet_text(self): return "hello"
    def time_datetime(self): return "2026-10-21T10:00:00.000Z"
    def repost_href(self): return None
    def metrics_label(self): return self._label


def test_a_tweet_carries_its_views_likes_and_bookmarks():
    sig = parse_tweet(FakeEl("2 replies, 3 reposts, 1,204 likes, 310 bookmarks, 48,213 views"), "T")
    assert sig.metrics == {"replies": 2, "reposts": 3, "likes": 1204,
                           "bookmarks": 310, "views": 48213}


def test_a_cell_without_numbers_still_parses():
    assert parse_tweet(FakeEl(""), "T").metrics == {}


def _api(tmp_path, monkeypatch, collectors=lambda: []):
    monkeypatch.setattr(paths, "app_dir", lambda: str(tmp_path))
    return Api(profiles={}, build_collectors=collectors, build_client=lambda: None,
               threshold=70, x_days=3, gh_days=60)


def test_the_author_list_round_trips_cleaned(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch)
    assert api.save_trends("@alice, bob\n\nALICE carol_1") == {"ok": True, "count": 3}
    assert api.get_trends() == {"handles": ["alice", "bob", "carol_1"]}


def test_a_handle_x_cannot_have_is_refused_and_nothing_is_written(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch)
    api.save_trends("alice")
    res = api.save_trends("alice ім'я")
    assert res.get("errors")
    assert api.get_trends() == {"handles": ["alice"]}


class FakeX:
    source = "x"
    def __init__(self, posts):
        self.posts, self.calls = posts, []
    def collect(self, profile, cfg):
        self.calls.append((profile, cfg))
        if getattr(self, "warn", None):
            self.warn("one account did not load")
        return self.posts


def _post(handle, date, views=10):
    return Signal(source="x", title=f"@{handle}", description=f"post by {handle}",
                  url=f"https://x.com/{handle}/status/{date[-2:]}", date=date,
                  profile="Trends", metrics={"views": views, "likes": 2, "bookmarks": 1})


def test_a_trends_run_scrapes_only_the_list_and_never_builds_a_client(tmp_path, monkeypatch):
    x = FakeX([_post("alice", "2026-10-20T01"), _post("bob", "2026-10-21T02")])
    other = type("GH", (), {"source": "github", "collect": lambda *a: 1 / 0})()

    def no_client():
        raise AssertionError("trends must not reach the model")

    api = _api(tmp_path, monkeypatch, collectors=lambda: [other, x])
    api._build_client = no_client
    api.save_trends("alice bob")
    res = api.run_trends()

    assert x.calls[0] == ("Trends", {"x": {"accounts": ["alice", "bob"]}})
    assert "searches" in x.calls[1][1]["x"]     # then the Radar (tests/test_radar.py)
    assert res["count"] == 2 and res["authors"] == 2
    assert "one account did not load" in res["warnings"]
    assert api.is_running() is False


def test_an_empty_list_is_refused_before_any_scrape(tmp_path, monkeypatch):
    x = FakeX([])
    api = _api(tmp_path, monkeypatch, collectors=lambda: [x])
    assert api.run_trends().get("error")
    assert x.calls == []


def test_trends_share_the_run_lock_with_the_parser(tmp_path, monkeypatch):
    # one scrape account: two scrapes at once look exactly like a bot
    api = _api(tmp_path, monkeypatch, collectors=lambda: [FakeX([])])
    api.save_trends("alice")
    api._running = True
    assert api.run_trends().get("error")


def test_the_trends_file_is_newest_first_with_link_text_and_numbers(tmp_path, monkeypatch):
    from datetime import date, timedelta
    day = lambda n: (date.today() - timedelta(days=n)).isoformat()
    x = FakeX([_post("alice", day(1) + "T01", views=48213), _post("bob", day(0) + "T02")])
    api = _api(tmp_path, monkeypatch, collectors=lambda: [x])
    api.save_trends("alice bob")
    api.run_trends()
    out = tmp_path / "t.md"

    assert api.save_trends_md(str(out))["ok"] is True
    md = (tmp_path / "rest-t.md").read_text(encoding="utf-8")
    assert md.index("@bob") < md.index("@alice")
    assert "https://x.com/alice/status/01" in md and "post by alice" in md
    assert "48,213" in md


def test_nothing_scraped_means_no_file_and_no_dialog(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch)
    assert api.save_trends_md() == {"ok": False, "empty": True}
