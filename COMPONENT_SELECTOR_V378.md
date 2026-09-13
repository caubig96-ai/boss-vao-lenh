# V3.7.8 — six independent candle methods

The six formulas in candle_color_model.py are unchanged. Each M5 persists all six
probabilities and their original directions in component_predictions BEFORE the
target candle closes. Neutral sources (distance from 0.5 < 0.01) do not become
directional trades. Invalid or missing probabilities are ineligible.

## Selection contract

- Use up to 100 newest settled directional forecasts per method, after stats reset
  and strictly before the decision's open time. Require 30 WIN/LOSS samples.
- Settlement is binary: Close >= Open is GREEN/UP; Close < Open is RED/DOWN.
  Every directional forecast is therefore WIN or LOSS; no TIE is displayed.
  Neutral method forecasts are still excluded from selection.
- More original wins than losses: keep the method's current original direction;
  eligible only if its latest original outcome is LOSS.
- More original losses than wins: reverse only the direction sent to Telegram;
  eligible only if its latest original outcome is WIN (the inverse side just lost).
- Equal wins/losses: keep the original direction only after an original LOSS.
- Rank eligible methods by original win rate for normal candidates and original
  loss rate for inverse candidates; ties prefer more decided samples, then stable
  method order: knn, sequence, body, close_position, wick, regime.
- No eligible method: KHÔNG MUA. Persist all six forecasts, but create no selected
  signal and do not advance money management for this session.
- The old global inverse toggle and agreement X/6 entry threshold do not apply.
  Old Telegram toggle callbacks are acknowledged without modifying selection.

The latest-outcome filter is a user-requested heuristic, NOT a claim that a loss
makes a subsequent win more probable. A ranking percentage is historical, not a
calibrated next-trade probability. Validate out-of-sample with realistic payout
before relying on the strategy; unit tests do not establish profitability.

## Immutable raw results and separate executed results

component_predictions.result ALWAYS scores raw_direction against official M5
open/close, including unselected methods. signals.direction/result/PnL represent
the selected executed direction. Example: original UP, sent DOWN, red candle:
method LOSS, executed WIN. Never feed the executed WIN back into method ranking.

component_decisions freezes the pre-decision statistics, selected method, raw and
sent directions, stake and enable state. Repeated decisions reuse this snapshot.
Old release color_predictions and signals are preserved; old aggregate results
are NOT treated as per-method history. A new installation/upgrade warms up from
new forecasts; after 30 decisive M5s a method may qualify (at least ~150 minutes).
Stats reset excludes older raw forecasts; it does not rewrite/delete results.
Pending method outcomes recover from official closed candles in the database.

## Delivery and rollout

Windows build uses desktop_v378.pyw; cloud_v3.py imports runtime_v378. Cloud and
Windows keep separate credentials/databases and each learns its own history.
Existing SQLite Telegram claim guards are reused. They prevent normal duplicate
processing, but cannot promise exactly-once delivery if Telegram accepts a send
and the process dies before recording the response. Run only one process per DB.

Run `python -m unittest discover -s tests -v`. Regression coverage includes raw
vs executed scoring, all-method recording, 50/50, inverse ranking, latest-result
filters, neutral/invalid inputs, sample/window/reset boundaries, duplicate calls,
DB recovery, disabled old toggle and matching Windows/cloud runtime wiring.
Windows packaging and live cloud/Telegram smoke tests must run in their actual
environments before deployment. No automatic merge or deployment is performed.
