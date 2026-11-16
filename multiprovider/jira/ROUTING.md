# Jira routing configuration - rollout contract

## Recommended current MVP: exactly one routing label
- `engine-claude`
- `engine-cursor`
- `engine-opencode`

These labels are mutually exclusive. A Ready issue must have EXACTLY ONE; unlabeled or multi-labeled issues must be skipped by EVERY engine. Do not preserve the single-provider default after enabling routing.

Keep `agent-ready` in addition to the routing label; neither label overrides `Ready` status, repo match, detailed design, or blocker gate.

For every unfinished blocker require `agent-ready` and exactly one of `engine-claude`, `engine-cursor`, `engine-opencode`, regardless of the child provider. Verify a unique open PR in the same repository, with a same-repo head, exact `Factory Jira: <KEY>` and `Factory Engine: <provider>` lines. For an older PR without the Jira marker, verify any engine marker agrees with Jira and require both the canonical Jira issue URL and the exact key in the branch name. Fetch the published branch and verify its full head SHA. An in-progress or review-stage agent task with this evidence can be used immediately, including in Human Review. An unfinished human task always blocks.

Use fresh `origin/master` when all blockers are Done/Finalizada or there are none. Otherwise choose a verified parent PR head containing every unfinished parent's pinned SHA (prove Git ancestry). If their heads diverge, leave the child Ready and report the separate PRs. Create the child's own branch and isolated worktree at that SHA. Open the child Draft PR **against that parent branch**. Record each parent key, PR URL, branch and pinned SHA in the child PR and Jira summary, with the parent-first review order. Review only the child diff. Recheck the plan before claim and dispatch. Report later base changes for human coordination; never write to a parent's branch or worktree.

A future Jira single-select field `Implementation Engine` can replace the engine label if and only if ALL providers switch over atomically; don't silently mix rules. Prefer labels for the first rollout to avoid configuration friction.

Sample candidate JQLs (substitute real project key):

```jql
project = APP AND status = "Ready" AND labels = "agent-ready" AND labels = "engine-claude" ORDER BY Rank ASC
```
```jql
project = APP AND status = "Ready" AND labels = "agent-ready" AND labels = "engine-cursor" ORDER BY Rank ASC
```
```jql
project = APP AND status = "Ready" AND labels = "agent-ready" AND labels = "engine-opencode" ORDER BY Rank ASC
```

JQL is the INITIAL filter only. Fetch all labels and issues for the exact repo; reject another engine label even if the JQL matched. For each blocker verify its Done status or its published agent PR base against current Jira and GitHub detail, twice.

Issue template:

```text
Repository: OWNER/REPO
Dependencies: None | PROJ-123, PROJ-125
Design approved: Yes (by human)
Technical design: ...
Acceptance criteria: ...
Testing: ...
```

Before switching on multiprovider:
1. Add engine-claude to ALL remaining Claude-eligible Ready issues you want Claude to pick up.
2. Deploy strict routing prompt in existing Claude Routine. Verify one NO_WORK for an unlabeled issue and one eligible labeled test issue, without letting an unintended task run.
3. Only then label an issue engine-cursor or engine-opencode and activate that provider's own run.
4. Use separate non-overlapping run schedules per engine+repo. Jira In Progress is not an atomic lock.
5. Keep Jira Done manual after merge. An agent dependency can supply a verified PR base while the parent PR is still open.
