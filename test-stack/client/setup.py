"""TEST ONLY. Runs the steps of both manuals on the plain iTop the itop container installed.

Idempotent: a step already done is skipped, so `docker compose up` can run it again.
"""
import os
import shutil
import zipfile
from pathlib import Path

import pymysql
import requests

import config_edits
import keycloak_realm
import wizard
from common import CONFIG, ITOP, ITOP_DB, KC_USERS, LOCAL_USER, SSO, itop_rest, say, wait_for

W = Path("/var/www/itop")
WWW_DATA = 33


def chown_tree(p: Path) -> None:
    for root, dirs, files in os.walk(p):
        for n in dirs + files:
            os.chown(os.path.join(root, n), WWW_DATA, WWW_DATA)
    os.chown(p, WWW_DATA, WWW_DATA)


def main() -> None:
    say("waiting for iTop (download + plain install take a few minutes on the first start)")
    wait_for(f"{ITOP}/pages/UI.php", lambda r: r.status_code in (200, 302) and Path(CONFIG).exists(), what="iTop")
    wait_for(f"{SSO}/realms/master", lambda r: r.status_code == 200, what="Keycloak")

    say("prerequisites, step 2: copy the extensions")
    ext = W / "extensions"
    if not (ext / "altioo-oauth-server" / "README.md").exists():
        zipfile.ZipFile("/downloads/altioo-oauth-server-0.1.0.zip").extractall(ext)
    if not (ext / "combodo-hybridauth" / "module.combodo-hybridauth.php").exists():
        zipfile.ZipFile("/downloads/combodo-hybridauth-2.1.1.zip").extractall(ext)
        shutil.move(str(ext / "combodo-hybridauth-2.1.1"), str(ext / "combodo-hybridauth"))
    chown_tree(ext)
    for p in ("datamodels/2.x/combodo-oauth2-client/module.combodo-oauth2-client.php",
              "datamodels/2.x/itop-attribute-encrypted-password/module.itop-attribute-encrypted-password.php"):
        assert (W / p).exists(), p

    if not (W / "env-production" / "altioo-oauth-server").exists():
        say("prerequisites, steps 3-4: config writable, setup wizard as upgrade")
        os.chmod(CONFIG, 0o640)
        wizard.run_upgrade(["Altioo OAuth Server", "oAuth/OpenID authentication"])

    say("prerequisites, step 5 + Configure iTop; example: iTop log in with Keycloak")
    os.chmod(CONFIG, 0o640)
    s = Path(CONFIG).read_text()
    s = config_edits.apply_hybridauth(config_edits.apply_prerequisites(s))
    Path(CONFIG).write_text(s)
    r = requests.get(f"{ITOP}/pages/UI.php", allow_redirects=False)
    if r.status_code >= 500:  # no php -l in this container: iTop itself must still answer
        raise SystemExit(f"iTop answers {r.status_code} after the config edit")
    os.chmod(CONFIG, 0o440)

    say("test data: admin may use REST (test only), persons and users")
    con = pymysql.connect(**ITOP_DB)
    with con.cursor() as c:
        c.execute("insert into priv_urp_userprofile (userid, profileid, description) "
                  "select u.id, p.id, 'test stack: REST for test data' from priv_user u, priv_urp_profiles p "
                  "where u.login='admin' and p.name='REST Services User' and not exists ("
                  "select 1 from priv_urp_userprofile x where x.userid=u.id and x.profileid=p.id)")
    con.commit()
    con.close()

    def person(first, last, mail):
        if not itop_rest({"operation": "core/get", "class": "Person", "key": f"SELECT Person WHERE email='{mail}'",
                          "output_fields": "id"}).get("objects"):
            itop_rest({"operation": "core/create", "comment": "test stack", "class": "Person", "output_fields": "id",
                       "fields": {"first_name": first, "name": last, "email": mail,
                                  "org_id": "SELECT Organization WHERE name='Demo'"}})

    def user(cls, login, mail, profile, password=None):
        if itop_rest({"operation": "core/get", "class": "User", "key": f"SELECT User WHERE login='{login}'",
                      "output_fields": "id"}).get("objects"):
            return
        fields = {"login": login, "language": "EN US", "contactid": f"SELECT Person WHERE email='{mail}'",
                  "profile_list": [{"profileid": f"SELECT URP_Profiles WHERE name='{profile}'"}]}
        if password:
            fields["password"] = password
        res = itop_rest({"operation": "core/create", "comment": "test stack", "class": cls,
                         "output_fields": "login", "fields": fields})
        if res.get("code") != 0:
            raise SystemExit(f"creating {login}: {res.get('message')}")
        say("   ", cls, login, profile)

    login, pw, first, last, mail, profile = LOCAL_USER
    person(first, last, mail)
    user("UserLocal", login, mail, profile, pw)
    for _u, _pw, first, last, mail, profile in KC_USERS:
        person(first, last, mail)
        user("UserExternal", mail, mail, profile)  # login = the email Keycloak returns

    say("example: Keycloak realm, clients, email lock-down, users")
    keycloak_realm.setup_realm()
    say("setup complete")


if __name__ == "__main__":
    main()
