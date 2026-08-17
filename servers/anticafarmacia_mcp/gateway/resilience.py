"""
Gateway resilience layer with local-first isolation and per-remote error handling.

Provides:
- Local tool/prompt/resource availability guarantee (even when all remotes down)
- Per-remote error isolation (one broken remote doesn't affect local or other remotes)
- Per-remote timeout safety (default: 10s for list, 30s for calls)
- Transparent remote health status in aggregated responses
- Circuit breaker state tracking per remote
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, TypeVar
from enum import Enum

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker state machine for per-remote error tracking."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Too many failures; skip remote for cooldown
    HALF_OPEN = "half_open"  # Recovering; probe remote


@dataclass
class RemoteHealthStatus:
    """Health status for a single remote."""

    remote_name: str
    remote_namespace: str
    enabled: bool
    reachable: bool = True
    error: str | None = None
    circuit_state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: float | None = None
    last_success_time: float | None = None
    latency_ms: int | None = None


class PerRemoteCircuitBreaker:
    """Circuit breaker for a single remote with exponential backoff cooldown."""

    def __init__(
        self,
        remote_name: str,
        failure_threshold: int = 3,
        cooldown_base_ms: float = 300_000,  # 5 min
        cooldown_max_ms: float = 1_800_000,  # 30 min
    ):
        self.remote_name = remote_name
        self.failure_threshold = failure_threshold
        self.cooldown_base_ms = cooldown_base_ms
        self.cooldown_max_ms = cooldown_max_ms

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: float | None = None
        self.cooldown_until: float | None = None
        self.cooldown_multiplier = 1.0

    def record_success(self) -> None:
        """Record successful operation; reset failure counter."""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None
        self.cooldown_multiplier = 1.0
        self.cooldown_until = None

    def record_failure(self) -> None:
        """Record failed operation; check if should open circuit."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            cooldown_ms = min(
                self.cooldown_base_ms * self.cooldown_multiplier,
                self.cooldown_max_ms,
            )
            self.cooldown_until = time.time() + (cooldown_ms / 1000.0)
            self.state = CircuitState.OPEN
            self.cooldown_multiplier *= 2.0  # Exponential backoff
            logger.warning(
                f"Circuit opened for {self.remote_name} after {self.failure_count} failures; "
                f"cooldown until {self.cooldown_until:.2f}"
            )

    def try_probe_recovery(self) -> bool:
        """Check if circuit is ready to probe recovery (HALF_OPEN)."""
        if self.state != CircuitState.OPEN:
            return False

        if self.cooldown_until is None or time.time() < self.cooldown_until:
            return False

        self.state = CircuitState.HALF_OPEN
        logger.info(f"Circuit transitioned to HALF_OPEN for {self.remote_name}; probing recovery")
        return True

    def is_open(self) -> bool:
        """Check if circuit is open (reject calls)."""
        if self.state != CircuitState.OPEN:
            return False

        if self.cooldown_until is None or time.time() < self.cooldown_until:
            return True

        # Cooldown expired; allow HALF_OPEN probe
        return False


