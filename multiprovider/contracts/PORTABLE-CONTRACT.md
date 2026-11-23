# Shared execution contract - Agentic Factory / v1

This is a semantic contract, not a claim that all vendors expose identical tools.
The human owns product architecture, issue approval, conflict resolution, and merges.

## Sources of truth
- Jira: approved functional/technical design, acceptance criteria, dependencies, target `owner/repo`, Rank, engine assignment, state.
- GitHub: code, branches, published PR diffs, tests/CI, merge state.
- Repository: root and applicable nested AGENTS.md, existing CLAUDE.md when relevant. Do not overwrite repository policies.

**Product Board (project PB, board 6).** Use these board-specific rules for all workflow steps when running against PB.

- For `Ready/Listo`, query `project = PB AND sprint in openSprints() AND status = 10015 AND labels = "agent-ready" AND labels = "engine-<provider>" ORDER BY Rank ASC`. Substitute the configured provider in the query. For ranked and explicitly requested keys, verify the full issue has status 10015 (`Tareas por hacer`), an active sprint belonging to board 6 (Sprint field `customfield_10020`), `agent-ready` and exactly one supported engine label matching this runner. Repeat these checks immediately before claim. Apply the same sprint and routing checks when deciding whether a pending To Do prerequisite can be picked up by its own provider.
- Claim by transitioning to `En curso` (10016). The AI review and correction steps run while Jira stays in that state. At the Human Review handoff, transition to `CODE REVIEW` (10048) once the published Draft PR head has an independent PASS and passing checks. Select the available transition by its destination status, then read back the issue. `Blocked` is 10147 and `Finalizada` is 10017.

## Mandatory eligibility before any work
1. Work only in the environment's EXACT selected GitHub `owner/repo` and configured Jira board/project.
2. Search `Ready` + `agent-ready`, ordered `Rank ASC`. Read entire candidate details, not only search excerpts.
3. Require EXACTLY ONE routing label from `engine-claude`, `engine-cursor`, `engine-opencode`, `engine-openai`; its value MUST match this runner. Missing, conflicting, or unreadable labels -> SKIP. Other labels do not count.
4. Require human-approved detailed technical spec, verifiable acceptance criteria, explicit correct target repo, no missing architecture decisions, no active execution and no open PR for the same Jira key.
5. Enumerate all blocking dependencies via structured Jira links, dependency fields, and explicit textual blockers. Interpret link directions correctly: `A blocks B` does NOT mean B blocks A. Ambiguous semantics -> SKIP.
6. Fetch each blocker by key. Done/Finalizada satisfies that prerequisite. For every unfinished blocker require `agent-ready` and exactly one of `engine-claude`, `engine-cursor`, `engine-opencode`, `engine-openai`, regardless of the child provider. Verify a unique open PR in the same repository, with a same-repo head, exact `Factory Jira: <KEY>` and `Factory Engine: <provider>` lines. For an older PR without the Jira marker, verify any engine marker agrees with Jira and require both the canonical Jira issue URL and the exact key in the branch name. Fetch the published branch and verify its full head SHA. An in-progress or review-stage agent task with this evidence can be used immediately, including in Human Review. An unfinished human task always blocks.
   - **Localized status names outside PB:** Jira may return translated `status.name` values depending on the account language. Treat `Ready` and `Listo` as the same status, and `Done` and `Finalizada` as the same status, in every check of this contract (candidate selection, dependency gate and re-checks). Any other name is not `Ready`/`Done`.
7. Recheck the candidate's status, its route label and EVERY blocker immediately before transition to `In Progress`. Do not dispatch if a gate fails. Document skip; do not move skipped issues to Blocked.
8. One non-overlapping run per engine/repo; Jira status alone is not an atomic lease. Do not launch overlapping schedules for same engine/repo. Two engines cannot own the same issue when routing is exclusive.

