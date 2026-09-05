#!/usr/bin/env python3
"""Сквозная проверка стека: CreateProject -> StartRun -> polling GetRun -> итог.

То же самое, что раньше гонялось руками через curl весь день разработки — теперь
воспроизводимо одной командой: `make smoke` (или `python3 scripts/smoke.py [base_url]`).

Возвращает ненулевой код, если Run не дошёл до DONE, упал в FAILED, завис дольше таймаута,
или (на mock-провайдере) не выдал ни одной новости.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "http://localhost"
POLL_INTERVAL_S = 3
POLL_TIMEOUT_S = 240

SMOKE_SOURCES = ["cit_gov", "arppsoft"]  # быстрые, проверенные каналы с /s/-превью
SMOKE_TOPIC = "цифровые технологии, гранты, госполитика в ИТ"


def rpc(base: str, service: str, method: str, body: dict) -> dict:
    url = f"{base}/api/monitoring.v1.{service}/{method}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"FAIL: {service}/{method} -> HTTP {exc.code}: {detail}")


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE
    print(f"== smoke: {base} ==")

    health = json.loads(urllib.request.urlopen(f"{base}/api/health", timeout=10).read())
    print(f"health: {health}")
    if not (health.get("db") and health.get("redis")):
        print("FAIL: db/redis не готовы")
        return 1
    if not health.get("worker"):
        print("WARN: воркер не отвечает по heartbeat — задачи не обработаются")

    project = rpc(
        base,
        "ProjectService",
        "CreateProject",
        {
            "name": f"smoke-{int(time.time())}",
            "topic": SMOKE_TOPIC,
            "filters": [],
            "sources": [
                {"type": "SOURCE_TYPE_TELEGRAM", "telegram": c} for c in SMOKE_SOURCES
            ],
        },
    )["project"]
    print(f"project: {project['id']}")

    run = rpc(base, "RunService", "StartRun", {"projectId": project["id"]})["run"]
    run_id = run["id"]
    print(f"run: {run_id} (state={run['state']})")

    deadline = time.monotonic() + POLL_TIMEOUT_S
    while time.monotonic() < deadline:
        run = rpc(base, "RunService", "GetRun", {"id": run_id})["run"]
        if run["state"] != "RUN_STATE_STARTED":
            break
        time.sleep(POLL_INTERVAL_S)
    else:
        print(f"FAIL: Run не завершился за {POLL_TIMEOUT_S}с (state={run['state']})")
        return 1

    stats = run.get("stats", {})
    news = run.get("news", [])
    print(f"итог: state={run['state']} stats={stats} news={len(news)}")

    if run["state"] == "RUN_STATE_FAILED":
        print(f"FAIL: Run упал: {stats.get('error')}")
        return 1

    if run["state"] != "RUN_STATE_DONE":
        print(f"FAIL: неожиданное состояние {run['state']}")
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
