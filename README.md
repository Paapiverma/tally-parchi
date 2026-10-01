# Tally Parchi Sync System

An end-to-end mobile parchi order entry and TallyPrime synchronization platform.

## Architecture

- **`mobile_app/`**: Flutter mobile application (supports Android 5.0 to 15+) for sales reps. Features customer search autocomplete, stock items selector, live camera face verification with oval guide, real-time status badges (`PENDING`, `POSTING`, `SENT_TO_TALLY`, `FAILED`), 1-tap retry, and in-app OTA auto-updater.
- **`laptop_helper/`**: PyQt6 desktop assistant for accountants. Auto-detects the currently open Tally company, synchronizes masters (debtors and stock items) to Supabase, checks for voucher duplicates, and posts zero-value quantity-only Sales Vouchers into Tally via XML port 9000. Includes preview of customer face photos.

## Quickstart

### 1. Database
Run `laptop_helper/schema.sql` in your Supabase SQL editor.

### 2. Laptop Helper
1. Copy `laptop_helper/.env.example` to `laptop_helper/.env` and configure credentials.
2. In TallyPrime: F1 -> Settings -> Connectivity -> Client/Server: Both, Port: 9000.
3. In Tally Voucher Types: Alter -> Sales -> Allow zero-valued transactions = Yes.
4. Run `python main.py` or double-click `TallyParchiHelper.exe`.

### 3. Mobile App
Build release APK:
```bash
flutter build apk --release
```
Or install the pre-compiled APK on sales reps' Android devices.
