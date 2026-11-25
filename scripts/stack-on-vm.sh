#!/usr/bin/env bash
# One whole test-stack run on the test VM, from this dev machine. See docs/agents/test-vm.md.
#
#   RUN=it-ti02 bash scripts/stack-on-vm.sh                 # Caddy stack, all checks
#   RUN=it-ti02 bash scripts/stack-on-vm.sh --nginx         # nginx variant (compose.nginx.yaml)
#   RUN=it-ti02 bash scripts/stack-on-vm.sh --groups prerequisites,proxy   # only these check groups
#   RUN=it-ti02 bash scripts/stack-on-vm.sh -- -v           # everything after -- goes to checks.py
#
# Steps: copy the working tree (tracked and untracked files, not git-ignored ones) to
# /root/<repo>-$RUN on the VM, wait for a free VM slot, make the test certificates, start the stack
# as compose project $RUN with image tags :$RUN (only the services the chosen check groups need: groups
# without LibreChat start neither LibreChat nor Mongo), wait for the setup, print the started containers
# and their RAM, run the checks and print their output, then always
# take the stack down with its volumes and remove its images, folder and slot, also on failure or
# Ctrl-C. Exits with the checks' exit code.
#
# LLM key: the stack reads the VM's one shared key file VM_LLM_ENV in place (compose env_file through
# LLM_ENV_FILE, at runtime only); it is never copied into the repo or the run's folder. Without the
# file the chat checks report SKIP "no shared LLM key". After the checks the script looks for the
# key's values in the start log, the stack's logs, the check output and its images' config, on the
# VM, and prints only where it found one (exit 5).
#
# Exit codes: the checks' own code once they ran; 2 wrong usage or RUN already in use on the VM
# (by any repo: RUN is the bare compose project name, so prefix it, e.g. it-ti02); 3 the stack
# did not start (the tail of the start log is printed); 4 no VM slot within VM_SLOT_TIMEOUT;
# 5 the checks passed but an LLM key showed up in a log, the check output or an image;
# 255 SSH failed (VM not reachable, key refused, connection lost).
#
# Environment:
#   RUN             name of this run: lowercase letters, digits, - (default: dev-<random>). Used for
#                   the VM folder, the compose project name and the image tag suffix (TEST_TAG).
#   VM_HOST         default root@192.168.178.25
#   VM_KEY          default ~/.ssh/itop-mcp-test-vm
#   VM_KNOWN_HOSTS  default ~/.ssh/itop-mcp-test-vm.known_hosts
#   VM_SLOT_MAX     ticket stacks at once on the VM (default 3)
#   VM_SLOT_MIN_MB  available RAM needed to start (default 3072)
#   VM_SLOT_TIMEOUT seconds to wait for a slot before giving up (default 1800)
#   START_TIMEOUT   seconds for build + start until the setup is complete (default 1500)
#   VM_LLM_ENV      the shared LLM key file on the VM (default /root/shared/llm.env; point it at a
#                   path that does not exist to test the run without a key)
set -euo pipefail

# --- What differs between repos (the Dolibarr twin changes only this block) ----------------------
REPO_NAME=itop-mcp-server                      # VM folder /root/$REPO_NAME-$RUN
STACK_DIR=test-stack                           # folder of the stack's compose files
COMPOSE_FILES=(-f compose.yaml)                # --nginx adds -f compose.nginx.yaml
PREPARE='sh make-certs.sh >/dev/null'          # run in STACK_DIR on the VM before the start
CHECKS=(run --rm client python checks.py)      # compose arguments of the check run (groups are added)
# Compose arguments that print the services to start for the groups that follow (checks.py --services).
SERVICES=(run --rm --no-deps client python checks.py --services)
SETUP_SERVICE=setup                            # one-shot setup; the checks start once it completed
GROUP_DIR=test-stack/client/groups             # one file <group>.py per check group
# Never usable as RUN: the stack's default image tags and project names.
RESERVED_RUNS=" local latest test-stack itop-mcp-test itop-mcp-smoke "
# ---------------------------------------------------------------------------------------------------

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
ME=stack-on-vm

