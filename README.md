# Session Visibility Repair

This package contains a small Codex skill and helper script for repairing invisible local Codex sessions after switching login mode or provider.

## What it does

- Probes the current login state by creating a temporary Codex session.
- Reads the probe session's `model_provider` from local Codex metadata.
- Deletes the temporary probe session artifacts.
- Finds existing local threads whose `model_provider` no longer matches the current login state.
- Backs up the affected metadata before writing.
- Rewrites `model_provider` in:
  - `~/.codex/state_5.sqlite`
  - each thread's rollout `session_meta`

## Files

- `SKILL.md`: the Codex skill entrypoint and usage notes.
- `scripts/migrate_session_visibility.py`: the repair script.
- `agents/openai.yaml`: the agent config used by the skill.

## Usage

From a terminal:

```bash
python3 session-visibility-repair/scripts/migrate_session_visibility.py --report-only
```

To apply the repair:

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

- The script only touches Codex thread metadata and rollout headers.
- It does not modify message content.
- It creates backups before making changes.

## Notes

- This package is tied to the local Codex session format observed on this machine.
- If your Codex installation changes its local metadata schema, the probe and migration logic may need updates.
