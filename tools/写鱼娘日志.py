# -*- coding: utf-8 -*-
"""写一条「鱼娘的日志」到 memoir。

用法：
    python 写鱼娘日志.py "正文" [标签]
    echo 正文 | python 写鱼娘日志.py -

做的事：
1. 走 memoir 自己的 HTTP 接口新增（保证全文索引同步）
2. 把这条挪进「鱼娘的日志」文件夹（folder id 7）
3. 把作者改成 ai（memoir 默认会记成「我」）
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8765"
FOLDER_ID = 7  # 鱼娘的日志
DB = Path.home() / ".memoir" / "memoir.db"


def post(route: str, payload: dict, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        f"{BASE}/api/{route}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python 写鱼娘日志.py \"正文\" [标签]")
        return 2
    text = sys.stdin.read() if sys.argv[1] == "-" else sys.argv[1]
    text = text.strip()
    if not text:
        print("正文为空")
        return 2
    tags = sys.argv[2] if len(sys.argv) > 2 else "日志"

    added = post("entries", {"text": text, "kind": "note", "tags": tags, "autoTitle": False})
    entry = added.get("entry") or {}
    eid = entry.get("id")
    if not eid:
        print("新增失败:", added)
        return 1
    print(f"新增 #{eid}")

    post("entries/move", {"id": eid, "folderId": FOLDER_ID})
    print(f"已移入 鱼娘的日志（folder {FOLDER_ID}）")

    # 作者改成 ai；短事务，碰上锁就重试几次
    for attempt in range(5):
        try:
            con = sqlite3.connect(str(DB), timeout=5)
            con.execute("UPDATE entries SET author='ai', source='ai' WHERE id=?", (eid,))
            con.commit()
            con.close()
            print("作者已设为 ai")
            return 0
        except sqlite3.OperationalError as exc:
            print(f"  改作者失败（{exc}），重试 {attempt + 1}/5")
            time.sleep(1.5)
    print("作者没改成 ai，条目已在鱼娘的日志里，只是显示成「我」")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
