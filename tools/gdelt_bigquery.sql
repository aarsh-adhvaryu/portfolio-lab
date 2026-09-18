-- GDELT 2.0 India backfill (Phase 1 task 1.6, E2-B / E2-C).
--
-- Aarsh runs this in the BigQuery console against the free public dataset and
-- drops the exported CSV in data/gdelt/backfill/. It mirrors exactly what
-- pflab/data/gdelt.py collects daily, so the backfill and the live feed share
-- one schema.
--
-- HOW TO RUN
--   1. console.cloud.google.com/bigquery, any project (the public dataset is
--      free to query; you pay only for bytes scanned, and the filters below
--      keep a full 2015-today pull well inside the free tier).
--   2. Paste this query, Run, then "Save results" -> CSV (or to Drive if the
--      result exceeds the 16 MB direct-download cap).
--   3. Save as data/gdelt/backfill/gdelt_india_events.csv
--
-- GDELT 2.0 starts 2015-02-18. There is no earlier history, so the E2 signal
-- cannot be tested before then; its real test is the live-forward period.
--
-- The India filter matches gdelt.py: either actor coded IND (ISO-3), OR the
-- event located in India (ActionGeo_CountryCode 'IN', FIPS). The third clause
-- is the one that matters -- it finds 63% of India events on its own, because
-- most domestic news codes no actor country.

SELECT
  GLOBALEVENTID                AS event_id,
  SQLDATE                      AS sqldate,
  Actor1CountryCode            AS a1_country,
  Actor2CountryCode            AS a2_country,
  EventCode                    AS event_code,
  EventRootCode                AS root_code,
  QuadClass                    AS quad_class,
  GoldsteinScale               AS goldstein,
  NumMentions                  AS n_mentions,
  NumSources                   AS n_sources,
  NumArticles                  AS n_articles,
  AvgTone                      AS avg_tone,
  ActionGeo_CountryCode        AS action_country,
  DATEADDED                    AS date_added,
  SOURCEURL                    AS source_url
FROM `gdelt-bq.gdeltv2.events`
WHERE
  _PARTITIONTIME IS NOT NULL                 -- skip the streaming buffer
  AND SQLDATE >= 20150218                    -- GDELT 2.0 begins here
  AND SQLDATE <= 20261231
  AND (
        Actor1CountryCode = 'IND'
     OR Actor2CountryCode = 'IND'
     OR ActionGeo_CountryCode = 'IN'
  )
ORDER BY SQLDATE, event_id;

-- ---------------------------------------------------------------------------
-- If the full pull is too large to export in one go, run it a year at a time
-- by editing the SQLDATE bounds, e.g. 20150218..20151231, and save each as
-- gdelt_india_events_<year>.csv in the same directory. The loader concatenates
-- whatever it finds there.
--
-- Daily aggregates are computed by pflab, not here, so that the backfill and
-- the live collector aggregate identically. If you would rather sanity-check
-- the volume before exporting, this returns one row per day:
--
--   SELECT SQLDATE, COUNT(*) AS n_events, SUM(NumArticles) AS n_articles,
--          AVG(AvgTone) AS mean_tone, AVG(GoldsteinScale) AS mean_goldstein
--   FROM `gdelt-bq.gdeltv2.events`
--   WHERE SQLDATE >= 20150218
--     AND (Actor1CountryCode = 'IND' OR Actor2CountryCode = 'IND'
--          OR ActionGeo_CountryCode = 'IN')
--   GROUP BY SQLDATE ORDER BY SQLDATE;
