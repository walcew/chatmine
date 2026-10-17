from pathlib import Path

from chatmine.secrets import ChromiumVault, build_query

VAULT = ChromiumVault(
    keychain_service="Some Safe Storage",
    cookie_names=("authtoken", "skypetoken_asm"),
    host_filters=("%teams.microsoft.com%", "%asm.skype.com"),
    cookie_dbs=lambda profile: [Path("/tmp/Cookies")],
    local_state=lambda: Path("/tmp/Local State"),
)


def test_build_query_param_order_and_counts():
    sql, params = build_query(VAULT)
    # host filters primeiro, depois os nomes de cookie, na ordem do vault.
    assert params == [
        "%teams.microsoft.com%",
        "%asm.skype.com",
        "authtoken",
        "skypetoken_asm",
    ]
    assert sql.count("host_key LIKE ?") == 2
    assert sql.count("?") == 4  # 2 hosts + 2 nomes
    assert "name IN (?,?)" in sql
    assert "ORDER BY last_access_utc DESC" in sql
