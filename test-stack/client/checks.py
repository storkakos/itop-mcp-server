"""TEST ONLY. Runs the check lists of docs/setup/itop-prerequisites.md and docs/setup/example-keycloak-librechat.md
against the test stack and reports each check as PASS, FAIL or SKIP. Exit code 1 if any check failed.

The checks live in check groups, one file per group in groups/ (see checklib.py and README.md):

    docker compose run --rm client python checks.py                       # every group
    docker compose run --rm client python checks.py prerequisites proxy   # only these groups
    docker compose run --rm client python checks.py --list                # the groups and their checks
    docker compose run --rm --no-deps client python checks.py --services prerequisites
        # prints the compose services to start for these groups (here: setup), for "up -d"

-v prints the traceback of a failed check. Exit code 2: an unknown group name.
"""
import argparse
import importlib
import pkgutil
import sys

import groups

# Every run needs the one-shot setup and what it depends on (proxy, iTop, Keycloak, MCP server, Mailpit).
BASE_SERVICES = ["setup"]


def all_groups() -> list:
    found = [importlib.import_module(f"groups.{m.name}").group for m in pkgutil.iter_modules(groups.__path__)]
    return sorted(found, key=lambda g: g.order)


def main() -> int:
    p = argparse.ArgumentParser(description="Check lists of the test stack.")
    p.add_argument("groups", nargs="*", metavar="GROUP", help="groups to run (default: all)")
    p.add_argument("-v", action="store_true", help="traceback of a failed check")
    p.add_argument("--list", action="store_true", help="list the groups and their checks")
    p.add_argument("--services", action="store_true", help="print the compose services the groups need")
    a = p.parse_args()

    known = all_groups()
    names = [g.name for g in known]
    wanted = [x for arg in a.groups for x in arg.replace(",", " ").split()]
    if not wanted or "all" in wanted:
        wanted = names
    unknown = [x for x in wanted if x not in names]
    if unknown:
        print(f"unknown check group: {' '.join(unknown)} (groups: {' '.join(names)}, or all)", file=sys.stderr)
        return 2
    chosen = [g for g in known if g.name in wanted]

    if a.services:
        services = list(BASE_SERVICES)
        for g in chosen:
            services += [s for s in g.services if s not in services]
        print(" ".join(services))
        return 0
    if a.list:
        for g in chosen:
            needs = f", needs {' '.join(g.services)}" if g.services else ""
            print(f"{g.name}: {g.title} ({len(g.checks)} checks{needs})")
            for name, _ in g.checks:
                print(f"    {name}")
        return 0

    results: list = []
    for g in chosen:
        g.run(results)
    failed = [r for r in results if r[0] == "FAIL"]
    print(f"\n{sum(r[0] == 'PASS' for r in results)} passed, {len(failed)} failed, "
          f"{sum(r[0] == 'SKIP' for r in results)} skipped"
          + ("" if len(chosen) == len(known) else f" (groups: {' '.join(g.name for g in chosen)})"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
