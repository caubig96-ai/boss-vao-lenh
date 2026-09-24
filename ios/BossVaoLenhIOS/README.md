# Boss Vào Lệnh — Native iOS

This folder contains the native SwiftUI iPhone app. It is not a Safari/PWA wrapper.

## What runs where

- **Oracle Cloud Boss** runs the Prediction engine 24/7.
- **Telegram** is sent by the cloud process.
- **iPhone app** is a native remote dashboard/controller.
- Turning off the PC, closing the iOS app, or turning off the iPhone does not stop the cloud engine.

## Requirements

To install a native iOS app, Apple requires code signing.

- Mac with Xcode 16+.
- iPhone with iOS 16+.
- Apple ID added to Xcode.
- A free Apple ID can install to a personal device for development, but provisioning may need periodic renewal.
- Apple Developer membership is the normal route for TestFlight/App Store and long-term distribution.

## Generate the Xcode project

This repository uses XcodeGen so the project stays readable in Git.

On a Mac:

```bash
brew install xcodegen
cd ios/BossVaoLenhIOS
xcodegen generate
open BossVaoLenhIOS.xcodeproj
```

In Xcode:

1. Select the **BossVaoLenhIOS** target.
2. Open **Signing & Capabilities**.
3. Select your Apple Team.
4. Change the bundle identifier if Xcode says it is already taken.
5. Connect the iPhone and press **Run**.

## First launch

Enter:

- **Boss Cloud URL**, for example `https://boss.example.com` or temporarily `http://SERVER_IP:8765`.
- **Cloud password** = `CLOUD_MOBILE_PASSWORD`.

The password is stored in the iOS Keychain. The server URL is stored in app preferences.

## Cloud requirement

The server must be reachable from the Internet. Boss Cloud V4.2.1+ accepts native app authentication on API calls using:

```http
Authorization: Bearer <CLOUD_MOBILE_PASSWORD>
```

The app uses:

- `GET /api/status`
- `POST /api/settings`
- `POST /api/test-telegram`

## HTTP vs HTTPS

The current project allows plain HTTP so it can connect directly to an Oracle public IP during setup. This is convenient but **not encrypted**.

For regular remote use, put the Boss endpoint behind HTTPS and then remove `NSAllowsArbitraryLoads` from the iOS Info.plist.

## Native app features

- 5 latest resolved BTC Up/Down 5m colors.
- Next BUY GREEN / BUY RED signal.
- Lệnh 1 / Lệnh 2 amount.
- Daily wins, losses, P/L and end balance.
- Latest 100 V/X results.
- Edit bet amounts, starting balance and payout.
- Enable/disable Telegram.
- TEST TELEGRAM button.
- Pull-to-refresh plus automatic foreground refresh every 2 seconds.

The app does not need to remain open. When it is closed, Oracle Cloud continues processing and Telegram remains the notification channel.
