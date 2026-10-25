"""When a job's slots fall, and which slot is the latest one at a given moment.

Times are the laptop's local wall clock (IST on the investor's machine); no timezone conversion happens
here. A job is due when its LATEST slot has no successful run since: after a sleep of three days it
runs once, for the latest slot, not three times. Jobs are idempotent and size their own look-back
from the last success, so one run still covers the gap.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Optional


@dataclass(frozen=True)
class Daily:
    hour: int
    minute: int = 0
    weekdays_only: bool = True

    def latest_slot(self, now: datetime) -> Optional[datetime]:
        d = now.date()
        for back in range(0, 8):
            day = d - timedelta(days=back)
            if self.weekdays_only and day.weekday() >= 5:
                continue
            slot = datetime.combine(day, time(self.hour, self.minute))
            if slot <= now:
                return slot
        return None


@dataclass(frozen=True)
class Interval:
    minutes: int
    start_hour: int = 0
    end_hour: int = 24          # slots strictly before this hour
    weekdays_only: bool = True

    def latest_slot(self, now: datetime) -> Optional[datetime]:
        for back in range(0, 8):
            day = (now - timedelta(days=back)).date()
            if self.weekdays_only and day.weekday() >= 5:
                continue
            start = datetime.combine(day, time(self.start_hour))
            end = datetime.combine(day, time(0)) + timedelta(hours=self.end_hour)
            limit = min(now, end - timedelta(seconds=1))
            if limit < start:
                continue
            n = int((limit - start).total_seconds() // (self.minutes * 60))
            return start + timedelta(minutes=n * self.minutes)
        return None
