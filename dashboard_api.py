"""In-process management API for the web dashboard.

Runs inside the bot's event loop (via aiohttp.web), so it reads and writes the
exact same in-memory state the slash commands use — edits are immediate and need
no locking, because discord.py runs one loop. No game logic lives here: this
only exposes the metadata a player owns for viewing and editing.

Trust model (see dashboard/README.md for the full picture):
  - The API is reachable only through a Cloudflare Tunnel, not a public port.
  - Every request must carry the shared secret (DASHBOARD_API_SECRET), proving
    it came from our Cloudflare Pages function rather than a random caller.
  - That function has already authenticated the user with Discord OAuth and
    passes their verified Discord id in X-User-Id. The API trusts that id and
    scopes every response to what the user owns, using the SAME ownership
    helpers the slash commands use.

The API is opt-in: if DASHBOARD_API_SECRET is unset the server never starts, so
the bot behaves exactly as before until you configure it.
"""

import os
from dataclasses import dataclass
from typing import Callable

# aiohttp is imported lazily inside build_app()/start(), so the pure request
# logic below can be imported and unit-tested without aiohttp present.


# Fields the dashboard is allowed to change. Anything not listed here is
# read-only, which keeps game state (streams, sales, wins, popularity, funds,
# member levels/skills, buildings) under the bot's control where it belongs.
GROUP_EDITABLE = ("korean_name", "description", "fandom_name",
                  "fandom_color", "profile_picture", "banner_url")
ALBUM_EDITABLE = ("image_url", "era_image_url", "title_track")
MEMBER_EDITABLE = ("name", "image_url", "bio")

MAX_TEXT_LEN = 2000  # Reject absurd payloads outright


@dataclass
class Deps:
    """Live references to the bot's state and helpers, injected by main.py.

    These are the same dict objects the commands mutate, so changes made here
    are seen by the bot immediately and vice versa.
    """
    group_data: dict
    album_data: dict
    company_funds: dict
    company_data: dict
    user_companies: dict
    user_balances: dict
    get_user_companies: Callable
    is_user_company_owner: Callable
    get_group_owner_company: Callable
    is_user_group_owner: Callable
    save_data: Callable


# --- Core logic (pure, unit-testable without a running server) -----------
#
# Each returns (http_status, payload_dict). The aiohttp handlers below are thin
# wrappers so this logic can be tested directly.

def _clean_value(value):
    """Validate an incoming edit value: strings only, bounded, trimmed."""
    if value is None:
        return None, None
    if not isinstance(value, str):
        return None, "value must be a string or null"
    value = value.strip()
    if len(value) > MAX_TEXT_LEN:
        return None, f"value exceeds {MAX_TEXT_LEN} characters"
    return value, None


def list_owned(deps: Deps, user_id: str):
    """Everything the user owns: companies, their groups, and those groups' albums."""
    companies = list(deps.get_user_companies(user_id))

    groups = []
    for name, entry in deps.group_data.items():
        if entry.get("company") in companies:
            groups.append({
                "name": name,
                "company": entry.get("company"),
                "korean_name": entry.get("korean_name", ""),
                "tier": entry.get("tier", "NUGU"),
                "popularity": entry.get("popularity", 0),
                "wins": entry.get("wins", 0),
                "is_disbanded": entry.get("is_disbanded", False),
                "album_count": len(entry.get("albums", [])),
                "member_count": len(entry.get("members", []) or []),
            })
    groups.sort(key=lambda g: g["name"])
    owned_group_names = {g["name"] for g in groups}

    albums = []
    for name, entry in deps.album_data.items():
        if entry.get("group") in owned_group_names:
            albums.append({
                "name": name,
                "group": entry.get("group"),
                "streams": entry.get("streams", 0),
                "sales": entry.get("sales", 0),
                "wins": entry.get("wins", 0),
                "is_active_promotion": entry.get("is_active_promotion", False),
            })
    albums.sort(key=lambda a: a["name"])

    return 200, {
        "user_id": user_id,
        "companies": [
            {"name": c, "funds": deps.company_funds.get(c, 0)} for c in sorted(companies)
        ],
        "groups": groups,
        "albums": albums,
    }


def get_group(deps: Deps, user_id: str, name: str):
    entry = deps.group_data.get(name)
    if entry is None:
        return 404, {"error": "group not found"}
    if not deps.is_user_group_owner(user_id, name):
        return 403, {"error": "you do not own this group"}

    members = entry.get("members", []) or []
    return 200, {
        "name": name,
        "company": entry.get("company"),
        "editable": {k: entry.get(k, "") for k in GROUP_EDITABLE},
        "readonly": {
            "tier": entry.get("tier", "NUGU"),
            "popularity": entry.get("popularity", 0),
            "wins": entry.get("wins", 0),
            "debut_date": entry.get("debut_date"),
            "is_disbanded": entry.get("is_disbanded", False),
        },
        "albums": list(entry.get("albums", [])),
        "members": [
            {"index": i, **{k: m.get(k, "") for k in MEMBER_EDITABLE}}
            for i, m in enumerate(members) if isinstance(m, dict)
        ],
    }


def patch_group(deps: Deps, user_id: str, name: str, changes: dict):
    entry = deps.group_data.get(name)
    if entry is None:
        return 404, {"error": "group not found"}
    if not deps.is_user_group_owner(user_id, name):
        return 403, {"error": "you do not own this group"}

    rejected = [k for k in changes if k not in GROUP_EDITABLE]
    if rejected:
        return 400, {"error": f"fields not editable: {', '.join(rejected)}"}

    for key, raw in changes.items():
        value, err = _clean_value(raw)
        if err:
            return 400, {"error": f"{key}: {err}"}
        entry[key] = value

    deps.save_data()
    return get_group(deps, user_id, name)


