"""Radar: posts that took off on SMALL accounts that are in no list of ours.

The trends list only sees the 84 authors the owner typed in. The posts that tell a wave
is starting are often somebody small whose one post got saved thousands of times
(owner, 2026-10-31). X search finds them; the author's follower count, read off the same
timeline JSON the full text already comes from, says who is small."""
from datetime import datetime, timedelta, timezone

from topicparser import export, paths
from topicparser.api import Api, RADAR_MAX_FOLLOWERS, RADAR_MIN_LIKES
from topicparser.collectors.x import enrich, parse_timeline, timeline_is_past
from topicparser.models import Signal


def _now(days_ago=0, hours=0):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago, hours=hours)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z")


def _tweet(tid, followers):
    return {"rest_id": tid, "legacy": {"id_str": tid, "full_text": "hi", "user_id_str": "9"},
            "core": {"user_results": {"result": {"rest_id": "9",
                                                 "legacy": {"followers_count": followers}}}}}


def test_the_authors_follower_count_comes_off_the_timeline_json():
    posts = parse_timeline({"data": [_tweet("111", 4200)]})
    s = Signal.make(source="x", title="@a", description="hi",
                    url="https://x.com/a/status/111", date=_now(), profile="T")
    enrich([s], posts)
    assert s.followers == 4200


def test_the_2026_10_shape_carries_followers_under_relationship_counts():
    # measured live 2026-10-31 on a SearchTimeline: no `followers_count` anywhere
    t = _tweet("111", 0)
    t["core"]["user_results"]["result"] = {"relationship_counts": {"followers": 14145}}
    s = Signal.make(source="x", title="@a", description="hi",
                    url="https://x.com/a/status/111", date=_now(), profile="T")
    enrich([s], parse_timeline([t]))
    assert s.followers == 14145


def test_a_tweet_without_a_user_block_has_no_follower_count():
    t = _tweet("111", 1)
    del t["core"]
    s = Signal.make(source="x", title="@a", description="hi",
                    url="https://x.com/a/status/111", date=_now(), profile="T")
    enrich([s], parse_timeline([t]))
    assert s.followers is None


def test_a_latest_search_is_chronological_so_it_stops_on_age_and_a_top_one_does_not():
    cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    old = [Signal.make(source="x", title="@a", description="", url="u", date=_now(9),
                       profile="T") for _ in range(3)]
    assert timeline_is_past(old, cutoff, "https://x.com/search?q=grok&f=live")
    assert not timeline_is_past(old, cutoff, "https://x.com/search?q=grok&f=top")


class FakeX:
    source = "x"

    def __init__(self, by_kind):
        self.by_kind, self.calls = by_kind, []

    def collect(self, profile, cfg):
        self.calls.append(cfg["x"])
        return self.by_kind["searches" if "searches" in cfg["x"] else "accounts"]


def _post(handle, followers, bookmarks, days_ago=0, views=1000):
    return Signal(source="x", title=f"@{handle}", description=f"post by {handle}",
                  url=f"https://x.com/{handle}/status/{bookmarks}", date=_now(days_ago, 1),
                  profile="Trends", followers=followers,
                  metrics={"views": views, "likes": 400, "bookmarks": bookmarks})


def _api(tmp_path, monkeypatch, x):
    monkeypatch.setattr(paths, "app_dir", lambda: str(tmp_path))
    return Api(profiles={}, build_collectors=lambda: [x], build_client=lambda: None,
               threshold=70, x_days=3, gh_days=60)


def test_the_radar_keeps_small_strangers_only_most_saved_first(tmp_path, monkeypatch):
    x = FakeX({"accounts": [_post("alice", 900, 5)],
               "searches": [_post("small", 3000, 300), _post("tiny", 800, 900),
                            _post("big", RADAR_MAX_FOLLOWERS, 5000),   # not small
                            _post("alice", 900, 7000),                 # already on the list
                            _post("unknown", None, 8000),              # cannot tell: out
                            _post("stale", 100, 9000, days_ago=5)]})   # older than the window
    api = _api(tmp_path, monkeypatch, x)
    api.save_trends("alice")
    res = api.run_trends()

    queries = x.calls[1]["searches"]
    assert queries and all(f"min_faves:{RADAR_MIN_LIKES}" in q and "-filter:replies" in q
                           for q in queries)
    assert [p.title for p in api._last_radar] == ["@tiny", "@small"]
    assert res["radar"] == 2


def test_the_radar_drops_what_was_liked_and_not_saved(tmp_path, monkeypatch):
    meme = _post("meme", 900, 400)
    meme.metrics["likes"] = 5000                                  # saved by 8 %
    x = FakeX({"accounts": [], "searches": [meme, _post("few", 900, 299), _post("good", 900, 300)]})
    api = _api(tmp_path, monkeypatch, x)
    api.save_trends("alice")
    api.run_trends()
    assert [p.title for p in api._last_radar] == ["@good"]


def test_an_old_post_is_not_shown_but_still_counts_towards_the_usual():
    old = [_post("a", 1, i, days_ago=8, views=100) for i in range(1, 4)]
    fresh = _post("a", 1, 98, days_ago=1, views=5000)
    today = fresh.date[:10]
    md = export.trends_markdown(old + [fresh], today, max_days=5)
    assert "/status/98" in md and "/status/1\n" not in md
    assert "×50" in md                    # the usual of 100 came from the hidden posts
    assert export.i18n.t("trends.md_summary", posts=1, authors=1) in md


