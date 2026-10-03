from pydantic import BaseModel, Field

from .task_fields import MAX_CONTENT_CHARS


class TaskFieldWrite(BaseModel):
    content: str = Field(max_length=MAX_CONTENT_CHARS)
    # The version this edit was based on; a stale base is rejected with 409.
    baseVersion: int = Field(ge=0)


class TaskFieldRestore(BaseModel):
    version: int = Field(ge=1)
    baseVersion: int = Field(ge=0)
