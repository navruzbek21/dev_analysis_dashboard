import argparse

from cache_backend import redis_client
from config import settings


def clear(prefix, dry_run=False):
    if redis_client is None:
        raise RuntimeError("Redis client is not available")
    pattern = f"{prefix}:*"
    deleted = 0
    for key in redis_client.scan_iter(match=pattern, count=1000):
        if dry_run:
            print(key.decode("utf-8") if isinstance(key, bytes) else key)
        else:
            deleted += int(redis_client.delete(key))
    print({"prefix": prefix, "deleted": deleted, "dry_run": dry_run})


def main():
    parser = argparse.ArgumentParser(description="Clear old Redis cache keys by prefix.")
    parser.add_argument("--prefix", default=settings.cache_key_prefix)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    clear(args.prefix, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
