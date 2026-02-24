import requests
import json
import os
import time

API_URL = "http://fluxer-api-1:8080/v1"
# Use the same token as create_training_ground.py
with open("migration_token.txt", "r") as f:
    TOKEN = f.read().strip()
    
HEADERS = {
    "Authorization": TOKEN,
    "Content-Type": "application/json",
    "X-Forwarded-For": "127.0.0.1"
}
def post_message(channel_id, content):
    url = f"{API_URL}/channels/{channel_id}/messages"
    payload = {"content": content}
    try:
        resp = requests.post(url, headers=HEADERS, json=payload)
        if resp.status_code == 200:
            print(f"✅ Posted message to {channel_id}")
            return True
        else:
            print(f"❌ Failed to post: {resp.status_code} - {resp.text}")
            return False
    except Exception as e:
        print(f"❌ Error posting: {e}")
        return False

def main():
    config_path = "training_ground_config.json"
    if not os.path.exists(config_path):
        print("❌ Config file not found.")
        return

    with open(config_path, "r") as f:
        config = json.load(f)

    guild_id = config["guild_id"]
    
    # Get the rules-and-info channel ID
    url = f"{API_URL}/guilds/{guild_id}/channels"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code != 200:
        print("❌ Failed to get channels")
        return
    
    channels = resp.json()
    rules_channel = next((c for c in channels if c["name"] == "rules-and-info"), None)
    
    if not rules_channel:
        print("❌ #rules-and-info channel not found")
        return
    
    channel_id = rules_channel["id"]

    manual_sections = [
        # SECTION 1: Introduction
        """# 📘 Manuál online komunitní platformy: Úvod
Tento manuál shrnuje účel, pravidla a provozní rámec online komunitních platforem projektu NePornu, z. s. (dále „OKP“). 
Cílem OKP je vytvořit strukturovaný a moderovaný veřejný prostor na internetu pro vzájemnou podporu osob, které reflektují a pracují se svým problémovým užíváním pornografie (PPU). 

> [!IMPORTANT]
> OKP je komunitní, svépomocná podpůrná služba. Tato služba není odborná zdravotní péče, psychoterapie, ani jako lékařské, psychologické či právní poradenství.""",

        # SECTION 2: Work with clients
        """# 🛡️ Práce s klienty a Hranice
OKP je komunitní platforma. Není individuální poradenskou ani terapeutickou službou. Interakce s jednotlivcem probíhá vždy v komunitním rámci a nesmí přerůst v dlouhodobé osobní vedení.

**Individuální komunikace:**
- Možná pouze v omezeném rozsahu (vysvětlení pravidel, navigace).
- Nesmí být pravidelná ani výlučná.
- **Rizikové situace:** Emoční fixace, vyhledávání výhradně jednoho člena týmu, komunikace mimo platformu.

Člen týmu neprovádí hlubokou analýzu, nediagnostikuje a nepřebírá odpovědnost za rozhodování uživatele.""",

        # SECTION 3: Roles
        """# 👥 Role v rámci OKP
- **Nový člen**: Uživatel po registraci, vidí pouze úvodní kanály.
- **Člen**: Registrovaný a ověřený uživatel (13+ let).
- **Ověřený člen**: Aktivní a nápomocný člen (min. 3 měsíce aktivní).
- **Pomocník (Helper)**: Dobrovolník (15+ let), pomáhá novým členům, nemá moderátorská práva.
- **Moderátor**: Dohlíží na pravidla, technicky zasahuje (18+ let, min. 3 měsíce role helpera).
- **Správce/Koordinátor**: Provozní a právní odpovědnost, eskalace.""",

        # SECTION 4: Safety Rules
        """# 📜 Pravidla chování na OKP
1. **Žádný sexuálně explicitní obsah!** (NSFW, pornografie, texty, odkazy). Nulová tolerance.
2. **Označování citlivého obsahu**: Používej "Spoiler" nebo upozornění (Trigger Warning) u témat relapsu či traumatu.
3. **Žádná šikana!** Respekt bez ohledu na gender, víru či politiku.
4. **Hranice laické pomoci**: Používej "Já-výroky" (Mně pomohlo...). Žádné příkazy.
5. **Anti-doxing**: Zákaz zveřejňování reálné identity uživatelů.
6. **Zákaz komerce a spamu**.
7. **Ochrana nezletilých**: Zákaz navazování soukromých vztahů dospělých s nezletilými. Podezření na grooming se okamžitě eskaluje.""",

        # SECTION 5: Sanctions & Incidents
        """# ⚖️ Sankce a Incidenty
**Stupně sankcí:**
1. **Upozornění**: Formální edukace.
2. **Dočasné omezení (Timeout)**: 1-24 hodin pro zklidnění.
3. **Dočasné vyloučení (Temp Ban)**: 3-30 dní.
4. **Trvalé vyloučení (Perm Ban)**: Hrubé porušení nebo recidiva.

**Incidenty:** 
Situace představující reálné riziko (šikana, CSAM, sebevražedné hrozby). Pokud incident přesahuje kompetence, nastává **ESKALACE** směrem ke správci.""",

        # SECTION 6: Terminology & Slang
        """# 🗣️ Místní slang
- **PMO**: Porno, Masturbace, Orgasmus.
- **Hard Mode**: Abstinence od PMO.
- **Monk Mode**: Hard Mode + žádné sociální sítě, seriály apod.
- **Trigger**: Podnět vyvolávající myšlenku na porno.
- **Relaps**: Vědomé, systematické porušení abstinence.
- **Laps**: Jednorázové uklouznutí.
- **Flatline**: Pokles libida během zotavení.""",

        # SECTION 7: FAQ
        """# ❓ FAQ
**Jsou tu jen křesťané?** Ne, vítán je každý bez ohledu na vyznání.
**Jak se stanu Ověřeným členem?** Buď aktivní a přátelský aspoň 3 měsíce.
**Proč nemůžu posílat odkazy?** Kvůli bezpečnosti. Tuto možnost mají až ověření uživatelé.
**Odkazy na pomoc:** 
- [NePornu.cz](https://nepornu.cz)
- [Linka bezpečí](https://www.linkabezpeci.cz/)""",
    ]

    print("🚀 Starting manual population...")
    for section in manual_sections:
        post_message(channel_id, section)
        time.sleep(1)
    
    print("✅ Manual population complete!")

if __name__ == "__main__":
    main()
