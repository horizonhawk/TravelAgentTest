"""Provider names in SDK diagnostics must match the request's actual endpoint."""

import asyncio
import logging

import httpx
import openai
import pytest
from strands.types.exceptions import ModelThrottledException

from trip_agent.openrouter_model import OpenRouterChatModel


def test_router_rate_limit_label_through_real_sdk_and_context_cleanup(monkeypatch, caplog):
    def respond(request):
        assert request.url.host == 'openrouter.ai'
        assert request.headers['authorization'] == 'Bearer offline-router-key'
        return httpx.Response(429, json={'error': {
            'message': 'Rate limit exceeded: free-models-per-day', 'code': 429}})

    original_client = openai.AsyncOpenAI
    monkeypatch.setattr(openai, 'AsyncOpenAI', lambda **kwargs: original_client(
        **kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond))))
    model = OpenRouterChatModel(model_id='openrouter/free', client_args={
        'api_key': 'offline-router-key', 'base_url': 'https://openrouter.ai/api/v1', 'max_retries': 0})

    async def invoke():
        with pytest.raises(ModelThrottledException, match='free-models-per-day'):
            async for _ in model.stream([{'role': 'user', 'content': [{'text': 'Help'}]}]):
                pass
        # Verify reset in the same async context, even after a provider exception.
        logging.getLogger('strands.models.openai').warning('OpenAI threw rate limit error')
        logging.getLogger('strands.models.openai').warning('Unrelated SDK warning')

    with caplog.at_level(logging.WARNING):
        asyncio.run(invoke())
    messages = [r.getMessage() for r in caplog.records]
    assert messages.count('OpenRouter returned a rate limit error') == 1
    assert messages.count('OpenAI threw rate limit error') == 1
    assert 'Unrelated SDK warning' in messages
