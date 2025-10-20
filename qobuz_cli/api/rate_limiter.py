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
        Waits if necessary to respect the current rate limit before allowing a call to proceed.
        """
        async with self._lock:
            # Gradually recover the rate if no 429 errors have occurred recently
            if time.monotonic() - self._last_429_time > 300:  # 5 minutes
                self._rate = min(self._max_rate, self._rate * 1.005)  # Slow recovery
                self._min_interval = 1.0 / self._rate

            now = asyncio.get_event_loop().time()
            time_since_last = now - self._last_call_time

            if time_since_last < self._min_interval:
                await asyncio.sleep(self._min_interval - time_since_last)

            self._last_call_time = asyncio.get_event_loop().time()
