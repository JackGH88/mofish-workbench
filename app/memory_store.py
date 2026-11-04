"""本地 Markdown 记忆库。

一条记忆一个 MD 文件，MD 是该记忆正文的唯一来源：工作台只负责读写这些文件，
不保留第二份正文副本。文件开头是一段 ``---`` 围栏元信息，正文分成
``## 记忆内容`` 与可选的 ``## 来源依据`` 两节。索引每次都从目录重建，
所以在 Obsidian 里改名、移动或直接编辑都会在下次读取时生效。
"""
from __future__ import annotations

import json
import os
import re
import uuid
from . import memory_index
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

MEMORY_FORMAT_VERSION = 1
MEMORY_CATEGORIES = ("preference", "experience", "reference_copy")
MEMORY_SCOPES = ("structure", "content", "both")
MEMORY_SOURCES = ("manual", "pending-experience", "migrated", "breakdown")
CATEGORY_LABELS = {"preference": "写作偏好", "experience": "个人经历", "reference_copy": "爆款文案"}
SCOPE_LABELS = {"structure": "结构", "content": "内容", "both": "结构 + 内容"}

TITLE_LIMIT = 80
CONTENT_LIMIT = 4000
EVIDENCE_LIMIT = 2000
SUMMARY_LIMIT = 60
SCAN_FILE_LIMIT = 5000

DEFAULT_DIRECTORY_NAME = "memories"
FENCE = "---"
CONTENT_HEADING = "## 记忆内容"
EVIDENCE_HEADING = "## 来源依据"

_UNSAFE_SEGMENT = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_SKIPPED_DIRECTORIES = {".obsidian", ".trash", ".git", "node_modules"}


