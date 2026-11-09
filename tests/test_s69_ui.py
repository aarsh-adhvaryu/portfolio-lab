"""S69: the dashboard shows the workflow in a REAL browser (headless Edge): a plan that waits for his yes with its approve button, the task table with owners and
dependencies, 'registered' that is not 'finished', a waiting task that says what resumes it, recommendations with their facts and what is missing, and the local
model's routing decisions. Synthetic profile; skipped where Edge is missing."""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from tests.test_s68_ui import NOW, server  # noqa: F401  (the fixture)
from tests import _edge
import os

pytestmark = [pytest.mark.ui, pytest.mark.skipif(not os.path.exists(_edge.EDGE), reason="Microsoft Edge is not installed here")]

PLAN = [{"key": "verify", "role": "research", "goal": "Verify the event from sources.", "promise": {"evidence": 1}, "depends_on": []},
        {"key": "calc", "role": "quant", "goal": "Compute the exposure.", "promise": {"calc": 1}, "depends_on": ["verify"]}]

