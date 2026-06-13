from datetime import datetime

from pydantic import BaseModel


class TimeRange(BaseModel):
    start: datetime
    end: datetime


class Page(BaseModel):
    limit: int = 50
    offset: int = 0
