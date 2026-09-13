# Component Selector V3.7.8

## Purpose
Choose the strongest eligible component/method for the next M5 trade while preserving the method's **original historical outcomes**.

## Rules
- Use up to 100 newest settled directional forecasts per method, after stats reset and strictly before the decision's open time.
- Require 30 WIN/LOSS samples.
- Settlement is binary: Close >= Open is GREEN/UP; Close < Open is RED/DOWN. Every directional forecast is therefore WIN or LOSS; no TIE is displayed. Neutral method forecasts are still excluded from selection.
- More original wins than losses: keep the method's current original direction; eligible only if its latest original outcome is LOSS.
- More original losses than wins: reverse only the direction sent to Telegram; eligible only if its latest original outcome is WIN.
- Never rewrite historical WIN/LOSS results when reversing a live order. This is critical so future selection can still detect consistently losing methods and invert them.
- Rank eligible methods by confidence first, then by sample quality and recent edge.

## Telegram
The selector may send the opposite direction from a method's raw forecast, but the method's own statistics must continue to use the raw forecast versus the real candle result.
