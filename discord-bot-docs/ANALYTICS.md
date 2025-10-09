# Analytika (Redis HLL + Heavy-Hitters)

## Co se počítá
- **DAU** – denní unikátní uživatelé (per guild, per den) přes HyperLogLog.
- **WAU/MAU** – rollující unikáty přes `PFMERGE` do dočasného klíče.
- **Heavy-hitters** – přibližné top uživatelé/kanály *dnes* (v RAM, Space-Saving).

## Redis klíče
- `hll:dau:{guild_id}:{YYYYMMDD}` – denní HLL.
- `_tmp:hll:{guild_id}:{YYYYMMDD}:{days}` – dočasný merge pro WAU/MAU (TTL ~30s).
- `hll:cfg:logchan:{guild_id}` – uložení ID kanálu pro heartbeat log.

## Příkazy
- `*dau [N]` / `*wau` / `*mau [window]`
- `*anloghere` – nastav kanál pro heartbeat embed (obsahuje DAU, queue, enqueued/written, drops).
- `*topusers [N]`, `*topchannels [N]` – dnešní heavy-hitters (orientační).

## Retence
- `CONFIG["RETENTION_DAYS"]` (např. 40) – HLL klíče mají TTL cca **dny × 86400 s**.

## Tipy
- HLL je přibližný (chyba řádu jednotky procent). Pro přesné počty používáme sety/DB (dražší).
