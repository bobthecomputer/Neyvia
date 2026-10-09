# Product Requirements (MVP)

## Product name

Grant Agent Harness

## Problem

Long-running coding agent sessions lose coherence when context windows fill up. Users also struggle to trust autonomy because they cannot see what was done, why it was done, and how to safely continue.

## Goal

Ship a local-first orchestration engine that can run iterative coding loops, enforce docs-first planning policy, and automatically hand off to fresh sessions when context is near capacity.

## Non-goals (MVP)

- Full multi-agent scheduling.
- Cloud deployment and multi-tenant permissions.
- Rich GUI implementation (engine-first in this repo).

## Key user stories

- As a builder, I want the agent to read docs before coding so output follows real constraints.
- As a user, I want the agent to continue after context rollover without losing progress.
- As an operator, I want verification defaults and artifacts for replay/debugging.
- As a founder, I want feature suggestions from papers/notes so roadmap planning is faster.

## Functional requirements

- Persona-aware prompt stack assembly.
- Docs-first preflight policy checks.
- Doc ingestion evidence persisted per run.
- Context usage tracking with configurable thresholds.
- Automatic handoff packet generation and session lineage.
- Persistent memory storage and retrieval for cross-session continuity.
- Resume command that restarts from latest session context automatically.
- Runtime and handoff budget caps.
- Verification command execution with pass/fail trace.
- High-risk command blocking for safer autonomous runs.
- Workspace search and timeline replay for observability.
- Feature suggestion generation from pasted paper text.
- Artifact persistence: timeline, state, and handoff JSON files.

## Success metrics

- Handoff packet generated before hard-stop overflow.
- Zero missing required fields in handoff schema.
- Verification command success/failure clearly visible in state artifacts.
