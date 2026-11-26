#!/usr/bin/env bash
# Run pytest on the test VM, never locally. Copies the current working tree (tracked and untracked
# files, not git-ignored ones, so uncommitted changes come along) to a folder of its own on the VM,
# runs the suite there in a throwaway python container with the locked dependencies, prints the
# result here, removes the folder and container again (also on failure or Ctrl-C) and exits with
# pytest's exit code. See docs/agents/test-vm.md.
#
#   bash scripts/test-on-vm.sh                          # whole suite
#   bash scripts/test-on-vm.sh tests/test_config.py -x  # arguments go to pytest
#
# Environment:
#   RUN           name of this run: lowercase letters, digits, - (default: dev-<random>).
#                 Used for the VM folder /root/itop-mcp-server-$RUN and the container $RUN-pytest.
#   VM_HOST       default root@192.168.178.25
#   VM_KEY        default ~/.ssh/itop-mcp-test-vm
#   VM_KNOWN_HOSTS default ~/.ssh/itop-mcp-test-vm.known_hosts
#   PYTHON_IMAGE  default: the FROM image of the Dockerfile, else python:3.13-slim
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RUN="${RUN:-dev-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')}"
if ! [[ "$RUN" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
  echo "test-on-vm: RUN must be lowercase letters, digits and - (got '$RUN')" >&2
  exit 2
fi
DIR="/root/itop-mcp-server-$RUN"
CONTAINER="$RUN-pytest"

if [ -z "${PYTHON_IMAGE:-}" ] && [ -f Dockerfile ]; then
  PYTHON_IMAGE="$(sed -n 's/^FROM[[:space:]]\{1,\}\(python:[^[:space:]]*\).*/\1/p' Dockerfile | head -n1)"
fi
PYTHON_IMAGE="${PYTHON_IMAGE:-python:3.13-slim}"

SSH=(ssh -i "${VM_KEY:-$HOME/.ssh/itop-mcp-test-vm}"
  -o "UserKnownHostsFile=${VM_KNOWN_HOSTS:-$HOME/.ssh/itop-mcp-test-vm.known_hosts}"
  -o BatchMode=yes -o ConnectTimeout=10 "${VM_HOST:-root@192.168.178.25}")

cleanup() {
  "${SSH[@]}" "docker rm -f $CONTAINER >/dev/null 2>&1; rm -rf $DIR" || \
    echo "test-on-vm: cleanup failed, remove $DIR and container $CONTAINER on the VM by hand" >&2
}

echo "test-on-vm: run $RUN, folder $DIR, image $PYTHON_IMAGE"
# ssh exits 255 when it cannot connect or log in; only exit 1 comes from the remote test itself.
check=0
"${SSH[@]}" "test ! -e $DIR" || check=$?
if [ "$check" -eq 255 ]; then
  echo "test-on-vm: cannot reach the VM over SSH (${VM_HOST:-root@192.168.178.25}), see the ssh error above" >&2
  exit 255
elif [ "$check" -ne 0 ]; then
  echo "test-on-vm: $DIR already exists on the VM (another run with RUN=$RUN?), pick another RUN" >&2
  exit 2
fi
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

git ls-files -z --cached --others --exclude-standard | tar --null -T - -cf - \
  | "${SSH[@]}" "mkdir $DIR && tar -xf - -C $DIR"

# Our own -q only when the caller passes none: pytest counts -q, and -qq drops the summary line.
quiet=-q
for arg in "$@"; do
  case "$arg" in
    -q|--quiet) quiet= ;;
    -[a-z]*q*) ;;
  esac
done

# The folder is mounted read-only and copied inside the container, so the install leaves nothing
# behind in it; --rm removes the container. pytest arguments travel as positional parameters.
inner='cp -r /src /work && cd /work &&
  export PIP_ROOT_USER_ACTION=ignore PIP_DISABLE_PIP_VERSION_CHECK=1 &&
  pip install -q --no-deps -r requirements.lock -r requirements-build.lock -r requirements-test.lock &&
  pip install -q --no-deps --no-build-isolation -e . &&
  exec pytest '"$quiet"' "$@"'
remote="docker run --rm --name $CONTAINER -v $DIR:/src:ro $PYTHON_IMAGE sh -c $(printf '%q' "$inner") sh"
if [ "$#" -gt 0 ]; then
  remote+=" $(printf '%q ' "$@")"
fi

status=0
"${SSH[@]}" "$remote" || status=$?
echo "test-on-vm: pytest exit code $status"
exit "$status"
