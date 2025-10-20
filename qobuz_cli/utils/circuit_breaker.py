"""
Circuit breaker pattern implementation for API call protection.
Place this file at: qobuz_cli/utils/circuit_breaker.py
"""

import asyncio
import logging
import time
from enum import Enum
from typing import Optional

log = logging.getLogger(__name__)


class CircuitState(Enum):
    """States of the circuit breaker."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Blocking requests
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open."""

    pass


class CircuitBreaker:
    """
    Circuit breaker to prevent cascading failures.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Too many failures, requests blocked
    - HALF_OPEN: Testing recovery, limited requests allowed
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        success_threshold: int = 2,
    ):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before attempting recovery
            success_threshold: Consecutive successes needed to close circuit
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Current circuit state."""
        return self._state

    async def _check_state(self) -> None:
        """Check if circuit should transition from OPEN to HALF_OPEN."""
        if self._state == CircuitState.OPEN:
            if self._last_failure_time is None:
                return

            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                log.info(
                    f"[yellow]Circuit breaker transitioning to HALF_OPEN "
                    f"(testing recovery after {elapsed:.0f}s)[/yellow]"
                )
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0

    async def _on_success(self) -> None:
        """Handle successful call."""
        async with self._lock:
            self._failure_count = 0

            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1

                if self._success_count >= self.success_threshold:
                    log.info(
                        "[green]✓ Circuit breaker recovered. "
                        "Transitioning to CLOSED.[/green]"
                    )
                    self._state = CircuitState.CLOSED
                    self._success_count = 0

    async def _on_failure(self) -> None:
        """Handle failed call."""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                log.warning(
                    "[yellow]Circuit breaker: Recovery test failed. "
                    "Returning to OPEN state.[/yellow]"
                )
                self._state = CircuitState.OPEN
                self._failure_count = 0
                self._success_count = 0

            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    log.error(
                        f"[red]✗ Circuit breaker OPENED after "
                        f"{self._failure_count} consecutive failures. "
                        f"Requests blocked for {self.recovery_timeout}s.[/red]"
                    )
                    self._state = CircuitState.OPEN

    async def __aenter__(self):
        """Enter context, check if circuit is open."""
        async with self._lock:
            await self._check_state()
            if self._state == CircuitState.OPEN:
                raise CircuitBreakerError(
                    f"Circuit is open. Will try to recover after "
                    f"{self.recovery_timeout} seconds."
                )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit context, handle success or failure."""
        if exc_type:
            await self._on_failure()
        else:
            await self._on_success()
