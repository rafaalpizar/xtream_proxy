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
USERAGENT = config.get("xtream-remote", "user-agent", fallback="okhttp/3.14.17")

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
LAST_REFRESH = {}
REFRESH_INTERVAL = 24 * 3600  # once per day

app = Flask(__name__)

def fetch_external(action=None, extra_params=None):
    """Fetch data from external Xtream Codes server."""
    headers = {"User-Agent": USERAGENT}
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

def refresh_cache(action):
    """Refresh cache once per day."""
    stream_actions = ["get_live_streams", "get_vod_streams", "get_series"]
    category_actions = ["get_live_categories", "get_vod_categories", "get_series_categores"]
    category_streams = dict(zip(category_actions, stream_actions))

    global LAST_REFRESH, CACHE
    now = time.time()

    # if invalid action
    if action not in stream_actions + category_actions:
        # action not supported
        return

    # no action maps to server_info
    if not action:
        action = "server_info"

    # get last refresh time per action
    action_last_refresh = LAST_REFRESH.get(action, 0)
    if now - action_last_refresh < REFRESH_INTERVAL:
        # no need to refresh cache
        return

    if action == "server_info":
        CACHE["server_info"] = fetch_external()
        # override some server info
        try:
            CACHE["server_info"]["user_info"]["username"] = "-"
            CACHE["server_info"]["user_info"]["password"] = "-"
            CACHE["server_info"]["server_info"]["url"] = "-"
        except:
            logger.error("Server information from external is malformed")
    elif action in stream_actions:
        CACHE[action] = filter_streams(fetch_external(action))
    else:
        # if a category is requested: first must be loaded the streams
        stream_to_refresh = category_streams[action]
        if now - LAST_REFRESH.get(stream_to_refresh, 0) > REFRESH_INTERVAL:
            # TTL has expired
            CACHE[stream_to_refresh] = filter_streams(fetch_external(stream_to_refresh))
        # refresh the category
        CACHE[action] = filter_categories(fetch_external(action))

    LAST_REFRESH[action] = now

def get_noncacheable_action(args):
    """
    Params:
    args -- http request querystrings
    """
    action = args.get("action")
    asset = action.split("_")[1]
    if asset == "simple":
        asset_str = "get_simple_data_table"
        asset_id = args.get("stream_id")
    else:
        asset_str = f"get_{asset}_info"
        asset_id = args.get(f"{asset}_id")
    return fetch_external(action, {asset_srt: asset_id})

def get_action(args):
    """
    Params:
    args -- http request querystrings
    """
    non_cacheable_actions = ["get_series_info",
                            "get_vod_info",
                            "get_simple_data_table"]

    action = args.get("action")
    refresh_cache(action)

    if action in non_cacheable_actions:
        return get_noncacheable_action(args)
    if not action:
        return CACHE.get("server_info", {})

    return CACHE.get(action, [])

@app.route("/player_api.php")
def local_api():
    """Proxy API with filtering and caching."""
    return jsonify(get_action(request.args))

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
