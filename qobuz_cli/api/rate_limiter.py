"""
Provides an adaptive rate limiter to avoid 429 "Too Many Requests" errors from the API.
"""

import asyncio
import logging
import time

log = logging.getLogger(__name__)


class AdaptiveRateLimiter:
    """
    Dynamically adjusts call rate based on API feedback (429 errors).
    """

    def __init__(
        self, initial_calls_per_second: float = 8.0, max_calls_per_second: float = 12.0
    ):
        """
        Initializes the rate limiter.

        Args:
            initial_calls_per_second: The starting rate of calls per second.
            max_calls_per_second: The maximum rate to recover to.
        """
        self._rate = initial_calls_per_second
        self._max_rate = max_calls_per_second
        self._min_interval = 1.0 / self._rate
        self._last_call_time = 0.0
        self._last_429_time = 0.0
        self._lock = asyncio.Lock()

    async def on_429(self) -> None:
        """
        Called when a 429 error is received. Halves the current request rate.
        """
        async with self._lock:
            self._rate = max(
                1.0, self._rate * 0.5
            )  # Halve the rate, minimum 1 call/sec
            self._min_interval = 1.0 / self._rate
            self._last_429_time = time.monotonic()
            log.warning(
                f"[yellow]Rate limit hit. New rate: {self._rate:.1f} calls/s[/yellow]"
            )

    async def acquire(self) -> None:
        """
        Waits if necessary to respect the current rate limit before allowing a
        call to proceed.

        The wait is computed while holding the lock but performed *after*
        releasing it, so a slow caller's sleep does not serialize every other
        concurrent caller. Each caller reserves its own slot by advancing
        ``_last_call_time`` before sleeping.
        """
        async with self._lock:
            now = time.monotonic()

            # Gradually recover the rate if no 429 errors have occurred recently
            if now - self._last_429_time > 300:  # 5 minutes
                self._rate = min(self._max_rate, self._rate * 1.005)  # Slow recovery
                self._min_interval = 1.0 / self._rate

            # Reserve the next slot: the earliest time this call may proceed.
            scheduled_time = max(now, self._last_call_time + self._min_interval)
            self._last_call_time = scheduled_time
            wait_time = scheduled_time - now

        if wait_time > 0:
            await asyncio.sleep(wait_time)
