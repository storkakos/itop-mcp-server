## Agent skills

### Issue tracker

Issues and specs live as local markdown files under `.scratch/<feature>/`. `.scratch/` is git-ignored and only exists in the main checkout; from a git worktree, reach it as described in `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Test VM

For anything that needs Docker (this machine has none), there is a test VM reachable over SSH. See `docs/agents/test-vm.md`.

Tests never run locally on this machine: not pytest, not the smoke test. Only the pane `vm-runner` talks to the VM. A ticket agent never runs `ssh`, `scripts/test-on-vm.sh` or `scripts/stack-on-vm.sh` itself: it commits, queues a request in the workspace's `.vm-queue/` (`../.vm-queue/README.md` from the main checkout's root is the protocol) and waits for the result. See `docs/agents/test-vm.md` (Only `vm-runner` uses the VM) and `docs/agents/issue-tracker.md` (Testing through the VM queue). The scripts themselves (`scripts/test-on-vm.sh` for pytest, `scripts/stack-on-vm.sh` for the test stack) are described in test-vm.md for the runner.
