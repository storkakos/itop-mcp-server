# Test VM (Docker host)

A throwaway VM on the maintainer's LAN for running the tests and anything that needs Docker, such as `scripts/smoke-test.sh`. This dev machine has neither Docker nor WSL.

| | |
| --- | --- |
| Host | `192.168.178.25` (only reachable from the maintainer's network) |
| User | `root` |
| OS | Debian 13 (trixie), Docker 29.10, Compose v5.8, 4 CPUs, 12 GB RAM minimum with ballooning (15.5 GB visible on 2026-11-25; the visible amount changes), no swap, 59 GB root disk (about 20 GB used) |
| Private key | `~/.ssh/itop-mcp-test-vm` (on the maintainer's machine, **never commit it**) |
| Host key | `~/.ssh/itop-mcp-test-vm.known_hosts` |

No password is written down anywhere. If the key is missing or rejected, ask the maintainer. Don't try to guess or recover a password.

## Tests always run on the VM

Run pytest and the smoke test on the VM, never locally on the Windows dev machine. The smoke test needs Docker, which only the VM has. pytest would run on Windows, but the virus scanner there slows the suite down to about 12 minutes, so a local run looks like a hang. On the VM the whole suite takes about 15 to 25 seconds.

## One command: `scripts/test-on-vm.sh`

From Git Bash in your checkout or worktree:

```sh
RUN=dp02 bash scripts/test-on-vm.sh                          # whole suite
RUN=dp02 bash scripts/test-on-vm.sh tests/test_config.py -x  # arguments go to pytest
```

The script does the steps below for you: it copies the working tree to `/root/itop-mcp-server-$RUN`, runs pytest in a throwaway container `$RUN-pytest` (the Python image from the `Dockerfile`'s `FROM` line, and the lock files), prints the output, removes the folder and the container again, also on failure or Ctrl-C, and exits with pytest's exit code. It refuses to start if the folder already exists, so it never touches another run. If the VM cannot be reached, it stops with ssh's error and exit code 255. pytest runs with `-q` unless you pass `-q` yourself, so the summary line always shows. Without `RUN` it picks a random `dev-<hex>` name. pytest needs no port. `VM_HOST`, `VM_KEY` and `VM_KNOWN_HOSTS` override the connection settings in the table above.

## One command for a test-stack run: `scripts/stack-on-vm.sh`

A whole run of `test-stack/` (start, checks, clean-up) from Git Bash in your checkout or worktree:

```sh
RUN=it-ti02 bash scripts/stack-on-vm.sh                # Caddy stack, all checks
RUN=it-ti02 bash scripts/stack-on-vm.sh --nginx        # nginx variant (adds compose.nginx.yaml)
RUN=it-ti02 bash scripts/stack-on-vm.sh -- -v          # arguments after -- go to checks.py
```

It copies the working tree to `/root/itop-mcp-server-$RUN`, takes a VM slot (see [Sharing the VM](#sharing-the-vm)), makes the test certificates, starts the stack as compose project `$RUN` with `TEST_TAG=$RUN` (images `itop-mcp-test-itop:$RUN`, `itop-mcp-server:$RUN`, `itop-mcp-test-client:$RUN`), waits until the setup is complete, runs the checks with their output straight through, and exits with their exit code. Afterwards it always takes the stack down with its volumes and removes its images, its folder and its slot, also on failure or Ctrl-C. The build and start output goes to a log on the VM; when the start fails, the script prints its last lines and the setup's log.

| Exit code | Meaning |
| --- | --- |
| the checks' code | the checks ran (0: no check failed) |
| 2 | wrong usage, or this RUN is already in use on the VM (folder, slot or compose project) |
| 3 | the stack did not start (or not within `START_TIMEOUT`, default 1500 s) |
| 4 | no VM slot within `VM_SLOT_TIMEOUT` (default 1800 s) |
| 255 | SSH failed: VM not reachable, key refused or connection lost |

RUN names must be unique on the whole VM, across repos: the compose project name is the bare `$RUN`, so an iTop and a Dolibarr run with the same name would share one project. Prefix the name with the repo, e.g. `it-ti02` here and `dl-ti02` in Dolibarr. The script refuses to start (exit 2) when the folder exists, when any slot already has that RUN, or when the VM has a container, volume or network of compose project `$RUN`. `RUN` must not be `local`, `latest`, `test-stack`, `itop-mcp-test` or `itop-mcp-smoke`, the stack's shared default tags and project names. The stack publishes no ports, so runs need no port of their own. `VM_HOST`, `VM_KEY` and `VM_KNOWN_HOSTS` work as for `test-on-vm.sh`; `VM_SLOT_MAX` (3) and `VM_SLOT_MIN_MB` (3072) change the slot rule. Without `test-stack/llm.env` on the VM the chat check is skipped, and the script never copies a key there.

If the script was killed so hard that its clean-up could not run (or SSH was gone), clean up by hand as described in [Clean up](#clean-up) and remove the slot: `rm -f /var/lib/test-vm-slots/itop-mcp-server-$RUN.lease`.

### Re-run after a settings change (cheap)

`stack-on-vm.sh` always takes the stack down at the end, so a re-run through it starts from scratch (5 to 10 minutes). When you only changed a setting and want to see the checks again, keep the stack and restart just the service that reads the setting. This is by hand, so you take the slot and clean up yourself: start the stack like the script does, **under a RUN name of its own**, and take it down when you are done (see [Clean up](#clean-up)).

```sh
RUN=it-ti04; DIR=/root/itop-mcp-server-$RUN
# once: copy (see "Copy the working tree over"), take a slot (lease file, see "Sharing the VM"), then
$SSH "cd $DIR/test-stack && export TEST_TAG=$RUN && sh make-certs.sh >/dev/null &&
      docker compose -p $RUN up -d --build --quiet-pull"       # returns when the setup is complete
# after each change: copy only the changed files, WITHOUT the rm -rf of the full copy (it would remove certs/)
git diff --name-only HEAD | tar -T - -cf - | $SSH "tar -xf - -C $DIR"      # plus new files: git ls-files -o --exclude-standard
$SSH "cd $DIR/test-stack && export TEST_TAG=$RUN && docker compose -p $RUN restart librechat"
$SSH "cd $DIR/test-stack && export TEST_TAG=$RUN && docker compose -p $RUN run --rm client python checks.py"
```

Which command picks up which change:

| Changed | Command (as `docker compose -p $RUN ...`) |
| --- | --- |
| a file mounted into a service (`librechat/librechat.yaml`, `Caddyfile`, `nginx/*`): the content, not the compose file | `restart <service>` (`librechat`, `proxy`) |
| `librechat/librechat.env`, a service's `environment:` or other compose settings | `up -d <service>` (recreates only that service) |
| something a service is built from (`Dockerfile`, `src/`, `test-stack/client/`, `itop/`) | `up -d --build <service>` (`mcp`, `itop`), for the checks themselves `build client` |
| the Keycloak realm, iTop's config or other things `client/setup.py` does once at the start | start from scratch (`stack-on-vm.sh`); the cheap re-run does not redo the setup |

After a restart LibreChat needs a few seconds before it answers: wait for its log line `Server readiness checks passing` (`docker compose -p $RUN logs --tail 5 librechat`) before the checks. A restart of `proxy` or `mcp` is ready in about a second. The checks always run the whole list, about 5 minutes (a wait for LibreChat's login limit is part of that). Proven on the VM under RUN `it-ti04`: the start took 1 minute with cached images, a changed line in `librechat.yaml` plus `restart librechat` took under a second, and the checks passed (18 passed, 0 failed, 3 skipped).

The sections below are the manual steps, for the smoke test and for debugging.

## Connect

```sh
SSH="ssh -i ~/.ssh/itop-mcp-test-vm -o UserKnownHostsFile=~/.ssh/itop-mcp-test-vm.known_hosts -o BatchMode=yes root@192.168.178.25"
$SSH
```

## Sharing the VM

The VM's RAM, not the number of agents, limits how many runs fit at once. It has no swap; when RAM runs out, SSH stops answering for many minutes and the kernel kills containers of other runs.

- A **ticket stack** is a full test stack started for one ticket under its own RUN name. Starting one takes a **VM slot**.
- At most 3 ticket stacks run at the same time. Start one only if at least 3 GB are available: `$SSH "free -m | awk '/^Mem:/{print \$7}'"` must print 3072 or more. If not, wait or ask the orchestrator.
- `scripts/stack-on-vm.sh` keeps this rule for you: a **slot** is a lease file `/var/lib/test-vm-slots/<repo>-<RUN>.lease`, taken under `flock` on `/var/lib/test-vm-slots/.lock` only while fewer than 3 leases exist and at least 3072 MB are available; otherwise the script waits and says why. The folder is shared by every repo that uses the VM, so the limit counts all their stacks together. A lease whose run folder is gone for 15 minutes, or that is older than 3 hours, counts as left over by a killed run and is dropped. When you start a stack by hand, take a slot the same way or count the leases yourself.
- Take your stack down right after the run, also when it failed: `docker compose -p $RUN down -v --remove-orphans`, then remove your images (see Clean up).
- Never stop, change or read stacks, folders or files you did not create, including other stacks' `.env` and key files. Some stacks on the VM run permanently on purpose.

## Your own run: folder, project name, port

Several agents may use the VM at the same time. Every run picks one name of its own and uses it for its folder on the VM, its smoke test project name and its pytest container, plus a port of its own for the smoke test. Use lowercase letters, digits and `-` only (compose project names allow nothing else), e.g. `db13` for ticket 13 of `docker-build`. For the port, take 18200 plus your ticket number:

```sh
RUN=db13                                # your own name: lowercase, digits, -
DIR=/root/itop-mcp-server-$RUN          # your own folder on the VM
PORT=18213                              # your own smoke test port: 18200 + ticket number
$SSH "ss -ltn | grep -q ':$PORT ' && echo 'port $PORT is taken, pick another' || echo 'port $PORT is free'"
```

Never use the bare `/root/itop-mcp-server` folder, the default smoke project `itop-mcp-smoke` or the default port 18130 when others may be on the VM. pytest needs no port of its own: it runs in its own container with its own network.

## Copy the working tree over

This copies tracked and untracked files but not git-ignored ones, so uncommitted changes come along and `.env`, `compose.override.yaml`, `certs/`, `logs/` and `.venv/` stay behind. It replaces only your own folder:

```sh
git ls-files -z --cached --others --exclude-standard | tar --null -T - -cf - \
  | $SSH "rm -rf $DIR && mkdir $DIR && tar -xf - -C $DIR"
```

The copy has no `.git` folder (`stack-on-vm.sh` and `test-on-vm.sh` copy the same way). What does not work because of that:

- Every `git` command in the VM folder fails (`not a git repository`): no `git status`, `diff` or `log` there. Do your git work on the dev machine and copy the result over.
- The one test that reads git attributes (`tests/test_container_files.py`, the LF line endings check) is skipped on the VM, so a CRLF file does not show up there. Check it on the dev machine with `git ls-files --eol | grep -v w/lf` (see below).
- Git-ignored files are not copied either: put nothing a run needs into `.env`, `compose.override.yaml`, `certs/`, `logs/` or `.venv/` (the stack makes its own certificates).

`.gitattributes` gives every text file LF line endings, also on Windows with `core.autocrlf=true`, so the copy runs on Linux as-is. A checkout made before that rule existed keeps its CRLF files until they are written again; `git ls-files --eol | grep -v w/lf` lists them. To rewrite them, commit or stash your changes first, then run this in the checkout:

```sh
git ls-files -z | xargs -0 rm -f -- && git checkout -- .
```

## Run pytest

The full suite in a throwaway `python:3.13-slim` container with the locked dependencies, the same steps as in the README. Your folder is mounted read-only and copied inside the container, so the install leaves nothing behind in it, and `--rm` removes the container afterwards:

```sh
$SSH "docker run --rm --name $RUN-pytest -v $DIR:/src:ro python:3.13-slim sh -c '
  cp -r /src /work && cd /work &&
  export PIP_ROOT_USER_ACTION=ignore PIP_DISABLE_PIP_VERSION_CHECK=1 &&
  pip install -q --no-deps -r requirements.lock -r requirements-build.lock &&
  pip install -q --no-deps --no-build-isolation -e . &&
  pip install -q pytest==8.4.2 &&
  pytest -q'"
```

Pass pytest arguments at the end as usual, e.g. `pytest -q tests/test_config.py`. The container needs internet access to PyPI.

## Run the smoke test

```sh
$SSH "cd $DIR && SMOKE_PROJECT=$RUN SMOKE_PORT=$PORT bash scripts/smoke-test.sh"
```

The script tags its image `itop-mcp-server:<version>-$RUN`, so it never replaces another run's image or the shared `itop-mcp-server:<version>` tag. When it ends it stops its containers (`docker compose down`) and deletes its `.smoke` work folder, but it keeps the image.

## Clean up

Remove only what you created yourself, and nothing else:

```sh
$SSH "docker rmi itop-mcp-server:\$(sed -n 's/^__version__ = \"\(.*\)\"\$/\1/p' $DIR/src/itop_mcp_server/__init__.py)-$RUN; rm -rf $DIR"
```

### A ticket stack killed halfway

When `stack-on-vm.sh` or a by-hand run died without its clean-up (Ctrl-C that did not get through, lost SSH, killed shell), the stack of that run is still on the VM. Find it and take it down by its project name, which is the bare `$RUN`; nothing else is touched:

```sh
$SSH "docker ps -a --filter label=com.docker.compose.project=$RUN --format '{{.Names}} {{.Status}}'"   # what is left
$SSH "docker compose -p $RUN down --volumes --remove-orphans --timeout 5"      # containers, network, volumes, from any folder
$SSH "docker rmi \$(docker images --format '{{.Repository}}:{{.Tag}}' | grep ':$RUN\$')"   # the images tagged :$RUN (itop, mcp, client)
$SSH "rm -rf /root/itop-mcp-server-$RUN /var/lib/test-vm-slots/itop-mcp-server-$RUN.lease"   # folder and VM slot
```

Check afterwards that the first command prints nothing. Use exactly your own `$RUN`: a prefix match would take down other runs. Without the folder, `docker compose -p $RUN down` still works; `docker compose config` (which the script uses to list the images) does not, hence the `docker images` lookup. A pytest container of a killed `test-on-vm.sh` run is `$SSH "docker rm -f $RUN-pytest"`.

Keep the shared things in place, even if they look unused: the `python:3.13-slim` image, the `itop-mcp-server:<version>` tag, and other runs' images, containers, networks and folders. Never run `docker system prune`, `docker image prune -a`, `docker builder prune` or `docker rm -f $(docker ps -aq)`: they hit every run on the VM, not just yours.

## Notes

- The VM exists only for testing and may be wiped or recreated at any time. If the host key changed, ask the maintainer before you trust the new one.
- Commands run as root there. For the default admin path, `./logs` must still be `chown 10001:10001` (see `.env.example`). The smoke test does not need this; it uses its own log folder.
