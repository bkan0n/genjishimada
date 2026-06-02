---
phase: 260530-mu5
plan: 01
subsystem: tooling
tags: [justfile, docker, local-dev]
requires: []
provides: [infra-up, infra-down, infra-logs just recipes]
affects: [justfile]
tech-stack:
  added: []
  patterns: ["just recipe wrapping docker compose -f docker-compose.local.yml"]
key-files:
  created: []
  modified: [justfile]
decisions: []
metrics:
  duration: 1min
  completed: 2026-05-30
---

# Quick Task 260530-mu5: Add just recipes for local infrastructure Summary

Added `infra-up`, `infra-down`, and `infra-logs` convenience `just` recipes wrapping `docker compose -f docker-compose.local.yml` so the local stack (postgres, rabbitmq, minio) can be managed with short task-runner targets instead of manually-typed compose commands.

## What Was Built

Three recipes appended to the `# Convenience` section of the repo-root `justfile`, after the `ci:` recipe and before the Documentation section:

- `infra-up` → `docker compose -f docker-compose.local.yml up -d`
- `infra-down` → `docker compose -f docker-compose.local.yml down`
- `infra-logs` → `docker compose -f docker-compose.local.yml logs -f`

Each has a descriptive comment line and a 4-space-indented body, matching existing recipe style. Uses the `docker compose` v2 plugin form consistent with CLAUDE.md.

## Verification

- `just --list` parses cleanly and lists all three new recipes (OK)
- `grep -c 'docker compose -f docker-compose.local.yml' justfile` returns 3

## Deviations from Plan

None - plan executed exactly as written.

## Commits

- d178334: feat(260530-mu5): add infra-up/down/logs just recipes for local stack

## Self-Check: PASSED

- FOUND: justfile (modified, recipes present)
- FOUND: d178334