## Workflow
- Claim eligible issue -> In Progress with verified transition and run identification.
- Implement only the original approved design, scoped to the target repo, in a dedicated branch/worktree or provider-isolated checkout. Multiple features may edit the same files in separate workspaces; Git integration conflicts belong to the human.
- Use fresh `origin/master` when all blockers are Done/Finalizada or there are none. Otherwise choose a verified parent PR head containing every unfinished parent's pinned SHA (prove Git ancestry). If their heads diverge, leave the child Ready and report the separate PRs. Create the child's own branch and isolated worktree at that SHA. Open the child Draft PR **against that parent branch**. Record each parent key, PR URL, branch and pinned SHA in the child PR and Jira summary, with the parent-first review order. Review only the child diff. Recheck the plan before claim and dispatch. Report later base changes for human coordination; never write to a parent's branch or worktree.
- Execute feasible prescribed tests, recording actual commands, exit codes and unrun checks. Never invent PASS.
- Parent orchestration agent MAY update EXISTING AGENTS.md files inside the feature branch when objectively necessary for durable, accurate project instructions. Record why and have changes reviewed. Do not invent new architecture/policies; do not modify main directly. Feature builders and reviewers do not edit instruction files.
- Publish one independent DRAFT PR against the recorded base branch. PR includes exact `Factory Engine: <claude|cursor|opencode|openai>` and `Factory Jira: <KEY>` lines, Jira issue URL, test evidence, acceptance mapping, documented AGENTS.md changes and human-review requirement.
- Independent review must read the real published PR diff and original Jira spec, including changes to AGENTS.md. If tool support cannot provide an independent reviewer, state this gap; never call self-review independent.
- Review failures -> corrections in the SAME branch/PR, within configured max 3 rounds; new independent review each round when available. `AI Review` during review; `Human Review` only after a real published PR, verified checks and reviewer PASS.
- OpenCode Go effective budget (`automation/opencode/review_budget.py`): MAX_CORRECTIONS=3 corrections after `CHANGES_REQUESTED`, MAX_RE_REVIEWS=3 re-reviews besides the initial review, MAX_TOTAL_REVIEWS=4. The OpenCode section below is the rule that engine follows. Cursor keeps the correction sentence in its own addendum. Claude keeps the shared correction-round baseline above.
- No agent merges, rebases across feature branches, resolves conflicts between unrelated PRs, deploys, changes permissions/secrets or bypasses policy. User handles final PR approval/merge and Jira Done until sync is implemented.

## Batch safety
- At most 3 issues per batch. Parallel builders only in isolated workspaces the runner can verify: a provider-native isolated worktree/VM (Claude `isolation: worktree`), for Cursor one git worktree per issue created and verified by the orchestrator before dispatch (that verification is the isolation proof), or for OpenCode one GitHub-hosted job per story (`max-parallel: 3`, `fail-fast: false`), each branched from its verified base. Never more than one writer in the same directory. A runner without such isolation processes ONE issue per run.
- Dispatch eligible work immediately in Rank order. Track distinct admitted keys for the whole run. Each admission consumes one of the three places even if its build finishes or fails. A pending dependency consumes none.
- Keep searching by Rank. With spare capacity, wait only for agent tasks in Ready/Listo, In Progress/En curso or AI Review to publish their prerequisite PR. For a Ready/Listo blocker, check that its own provider could admit it now: its prerequisites must be complete or covered by one verified stack. Trace unpublished prerequisites by key. Skip cycles and chains held up by human work, and include the blocking keys in the summary. A completed human blocker satisfies the Done gate. An unfinished human blocker, ambiguous route or missing PR in Human Review does not keep the run waiting.
- Recheck every 10 minutes for up to 5 hours 40 minutes from the first selection, using one shared deadline. Run eligible builders immediately and continue their reviews. Stop polling once the provider has admitted three distinct issues, no candidate warrants waiting, or the deadline expires.
- Record the published parent branch and SHA before creating the child worktree.

