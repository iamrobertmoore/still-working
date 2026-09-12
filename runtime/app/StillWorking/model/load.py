"""The model the deployed judgement layer runs on.

One id, in one place, overridable by environment so a redeploy can move it without a code
change. It is also the id every document in this repository quotes, and there is a test
asserting they still agree, because for a while they did not: the bundle ran Sonnet 4.5
through the global inference profile while the README, the architecture document and the
diagram all claimed 4.6, and the local agent defaulted to a third thing in a region this
account cannot invoke it in.

Which ids an account can actually invoke is not guessable from the model list. Run
`python tools/check_bedrock.py` to find out for yours.
"""
import os

from strands.models.bedrock import BedrockModel

MODEL_ID = os.environ.get("STILL_WORKING_MODEL",
                          "global.anthropic.claude-sonnet-4-5-20250929-v1:0")


def load_model() -> BedrockModel:
    """Get a Bedrock model client using the runtime's IAM credentials."""
    return BedrockModel(model_id=MODEL_ID, max_tokens=1600)
