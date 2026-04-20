---
name: session-visibility-repair
description: Use when Codex sessions become invisible after switching login method or model provider and you need to repair local ~/.codex thread metadata so existing local sessions show up again.
---

# Session Visibility Repair

Use this skill when old local Codex sessions still exist under `~/.codex`, but the App or CLI stops listing them after a login or provider switch.

## What This Skill Does

- Inspects the local state DB and rollout files under `~/.codex`
- Probes the current login by creating a temporary Codex session, then reads its `model_provider`
- Cleans up the temporary probe session after reading its provider
- Finds threads whose `model_provider` no longer matches the inferred active provider
- Reports which threads are likely hidden from App or CLI lists because of that mismatch
- Backs up the affected DB and rollout files before any write
- Rewrites the thread `model_provider` in:
  - `state_5.sqlite`
  - each thread's rollout `session_meta`

## When To Use It

- Sessions are visible by `codex resume <id>` but hidden from App lists
- You switched between `auth_mode="chatgpt"` and API-key login
- The script probes the current login state instead of relying on a hardcoded provider mapping

## Workflow

1. Run a temporary probe session with `codex exec` and read the written `model_provider`.
2. Delete the probe session artifacts immediately after reading them.
3. Run the script with `--report-only` first when you want a visibility diagnosis.
4. Run the migration script in `scripts/migrate_session_visibility.py`. By default it probes the current provider and migrates all mismatched threads.
5. Restart Codex App and verify the sessions are visible again.

## Script

Use:

```bash
python3 session-visibility-repair/scripts/migrate_session_visibility.py
```

Useful options:

- Report only, no writes:

```bash
python3 session-visibility-repair/scripts/migrate_session_visibility.py --report-only
```

- Restrict to one workspace:

```bash
python3 session-visibility-repair/scripts/migrate_session_visibility.py --workspace-root /path/to/workspace
```

- Restrict to a single thread:

```bash
python3 session-visibility-repair/scripts/migrate_session_visibility.py --thread-id <thread-id>
```

- Preview only:

```bash
python3 session-visibility-repair/scripts/migrate_session_visibility.py --dry-run
```

- Override the detected provider only when needed:

```bash
python3 session-visibility-repair/scripts/migrate_session_visibility.py --target-provider openai
```

- The script now probes the active login state first. Use `--target-provider` only when you want to override the probe.

- Restrict to specific source providers only when needed:

```bash
python3 session-visibility-repair/scripts/migrate_session_visibility.py --source-provider openai --source-provider anthropic
```

## Safety

- Always back up before writing.
- Do not touch session message content except the first `session_meta.model_provider` field in the rollout file.
- Prefer the smallest migration scope that solves the visibility issue.
