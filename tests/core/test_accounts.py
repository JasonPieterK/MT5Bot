import core.accounts as accounts


def test_new_account_shape():
    acc = accounts.new_account(1, "Demo", "C:/MT5/terminal64.exe", 12345, "pw", "Broker-Demo")
    assert acc == {"id": 1, "name": "Demo", "path": "C:/MT5/terminal64.exe",
                    "login": 12345, "password": "pw", "server": "Broker-Demo"}
