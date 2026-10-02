"""Validated options shared by the live ledger and historical model."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class VRSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

    mode: Literal['basic', 'skilled'] = 'basic'
    g: float = Field(default=10, gt=0)
    band: float = Field(default=0.15, gt=0, lt=1)
    fee: float = Field(default=0.0005, ge=0, lt=1)
    tick: float = Field(default=0.01, gt=0)
    cycle_days: int = Field(default=14, ge=1, le=365)
    pool_usage: float = Field(default=0.5, ge=0, le=1)
    periodic_flow: float = 0
