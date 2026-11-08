# Lens candidate (STUB): lens_gap_fill

Status: STUB drafted by the agenda on 2026-10-08. NOT registered, no code, not live. It becomes a pre-registered protocol only when the lead commits a protocol file for it.

## Idea
Opening gaps and the fill: after a gap of more than one daily sigma at the open, how often the gap is closed within 1 and 5 sessions.

## Question to be registered
Does conditioning the centre of the next 1, 5 and 20 session return quantiles on this indicator improve the pinball loss of the combined forecast over the combination without it?

## Inputs (point in time: rows dated on or before the forecast date only)
daily open, prior close.

## Features
signed gap in sigmas; share of past gaps filled.

## Quantile output
The lens returns quantiles of the h-session return at fcast.protocol.LEVELS: the volatility forecaster's spread, its centre shifted by the mean of the standardised
outcomes that had already matured after the same state, shrunk to zero by n/(n+n0), capped. Fit by code on past data only. (This is the shape of lens_value_area.)

## Admission rule (the generic one, fcast/plugins.py)
Shadow (scored, Hedge-weighted, left out of the combined forecast) until at least 60 live sessions of the market AND the Diebold-Mariano t of the pinball loss of the
combination without it minus the combination with it reaches the learner counter's bar t_needed(N), with a positive mean.

## Before any run
The replay (2012-2021) may run the lens as a development read only. 2022-2025 is spent. Running this as a study counts in the learner's counter.
