"""Shared Redis client configuration for resilient connections.

NOTE: ``socket_timeout`` must exceed the longest ``XREADGROUP BLOCK``
timeout used by any consumer (currently 5 000 ms).  Setting it to 10 s
avoids false ``TimeoutError`` on idle blocking reads.
"""

REDIS_CLIENT_OPTIONS = {
    "decode_responses": True,
    "socket_timeout": 10.0,
    "socket_connect_timeout": 5.0,
    "socket_keepalive": True,
    "retry_on_timeout": True,
    "health_check_interval": 30,
}
