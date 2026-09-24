from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    """Base class for every API payload this example sends or receives."""

    model_config = ConfigDict(frozen=True)
