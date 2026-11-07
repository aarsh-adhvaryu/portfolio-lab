"""S79b item 15b: sentiment per (market, theme, day), the headlines the local model tagged, the theme exposure of the book and the calendar notes (versions 91-93)."""

MIGRATIONS = [
    (91, "sentiment_s79",
     "CREATE TABLE IF NOT EXISTS sentiment_s79 ("
     "market VARCHAR, theme VARCHAR, day DATE, "
     "tone_gdelt DOUBLE, tone_gdelt_z DOUBLE, tone_gdelt_n INTEGER, "
     "tone_country DOUBLE, tone_country_z DOUBLE, "
     "tone_model DOUBLE, tone_model_z DOUBLE, tone_model_n INTEGER, "
     "fear_vix DOUBLE, fear_vix_z DOUBLE, fear_pcr DOUBLE, fear_pcr_z DOUBLE, fear_skew DOUBLE, fear_skew_z DOUBLE, "
     "proxy_vol DOUBLE, proxy_vol_z DOUBLE, "
     "pos_flow DOUBLE, pos_flow_z DOUBLE, pos_fut DOUBLE, pos_fut_z DOUBLE, pos_dii DOUBLE, pos_dii_z DOUBLE, pos_dii_cash DOUBLE, pos_dii_cash_z DOUBLE, "
     "pos_oi DOUBLE, pos_oi_z DOUBLE, pos_breadth DOUBLE, pos_breadth_z DOUBLE, "
     "tone_score DOUBLE, fear_score DOUBLE, pos_score DOUBLE, combined DOUBLE, n_groups INTEGER, n_comp INTEGER, "
     "computed_at TIMESTAMP, PRIMARY KEY (market, theme, day));"
     "CREATE TABLE IF NOT EXISTS sentiment_tags_s79 ("
     "doc_key VARCHAR PRIMARY KEY, market VARCHAR, day DATE, headline VARCHAR, source VARCHAR, theme VARCHAR, tone_class VARCHAR, "
     "model VARCHAR, tagged_at TIMESTAMP);"),
    (92, "theme_exposure_s79",
     "CREATE TABLE IF NOT EXISTS theme_exposure_s79 ("
     "market VARCHAR, day DATE, scope VARCHAR, theme VARCHAR, isin VARCHAR, symbol VARCHAR, weight DOUBLE, sector_hit BOOLEAN, "
     "beta DOUBLE, t_stat DOUBLE, n INTEGER, carries BOOLEAN, contribution DOUBLE, computed_at TIMESTAMP);"),
    (93, "sentiment_event_notes_s79",
     "CREATE TABLE IF NOT EXISTS sentiment_event_notes_s79 ("
     "market VARCHAR, event_id VARCHAR, kind VARCHAR, theme VARCHAR, as_of DATE, text VARCHAR, values_json VARCHAR, created_at TIMESTAMP, "
     "PRIMARY KEY (market, event_id, kind, theme));"),
]
