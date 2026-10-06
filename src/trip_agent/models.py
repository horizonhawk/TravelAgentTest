"""The only module that constructs provider-specific model adapters."""

import os

from .config import AppError, Profile, check_profile


def build_model(profile: Profile):
    problems = check_profile(profile)
    if problems:
        raise AppError(" ".join(problems))
    if profile.provider == "openai":
        from .openai_model import TravelOpenAIResponsesModel
        return TravelOpenAIResponsesModel(model_id=profile.model_id, stateful=False,
                                    client_args={"api_key": os.environ[profile.credential_env],
                                                 "timeout": profile.timeout_seconds, "max_retries": 0},
                                    params={"store": False})
    if profile.provider == "openrouter":
        from .openrouter_model import OpenRouterChatModel
        client_args = {"api_key": os.environ[profile.credential_env], "timeout": profile.timeout_seconds,
                       "max_retries": 0}
        client_args["base_url"] = "https://openrouter.ai/api/v1"
        params = {"extra_body": {"provider": {"require_parameters": True}}}
        return OpenRouterChatModel(model_id=profile.model_id, client_args=client_args, params=params)
    if profile.provider == "anthropic":
        from strands.models.anthropic import AnthropicModel
        return AnthropicModel(model_id=profile.model_id, max_tokens=4096,
                              client_args={"api_key": os.environ[profile.credential_env],
                                           "timeout": profile.timeout_seconds, "max_retries": 0})
    import boto3
    from botocore.config import Config
    from strands.models import BedrockModel
    session = boto3.Session(profile_name=profile.aws_profile, region_name=profile.region)
    return BedrockModel(model_id=profile.model_id, boto_session=session,
                        boto_client_config=Config(connect_timeout=10, read_timeout=profile.timeout_seconds,
                                                  retries={"total_max_attempts": 1}))
