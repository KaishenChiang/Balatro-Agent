import asyncio
import ipaddress
import math
import time
from urllib.parse import urlsplit

import httpx

READ_ONLY_METHODS = frozenset(("health", "reader_snapshot", "action_status"))
READ_RETRY_DELAYS = (0.05, 0.1)


class ReaderError(Exception):
    """Only a fixed code may escape the trust boundary."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class GameClient:
    def __init__(self, url: str, timeout_s: float, transport: httpx.AsyncBaseTransport | None = None):
        parsed = urlsplit(url)
        if parsed.scheme != "http" or parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError("invalid_loopback_endpoint")
        if not ipaddress.ip_address(parsed.hostname or "").is_loopback:
            raise ValueError("non_loopback_endpoint")
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("invalid_timeout")
        self._timeout_s = timeout_s
        self._client = httpx.AsyncClient(base_url=url, timeout=timeout_s, trust_env=False, follow_redirects=False, transport=transport)
        self._lock = asyncio.Lock()
        self._counter = 0

    async def read(self, method: str, timeout_s: float | None = None) -> dict:
        if method not in ("health", "reader_snapshot"):
            raise ReaderError("method_not_allowed")
        return await self._request(method, {}, timeout_s)

    async def action(self, method: str, params: dict, timeout_s: float | None = None) -> dict:
        if method not in ("act_submit", "action_status"):
            raise ReaderError("method_not_allowed")
        return await self._request(method, params, timeout_s)

    async def _request(self, method: str, params: dict, timeout_s: float | None = None) -> dict:
        # Passing None to HTTPX disables the configured timeout. Keep the
        # default, and bound the entire request (lock, body and safe retries),
        # not just each read of a slowly arriving response.
        budget = self._timeout_s if timeout_s is None else timeout_s
        if isinstance(budget, bool) or not isinstance(budget, (int, float)) or not math.isfinite(budget) or budget <= 0:
            raise ReaderError("invalid_timeout")
        deadline = time.monotonic() + budget
        try:
            async with asyncio.timeout(budget):
                async with self._lock:
                    self._counter += 1
                    identifier = self._counter
                    for attempt in range(len(READ_RETRY_DELAYS) + 1):
                        try:
                            return await self._exchange(method, params, identifier, max(0.001, deadline - time.monotonic()))
                        except httpx.TimeoutException:
                            code = "request_timeout"
                        except httpx.RequestError:
                            code = "disconnected"
                        # Never resend a state-changing submission, even when
                        # it looks like a connection failure. Status retries
                        # retain exactly the caller's original action ID.
                        if (method not in READ_ONLY_METHODS or attempt == len(READ_RETRY_DELAYS)
                                or deadline - time.monotonic() <= READ_RETRY_DELAYS[attempt]):
                            raise ReaderError(code) from None
                        await asyncio.sleep(READ_RETRY_DELAYS[attempt])
        except ReaderError:
            raise
        except TimeoutError:
            raise ReaderError("request_timeout") from None
        except (ValueError, UnicodeError):
            raise ReaderError("invalid_response") from None

    async def _exchange(self, method, params, identifier, timeout_s):
        async with self._client.stream("POST", "/", json={"jsonrpc": "2.0", "method": method, "params": params, "id": identifier}, timeout=timeout_s) as response:
            if response.status_code != 200:
                raise ReaderError("invalid_response")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 2_000_000:
                    raise ReaderError("invalid_response")
        import json
        envelope = json.loads(body)
        if not isinstance(envelope, dict) or envelope.get("jsonrpc") != "2.0" or envelope.get("id") != identifier:
            raise ReaderError("invalid_response")
        if "error" in envelope or not isinstance(envelope.get("result"), dict):
            raise ReaderError("adapter_error")
        return envelope["result"]

    async def close(self) -> None:
        await self._client.aclose()
