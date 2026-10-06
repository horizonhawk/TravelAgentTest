"""Stable failure categories for CLI diagnostics and saved evaluation replays."""


def classify_failure(error):
    chain = []
    current = error
    while isinstance(current, BaseException) and id(current) not in {id(item) for item in chain}:
        chain.append(current)
        current = current.__cause__ or current.__context__
    text = " ".join(str(item) for item in chain) if chain else str(error)
    lower = text.lower()
    statuses = {getattr(item, "status_code", None) for item in chain}
    names = {type(item).__name__ for item in chain}
    category, blocked = "agent_error", False
    if any(word in lower for word in ("free-models-per-day", "insufficient_quota", "daily quota", "provider_quota")):
        category, blocked = "provider_quota", True
    elif 429 in statuses or "ModelThrottledException" in names or "error code: 429" in lower or "provider_rate_limit" in lower:
        category, blocked = "provider_rate_limit", True
    elif statuses & {401, 403, 404} or "provider_access" in lower or any(f"error code: {code}" in lower for code in (401, 403, 404)):
        category, blocked = "provider_access", True
    elif names & {"APIConnectionError", "APITimeoutError"} or any(word in lower for word in (
            "apiconnectionerror", "apitimeouterror", "connection error", "connection timeout", "provider_connection")):
        category, blocked = "provider_connection", True
    elif "provider_unavailable" in lower or any(isinstance(code, int) and code >= 500 for code in statuses):
        category, blocked = "provider_unavailable", True
    elif "repeated identical invalid tool" in lower:
        category = "repeated_invalid_tool_input"
    elif "model-call limit" in lower:
        category = "model_call_limit"
    elif "StructuredOutputException" in names or "model/tool-protocol failure" in lower:
        category = "structured_output_protocol"
    return {"category": category, "provider_blocked": blocked}


def output_failure(output):
    if not output or not output.get("error"):
        return None
    return output.get("failure") or classify_failure(output["error"])
