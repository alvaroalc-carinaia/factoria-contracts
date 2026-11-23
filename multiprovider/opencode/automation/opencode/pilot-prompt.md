MANUAL SINGLE-ISSUE PILOT. You MUST be the named `factory-orchestrator` agent.
Process EXACTLY Jira key __ISSUE_KEY__ in repository __GITHUB_REPOSITORY__
(given by the human or selected deterministically by the runner; never pick another).
This invocation is exactly one issue. The workflow may start up to 3 such
invocations in parallel; do not pick or refill another issue.

Use the loaded factory-orchestrator agent contract. Read the issue worktree's
root and applicable nested AGENTS.md for project conventions. The runner
has independently validated the issue and created the feature branch.
Independently recheck Jira approved spec, agent-ready, engine-opencode, repo,
Ready status, links and live statuses. A human prerequisite requires Done/Finalizada. For an unfinished agent prerequisite, verify the parent PR(s), branch and head in the runner's pinned plan.
A story that declares no
Repository/Repositorio targets __GITHUB_REPOSITORY__; one naming another repo is ineligible.
For PB, verify status 10015 (Tareas por hacer), an active sprint on board 6,
agent-ready and only engine-opencode immediately before claim. Claim En curso
(10016) and stay there during automated review and corrections. For every
Human Review handoff below, use CODE REVIEW (10048) and verify the result.
**Localized status names outside PB:** Jira may return translated `status.name` values depending on the account language. Treat `Ready` and `Listo` as the same status, and `Done` and `Finalizada` as the same status, in every check of this contract (candidate selection, dependency gate and re-checks). Any other name is not `Ready`/`Done`.
Start from the runner's pinned base commit (fresh origin/master or a verified parent PR head). Confirm the current HEAD and recheck each parent before claim.

Delegate source/test editing to feature-builder (DeepSeek V4.1 Flash) ONE TIME
for the initial implementation.
Give it relevant files, approved spec and instructions to EDIT within 10 steps.
Never launch a fresh replacement builder if the first produces no diff.
Corrections, if any, resume that same session; they are not a second builder.
The external guard will stop the run if there is no source/test edit within
its initial deadline, or at the absolute timeout. Do not work around it.

Publish ONE Draft PR against the recorded base branch, listing parent keys, PR URLs and pinned heads in review order, then obtain an independent published-diff pr-reviewer
(Kimi K3.1 Pro) verdict. Review budget, authoritative in
automation/opencode/review_budget.py: MAX_CORRECTIONS=3, MAX_RE_REVIEWS=3,
MAX_TOTAL_REVIEWS=4. The initial review is review 1 and is not a correction
or a re-review. On CHANGES_REQUESTED, resume the SAME builder session for the
next correction when corrections already done are still below 3 and re-reviews
already done are still below 3, then launch one fresh re-review for that cycle.
PASS on the initial review or on re-review 1, 2 or 3 (reviews 1 through 4)
with the current head and real passing tests goes to Human Review. If the re-review
after the 3rd correction is still CHANGES_REQUESTED, BLOCKED: do not start a
4th correction or a 5th review. Do not apply a cap of 1 re-review or of 3
total reviews. `decidir_tras_review` only classifies that verdict; it does not
launch the builder or the reviewer.
On PASS at current head with real passing tests,
comment with EXACT literal markers on the PR:
Factory Review: PASS
Factory Review Head: <CURRENT PR HEAD SHA>
Factory Reviewer: pr-reviewer
Then move Jira to Human Review. Otherwise leave AI Review or Blocked with
truthful reasons and no fabricated PASS. No merges/deploys.

No extra features, no extra subagent types, and no batch refills. Do not
re-run a failed or no-progress session. Budgeted same-session corrections and
their fresh re-reviews stay inside MAX_CORRECTIONS=3, MAX_RE_REVIEWS=3 and
MAX_TOTAL_REVIEWS=4 (`automation/opencode/review_budget.py`). The workflow may
still run up to 3 of these single-issue invocations in parallel.
