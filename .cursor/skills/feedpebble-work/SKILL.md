---
name: feedpebble-work
description: >-
  Run the FeedPebble implementation workflow for an issue in the BenBot
  project: fetch issue context (including relations/blockers and project brief),
  confirm scope, in_progress, implement, update issue with work log, and move
  the issue to ready_for_qa on completion; never set done without explicit user
  request. Use when implementing or fixing work tied to a FeedPebble issue
  (e.g. BENBOT-7), when the user invokes /feedpebble-work, or when they pass an
  issue key as arguments. Optional arguments: issue key (BENBOT-*) or issue ULID.
disable-model-invocation: true
---

# FeedPebble work (BenBot)

Use this skill when implementation is tied to a **FeedPebble issue** in the
**BenBot** project (e.g. “implement **BENBOT-7**”, or the task clearly maps to
one issue).

Project defaults, issue-quality template, and tracked-issue rules:
**`.cursor/rules/feedpebble-scope.mdc`**.

This repo is not on git yet, has no database, and does not require tests. Skip
commits, migrations, and test runs.

## Issue reference (`$ARGUMENTS`)

When this skill is invoked with arguments, **`$ARGUMENTS`** is the issue
reference. Accept:

- **Issue key (preferred):** `BENBOT-7` (`<PREFIX>-<number>`; normalize to a
  single token like `BENBOT-7`).
- **Issue ULID:** 26-character ULID if the user passes one.

If **`$ARGUMENTS` is empty**:

- If the conversation already identifies **one** unambiguous issue, use that.
- If there are **zero** or **multiple** possible issues, **ask the user** which
  issue before calling FeedPebble MCP.

If the issue reference is **ambiguous**, **ask** before calling MCP.

### Project resolution

- **Default project:** `BenBot` (`projectSlug: "benbot"`). Do not hard-code
  `projectId`; resolve via `get_project { slug: "benbot" }` when needed.
- If the issue key uses a prefix that is **not** BenBot’s current prefix, or
  the user names another project, use that project’s slug and **do not** assume
  BenBot.

## Steps (complete in order, do not skip)

- [ ] **1. Fetch issue + project brief via FeedPebble MCP** — Call
  `get_issue_context` with `{ issueKey: "BENBOT-7", projectSlug: "benbot" }` or
  `{ issueId: "<ulid>" }`, and call `list_project_context` for the BenBot
  standing brief. Read title, description (Summary, Scope, Acceptance Criteria),
  priority, newest comments, and the embedded **`relations`** block. Record the
  issue **ULID**, **key**, and any **open blockers** — entries in
  `relations.blockedBy` whose `status` is `open`. (Blockers that are
  `in_progress`, `done`, or `cancelled` do **not** count — see step 1a.)

- [ ] **1a. Blocker gate** — Inspect `relations.blockedBy`:
  - **`open` blockers** — stop and surface them (key, title, status). These are
    unstarted prerequisites; ask whether to (a) switch to the blocker,
    (b) proceed anyway (stale/parallel dependency), or (c) cancel. Do **not** set
    `in_progress` until the user decides.
  - **`in_progress` blockers** — do **not** block. Leaving prerequisites
    `in_progress` while working through a related set is expected. Note them for
    context (one line) and continue.
  - **`done` / `cancelled` blockers** — satisfied; ignore.

  Prefer the live **`relations` graph** over the description's
  "Dependencies / Blockers" prose when they disagree; the prose can be stale.

- [ ] **2. Summarize what needs to be done; confirm understanding** — Short
  summary for the user; if scope is unclear, ask before coding. Also note
  relevant relations: a **`parent`** (tracking/epic context), any **`children`**
  (this may be an umbrella issue — confirm whether the ask is coordination vs.
  code), and any **`duplicates` / `duplicatedBy`** (flag possible redundancy
  before implementing).

- [ ] **2a. Parent context (conditional)** — If `relations.parent` exists **and**
  the issue cites it as source of truth (e.g. "Source of truth: BENBOT-X", "see
  BENBOT-X §N", "Refs: BENBOT-X") **or** scope is unclear without it, fetch the
  parent once via `get_issue` / `get_issue_context` for context. Focus on the
  cited sections when the issue names them (e.g. §3, §4). Otherwise skip — the
  child may be self-contained and fetching the parent burns context for little
  gain.

- [ ] **3. Set issue status → `in_progress`** — `update_issue` with
  `status: "in_progress"`. Only after the correct issue is confirmed. Skip if
  already `in_progress`.

- [ ] **3a. Create an agent run** — `feedpebble-create_agent_run` with
  `projectSlug: "dogfood"` (or the project resolved in step 1), `issueKey` from
  step 1, `state: "running"`, and a short `title` (the issue key plus the issue
  title). Keep the returned run id. Skip this step if you stopped at the blocker
  gate or are waiting on the user. Creating the run does not change issue status
  or assignee.

- [ ] **4. Implement the changes** — Follow `.cursor/rules/` and project
  conventions. Do not invent git commits, DB migrations, or test suites.

- [ ] **5. Update issue with a work log comment** — Post a comment on the issue
  via `add_issue_comment` (or `PATCH` the issue description only when a comment
  is not appropriate). Include: what changed, important paths. If
  `relations.blocks` is non-empty, mention which downstream issues this unblocks
  once verified (key + title) so the reviewer knows what becomes actionable next.
  Write for a human reviewer.

- [ ] **6. Set issue status → `ready_for_qa`** — Once implementation and the
  work-log comment are done, move the issue out of `in_progress` via
  `update_issue` with `status: "ready_for_qa"`. Confirm the slug exists for the
  project first with `list_issue_statuses { projectId }` (`ready_for_qa` is a
  default slug; if a project has renamed or removed it, pick the project's
  equivalent "ready for review/QA" slug and note the substitution).

- [ ] **7. Finish the agent run** — `feedpebble-update_agent_run` with the run
  id from step 3a and the same project.
  - Commit succeeded: `state: "succeeded"` and a `summary` of what landed. Set
    `externalUrl` to the pull request URL when this session opened one.
  - You started the run and then stopped because implementation, tests, or the
    commit failed: `state: "failed"` and a non-empty `error`.
  - Do not leave the run `running`.

## Status after completion

- Move the issue to **`ready_for_qa`** when you finish working on it (step 6) so
  the user knows it is ready to verify.
- **Do not** set the issue to `done`, `cancelled`, or `open`, unless the user
  **explicitly** asks for that status change — `done` in particular requires
  explicit user confirmation (see `.cursor/rules/feedpebble-scope.mdc`).

## Relations (optional)

When the work spawns a follow-up issue, link it with MCP relation tools:
`relate_issues` / `unrelate_issues` (or `list_issue_relations` to inspect).
Examples: `parent_of` under a tracking issue, `relates_to` for a related follow-up,
`blocks` for a declared prerequisite.
