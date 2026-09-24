# Boss Vào Lệnh V4.2.1

V4.2.1 is the five-result Prediction build with an always-on cloud mode and a password-protected iPhone control panel. The active Windows and cloud launchers no longer use the old analysis modes, inverse mode, confidence scoring, consensus thresholds, or Telegram control menus. By default, the five colors come from resolved BTC Up/Down 5m Prediction markets instead of BTCUSDT Futures candle colors.

## Active signal rule

Default source: `PREDICTION_SOURCE=predictfun`. Boss reads the resolved BTC Up/Down 5m market sequence used by Binance Prediction's Predict.fun-backed market. The newest resolved 5-minute round is color number five; the other four are the four consecutive rounds immediately before it. As soon as settlement is published, Boss evaluates those five colors and targets the following 5-minute round. `G` = UP/green, `R` = DOWN/red. The old Binance Futures M5 source remains only as an explicit diagnostic fallback with `PREDICTION_SOURCE=futures`.

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

## Telegram messages

At an M5 close, the previous signal is settled first. Telegram sends the WIN/LOSS result card first, then the new BUY card for the immediately following M5 candle when the latest five-candle sequence matches the table. Both cards show the current win/loss totals. The entry card always includes the just-closed live M5 as candle number five.

Example result:

```text
✅ THẮNG • MUA ĐỎ
⏰ Khung giờ: 10:00–10:05
🕯 Nến kết quả: 🔴 ĐỎ
💵 Lệnh 1: 1.00 USDT • P/L: +0.80 USDT
📊 Thắng: 7 • Thua: 3
```

Immediately after it, when the new five-candle group matches:

```text
🟢 MUA XANH
⏰ Khung giờ: 10:05–10:10
🕯 5 kết quả Prediction gần nhất: 🔴 🟢 🟢 🔴 🔴
💵 Lệnh 2: 2.00 USDT
📊 Thắng: 7 • Thua: 3
```

## Money sequence

The desktop panel has separate values for `Lệnh 1` and `Lệnh 2`.

- If a Lệnh 1 signal wins, the next matched signal uses Lệnh 2.
- After a Lệnh 2 result, the next matched signal returns to Lệnh 1.
- If Lệnh 1 loses, the next matched signal stays at Lệnh 1.
- A doji result is void and is excluded from the V/X history.

P/L uses the configured payout rate. A win adds `bet × payout_rate`; a loss subtracts the bet amount.

## Telegram check

The desktop panel now has a **TEST TELEGRAM** button. Press it after rebuilding. A successful test sends one manual diagnostic message to the configured Telegram chat and the panel shows an OK timestamp. If the bot token/chat ID is wrong or Telegram is unreachable, the exact error is shown in the panel and log.

## iPhone dashboard

V4.2.1 starts a read-only phone dashboard on port `8765` by default. The desktop panel shows the exact LAN address, for example:

```text
http://192.168.1.20:8765
```

Connect the iPhone and PC to the same Wi-Fi, open that address in Safari, then use **Share → Add to Home Screen**. The phone view contains the five latest Prediction colors, next signal, stake step, daily P/L and the 100-result V/X grid.

If Windows Firewall blocks the page, allow `BossVaoLenh.exe` on Private networks. The phone dashboard is read-only.

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
PREDICTION_SOURCE=predictfun
PREDICT_API_BASE=https://api.predict.fun
PREDICT_API_KEY=
MOBILE_ENABLED=1
MOBILE_PORT=8765
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

The cloud process uses the same result-first flow and the same Prediction-market source. The cloud phone dashboard is disabled by default; enable it only after configuring a firewall and HTTPS/reverse proxy.

## Tests

```bash
python -m unittest discover -s tests -v
```

`tests/test_pattern_v4.py` locks the 24 reference patterns and the Lệnh 1 → Lệnh 2 → Lệnh 1 progression. `tests/test_prediction_source_v41.py` locks the Prediction winner parsing and the `btc-updown-5m-<timestamp>` slug format.

## Important

The pattern table is a fixed rule supplied by the operator. The software records and applies that rule; it does not guarantee profitability or future market outcomes. Test with non-production funds before relying on it operationally.


## Always-on iPhone cloud mode

This is the recommended daily setup when the PC should stay off.

The architecture is:

```text
BTC Up/Down 5m Prediction -> Oracle Cloud Boss (24/7) -> Telegram
                                            -> iPhone web app
```

The cloud process is installed as a `systemd` service with `Restart=always` and is enabled at boot. The iPhone is only a remote screen/controller: turning the iPhone off, closing Safari, or turning the PC off does not stop the Boss.

Configure `.env.cloud`:

```env
CLOUD_TELEGRAM_BOT_TOKEN=...
CLOUD_TELEGRAM_CHAT_ID=...
CLOUD_TELEGRAM_STARTUP_TEST=1

CLOUD_PREDICTION_SOURCE=predictfun
CLOUD_PREDICT_API_BASE=https://api.predict.fun
CLOUD_PREDICT_API_KEY=...

CLOUD_MOBILE_ENABLED=1
CLOUD_MOBILE_HOST=0.0.0.0
CLOUD_MOBILE_PORT=8765
CLOUD_MOBILE_PASSWORD=choose-a-private-password
```

V4.2.1 Telegram is send-only, so the cloud and Windows builds may use the same Telegram bot token if desired.

Install or upgrade on Oracle Cloud:

```bash
bash deploy/oracle/install.sh
# later:
bash deploy/oracle/update.sh
```

Then verify the phone endpoint:

```bash
bash deploy/oracle/mobile_public.sh
```

The helper prints the server's public IPv4 URL. Oracle Cloud must allow inbound TCP to the configured mobile port (default `8765`). Once that ingress rule exists, the iPhone can open the URL using any Wi-Fi or 4G/5G connection; it does not need to be on the same network as the server or PC.

The iPhone panel is password protected. It can:

- display the latest five resolved Prediction colors;
- display the next BUY color and stake step;
- display P/L and 100 recent V/X results;
- change Lệnh 1, Lệnh 2, starting balance and payout;
- enable/disable Telegram sends;
- send a TEST TELEGRAM message.

For public Internet use, HTTPS through a reverse proxy/tunnel is preferable to plain HTTP. The built-in password prevents casual access but does not encrypt traffic by itself.


## Telegram credentials on Windows

Starting with V4.2.1, the Windows EXE does **not** require `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID` just to open. Boss opens normally even when Telegram has never been configured.

In the desktop panel:

1. Enter **Telegram Bot Token**.
2. Enter **Telegram Chat ID**.
3. Press **LƯU + TEST TELEGRAM**.
4. Boss stores the credentials in its persistent SQLite database and sends a test message immediately.
5. On later launches the two boxes may be left blank; the stored credentials continue to be used.

If Prediction data is temporarily unavailable, the desktop panel and Telegram setup remain alive and the market engine keeps retrying in the background.
