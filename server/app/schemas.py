from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    messages: list[ChatTurn] = Field(min_length=1, max_length=40)
    @field_validator("messages")
    @classmethod
    def last_turn_is_user(cls, messages: list[ChatTurn]) -> list[ChatTurn]:
        if messages[-1].role != "user":
            raise ValueError("last message must be from the user")
        return messages
