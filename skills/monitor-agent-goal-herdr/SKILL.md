---
name: monitor-agent-goal-herdr
description: Independently inspect one registered Codex /goal through Herdr, compare its semantic progress with the goal and repository evidence, and report a notify-only finding to Agent Control Center. Use when asked to monitor, supervise, audit, or periodically check a Codex goal without taking over its work.
---

# Monitor Agent Goal Through Herdr

Run one evidence-backed inspection of an existing Control Center monitor. This skill is a supervisor, not another implementation agent.

## Input

Require the Control Center project ID and monitor ID. The API base defaults to `http://127.0.0.1:8765`; override it with `CONTROL_CENTER_API`. If Basic Auth is enabled, read `CONTROL_CENTER_USER` and `CONTROL_CENTER_PASSWORD` from the environment. Never print credentials.

## Hard boundaries

- Operate only when `HERDR_ENV=1`.
- Treat the registered project path, Herdr pane ID, and Codex goal session ID as an exact three-way identity. Do not guess or substitute another session.
- Stay read-only toward the target repository and Codex pane.
- Never run `herdr agent prompt`, inject keystrokes, edit files, run tests, start implementation subagents, change Git state, or alter the Codex transcript.
- Do not infer product progress from terminal activity, token use, file count, or passing tests alone.
- Never claim that a scheduled loop is active merely because a monitor record exists.
- Report secrets only as `[REDACTED]`; omit large transcript or diff bodies.
- Stop after one inspection. A caller may schedule repeated invocations, but each invocation remains independent.

## Inspection procedure

Resolve `scripts/monitor_client.py` relative to this `SKILL.md`, not relative to the target repository.

1. Run `python <skill-directory>/scripts/monitor_client.py monitor <project-id> <monitor-id>`. Stop if the monitor is absent, not `armed`, not `notify_only`, or its identity is ambiguous.
2. Run `python <skill-directory>/scripts/monitor_client.py snapshot <project-id> <monitor-id>`. The server performs exact session/path checks and returns bounded terminal, goal, and Git evidence.
3. Read only the minimum project guidance needed to interpret the goal: the nearest `AGENTS.md`, then named PRD/spec/checkpoint files if they exist. Do not crawl unrelated personal directories.
4. Judge semantic progress against the goal objective and explicit acceptance evidence. Look for forward progress tied to a deliverable, repeated attempts without new evidence, divergence, unsupported completion claims, decisions not derivable from existing rules, terminal goal states, and broken identity/access.
5. Choose exactly one verdict:
   - `clean`: progress is coherent and no intervention is needed.
   - `attention`: a risk or likely dead end exists, but no human decision is yet required.
   - `needs_human`: a concrete, consequential decision is required. This creates or reuses a Decision Card.
   - `terminal`: the goal is complete, blocked beyond useful monitoring, cancelled, or otherwise finished.
   - `error`: the evidence channel or exact identity is broken.
6. Write a compact JSON file containing `verdict`, `finding_type`, `summary`, `evidence`, `recommendation`, and `confidence`. Evidence must cite observable facts, not hidden reasoning. Report it with `python <skill-directory>/scripts/monitor_client.py report <project-id> <monitor-id> --file <json-file>`.
7. Delete the temporary JSON file. Return the verdict, strongest evidence, and Decision Card ID if one was created.

## Reporting quality

Use `needs_human` only for a question with a clear decision boundary. State what is blocked, why existing evidence cannot decide it, and what choice or information is needed. Prefer `attention` for ordinary implementation mistakes that the working agent can still correct itself.

For repeated runs, do not re-report an unchanged observation as new progress. Compare the latest monitor events, goal update time, Git head/status, and terminal evidence. If there is no material change, say so plainly.

## Scheduling

This skill performs one tick. In Claude Code, the user may wrap the command with `/loop` at the cadence registered in Control Center. If `/loop` is unavailable, report that scheduling is unavailable; do not pretend to have created a background monitor.
