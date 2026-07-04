from datetime import datetime, timedelta

CACHE = {}

CACHE_MINUTES = 10


def get_cache(key: str):
    item = CACHE.get(key)

    if not item:
        return None

    expire_time = item["expire_time"]

    if datetime.now() > expire_time:
        del CACHE[key]
        return None

    return item["data"]


def set_cache(key: str, data):
    CACHE[key] = {
        "data": data,
        "expire_time": datetime.now() + timedelta(minutes=CACHE_MINUTES)
    }