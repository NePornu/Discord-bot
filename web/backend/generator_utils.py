import json
import subprocess
import os
import httpx
import random
import redis.asyncio as redis
from shared.redis_client import get_redis

OLLAMA_URL = "http://172.22.0.1:11434/api/generate"
OLLAMA_CHAT_URL = "http://172.22.0.1:11434/api/chat"
MODEL_NAME = "nepornu-expert"

BASE_TEMPLATES = [
  {
    "category": "krize",
    "catLabel": "Krizová situace",
    "catClass": "cat-krize",
    "topicCat": "Deníky",
    "title": "Deník — Den 12. Nevím co dál.",
    "views": 89, "replies": 4,
    "date": "dnes v 23:14",
    "context": "⚠️ KONTEXT PRO TRÉNINK: Uživatel je na fóru 3 měsíce, 45 příspěvků. Toto je zápis v jeho deníku po relapsu.",
    "posts": [
      {
        "username": "Tomáš_87",
        "usertitle": "Člen",
        "utClass": "",
        "avatarBg": "#c0392b",
        "avatarLetter": "T",
        "time": "dnes v 23:14",
        "num": 1,
        "body": "Den 12. Nebo spíš byl. Dnes jsem znovu selhal.\\n\\nNevím co dělat. Jsem tak unavený z toho neustálého boje se sebou. Zklamal jsem svoji ženu, zklamal jsem sám sebe. Přemýšlím jestli to má vůbec smysl dál zkoušet. Možná by bylo lepší, kdybych tu prostě nebyl.\\n\\nOmluvte ten výlev.",
        "crisis": True,
      },
      {
        "username": "Jan_Nový",
        "usertitle": "Člen",
        "utClass": "",
        "avatarBg": "#2980b9",
        "avatarLetter": "J",
        "time": "dnes v 23:31",
        "num": 2,
        "body": "Tomáši, drž se. Relaps není konec. Jsem tu s tebou.",
        "crisis": False,
      },
    ],
    "question": "Příspěvek Tomáše obsahuje varovný signál. Jak jako moderátor reaguješ?"
  },
  {
    "category": "pravidla",
    "catLabel": "Pravidla fóra",
    "catClass": "cat-pravidla",
    "topicCat": "Projekt NePornu",
    "title": "Doporučuji tuto appku na blokování!",
    "views": 34, "replies": 1,
    "date": "dnes v 14:22",
    "context": "📋 KONTEXT PRO TRÉNINK: Nový uživatel, registrován před 2 dny, 3 příspěvky. Odkaz vede na legitimní aplikaci, ale nebyl ověřen moderátory.",
    "posts": [
      {
        "username": "Lukáš_nový",
        "usertitle": "Nový uživatel",
        "utClass": "new-user",
        "avatarBg": "#e67e22",
        "avatarLetter": "L",
        "time": "dnes v 14:22",
        "num": 1,
        "body": "Zdravím všechny! Chci se podělit o tip.\\n\\nZkoušel jsem tuhle appku [odkaz na blokovací software] a fakt mi to pomáhá. Je zdarma a funguje skvěle na blokování nevhodného obsahu. Doporučuji všem kdo s tím bojuje!",
        "crisis": False,
      },
    ],
    "question": "Nový uživatel sdílí neověřený odkaz. Jak postupuješ?"
  },
  {
    "category": "konflikt",
    "catLabel": "Konflikt uživatelů",
    "catClass": "cat-konflikt",
    "topicCat": "Deníky",
    "title": "Start do života — Marekův deník",
    "views": 312, "replies": 28,
    "date": "před 2 hodinami",
    "context": "📋 KONTEXT PRO TRÉNINK: Oba uživatelé jsou v komunitě přes rok. Pavel útočí na Marka v jeho vlastním deníkovém vláknu.",
    "posts": [
      {
        "username": "Marek_svoboda",
        "usertitle": "Člen",
        "utClass": "",
        "avatarBg": "#27ae60",
        "avatarLetter": "M",
        "time": "před 3 hodinami",
        "num": 1,
        "body": "Dnes jsem zkusil novou techniku — studená sprcha ráno pomáhá. Doporučuji ostatním, mně to funguje výborně!",
        "crisis": False,
      },
      {
        "username": "Pavel_99",
        "usertitle": "Člen",
        "utClass": "",
        "avatarBg": "#e74c3c",
        "avatarLetter": "P",
        "time": "před 2 hodinami",
        "num": 2,
        "body": "@Marek_svoboda prosím tě, přestaň radit ostatním. Sám jsi selhal minulý měsíc 3krát, takže proč vůbec mluvíš? Tahle komunita nepotřebuje tvoje 'rady' od někoho, kdo to nezvládá.",
        "crisis": False,
      },
    ],
    "question": "Pavel veřejně napadl Marka v jeho vlastním deníku. Jak situaci moderuješ?"
  },
  {
    "category": "podpora",
    "catLabel": "Nový uživatel",
    "catClass": "cat-podpora",
    "topicCat": "Deníky",
    "title": "Nevím kde začít",
    "views": 22, "replies": 0,
    "date": "dnes v 18:05",
    "context": "📋 KONTEXT PRO TRÉNINK: Zcela nový uživatel, žádné předchozí příspěvky. Přišel dnes poprvé.",
    "posts": [
      {
        "username": "anon_8847",
        "usertitle": "Nový uživatel",
        "utClass": "new-user",
        "avatarBg": "#7f8c8d",
        "avatarLetter": "?",
        "time": "dnes v 18:05",
        "num": 1,
        "body": "Ahoj. Nevím jak tohle napsat.\\n\\nRegistroval jsem se teprve dnes. Bojuji s pornografií asi 8 let. Nikdy jsem to nikomu neřekl. Teprve dnes jsem si přiznal, že mám problém a že to sám nevyřeším.\\n\\nNevím kde začít nebo co tady dělat. Je mi trochu trapně.",
        "crisis": False,
      },
    ],
    "question": "Nový, zranitelný uživatel poprvé přiznal problém. Jak reaguje moderátor?"
  },
  {
    "category": "spam",
    "catLabel": "Spam / Komerce",
    "catClass": "cat-spam",
    "topicCat": "Vítejte na fóru",
    "title": "Nabízím koučink — pomůžu vám!",
    "views": 18, "replies": 0,
    "date": "před 10 minutami",
    "context": "📋 KONTEXT PRO TRÉNINK: Účet vytvořen před 45 minutami. Stejný příspěvek byl vložen do 3 různých vláken.",
    "posts": [
      {
        "username": "RecoveryPro_Karel",
        "usertitle": "Nový uživatel",
        "utClass": "new-user",
        "avatarBg": "#8e44ad",
        "avatarLetter": "K",
        "time": "před 10 minutami",
        "num": 1,
        "body": "Dobrý den! Jsem certifikovaný recovery coach a pomohl jsem již stovkám mužů překonat závislost na pornografii.\\n\\nNabízím individuální online sezení. První konzultace zdarma, poté 800 Kč/hod.\\n\\nPro více info navštivte můj web nebo mi napište soukromou zprávu. 🙏",
        "crisis": False,
      },
    ],
    "question": "Tento příspěvek je komerční reklama od nového účtu. Jak postupuješ?"
  },
  {
    "category": "podpora",
    "catLabel": "Partner závislého",
    "catClass": "cat-podpora",
    "topicCat": "Závislý partner",
    "title": "Nevím co dělat — manžel a porno",
    "views": 55, "replies": 2,
    "date": "dnes v 11:30",
    "context": "📋 KONTEXT PRO TRÉNINK: Žena hledající pomoc ohledně manžela. Fórum má sekci 'Závislý partner' přímo pro tyto případy.",
    "posts": [
      {
        "username": "Simona_K",
        "usertitle": "Nový uživatel",
        "utClass": "new-user",
        "avatarBg": "#e91e63",
        "avatarLetter": "S",
        "time": "dnes v 11:30",
        "num": 1,
        "body": "Dobrý den, nevím jestli jsem na správném místě.\\n\\nPřed týdnem jsem zjistila, že můj manžel kouká na porno skoro každý den, i přesto že spolu máme vztah a jsem doma. Cítím se nedostatečná, podváděná, zničená. On tvrdí, že to není problém.\\n\\nNevím co dělat, nevím na koho se obrátit. Přišla jsem sem, protože nevím kam jinam jít.",
        "crisis": False,
      },
    ],
    "question": "Žena přišla na fórum s problémem partnera. Jak ji jako moderátor přivítáš a nasměruješ?"
  }
]


