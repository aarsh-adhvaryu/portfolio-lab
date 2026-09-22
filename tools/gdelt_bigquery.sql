-- GDELT 2.0 India daily aggregate, 2015-02-18 -> yesterday (E2-C §4, E2-B).
--
-- Aarsh runs this in the BigQuery console; `python tools/ingest_gdelt_backfill.py`
-- loads the result into data/gdelt/agg/, the same files the daily collector
-- (pflab/data/gdelt.py) writes.
--
-- Rewritten 2026-09-22. The first version exported every India EVENT (about
-- 25 million rows with URLs, several GB), which the console cannot download.
-- E2-C §4 asks for the daily aggregate, so BigQuery computes it here: about
-- 4,200 rows, a few hundred KB.
--
-- It reproduces gdelt.aggregate() exactly:
--   * a day is the UTC date of DATEADDED -- when GDELT published the event.
--     The live collector reads the 96 fifteen-minute files stamped with that
--     day, and each event's DATEADDED is its file's stamp. This is also the
--     point-in-time key: an event dated D was public on D. (SQLDATE, the day
--     the event happened, can be days or years earlier: never use it here.)
--   * India filter: Actor1 or Actor2 country 'IND' (ISO-3), or event located
--     in India, ActionGeo_CountryCode 'IN' (FIPS).
--   * n_events = rows; n_articles = SUM(NumArticles); mean_tone = AVG(AvgTone);
--     mean_goldstein = AVG(GoldsteinScale); q1..q4 = rows per QuadClass.
--   * today (UTC) is excluded, because it is still being filled.

SELECT
  DIV(DATEADDED, 1000000)                          AS day,          -- YYYYMMDD
  COUNT(*)                                         AS n_events,
  COALESCE(SUM(NumArticles), 0)                    AS n_articles,
  AVG(AvgTone)                                     AS mean_tone,
  AVG(GoldsteinScale)                              AS mean_goldstein,
  COUNTIF(QuadClass = 1)                           AS q1,
  COUNTIF(QuadClass = 2)                           AS q2,
  COUNTIF(QuadClass = 3)                           AS q3,
  COUNTIF(QuadClass = 4)                           AS q4
FROM `gdelt-bq.gdeltv2.events`
WHERE
  DATEADDED >= 20150218000000                      -- GDELT 2.0 begins here
  AND DATEADDED < CAST(FORMAT_DATE('%Y%m%d', CURRENT_DATE()) AS INT64) * 1000000
  AND (
        Actor1CountryCode = 'IND'
     OR Actor2CountryCode = 'IND'
     OR ActionGeo_CountryCode = 'IN'
  )
GROUP BY day
ORDER BY day;
