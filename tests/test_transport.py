"""Bounded transport failures, query recovery and no native resubmission."""
import asyncio
import json
import time

import httpx
import pytest

from balatro_agent.executor import Executor
from balatro_agent.reader import Reader
from balatro_agent.transport import GameClient, ReaderError


def reply(request, result):
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": json.loads(request.content)["id"], "result": result})


@pytest.mark.parametrize("method", ["health", "reader_snapshot", "action_status"])
@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ReadError, httpx.ReadTimeout, httpx.RemoteProtocolError])
async def test_only_queries_retry_transient_failures_with_original_parameters(method, error):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            raise error("SECRET_NETWORK_ERROR", request=request)
        return reply(request, {"public": "result"})
    client = GameClient("http://127.0.0.1:12346/", .4, httpx.MockTransport(handler))
    try:
        result = await (client.action(method, {"action_id": "original-id"}) if method == "action_status" else client.read(method))
        assert result == {"public": "result"} and len(requests) == 2
        assert requests[0] == requests[1]
    finally:
        await client.close()


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ReadError, httpx.ReadTimeout, httpx.RemoteProtocolError])
async def test_submit_is_sent_once_even_when_the_response_is_lost(error):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        raise error("SECRET_NETWORK_ERROR", request=request)
    client = GameClient("http://127.0.0.1:12346/", .4, httpx.MockTransport(handler))
    try:
        with pytest.raises(ReaderError) as failure:
            await client.action("act_submit", {"action_id": "original-id"})
        assert failure.value.code in ("disconnected", "request_timeout")
        assert len(requests) == 1 and "SECRET" not in str(failure.value)
    finally:
        await client.close()


async def test_default_timeout_bounds_a_stalled_submit_and_releases_the_lock():
    requests = []
    async def handler(request):
        data = json.loads(request.content)
        requests.append(data)
        assert all(value is not None for value in request.extensions["timeout"].values())
        if data["method"] == "act_submit":
            await asyncio.Event().wait()
        return reply(request, {"public": "result"})
    client = GameClient("http://127.0.0.1:12346/", .04, httpx.MockTransport(handler))
    try:
        with pytest.raises(ReaderError, match="request_timeout"):
            await asyncio.wait_for(client.action("act_submit", {"action_id": "original-id"}), 1)
        assert await client.read("health") == {"public": "result"}
        assert [value["method"] for value in requests] == ["act_submit", "health"]
    finally:
        await client.close()


async def test_whole_response_budget_bounds_slow_stream_and_closes_it():
    class SlowBody(httpx.AsyncByteStream):
        closed = False
        async def __aiter__(self):
            while True:
                await asyncio.sleep(.01)
                yield b" "
        async def aclose(self):
            self.closed = True
    stream = SlowBody()
    client = GameClient("http://127.0.0.1:12346/", .04,
                        httpx.MockTransport(lambda request: httpx.Response(200, stream=stream)))
    try:
        with pytest.raises(ReaderError, match="request_timeout"):
            await asyncio.wait_for(client.read("reader_snapshot"), 1)
        assert stream.closed
    finally:
        await client.close()


async def test_query_retries_share_one_deadline_and_do_not_reset_it():
    requests = []
    async def handler(request):
        requests.append(request)
        if len(requests) == 1:
            await asyncio.sleep(.03)
            raise httpx.ConnectError("SECRET_NETWORK_ERROR", request=request)
        await asyncio.Event().wait()
    client = GameClient("http://127.0.0.1:12346/", .5, httpx.MockTransport(handler))
    try:
        started = time.monotonic()
        with pytest.raises(ReaderError) as failure:
            await client.read("health", .3)
        assert failure.value.code == "request_timeout" and len(requests) == 2
        assert requests[1].extensions["timeout"]["read"] < .27
        assert time.monotonic() - started < 1
    finally:
        await client.close()


async def test_persistent_query_failure_stops_after_three_attempts():
    requests = []
    def handler(request):
        requests.append(request)
        raise httpx.ConnectError("SECRET_NETWORK_ERROR", request=request)
    client = GameClient("http://127.0.0.1:12346/", .5, httpx.MockTransport(handler))
    try:
        with pytest.raises(ReaderError, match="disconnected"):
            await client.read("health")
        assert len(requests) == 3
    finally:
        await client.close()


@pytest.mark.parametrize("kind", ["bad_id", "bad_json", "rpc_error", "http_error", "oversize"])
async def test_invalid_responses_are_not_retried(kind):
    requests = []
    def handler(request):
        requests.append(request)
        if kind == "bad_id":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": -1, "result": {}})
        if kind == "bad_json":
            return httpx.Response(200, content=b"SECRET_NOT_JSON")
        if kind == "rpc_error":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": json.loads(request.content)["id"], "error": {"message": "SECRET"}})
        if kind == "oversize":
            return httpx.Response(200, content=b"x" * 2_000_001)
        return httpx.Response(503, content=b"SECRET_SERVER_ERROR")
    client = GameClient("http://127.0.0.1:12346/", .4, httpx.MockTransport(handler))
    try:
        with pytest.raises(ReaderError) as failure:
            await client.read("health")
        assert len(requests) == 1 and "SECRET" not in str(failure.value)
    finally:
        await client.close()


@pytest.mark.parametrize("budget", [None, 0, -1, float("nan"), float("inf"), True, "SECRET"])
def test_unbounded_or_invalid_configuration_is_refused(budget):
    with pytest.raises(ValueError, match="invalid_timeout"):
        GameClient("http://127.0.0.1:12346/", budget)


@pytest.mark.parametrize("cancel", [False, True])
async def test_timed_out_or_cancelled_submission_retains_intent_and_recovers_by_query(settings, public_envelope, cancel):
    methods = []
    submitted = asyncio.Event()
    action_id = "synthetic-bounded-transport"
    async def handler(request):
        data = json.loads(request.content)
        methods.append(data["method"])
        if data["method"] == "reader_snapshot":
            return reply(request, public_envelope)
        if data["method"] == "act_submit":
            submitted.set()
            await asyncio.Event().wait()
        return reply(request, {"state": "COMPLETED", "reason": "completed", "submitted": True,
                    "action_id": action_id, "observation_id": public_envelope["observation_id"],
                    "game_session": public_envelope["game_session"], "execution_profile": public_envelope["profile"],
                    "callback_confirmed": True, "related_events_complete": True,
                    "completion_signal": "callback_events", "snapshot": public_envelope})
    client = GameClient(settings.url, .2 if cancel else .04, httpx.MockTransport(handler))
    reader = Reader(settings, client)
    executor = Executor(reader)
    try:
        observation = (await reader.observe())["observation"]
        parameters = dict(action="select", parameters={"region": "hand", "positions": [0]},
                          observation_id=observation["observation_id"], action_id=action_id,
                          reason="Synthetic no-resubmit boundary", experience_refs=[])
        task = asyncio.create_task(executor.act(**parameters))
        await asyncio.wait_for(submitted.wait(), 1)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert (await asyncio.wait_for(task, 1))["state"] == "UNKNOWN"
        assert executor.pending["action_id"] == action_id
        # Reloading the executor reads the same durable intent, not a new ID.
        restarted = Executor(reader)
        assert restarted.pending["action_id"] == action_id
        rejected = await restarted.act(**{**parameters, "action_id": "synthetic-next-action"})
        assert rejected["state"] == "REJECTED" and rejected["submitted"] is False
        assert (await restarted.action_status(action_id))["state"] == "COMPLETED"
        assert restarted.pending is None and methods.count("act_submit") == 1
    finally:
        await client.close()