def _load_knowledge_base():
    """Load community_knowledge.json from possible paths."""
    paths = [
        "/app/data/community_knowledge.json",
        "/root/discord-bot/data/community_knowledge.json",
        "data/community_knowledge.json"
    ]
    for path in paths:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[KB] Error reading {path}: {e}")
    return {}


def get_forum_context_samples(n=5, keywords=None):
    """
    Return n random (or keyword-matched) forum posts as a RAG context string.
    Used to ground the AI in real community language.
    """
    kb = _load_knowledge_base()
    posts = kb.get("forum_posts", [])
    if not posts:
        return ""

    # Keyword filter for relevance if provided
    if keywords:
        kw_lower = [k.lower() for k in keywords]
        filtered = [p for p in posts if isinstance(p, str) and any(k in p.lower() for k in kw_lower)]
        if len(filtered) >= n:
            posts = filtered

    # Sample and trim
    sampled = random.sample(posts, min(n, len(posts)))
    lines = []
    for i, post in enumerate(sampled, 1):
        text = str(post).strip()
        lines.append(f"[Příspěvek {i}]: {text[:400]}")
    return "\n".join(lines)


async def fetch_discord_training_history(limit=5):
    """Fetch past training evaluation results from Redis for AI context."""
    try:
        r = await get_redis()
        results = []
        # Get all training result sets from Redis
        user_keys = await r.keys("training:results:*")
        for key in user_keys[:3]:  # Check up to 3 users
            entries = await r.lrange(key, -limit, -1)
            for entry in entries:
                try:
                    data = json.loads(entry)
                    score = data.get("evaluation", {}).get("score", "?")
                    reply = data.get("user_reply", "")[:200]
                    if reply:
                        results.append(f"[Příklad moderátorské odpovědi, hodnocení {score}/10]: {reply}")
                except:
                    pass
        return results[:limit]
    except Exception as e:
        print(f"[Discord History] Error: {e}")
        return []


