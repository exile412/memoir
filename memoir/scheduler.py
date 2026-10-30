"""夜间守护进程。

行为：
- 每天在 review_at（默认 23:30）生成当天复盘
- 复盘后顺手蒸馏人格档案
- 进程重启不影响：按时间计算下一次触发，不会重复跑同一天
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import Any

from .config import Config
from .i18n import I18N
from .persona import distill
from .review import generate_review


def parse_hhmm(value: str) -> tuple[int, int]:
    try:
        hh, mm = value.split(":", 1)
        h, m = int(hh), int(mm)
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError
        return h, m
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"review_at 格式错误，应为 HH:MM：{value}") from exc


def next_run(review_at: str, now: datetime | None = None) -> datetime:
    now = now or datetime.now()
    h, m = parse_hhmm(review_at)
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def run_once(
    store: Any,
    cfg: Config,
    i18n: I18N,
    day: str | None = None,
    offline: bool = False,
    log: Any = print,
) -> dict[str, Any]:
    day = day or date.today().isoformat()
    result: dict[str, Any] = {"day": day, "review": False, "persona": 0}
    review = generate_review(store, cfg, i18n, day=day, offline=offline)
    if review is None:
        log(i18n.t("scheduler.no_entries", date=day))
        return result
    result["review"] = True
    result["entries"] = review.entries_count
    learned = distill(store, cfg, i18n, days=7, offline=offline)
    result["persona"] = len(learned)
    log(i18n.t("scheduler.done", date=day, count=str(review.entries_count), facts=str(len(learned))))
    return result


def run_daemon(
    store: Any,
    cfg: Config,
    i18n: I18N,
    offline: bool = False,
    log: Any = print,
) -> None:
    log(i18n.t("scheduler.started", at=cfg.review_at))
    while True:
        target = next_run(cfg.review_at)
        wait_s = max(1.0, (target - datetime.now()).total_seconds())
        log(i18n.t("scheduler.sleeping", target=target.strftime("%Y-%m-%d %H:%M"), hours=f"{wait_s / 3600:.1f}"))
        try:
            # 分片睡眠：方便 Ctrl+C 立刻退出
            slept = 0.0
            while slept < wait_s:
                chunk = min(60.0, wait_s - slept)
                time.sleep(chunk)
                slept += chunk
            run_once(store, cfg, i18n, offline=offline, log=log)
        except KeyboardInterrupt:
            log(i18n.t("scheduler.stopped"))
            return