while [ "$#" -gt 0 ]; do
  case "$1" in
    --nginx) COMPOSE_FILES+=(-f compose.nginx.yaml); shift ;;
    --groups) [ "$#" -ge 2 ] || { echo "$ME: --groups needs a list, e.g. --groups prerequisites,proxy" >&2; exit 2; }
              GROUPS_ARG="$2"; shift 2 ;;
    --) shift; break ;;
    *) echo "$ME: unknown option '$1' (arguments for the checks go after --)" >&2; exit 2 ;;
  esac
done

RUN="${RUN:-dev-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')}"
if ! [[ "$RUN" =~ ^[a-z0-9][a-z0-9-]*$ ]] || [[ "$RESERVED_RUNS" == *" $RUN "* ]]; then
  echo "$ME: RUN must be lowercase letters, digits and -, and not one of:$RESERVED_RUNS(got '$RUN')" >&2
  exit 2
fi
# Check groups: --groups a,b (or "all", the default). Each name must have its file in GROUP_DIR.
GROUPS_ARG="${GROUPS_ARG:-all}"
if ! [[ "$GROUPS_ARG" =~ ^[a-z0-9_]+(,[a-z0-9_]+)*$ ]]; then
  echo "$ME: --groups takes names separated by commas, e.g. prerequisites,proxy (got '$GROUPS_ARG')" >&2
  exit 2
fi
CHECK_GROUPS="${GROUPS_ARG//,/ }"
for g in $CHECK_GROUPS; do
  if [ "$g" != all ] && [ ! -f "$GROUP_DIR/$g.py" ]; then
    known="$(cd "$GROUP_DIR" && ls *.py | grep -v '^__' | sed 's/\.py$//' | tr '\n' ' ')"
    echo "$ME: unknown check group '$g' (groups: ${known}or all)" >&2
    exit 2
  fi
done
VM_HOST="${VM_HOST:-root@192.168.178.25}"
DIR="/root/$REPO_NAME-$RUN"
SLOT_DIR=/var/lib/test-vm-slots                # shared by all repos that use the VM
LEASE="$SLOT_DIR/$REPO_NAME-$RUN.lease"
SLOT_MAX="${VM_SLOT_MAX:-3}"
SLOT_MIN_MB="${VM_SLOT_MIN_MB:-3072}"
SLOT_TIMEOUT="${VM_SLOT_TIMEOUT:-1800}"
START_TIMEOUT="${START_TIMEOUT:-1500}"
LLM_ENV="${VM_LLM_ENV:-/root/shared/llm.env}"  # the VM's one shared LLM key, root-only (see test-vm.md)
if ! [[ "$LLM_ENV" =~ ^/[A-Za-z0-9._/-]+$ ]]; then
  echo "$ME: VM_LLM_ENV must be an absolute path of letters, digits, . _ / - (got '$LLM_ENV')" >&2
  exit 2
fi

SSH=(ssh -i "${VM_KEY:-$HOME/.ssh/itop-mcp-test-vm}"
  -o "UserKnownHostsFile=${VM_KNOWN_HOSTS:-$HOME/.ssh/itop-mcp-test-vm.known_hosts}"
  -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=4 "$VM_HOST")

# Compose as this run sees it, on the VM: own project name and image tags. Use as "$IN_STACK && $DC ...".
# LLM_ENV_FILE: compose reads the shared key file where it is (env_file, required: false), so the
# key is never copied and a missing file only makes the chat checks SKIP.
IN_STACK="cd $DIR/$STACK_DIR && export TEST_TAG=$RUN LLM_ENV_FILE=$LLM_ENV"
DC="docker compose -p $RUN ${COMPOSE_FILES[*]}"

