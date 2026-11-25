"""The iTop extension mcp-token-info: its ZIP build is reproducible and ships what iTop's setup needs.

The PHP itself runs only inside iTop; it is checked with curl on the test stack (ticket dolibarr-parity 06).
"""
import hashlib
import importlib.util
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "itop-extension"


def _build_module():
    spec = importlib.util.spec_from_file_location("itop_extension_build", EXT / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_zip_is_byte_for_byte_reproducible(tmp_path):
    build = _build_module()
    a = build.build(tmp_path / "a")
    b = build.build(tmp_path / "b")
    assert a.name == b.name == f"mcp-token-info-{build.version()}.zip"
    assert hashlib.sha256(a.read_bytes()).digest() == hashlib.sha256(b.read_bytes()).digest()


def test_zip_unpacks_into_the_extension_folder_with_lf_and_fixed_metadata(tmp_path):
    build = _build_module()
    with zipfile.ZipFile(build.build(tmp_path)) as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        assert names == sorted(names)
        assert set(names) >= {
            "mcp-token-info/extension.xml",
            "mcp-token-info/module.mcp-token-info.php",
            "mcp-token-info/main.mcp-token-info.php",
            "mcp-token-info/README.md",
            "mcp-token-info/LICENSE",
        }
        for i in infos:
            assert i.date_time == (1980, 1, 1, 0, 0, 0), i.filename
            assert (i.external_attr >> 16) == 0o100644, i.filename
            assert b"\r\n" not in z.read(i), i.filename


def test_versions_agree():
    build = _build_module()
    v = build.version()
    main = (EXT / "mcp-token-info" / "main.mcp-token-info.php").read_text(encoding="utf-8")
    assert re.search(rf"const VERSION = '{re.escape(v)}';", main)


def test_module_loads_the_rest_provider_file_and_offers_the_verb():
    d = EXT / "mcp-token-info"
    module = (d / "module.mcp-token-info.php").read_text(encoding="utf-8")
    assert "'main.mcp-token-info.php'" in module  # included on every page, so rest.php sees the class
    main = (d / "main.mcp-token-info.php").read_text(encoding="utf-8")
    assert "implements iRestServiceProvider" in main
    assert "const VERB = 'mcp/token_info';" in main
    assert "<extension_code>mcp-token-info</extension_code>" in (d / "extension.xml").read_text(encoding="utf-8")
