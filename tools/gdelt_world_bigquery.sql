-- GDELT 2.0 WORLD daily aggregate by country, 2015-02-18 -> yesterday.
--
-- Written 2026-09-22 at Aarsh's request: shocks reach India from outside
-- (2008 came from US housing and credit), so the event record is collected
-- for every country, not only India. Collected, not used: no charter reads
-- it yet.
--
-- One row per (day, country) where the event took place. Same definitions as
-- tools/gdelt_bigquery.sql (day = UTC date of DATEADDED, i.e. publication:
-- point-in-time), plus `country` = ActionGeo_CountryCode (FIPS 10-4, e.g.
-- US, CH = China, UP = Ukraine, RS = Russia, IS = Israel, IR = Iran;
-- 'XX' = no location coded).
--
-- About a million rows (~70 MB): too big for "CSV (local file)". Use
-- Save results -> "CSV (Google Drive)", download it from Drive, and save it
-- as data/gdelt/world_backfill/gdelt_world_daily.csv. Then run
--   python tools/ingest_gdelt_world.py
-- If Drive is not offered, add `AND DATEADDED BETWEEN 2015...` year bounds,
-- run one year at a time, and save each as gdelt_world_<year>.csv in the same
-- folder: the loader reads every CSV there.

SELECT
  DIV(DATEADDED, 1000000)                          AS day,
  COALESCE(NULLIF(ActionGeo_CountryCode, ''), 'XX') AS country,
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
  DATEADDED >= 20150218000000
  AND DATEADDED < CAST(FORMAT_DATE('%Y%m%d', CURRENT_DATE()) AS INT64) * 1000000
GROUP BY day, country
ORDER BY day, country;
