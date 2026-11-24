"""Builds the installable ZIP of the iTop extension mcp-token-info, byte for byte reproducible.

    python itop-extension/build.py            # writes itop-extension/dist/mcp-token-info-<version>.zip
    python itop-extension/build.py --out DIR  # writes the ZIP into DIR

Only the standard library. The same sources give the same ZIP on every machine: entries sorted, fixed
timestamp and permissions, LF line endings (also from a Windows checkout), fixed compression level.
Prints the ZIP's path and SHA256.
"""
import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CODE = "mcp-token-info"
SRC = HERE / CODE
# 1980-01-01, the earliest time a ZIP entry can hold: no build date in the archive.
EPOCH = (1980, 1, 1, 0, 0, 0)
TEXT = {".php", ".xml", ".md", ".txt", ""}


def version() -> str:
    """The version from extension.xml, after checking module.<code>.php states the same one."""
    ext = re.search(r"<version>([^<]+)</version>", (SRC / "extension.xml").read_text(encoding="utf-8"))
    mod = re.search(rf"'{re.escape(CODE)}/([^']+)'", (SRC / f"module.{CODE}.php").read_text(encoding="utf-8"))
    if not ext or not mod:
        raise SystemExit("no version in extension.xml or the module file")
    if ext.group(1) != mod.group(1):
        raise SystemExit(f"version mismatch: extension.xml {ext.group(1)}, module file {mod.group(1)}")
    return ext.group(1)


def files() -> list[Path]:
    return sorted((p for p in SRC.rglob("*") if p.is_file()), key=lambda p: p.relative_to(SRC).as_posix())


def build(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{CODE}-{version()}.zip"
    with zipfile.ZipFile(target, "w") as z:
        for p in files():
            data = p.read_bytes()
            if p.suffix in TEXT:
                data = data.replace(b"\r\n", b"\n")
            info = zipfile.ZipInfo(f"{CODE}/{p.relative_to(SRC).as_posix()}", date_time=EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3  # Unix, so the permissions below count
            info.external_attr = (0o100644 & 0xFFFF) << 16
            z.writestr(info, data, compresslevel=9)
    return target


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=HERE / "dist", help="output folder (default: itop-extension/dist)")
    target = build(ap.parse_args(argv).out)
    print(target)
    print("sha256", hashlib.sha256(target.read_bytes()).hexdigest())


if __name__ == "__main__":
    main(sys.argv[1:])
