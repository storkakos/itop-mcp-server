# Issue tracker: Local Markdown

Issues and specs for this repo live as markdown files in `.scratch/`.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The spec is `.scratch/<feature-slug>/spec.md`
- Implementation issues are one file per ticket at `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`, never a single combined tickets file
- Triage state is recorded as a `Status:` line near the top of each issue file (see `triage-labels.md` for the role strings)
- Comments and conversation history append to the bottom of the file under a `## Comments` heading

## Where `.scratch/` lives

`.scratch/` is git-ignored. It exists only in the main checkout, never in a git worktree, and never on a branch.

If you work in a worktree (`.scratch/` is missing next to you), find the main checkout through git. The common git directory belongs to the main checkout, so its parent is the main checkout's root:

```sh
MAIN="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
ls "$MAIN/.scratch/"
```

`git worktree list` shows the same path: the first entry is always the main checkout. In the main checkout itself, `$MAIN` is just the repo root, so the same commands work everywhere.

### What you may change in the main checkout

From a worktree, change nothing in the main checkout except your own ticket file: claim it, tick its acceptance criteria, resolve it and append comments. Do not edit other tickets, specs or maps, do not touch the main checkout's working tree or branch, and do not commit there. All code and doc changes go into your worktree's branch.

## Working on a ticket next to other agents

- Before you resolve a ticket, rebase your branch onto the current target branch. If the rebase brought in changes to files you touched, run the affected tests or checks on the test VM again and note that second run in the ticket.
- A ticket never asks you to change a ticket or file of another repo. If something has to be handed over to another repo, write it in your own ticket under a heading `## Handover to <repo> <NN>`. The orchestrator carries it over when it merges your branch.
- Criteria about code (lint, tests) only apply when code changed. Write them that way, e.g. "If PHP files changed, the PHP lint passes", so a docs-only ticket is not left with a criterion nobody can tick.

## Terms

- **Orchestrator**: the session that hands out tickets to ticket agents, reviews their branches and merges them.
- **Ticket agent**: an agent that works on exactly one ticket, in its own git worktree on a branch `ticket/<id>`.
- **Twin ticket**: the matching ticket in a sibling repo. It names the leading ticket under Blocked by and reuses its solution instead of working it out again.
- **Handover**: what one ticket passes on to a ticket in another repo, written in its own ticket (see above).

## When a skill says "publish to the issue tracker"

Create a new file under `.scratch/<feature-slug>/` (creating the directory if needed).

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user will normally pass the path or the issue number directly.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a file with one **child** file per ticket.

- **Map**: `.scratch/<effort>/map.md` (the Notes / Decisions-so-far / Fog body).
- **Child ticket**: `.scratch/<effort>/issues/NN-<slug>.md`, numbered from `01`, with the question in the body. A `Type:` line records the ticket type (`research`/`prototype`/`grilling`/`task`); a `Status:` line records `claimed`/`resolved`.
- **Blocking**: a `Blocked by: NN, NN` line near the top. A ticket is unblocked when every file it lists is `resolved`.
- **Frontier**: scan `.scratch/<effort>/issues/` for files that are open, unblocked, and unclaimed; first by number wins.
- **Claim**: set `Status: claimed` and save before any work.
- **Resolve**: append the answer under an `## Answer` heading, set `Status: resolved`, then append a context pointer (gist + link) to the map's Decisions-so-far in `map.md`.
