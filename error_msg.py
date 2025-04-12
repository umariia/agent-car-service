from langchain_core.messages import BaseMessage
from typing import Literal


class ErrorMessage(BaseMessage):
    type: Literal["error"] = "error"

    def __init__(self, content: str, **kwargs) -> None:
        super().__init__(content=content, **kwargs)
