"""Shared schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    """Base schema with ORM support."""

    model_config = ConfigDict(from_attributes=True)