## Required output per issue
`ISSUE`, `ENGINE`, `REPO`, `ROUTE_VERIFIED`, `DEPENDENCY_GATE` (Done blockers / no blockers / verified parent PRs and SHAs / skipped), `BRANCH`, `PR_URL`, `TEST_COMMANDS_AND_RESULTS`, `REVIEW_VERDICT`, `AGENTS_MD_ACTION`, `JIRA_STATUS`, `NEXT_HUMAN_ACTION`.

Fail closed when required provider/Jira/GitHub/MCP permissions or actual code evidence are unavailable. No fake issue transitions, PRs or reviews.

## Cursor v2 operational addendum

Cursor uses ONE scheduled orchestration Automation (not two independent PR-trigger runs) plus repository subagents. It implements up to 3 eligible issues in parallel in the same invocation: before dispatch the orchestrator creates one git worktree per issue (`git worktree add /tmp/<KEY>-wt -b cursor/<KEY>-<slug> <BASE_COMMIT>` from the base branch fetched for that dispatch) and verifies it; that verification is the isolation proof. A worktree that cannot be created/verified makes only that issue `CONFIG_BLOCKED`; a dirty parent checkout after a builder makes the affected issue `BLOCKED`. A new read-only reviewer subagent inspects the published diff after every change; because the reviewer cannot make authenticated GitHub calls, the orchestrator fetches the published PR diff with authenticated git (`git fetch origin pull/<N>/head:pr-<N>` + `git diff <BASE_COMMIT>...pr-<N>`) and hands it over as a local file/text. Up to 3 corrections occur on the same branch/PR. AGENTS.md changes are owned by the parent orchestrator and reviewed before Jira Human Review. Separate v1 PR-event reviewer must be disabled. These are contracts, not guaranteed platform capabilities.

## OpenCode Go review budget

Effective for the OpenCode runner. Cursor and Claude are outside this section.

Authoritative integers: `automation/opencode/review_budget.py` (`MAX_CORRECTIONS`, `MAX_RE_REVIEWS`, `MAX_TOTAL_REVIEWS`). In this contracts repository that module lives at `multiprovider/opencode/automation/opencode/review_budget.py`. `verificar_textos` runs from `check_config.py` before inference and checks that the published texts match those integers. `decidir_tras_review` only classifies one verdict (`aceptar`, `corregir`, `bloquear`); it does not resume the builder or launch reviewers. The orchestrator prompt performs that loop.

- Up to 3 corrections after a reviewer `CHANGES_REQUESTED` (MAX_CORRECTIONS=3). The initial implementation is not a correction. Each correction resumes the same builder session on the same branch and PR. A fresh builder is not a correction path.
- Up to 3 re-reviews (MAX_RE_REVIEWS=3) in addition to the initial review. Maximum 4 reviews in total (MAX_TOTAL_REVIEWS=4). Each re-review is a new independent reviewer of the published PR head.
- PASS on the initial review, or PASS on any of the 3 re-reviews, accepts the story. A PASS on review 4 (the third re-review) accepts. Do not treat that PASS as exhaustion of the budget.
- If the re-review that follows the 3rd correction is still `CHANGES_REQUESTED`, stop as BLOCKED. Do not start a 4th correction or a 5th review.
- The decision is the same one implemented by `decidir_tras_review`: with `corrections_already_done == review_index - 1`, CHANGES_REQUESTED on reviews 1, 2 and 3 starts the next cycle, and CHANGES_REQUESTED on review 4 blocks. A review ceiling of 1 re-review, or of 3 total reviews, is not the OpenCode cap: either one would stop a cycle that MAX_CORRECTIONS=3 still allows.
- Time, token, step and story-selection caps stay as already configured for OpenCode (orchestrator 40 steps, reviewer 15 steps, builder without a step limit, watchdog 20400 s / 900 s without edits / 5M reported input tokens, at most 3 stories).
