# Pokyny pro přispívání (Contributing Guidelines)

Děkujeme, že máte zájem přispět do projektu Metricord! Tento dokument vám pomůže začít.

## 🛠 Vývojářské Prostředí

Metricord se skládá ze dvou hlavních částí: **Go Core** a **Python Worker**.

### Go Core
- Vyžaduje **Go 1.21+**.
- Nachází se v adresáři `go-core/`.
- Pro spuštění testů: `go test ./...`

### Python Worker
- Vyžaduje **Python 3.10+**.
- Nachází se v kořenovém adresáři a adresáři `bot/`.
- Závislosti instalujte pomocí `pip install -r requirements.txt`.

## 📝 Pravidla Kódování

### Go
- Dodržujte standardní `gofmt` formátování.
- Dokumentujte veřejné funkce a typy.
- Využívejte balíček `internal` pro privátní logiku.

### Python
- Používejte `black` nebo `autopep8` pro formátování.
- Dodržujte PEP 8.
- Pište asynchronní kód (async/await) tam, kde je to vhodné pro `discord.py`.

## 🌿 Git Workflow

1. Vytvořte si vlastní větev (branch) z `main`: `git checkout -b feature/moje-nova-funkce`.
2. Commitujte své změny s jasnými zprávami.
3. Pokud přidáváte novou funkci, nezapomeňte aktualizovat dokumentaci v `ARCHITECTURE.md` nebo v `README.md`.
4. Před odesláním Pull Requestu se ujistěte, že projekt lze sestavit pomocí `docker compose build`.

## 🧪 Testování

Před každým PR prosím ověřte:
- [ ] Go kód se zkompiluje (`go build ./...`).
- [ ] Python kód nemá syntaktické chyby.
- [ ] Docker kontejnery se nastartují.

## 🤝 Komunikace

Pokud máte dotazy nebo chcete nahlásit chybu, vytvořte prosím **Issue** v repozitáři nebo kontaktujte správce na Discordu nepornu.cz.
