from types import SimpleNamespace as NS

from app.accounting.usage_snapshot import usage_from_response


def test_full_usage():
    r = NS(model="claude-haiku-4-5", _request_id="req_1", usage=NS(
        input_tokens=10, output_tokens=5, cache_read_input_tokens=7, cache_creation_input_tokens=3,
        server_tool_use=NS(web_search_requests=2)))
    s = usage_from_response(r)
    assert (s.model, s.input_tokens, s.output_tokens, s.cache_read_tokens, s.cache_creation_tokens,
            s.web_search_count, s.request_id) == ("claude-haiku-4-5", 10, 5, 7, 3, 2, "req_1")


def test_missing_optional_fields_default_to_zero():
    s = usage_from_response(NS(usage=NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=None)),
                            requested_model="claude-sonnet-5")
    assert s.cache_read_tokens == 0 and s.cache_creation_tokens == 0 and s.web_search_count == 0
    assert s.model == "claude-sonnet-5" and s.request_id is None


def test_missing_usage_never_raises():
    s = usage_from_response(NS())
    assert (s.input_tokens, s.output_tokens, s.model) == (0, 0, "unknown")
    assert usage_from_response(NS(usage=None)).output_tokens == 0
