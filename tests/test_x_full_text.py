"""FULL TEXT AND MEDIA from the timeline's own data (2026-10-26).

The timeline shows a long post cut at ~280 characters behind "Show more", and the scrape
read the text off the screen, so every long post reached the trends file and the Context
section as its first lines only, with no picture or video at all. The page already
receives every post whole in the JSON it renders from; reading that costs no extra
request to X. Anything unreadable leaves the screen text exactly as it was."""
from topicparser import export
from topicparser.collectors.x import enrich, parse_timeline
from topicparser.models import Signal


def _tweet(tid, text, *, uid="1", reply_to=None, reply_uid=None, note=None, media=None,
           urls=None, article=None):
    t = {"__typename": "Tweet", "rest_id": tid,
         "legacy": {"id_str": tid, "full_text": text, "user_id_str": uid,
                    "entities": {"urls": urls or []}}}
    if reply_to:
        t["legacy"]["in_reply_to_status_id_str"] = reply_to
        t["legacy"]["in_reply_to_user_id_str"] = reply_uid or uid
    if note:
        t["note_tweet"] = {"note_tweet_results": {"result": {
            "text": note, "entity_set": {"urls": urls or []}}}}
    if media:
        t["legacy"]["extended_entities"] = {"media": media}
    if article:
        t["article"] = {"article_results": {"result": article}}
    return t


def _body(*tweets):
    # the real shape nests each tweet a few levels down, sometimes inside a
    # visibility wrapper that has no `__typename` of its own on the inner object
    entries = [{"content": {"itemContent": {"tweet_results": {"result": t}}}} for t in tweets]
    wrapped = {"__typename": "TweetWithVisibilityResults",
               "tweet": {k: v for k, v in tweets[0].items() if k != "__typename"}}
    entries.append({"content": {"itemContent": {"tweet_results": {"result": wrapped}}}})
    return {"data": {"user": {"result": {"timeline": {"instructions": [{"entries": entries}]}}}}}


VIDEO = {"type": "video", "url": "https://t.co/vid", "media_url_https": "https://pbs.twimg.com/thumb.jpg",
         "video_info": {"duration_millis": 20400, "variants": [
             {"content_type": "application/x-mpegURL", "url": "https://video.twimg.com/pl.m3u8"},
             {"content_type": "video/mp4", "bitrate": 632000, "url": "https://video.twimg.com/small.mp4"},
             {"content_type": "video/mp4", "bitrate": 2176000, "url": "https://video.twimg.com/big.mp4"}]}}


def test_a_long_post_comes_back_whole_with_its_links_expanded():
    link = {"url": "https://t.co/abc", "expanded_url": "https://github.com/a/b"}
    posts = parse_timeline(_body(_tweet("10", "short cut https://t.co/abc",
                                        note="the whole long post, see https://t.co/abc",
                                        urls=[link])))
    assert posts["10"]["text"] == "the whole long post, see https://github.com/a/b"


def test_the_media_link_is_dropped_and_the_video_is_described():
    posts = parse_timeline(_body(_tweet("11", "watch this https://t.co/vid", media=[VIDEO])))
    assert posts["11"]["text"] == "watch this"
    assert posts["11"]["media"] == [{"type": "video", "url": "https://pbs.twimg.com/thumb.jpg",
                                     "video": "https://video.twimg.com/big.mp4", "seconds": 20}]


def test_an_article_carries_its_title_and_preview():
    art = {"title": "A Full Course", "preview_text": "It starts like this"}
    posts = parse_timeline(_body(_tweet("12", "https://t.co/x", article=art,
                                        urls=[{"url": "https://t.co/x",
                                               "expanded_url": "https://x.com/i/article/9"}])))
    assert posts["12"]["media"] == [{"type": "article", "title": "A Full Course"}]
    assert "It starts like this" in posts["12"]["text"]


def test_the_authors_own_reply_rides_with_the_post_and_a_strangers_does_not():
    body = _body(_tweet("20", "the post"),
                 _tweet("21", "the prompt, part one", reply_to="20"),
                 _tweet("22", "part two", reply_to="20"),
                 _tweet("23", "a stranger", uid="2", reply_to="20", reply_uid="1"))
    sig = Signal.make(source="x", title="@a", description="the post",
                      url="https://x.com/a/status/20", date="", profile="T")
    enrich([sig], parse_timeline(body))
    assert sig.reply == "the prompt, part one\n\npart two"


