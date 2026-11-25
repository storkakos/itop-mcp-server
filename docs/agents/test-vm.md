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

## Only `vm-runner` uses the VM

When several agents work at once, exactly one session, the pane **`vm-runner`**, talks to the VM. **Ticket agents never run `ssh`, `scripts/test-on-vm.sh` or `scripts/stack-on-vm.sh` themselves**, not even to look. They commit, queue a request and wait for the result file. Each agent starting its own stacks made runs slow and fought over the VM's RAM; one runner with a queue does not.

The queue is the folder `.vm-queue/` in the workspace, next to the repos: `../.vm-queue/` from the main checkout's root. From a worktree, go through the main checkout (see [issue-tracker.md](issue-tracker.md#where-scratch-lives)):

```sh
MAIN="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")"
QUEUE="$MAIN/../.vm-queue"
cat "$QUEUE/README.md"
```

**`../.vm-queue/README.md` is the single source of the protocol.** Read it before you queue; if this summary and the README ever disagree, the README wins. In short:

- **Request** `<agent>.md`, written only after the commit: `agent`, `repo`, `branch`, `commit`, `target` (the branch you will be merged into), `kind` (`batch` or `single`), `needs` (`stack`, `pytest`, `lint`, `stack+pytest`), `variant` (`caddy`, `nginx`, `both`), `checks` (check groups or `all`), `pytest` (paths or `all`), `llm` (`key`, `none`, `both`) and `proves` (which criteria the run proves). One request per agent; to re-queue, overwrite it with the new commit and delete your old result.
- **`batch`** (default): the runner may merge your branch with other queued branches of the same repo into a temporary integration branch (from `target`) and test them all in one stack with only the check groups the requests need. **`single`**: a run that cannot be shared (a deliberately failing check, Ctrl-C, a scenario step by step); you give the exact `## Steps` and, for temporary changes, a `## Patch`, never a commit.
- **Result** `<agent>.result.md`, written only by `vm-runner`: `commit`, `status` (`PASS`, `FAIL`, `CONFLICT`, `ERROR`), `run` (the RUN name and what it included), `summary` and an excerpt. What to do with each status is in [issue-tracker.md](issue-tracker.md#testing-through-the-vm-queue).
- **Finding the culprit**: when a batch run fails, the runner reruns the failing check group (or test) per branch. The branch that fails alone gets `FAIL` with its lines; the others get `PASS`. A branch that does not merge cleanly gets `CONFLICT` and is run alone or sent back for a rebase.

### What the runner takes care of

These are `vm-runner`'s job, not the ticket agent's:

- the VM rules in [Sharing the VM](#sharing-the-vm): at most 3 stacks at once, a VM slot per stack, enough free RAM;
- unique RUN names across repos (prefixed `it-`, `dl-`, `ra-`);
- the shared LLM key (see [LLM key](#llm-key)): pointing runs at it, never printing it;
- the [clean-up](#clean-up) after every run: stacks, volumes, networks, images, folders and slots of its RUNs, plus its integration branches and worktrees (local only, never pushed).

The rest of this file is the reference for the runner, and for the maintainer working alone without the queue.

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
RUN=it-ti02 bash scripts/stack-on-vm.sh --groups prerequisites,example   # only these check groups
RUN=it-ti02 bash scripts/stack-on-vm.sh -- -v          # arguments after -- go to checks.py
```

It copies the working tree to `/root/itop-mcp-server-$RUN`, takes a VM slot (see [Sharing the VM](#sharing-the-vm)), makes the test certificates, starts the stack as compose project `$RUN` with `TEST_TAG=$RUN` (images `itop-mcp-test-itop:$RUN`, `itop-mcp-server:$RUN`, `itop-mcp-test-client:$RUN`), starts only the services the chosen check groups need (see below), waits until the setup is complete, prints the started containers with their RAM, runs the checks with their output straight through, and exits with their exit code. Afterwards it always takes the stack down with its volumes and removes its images, its folder and its slot, also on failure or Ctrl-C. The build and start output goes to a log on the VM; when the start fails, the script prints its last lines and the setup's log.

**Check groups** (`--groups`, default `all`): the checks are split into the groups `prerequisites`, `proxy`, `example` (Keycloak and iTop) and `librechat` (see [test-stack/README.md](../../test-stack/README.md#check-groups)). `--groups prerequisites,proxy` runs only those groups and starts only the setup and its dependencies: neither LibreChat nor Mongo. Only a list with `librechat` (or `all`) starts them. Unknown names stop the script before it touches the VM (exit 2). Before the first LibreChat check the checks wait until LibreChat answers (up to 300 s), so they no longer fail right after the setup.

| Exit code | Meaning |
| --- | --- |
| the checks' code | the checks ran (0: no check failed) |
| 2 | wrong usage, or this RUN is already in use on the VM (folder, slot or compose project) |
| 3 | the stack did not start (or not within `START_TIMEOUT`, default 1500 s) |
| 4 | no VM slot within `VM_SLOT_TIMEOUT` (default 1800 s) |
| 5 | the checks passed, but an LLM key showed up in a log, the check output or an image (see [LLM key](#llm-key)) |
| 255 | SSH failed: VM not reachable, key refused or connection lost |

RUN names must be unique on the whole VM, across repos: the compose project name is the bare `$RUN`, so an iTop and a Dolibarr run with the same name would share one project. Prefix the name with the repo, e.g. `it-ti02` here and `dl-ti02` in Dolibarr. The script refuses to start (exit 2) when the folder exists, when any slot already has that RUN, or when the VM has a container, volume or network of compose project `$RUN`. `RUN` must not be `local`, `latest`, `test-stack`, `itop-mcp-test` or `itop-mcp-smoke`, the stack's shared default tags and project names. The stack publishes no ports, so runs need no port of their own. `VM_HOST`, `VM_KEY` and `VM_KNOWN_HOSTS` work as for `test-on-vm.sh`; `VM_SLOT_MAX` (3) and `VM_SLOT_MIN_MB` (3072) change the slot rule. For the LLM key see [LLM key](#llm-key): the script points the stack at the shared key file and never copies it; without that file the chat checks report SKIP.

If the script was killed so hard that its clean-up could not run (or SSH was gone), clean up by hand as described in [Clean up](#clean-up) and remove the slot: `rm -f /var/lib/test-vm-slots/itop-mcp-server-$RUN.lease`.

### Re-run after a settings change (cheap)

`stack-on-vm.sh` always takes the stack down at the end, so a re-run through it starts from scratch (5 to 10 minutes). When you only changed a setting and want to see the checks again, keep the stack and restart just the service that reads the setting. This is by hand, so you take the slot and clean up yourself: start the stack like the script does, **under a RUN name of its own**, and take it down when you are done (see [Clean up](#clean-up)).

```sh
RUN=it-ti04; DIR=/root/itop-mcp-server-$RUN
# once: copy (see "Copy the working tree over"), take a slot (lease file, see "Sharing the VM"), then
$SSH "cd $DIR/test-stack && export TEST_TAG=$RUN LLM_ENV_FILE=/root/shared/llm.env && sh make-certs.sh >/dev/null &&
      docker compose -p $RUN up -d --build --quiet-pull"       # returns when the setup is complete
# after each change: copy only the changed files, WITHOUT the rm -rf of the full copy (it would remove certs/)
git diff --name-only HEAD | tar -T - -cf - | $SSH "tar -xf - -C $DIR"      # plus new files: git ls-files -o --exclude-standard
$SSH "cd $DIR/test-stack && export TEST_TAG=$RUN LLM_ENV_FILE=/root/shared/llm.env && docker compose -p $RUN restart librechat"
$SSH "cd $DIR/test-stack && export TEST_TAG=$RUN LLM_ENV_FILE=/root/shared/llm.env && docker compose -p $RUN run --rm client python checks.py"      # or: ... python checks.py librechat (only that group)
```

Which command picks up which change:

| Changed | Command (as `docker compose -p $RUN ...`) |
| --- | --- |
| a file mounted into a service (`librechat/librechat.yaml`, `Caddyfile`, `nginx/*`): the content, not the compose file | `restart <service>` (`librechat`, `proxy`) |
| `librechat/librechat.env`, a service's `environment:` or other compose settings | `up -d <service>` (recreates only that service) |
| something a service is built from (`Dockerfile`, `src/`, `test-stack/client/`, `itop/`) | `up -d --build <service>` (`mcp`, `itop`), for the checks themselves `build client` |
| the Keycloak realm, iTop's config or other things `client/setup.py` does once at the start | start from scratch (`stack-on-vm.sh`); the cheap re-run does not redo the setup |

After a restart LibreChat needs a few seconds before it answers (its log line `Server readiness checks passing`, `docker compose -p $RUN logs --tail 5 librechat`); the checks wait for it themselves, up to 300 s, before the group `librechat`. A restart of `proxy` or `mcp` is ready in about a second. The whole list takes about 5 minutes (a wait for LibreChat's login limit is part of that); name groups to run fewer (`python checks.py prerequisites`). Proven on the VM under RUN `it-ti04`: the start took 1 minute with cached images, a changed line in `librechat.yaml` plus `restart librechat` took under a second, and the checks passed (18 passed, 0 failed, 3 skipped).

## LLM key

The chat checks (example 7: a chat answer through LibreChat) need an LLM key. The VM has exactly one, for every repo and every agent:

| | |
| --- | --- |
| File | `/root/shared/llm.env` (folder `/root/shared` 0700, file 0600, root:root, put there by the maintainer) |
| Variables | `OPENROUTER_KEY`, `LLM_KEY`, `LLM_BASE_URL`, `LLM_MODEL` (`openrouter/free`) |

- This file is the only LLM key agents may use. Keys in other stacks' folders, `.env` files or containers are off limits, also when your chat check would otherwise be skipped: never read, copy or reuse them.
- Never print the key, and never copy it into a repo, the run's folder, a ticket, a log or a commit. To see which variables the file has, print the names only: `$SSH "sed -n 's/=.*//p' /root/shared/llm.env"`.
- `scripts/stack-on-vm.sh` lets the stack read the file where it is: it sets `LLM_ENV_FILE=/root/shared/llm.env`, and `test-stack/compose.yaml` passes that file to LibreChat and the check client as an `env_file` (optional), so the key is in their environment at runtime only, not in an image or a file of the run.
- Without the file, every chat check reports `SKIP no shared LLM key`, and the run's exit code ignores SKIPs. To try that, point `VM_LLM_ENV` at a path that does not exist (`VM_LLM_ENV=/root/shared/none.env RUN=it-x bash scripts/stack-on-vm.sh`); never move or rename the real file.
- After the checks the script looks for the key's values on the VM in the start log, the logs of all the stack's containers, the check output and the config of the run's images, and prints only where it found one (exit 5). By hand, compare on the VM without printing the key, e.g. `grep -qF "$(sed -n 's/^LLM_KEY=//p' /root/shared/llm.env | cut -c10-25)" <file> && echo found`.
- The chat model is OpenRouter's free route `openrouter/free` (maintainer decision), set in `test-stack/librechat/librechat.yaml`.

The sections below are the manual steps, for the smoke test and for debugging.

## Connect

```sh
SSH="ssh -i ~/.ssh/itop-mcp-test-vm -o UserKnownHostsFile=~/.ssh/itop-mcp-test-vm.known_hosts -o BatchMode=yes root@192.168.178.25"
$SSH
```

## Sharing the VM

This section is `vm-runner`'s job (see [Only `vm-runner` uses the VM](#only-vm-runner-uses-the-vm)). The VM's RAM, not the number of agents, limits how many runs fit at once. It has no swap; when RAM runs out, SSH stops answering for many minutes and the kernel kills containers of other runs.

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
