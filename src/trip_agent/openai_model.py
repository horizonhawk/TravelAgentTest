"""Explicit optional-field behavior for the Strands Responses adapter."""

from strands.models.openai_responses import OpenAIResponsesModel


class TravelOpenAIResponsesModel(OpenAIResponsesModel):
    def _format_request(self, *args, **kwargs):
        request = super()._format_request(*args, **kwargs)
        for spec in request.get("tools", []):
            if spec.get("type") == "function":
                # Preserve omission/default semantics instead of server-side strict
                # normalization making optional fields mandatory. Runtime validation
                # and evidence checks still apply to every final response.
                spec["strict"] = False
        return request