def test_a_self_reply_is_not_also_a_post_of_its_own_once_it_rides_under_its_post():
    body = _body(_tweet("20", "the post"), _tweet("21", "the prompt", reply_to="20"),
                 _tweet("31", "a reply to a post not scraped", reply_to="30"))
    sig = lambda n: Signal.make(source="x", title="@a", description="d",
                                url=f"https://x.com/a/status/{n}", date="", profile="T")
    kept = enrich([sig(20), sig(21), sig(31)], parse_timeline(body))
    assert [s.url[-2:] for s in kept] == ["20", "31"]


def test_enrich_fills_full_text_and_media_and_leaves_an_unknown_post_alone():
    known = Signal.make(source="x", title="@a", description="cut", url="https://x.com/a/status/11",
                        date="", profile="T")
    unknown = Signal.make(source="x", title="@a", description="as seen", url="https://x.com/a/status/99",
                          date="", profile="T")
    enrich([known, unknown], parse_timeline(_body(_tweet("11", "watch this https://t.co/vid",
                                                         media=[VIDEO]))))
    assert known.full_text == "watch this" and known.media[0]["type"] == "video"
    assert unknown.full_text == "" and unknown.media == [] and unknown.description == "as seen"


def test_rubbish_reads_as_nothing():
    assert parse_timeline(None) == {} and parse_timeline({"data": [1, "x", None]}) == {}
    assert parse_timeline(_body({"__typename": "Tweet", "rest_id": "5", "legacy": None})) == {}


def _post(handle, n, views, **kw):
    s = Signal.make(source="x", title=f"@{handle}", description=f"cut {n}",
                    url=f"https://x.com/{handle}/status/{n}", date=f"2026-10-2{n % 10}T10:00",
                    profile="Trends", metrics={"views": views})
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def test_the_trends_file_prints_the_whole_post_its_media_reply_and_how_it_did():
    posts = [_post("a", 1, 1000), _post("a", 2, 1000),
             _post("a", 3, 5000, full_text="the whole post", reply="the prompt",
                   media=[{"type": "video", "url": "https://pbs/t.jpg",
                           "video": "https://video/v.mp4", "seconds": 20}])]
    md = export.trends_markdown(posts, "2026-10-26")
    assert "the whole post" in md and "cut 3" not in md
    assert "https://video/v.mp4" in md and "https://pbs/t.jpg" in md
    assert "the prompt" in md
    assert "×5 " in md                 # 5000 against the author's usual 1000
    assert md.count("×1 ") == 2        # the two ordinary posts say so too


def test_no_ratio_for_an_author_with_too_few_posts_to_have_a_usual():
    md = export.trends_markdown([_post("b", 1, 900), _post("b", 2, 9000)], "2026-10-26")
    assert "×" not in md


def test_the_context_section_is_no_longer_cut_at_400_characters():
    long = "word " * 200
    ctx = [{"source": "x", "title": "@claudeai", "text": long.strip(), "url": "u",
            "date": "2026-10-26", "media": [{"type": "photo", "url": "https://pbs/p.jpg"}],
            "reply": "docs below"}]
    md = export.to_markdown([], date="2026-10-26", context=ctx)
    assert md.count("word") == 200
    assert "https://pbs/p.jpg" in md and "docs below" in md


def test_what_took_off_leads_the_file_and_is_not_printed_twice():
    # ~700 posts: the agent reads the top closely and searches the rest, so the posts
    # that beat their author's usual 2x or more come first, hottest first
    posts = [_post("a", 1, 1000), _post("a", 2, 1000), _post("a", 3, 1000),
             _post("a", 4, 3000), _post("a", 5, 9000)]
    md = export.trends_markdown(posts, "2026-10-26")
    hot, rest = md.split(export.i18n.t("trends.rest_heading"))
    assert export.i18n.t("trends.hot_heading", n=2) in hot
    assert hot.index("cut 5") < hot.index("cut 4") and "cut 1" not in hot
    assert "cut 4" not in rest and "cut 5" not in rest
    assert rest.index("cut 3") < rest.index("cut 2") < rest.index("cut 1")


def test_no_hot_section_when_nothing_took_off():
    md = export.trends_markdown([_post("a", n, 1000) for n in (1, 2, 3)], "2026-10-26")
    assert "##  " not in md
