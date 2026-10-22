import pytest

from opspilot.local_llm import output_without_thinking, parse_tool_output


def test_parse_generated_tool_calls_without_changing_actions():
    value = '<tool_call>{"name":"analyze_service_logs","arguments":{"service":"orders-api","start_time":"2026-10-20T09:00:00Z"}}</tool_call>'
    result = parse_tool_output(value)
    assert result[0]["function"]["name"] == "analyze_service_logs"
    assert '"start_time": "2026-10-20T09:00:00Z"' in result[0]["function"]["arguments"]


def test_missing_tool_block_is_not_synthesized():
    assert parse_tool_output("I would search the documents") == []


@pytest.mark.parametrize("value", [
    '<tool_call>{"name":42,"arguments":{}}</tool_call>',
    '<tool_call>{"name":"search_knowledge","arguments":[]}</tool_call>',
    '<tool_call>not JSON</tool_call>',
])
def test_invalid_tool_block_fails(value):
    with pytest.raises(ValueError):
        parse_tool_output(value)


def test_only_non_thinking_output_is_retained():
    assert output_without_thinking('<think>private</think>```json\n{"claims":[]}\n```') == '{"claims":[]}'
