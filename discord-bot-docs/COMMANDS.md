# Příkazy a chování podle modulů

## Core (`bot.py`)
- Start logy do `CONSOLE_CHANNEL_ID` (chunkuje dlouhé zprávy).
- Načítá všechny cogy v `commands/`.
- **Globální check** čte `COMMANDS_CONFIG` (enabled/admin_only).

---
## Nápověda (`commands/help.py`)

* Nahrazuje výchozí Discord `help` systém (ten je v `bot.py` odstraněn pomocí `bot.remove_command("help")`).
* Hybridní příkaz — dostupný jako `*help` i `/help`.
* Načítá se automaticky jako Cog `HelpCustom`.

### Prefix příkazy (`*help`)

```
*help
*help <příkaz>
*help <kategorie>
```

* Zobrazí přehled všech dostupných příkazů a kategorií.
* Umožňuje zobrazit detailní nápovědu ke konkrétnímu příkazu nebo celé skupině.
* Umí stránkování pomocí `HelpPaginator` (tlačítka „◀️ ▶️ Zavřít“).

### Slash příkaz (`/help`)

```
/help
/help příkaz:<název>
```

* Identické chování jako prefix verze.
* Slash varianta se **registruje ihned po startu** díky `bot.tree.copy_global_to(guild=...)`.

### Embed výstup

* Automaticky rozděluje příkazy podle kategorií (název Cog = sekce).
* Každý příkaz se zobrazuje jako:

  ```
  *status      – stav služby
  *report      – měsíční report
  ```
* Barvy a rozložení lze měnit v metodě `HelpCustom.format_help_for()`.

### Třídy

* **`HelpCustom`** – hlavní třída, dědí z `commands.HelpCommand`.
* **`HelpPaginator`** – interní view pro stránkování embedů.

### Chování

* Prefixové i slash příkazy sdílí stejný embed systém.
* Pokud je příkaz v `COMMANDS_CONFIG` vypnutý (`enabled=False`), v helpu se nezobrazí.
* Administrátorské příkazy (`admin_only=True`) jsou označeny 🔒.

---

## Logování (`commands/log.py`)
- Dva log kanály (ID jsou v souboru): **MAIN** a **PROFILE**.
- Perzistence: `data/log_config.json` (nastavení), `data/member_cache.json` (cache).
- Slash **group**: `/log`
  - `/log status` – stav, metriky, detaily
  - `/log toggle <typ|all> <true/false>` – granularita (messages/members/channels/roles/voice/…)

Loguje:
- Členy (join/leave/update, role, timeout, pending…), profily (globálně)
- Kanály (create/update/delete/overwrites), vlákna, role, emoji/stickers
- Invites, webhooks, integrace, stage, scheduled events, reactions
- Moderaci a vybrané audit log akce
- (volitelně) presence změny

---

## Měsíční reporty (`commands/report.py`)
- Automaticky 1. den v měsíci → **report za předchozí měsíc** do `REPORT_CHANNEL_ID`.
- Manuálně: `*report` (na `GUILD_ID`).
- Data:
  - `data/member_counts.json` – joins/leaves po měsících (počítá `on_member_join/remove`)
  - `data/active_users.json` – denní set aktivních userů (počítá `on_message`)
- Metriky: Noví členové, Odchody, Celkem, Průměrné **DAU**, **MAU**, **DAU/MAU%**, Boti/Lidé, Online, počty kanálů/rolí.

---

## Analytika HLL (`activity_hll_optimized.py`)
Příkazy (typicky potřebují `manage_guild`):
- `*dau [days_ago=0]` – DAU pro den
- `*wau` – 7d rolling
- `*mau [window_days=30]` – N-denní rolling (N ≤ retention)
- `*anloghere` – nastav kanál pro heartbeat log
- `*topusers [N]`, `*topchannels [N]` – „dnešní“ heavy-hitters (Space-Saving, RAM only)

Konfigurace v souboru (`CONFIG = { ... }`): `REDIS_URL`, retenční dny, cooldowny, TOP_K atd.

---

## Hromadné DM (`commands/notify.py`) – admin
```
*notify "zpráva" [@role|role_id|ALL] [--skip @uživatel @role 123...]
```
- Posílá DM **velmi opatrně** (90±30 s mezi uživateli, concurrency=1, retry).
- Výsledky v CSV jako příloha do `CONSOLE_CHANNEL_ID`.
- `DRY_RUN = True` → jen simulace.

---

## Verifikace (`commands/verification.py`)

Systém pro ověřování nových uživatelů pomocí DM a kódu.

