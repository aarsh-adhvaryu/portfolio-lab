-- GDELT 1.0 India daily aggregate, 1979 -> 2015-12-31. INSPECTION ONLY.
--
-- Written 2026-09-22 at Aarsh's request, to measure how different GDELT 1.0
-- is from the 2.0 series E2-C uses. It is NOT an input to any charter:
-- E2-C §4 names GDELT 2.0 from 2015-02-18. Save the result to
--   data/gdelt/v1_backfill/gdelt_v1_india_daily.csv
-- -- a separate folder; nothing loads it into data/gdelt/agg/.
--
-- Why it is not the same series:
--   * Before April 2013 GDELT 1.0 is a BACKFILE, coded in 2013 from news
--     archives. There is no publication timestamp, so rows are dated by
--     SQLDATE (the day the event happened), not by DATEADDED as the 2.0
--     series is. That is not point-in-time.
--   * English only (2.0 adds the translingual feed), and the source list grows
--     roughly exponentially through the decades, so counts break at 2013 and
--     again at 2015. The 2015 overlap (Feb-Dec) is there to measure that.
--
-- Same filter and same columns as tools/gdelt_bigquery.sql, so the two CSVs
-- compare column for column.

SELECT
  SQLDATE                                          AS day,          -- YYYYMMDD, event date
  COUNT(*)                                         AS n_events,
  COALESCE(SUM(NumArticles), 0)                    AS n_articles,
  AVG(AvgTone)                                     AS mean_tone,
  AVG(GoldsteinScale)                              AS mean_goldstein,
  COUNTIF(QuadClass = 1)                           AS q1,
  COUNTIF(QuadClass = 2)                           AS q2,
  COUNTIF(QuadClass = 3)                           AS q3,
  COUNTIF(QuadClass = 4)                           AS q4
FROM `gdelt-bq.full.events`
WHERE
  SQLDATE BETWEEN 19790101 AND 20151231
  AND (
        Actor1CountryCode = 'IND'
     OR Actor2CountryCode = 'IND'
     OR ActionGeo_CountryCode = 'IN'
  )
GROUP BY day
ORDER BY day;
