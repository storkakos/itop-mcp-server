## Agent skills

### Issue tracker

Issues and specs live as local markdown files under `.scratch/<feature>/`. `.scratch/` is git-ignored and only exists in the main checkout; from a git worktree, reach it as described in `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Test VM

For anything that needs Docker (this machine has none), there is a test VM reachable over SSH. See `docs/agents/test-vm.md`.