### Slash příkazy (`/verify`)
- `/verify send user:@User` – Pošle uživateli DM s ověřovacím kódem.
- `/verify resend user:@User` – Znovu pošle kód (alias pro send).
- `/verify approve user:@User` – Manuálně ověří uživatele (odebere roli).
- `/verify status user:@User` – Zobrazí info o uživateli (role, stáří účtu, bezpečnost).
- `/verify ping` – Pošle testovací DM tobě.
- `/verify suspicious` – Zobrazí log podezřelých aktivit (rate limits, failed checks).

### Konfigurace (`/verifysettings`)
- `/verifysettings setpassword password:<heslo>` – Nastaví bypass heslo.
- `/verifysettings setmaxattempts attempts:<N>` – Počet pokusů před zamčením.
- `/verifysettings setaccountage days:<N>` – Min. stáří účtu.
- `/verifysettings requireavatar required:<True/False>` – Vyžadování avatara.
- `/verifysettings view` – Zobrazí aktuální nastavení.
- `/verifysettings reset` – Reset do výchozího stavu.

### Automatizace
- **Při joinu**:
  - Kontrola bezpečnosti (stáří účtu, avatar).
  - Přiřazení "unverified" role.
  - Odeslání DM s kódem `VERIFICATION_CODE`.
  - Logování do `MOD_CHANNEL_ID`.
- **Po ověření**:
  - Odebrání role.
  - Uvítací zpráva do `WELCOME_CHANNEL_ID`.

---

## Hromadná re-verifikace (`commands/reverification.py`) – admin

Nástroj pro hromadné ověření stávajících uživatelů (např. při změně pravidel).

### Slash příkazy (`/reverify`) Group
- `/reverify status [role]` – Statistiky (kolik lidí má roli).
- `/reverify preview [role]` – Náhled, kdo dostane DM.
- `/reverify run [role] [code] [dm_text] ...` – Spustí hromadné rozesílání DM.
  - Smart queue (batching, delay, error handling).
- `/reverify resend user:@User` – Znovu pošle kód jednotlivci.
- `/reverify ping` – Testovací zpráva tobě.

- **Status & Logy**: Posílá progress bar a výsledky do kanálu a mod logu.

---

## Čištění (`commands/purge.py`) – manage_messages
```
*purge <množství 1–100> [@uživatel] [slovo]
```
- Najde přesně N odpovídajících zpráv (prochází až ~1000), hromadně smaže.

---

## Status embedy (`commands/status.py`) – manage_messages
```
*status [kód|stav] [služba] (podrobnosti)
```
- Kódy `1..11` mapují na stavy (online/údržba/výpadek/…).
- Mazání příkazové zprávy, cooldown, hezký barevný embed.

---

## Emoji Challenge (`commands/emojirole.py`) – admin
Automatický systém odměn za poslání správné kombinace emoji v určeném kanále.

### Nastavení
**Slash příkazy** (`/challenge`):
```
/challenge setup role:@Role channel_name:<#kanál> emojis:"🍁 :strongdoge: 🔥"
/challenge show                    – zobrazí aktuální konfiguraci
/challenge settings                – nastavení chování (react_ok, reply_on_success, require_all)
/challenge messages add text:"..."  – přidá vlastní zprávu pro úspěch
/challenge messages list           – seznam všech zpráv
/challenge messages clear          – smaže všechny zprávy
/challenge clear                   – smaže celou konfiguraci
```

**Prefix příkazy** (`*challenge`):
```
*challenge setup role:@Role channel_name:<#kanál> emojis:"🍁 :strongdoge: 🔥"
*challenge show
*challenge messages add text:"Vítej!"
*challenge messages list
*challenge messages clear
*challenge clear
```

### Chování
- **Úspěšná kombinace**:
  - Bot zareaguje ✅
  - Přidá roli uživateli (pokud ji ještě nemá)
  - Odpoví náhodnou zprávou z 30 přednastavených (nebo vlastních)
  
- **Ostatní zprávy**: Bot je tiché ignoruje (žádná reakce, žádná odpověď)

### Formát emoji
- **Unicode emoji**: `🍁 🔥 💪`
- **Custom emoji**: `:strongdoge:` nebo `<:strongdoge:123456789>`
- **Kombinované**: `🍁 :strongdoge: 🔥`

### Nastavení
- `require_all: true` – musí obsahovat všechna emoji (výchozí)
- `require_all: false` – stačí alespoň jedno emoji
- `react_ok: true` – reaguje checkmarkem na úspěch
- `reply_on_success: true` – posílá náhodnou zprávu

### Datové soubory
- `data/challenge_config.json` – konfigurace per guild (role, kanál, emoji, zprávy)

