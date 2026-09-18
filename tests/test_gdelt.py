"""GDELT 2.0 column positions and the India filter (Phase 1 task 1.6)."""
import io
import zipfile
from datetime import date

import pandas as pd

from pflab.data import gdelt


def _row(**over):
    """A GDELT 2.0 export row: 61 tab-separated fields, codebook order."""
    f = [""] * 61
    f[0] = "1234567890"      # GLOBALEVENTID
    f[1] = "20260915"        # SQLDATE
    f[7] = "USA"             # Actor1CountryCode
    f[17] = "CHN"            # Actor2CountryCode
    f[26] = "043"            # EventCode
    f[28] = "04"             # EventRootCode
    f[29] = "1"              # QuadClass
    f[30] = "7.0"            # GoldsteinScale
    f[31] = "10"             # NumMentions
    f[32] = "2"              # NumSources
    f[33] = "5"              # NumArticles
    f[34] = "1.5"            # AvgTone
    f[51] = "4"              # ActionGeo_Type -- a 0-5 enum, NOT a country
    f[53] = "US"             # ActionGeo_CountryCode
    f[59] = "20260915120000"  # DATEADDED
    f[60] = "http://example.com/a"
    for k, v in over.items():
        f[int(k[1:])] = v
    return "\t".join(f)


def _zip(rows):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("20260915000000.export.CSV", "\n".join(rows) + "\n")
    return buf.getvalue()


def test_action_country_reads_column_53_not_51():
    """Regression: column 51 is ActionGeo_Type (0-5). Reading it as the country
    code matched no India rows at all and silently dropped 63% of the feed."""
    df = gdelt.parse_export(_zip([_row(f51="4", f53="IN")]))
    assert len(df) == 1
    assert df.loc[0, "action_country"] == "IN"


def test_event_located_in_india_is_kept_without_an_indian_actor():
    """Most domestic India news codes no actor country; the ActionGeo clause is
    the only thing that finds it."""
    df = gdelt.parse_export(_zip([_row(f7="", f17="", f53="IN")]))
    assert len(df) == 1


def test_indian_actor_is_kept_wherever_the_event_happened():
    a1 = gdelt.parse_export(_zip([_row(f7="IND", f53="US")]))
    a2 = gdelt.parse_export(_zip([_row(f7="USA", f17="IND", f53="US")]))
    assert len(a1) == 1 and len(a2) == 1


def test_unrelated_event_is_dropped():
    assert gdelt.parse_export(_zip([_row()])).empty


def test_numeric_columns_are_typed():
    df = gdelt.parse_export(_zip([_row(f53="IN")]))
    assert df.loc[0, "goldstein"] == 7.0
    assert df.loc[0, "avg_tone"] == 1.5
    assert int(df.loc[0, "quad_class"]) == 1
    assert int(df.loc[0, "n_articles"]) == 5


def test_column_map_matches_the_codebook():
    """Positions verified against a live export on 2026-09-16."""
    assert gdelt.KEEP[53] == "action_country"
    assert 51 not in gdelt.KEEP
    assert gdelt.KEEP[29] == "quad_class" and gdelt.KEEP[34] == "avg_tone"
    assert gdelt.KEEP[60] == "source_url"


def test_aggregate_of_an_empty_day_is_one_zero_row():
    out = gdelt.aggregate(pd.DataFrame(), date(2026, 9, 15))
    assert len(out) == 1 and out.loc[0, "n_events"] == 0


def test_aggregate_counts_quad_classes():
    df = gdelt.parse_export(_zip([_row(f53="IN", f29="1"), _row(f53="IN", f29="3")]))
    out = gdelt.aggregate(df, date(2026, 9, 15))
    assert out.loc[0, "n_events"] == 2
    assert out.loc[0, "q1"] == 1 and out.loc[0, "q3"] == 1
