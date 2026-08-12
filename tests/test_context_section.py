"""CONTEXT, not topics (2026-10-17, owner's call). What a lab's own X account says and what its
GitHub release / commit feeds carry is raw material for the writing project, not a post on its
own: those feeds had 0 of 6 signals at >=70 on 10-16 because a title like "v2.1.3" gives the
scorer nothing, and tweets as topics were the part he had turned off. They skip the paid scoring
and ride in the .md as their own section."""
from datetime import datetime, timedelta, timezone

import topicparser.store as store
from topicparser import export
from topicparser.collectors.x import timeline_is_past
from topicparser.models import Signal
from topicparser.pipeline import run

FRESH = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Mixed:
    source = "github"
    def collect(self, name, cfg):
        return [
            Signal.make(source="github", title="foo/bar", description="d", url="u1",
                        date=FRESH, profile=name, stars=9),
            Signal.make(source="x", title="@claudeai", description="New: /teams in Claude Code",
                        url="https://x.com/claudeai/status/1", date=FRESH, profile=name),
            Signal.make(source="feed", title="v2.1.3", description="changelog",
                        url="https://github.com/anthropics/claude-code/releases/tag/v2.1.3",
                        date=FRESH, profile=name),
            Signal.make(source="feed", title="Introducing dots", description="blog",
                        url="https://openai.com/index/dots", date=FRESH, profile=name),
        ]


class CountingClient:
    def __init__(self): self.seen = []
    def make(self, messages):
        self.seen.append(messages[-1]["content"])
        return '{"scored":[{"i":0,"score":90,"reason":"r","title":"T"},{"i":1,"score":90,"reason":"r","title":"T2"}],"groups":[]}'


def _run(tmp_path, x_as_context):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    client = CountingClient()
    out = run(selected=["AI"], profiles={"AI": {"github": {"topics": ["mcp"]}}},
              collectors=[Mixed()], client=client, threshold=80, x_days=3, gh_days=21,
              feed_days=7, x_as_context=x_as_context)
    return out, client


def test_tweets_and_github_feeds_skip_scoring_and_come_back_as_context(tmp_path):
    out, client = _run(tmp_path, x_as_context=True)
    scored_payload = client.seen[0]
    assert "foo/bar" in scored_payload and "Introducing dots" in scored_payload
    assert "@claudeai" not in scored_payload and "v2.1.3" not in scored_payload
    assert {c["url"] for c in out["context"]} == {
        "https://x.com/claudeai/status/1",
        "https://github.com/anthropics/claude-code/releases/tag/v2.1.3"}


def test_without_the_flag_tweets_are_still_topics_but_github_feeds_are_context(tmp_path):
    # the public copy keeps tweets as topics; a release title is useless to score for anyone
    out, client = _run(tmp_path, x_as_context=False)
    assert "@claudeai" in client.seen[0]
    assert [c["title"] for c in out["context"]] == ["v2.1.3"]


def test_the_md_carries_the_context_after_the_topics():
    topics = [{"title": "T", "why": "w", "links": ["https://github.com/a/b"], "score": 90,
               "source": "gh", "kept": 1}]
    ctx = [{"source": "x", "title": "@claudeai", "text": "New: /teams in Claude Code",
            "url": "https://x.com/claudeai/status/1", "date": "2026-10-16T10:00:00Z"}]
    md = export.to_markdown(topics, date="2026-10-17", context=ctx)
    assert md.index("New: /teams in Claude Code") > md.index("T")
    assert "https://x.com/claudeai/status/1" in md


def test_an_empty_context_adds_nothing():
    topics = [{"title": "T", "why": "w", "links": ["u"], "score": 90, "source": "gh", "kept": 1}]
    assert export.to_markdown(topics, date="2026-10-17", context=[]) == \
           export.to_markdown(topics, date="2026-10-17")


def test_an_account_timeline_stops_once_it_is_past_the_window():
    cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    old = (datetime.now(timezone.utc) - timedelta(days=9)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sig = lambda d: Signal.make(source="x", title="@a", description="", url="u", date=d, profile="AI")
    two_old = [sig(old), sig(old), sig(FRESH)]          # a pinned post can be old: not enough
    three_old = two_old + [sig(old)]
    assert not timeline_is_past(two_old, cutoff, "https://x.com/claudeai")
    assert timeline_is_past(three_old, cutoff, "https://x.com/claudeai")
    # a search is ranked, not chronological, so old results say nothing about the rest
    assert not timeline_is_past(three_old, cutoff, "https://x.com/search?q=claude&f=live")
    assert not timeline_is_past(three_old, None, "https://x.com/claudeai")