### Přednastavené zprávy (30)
Při úspěšné kombinaci bot vybere náhodně z těchto zpráv:
- Vítej ve výzvě! ✅
- Gratuluji, máš to! 🔥
- Achievement unlocked! 🏅
- Beast mode activated! 🐺
- Level up! 📈
- ... a dalších 25 variací

---


## Výzvy (`commands/vyzva.py`) – admin
```
*vyhodnotit_vyzvu [#kanál|-] [vypis=true/false] [filtr|photo|-]
                   [mode=days/fotosum/weekly] [interval]
                   [počet role] [počet role] ...
```
- **days** – počet dní s aktivitou
- **fotosum** – počet příspěvků s fotkou (vyžaduje filtr `photo`)
- **weekly** – po sobě jdoucí X-denní intervaly s aktivitou
- Může **přidělovat role** po dosažení prahů.

---

## Adventní kalendář (`commands/calendar.py`) – admin

Interaktivní kalendář s denními odměnami (role, obrázky, texty).

### Slash příkazy
- `/calendar_create` – Wizard pro vytvoření nového kalendáře.
- `/calendar_admin` – Hlavní dashboard pro správu.
  - Úprava dnů (text, odměna, obrázek).
  - Nastavení broadcastu (připomínky).
  - Statistiky otevření.
- `/calendar_delete` – Hromadné mazání kalendářů.

### Funkce
- **Databáze**: SQLite (`data/calendar.db`).
- **Odměny**: Text, odkaz, role, nebo obrázek (DM).
- **Logika**:
  - Nelze otevřít budoucí dny (pokud není test_mode).
  - Každý uživatel může otevřít den jen jednou.
  - Broadcast task připomíná neotevřená okénka.

---

# Echo / Say (hybridní příkaz)

Jednoduchý utilitní příkaz pro „přeříkání“ textu do aktuálního nebo jiného kanálu – se stejným chováním dostupný jako prefixový `*echo`/`*say` a slash `/echo`/`/say`. Umí poslat až 3 přílohy, potlačit @mentions a pohodlně vybrat kanál přes autocomplete.

## Rychlý přehled

* **Cesty k příkazu:**

  * Prefix: `*echo`, aliasy `*say`, `*repeat`
  * Slash: `/echo`, alias `/say`
* **Cílový kanál:** volitelně jako ID, název (`general`), nebo mention (`<#1234567890>`). Slash varianta podporuje **autocomplete** (max 25 návrhů).
* **Přílohy:** až 3 soubory (u slash přes parametry `file1..3`, u prefixu přes přílohy zprávy).
* **Mentions:** výchozí chování **zakazuje** všem @mentions (`no_mentions=True`). Lze vypnout.
* **Soukromé odpovědi:** u slash lze použít `hide=True` → pošle se jako *ephemeral*.

## Syntaxe a příklady

### Prefix

```txt
*echo "Ahoj světe!"
*echo "Ahoj z ved vedle!" <#kanál>
*echo "Pozdrav do #oznámení" oznámení no_mentions=false
```

> U prefixu se **přílohy** přikládají k původní zprávě. Po úspěchu je příkazová zpráva smazána. Text nesmí být prázdný.

### Slash

```txt
/echo text:"Ahoj světe!"
/echo text:"Report" channel:"#oznámení" file1:<soubor.pdf>
/echo text:"Tichá zpráva" hide:true
/say  text:"Alias na echo" no_mentions:false
```

> U slashe se soubory před odesláním stáhnou; při odeslání do jiného kanálu dostanete potvrzení „✅ Odesláno do …“.

## Parametry

* `text: str` – povinný, nesmí být prázdný.
* `channel: Optional[str]` – cílový kanál (ID, název, `<#mention>`). Není-li uveden, použije se aktuální.
* `hide: bool` – **jen slash**; pošle odpověď jako *ephemeral* (skrytou).
* `no_mentions: bool` – když `True` (výchozí), **zakáže všechny mentions** přes `AllowedMentions.none()`.
* `file1..file3: Attachment` – až 3 přílohy (**slash**). U prefixu vezme přílohy z příkazové zprávy.

## Chování a okrajové situace

* **Přeposlání do jiného kanálu:**
  Pokud `channel` ukazuje na jiný kanál než aktuální, zpráva se odešle tam; u slash příkazu dostanete soukromé potvrzení.
* **Mazání příkazové zprávy (prefix):**
  Po úspěchu se původní `*echo` zpráva smaže, aby nezůstával „šum“.
