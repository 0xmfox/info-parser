"""A signal written mostly in Chinese, Japanese or Korean is dropped in code.

The scoring prompt has said "English signals only" since July, and both models ignore it.
Measured on 2026-10-01 over 550 real signals, three replays a side: gpt-4.1-mini and
gpt-5-mini each passed about 17 mostly-Chinese repos at 70-75 ("让 AI 写的中文读起来像一个
具体的人在说话…", a Japanese writing skill, a Douyin pre-publish checker). A rule the
model reads and then skips is a job for code, the same reasoning as `OFF_INTEREST`.

A bilingual blurb with a real English pitch is NOT dropped: the prompt has always said
that one is fine, and a lot of good repos open in English and repeat it in Chinese.
"""
from datetime import datetime, timedelta, timezone

import topicparser.store as store
from topicparser.models import Signal
from topicparser.pipeline import run
from topicparser.prefilter import drop_non_english


def sig(desc, title="acme/tool", source="github"):
    return Signal.make(source=source, title=title, description=desc,
                       url=f"http://e/{title}/{len(desc)}", date="", profile="AI")


def test_a_chinese_description_is_dropped():
    s = sig("让 AI 写的中文读起来像一个具体的人在说话。通用创作与改稿 Skill，开箱即用。")
    assert drop_non_english([s]) == []


def test_a_japanese_description_is_dropped():
    s = sig("仕事の日本語を、読みやすくわかりやすく書く・直すための Agent Skill です。")
    assert drop_non_english([s]) == []


def test_a_bracketed_tag_in_front_does_not_rescue_chinese():
    s = sig("[dsh]为纯文本模型设计更强大的视觉工具箱：一行安装使用、粘贴图片直接识别、多张图片问答")
    assert drop_non_english([s]) == []


def test_a_bilingual_blurb_with_a_real_english_pitch_survives():
    s = sig("Run Pi and Claude Code directly in Codex Desktop. "
            "在 Codex Desktop 中直接运行 Pi 和 Claude Code。")
    assert drop_non_english([s]) == [s]


def test_chinese_first_then_a_full_english_pitch_survives():
    s = sig("一句话，做成有封面、有动画的 Live 图。Turn a sentence into a Live Photo "
            "with a designed cover and animation.")
    assert drop_non_english([s]) == [s]


def test_plain_english_survives():
    s = sig("Turn a photo of your handwriting into a real font, free and open source.")
    assert drop_non_english([s]) == [s]


def test_an_empty_description_falls_back_to_the_title():
    assert drop_non_english([sig("", title="开源短剧创作合集")]) == []
    s = sig("", title="acme/plain-tool")
    assert drop_non_english([s]) == [s]


def test_other_scripts_are_not_this_rule():
    """Cyrillic, accents and emoji are not what the measurement found leaking."""
    s = sig("Инструмент для заметок — café ✨ notes for everyone")
    assert drop_non_english([s]) == [s]


def test_the_drop_is_reported():
    seen = []
    drop_non_english([sig("开源 AI 短剧创作合集，剧本、角色资产、分镜", title="zen/drama")],
                     dropped=seen.append)
    assert seen == ["zen/drama"]


# ---- wired into the run, and visible in its log ---------------------------------

FRESH = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ')


class TwoRepos:
    source = "github"

    def collect(self, name, cfg):
        return [Signal.make(source="github", title="zen/drama",
                            description="开源 AI 短剧创作合集，剧本、角色资产、分镜",
                            url="u-zh", date=FRESH, profile=name, stars=900),
                Signal.make(source="github", title="foo/bar", description="A tool.",
                            url="u-en", date=FRESH, profile=name, stars=900)]


class Client:
    def __init__(self):
        self.seen = []

    def make(self, messages):
        self.seen.append(messages[-1]["content"])
        return ('{"scored":[{"i":0,"score":90,"reason":"r","title":"T"}],'
                '"groups":[]}')


def test_the_run_never_sends_it_to_the_model_and_logs_the_drop(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    client = Client()
    debug = tmp_path / "debug"
    run(selected=["AI"], profiles={"AI": {"github": {"topics": ["mcp"]}}},
        collectors=[TwoRepos()], client=client, threshold=80,
        x_days=3, gh_days=21, debug_dir=str(debug))
    assert "zen/drama" not in client.seen[0]
    import glob, json
    log = json.load(open(glob.glob(str(debug / "run-*.json"))[0], encoding="utf-8"))
    assert log["profiles"]["AI"]["dropped"]["non_english"] == ["zen/drama"]
