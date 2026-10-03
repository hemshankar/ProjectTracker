from typing import Optional

from pydantic import BaseModel


class BoardBudgetUpdate(BaseModel):
    capUsd: Optional[float] = None
