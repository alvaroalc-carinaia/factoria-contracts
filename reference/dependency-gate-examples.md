# Jira dependency gate -- expected behavior

This page is a **review fixture**, not executable code. The orchestrator decides by reading the actual Jira issue links and current linked issue statuses via Jira MCP.

| Candidate | Jira link(s) / dependency declaration | Live blocker statuses | Select? |
|---|---|---|---|
| PROJ-100 | `Dependencies: None` + empty inspected issue links | -- | YES |
| PROJ-101 | `is blocked by PROJ-80` | PROJ-80 = Done | YES |
| PROJ-102 | `is blocked by PROJ-80, PROJ-81` | PROJ-80 = Done; PROJ-81 = Human Review | Only from a verified open agent PR when implementation has started |
| PROJ-103 | `depends on PROJ-82` | PROJ-82 = Resolved | **NO** |
| PROJ-104 | `is blocked by PROJ-83` | PROJ-83 = Done category, status = Cancelled | **NO** |
| PROJ-105 | `is blocked by PROJ-84` | Lookup returns missing status | **NO** |
| PROJ-106 | `blocks PROJ-85` (outward link on candidate) | PROJ-85 = Ready | YES, if no other blockers |
| PROJ-107 | `relates to PROJ-86` | PROJ-86 = Ready | YES, if no other blockers |
| PROJ-108 | `depends on PROJ-109` (same batch) | PROJ-109 = Ready | Wait for the routed agent to publish its PR while there is spare capacity |
| PROJ-110 | custom link type with ambiguous direction | unknown | **NO** |

## Example with Jira link JSON

```json
{
  "key": "PROJ-102",
  "fields": {
    "status": { "name": "Ready" },
    "issuelinks": [
      {"type":{"name":"Blocks","inward":"is blocked by","outward":"blocks"},"inwardIssue":{"key":"PROJ-80"}},
      {"type":{"name":"Blocks","inward":"is blocked by","outward":"blocks"},"inwardIssue":{"key":"PROJ-81"}}
    ]
  }
}
```

Re-fetch each prerequisite by key. PROJ-102 can start in Human Review only from a verified agent PR for PROJ-81. A human task or missing PR evidence keeps PROJ-102 in Ready.

## Two-pass gate

1. Search candidate and verify all blockers are Done or included in the selected agent PR head.
2. Immediately before transitioning candidate to `In Progress`, re-fetch and re-verify all blockers and candidate Ready status. If the selected base or dependency evidence no longer verifies, skip and report, even if it passed in the initial scan.

## AGENTS.md update scope

The parent Opus may edit a **pre-existing** root or nested AGENTS.md in the assigned feature's own worktree when the feature legitimately changes durable repository instructions. Publish in the same feature Draft PR before the independent review. **Sonnet and pr-reviewer remain read-only for instruction files.** The human can reject the documentation change during PR review; no automatic merge occurs.
