# Codex Session Visibility Repair

English: A small Codex skill and helper script for repairing invisible local Codex sessions after switching login mode or model provider.

中文：一个用于修复 Codex 本地会话“仍在磁盘上但在 App 或 CLI 中不可见”问题的小型 skill 和辅助脚本，适用于切换登录方式或模型提供方之后的场景。

## Overview

English:
- Create a temporary probe session to detect the current active `model_provider`.
- Read the provider from local Codex metadata.
- Delete the temporary probe session artifacts.
- Find existing threads whose `model_provider` no longer matches the current login state.
- Back up affected metadata before writing.
- Rewrite `model_provider` in:
  - `~/.codex/state_5.sqlite`
  - each thread rollout's `session_meta`

中文：
- 通过创建一个临时 probe session 探测当前实际生效的 `model_provider`。
- 从本地 Codex 元数据中读取该 provider。
- 读取后立即删除这个临时 probe session 的痕迹。
- 找出那些 `model_provider` 与当前登录态不一致的旧线程。
- 在写入前自动备份受影响的元数据。
- 修改以下位置中的 `model_provider`：
  - `~/.codex/state_5.sqlite`
  - 每个线程 rollout 文件中的 `session_meta`

## Files

- `SKILL.md`: Codex skill entrypoint and usage notes / skill 入口和使用说明
- `scripts/migrate_session_visibility.py`: repair script / 修复脚本
- `agents/openai.yaml`: agent config used by the skill / skill 使用的 agent 配置

## Usage

Report only:

```bash
python3 session-visibility-repair/scripts/migrate_session_visibility.py --report-only
```

Apply the repair:

```bash
python3 session-visibility-repair/scripts/migrate_session_visibility.py
```

Optional filters:

```bash
python3 session-visibility-repair/scripts/migrate_session_visibility.py --workspace-root /path/to/workspace
python3 session-visibility-repair/scripts/migrate_session_visibility.py --thread-id <thread-id>
python3 session-visibility-repair/scripts/migrate_session_visibility.py --dry-run
python3 session-visibility-repair/scripts/migrate_session_visibility.py --target-provider openai
```

## Safety

English:
- Only Codex thread metadata and rollout headers are modified.
- Message content is not modified.
- Backups are created before changes are applied.

中文：
- 只修改 Codex 线程元数据和 rollout 头部信息。
- 不修改消息正文内容。
- 写入前会自动创建备份。

## Notes

English:
- This package is tied to the local Codex session format observed during development.
- If Codex changes its local metadata schema, the probe and migration logic may need updates.

中文：
- 这个工具依赖开发时观察到的 Codex 本地会话格式。
- 如果 Codex 后续修改了本地元数据结构，probe 和迁移逻辑可能需要同步更新。
