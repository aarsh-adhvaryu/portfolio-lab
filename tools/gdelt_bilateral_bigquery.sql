-- GDELT 2.0 BILATERAL conflict and cooperation, daily, 2015-02-18 -> yesterday.
--
-- Written 2026-09-22. Who acted against whom: one row per (day, actor-1
-- country, actor-2 country), ISO-3 codes (USA, CHN, RUS, UKR, ISR, IRN, IND,
-- PAK...). Only pairs of two DIFFERENT coded countries, and only pairs with at
-- least 10 events that day, so the file stays near a million rows. Same
-- point-in-time key (day = UTC date of DATEADDED). Collected, not used.
--
-- Save results -> CSV (Google Drive), save as
-- data/gdelt/bilateral_backfill/gdelt_bilateral.csv, then run
--   python tools/ingest_gdelt_world.py bilateral

SELECT
  DIV(DATEADDED, 1000000)                          AS day,
  Actor1CountryCode                                AS a1,
  Actor2CountryCode                                AS a2,
  COUNT(*)                                         AS n_events,
  COALESCE(SUM(NumArticles), 0)                    AS n_articles,
  AVG(AvgTone)                                     AS mean_tone,
  AVG(GoldsteinScale)                              AS mean_goldstein,
  COUNTIF(QuadClass = 1)                           AS q1,
  COUNTIF(QuadClass = 2)                           AS q2,
  COUNTIF(QuadClass = 3)                           AS q3,
  COUNTIF(QuadClass = 4)                           AS q4,
  COUNTIF(EventRootCode IN ('16', '17'))           AS sanctions_coerce,
  COUNTIF(EventRootCode IN ('18', '19', '20'))     AS violence
FROM `gdelt-bq.gdeltv2.events`
WHERE
  DATEADDED >= 20150218000000
  AND DATEADDED < CAST(FORMAT_DATE('%Y%m%d', CURRENT_DATE()) AS INT64) * 1000000
  AND Actor1CountryCode != '' AND Actor2CountryCode != ''
  AND Actor1CountryCode != Actor2CountryCode
GROUP BY day, a1, a2
HAVING COUNT(*) >= 10
ORDER BY day, a1, a2;