* **Oprávnění a chyby:**

  * Při chybě oprávnění (`discord.Forbidden`) dostanete stručnou chybovou hlášku (u slashe *ephemeral*, u prefixu s `delete_after`).
  * U nedostupného kanálu / špatného formátu kanálu se zpráva pošle do aktuálního kanálu (pokud je to možné).
* **Limity:** max. 10 stažených příloh v interní metodě (použito konzervativně na 3 veřejné parametry).

## Autocomplete kanálů (slash)

Parametr `channel` nabízí až 25 návrhů textových kanálů podle podřetězce (case-insensitive). Hodnota se vrací jako `<#id>`, takže funguje i při přejmenování kanálu.

## Bezpečnost mentions

Výchozí `no_mentions=True` chrání před nechtěným pingováním rolí/uživatelů. Pokud opravdu potřebujete pingovat, přepněte na `no_mentions:false`. Interně se používá:

* `AllowedMentions.none()` (bez pingů)
* `AllowedMentions.all()` (povolí pingy)

## Požadovaná oprávnění bota

* **V cílovém kanálu:** `Send Messages`, `Attach Files` (pokud posíláte soubory), případně `Embed Links`.
* **Pro prefixovou verzi:** `Manage Messages` (volitelné – k smazání příkazové zprávy).

## Integrace s projektem

* Příkaz je **hybridní** (funguje přes prefix i slash) a respektuje globální checky (např. `COMMANDS_CONFIG`: `enabled`, `admin_only`).
* Alias `/say` je samostatný slash příkaz se stejnými parametry – pro uživatele, kteří očekávají „/say“.

## Rychlé tipy

* Chcete „hlášení“ do #console? Použijte `/echo text:"…" channel:"#console" hide:true` – uvidíte jen soukromé potvrzení.
* Potřebujete ztlumit pingy u kopírovaných oznámení? Nechte `no_mentions` na výchozí `True`.
* Posíláte soubory? U slash přiložte přes `file1..3`; u prefixu stačí přidat přílohy ke zprávě s příkazem.
## Ping (hybridní příkaz)

Nástroj pro měření odezvy bota s přidanou motivační zprávou. Funguje jako **hybridní příkaz**, tedy jak přes prefix `*ping`, tak přes **slash** `/ping`. V obou případech změří latenci (reakční dobu bota) a pošle **náhodný citát** o svobodě, sebekontrole a skutečné intimitě.

---

### Přehled

* **Název příkazu:** `ping`
* **Typ:** Hybridní (prefix i slash)
* **Popis:** Měří odezvu bota a připojuje náhodný citát
* **Parametry:**

  * `detailed` *(bool)* — zobrazí podrobný rozpis měření (volitelné)
  * `hide` *(bool)* — u slash verze skrytá odpověď (*ephemeral*)

---

### Syntaxe

#### Prefix varianta

```
*ping
*ping detailed=True
```

#### Slash varianta

```
/ping
/ping detailed:true
/ping hide:true
```

---

### Výstup

Základní odpověď:

```
🏓 Pong! Odezva: ~123.45 ms (WS 47.83 ms)
📖 „Skutečná intimita není na obrazovce.“ — Matt Fradd
```

Podrobný výstup (`detailed=True`):

```
🏓 Pong!
📖 „Síla člověka se ukazuje v tom, co dokáže ovládnout.“ — Sokrates

### Detaily měření
• WebSocket: 47.83 ms
• Odeslání zprávy: 82.64 ms
• Editace zprávy: 61.14 ms
```

---

### Citáty

Při každém spuštění se náhodně vybere jeden z více než dvaceti citátů o svobodě, intimitě, závislosti a sebeovládání.
Autoři zahrnují:

* John Eldredge
* Gary Wilson
* Noah Church
* Matt Fradd
* Jan Pavel II.
* C. S. Lewis
* Jason Evert
* Christopher West
* a další anonymní či komunitní zdroje (např. NoFap, NePornu.cz)

Citáty jsou formátovány jako:

```
📖 „Text citátu.“ — Autor
```

---

### Funkce měření

Příkaz měří tři typy odezvy:

1. **WebSocket latency** – průměrná odezva mezi botem a Discordem.
2. **Send roundtrip** – doba odeslání první zprávy.
3. **Edit roundtrip** – doba potřebná ke změně obsahu zprávy.

Výsledek kombinuje tyto údaje do přehledného výpisu.

---

### Chování

* **U prefixu**: odpověď se zobrazí veřejně v kanále.
* **U slashe**: volitelný *ephemeral* režim (`hide=True`).
* **Oprávnění**: vyžaduje pouze `Send Messages` a `Embed Links`.
* **Bezpečné selhání**: při chybě vrací jasnou hlášku (bez výjimky do konzole).