class MemoryStoreError(Exception):
    """带稳定错误码的记忆存储异常，便于接口层映射为具体提示。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def now_stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _one_line(value: Any) -> str:
    return " ".join(str(value or "").split())


def safe_segment(value: Any, *, fallback: str) -> str:
    """把账号、标题转成安全的路径片段；中文与常规字符保持原样。"""
    raw = _UNSAFE_SEGMENT.sub("-", str(value or "").strip())
    raw = re.sub(r"\s+", "-", raw)
    raw = raw.strip("-.").strip()
    raw = raw[:40].strip("-.")
    return raw or fallback


def derive_title(content: str, *, fallback: str = "未命名记忆") -> str:
    """从正文里取一段适合做标题的文字，只用于补全缺失的标题。"""
    first_line = next((line.strip() for line in str(content or "").splitlines() if line.strip()), "")
    first_line = first_line.lstrip("#-*> ").strip()
    return first_line[:TITLE_LIMIT] or fallback


def format_memory_file(memory: dict[str, Any]) -> str:
    """把一条记忆渲染成可读、可手工编辑的 Markdown 文件。"""
    metadata = [
        ("memoryFormat", memory.get("memoryFormat") or MEMORY_FORMAT_VERSION),
        ("id", memory.get("id")),
        ("accountId", memory.get("accountId")),
        ("title", memory.get("title")),
        ("category", memory.get("category")),
        ("scope", memory.get("scope")),
        ("enabled", "true" if memory.get("enabled", True) is not False else "false"),
        ("source", memory.get("source") or "manual"),
        ("sourceBreakdownId", memory.get("sourceBreakdownId") or ""),
        ("sourceUrl", memory.get("sourceUrl") or ""),
        ("createdAt", memory.get("createdAt")),
        ("updatedAt", memory.get("updatedAt")),
    ]
    lines = [FENCE]
    for key, value in metadata:
        lines.append(f"{key}: {_one_line(value)}")
    lines.append(FENCE)
    lines.append("")
    lines.append(CONTENT_HEADING)
    lines.append("")
    lines.append(str(memory.get("content") or "").strip())
    evidence = str(memory.get("evidence") or "").strip()
    if evidence:
        lines.append("")
        lines.append(EVIDENCE_HEADING)
        lines.append("")
        lines.append(evidence)
    return "\n".join(lines).rstrip("\n") + "\n"


def _read_metadata(raw: str) -> dict[str, str] | None:
    """读取开头的 ``---`` 围栏；没有围栏或围栏不闭合时返回 ``None``。"""
    lines = raw.splitlines()
    if not lines or lines[0].strip() != FENCE:
        return None
    metadata: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == FENCE:
            return metadata
        key, separator, value = line.partition(":")
        if not separator:
            continue
        metadata[key.strip()] = value.strip()
    return None


def _split_sections(raw: str) -> tuple[str, str]:
    lines = raw.splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line.strip() == FENCE)
        end = next(index for index, line in enumerate(lines[start + 1:], start + 1) if line.strip() == FENCE)
    except StopIteration:
        return raw.strip(), ""
    body = lines[end + 1:]
    content_lines: list[str] = []
    evidence_lines: list[str] = []
    target = content_lines
    for line in body:
        stripped = line.strip()
        if stripped == CONTENT_HEADING:
            target = content_lines
            continue
        if stripped == EVIDENCE_HEADING:
            target = evidence_lines
            continue
        target.append(line)
    if content_lines:
        return "\n".join(content_lines).strip(), "\n".join(evidence_lines).strip()
    # 没有小节标题时，整段正文按内容处理，便于手工写的记忆直接可用。
    return "\n".join(body).strip(), ""


def _parse_account(metadata: dict[str, str]) -> str:
    account = _one_line(metadata.get("accountId"))
    if account:
        return account
    raise MemoryStoreError("memory_account_missing", "记忆缺少归属账号（accountId）。")


def parse_memory_file(text: str) -> dict[str, Any] | None:
    """解析一个 MD 文件。

    返回 ``None`` 表示这不是受管记忆（例如仓库里其它笔记）；返回字典代表受管记忆，
    字段已做校验。元信息明显想写成记忆但内容不合法时抛 ``MemoryStoreError``。
    """
    raw = str(text or "").lstrip("\ufeff")
    metadata = _read_metadata(raw)
    content, evidence = _split_sections(raw)
    intended = (metadata is not None and "memoryFormat" in metadata) or CONTENT_HEADING in raw
    if not intended:
        return None
    if metadata is None:
        raise MemoryStoreError("memory_metadata_missing", "缺少文件开头的元信息区。")
    try:
        format_version = int(_one_line(metadata.get("memoryFormat")) or "")
    except ValueError:
        raise MemoryStoreError("memory_format_invalid", "memoryFormat 必须是整数。") from None
    if format_version != MEMORY_FORMAT_VERSION:
        raise MemoryStoreError("memory_format_unsupported", f"不支持的记忆格式版本：{format_version}。")
    memory_id = _one_line(metadata.get("id"))
    if not memory_id:
        raise MemoryStoreError("memory_id_missing", "记忆缺少稳定 ID。")
    account_id = _parse_account(metadata)
    category = _one_line(metadata.get("category")) or "preference"
    if category not in MEMORY_CATEGORIES:
        raise MemoryStoreError("memory_category_invalid", f"未知的记忆类别：{category}。")
    scope = _one_line(metadata.get("scope")) or ("content" if category in {"experience", "reference_copy"} else "both")
    if scope not in MEMORY_SCOPES:
        raise MemoryStoreError("memory_scope_invalid", f"未知的适用环节：{scope}。")
    if category in {"experience", "reference_copy"}:
        scope = "content"
    enabled_raw = _one_line(metadata.get("enabled")).lower()
    if enabled_raw not in {"true", "false", ""}:
        raise MemoryStoreError("memory_enabled_invalid", "enabled 只能是 true 或 false。")
    source = _one_line(metadata.get("source")) or "manual"
    if source not in MEMORY_SOURCES:
        source = "manual"
    title = _one_line(metadata.get("title"))[:TITLE_LIMIT]
    if not title:
        raise MemoryStoreError("memory_title_missing", "记忆缺少标题。")
    if not content:
        raise MemoryStoreError("memory_content_missing", "记忆缺少正文内容。")
    if category == "reference_copy" and len(content) > CONTENT_LIMIT:
        raise MemoryStoreError("memory_content_too_long", f"爆款文案最多 {CONTENT_LIMIT} 个字，内容未截断。")
    return {
        "memoryFormat": format_version,
        "id": memory_id,
        "accountId": account_id,
        "title": title,
        "category": category,
        "scope": scope,
        "enabled": enabled_raw != "false",
        "source": source,
        "sourceBreakdownId": _one_line(metadata.get("sourceBreakdownId")),
        "sourceUrl": _one_line(metadata.get("sourceUrl")),
        "createdAt": _one_line(metadata.get("createdAt")),
        "updatedAt": _one_line(metadata.get("updatedAt")),
        "content": content[:CONTENT_LIMIT],
        "evidence": evidence[:EVIDENCE_LIMIT],
    }


def _write_text(path: Path, text: str) -> None:
    """原子写入，避免 Obsidian 或工作台看到半份文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary_path.write_text(text, encoding="utf-8")
    temporary_path.replace(path)


