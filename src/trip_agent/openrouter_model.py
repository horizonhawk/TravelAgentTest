"""Small request-formatting compatibility shim around Strands' existing adapter."""

from strands.models.openai import OpenAIModel
from contextlib import asynccontextmanager
from contextvars import ContextVar
import logging
from types import SimpleNamespace


_openrouter_request = ContextVar("openrouter_request", default=False)


class _ProviderLogLabel(logging.Filter):
    """Correct hardcoded SDK labels only inside this provider's request context."""

    def filter(self, record):
        labels = {
            "OpenAI threw rate limit error": "OpenRouter returned a rate limit error",
            "OpenAI threw context window overflow error": "OpenRouter returned a context window overflow error",
        }
        if _openrouter_request.get() and record.getMessage() in labels:
            record.msg = labels[record.getMessage()]
            record.args = ()
        return True


logging.getLogger("strands.models.openai").addFilter(_ProviderLogLabel())


class OpenRouterChatModel(OpenAIModel):
    @asynccontextmanager
    async def _get_client(self):
        token = _openrouter_request.set(True)
        try:
            async with self._observed_client() as client:
                yield client
        finally:
            _openrouter_request.reset(token)

    @asynccontextmanager
    async def _observed_client(self):
        # Observe SDK-parsed response identities; leave transport, streaming and
        # tool parsing with Strands/OpenAI. This seam is pinned to Strands 1.57.2.
        self.response_identities = []
        async with super()._get_client() as client:
            def record(response):
                identity = {name: getattr(response, name) for name in ("id", "model", "provider")
                            if isinstance(getattr(response, name, None), str)}
                if identity and identity not in self.response_identities:
                    self.response_identities.append(identity)

            async def create(**request):
                response = await client.chat.completions.create(**request)
                if not request.get("stream"):
                    record(response)
                    return response

                async def observed():
                    async for chunk in response:
                        record(chunk)
                        yield chunk
                return observed()

            yield SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    @classmethod
    def format_request_messages(cls, messages, system_prompt=None, **kwargs):
        # Strands 1.57 already skips reasoningContent for Chat Completions, but warns
        # for every historical block on every call. Project a copy without those
        # unsupported blocks. Original memory and immutable audit records stay intact.
        projected = [{**message, 'content': [block for block in message['content']
                     if 'reasoningContent' not in block]} for message in messages]
        return super().format_request_messages(projected, system_prompt, **kwargs)
