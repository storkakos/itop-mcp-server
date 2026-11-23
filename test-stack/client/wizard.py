"""TEST ONLY. Drives iTop's setup wizard like a browser: an upgrade that ticks the given extensions."""
import json
import re

from bs4 import BeautifulSoup

from common import ITOP, ITOP_ADMIN, browser, form_data, say


def run_upgrade(ticks: list[str]) -> None:
    b = browser()
    r = b.get(f"{ITOP}/setup/")
    if BeautifulSoup(r.text, "lxml").find("input", attrs={"name": "auth_user"}):
        b.post(r.url, data={"auth_user": ITOP_ADMIN[0], "auth_pwd": ITOP_ADMIN[1], "loginop": "login"})
    r = b.get(f"{ITOP}/setup/wizard.php")
    found = set()
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
                lab = form.find("label", attrs={"for": box.get("id")})
                label = lab.get_text(" ", strip=True) if lab else ""
                if label in ticks:
                    d[box["name"]] = box.get("value", "on")
                    found.add(label)
                    say("     ticked:", label)
        if cls == "WizStepSummary":
            if set(ticks) - found:
                raise SystemExit(f"setup wizard: checkbox not found: {set(ticks) - found}")
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
