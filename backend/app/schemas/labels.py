from typing import Literal

from pydantic import BaseModel, Field


class Label(BaseModel):
    """A box in normalised YOLO form (centre x/y, width, height; all 0..1)."""

    class_id: int = Field(ge=0)
    cx: float = Field(ge=0, le=1)
    cy: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)
    origin: Literal["model", "human"] = "human"
    conf: float | None = None


class LabelsIn(BaseModel):
    labels: list[Label] = Field(max_length=500)
