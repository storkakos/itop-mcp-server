"""TEST ONLY. Menu paths the docs name, e.g. **Administration** → **OAuth connections**. No dependencies, so the
parser can be run without a stack: python3 menupaths.py [docs folder] prints every chain it finds per doc."""
import re
import sys
from pathlib import Path

WORDING_DOCS = ["README.md", "docs/setup/itop-prerequisites.md", "docs/setup/example-keycloak-librechat.md"]
MENU_DOCS = WORDING_DOCS + ["docs/quick-start.md"]

# Only bold or italic segments are menu names; the text after the last one is prose and never part of the chain.
_SEG = r"\*{1,2}([^*\n]+?)\*{1,2}"
_CHAIN = re.compile(rf"\*{{1,2}}Administration\*{{1,2}}((?:\s*→\s*{_SEG})+)")
_ACTIONS = ("New", "the user")  # an action or a record after the menu entries, not a menu entry


def parse_menu_paths(text: str) -> list:
    """Chains starting at 'Administration' as tuples of menu names, cut at the first action."""
    paths = []
    for m in _CHAIN.finditer(text):
        parts = ["Administration"] + [re.sub(r"\s+", " ", s).strip() for s in re.findall(_SEG, m.group(1))]
        for stop in _ACTIONS:
            if stop in parts:
                parts = parts[:parts.index(stop)]
        paths.append(tuple(parts))
    return paths


if __name__ == "__main__":
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    found = 0
    for rel in MENU_DOCS:
        for p in parse_menu_paths((root / rel).read_text(encoding="utf-8")):
            print(f"{rel}: {' → '.join(p)}")
            found += 1
    sys.exit(0 if found else 1)
