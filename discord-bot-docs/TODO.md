# TODO / Doporučené úpravy

- **Fix syntaxe** v `activity_hll_optimized.py`: u `@commands.Cog.listener()` je v jednom místě přebytečná `)`.
- **Přenést ID log kanálů** z `commands/log.py` do `config.py` (sjednocení nastavení).
- (Volitelně) **Reporty bez JSON**: přepsat `report.py`, aby bral DAU/MAU z Redis HLL (stejně jako analytický cog).
- Přidat `docker-compose.yml` pro bot + redis.
- Dopsat kompletní `vyzva.py` (v poskytnutém výpisu je poslední řádek zkrácený).
