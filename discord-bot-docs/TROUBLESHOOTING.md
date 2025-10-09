# Ladění & řešení problémů

## Příkaz „nejde“
- Zkontroluj `COMMANDS_CONFIG` (enabled/admin_only) v `config.py`.
- Ověř role/oprávnění uživatele a bota v kanálu.

## Report nepřišel
- Sedí `REPORT_CHANNEL_ID`? Má bot právo psát do kanálu?
- Běží eventy? Zkus manuálně `*report`.

## HLL/Redis nepočítá
- Běží Redis? Sedí `CONFIG["REDIS_URL"]`?
- Máš zapnutý **Message Content Intent**?

## Slash `/log` nevidím
- První sync probíhá v `on_ready`. Počkej pár minut nebo restartuj bota.
- Bot musí mít právo `applications.commands`.

## Purge nesmaže nic
- Bot potřebuje **Manage Messages** + přístup do kanálu.
- Limit 1–100 zpráv. Filtr může být moc přísný.

## Emoji role nereaguje
- Sedí `CHANNEL_ID`, `ROLE_ID` a `EMOJI_COMBO` v souboru?
- Uživatel má oprávnění psát? Bot může přidávat roli?