def test_the_rest_goes_to_its_own_file(tmp_path):
    hot = [_post("a", 1, i, days_ago=1, views=100) for i in range(1, 4)]
    star = _post("a", 1, 98, days_ago=1, views=5000)
    path = tmp_path / "trends-2026-11-09.md"
    export.write_trends(hot + [star], str(path), date=star.date[:10])
    head, rest = path.read_text(encoding="utf-8"), (tmp_path / "rest-2026-11-09.md").read_text(encoding="utf-8")
    assert "/status/98" in head and "/status/1\n" not in head
    assert "/status/1\n" in rest and "/status/98" not in rest


def test_the_official_sources_land_in_their_own_section(tmp_path, monkeypatch):
    x = FakeX({"accounts": [], "searches": [_post("OpenAI", None, 1)]})
    feed = type("F", (), {"source": "feed", "calls": [],
                          "collect": lambda self, p, c: self.calls.append(c) or []})()
    monkeypatch.setattr(paths, "app_dir", lambda: str(tmp_path))
    api = Api(profiles={"profiles": {"AI": {
                  "x": {"accounts": ["OpenAI"], "searches": ["from:somebody launch"]},
                  "feeds": {"urls": ["https://github.com/a/b/releases.atom", "https://blog.x/rss"]}}}},
              build_collectors=lambda: [x, feed], build_client=lambda: None,
              threshold=70, x_days=3, gh_days=60)
    api.save_trends("alice")
    api.run_trends()
    assert x.calls[-1] == {"accounts": ["OpenAI"], "searches": ["from:somebody launch"]}
    assert feed.calls == [{"feeds": {"urls": ["https://github.com/a/b/releases.atom"]}}]
    md = export.trends_markdown([], api._last_official[0].date[:10], official=api._last_official)
    assert export.i18n.t("trends.official_heading", n=1) in md and "@OpenAI" in md


def test_a_scrape_in_another_process_refuses_this_one_until_its_lock_goes_stale(tmp_path, monkeypatch):
    import os, time
    x = FakeX({"accounts": [], "searches": []})
    api = _api(tmp_path, monkeypatch, x)
    api.save_trends("alice")
    lock = tmp_path / "scrape.lock"
    lock.write_text("", encoding="utf-8")
    assert "error" in api.run_trends() and x.calls == []
    assert lock.exists()                   # somebody else's lock is not ours to remove
    old = time.time() - 4 * 3600
    os.utime(lock, (old, old))
    assert "error" not in api.run_trends() and x.calls
    assert not lock.exists()


def test_the_radar_queries_are_the_owners_file_when_he_has_one(tmp_path, monkeypatch):
    x = FakeX({"accounts": [], "searches": []})
    api = _api(tmp_path, monkeypatch, x)
    api.save_trends("alice")
    (tmp_path / "radar.txt").write_text("cursor agent\n\n", encoding="utf-8")
    api.run_trends()
    assert x.calls[1]["searches"] == [f"cursor agent min_faves:{RADAR_MIN_LIKES} -filter:replies lang:en"]


def test_the_radar_is_its_own_section_with_the_follower_count():
    md = export.trends_markdown([], "2026-10-31", radar=[_post("tiny", 800, 900)])
    assert "@tiny" in md and "800" in md
    assert md.index("##  ") < md.index("@tiny")


def test_an_old_pinned_post_never_leads_the_hot_section():
    usual = [_post("a", 1, i, days_ago=1, views=100) for i in range(1, 4)]
    pinned = _post("a", 1, 99, days_ago=60, views=100000)
    fresh = _post("a", 1, 98, days_ago=1, views=5000)
    md = export.trends_markdown(usual + [pinned, fresh], "2026-10-31")
    hot, rest = md.split(export.i18n.t("trends.rest_heading"))
    assert "/status/98" in hot and "/status/99" not in hot
    assert "/status/99" in rest           # still in the file, once


def test_the_screen_reads_the_radar_searches_and_the_defaults_when_there_is_no_file(tmp_path, monkeypatch):
    from topicparser.api import RADAR_QUERIES
    api = _api(tmp_path, monkeypatch, FakeX({}))
    assert api.get_radar() == {"queries": list(RADAR_QUERIES)}
    (tmp_path / "radar.txt").write_text("cursor agent\n\n codex \n", encoding="utf-8")
    assert api.get_radar() == {"queries": ["cursor agent", "codex"]}


def test_saving_the_radar_from_the_screen_writes_what_the_run_reads(tmp_path, monkeypatch):
    x = FakeX({"accounts": [], "searches": []})
    api = _api(tmp_path, monkeypatch, x)
    assert api.save_radar(["cursor agent", " codex ", "", "cursor agent"]) == {"ok": True, "count": 2}
    api.save_trends("alice")
    api.run_trends()
    assert [q.split(" min_faves")[0] for q in x.calls[1]["searches"]] == ["cursor agent", "codex"]


def test_an_empty_radar_is_refused_rather_than_silently_turning_into_the_defaults(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch, FakeX({}))
    api.save_radar(["codex"])
    assert "errors" in api.save_radar(["", "  "])
    assert api.get_radar() == {"queries": ["codex"]}