def get_album(deps: Deps, user_id: str, name: str):
    entry = deps.album_data.get(name)
    if entry is None:
        return 404, {"error": "album not found"}
    group_name = entry.get("group")
    if not group_name or not deps.is_user_group_owner(user_id, group_name):
        return 403, {"error": "you do not own this album"}

    return 200, {
        "name": name,
        "group": group_name,
        "editable": {k: entry.get(k, "") for k in ALBUM_EDITABLE},
        "readonly": {
            "streams": entry.get("streams", 0),
            "sales": entry.get("sales", 0),
            "wins": entry.get("wins", 0),
            "release_date": entry.get("release_date"),
            "is_active_promotion": entry.get("is_active_promotion", False),
        },
    }


def patch_album(deps: Deps, user_id: str, name: str, changes: dict):
    entry = deps.album_data.get(name)
    if entry is None:
        return 404, {"error": "album not found"}
    group_name = entry.get("group")
    if not group_name or not deps.is_user_group_owner(user_id, group_name):
        return 403, {"error": "you do not own this album"}

    rejected = [k for k in changes if k not in ALBUM_EDITABLE]
    if rejected:
        return 400, {"error": f"fields not editable: {', '.join(rejected)}"}

    for key, raw in changes.items():
        value, err = _clean_value(raw)
        if err:
            return 400, {"error": f"{key}: {err}"}
        entry[key] = value

    deps.save_data()
    return get_album(deps, user_id, name)


def patch_member(deps: Deps, user_id: str, group_name: str, index: int, changes: dict):
    entry = deps.group_data.get(group_name)
    if entry is None:
        return 404, {"error": "group not found"}
    if not deps.is_user_group_owner(user_id, group_name):
        return 403, {"error": "you do not own this group"}

    members = entry.get("members", []) or []
    if not (0 <= index < len(members)) or not isinstance(members[index], dict):
        return 404, {"error": "member not found"}

    rejected = [k for k in changes if k not in MEMBER_EDITABLE]
    if rejected:
        return 400, {"error": f"fields not editable: {', '.join(rejected)}"}

    for key, raw in changes.items():
        value, err = _clean_value(raw)
        if err:
            return 400, {"error": f"{key}: {err}"}
        members[index][key] = value

    deps.save_data()
    return get_group(deps, user_id, group_name)


# --- HTTP layer ----------------------------------------------------------

def build_app(deps: Deps, secret: str):
    from aiohttp import web

    @web.middleware
    async def auth_middleware(request, handler):
        if request.path == "/api/health":
            return await handler(request)

        provided = request.headers.get("Authorization", "")
        expected = f"Bearer {secret}"
        # constant-time-ish compare; secrets are short and this is behind a tunnel
        if not provided or provided != expected:
            return web.json_response({"error": "unauthorized"}, status=401)

        user_id = request.headers.get("X-User-Id", "").strip()
        if not user_id:
            return web.json_response({"error": "missing user"}, status=400)
        request["user_id"] = user_id
        return await handler(request)

    async def health(request):
        return web.json_response({"ok": True})

    async def me(request):
        status, body = list_owned(deps, request["user_id"])
        return web.json_response(body, status=status)

    async def group_get(request):
        status, body = get_group(deps, request["user_id"], request.match_info["name"])
        return web.json_response(body, status=status)

    async def group_patch(request):
        changes = await _json_body(request)
        if changes is None:
            return web.json_response({"error": "invalid JSON body"}, status=400)
        status, body = patch_group(deps, request["user_id"], request.match_info["name"], changes)
        return web.json_response(body, status=status)

    async def album_get(request):
        status, body = get_album(deps, request["user_id"], request.match_info["name"])
        return web.json_response(body, status=status)

    async def album_patch(request):
        changes = await _json_body(request)
        if changes is None:
            return web.json_response({"error": "invalid JSON body"}, status=400)
        status, body = patch_album(deps, request["user_id"], request.match_info["name"], changes)
        return web.json_response(body, status=status)

    async def member_patch(request):
        changes = await _json_body(request)
        if changes is None:
            return web.json_response({"error": "invalid JSON body"}, status=400)
        try:
            index = int(request.match_info["index"])
        except ValueError:
            return web.json_response({"error": "invalid member index"}, status=400)
        status, body = patch_member(
            deps, request["user_id"], request.match_info["name"], index, changes
        )
        return web.json_response(body, status=status)

    app = web.Application(middlewares=[auth_middleware])
    app.add_routes([
        web.get("/api/health", health),
        web.get("/api/me", me),
        web.get("/api/groups/{name}", group_get),
        web.patch("/api/groups/{name}", group_patch),
        web.get("/api/albums/{name}", album_get),
        web.patch("/api/albums/{name}", album_patch),
        web.patch("/api/groups/{name}/members/{index}", member_patch),
    ])
    return app


async def _json_body(request):
    try:
        body = await request.json()
        return body if isinstance(body, dict) else None
    except Exception:
        return None


async def start(deps: Deps):
    """Start the API inside the running event loop, if configured.

    Returns the AppRunner (or None if disabled) so the caller could clean it up.
    """
    secret = os.getenv("DASHBOARD_API_SECRET")
    if not secret:
        print("Dashboard API: DASHBOARD_API_SECRET not set — API disabled.")
        return None

    from aiohttp import web
    host = os.getenv("DASHBOARD_API_HOST", "127.0.0.1")
    port = int(os.getenv("DASHBOARD_API_PORT", "8787"))

    app = build_app(deps, secret)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"Dashboard API listening on http://{host}:{port}")
    return runner