class MemoryLibrary:
    """读写记忆目录：目录配置、记忆增改、按账号读取、迁移。"""

    def __init__(self, workspace_dir: Path, config_path: Path, *, reference_title_resolver: Callable[[str, str], str] | None = None) -> None:
        self.reference_title_resolver = reference_title_resolver
        self._workspace_dir = Path(workspace_dir)
        self._config_path = Path(config_path)
        self._layout_root: Path | None = None
        self._layout_warnings: list[dict[str, str]] = []

    # ---------------------------------------------------------------- 目录配置

    @property
    def default_directory(self) -> Path:
        return self._workspace_dir / DEFAULT_DIRECTORY_NAME

    def _read_config(self) -> dict[str, Any]:
        if not self._config_path.exists():
            return {}
        try:
            raw = json.loads(self._config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _write_config(self, config: dict[str, Any]) -> None:
        _write_text(self._config_path, json.dumps(config, ensure_ascii=False, indent=2) + "\n")

    def directory(self) -> Path:
        configured = _one_line(self._read_config().get("directory"))
        if not configured:
            return self.default_directory
        candidate = Path(configured).expanduser()
        if not candidate.is_absolute():
            candidate = self._workspace_dir / candidate
        return candidate

    def ensure_directory(self) -> Path:
        """默认目录不存在时按需建立；用户指定的目录只在保存时校验。"""
        directory = self.directory()
        if not directory.exists() and directory == self.default_directory:
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise MemoryStoreError("memory_directory_write_failed", "无法创建记忆根目录，请检查路径与权限。") from exc
        return directory

    def account_directory(self, account_id: str) -> Path:
        account = str(account_id).strip()
        if not account or safe_segment(account, fallback="") != account:
            raise MemoryStoreError("memory_account_invalid", "工作台 ID 无效。")
        custom = self._read_config().get("accountDirectories", {}).get(account)
        if custom:
            directory = Path(custom)
            if directory.is_symlink():
                raise MemoryStoreError("memory_directory_invalid", "工作台记忆目录不能是符号链接。")
            return directory
        directory = self.directory() / account
        if directory.is_symlink() or not directory.resolve().is_relative_to(self.directory().resolve()):
            raise MemoryStoreError("memory_directory_invalid", "工作台记忆目录不能链接到其他目录。")
        return directory

    def ensure_account_directory(self, account_id: str) -> Path:
        if self._read_config().get("accountDirectories", {}).get(account_id):
            directory = self.account_directory(account_id)
            error = self._directory_error(directory)
            if error:
                raise MemoryStoreError("memory_directory_unavailable", error)
            return directory
        root = self.ensure_directory()
        error = self._directory_error(root)
        if error:
            raise MemoryStoreError("memory_directory_unavailable", error)
        directory = self.account_directory(account_id)
        try:
            directory.mkdir(exist_ok=True)
        except OSError as exc:
            raise MemoryStoreError("memory_directory_write_failed", "无法创建工作台记忆目录，请检查路径与权限。") from exc
        error = self._directory_error(directory)
        if error:
            raise MemoryStoreError("memory_directory_unavailable", error)
        return directory

    def initialize_accounts(self, account_ids: Iterable[str]) -> None:
        """启动或切换根目录时归位旧文件；正常账号读取不扫描其他账号。"""
        root = self.ensure_directory()
        resolved = root.resolve()
        if self._layout_root == resolved:
            return
        owners = set(account_ids)
        for owner in owners:
            self.ensure_account_directory(owner)
        memories, problems = self.scan(include_duplicates=True)
        duplicate_ids = {key for key, count in Counter(item["id"] for item in memories).items() if count > 1}
        warnings = list(problems)
        for item in memories:
            source = root / item["path"]
            if item["id"] in duplicate_ids:
                continue
            if item["accountId"] not in owners:
                warnings.append({"file": item["path"], "reason": "归属工作台不存在，原文件已保留。"})
                continue
            if self._read_config().get("accountDirectories", {}).get(item["accountId"]):
                # A preserved original is a backup after an explicit account-directory switch.
                continue
            owner_dir = self.account_directory(item["accountId"])
            if source.is_relative_to(owner_dir):
                continue
            target = self._target_path(item["accountId"], item["title"], item["id"], item["category"])
            if target.exists():
                warnings.append({"file": item["path"], "reason": "目标文件已存在，原文件已保留，请手动处理冲突。"})
                continue
            try:
                source.rename(target)
            except OSError:
                warnings.append({"file": item["path"], "reason": "旧记忆归位失败，原文件已保留。"})
        self._layout_warnings = warnings
        self._layout_root = resolved

    def _scan_account(self, account_id: str) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        directory = self.ensure_account_directory(account_id)
        return memory_index.reconcile(self, directory, str(account_id))

    def _directory_error(self, directory: Path) -> str:
        if not directory.exists():
            return "目录不存在，请重新选择。"
        if not directory.is_dir():
            return "这个路径不是文件夹。"
        if not os.access(directory, os.W_OK):
            return "目录不可写，请检查系统权限。"
        return ""

    @staticmethod
    def _is_obsidian_vault(directory: Path) -> bool:
        return any((path / ".obsidian").is_dir() for path in (directory, *directory.parents))

    def settings_view(self, account_id: str = "") -> dict[str, Any]:
        directory = self.ensure_directory()
        error = self._directory_error(directory)
        view = {
            "directory": str(directory),
            "defaultDirectory": str(self.default_directory),
            "exists": directory.is_dir(),
            "writable": os.access(directory, os.W_OK) if directory.is_dir() else False,
            "isObsidian": self._is_obsidian_vault(directory) if directory.is_dir() else False,
            "error": error,
            "migrationWarnings": self._layout_warnings,
        }
        if account_id:
            account_dir = self.account_directory(account_id)
            try:
                self.ensure_account_directory(account_id)
                account_error = ""
            except MemoryStoreError as exc:
                account_error = exc.message
            view.update(accountId=account_id, accountDirectory=str(account_dir),
                        accountExists=account_dir.is_dir(), accountError=account_error)
        return view

    def _resolve_directory(self, directory: str) -> Path:
        value = _one_line(directory)
        if not value:
            raise MemoryStoreError("memory_directory_empty", "请先填写记忆文件夹路径。")
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = (self._workspace_dir / candidate).resolve()
        return candidate.resolve()

    def save_settings(self, directory: str, *, migrate: bool = True, account_ids: Iterable[str] = ()) -> dict[str, Any]:
        target = self._resolve_directory(directory)
        error = self._directory_error(target)
        if error:
            raise MemoryStoreError("memory_directory_invalid", error)
        current = self.directory().resolve()
        if target != current and (target.is_relative_to(current) or current.is_relative_to(target)):
            raise MemoryStoreError("memory_directory_invalid", "新旧记忆根目录不能相互包含，请选择独立目录。")
        migrated = 0
        # 项目搬家后旧路径可能已不存在；此时直接使用已校验的新目录，
        # 不再扫描旧目录，也不重新创建旧目录或覆盖目标里的记忆。
        if migrate and target != current and current.exists():
            result = self.migrate_to_directory(target)
            migrated = int(result["copied"])
        for owner in account_ids:
            child = target / self.account_directory(owner).name
            if child.is_symlink():
                raise MemoryStoreError("memory_directory_invalid", "目标工作台目录不能是符号链接。")
            child.mkdir(exist_ok=True)
        config = self._read_config()
        config["version"] = 1
        config["directory"] = str(target)
        self._write_config(config)
        view = self.settings_view()
        view["migrated"] = migrated
        return view

    def save_account_settings(self, account_id: str, directory: str, account_ids: Iterable[str]) -> dict[str, Any]:
        if Path(directory).expanduser().is_symlink():
            raise MemoryStoreError("memory_directory_invalid", "请选择实际文件夹，不使用符号链接。")
        target = self._resolve_directory(directory)
        error = self._directory_error(target)
        if error:
            raise MemoryStoreError("memory_directory_invalid", error)
        self._scan_account(account_id)
        source = self.account_directory(account_id).resolve()
        root = self.directory().resolve()
        if target == root or root.is_relative_to(target):
            raise MemoryStoreError("memory_directory_invalid", "请选择当前工作台的独立文件夹。")
        for owner in account_ids:
            if owner == account_id:
                continue
            for other in {self.account_directory(owner).resolve(), (root / owner).resolve()}:
                if target == other or target.is_relative_to(other) or other.is_relative_to(target):
                    raise MemoryStoreError("memory_directory_invalid", "不能使用其他工作台的目录或其父子目录。")
        if target != source and (target.is_relative_to(source) or source.is_relative_to(target)):
            raise MemoryStoreError("memory_directory_invalid", "新旧记忆目录不能相互包含。")
        existing, problems = self.scan(target)
        if problems or any(item["accountId"] != account_id for item in existing):
            raise MemoryStoreError("memory_directory_conflict", "目标目录包含其他工作台或无法识别的记忆，请选择独立目录。")
        migrated = 0
        if source.exists() and target != source:
            migrated = self.migrate_to_directory(target, source=source)["copied"]
        config = self._read_config()
        config.setdefault("accountDirectories", {})[account_id] = str(target)
        self._write_config(config)
        view = self.settings_view(account_id)
        view["migrated"] = migrated
        return view

    def mark_migrated(self, *, source: str) -> None:
        config = self._read_config()
        config["version"] = 1
        config.setdefault("directory", str(self.directory()))
        config["migratedAt"] = now_stamp()
        config["migratedFrom"] = source
        self._write_config(config)

    def migrated_at(self) -> str:
        return _one_line(self._read_config().get("migratedAt"))

    # ------------------------------------------------------------------ 文件扫描

    def _iter_files(self, root: Path) -> Iterable[Path]:
        count = 0
        for path in sorted(root.rglob("*.md")):
            if any(part in _SKIPPED_DIRECTORIES or part.startswith(".") for part in path.relative_to(root).parts[:-1]):
                continue
            if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root and parent.is_relative_to(root)):
                continue
            if path.name.startswith("."):
                continue
            count += 1
            if count > SCAN_FILE_LIMIT:
                break
            yield path

    def scan(self, root: Path | None = None, *, include_duplicates: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        """读取指定目录（默认当前生效目录），返回 ``(记忆列表, 无效文件列表)``。"""
        root = Path(root) if root is not None else self.ensure_directory()
        error = self._directory_error(root)
        if error:
            raise MemoryStoreError("memory_directory_unavailable", error)
        memories: list[dict[str, Any]] = []
        problems: list[dict[str, str]] = []
        seen: dict[str, Path] = {}
        for path in self._iter_files(root):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                problems.append({"file": self._relative(path, root), "reason": "文件无法读取。"})
                continue
            try:
                indexed = memory_index.indexed_file(path, root)
                if indexed and not (text.lstrip().startswith('---') and 'memoryFormat:' in text.split('---', 2)[1]):
                    parsed = dict(indexed, content=text.strip())
                else:
                    parsed = parse_memory_file(text)
            except MemoryStoreError as exc:
                problems.append({"file": self._relative(path, root), "reason": exc.message})
                continue
            if parsed is None:
                parsed = memory_index.indexed_file(path, root)
                if parsed is None:
                    continue
                parsed['content'] = text.strip()
            memory_id = parsed["id"]
            if memory_id in seen:
                problems.append({
                    "file": self._relative(path, root),
                    "reason": f"记忆 ID 与 {self._relative(seen[memory_id], root)} 重复。",
                })
                if not include_duplicates:
                    continue
            seen[memory_id] = path
            parsed["path"] = self._relative(path, root)
            parsed["summary"] = self._summary(parsed["content"])
            memories.append(parsed)
        return memories, problems

    def _relative(self, path: Path, root: Path | None = None) -> str:
        base = Path(root) if root is not None else self.directory()
        try:
            return str(path.relative_to(base))
        except ValueError:
            return path.name

    @staticmethod
    def _summary(content: str) -> str:
        text = _one_line(content)
        return text if len(text) <= SUMMARY_LIMIT else text[:SUMMARY_LIMIT] + "…"

    def _account_memories(self, account_id: str) -> list[dict[str, Any]]:
        memories, _problems = self._scan_account(account_id)
        return memories

    def list_memories(self, account_id: str) -> dict[str, Any]:
        try:
            memories, problems = self._scan_account(account_id)
        except MemoryStoreError as exc:
            return {
                "items": [],
                "errors": [{"file": "", "reason": exc.message}],
                "counts": {"total": 0, "enabled": 0},
                "directoryError": exc.message,
            }
        owned = [item for item in memories if item["accountId"] == str(account_id)]
        owned.sort(key=lambda item: (str(item.get("createdAt") or ""), item["title"]), reverse=True)
        return {
            "items": owned,
            "errors": problems,
            "counts": {"total": len(owned), "enabled": sum(1 for item in owned if item["enabled"])},
            "directoryError": "",
        }

    # ------------------------------------------------------------------ 记忆写入

    @staticmethod
    def _validate_fields(
        *,
        title: str,
        category: str,
        scope: str,
        content: str,
        evidence: str,
    ) -> dict[str, Any]:
        normalized_title = _one_line(title)
        if not normalized_title:
            raise MemoryStoreError("memory_title_empty", "请填写记忆标题。")
        if len(normalized_title) > TITLE_LIMIT:
            raise MemoryStoreError("memory_title_too_long", f"标题最多 {TITLE_LIMIT} 个字。")
        if category not in MEMORY_CATEGORIES:
            raise MemoryStoreError("memory_category_invalid", "请选择写作偏好、个人经历或爆款文案。")
        if category in {"experience", "reference_copy"}:
            normalized_scope = "content"
        else:
            normalized_scope = "both"
        normalized_content = str(content or "").strip()
        if not normalized_content:
            raise MemoryStoreError("memory_content_empty", "请填写记忆内容。")
        if len(normalized_content) > CONTENT_LIMIT:
            raise MemoryStoreError("memory_content_too_long", f"记忆内容最多 {CONTENT_LIMIT} 个字。")
        normalized_evidence = str(evidence or "").strip()
        if len(normalized_evidence) > EVIDENCE_LIMIT:
            raise MemoryStoreError("memory_evidence_too_long", f"来源依据最多 {EVIDENCE_LIMIT} 个字。")
        return {
            "title": normalized_title,
            "category": category,
            "scope": normalized_scope,
            "content": normalized_content,
            "evidence": normalized_evidence,
        }

    def _target_path(self, account_id: str, title: str, memory_id: str, category: str = "preference") -> Path:
        account_dir = memory_index.category_directory(self.account_directory(account_id), category)
        slug = safe_segment(title, fallback="memory")
        return account_dir / f"{slug}-{memory_id[:8]}.md"

    def _existing_duplicate(self, account_id: str, *, scope: str, content: str) -> dict[str, Any] | None:
        wanted = _one_line(content)
        for item in self._account_memories(account_id):
            if item["category"] == "preference" and _one_line(item["content"]) == wanted:
                return item
        return None

    def create_memory(
        self,
        account_id: str,
        *,
        title: str = "",
        category: str = "preference",
        scope: str = "content",
        content: str,
        evidence: str = "",
        source: str = "manual",
        enabled: bool = True,
        memory_id: str = "",
        created_at: str = "",
        dedupe: bool = False,
        sourceBreakdownId: str = "",
        sourceUrl: str = "",
    ) -> dict[str, Any]:
        account = _one_line(account_id)
        if not account:
            raise MemoryStoreError("memory_account_missing", "请先选择账号。")
        fields = self._validate_fields(
            title=title or derive_title(content),
            category=category,
            scope=scope,
            content=content,
            evidence=evidence,
        )
        normalized_source = source if source in MEMORY_SOURCES else "manual"
        if dedupe:
            existing = self._existing_duplicate(account, scope=fields["scope"], content=fields["content"])
            if existing is not None:
                return existing
        self.ensure_account_directory(account)
        stamp = now_stamp()
        memory = {
            "memoryFormat": MEMORY_FORMAT_VERSION,
            "id": memory_id or uuid.uuid4().hex,
            "accountId": account,
            "title": fields["title"],
            "category": fields["category"],
            "scope": fields["scope"],
            "enabled": enabled is not False,
            "source": normalized_source,
            "sourceBreakdownId": _one_line(sourceBreakdownId),
            "sourceUrl": _one_line(sourceUrl),
            "createdAt": created_at or stamp,
            "updatedAt": stamp,
            "content": fields["content"],
            "evidence": fields["evidence"],
        }
        path = self._target_path(account, memory["title"], memory["id"], memory["category"])
        _write_text(path, memory['content'] + "\n")
        memory_index.record(self.account_directory(account), path, memory)
        memory["path"] = self._relative(path)
        memory["summary"] = self._summary(memory["content"])
        return memory

    def _find(self, account_id: str, memory_id: str) -> tuple[dict[str, Any], Path]:
        wanted = _one_line(memory_id)
        if not wanted:
            raise MemoryStoreError("memory_not_found", "记忆不存在或已被删除。")
        for item in self._account_memories(account_id):
            if item["id"] == wanted:
                root = self.account_directory(account_id)
                relative = Path(item["path"]).relative_to(str(account_id))
                index, _ = memory_index.load(root, account_id)
                if str(relative) in index.get('pendingMoves', {}):
                    raise MemoryStoreError("memory_directory_write_failed", "此记忆的分类整理尚未完成，请处理目录权限或冲突后重试。")
                return item, root / relative
        raise MemoryStoreError("memory_not_found", "记忆不存在或已被删除。")

    def update_memory(self, account_id: str, memory_id: str, **fields: Any) -> dict[str, Any]:
        current, path = self._find(account_id, memory_id)
        merged = self._validate_fields(
            title=fields.get("title", current["title"]),
            category=fields.get("category", current["category"]),
            scope=fields.get("scope", current["scope"]),
            content=fields.get("content", current["content"]),
            evidence=fields.get("evidence", current["evidence"]),
        )
        enabled = current["enabled"]
        if "enabled" in fields and fields["enabled"] is not None:
            enabled = bool(fields["enabled"])
        memory = {
            "memoryFormat": MEMORY_FORMAT_VERSION,
            "id": current["id"],
            "accountId": current["accountId"],
            "source": current["source"],
            "sourceBreakdownId": current.get("sourceBreakdownId", ""),
            "sourceUrl": current.get("sourceUrl", ""),
            "createdAt": current["createdAt"] or now_stamp(),
            "updatedAt": now_stamp(),
            "enabled": enabled,
            **merged,
        }
        target = self._target_path(current["accountId"], memory["title"], memory["id"], memory["category"])
        if target != path and (target.exists() or target.is_symlink()):
            raise MemoryStoreError("memory_directory_conflict", "目标文件已存在，原记忆未修改。")
        _write_text(path, memory["content"] + "\n")
        memory_index.record(self.account_directory(account_id), path, memory)
        if target != path:
            root = self.account_directory(account_id)
            data, _ = memory_index.load(root, account_id)
            data.setdefault('pendingMoves', {})[str(path.relative_to(root))] = str(target.relative_to(root))
            memory_index.save(root, data)
            problems = memory_index.finish_moves(root, data)
            if problems:
                raise MemoryStoreError("memory_directory_write_failed", problems[0]['reason'])
            path = target
        memory["path"] = self._relative(path)
        memory["summary"] = self._summary(memory["content"])
        return memory

    def delete_memory(self, account_id: str, memory_id: str) -> dict[str, str]:
        _, path = self._find(account_id, memory_id)
        # Move to the ignored local trash so accidental deletion remains recoverable.
        trash = self.account_directory(account_id) / ".trash"
        trash.mkdir(exist_ok=True)
        path.replace(trash / f"{uuid.uuid4().hex}-{path.name}")
        return {"deletedMemoryId": memory_id}

    def set_enabled(self, account_id: str, memory_id: str, enabled: bool) -> dict[str, Any]:
        memory, path = self._find(account_id, memory_id)
        memory['enabled'] = bool(enabled)
        memory['updatedAt'] = now_stamp()
        memory_index.record(self.account_directory(account_id), path, memory)
        return memory

    # ------------------------------------------------------------------ 记忆读取

    def read_entries(
        self,
        account_id: str,
        *,
        scope: str,
        category: str = "preference",
    ) -> list[dict[str, Any]]:
        """写作偏好统一应用；旧 scope 仅为存储兼容字段。"""
        scopes = {scope, "both"} if scope in {"structure", "content"} else {scope}
        entries = [
            item
            for item in self._account_memories(account_id)
            if item["enabled"] and item["category"] == category and (category == "preference" or item["scope"] in scopes)
        ]
        entries.sort(key=lambda item: (str(item.get("createdAt") or ""), item["title"]))
        return [
            {
                "id": item["id"],
                "title": item["title"],
                "category": item["category"],
                "scope": item["scope"],
                "text": item["content"],
                "evidence": item["evidence"],
                "createdAt": item["createdAt"],
                "updatedAt": item["updatedAt"],
                "path": item["path"],
            }
            for item in entries
        ]

    def read_experiences(self, account_id: str, ids: Iterable[str], *, category: str = "experience") -> dict[str, Any]:
        """按用户勾选读取个人经历；停用或已删除的条目如实回报，不静默忽略。"""
        wanted = [str(item) for item in ids if str(item).strip()]
        if not wanted:
            return {"items": [], "missing": [], "disabled": []}
        indexed = {item["id"]: item for item in self._account_memories(account_id)}
        items: list[dict[str, Any]] = []
        missing: list[str] = []
        disabled: list[str] = []
        for memory_id in wanted:
            item = indexed.get(memory_id)
            if item is None or item["category"] != category:
                missing.append(memory_id)
                continue
            if not item["enabled"]:
                disabled.append(memory_id)
                continue
            items.append({
                "id": item["id"],
                "title": item["title"],
                "text": item["content"],
                "category": item["category"],
                "createdAt": item["createdAt"],
                "path": item["path"],
            })
        return {"items": items, "missing": missing, "disabled": disabled}

    # -------------------------------------------------------------------- 迁移

    def migrate_from_json(self, account_memory: dict[str, Any]) -> dict[str, int]:
        """把旧的 account-memory.json 内容保留为停用的参考文案 MD。

        旧 preferences 曾直接保存结构和全文，无法据此认定为写作规则。

        幂等：同一账号、同一环节、同一正文只生成一个文件；重复调用只会增加 skipped。
        """
        created = 0
        skipped = 0
        if not isinstance(account_memory, dict):
            return {"created": 0, "skipped": 0}
        for account_id, nodes in account_memory.items():
            if not isinstance(nodes, dict):
                continue
            for node in ("structure", "content"):
                node_memory = nodes.get(node)
                node_memory = node_memory if isinstance(node_memory, dict) else {}
                for entry in node_memory.get("preferences") or []:
                    raw_text = entry.get("text") if isinstance(entry, dict) else entry
                    content = str(raw_text or "").strip()
                    if not content:
                        continue
                    created_at = str(entry.get("createdAt") or "") if isinstance(entry, dict) else ""
                    if any(_one_line(item["content"]) == _one_line(content)
                           for item in self._account_memories(str(account_id))):
                        skipped += 1
                        continue
                    self.create_memory(
                        str(account_id),
                        title=derive_title(content),
                        category="reference_copy",
                        enabled=False,
                        scope=node,
                        content=content,
                        source="migrated",
                        created_at=created_at,
                        dedupe=True,
                    )
                    created += 1
        return {"created": created, "skipped": skipped}

    def migrate_to_directory(self, target: Path, *, source: Path | None = None) -> dict[str, Any]:
        """把当前目录里的记忆复制到新目录。

        目标已有同 ID 记忆时：内容一致就跳过，内容不同则报冲突并整体放弃，
        避免把用户正在使用的新目录改坏。
        """
        source = source if source is not None else self.directory()
        if source.resolve() == target.resolve():
            return {"copied": 0, "skipped": 0, "conflicts": []}
        memories, problems = self.scan(source)
        target_files: dict[str, Path] = {}
        if target.exists():
            existing, target_problems = self.scan(root=target)
            if target_problems:
                raise MemoryStoreError("memory_directory_conflict", "新目录中有无效或重复的记忆，请先处理后重试。")
            target_files = {item["id"]: target / item["path"] for item in existing}
        conflicts: list[dict[str, str]] = []
        copies: list[tuple[Path, Path]] = []
        skipped = 0
        for item in memories:
            source_path = source / item["path"]
            known = target_files.get(item["id"])
            if known is not None:
                try:
                    same = next(({k: v for k, v in entry.items() if k not in {"path", "summary"}} for entry in existing if entry["id"] == item["id"]), None)
                except (OSError, UnicodeDecodeError, MemoryStoreError):
                    same = None
                if same is not None and same == {key: value for key, value in item.items() if key not in {"path", "summary"}}:
                    skipped += 1
                    continue
                conflicts.append({"id": item["id"], "title": item["title"], "file": item["path"]})
                continue
            destination = target / item["path"]
            if destination.exists() or any(p.is_symlink() for p in destination.parents if p.is_relative_to(target)):
                conflicts.append({"id": item["id"], "title": item["title"], "file": item["path"]})
                continue
            copies.append((source_path, destination))
        # 无效文件也保留原文，不能因为无法解析就让换目录丢掉记忆。
        for problem in problems:
            source_path = source / problem["file"]
            destination = target / problem["file"]
            if destination.exists() or destination.is_symlink():
                conflicts.append({"id": "", "title": "", "file": problem["file"]})
                continue
            copies.append((source_path, destination))
        if conflicts:
            raise MemoryStoreError(
                "memory_directory_conflict",
                "新目录里已有同 ID 但内容不同的记忆，请先处理后重试。",
            )
        for source_dir in source.rglob("*"):
            relative = source_dir.relative_to(source)
            if source_dir.is_dir() and not any(p.is_symlink() for p in (source_dir, *source_dir.parents) if p.is_relative_to(source)) and not any(part.startswith(".") or part in _SKIPPED_DIRECTORIES for part in relative.parts):
                destination = target / relative
                if any(p.is_symlink() for p in (destination, *destination.parents) if p.is_relative_to(target)):
                    raise MemoryStoreError("memory_directory_conflict", "目标子目录为符号链接，无法复制。")
                destination.mkdir(parents=True, exist_ok=True)
        for source_path, target_path in copies:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            _write_text(target_path, source_path.read_text(encoding="utf-8"))
            if target_path.read_bytes() != source_path.read_bytes():
                raise MemoryStoreError("memory_directory_copy_failed", "记忆复制校验失败，原目录配置未改变。")
        for index_path in source.rglob(memory_index.INDEX):
            if any(part.startswith('.') for part in index_path.relative_to(source).parts[:-1]):
                continue
            if index_path.is_symlink():
                continue
            destination = target / index_path.parent.relative_to(source)
            incoming, _ = memory_index.load(index_path.parent)
            stored, _ = memory_index.load(destination, incoming['accountId'])
            stored['files'].update(incoming['files'])
            memory_index.save(destination, stored)
        return {"copied": len(copies), "skipped": skipped, "conflicts": []}
