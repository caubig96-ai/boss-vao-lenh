# Boss Vào Lệnh V4.0.0

V4 is a clean five-candle pattern build. The active Windows and cloud launchers no longer use the old analysis modes, inverse mode, confidence scoring, consensus thresholds, or Telegram control menus.

## Active signal rule

The tool reads official Binance Futures M5 candles for `SYMBOL`. After each 5-minute candle closes, it looks at the five most recent closed candle colors. A signal is sent only when those five colors match one of the 24 fixed rows below. `G` = green, `R` = red.

| 5 closed candles | Buy |
|---|---|
| RGGRR | R |
| GRRGR | R |
| GGRRR | G |
| RRGGR | G |
| RGGRG | G |
| GRRGG | G |
| GGRRG | R |
| RRGGG | R |
| RGGGR | G |
| RRRGR | R |
| GGGRR | G |
| GRRRR | R |
| RGRRR | G |
| GRGGR | R |
| RRGRR | R |
| GGRGR | G |
| RGGGG | G |
| RRRGG | R |
| GGGRG | G |
| GRRRG | R |
| RGRRG | G |
| GRGGG | R |
| RRGRG | R |
| GGRGG | G |

A doji candle or any sequence outside this table produces no Telegram signal.

## Telegram message

V4 sends only the entry signal. There are no startup cards, result cards, old mode menus, confidence cards, or follow-up alerts.

Example:

```text
🔴 MUA ĐỎ
⏰ Khung giờ: 10:05–10:10
🕯 5 nến vừa kết thúc: 🔴 🟢 🟢 🔴 🔴
💵 Lệnh 1: 1.00 USDT
```

## Money sequence

The desktop panel has separate values for `Lệnh 1` and `Lệnh 2`.

- If a Lệnh 1 signal wins, the next matched signal uses Lệnh 2.
- After a Lệnh 2 result, the next matched signal returns to Lệnh 1.
- If Lệnh 1 loses, the next matched signal stays at Lệnh 1.
- A doji result is void and is excluded from the V/X history.

P/L uses the configured payout rate. A win adds `bet × payout_rate`; a loss subtracts the bet amount.

## Desktop panel

The Windows UI displays:

- the five most recent closed M5 candle colors;
- the matched buy direction for the next M5 candle;
- the next time frame;
- the current Lệnh 1/Lệnh 2 amount;
- editable Lệnh 1, Lệnh 2, starting balance for the current day, and payout percentage;
- current-day P/L and estimated end-of-day balance;
- the previous completed day's balance and P/L;
- a 10×10 history grid for the latest 100 settled signals, with `V` for win and `X` for loss;
- recent detailed results under the grid.

Settings and history persist in SQLite at the normal application database path. The V4 tables use the `pattern_` prefix so old database tables do not interfere with the active V4 logic.

## Windows setup

Copy `.env.example` to `.env` and add your Telegram credentials:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
SYMBOL=BTCUSDT
BASE_BET=1
SECOND_BET=2
START_BALANCE=100
PAYOUT_RATE=0.80
TIMEZONE=Asia/Ho_Chi_Minh
APP_PASSWORD=123
```

Build:

```bat
build_windows.bat
```

The EXE is created at:

```text
dist\BossVaoLenh.exe
```

The desktop app starts in the Windows system tray. Open the tray icon and enter `APP_PASSWORD` to open the panel.

## Cloud

Cloud uses the same V4 pattern engine. Keep a separate Telegram bot token for cloud and Windows.

```bash
cp .env.cloud.example .env.cloud
nano .env.cloud
bash deploy/oracle/install.sh
```

The cloud process sends the same concise signal card and does not send the old mode/status/result cards.

## Tests

```bash
python -m unittest discover -s tests -v
```

`tests/test_pattern_v4.py` locks the 24 reference patterns and the Lệnh 1 → Lệnh 2 → Lệnh 1 progression so future edits cannot silently alter them.

## Important

The pattern table is a fixed rule supplied by the operator. The software records and applies that rule; it does not guarantee profitability or future market outcomes. Test with non-production funds before relying on it operationally.
