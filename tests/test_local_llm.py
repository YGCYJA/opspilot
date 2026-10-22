from opspilot.local_llm import output_without_thinking


def test_only_non_thinking_json_output_is_retained():
    assert output_without_thinking('<think>private</think>```json\n{"claims":[]}\n```') == '{"claims":[]}'
