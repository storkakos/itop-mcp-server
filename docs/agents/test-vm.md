# Test VM (Docker host)

A throwaway VM on the maintainer's LAN for running things that need Docker, such as `scripts/smoke-test.sh`. This dev machine has neither Docker nor WSL.

| | |
| --- | --- |
| Host | `192.168.178.25` (only reachable from the maintainer's network) |
| User | `root` |
| OS | Debian 13 (trixie), Docker 29, Compose v5, 2 CPUs, 4 GB RAM, 10 GB disk |
| Private key | `~/.ssh/itop-mcp-test-vm` (on the maintainer's machine, **never commit it**) |
| Host key | `~/.ssh/itop-mcp-test-vm.known_hosts` |

No password is written down anywhere. If the key is missing or rejected, ask the maintainer. Don't try to guess or recover a password.

## Connect

```sh
ssh -i ~/.ssh/itop-mcp-test-vm -o UserKnownHostsFile=~/.ssh/itop-mcp-test-vm.known_hosts -o BatchMode=yes root@192.168.178.25
```

## Copy the working tree over

This copies tracked and untracked files but not git-ignored ones, so uncommitted changes come along and `.env`, `logs/` and `.venv/` stay behind:

```sh
SSH="ssh -i ~/.ssh/itop-mcp-test-vm -o UserKnownHostsFile=~/.ssh/itop-mcp-test-vm.known_hosts -o BatchMode=yes root@192.168.178.25"
git ls-files -z --cached --others --exclude-standard | tar --null -T - -cf - \
  | $SSH 'rm -rf /root/itop-mcp-server && mkdir /root/itop-mcp-server && tar -xf - -C /root/itop-mcp-server'
$SSH 'cd /root/itop-mcp-server && bash scripts/smoke-test.sh'
```

## Notes

- The VM exists only for testing and may be wiped or recreated at any time. If the host key changed, ask the maintainer before you trust the new one.
- Commands run as root there. For the default admin path, `./logs` must still be `chown 10001:10001` (see `.env.example`).
- Clean up containers and test folders you created when you are done (`docker compose down`, `rm -rf`).
