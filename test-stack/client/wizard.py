"""TEST ONLY. Drives iTop's setup wizard like a browser: an upgrade that ticks the given extensions.

Extensions are picked by their extension code, never by the label the wizard shows: an extension's label can
differ from its module's label (e.g. "OpenID Authentication" vs "oAuth/OpenID authentication"). The wizard
gives each extension checkbox the extension code as its id (with a data-id fallback); the label is display only.
"""
import json
import re

from bs4 import BeautifulSoup

from common import ITOP, ITOP_ADMIN, browser, form_data, say


def _choice_code(box) -> str:
    """The extension code of a wizard checkbox: its id, or the data-id of the choice it sits in."""
    holder = box if box.has_attr("data-id") else box.find_parent(attrs={"data-id": True})
    return holder["data-id"] if holder is not None else box.get("id", "")


def run_upgrade(codes: list[str]) -> None:
    """Run the setup wizard as an upgrade and tick the extensions with the given extension codes."""
    b = browser()
    r = b.get(f"{ITOP}/setup/")
    if BeautifulSoup(r.text, "lxml").find("input", attrs={"name": "auth_user"}):
        b.post(r.url, data={"auth_user": ITOP_ADMIN[0], "auth_pwd": ITOP_ADMIN[1], "loginop": "login"})
    r = b.get(f"{ITOP}/setup/wizard.php")
    found: set[str] = set()
    offered: dict[str, str] = {}
    for _ in range(30):
        soup = BeautifulSoup(r.text, "lxml")
        cls_el = soup.find("input", id="_class")
        if cls_el is None:
            raise SystemExit("setup wizard stopped: " + re.sub(r"\s+", " ", soup.get_text(" "))[:800])
        cls = cls_el["value"]
        form = soup.find("form", id="wiz_form")
        d = form_data(form)
        say("   wizard:", cls)
        if cls == "WizStepInstallOrUpgrade":
            d["install_mode"] = "upgrade"
        if cls in ("WizStepLicense", "WizStepLicense2"):
            d["accept_license"] = "yes"
        if cls == "WizStepModulesChoice":
            for box in form.find_all("input", attrs={"type": "checkbox"}):
                code = _choice_code(box)
                lab = form.find("label", attrs={"for": box.get("id")}) if box.get("id") else None
                label = lab.get_text(" ", strip=True) if lab else ""
                offered[code] = label
                if code in codes:
                    found.add(code)
                    if box.has_attr("name"):
                        d[box["name"]] = box.get("value", "on")
                        say("     ticked:", code, f"({label})" if label else "")
                    else:  # an installed extension: ticked and locked, nothing to submit
                        say("     already installed:", code, f"({label})" if label else "")
        if cls == "WizStepSummary":
            missing = [c for c in codes if c not in found]
            if missing:
                raise SystemExit(
                    "setup wizard: extension code(s) not offered by the wizard: " + ", ".join(missing)
                    + "; offered: " + ", ".join(f"{c} ({l})" for c, l in offered.items()))
            params = soup.find("input", id="installer_parameters")["value"]
            say("     modules:", ", ".join(json.loads(params)["selected_modules"][-8:]), "...")
            authent = soup.find("input", id="authent_token")["value"]
            step = ""
            while True:
                rr = b.post(f"{ITOP}/setup/ajax.dataloader.php", data={
                    "operation": "async_action", "step_class": cls, "step_state": d.get("_state", ""),
                    "code": "execute_step", "authent": authent,
                    "params[installer_step]": step, "params[installer_config]": params})
                m = re.search(r"ExecuteStep\('([^']*)'\)", rr.text)
                if m:
                    step = m.group(1)
                    say("     step:", step)
                    continue
                if 'installation_status", "completed' in rr.text:
                    break
                raise SystemExit("setup wizard failed: " + re.sub(r"\s+", " ", BeautifulSoup(rr.text, "lxml").get_text(" "))[:1500])
        if cls == "WizStepDone":
            return
        r = b.post(f"{ITOP}/setup/wizard.php", data=list(d.items()) + [("operation", "next")])
    raise SystemExit("setup wizard: too many steps")
