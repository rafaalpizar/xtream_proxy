#!/usr/bin/env python3
import os
import time
import requests
import configparser
from flask import Flask, request, jsonify

# --- Configuration loading ---
config = configparser.ConfigParser(allow_no_value=True)
config.optionxform = str  # preserve case, don't lowercase keys
config.read("xtream_proxy.conf")

EXTERNAL_SERVER = config.get("xtream-remote", "server", fallback="http://remote-server:8080")
USERNAME = config.get("xtream-remote", "user", fallback="user")
PASSWORD = config.get("xtream-remote", "pass", fallback="pass")

def read_list_section(section_name):
    """Read a section as a list of values (one per line)."""
    if not config.has_section(section_name):
        return set()
    return {item.strip() for item in config.options(section_name) if item.strip()}

WHITELIST = read_list_section("whitelist")
BLACKLIST = read_list_section("blacklist")

# Cache storage
CACHE = {}
LAST_REFRESH = 0
REFRESH_INTERVAL = 24 * 3600  # once per day

app = Flask(__name__)

def fetch_external(action=None, extra_params=None):
    """Fetch data from external Xtream Codes server."""
    headers = {"User-Agent": "okhttp/3.14.17"}
    params = {"username": USERNAME, "password": PASSWORD}
    if action:
        params["action"] = action
    if extra_params:
        params.update(extra_params)
    resp = requests.get(f"{EXTERNAL_SERVER}/player_api.php", headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()

def filter_streams(streams):
    """Filter streams by unified whitelist/blacklist."""
    filtered = []
    for s in streams:
        name = str(s.get("name", "")).strip()
        category = str(s.get("category_name", "")).strip()

        if WHITELIST and name not in WHITELIST and category not in WHITELIST:
            continue
        if name in BLACKLIST or category in BLACKLIST:
            continue

        filtered.append(s)
    return filtered

def filter_categories(categories):
    """Filter categories by unified whitelist/blacklist."""
    filtered = []
    for c in categories:
        cname = str(c.get("category_name", "")).strip()

        if WHITELIST and cname not in WHITELIST:
            continue
        if cname in BLACKLIST:
            continue

        filtered.append(c)
    return filtered

def refresh_cache():
    """Refresh cache once per day."""
    global LAST_REFRESH, CACHE
    now = time.time()
    if now - LAST_REFRESH < REFRESH_INTERVAL:
        return

    CACHE["server_info"] = fetch_external()

    CACHE["get_live_categories"] = filter_categories(fetch_external("get_live_categories"))
    CACHE["get_vod_categories"] = filter_categories(fetch_external("get_vod_categories"))
    CACHE["get_series_categories"] = filter_categories(fetch_external("get_series_categories"))

    CACHE["get_live_streams"] = filter_streams(fetch_external("get_live_streams"))
    CACHE["get_vod_streams"] = filter_streams(fetch_external("get_vod_streams"))
    CACHE["get_series"] = filter_streams(fetch_external("get_series"))

    LAST_REFRESH = now

@app.route("/player_api.php")
def local_api():
    """Proxy API with filtering and caching."""
    refresh_cache()

    action = request.args.get("action", None)
    if action == "get_series_info":
        series_id = request.args.get("series_id")
        data = fetch_external("get_series_info", {"series_id": series_id})
        return jsonify(data)

    if not action:
        return jsonify(CACHE.get("server_info", {}))

    return jsonify(CACHE.get(action, []))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
