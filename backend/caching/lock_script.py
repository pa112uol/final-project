# Lua script shared by the sync and async caches: releases a lock only if the
# caller still holds it, so a stale holder cannot release a successor's lock.
# Canonical compare-and-delete release from the Redis distributed-lock docs
# https://redis.io/docs/latest/develop/use-cases/patterns/distributed-locks/
RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""
