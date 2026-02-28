#!/usr/bin/env python3
import os
import time
import requests
import configparser
import logging
from flask import Flask, request, jsonify, redirect

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()

# --- Configuration loading ---
config = configparser.ConfigParser(allow_no_value=True)
#config.optionxform = str  # preserve case, don't lowercase keys
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
WHITELIST_CATEGORY = read_list_section("whitelist-category")

# used to add categories
whitelist_category_updated = [x for x in WHITELIST_CATEGORY]

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
    else:
        action = "server_info"  # for logging purposes
    if extra_params:
        params.update(extra_params)
    logger.info("Downloading action: %s", action)
    resp = requests.get(f"{EXTERNAL_SERVER}/player_api.php", headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()

def filter_streams(streams):
    """Filter streams by unified whitelist/blacklist."""
    global whitelist_category_updated
    add_count = 0
    remove_count = 0
    filtered = []
    for s in streams:
        name = str(s.get("name", "\0")).strip().lower()
        category_id = s.get("category_id", "\0")
        #logger.debug("Filtering name: %s", name)

        # count the number of whitelist items that are found inside a stream name
        # if that count is > 0, this is a whitelisted stream
        match_list = [n for n in WHITELIST if n in name]
        good_stream = len(match_list) > 0 or category_id in WHITELIST_CATEGORY
        # same but for blacklist, this case more than 0 means it is blacklisted
        match_list = [n for n in BLACKLIST if n in name]
        bad_stream = len(match_list) > 0

        if not good_stream or bad_stream:
            remove_count += 1
            continue

        category_id = s.get("category_id")
        
        logger.debug("Added name: %s", name)
        add_count += 1
        # add stream to good list
        filtered.append(s)
        # add category is to good list
        whitelist_category_updated.append(category_id)
    logger.info("Filter done. Added:%d Removed:%d", add_count, remove_count)
    return filtered

def filter_categories(categories):
    """Filter categories by unified whitelist/blacklist."""
    add_count = 0
    remove_count = 0
    filtered = []
    for c in categories:
        category_id = c.get("category_id", "\0")

        if whitelist_category_updated and category_id not in whitelist_category_updated:
            remove_count += 1
            continue

        add_count += 1
        filtered.append(c)
    logger.info("Filter done. Added:%d Removed:%d", add_count, remove_count)
    return filtered

def refresh_cache():
    """Refresh cache once per day."""
    global LAST_REFRESH, CACHE
    now = time.time()
    if now - LAST_REFRESH < REFRESH_INTERVAL:
        return

    CACHE["server_info"] = fetch_external()
    # override some server info
    try:
        CACHE["server_info"]["user_info"]["username"] = "-"
        CACHE["server_info"]["user_info"]["password"] = "-"
        CACHE["server_info"]["server_info"]["url"] = "-"
    except:
        logger.error("Server information from external is malformed")

    # Streams must be loaded first in order to update: whitelist_category_updated
    CACHE["get_live_streams"] = filter_streams(fetch_external("get_live_streams"))
    CACHE["get_series"] = filter_streams(fetch_external("get_series"))
    CACHE["get_vod_streams"] = filter_streams(fetch_external("get_vod_streams"))
    # Fetch categories and filter based on allowed streams
    CACHE["get_live_categories"] = filter_categories(fetch_external("get_live_categories"))
    CACHE["get_series_categories"] = filter_categories(fetch_external("get_series_categories"))
    CACHE["get_vod_categories"] = filter_categories(fetch_external("get_vod_categories"))

    LAST_REFRESH = now

    logger.info("Whitelist Category (Updated): %s", WHITELIST_CATEGORY)

@app.route("/player_api.php")
def local_api():
    """Proxy API with filtering and caching."""
    refresh_cache()

    action = request.args.get("action")

    # series info cannot be cacheable because depends on series_id parameter
    if action == "get_series_info":
        series_id = request.args.get("series_id")
        data = fetch_external("get_series_info", {"series_id": series_id})
        return jsonify(data)

    # vod info
    if action == "get_vod_info":
        vod_id = request.args.get("vod_id")
        data = fetch_external("get_vod_info", {"vod_id": vod_id})
        return jsonify(data)

    # live EPG data
    if action == "get_simple_data_table":
        stream_id = request.args.get("stream_id")
        data = fetch_external("get_simple_data_table", {"stream_id": stream_id})
        return jsonify(data)

    if not action:
        return jsonify(CACHE.get("server_info", {}))

    return jsonify(CACHE.get(action, []))


@app.route("/<asset>/<user>/<passwd>/<name>")
def redirect_external_server(asset=None, user=None, passwd=None, name=None):
    # Rediret stream request to external server directly
    # Incoming user and passwd are discarded
    location = f"{EXTERNAL_SERVER}/{asset}/{USERNAME}/{PASSWORD}/{name}"
    logger.info("Redirecting to: %s", location)
    return redirect(location, code=307)
    
if __name__ == "__main__":
    logger.info("Whitelist: %s", WHITELIST)
    logger.info("Blacklist: %s", BLACKLIST)
    logger.info("Whitelist Category: %s", WHITELIST_CATEGORY)
    app.run(host="0.0.0.0", port=8000)
