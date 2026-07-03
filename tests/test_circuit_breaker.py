"""Tests for the async circuit breaker state machine."""

import asyncio
import contextlib

from qobuz_cli.utils.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerError,
    CircuitState,
)


def run(coro):
    return asyncio.run(coro)


def test_starts_closed():
    assert CircuitBreaker().state == CircuitState.CLOSED


def test_opens_after_threshold_failures():
    async def scenario():
        breaker = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            with contextlib.suppress(ValueError):
                async with breaker:
                    raise ValueError("boom")
        return breaker.state

    assert run(scenario()) == CircuitState.OPEN


def test_open_blocks_requests():
    async def scenario():
        breaker = CircuitBreaker(failure_threshold=1)
        with contextlib.suppress(ValueError):
            async with breaker:
                raise ValueError("boom")
        blocked = False
        try:
            async with breaker:
                pass
        except CircuitBreakerError:
            blocked = True
        return blocked

    assert run(scenario()) is True


def test_ignore_predicate_does_not_trip():
    async def scenario():
        breaker = CircuitBreaker(
            failure_threshold=1,
            ignore_predicate=lambda exc: isinstance(exc, KeyError),
        )
        with contextlib.suppress(KeyError):
            async with breaker:
                raise KeyError("ignored")
        return breaker.state

    assert run(scenario()) == CircuitState.CLOSED


def test_recovers_through_half_open():
    async def scenario():
        breaker = CircuitBreaker(
            failure_threshold=1,
            recovery_timeout=0,
            success_threshold=1,
        )
        with contextlib.suppress(ValueError):
            async with breaker:
                raise ValueError("boom")
        async with breaker:
            pass
        return breaker.state

    assert run(scenario()) == CircuitState.CLOSED
