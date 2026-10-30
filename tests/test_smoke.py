"""冒烟测试：不联网、不依赖 pytest 之外的任何东西。

跑法：
    python -m pytest tests/ -q
或直接：
    python tests/test_smoke.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memoir.config import Config, ModelConfig  # noqa: E402
from memoir.i18n import I18N  # noqa: E402
from memoir.llm import extract_json  # noqa: E402
from memoir.persona import distill, render_profile  # noqa: E402
from memoir.review import generate_review, render_review  # noqa: E402
from memoir.storage import Store  # noqa: E402


def _cfg(tmp: Path) -> Config:
    cfg = Config(home=tmp, lang="zh", model=ModelConfig(base_url="http://127.0.0.1:1/v1", name="none"))
    cfg.ensure_dirs()
    return cfg


def test_add_and_query(tmp_path: Path) -> None:
    with Store(tmp_path / "t.db") as store:
        eid = store.add_entry("今天写了测试", kind="event", tags="dev")
        assert eid > 0
        day = store.recent(1)[0].day
        entries = store.entries_for_day(day)
        assert len(entries) == 1
        assert entries[0].text == "今天写了测试"
        assert store.count_entries() == 1
        hits = store.search("测试")
        assert any(h.id == eid for h in hits)


def test_delete(tmp_path: Path) -> None:
    with Store(tmp_path / "d.db") as store:
        eid = store.add_entry("待删除")
        assert store.delete_entry(eid) is True
        assert store.count_entries() == 0
        assert store.delete_entry(eid) is False


def test_review_fallback(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    i18n = I18N("zh")
    with Store(tmp_path / "r.db") as store:
        store.add_entry("上午改代码，还是没跑通", kind="event")
        store.add_entry("有点怀疑自己", kind="thought")
        day = store.recent(1)[0].day
        review = generate_review(store, cfg, i18n, day=day, offline=True)
        assert review is not None
        assert review.model == "fallback"
        assert review.sections["events"]
        text = render_review(review, i18n)
        assert day in text
        # 幂等：同一天再跑一次不会重复建行
        again = generate_review(store, cfg, i18n, day=day, offline=True)
        assert again is not None
        assert len(store.list_reviews(limit=10)) == 1


def test_review_empty_day(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    with Store(tmp_path / "e.db") as store:
        assert generate_review(store, cfg, I18N("zh"), day="2000-01-01", offline=True) is None


def test_persona_fallback_does_not_learn_garbage(tmp_path: Path) -> None:
    """本地兜底文案不是观察，不应该进入人格档案。"""
    cfg = _cfg(tmp_path)
    i18n = I18N("zh")
    with Store(tmp_path / "p.db") as store:
        store.add_entry("跑了一天", kind="event")
        day = store.recent(1)[0].day
        generate_review(store, cfg, i18n, day=day, offline=True)
        learned = distill(store, cfg, i18n, days=7, offline=True)
        assert learned == []
        assert store.list_facts() == []
        assert render_profile(store, i18n)


def test_i18n_all_locales_have_core_keys() -> None:
    required = [
        "cli.add_ok",
        "report.title",
        "report.sections.events",
        "persona.title",
        "scheduler.started",
        "prompts.review_system",
        "prompts.review_schema",
        "prompts.persona_system",
    ]
    i18n = I18N("zh")
    for lang in i18n.available():
        loc = I18N(lang)
        for key in required:
            assert loc.raw(key) is not None, f"{lang} 缺少 {key}"


def test_i18n_fallback() -> None:
    i18n = I18N("xx")  # 不存在的语言 -> 回退到 en
    assert i18n.t("cli.add_ok") != "cli.add_ok"


def test_extract_json_dirty_output() -> None:
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('好的，如下：\n```json\n{"a": 2}\n```\n以上') == {"a": 2}
    assert extract_json('前言 [{"k": "v"}] 后记') == [{"k": "v"}]
    assert extract_json("完全不是 JSON") is None


def test_extract_json_truncated() -> None:
    """小模型常见：字段写完但少一个右花括号，或者字符串都没闭合。"""
    assert extract_json('{ "events": "aaa", "closing": "bbb"') == {
        "events": "aaa",
        "closing": "bbb",
    }
    assert extract_json('{ "events": "aaa') == {"events": "aaa"}
    assert extract_json('[{"a": 1}, {"b": 2}') == [{"a": 1}, {"b": 2}]
    assert extract_json('{"a": {"b": [1, 2') == {"a": {"b": [1, 2]}}


def test_unwrap_and_normalize() -> None:
    """模型把对象套进数组、或者直接给列表时都要能接住。"""
    from memoir.llm import unwrap_object
    from memoir.persona import _normalize_items

    assert unwrap_object({"a": 1}) == {"a": 1}
    assert unwrap_object([{"a": 1}]) == {"a": 1}
    assert unwrap_object([{"a": 1}, {"b": 2}]) == [{"a": 1}, {"b": 2}]
    assert _normalize_items({"facts": [1, 2]}) == [1, 2]
    assert _normalize_items([{"facts": [1, 2]}]) == [1, 2]
    assert _normalize_items([{"key": "k", "value": "v"}]) == [{"key": "k", "value": "v"}]
    assert _normalize_items("nope") is None


def test_export_shape(tmp_path: Path) -> None:
    with Store(tmp_path / "x.db") as store:
        store.add_entry("一条")
        data = store.export_all()
        assert data["version"] == 1
        assert len(data["entries"]) == 1
        json.dumps(data, ensure_ascii=False)


if __name__ == "__main__":
    import tempfile

    failures = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        with tempfile.TemporaryDirectory() as td:
            try:
                if fn.__code__.co_argcount == 1:
                    fn(Path(td))
                else:
                    fn()
                print(f"PASS {name}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    print("OK" if failures == 0 else f"{failures} failure(s)")
    raise SystemExit(1 if failures else 0)