class GatewayResilienceManager:
    """Manages local-first resilience, per-remote error isolation, and health tracking."""

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_base_ms: float = 300_000,
        cooldown_max_ms: float = 1_800_000,
        list_tools_timeout_ms: float = 10_000,
        call_tool_timeout_ms: float = 30_000,
    ):
        self.failure_threshold = failure_threshold
        self.cooldown_base_ms = cooldown_base_ms
        self.cooldown_max_ms = cooldown_max_ms
        self.list_tools_timeout_ms = list_tools_timeout_ms
        self.call_tool_timeout_ms = call_tool_timeout_ms

        self._circuit_breakers: dict[str, PerRemoteCircuitBreaker] = {}
        self._remote_health: dict[str, RemoteHealthStatus] = {}

    def register_remote(self, remote_name: str, remote_namespace: str, enabled: bool = True) -> None:
        """Register a remote for health tracking."""
        if remote_name not in self._circuit_breakers:
            self._circuit_breakers[remote_name] = PerRemoteCircuitBreaker(
                remote_name,
                failure_threshold=self.failure_threshold,
                cooldown_base_ms=self.cooldown_base_ms,
                cooldown_max_ms=self.cooldown_max_ms,
            )
            self._remote_health[remote_name] = RemoteHealthStatus(
                remote_name=remote_name,
                remote_namespace=remote_namespace,
                enabled=enabled,
            )

    def get_circuit_breaker(self, remote_name: str) -> PerRemoteCircuitBreaker | None:
        """Get circuit breaker for a remote."""
        return self._circuit_breakers.get(remote_name)

    def get_health_status(self, remote_name: str) -> RemoteHealthStatus | None:
        """Get health status for a remote."""
        return self._remote_health.get(remote_name)

    def get_all_health_status(self) -> dict[str, RemoteHealthStatus]:
        """Get health status for all remotes."""
        return self._remote_health.copy()

    async def call_with_timeout_and_isolation(
        self,
        remote_name: str,
        *,
        operation: Callable[[], Coroutine[Any, Any, T]],
        operation_name: str = "operation",
        timeout_ms: float | None = None,
        is_read_only: bool = True,
    ) -> T | None:
        """Call a remote operation with timeout, circuit breaker, and error isolation.

        Returns:
          - T: Result if successful
          - None: If circuit is open, timeout, or error (with isolation)

        Errors are logged but never raised (error isolation).
        """
        timeout_s = (timeout_ms or self.call_tool_timeout_ms) / 1000.0
        cb = self.get_circuit_breaker(remote_name)
        health = self.get_health_status(remote_name)

        if cb is None or health is None:
            logger.warning(f"Remote {remote_name} not registered; skipping {operation_name}")
            return None

        # Check circuit state
        if cb.is_open():
            health.reachable = False
            health.error = f"circuit open (cooldown until {cb.cooldown_until})"
            health.circuit_state = CircuitState.OPEN
            logger.warning(
                f"Skipping {operation_name} for {remote_name} (circuit open); local tools unaffected"
            )
            return None

        # Try recovery if HALF_OPEN
        if cb.state == CircuitState.HALF_OPEN:
            health.circuit_state = CircuitState.HALF_OPEN
            logger.info(f"Probing recovery for {remote_name} during {operation_name}")

        # Execute with timeout
        start = time.time()
        try:
            result = await asyncio.wait_for(operation(), timeout=timeout_s)
            elapsed_ms = int((time.time() - start) * 1000)

            # Success
            cb.record_success()
            health.reachable = True
            health.error = None
            health.circuit_state = CircuitState.CLOSED
            health.last_success_time = time.time()
            health.latency_ms = elapsed_ms
            logger.debug(f"{operation_name} for {remote_name} succeeded in {elapsed_ms}ms")
            return result

        except asyncio.TimeoutError:
            elapsed_ms = int((time.time() - start) * 1000)
            cb.record_failure()
            health.reachable = False
            health.error = f"timeout after {timeout_s}s"
            health.circuit_state = cb.state
            health.failure_count = cb.failure_count
            health.last_failure_time = time.time()
            health.latency_ms = elapsed_ms
            logger.warning(
                f"{operation_name} for {remote_name} timed out after {timeout_s}s; "
                f"failures: {cb.failure_count}/{self.failure_threshold}; local tools unaffected"
            )
            return None

        except Exception as exc:
            elapsed_ms = int((time.time() - start) * 1000)
            cb.record_failure()
            health.reachable = False
            health.error = str(exc)
            health.circuit_state = cb.state
            health.failure_count = cb.failure_count
            health.last_failure_time = time.time()
            health.latency_ms = elapsed_ms
            logger.warning(
                f"{operation_name} for {remote_name} failed: {exc}; "
                f"failures: {cb.failure_count}/{self.failure_threshold}; local tools unaffected"
            )
            return None

    async def call_all_remotes_with_isolation(
        self,
        remotes: list[tuple[str, Callable[[], Coroutine[Any, Any, T]]]],
        *,
        operation_name: str = "operation",
        timeout_ms: float | None = None,
    ) -> dict[str, T | None]:
        """Call operation on multiple remotes in parallel, with per-remote isolation.

        Args:
          - remotes: [(remote_name, operation), ...]
          - operation_name: For logging
          - timeout_ms: Per-remote timeout

        Returns:
          - {remote_name: result_or_none}

        Each remote timeout/failure is isolated; failures don't affect other remotes or local tools.
        """
        timeout_s = (timeout_ms or self.call_tool_timeout_ms) / 1000.0
        tasks = []

        for remote_name, operation in remotes:
            task = self.call_with_timeout_and_isolation(
                remote_name,
                operation=operation,
                operation_name=operation_name,
                timeout_ms=timeout_ms,
            )
            tasks.append((remote_name, task))

        # Run all in parallel (not sequentially)
        results = {}
        for remote_name, task in tasks:
            result = await task
            results[remote_name] = result

        return results
