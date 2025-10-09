# Měsíční reporty

- **Kdy:** 1. den v měsíci 00:05 UTC – za **předchozí** měsíc.
- **Kam:** `REPORT_CHANNEL_ID` (fallback na `CONSOLE_CHANNEL_ID`, pokud není).

## Data
- `data/member_counts.json` – měsíční počty *joins*/*leaves* (z `on_member_join/remove`).
- `data/active_users.json` – denní set uživatelů, kteří poslali zprávu (z `on_message`).

## Výpočet
- **Průměrné DAU** – aritmetický průměr denních počtů (ze setů).
- **MAU** – velikost unie uživatelů za celý měsíc.
- **DAU/MAU %** – průměrné DAU / MAU × 100.

## Embed
- Titulek „Server Report — \<český měsíc\> \<rok\>“.
- Pole: Noví členové, Odchody, Celkem členů, Průměrné DAU, MAU, DAU/MAU, Boti, Lidé, Online, počty kanálů/rolí.
- Footer: přesné pokryté období + čas vygenerování v Europe/Prague.
