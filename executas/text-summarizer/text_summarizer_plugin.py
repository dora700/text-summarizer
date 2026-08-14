"""Executa plugin for the text-summarizer Anna App.

Exposes a single tool, `summarize`, that asks the host to run an LLM
completion via reverse sampling (`sampling/createMessage`) instead of
holding its own model credentials. Anna's host owns model selection,
billing, and quota.
"""

import json
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue

PROTOCOL_VERSION_V2 = "2.0"

MANIFEST = {
    "name": "tool-dev-text-summarizer",
    "version": "0.1.0",
    "description": "Summarizes a passage of text by asking the host to sample an LLM.",
    # Declares which reverse capability this plugin uses. Without this,
    # the host refuses sampling/createMessage with error -32008.
    "host_capabilities": ["llm.sample"],
    "tools": [
        {
            "name": "summarize",
            "description": "Summarize the supplied text into a short paragraph.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to summarize"},
                    "max_words": {
                        "type": "integer",
                        "description": "Approx max words in the summary",
                        "default": 80,
                    },
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        }
    ],
}

_stdout_lock = threading.Lock()
_pending: dict = {}
_pending_lock = threading.Lock()
_sampling_enabled = True
_sampling_disabled_reason = ""


def _write_frame(msg: dict) -> None:
    with _stdout_lock:
        sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def _make_response(req_id, *, result=None, error=None) -> dict:
    out = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result
    return out


def sample(invoke_id: str, text: str, max_words: int, *, timeout: float = 90.0) -> dict:
    """Ask the host to summarize `text` via reverse sampling."""
    if not _sampling_enabled:
        raise RuntimeError(_sampling_disabled_reason or "sampling not negotiated")

    req_id = str(uuid.uuid4())
    q: Queue = Queue()
    with _pending_lock:
        _pending[req_id] = q

    _write_frame(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "sampling/createMessage",
            "params": {
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": (
                                f"Summarize the following text in at most {max_words} words. "
                                "Return only the summary, no preamble.\n\n---\n" + text
                            ),
                        },
                    }
                ],
                "maxTokens": max(64, min(1024, max_words * 5)),
                "systemPrompt": "You are a concise editorial assistant.",
                "includeContext": "none",
                "metadata": {"executa_invoke_id": invoke_id, "tool": "summarize"},
            },
        }
    )

    try:
        resp = q.get(timeout=timeout)
    except Empty:
        with _pending_lock:
            _pending.pop(req_id, None)
        raise RuntimeError("sampling request timed out")

    if "error" in resp:
        err = resp["error"]
        raise RuntimeError(f"sampling error {err.get('code')}: {err.get('message')}")

    result = resp["result"]
    content = result.get("content") or {}
    text_out = content.get("text", "") if isinstance(content, dict) else ""
    return {
        "summary": text_out,
        "model": result.get("model"),
        "usage": result.get("usage"),
        "stopReason": result.get("stopReason"),
    }


def _handle_initialize(req_id, params: dict) -> dict:
    global _sampling_enabled, _sampling_disabled_reason
    proto = (params or {}).get("protocolVersion") or "1.1"
    if proto != PROTOCOL_VERSION_V2:
        _sampling_enabled = False
        _sampling_disabled_reason = (
            f"host did not negotiate v2 (offered protocolVersion={proto!r}); "
            "sampling/createMessage requires Executa protocol 2.0"
        )
    return _make_response(
        req_id,
        result={
            "protocolVersion": proto if proto in ("1.1", "2.0") else "2.0",
            "serverInfo": {"name": MANIFEST["name"], "version": MANIFEST["version"]},
            # Mirror MCP shape: advertise that we WILL use sampling.
            "client_capabilities": {"sampling": {}} if proto == PROTOCOL_VERSION_V2 else {},
            "capabilities": {},
        },
    )


def _handle_describe(req_id) -> dict:
    return _make_response(req_id, result=MANIFEST)


def _handle_health(req_id) -> dict:
    return _make_response(req_id, result={"status": "ready"})


def _handle_invoke(req_id, params: dict) -> dict:
    tool = params.get("tool")
    args = params.get("arguments") or {}
    invoke_id = params.get("invoke_id") or str(req_id)

    if tool != "summarize":
        return _make_response(req_id, error={"code": -32601, "message": f"Unknown tool: {tool}"})

    text = (args.get("text") or "").strip()
    if not text:
        return _make_response(req_id, result={"success": False, "error": "text must not be empty"})

    max_words = args.get("max_words", 80)
    try:
        max_words = max(20, min(400, int(max_words)))
    except (TypeError, ValueError):
        max_words = 80

    try:
        data = sample(invoke_id, text, max_words)
    except Exception as e:  # noqa: BLE001
        return _make_response(req_id, result={"success": False, "error": str(e)})

    return _make_response(req_id, result={"success": True, "data": data})


def _handle_line(line: str) -> None:
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        _write_frame(_make_response(None, error={"code": -32700, "message": "Parse error"}))
        return

    # Reverse-RPC reply from the host (no "method") resolves a pending sample() call.
    if "method" not in msg:
        req_id = msg.get("id")
        with _pending_lock:
            q = _pending.pop(req_id, None)
        if q is not None:
            q.put(msg)
        else:
            print(f"unmatched sampling response id={req_id!r}", file=sys.stderr)
        return

    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        resp = _handle_initialize(req_id, params)
    elif method == "describe":
        resp = _handle_describe(req_id)
    elif method == "health":
        resp = _handle_health(req_id)
    elif method == "invoke":
        resp = _handle_invoke(req_id, params)
    elif method == "shutdown":
        resp = _make_response(req_id, result={"ok": True})
    else:
        resp = _make_response(req_id, error={"code": -32601, "message": f"Method not found: {method}"})

    if req_id is not None:
        _write_frame(resp)


def main() -> None:
    print("text-summarizer executa started", file=sys.stderr)
    # Invokes block on a reverse RPC round-trip, so run them on a worker
    # pool and keep the stdin reader thread free to receive the matching
    # sampling response in the meantime.
    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="invoke")
    try:
        for raw in sys.stdin:
            line = raw.strip()
            if not line:
                continue
            pool.submit(_handle_line, line)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    main()
