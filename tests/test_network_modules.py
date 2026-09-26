"""Only the modules the website's /privacy names may reach the network.
A new one fails here: update ../previously-on-web's /privacy first (what it
sends, to whom), then add the module below and to CLAUDE.md."""

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src/previously_on"

NETWORK = {"urllib.request", "http.client", "socket", "ssl", "httpx", "requests", "urllib3", "aiohttp",
           "websocket", "websockets", "smtplib", "ftplib", "anthropic", "openai"}

ALLOWED = {
    "recap/provider.py",  # the recap model's API (Anthropic or OpenAI), with the player's key
    "app/account.py",     # the account and sync API; app/sync.py calls through account.request
    "app/instance.py",    # localhost only: the second copy asks the first to show itself
}


def network_imports(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            # `from urllib import request` imports urllib.request.
            names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
        else:
            continue
        found |= {n for n in names if n in NETWORK or n.split(".")[0] in NETWORK - {"urllib", "http"}}
    return found


def test_only_the_modules_privacy_names_import_a_network_library():
    offenders = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = path.relative_to(PACKAGE).as_posix()
        if rel not in ALLOWED and (found := network_imports(path)):
            offenders[rel] = sorted(found)
    assert not offenders, (
        f"{offenders} import a network library. Update the website's /privacy first "
        "(../previously-on-web, src/pages/privacy.astro), then add the module to ALLOWED here and to CLAUDE.md."
    )


def test_the_allowed_modules_exist():
    assert all((PACKAGE / m).is_file() for m in ALLOWED)
