#!/usr/bin/env python3
"""Post one finished Codex writing task back to the local script workbench.

The script is deliberately dependency-free and talks only to a loopback workbench. It
always writes the return package to an outbox file first, so a failed delivery can be
retried with ``--retry`` without rebuilding the payload.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
CONTENT_LIMIT = 100000
EXPERIENCE_LIMIT = 20
TEMPORARY_REQUIREMENT_LIMIT = 20
TIMEOUT_SECONDS = 30

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_UNDELIVERED = 3
EXIT_REJECTED = 4


class ReturnError(Exception):
    """A payload or descriptor problem that must be fixed before posting."""


def read_json(path: Path, label: str) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ReturnError(f"读不到{label}：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ReturnError(f"{label}不是合法 JSON：{path}") from exc
    if not isinstance(raw, dict):
        raise ReturnError(f"{label}必须是 JSON 对象：{path}")
    return raw


def validate_endpoint(value: str) -> str:
    endpoint = str(value or "").strip()
    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme != "http" or (parsed.hostname or "") not in LOOPBACK_HOSTS:
        raise ReturnError(f"回传地址必须指向本机工作台（127.0.0.1），当前是：{endpoint}")
    if not parsed.path.startswith("/api/writing-agent-tasks/"):
        raise ReturnError(f"回传地址不是工作台回传接口：{endpoint}")
    return endpoint


def _one_line(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def normalize_experiences(value: object) -> list[dict[str, str]]:
    items = value if isinstance(value, list) else []
    experiences: list[dict[str, str]] = []
    for entry in items:
        raw = entry if isinstance(entry, dict) else {}
        rule = _one_line(raw.get("rule"), 300)
        if not rule:
            continue
        node = _one_line(raw.get("node"), 20) or "content"
        experiences.append({
            "rule": rule,
            "evidence": _one_line(raw.get("evidence"), 600),
            "node": node if node in {"structure", "content"} else "content",
        })
        if len(experiences) >= EXPERIENCE_LIMIT:
            break
    return experiences


def normalize_requirements(value: object) -> list[str]:
    items = value if isinstance(value, list) else []
    requirements: list[str] = []
    for entry in items:
        text = _one_line(entry, 300)
        if text and text not in requirements:
            requirements.append(text)
        if len(requirements) >= TEMPORARY_REQUIREMENT_LIMIT:
            break
    return requirements


def build_package(descriptor: dict, payload: dict) -> dict:
    endpoint = validate_endpoint(descriptor.get("endpoint"))
    task_id = _one_line(descriptor.get("id"), 64)
    token = str(descriptor.get("token") or "")
    if not task_id or not token:
        raise ReturnError("任务描述文件缺少任务标识或回传凭证，请从工作台重新发起 Agent 生成。")
    content = str(payload.get("content") or "").strip()
    if not content:
        raise ReturnError("回传脚本内容为空。")
    if len(content) > CONTENT_LIMIT:
        raise ReturnError("回传内容超过 100000 字，请先缩短；内容未截断或提交。")
    submission_id = _one_line(payload.get("submissionId"), 200)
    if not submission_id:
        # Deterministic so an unlabelled retry of the same script is not stored twice.
        submission_id = hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]
    return {
        "taskId": task_id,
        "endpoint": endpoint,
        "token": token,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "body": {
            "submissionId": submission_id,
            "content": content[:CONTENT_LIMIT],
            "experiences": normalize_experiences(payload.get("experiences")),
            "temporaryRequirements": normalize_requirements(payload.get("temporaryRequirements")),
        },
    }


def outbox_path(descriptor_path: Path, package: dict) -> Path:
    directory = descriptor_path.parent / "return-outbox"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / (hashlib.sha256((package["taskId"] + package["body"]["submissionId"]).encode()).hexdigest() + ".json")


def post_package(package: dict) -> tuple[int, object]:
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    request = urllib.request.Request(
        validate_endpoint(package["endpoint"]),
        data=json.dumps(package["body"], ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Writing-Agent-Token": package["token"],
        },
        method="POST",
    )
    # Never route the return through a system HTTP proxy: the workbench is loopback only.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
            status = response.status
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        return exc.code, detail
    except (urllib.error.URLError, OSError) as exc:
        return 0, str(exc)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return status, raw
    return status, parsed


def describe(status: int, payload: object) -> str:
    if status == 200 and isinstance(payload, dict):
        message = str(payload.get("message") or "")
        applied = bool(payload.get("applied"))
        created = int(payload.get("candidateCreated") or 0)
        duplicated = int(payload.get("candidateDuplicated") or 0)
        parts = [message or ("已把回传稿写入工作台。" if applied else "已保存为待采用版本。")]
        parts.append(f"本次新增待确认经验 {created} 条" + (f"，跳过重复 {duplicated} 条" if duplicated else ""))
        return "；".join(parts)
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, dict) and detail.get("message"):
            return str(detail["message"])
        if isinstance(detail, str):
            return detail
        if payload.get("message"):
            return str(payload["message"])
    return str(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把定稿脚本回传到本地视频脚本工作台")
    parser.add_argument("--descriptor", help="工作台写入的任务描述文件路径")
    parser.add_argument("--payload", help="包含 content / experiences 的 JSON 文件路径")
    parser.add_argument("--retry", help="重发上一次已保存在 outbox 的回传包")
    parser.add_argument("--dry-run", action="store_true", help="只打包并打印，不提交")
    args = parser.parse_args(argv)

    if args.retry:
        package = read_json(Path(args.retry).expanduser(), "回传包")
        for field in ("taskId", "endpoint", "token", "body"):
            if not package.get(field):
                raise ReturnError(f"回传包缺少字段 {field}：{args.retry}")
    else:
        if not args.descriptor or not args.payload:
            parser.error("需要同时提供 --descriptor 和 --payload，或使用 --retry")
        descriptor_path = Path(args.descriptor).expanduser()
        package = build_package(
            read_json(descriptor_path, "任务描述文件"),
            read_json(Path(args.payload).expanduser(), "回传内容"),
        )
        saved = outbox_path(descriptor_path, package)
        with saved.open("w", encoding="utf-8") as out:
            if os.name != "nt":
                os.chmod(saved, 0o600)
            json.dump(package, out, ensure_ascii=False, indent=2)
        print(f"本地回传包：{saved}")

    if args.dry_run:
        print(json.dumps(package["body"], ensure_ascii=False, indent=2))
        return EXIT_OK

    status, payload = post_package(package)
    if status == 200:
        print(describe(status, payload))
        return EXIT_OK
    if status == 0:
        print(f"未能连接工作台，回传包已保留，可稍后用 --retry 重试：{payload}", file=sys.stderr)
        return EXIT_UNDELIVERED
    print(f"工作台拒绝了这次回传（HTTP {status}）：{describe(status, payload)}", file=sys.stderr)
    return EXIT_REJECTED


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReturnError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(EXIT_USAGE) from None
