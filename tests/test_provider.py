import httpx
import pytest

from opspilot.llm import ChatModel, ModelError


def test_retry_and_usage_are_adapter_requests():
    seen = []
    def handle(request):
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={'choices': [{'message': {'content': 'ok'}}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 2}})
    model = ChatModel('https://provider.example/v1', 'fake-key', 'test', httpx.MockTransport(handle))
    assert model.complete([])['content'] == 'ok'
    assert model.calls == 2 and model.usage['prompt_tokens'] == 10
    assert seen[0].url.path == '/v1/chat/completions'


def test_provider_error_does_not_echo_credentials():
    model = ChatModel('https://provider.example/v1', 'fake-secret', 'test', httpx.MockTransport(lambda _: httpx.Response(401, text='fake-secret')))
    with pytest.raises(ModelError) as error:
        model.complete([])
    assert 'fake-secret' not in str(error.value) and model.calls == 1


@pytest.mark.parametrize('message', [[], None, 42])
def test_malformed_provider_message_is_a_safe_error(message):
    model = ChatModel('https://provider.example/v1', 'fake', 'test', httpx.MockTransport(lambda _: httpx.Response(200, json={'choices': [{'message': message}]})))
    with pytest.raises(ModelError):
        model.complete([])


def test_missing_provider_usage_is_unknown():
    model = ChatModel('https://provider.example/v1', 'fake', 'test', httpx.MockTransport(lambda _: httpx.Response(200, json={'choices': [{'message': {'content': 'ok'}}]})))
    model.complete([])
    assert model.usage['prompt_tokens'] is None
