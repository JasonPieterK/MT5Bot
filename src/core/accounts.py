"""Saved MT5 account profiles for quick switching. A single MT5 terminal process can
only be logged into one account at a time — this is a switch mechanism, not true
simultaneous multi-account trading (which would need one terminal process per account)."""


def new_account(account_id, name, path, login, password, server):
    return {"id": account_id, "name": name, "path": path, "login": login,
            "password": password, "server": server}
