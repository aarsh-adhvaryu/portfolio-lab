"""S79 item 8 tools: `forecast_now`, `forecast_scoreboard`, `fall_risk`. Read only; each works with {} and returns a harmless dict when the data is missing.
The numbers are the code's (pinball scores, weights, Brier); the verdict is refused until 60 live sessions (fcast/score.py)."""
from __future__ import annotations

import json

from pflab.hq.tools import Ctx, Tool, _i, _s

MARKET = _s("The market: IN (NIFTY 50) or US (S&P 500). Default IN.", enum=("IN", "US"))


def _market(a: dict) -> str:
    m = str(a.get("market") or "IN").upper()
    return m if m in ("IN", "US") else "IN"


def forecast_now(ctx: Ctx, a: dict) -> dict:
    try:
        from pflab.fcast import protocol as P, score as S
        con, market = ctx.con, _market(a)
        hs = [int(a["horizon"])] if a.get("horizon") else list(P.HORIZONS)
        row = con.execute("SELECT max(as_of) FROM forecasts_s79 WHERE market=? AND source='live'", [market]).fetchone()
        if not row or row[0] is None:
            return {"market": market, "note": "no live forecast made yet", "source": "fcast/run.py"}
        asof = row[0]
        from pflab import markets
        idx = markets.get(market).index
        out = {"market": market, "subject": idx, "made_at_close_of": str(asof), "levels": list(P.LEVELS), "horizons": {}}
        for h in hs:
            rows = con.execute("SELECT forecaster, quantiles_json, matures FROM forecasts_s79 WHERE market=? AND source='live' AND as_of=? AND subject=? "
                               "AND horizon_sessions=?", [market, asof, idx, h]).fetchall()
            if not rows:
                continue
            q = {f: {k: round(v * 100, 3) for k, v in json.loads(j).items()} for f, j, m in rows}
            w = con.execute("SELECT forecaster, weight, n FROM forecaster_weights WHERE market=? AND source='live' AND horizon_sessions=? "
                            "AND as_of=(SELECT max(as_of) FROM forecaster_weights WHERE market=? AND source='live' AND horizon_sessions=?)",
                            [market, h, market, h]).fetchall()
            sb = S.scoreboard(con, market, "live")["horizons"].get(str(h), {})
            out["horizons"][str(h)] = {
                "matures": str(rows[0][2]), "return_quantiles_percent": q.get(P.COMBINED),
                "each_forecaster_percent": {f: v for f, v in q.items() if f != P.COMBINED},
                "weights": {f: round(wt, 3) for f, wt, _ in w} or "uniform (no outcome has matured yet)",
                "weight_updates": int(w[0][2]) if w else 0,
                "live_scored": sb.get("live_sessions", 0), "scores": sb.get("forecasters", {}), "verdict": sb.get("verdict", {}).get("status")}
        out["note"] = "quantiles are the percent return from the close of the date above to the maturity; 10th to 90th is the 80% range"
        out["source"] = "fcast/run.py (hedge of code forecasters; weights by pinball loss)"
        return out
    except Exception as e:
        return {"error": repr(e)[:200], "note": "forecasts could not be read"}


def forecast_scoreboard(ctx: Ctx, a: dict) -> dict:
    try:
        from pflab.fcast import score as S
        src = a.get("source") if a.get("source") in ("live", "replay") else "live"
        out = S.scoreboard(ctx.con, _market(a), src)
        out["source_note"] = "fcast/score.py: pinball loss vs naive, 80% coverage; live sessions toward the 60 needed for any verdict (a replay never counts)"
        return out
    except Exception as e:
        return {"error": repr(e)[:200], "note": "scoreboard could not be read"}


def fall_risk(ctx: Ctx, a: dict) -> dict:
    try:
        from pflab.fcast import fall_risk as FR
        src = a.get("source") if a.get("source") in ("live", "replay") else "live"
        out = FR.status(ctx.con, _market(a), src)
        out["source_note"] = "fcast/fall_risk.py: a probability scored by Brier; not a date and not a call to sell"
        return out
    except Exception as e:
        return {"error": repr(e)[:200], "note": "fall risk could not be read"}


_SRC = _s("live (default) or replay (2012-2021 development read, never evidence)", enum=("live", "replay"))
TOOLS = [
    Tool("forecast_now", "read", "The latest combined forecast (quantiles of the return over 1, 5 and 20 sessions) for a market's index, each code forecaster's "
         "weight and score, and whether the 60 live sessions needed for a verdict exist yet.",
         {"market": MARKET, "horizon": _i("Horizon in sessions: 1, 5 or 20 (default all).", 1, 20)}, (), forecast_now),
    Tool("forecast_scoreboard", "read", "How the forecasts have done: pinball loss against the naive forecast, how often the 80% range held, live sessions so far "
         "of the 60 needed (no verdict before that).", {"market": MARKET, "source": _SRC}, (), forecast_scoreboard),
    Tool("fall_risk", "read", "The probability that the market's index falls at least 5% under its 60-session high within 20 sessions: raw and calibrated, how many "
         "past outcomes calibrate it, its Brier score. A probability, never a date.", {"market": MARKET, "source": _SRC}, (), fall_risk),
]