# vm CMD: run CMD on the VM and return its exit code. ssh exits 255 when it cannot connect, log in
# or keep the connection; that is reported as an SSH failure and ends the run with 255.
vm() {
  local rc=0
  "${SSH[@]}" "$1" || rc=$?
  if [ "$rc" -eq 255 ]; then
    echo "$ME: SSH to $VM_HOST failed (not reachable, key refused or connection lost), see the ssh error above" >&2
    exit 255
  fi
  return "$rc"
}

cleaned=
cleanup() {
  [ -n "$cleaned" ] && return
  cleaned=1
  echo "$ME: taking down run $RUN (containers, volumes, images, folder, slot)"
  # First stop this run's compose commands that may still run on the VM after Ctrl-C (matched by
  # process name, so this shell, whose command line also says "compose -p $RUN", is spared), then
  # remove only what this run created: its project, the images tagged :$RUN, its folder, its slot.
  "${SSH[@]}" "ps -eo pid=,comm=,args= | awk '(\$2 == \"docker\" || \$2 == \"docker-compose\") &&
      index(\$0, \" compose -p $RUN \") { print \$1 }' | xargs -r kill 2>/dev/null; sleep 1
    if [ -d $DIR/$STACK_DIR ]; then
      ($IN_STACK && $DC down --volumes --remove-orphans --timeout 5) >/dev/null 2>&1
      imgs=\$($IN_STACK && $DC config --images 2>/dev/null | grep ':$RUN\$')
      [ -z \"\$imgs\" ] || docker rmi \$imgs >/dev/null 2>&1
    fi
    docker compose -p $RUN down --volumes --remove-orphans --timeout 5 >/dev/null 2>&1
    rm -rf $DIR; rm -f $LEASE
    ! docker ps -aq --filter label=com.docker.compose.project=$RUN | grep -q ." || {
    echo "$ME: cleanup on the VM failed or is incomplete. By hand: docker compose -p $RUN down -v --remove-orphans;" \
      "docker rmi the images tagged :$RUN; rm -rf $DIR $LEASE" >&2
  }
}

echo "$ME: run $RUN, folder $DIR, compose project $RUN, image tags :$RUN"
# RUN must be free on the whole VM, not only for this repo: the compose project name is the bare
# $RUN, so a run of another repo with the same RUN would share containers, volumes and networks,
# and either cleanup would destroy the other's stack. The traps are set only after this check, so a
# refused run never takes anything down.
rc=0
vm "if [ -e $DIR ]; then echo 'its folder $DIR exists'; exit 1; fi
  if [ -e $LEASE ] || grep -qsx 'run=$RUN' $SLOT_DIR/*.lease; then echo 'a VM slot with run=$RUN is taken'; exit 1; fi
  for kind in 'container ls -a' 'volume ls' 'network ls'; do
    if [ \"\$(docker \$kind -q --filter label=com.docker.compose.project=$RUN | head -n1)\" ]; then
      echo \"compose project $RUN already has a \${kind%% *}\"; exit 1
    fi
  done" >&2 || rc=$?
if [ "$rc" -ne 0 ]; then
  echo "$ME: RUN=$RUN is already in use on the VM (see above), maybe by another repo; pick another RUN, prefixed with the repo (e.g. it-ti02)" >&2
  exit 2
fi
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# 1. Copy the working tree (through a local file, so an SSH failure keeps its own exit code).
tarball="$(mktemp)"
git ls-files -z --cached --others --exclude-standard | tar --null -T - -cf "$tarball"
rc=0
vm "mkdir $DIR && tar -xf - -C $DIR" < "$tarball" || rc=$?
rm -f "$tarball"
[ "$rc" -eq 0 ] || { echo "$ME: copying the working tree to $DIR failed" >&2; exit 2; }

# 2. Take a VM slot: a lease file in $SLOT_DIR, taken under a flock so two runs never count at the
# same time. Leases whose folder is gone and that are older than 15 minutes, or older than 3 hours,
# belong to runs that died without cleanup and are dropped.
take_slot="mkdir -p $SLOT_DIR && exec 9>$SLOT_DIR/.lock && flock -w 60 9 || { echo BUSY; exit 0; }
  now=\$(date +%s)
  for f in $SLOT_DIR/*.lease; do
    [ -e \"\$f\" ] || continue
    age=\$(( now - \$(stat -c %Y \"\$f\") )); d=\$(sed -n 's/^dir=//p' \"\$f\")
    if { [ ! -d \"\$d\" ] && [ \$age -gt 900 ]; } || [ \$age -gt 10800 ]; then rm -f \"\$f\"; fi
  done
  n=\$(ls $SLOT_DIR/*.lease 2>/dev/null | wc -l)
  mb=\$(awk '/^MemAvailable:/{print int(\$2/1024)}' /proc/meminfo)
  if [ \$n -lt $SLOT_MAX ] && [ \$mb -ge $SLOT_MIN_MB ]; then
    printf 'dir=%s\nrun=%s\nstarted=%s\n' $DIR $RUN \"\$(date -Is)\" > $LEASE; echo TAKEN
  else
    echo \"WAIT \$n \$mb\"
  fi"
deadline=$(( $(date +%s) + SLOT_TIMEOUT ))
while :; do
  answer="$(vm "$take_slot")" || exit $?
  case "$answer" in
    TAKEN) echo "$ME: got a VM slot"; break ;;
    WAIT*) read -r _ n mb <<<"$answer"
           msg="$n of $SLOT_MAX ticket stacks running, $mb MB available (need $SLOT_MIN_MB)" ;;
    *)     msg="slot lock busy" ;;
  esac
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "$ME: no VM slot within ${SLOT_TIMEOUT}s ($msg); try later or ask the orchestrator" >&2
    exit 4
  fi
  echo "$ME: waiting for a VM slot: $msg"
  sleep 30
done

# 3. Start the stack. up returns once the one-shot setup has completed (LibreChat depends on it).
# The build and start output goes to a log on the VM and is shown only when the start fails.
if vm "[ -f $LLM_ENV ]"; then
  echo "$ME: LLM key: the stack reads the shared key file $LLM_ENV (not copied)"
else
  echo "$ME: LLM key: no shared LLM key at $LLM_ENV, the chat checks will report SKIP"
fi
echo "$ME: starting the stack for the check groups: $CHECK_GROUPS (build, iTop install, setup: about 5-10 minutes)"
# Build, ask the checks which services their groups need (SERVICES), start only those (compose adds
# their dependencies) and wait until the one-shot setup has completed. Without LibreChat in the list
# nothing waits for the setup on its own, hence the explicit wait.
rc=0
vm "$IN_STACK && $PREPARE && $DC config --quiet &&
    timeout $START_TIMEOUT sh -c '$DC build --quiet &&
      s=\$($DC ${SERVICES[*]} $CHECK_GROUPS) && echo \"services to start: \$s\" &&
      $DC up -d --quiet-pull \$s && $DC wait $SETUP_SERVICE' > $DIR/start.log 2>&1" || rc=$?
if [ "$rc" -ne 0 ]; then
  [ "$rc" -eq 124 ] && why="did not finish within ${START_TIMEOUT}s" || why="failed (exit $rc)"
  echo "$ME: the stack start $why. Last lines of the start log and of the setup:" >&2
  vm "tail -n 60 $DIR/start.log; $IN_STACK && $DC logs --no-color --tail 40 setup" >&2 || true
  exit 3
fi
echo "$ME: stack is up"
# What runs, and what it costs: the running containers of this run with their RAM, the sum, and the
# VM's available RAM. Only for the record; a failure here does not stop the run.
vm "sed -n 's/^services to start: /$ME: services started for the groups: /p' $DIR/start.log
  ids=\$(docker ps -q --filter label=com.docker.compose.project=$RUN)   # never all of the VM's containers
  [ -z \"\$ids\" ] || docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' \$ids |
    awk '{ v = \$2; u = v; gsub(/[0-9.]/, \"\", u); sub(/[A-Za-z]+\$/, \"\", v)
           mb = (u == \"GiB\") ? v * 1024 : (u == \"KiB\") ? v / 1024 : (u == \"B\") ? v / 1048576 : v
           sum += mb; printf \"$ME:   container %s %.0f MB\\n\", \$1, mb }
         END { printf \"$ME: %d containers running, %.0f MB RAM in all\\n\", NR, sum }'
  awk '/^MemAvailable:/{ printf \"$ME: VM RAM available now: %d MB\\n\", \$2 / 1024 }' /proc/meminfo" || true

# 4. The checks: output straight through, exit code unchanged. A copy goes to a local file for the
# key scan below (PIPESTATUS keeps the checks' code; vm's own exit 255 ends only the subshell).
args=" $CHECK_GROUPS"
[ "$#" -gt 0 ] && args+=" $(printf '%q ' "$@")"
checks_out="$(mktemp)"
# set +e around the pipe: with errexit and pipefail a failing check would end the script here,
# before the key scan; PIPESTATUS is read right after the pipe, before set -e changes it.
set +e
vm "$IN_STACK && $DC ${CHECKS[*]}$args" | tee "$checks_out"
status=${PIPESTATUS[0]}
set -e
echo "$ME: checks exit code $status"
[ "$status" -eq 255 ] && { rm -f "$checks_out"; exit 255; }

# 5. Key scan, on the VM only: every *_KEY value of the shared file (and a 16-character piece of it,
# past the provider prefix) is looked up in the start log, all logs of the stack, the check output
# (sent back from here) and the config of the images tagged :$RUN. Only places are printed, never
# a value. Without the file there is nothing to look for.
rc=0
leaks="$(vm "[ -f $LLM_ENV ] || { echo NOKEY; exit 0; }
  cat > $DIR/checks.out
  ($IN_STACK && $DC logs --no-color) > $DIR/compose.log 2>&1
  imgs=\$($IN_STACK && $DC config --images 2>/dev/null | grep ':$RUN\$')
  [ -z \"\$imgs\" ] || docker image inspect \$imgs > $DIR/images.json 2>/dev/null
  sed -n 's/^[A-Za-z0-9_]*_KEY=//p' $LLM_ENV | tr -d '\\r\"' | while IFS= read -r k; do
    [ \${#k} -ge 8 ] || continue
    p=\$(printf %s \"\$k\" | cut -c10-25); [ \${#p} -ge 8 ] || p=\$k
    for f in start.log compose.log checks.out images.json; do
      [ -f $DIR/\$f ] && grep -qF -e \"\$k\" -e \"\$p\" $DIR/\$f && echo \$f
    done
  done | sort -u | tr '\\n' ' '
  rm -f $DIR/checks.out $DIR/compose.log $DIR/images.json" < "$checks_out")" || rc=$?
rm -f "$checks_out"
[ "$rc" -eq 255 ] && exit 255
if [ "$rc" -ne 0 ]; then
  echo "$ME: the key scan on the VM failed (exit $rc)" >&2
  [ "$status" -eq 0 ] && status=5
elif [ "$leaks" = NOKEY ]; then
  echo "$ME: key scan: no shared LLM key, nothing to look for"
elif [ -n "${leaks// /}" ]; then
  echo "$ME: key scan: an LLM key shows up in: $leaks(on the VM, removed with the run's folder)" >&2
  [ "$status" -eq 0 ] && status=5
else
  echo "$ME: key scan: no LLM key in the start log, the stack's logs, the check output or the images"
fi
exit "$status"
