#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4


@dataclass
class ThreadRecord:
    thread_id: str
    rollout_path: Path
    model_provider: str
    title: str
    cwd: str
    source: str


def read_thread_provider_by_id(state_db: Path, thread_id: str) -> str | None:
    conn = sqlite3.connect(state_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "select model_provider from threads where id = ?",
        (thread_id,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    provider = row["model_provider"] or None
    return str(provider) if provider else None


def read_auth_mode(auth_path: Path) -> str | None:
    if not auth_path.exists():
        return None
    try:
        data = json.loads(auth_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    auth_mode = data.get("auth_mode")
    return str(auth_mode) if auth_mode else None


def resolve_provider_from_auth_mode(auth_mode: str | None) -> str | None:
    if not auth_mode:
        return None
    if auth_mode == "chatgpt":
        return "openai"
    return "newapi"


def read_current_provider(config_path: Path) -> str | None:
    if not config_path.exists():
        return None
    for raw in config_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("model_provider"):
            continue
        _, _, value = line.partition("=")
        return value.strip().strip('"').strip("'")
    return None


def read_latest_thread_provider(state_db: Path, workspace_root: str | None) -> str | None:
    conn = sqlite3.connect(state_db)
    conn.row_factory = sqlite3.Row
    query = (
        "select model_provider "
        "from threads "
        "where coalesce(model_provider, '') <> ''"
    )
    params: list[str] = []
    if workspace_root:
        query += " and cwd = ?"
        params.append(workspace_root)
    query += (
        " order by coalesce(updated_at_ms, 0) desc, "
        "coalesce(created_at_ms, 0) desc limit 1"
    )
    row = conn.execute(query, params).fetchone()
    conn.close()
    if row is None:
        return None
    return row["model_provider"] or None


def read_latest_rollout_provider(state_db: Path, workspace_root: str | None) -> str | None:
    conn = sqlite3.connect(state_db)
    conn.row_factory = sqlite3.Row
    query = (
        "select rollout_path "
        "from threads "
        "where rollout_path is not null"
    )
    params: list[str] = []
    if workspace_root:
        query += " and cwd = ?"
        params.append(workspace_root)
    query += (
        " order by coalesce(updated_at_ms, 0) desc, "
        "coalesce(created_at_ms, 0) desc limit 1"
    )
    row = conn.execute(query, params).fetchone()
    conn.close()
    if row is None:
        return None
    rollout_path = Path(row["rollout_path"])
    if not rollout_path.exists():
        return None
    for raw in rollout_path.read_text(encoding="utf-8").splitlines():
        obj = json.loads(raw)
        payload = obj.get("payload") if isinstance(obj, dict) else None
        if obj.get("type") == "session_meta" and isinstance(payload, dict):
            provider = payload.get("model_provider")
            if provider:
                return str(provider)
            break
    return None


def cleanup_probe_artifacts(
    *,
    codex_home: Path,
    state_db: Path,
    thread_id: str,
) -> None:
    conn = sqlite3.connect(state_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "select rollout_path from threads where id = ?",
        (thread_id,),
    ).fetchone()
    rollout_path = Path(row["rollout_path"]) if row and row["rollout_path"] else None
    conn.execute("delete from threads where id = ?", (thread_id,))
    conn.commit()
    conn.close()

    if rollout_path and rollout_path.exists():
        rollout_path.unlink()

    session_index_path = codex_home / "session_index.jsonl"
    if session_index_path.exists():
        filtered: list[str] = []
        for raw in session_index_path.read_text(encoding="utf-8").splitlines():
            if thread_id not in raw:
                filtered.append(raw)
        session_index_path.write_text("\n".join(filtered) + ("\n" if filtered else ""), encoding="utf-8")

    global_state_path = codex_home / ".codex-global-state.json"
    if global_state_path.exists():
        try:
            global_state = json.loads(global_state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        if isinstance(global_state, dict):
            projectless_thread_ids = global_state.get("projectless-thread-ids")
            if isinstance(projectless_thread_ids, list):
                global_state["projectless-thread-ids"] = [
                    item for item in projectless_thread_ids if item != thread_id
                ]
            hints = global_state.get("thread-workspace-root-hints")
            if isinstance(hints, dict):
                hints.pop(thread_id, None)
            global_state_path.write_text(
                json.dumps(global_state, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )


def probe_current_provider(
    *,
    codex_home: Path,
    state_db: Path,
    workspace_root: str | None,
) -> str | None:
    probe_token = f"PROBE_PROVIDER_{uuid4().hex}"
    cmd = [
        "codex",
        "exec",
        "--json",
        "--skip-git-repo-check",
    ]
    if workspace_root:
        cmd.extend(["-C", workspace_root])
    cmd.append(f"Reply with exactly {probe_token} and nothing else.")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return None

    thread_id: str | None = None
    for line in proc.stdout.splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == "thread.started":
            maybe_thread_id = obj.get("thread_id")
            if maybe_thread_id:
                thread_id = str(maybe_thread_id)
                break
    if not thread_id:
        return None

    provider = read_thread_provider_by_id(state_db, thread_id)
    cleanup_probe_artifacts(codex_home=codex_home, state_db=state_db, thread_id=thread_id)
    return provider


def detect_target_provider(
    *,
    explicit_provider: str | None,
    codex_home: Path,
    auth_path: Path,
    state_db: Path,
    config_path: Path,
    workspace_root: str | None,
) -> tuple[str | None, str]:
    if explicit_provider:
        return explicit_provider, "cli"
    probed_provider = probe_current_provider(
        codex_home=codex_home,
        state_db=state_db,
        workspace_root=workspace_root,
    )
    if probed_provider:
        return probed_provider, "probe-session"
    auth_mode = read_auth_mode(auth_path)
    auth_provider = resolve_provider_from_auth_mode(auth_mode)
    if auth_provider:
        return auth_provider, f"auth-mode:{auth_mode}"
    latest_thread_provider = read_latest_thread_provider(state_db, workspace_root)
    if latest_thread_provider:
        return latest_thread_provider, "latest-thread"
    config_provider = read_current_provider(config_path)
    if config_provider:
        return config_provider, "config"
    latest_rollout_provider = read_latest_rollout_provider(state_db, workspace_root)
    if latest_rollout_provider:
        return latest_rollout_provider, "latest-rollout"
    return None, "unknown"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Repair Codex local session visibility after switching login/provider by "
            "migrating old thread metadata to the current model provider."
        )
    )
    parser.add_argument(
        "--codex-home",
        default=str(Path.home() / ".codex"),
        help="Path to Codex home directory. Defaults to ~/.codex.",
    )
    parser.add_argument(
        "--target-provider",
        help=(
            "Provider name that current Codex login/config uses, such as openai or newapi. "
            "If omitted, infer it from ~/.codex/auth.json auth_mode first."
        ),
    )
    parser.add_argument(
        "--source-provider",
        action="append",
        default=[],
        help=(
            "Only inspect threads currently using one of these providers. "
            "If omitted, inspect every thread whose provider differs from the current provider."
        ),
    )
    parser.add_argument(
        "--workspace-root",
        help="Only migrate threads belonging to this workspace root.",
    )
    parser.add_argument(
        "--thread-id",
        action="append",
        default=[],
        help="Restrict migration to one or more specific thread ids.",
    )
    parser.add_argument(
        "--backup-dir",
        help="Directory to store backups. Defaults to ./backups/<timestamp>.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing anything.",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Print a visibility report and recommendations without preparing backups or writing files.",
    )
    return parser.parse_args()


def load_threads(
    *,
    state_db: Path,
    target_provider: str,
    source_providers: set[str],
    workspace_root: str | None,
    thread_ids: set[str],
) -> list[ThreadRecord]:
    conn = sqlite3.connect(state_db)
    conn.row_factory = sqlite3.Row
    query = (
        "select id, rollout_path, model_provider, title, cwd, source "
        "from threads"
    )
    rows = conn.execute(query).fetchall()
    conn.close()

    results: list[ThreadRecord] = []
    for row in rows:
        thread_id = row["id"]
        cwd = row["cwd"] or ""
        model_provider = row["model_provider"] or ""
        if workspace_root and cwd != workspace_root:
            continue
        if thread_ids and thread_id not in thread_ids:
            continue
        if source_providers:
            if model_provider not in source_providers:
                continue
        elif model_provider == target_provider:
            continue
        rollout_path = Path(row["rollout_path"])
        results.append(
            ThreadRecord(
                thread_id=thread_id,
                rollout_path=rollout_path,
                model_provider=model_provider,
                title=row["title"] or "",
                cwd=cwd,
                source=row["source"] or "",
            )
        )
    return results


def ensure_backup_dir(path_arg: str | None) -> Path:
    if path_arg:
        backup_dir = Path(path_arg)
    else:
        backup_dir = Path.cwd() / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def backup_file(src: Path, backup_dir: Path) -> None:
    if src.exists():
        shutil.copy2(src, backup_dir / src.name)


def rewrite_rollout_provider(rollout_path: Path, thread_id: str, target_provider: str) -> int:
    lines: list[str] = []
    replaced = 0
    for raw in rollout_path.read_text(encoding="utf-8").splitlines():
        obj = json.loads(raw)
        payload = obj.get("payload") if isinstance(obj, dict) else None
        if obj.get("type") == "session_meta" and isinstance(payload, dict) and payload.get("id") == thread_id:
            if payload.get("model_provider") != target_provider:
                payload["model_provider"] = target_provider
                replaced += 1
        lines.append(json.dumps(obj, ensure_ascii=False))
    rollout_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return replaced


def print_report(
    *,
    threads: list[ThreadRecord],
    target_provider: str,
    target_provider_source: str,
    report_only: bool,
) -> None:
    print(f"Target provider: {target_provider}")
    print(f"Target provider source: {target_provider_source}")
    print(f"Mismatched threads: {len(threads)}")
    if not threads:
        print("No visibility mismatches found.")
        return
    providers = sorted({item.model_provider for item in threads if item.model_provider})
    if providers:
        print(f"Detected source providers: {', '.join(providers)}")
    for item in threads:
        print(
            f"- {item.thread_id} | provider={item.model_provider} | source={item.source} | "
            f"title={item.title or '(untitled)'}"
        )
        print(f"  cwd={item.cwd}")
    if report_only:
        print("Report only. No files were modified.")


def main() -> int:
    args = parse_args()
    codex_home = Path(args.codex_home).expanduser()
    auth_path = codex_home / "auth.json"
    state_db = codex_home / "state_5.sqlite"
    config_path = codex_home / "config.toml"
    if not state_db.exists():
        raise SystemExit(f"state db not found: {state_db}")
    workspace_root = args.workspace_root
    target_provider, target_provider_source = detect_target_provider(
        explicit_provider=args.target_provider,
        codex_home=codex_home,
        auth_path=auth_path,
        state_db=state_db,
        config_path=config_path,
        workspace_root=workspace_root,
    )
    if not target_provider:
        raise SystemExit(
            "Could not determine target provider. Pass --target-provider explicitly "
            "or create a new local session so the script can infer it from the latest thread."
        )

    threads = load_threads(
        state_db=state_db,
        target_provider=target_provider,
        source_providers=set(args.source_provider),
        workspace_root=workspace_root,
        thread_ids=set(args.thread_id),
    )
    if not threads:
        print(f"Target provider: {target_provider}")
        print(f"Target provider source: {target_provider_source}")
        print("No matching threads found.")
        return 0
    if args.report_only:
        print_report(
            threads=threads,
            target_provider=target_provider,
            target_provider_source=target_provider_source,
            report_only=True,
        )
        return 0

    backup_dir = ensure_backup_dir(args.backup_dir)
    print(f"Backup dir: {backup_dir}")
    print_report(
        threads=threads,
        target_provider=target_provider,
        target_provider_source=target_provider_source,
        report_only=False,
    )

    if args.dry_run:
        print("Dry run only. No files were modified.")
        return 0

    backup_file(state_db, backup_dir)
    backup_file(codex_home / "state_5.sqlite-shm", backup_dir)
    backup_file(codex_home / "state_5.sqlite-wal", backup_dir)

    conn = sqlite3.connect(state_db)
    for item in threads:
        backup_file(item.rollout_path, backup_dir)
        replaced = 0
        if item.rollout_path.exists():
            replaced = rewrite_rollout_provider(item.rollout_path, item.thread_id, target_provider)
        conn.execute(
            "update threads set model_provider = ? where id = ?",
            (target_provider, item.thread_id),
        )
        print(
            f"Migrated {item.thread_id}: db model_provider -> {target_provider}, "
            f"rollout updates = {replaced}"
        )
    conn.commit()
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
