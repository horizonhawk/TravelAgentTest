from trip_agent.config import Profile
from trip_agent.models import build_model


def test_provider_factories_construct_without_network(monkeypatch):
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.setenv(key, "test-placeholder")
    openai = build_model(Profile(provider="openai", model_id="gpt-6.1-sol"))
    from strands.models.openai_responses import OpenAIResponsesModel
    assert isinstance(openai, OpenAIResponsesModel)
    assert openai.get_config()["stateful"] is False
    assert openai.get_config()["params"]["store"] is False
    anthropic = build_model(Profile(provider="anthropic", model_id="configured-claude"))
    assert type(anthropic).__name__ == "AnthropicModel"
    router = build_model(Profile(provider="openrouter", model_id="configured/router-model"))
    assert router.client_args["base_url"].rstrip("/") == "https://openrouter.ai/api/v1"
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    bedrock = build_model(Profile(provider="bedrock", model_id="configured-bedrock", region="us-west-2"))
    assert type(bedrock).__name__ == "BedrockModel"


def test_credentials_are_not_in_persisted_profile(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-value")
    profile = Profile(provider="openai", model_id="gpt-6.1-sol")
    assert "secret-value" not in profile.model_dump_json()