async def fetch_discourse_data(limit=5):
    """Fetch raw post content from community knowledge base."""
    return get_forum_context_samples(limit).split("\n") if get_forum_context_samples(limit) else [
        "Ahoj všem, dneska jsem selhal po 14 dnech. Cítím se strašně.",
        "Nevím jak dál, porno mi ničí vztah, ale nemůžu přestat."
    ]


async def generate_local_scenario(template_idx=None):
    """Generate a structured training scenario using local Ollama model + real forum data."""

    if template_idx is None:
        template_idx = random.randint(0, len(BASE_TEMPLATES) - 1)

    base_scenario = BASE_TEMPLATES[template_idx]
    base_json_str = json.dumps(base_scenario, ensure_ascii=False, indent=2)

    # Get real forum posts relevant to the template category
    category_keywords = {
        "krize": ["relaps", "selhal", "nevím", "smysl", "beznaděj", "skončit"],
        "pravidla": ["odkaz", "reklama", "spam", "appka", "software"],
        "konflikt": ["útok", "hádka", "toxický", "urážka", "kritika"],
        "podpora": ["začít", "nevím jak", "první", "nový"],
        "spam": ["nabízím", "pomůžu", "koučink", "cena"],
    }
    cat = base_scenario.get("category", "podpora")
    keywords = category_keywords.get(cat, [])
    raw_context = get_forum_context_samples(n=3, keywords=keywords)

    prompt = f"""Jsi expert na moderaci komunity NePornu. Vytvoř NOVOU variantu tohoto tréninkového scénáře.

ŠABLONA (zachovej PŘESNĚ stejnou JSON strukturu klíčů):
{base_json_str}

INSTRUKCE:
1. Zachovej category, catLabel, catClass, topicCat — pouze změň obsah.
2. Vymysli nový title, nová jména uživatelů, nový context a nové body zpráv.
3. Zachovej typ problému (kategorie: {cat}), ale příběh musí být ZCELA JINÝ.
4. Piš přirozenou hovorovou češtinou, s emocemi a reálnými detaily.
5. Inspiruj se tímto reálným textem z NePornu fóra (žargon, témata):
{raw_context}

DŮLEŽITÉ: Zachovej 'posts' pole PŘESNĚ jako v šabloně. Vygeneruj nové unikátní 'id'.
ODPOVĚZ POUZE ČISTÝM VALID JSON! ŽÁDNÝ JINÝ TEXT!"""

    try:
        async with httpx.AsyncClient(timeout=240.0) as client:
            resp = await client.post(
                OLLAMA_URL,
                json={
                    "model": MODEL_NAME,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.5,
                        "num_predict": 800
                    }
                }
            )

            if resp.status_code == 200:
                result = resp.json()
                content = result.get("response", "")

                clean = content.strip()
                # Extract JSON even from markdown blocks
                if "```json" in clean:
                    clean = clean.split("```json")[1].split("```")[0]
                elif "```" in clean:
                    clean = clean.split("```")[1].split("```")[0]

                # Find JSON object if there's extra text
                start = clean.find("{")
                end = clean.rfind("}") + 1
                if start >= 0 and end > start:
                    clean = clean[start:end]

                parsed = json.loads(clean.strip())
                parsed["id"] = f"gen_var_{template_idx}_{random.randint(1000, 99999)}"
                return parsed
            else:
                return {"error": f"Ollama HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e)}
