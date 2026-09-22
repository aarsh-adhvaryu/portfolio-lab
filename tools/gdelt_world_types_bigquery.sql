-- GDELT 2.0 WORLD daily EVENT TYPES by country, 2015-02-18 -> yesterday.
--
-- Written 2026-09-22. The world aggregate (gdelt_world_bigquery.sql) says HOW
-- MUCH conflict; this says WHAT KIND: one count column per CAMEO root code,
-- so a riot (14 protest) and an invasion (19 fight, 20 mass violence) are no
-- longer one number. Same rows as the world file (day x country), same
-- point-in-time key (day = UTC date of DATEADDED). Collected, not used.
--
-- ~1M rows x 22 columns (~100 MB): Save results -> CSV (Google Drive), then
-- save as data/gdelt/world_types_backfill/gdelt_world_types.csv and run
--   python tools/ingest_gdelt_world.py types

SELECT
  DIV(DATEADDED, 1000000)                            AS day,
  COALESCE(NULLIF(ActionGeo_CountryCode, ''), 'XX')  AS country,
  COUNTIF(EventRootCode = '01')    AS r01,      -- make public statement
  COUNTIF(EventRootCode = '02')    AS r02,      -- appeal
  COUNTIF(EventRootCode = '03')    AS r03,      -- express intent to cooperate
  COUNTIF(EventRootCode = '04')    AS r04,      -- consult
  COUNTIF(EventRootCode = '05')    AS r05,      -- engage in diplomatic cooperation
  COUNTIF(EventRootCode = '06')    AS r06,      -- engage in material cooperation
  COUNTIF(EventRootCode = '07')    AS r07,      -- provide aid
  COUNTIF(EventRootCode = '08')    AS r08,      -- yield
  COUNTIF(EventRootCode = '09')    AS r09,      -- investigate
  COUNTIF(EventRootCode = '10')    AS r10,      -- demand
  COUNTIF(EventRootCode = '11')    AS r11,      -- disapprove
  COUNTIF(EventRootCode = '12')    AS r12,      -- reject
  COUNTIF(EventRootCode = '13')    AS r13,      -- threaten
  COUNTIF(EventRootCode = '14')    AS r14,      -- protest
  COUNTIF(EventRootCode = '15')    AS r15,      -- exhibit force posture
  COUNTIF(EventRootCode = '16')    AS r16,      -- reduce relations (incl. sanctions)
  COUNTIF(EventRootCode = '17')    AS r17,      -- coerce
  COUNTIF(EventRootCode = '18')    AS r18,      -- assault
  COUNTIF(EventRootCode = '19')    AS r19,      -- fight
  COUNTIF(EventRootCode = '20')    AS r20      -- use unconventional mass violence
FROM `gdelt-bq.gdeltv2.events`
WHERE
  DATEADDED >= 20150218000000
  AND DATEADDED < CAST(FORMAT_DATE('%Y%m%d', CURRENT_DATE()) AS INT64) * 1000000
GROUP BY day, country
ORDER BY day, country;
