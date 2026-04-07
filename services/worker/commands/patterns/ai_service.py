import os
import httpx
import logging
import json
import base64
import re
from typing import List, Optional, Dict
from datetime import datetime

logger = logging.getLogger("PatternDetector")

# Expanded Czech/Slovak non-informative words
STOP_WORDS = {
    "vlastně", "nicméně", "současně", "potom", "takže", "prostě", "jakože", "abych", "pokud", "protože", "jenže", "aspoň", "právě", "celkem", "docela", "trochu", "hodně", "příliš", "možná", "určitě", "stále", "ještě", "však", "nebo", "také", "tady", "tam", "zase", "opět", "víceméně", "vlastne", "nicmene", "soucasne", "lebo", "prečo", "proč", "kvůli", "kvôli", "kvoli", "právě", "prave", "hneď", "hned", "vtedy", "tehdy", "tento", "tamto", "lepšie", "lepší", "zatiaľ", "zatím", "úplně", "úplne", "posledné", "poslední", "velmi", "veľmi", "taky", "také", "jako", "jenom", "iba", "teraz", "terazky", "vždy", "nikdy", "často", "skoro", "téměř", "také", "opět", "znovu", "předtím", "potom", "zatímco", "mezitím", "najednou", "náhle", "stále", "opravdu", "skutečně", "skutočne", "vlastne", "naopak", "podobně", "podobne", "chtěl", "budu", "mám", "jsem", "jsme", "bolo", "bylo", "jsou", "budou", "chci", "chtějí", "přišel", "dělat", "robit", "musím", "můžu", "môžem", "vím", "viem", "vidím", "vypadá", "stalo", "začal", "začala", "končí", "může", "môže", "mají", "majú", "mali", "bol", "byl", "bude", "uživatel", "příspěvek", "vlákno", "fórum", "děkuji", "díky", "dobrý", "den", "ahoj", "zdravím", "taky", "super", "paráda", "ahojte", "všichni", "všetci", "něco", "niečo", "všechno", "všetko", "verím", "verim", "píšem", "pisem", "týždeň", "tyzden", "týždne", "tyzdne", "kalendári", "kalendari", "včera", "vcera", "dneska", "zítra", "zitra", "zastavme", "myslím", "myslim", "možná", "mozna", "skôr", "skor", "potom", "prípad", "pripad", "ideme", "idem", "ideš", "ide", "budeme", "budem", "budeš", "budú", "robenie", "robil", "robila", "začal", "začala", "skončil", "skončila", "povedal", "povedala", "povedali", "povedat", "rozhodol", "rozhodla", "rozhodli", "mali", "mali", "mal", "mala", "mali", "tuto", "toto", "tenhle", "tento", "tadyto", "tamto", "všude", "všade", "nějak", "nejak", "niekto", "někdo", "vlastní", "vlastni", "jinak", "inak", "stejně", "rovnako", "konečně", "konečne", "vůbec", "vôbec", "trochu", "trochu", "snad", "hádam", "aspoň", "aspoň", "celkom", "celkem", "docela", "celkom", "možno", "možná", "snad", "vlastně", "opravdu", "skutečně", "skutočne", "vlastne", "naopak", "podobně", "podobne", "však", "ale", "alebo", "bych", "abych", "když", "keď", "však", "nech", "aj", "ešte", "este", "fakt", "môžeš", "mužeš", "muzes", "mozes", "keby", "když", "ked", "kdy", "kde", "ako", "akože", "akoze", "ani", "neviem", "nevím", "uvidím", "uvidíme", "vidieme", "uvidime", "viete", "vím", "viem", "viete", "vieš", "víš", "dnes", "včera", "zajtra", "zítra", "teraz", "teď", "potom", "pak", "skôr", "skor", "práve", "právě", "stále", "stále", "už", "ešte", "este", "vždy", "nikdy", "často", "občas", "niekdy", "někdy", "nejak", "nějak", "niečo", "něco", "všetko", "všechno", "každý", "všetci", "všichni", "veľa", "hodně", "málo", "trochu", "skoro", "takmer", "téměř", "možno", "asi", "snáď", "snad", "určite", "určitě", "naozaj", "opravdu", "skutočne", "skutečně", "vlastne", "vlastně", "fakt", "naopak", "pritom", "přitom", "napriek", "přes", "medzi", "mezi", "proti", "kvôli", "kvůli"
}

# Clinically significant keywords to BOOST in analysis
CLINICAL_KEYWORDS = {
    "relaps", "recidiva", "selhání", "selhani", "sexting", "grindr", "tinder", "badoo", "seznamka", "porno", "pornoherečka", "poker", "hazard", "sázení", "sazeni", 
    "alkohol", "drogy", "pervitin", "tráva", "marihuana", "koks", "kokain", "chuť", "chut", "bažení", "bazeni", "pokušení", "pokuseni", "pokušenie", "krize", "kriza", 
    "deprese", "úzkost", "uzkost", "strach", "samota", "nuda", "únava", "unava", "hněv", "hnev", "vzteky", "vztek", "stydím", "stud", "vina", "zklamání", "zklamani",
    "deník", "denik", "plán", "plan", "metodika", "survival", "terapie", "terapeut", "pomoc", "abstinence", "střízlivost", "strizlivost", "čistý", "cisty", "vztah", "partner", "manžel", "manželka"
}

class AIService:
    @staticmethod
    async def summarize_posts(posts: List[str], ctx: Optional[Dict] = None) -> Optional[str]:
        """
        Summarize the given posts using a configured provider (Cloud, Local, or Medical Report).
        """
        if not posts:
            return None

        provider = os.getenv("AI_PROVIDER", "auto").lower()
        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        openai_key = os.getenv("OPENAI_API_KEY")
        
        # Auto-detection logic
        if provider == "auto":
            if anthropic_key: provider = "anthropic"
            elif openai_key: provider = "openai"
            else: provider = "none"

        # Routing
        if provider == "anthropic" and anthropic_key:
            return await AIService._summarize_anthropic(posts, anthropic_key)
        elif provider == "openai" and openai_key:
            return await AIService._summarize_openai(posts, openai_key)
        elif provider == "ollama":
            return await AIService._summarize_ollama(posts)
        else:
            return await AIService._summarize_medical_report(posts, ctx)

    @staticmethod
    async def _summarize_anthropic(posts: List[str], api_key: str) -> Optional[str]:
        context_text = "\n---\n".join(posts)[:8000]
        prompt = (
            "Shrň stručně (max 350 znaků) tyto příspěvky uživatele fóra NePornu (zotavení ze závislosti). "
            "Zaměř se na emoční stav, témata a rizika. Piš přímo v češtině.\n\n"
            f"Příspěvky:\n{context_text}"
        )
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-3-haiku-20240307",
                        "max_tokens": 300,
                        "messages": [{"role": "user", "content": prompt}]
                    }
                )
                response.raise_for_status()
                return response.json()["content"][0]["text"].strip()
        except Exception as e:
            logger.error(f"Anthropic AI failed: {e}")
            return "Chyba při komunikaci s Anthropic."

    @staticmethod
    async def _summarize_openai(posts: List[str], api_key: str) -> Optional[str]:
        context_text = "\n---\n".join(posts)[:6000]
        prompt = (
            "Shrň stručně (max 350 znaků) tyto příspěvky uživatele fóra NePornu. "
            "Piš přímo v češtině, stručně k jádru věci.\n\n"
            f"Příspěvky:\n{context_text}"
        )
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 200
                    }
                )
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"OpenAI failed: {e}")
            return "Chyba při komunikaci s OpenAI."

    @staticmethod
    async def _summarize_ollama(posts: List[str]) -> Optional[str]:
        ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        ollama_model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
        context_text = "\n---\n".join(posts)[:4000]
        prompt = (
            "Instrukce: Shrň stručně (max 350 znaků) v češtině tyto příspěvky uživatele fóra NePornu.\n\n"
            f"Příspěvky:\n{context_text}"
        )
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.post(
                    f"{ollama_host}/api/generate",
                    json={"model": ollama_model, "prompt": prompt, "stream": False}
                )
                response.raise_for_status()
                return response.json()["response"].strip()
        except Exception as e:
            logger.error(f"Ollama failed: {e}")
            return "Chyba při komunikaci s Ollama."

    @staticmethod
    async def _summarize_medical_report(posts: List[str], ctx: Optional[Dict]) -> str:
        """
        Non-AI local fallback: Advanced Activity Diagnostic Overview with Weighted Clinical Themes.
        """
        if not ctx:
            return "Nedostatek dat pro diagnostický přehled."

        # Advanced Keyword Extraction with Clinical Weighting
        full_text = "\n".join(posts)
        freq = {}
        for word in re.findall(r'\b\w{4,}\b', full_text.lower()):
            if word not in STOP_WORDS:
                weight = 5 if word in CLINICAL_KEYWORDS else 1
                freq[word] = freq.get(word, 0) + weight

        top_kws = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:5]

        # Contextual mapping for themes – extracting up to 3 snippets per keyword
        kw_details = []
        for kw, _ in top_kws:
            raw_count = full_text.lower().count(kw)
            
            # Find up to 3 unique snippets
            snippets = []
            seen_ranges = [] # Avoid heavily overlapping snippets
            
            # Use regex to find all matches
            for match in re.finditer(f".{{0,40}}{re.escape(kw)}.{{0,50}}", full_text, re.IGNORECASE | re.DOTALL):
                start, end = match.span()
                # Check if this range overlaps too much with existing ones
                if any(abs(start - s) < 50 for s, e in seen_ranges):
                    continue
                
                snippet = match.group(0).strip().replace("\n", " ")
                snippet = re.sub(r'\s+', ' ', snippet)
                snippets.append(f"„...{snippet.strip()}...“")
                seen_ranges.append((start, end))
                if len(snippets) >= 3:
                    break
            
            snippets_str = "\n   ".join(snippets)
            kw_details.append(f"• **{kw.upper()}** ({raw_count}x):\n   {snippets_str}")

        # Report Construction
        report = f"📋 **DIAGNOSTICKÝ PŘEHLED AKTIVITY (POKROČILÁ HEURISTIKA)**\n"
        report += f"**────────────────────────────────────────────────────**\n\n"
        
        # 1. Subjective profile
        report += f"👤 **IDENTIFIKACE A HISTORIE**\n"
        report += f"• **Stáří účtu:** {ctx.get('join_days', '?')} dní v komunitě\n"
        report += f"• **První kontakt:** {ctx.get('first_msg_date', '?')}\n"
        
        interact = ctx.get('interactivity', 0)
        report += f"• **Interaktivita:** {int(interact) if interact is not None else 0}% (zapojení do komunity)\n\n"

        # 2. Theme Analysis (Detailed & Weighted)
        report += f"🧠 **KLÍČOVÁ TÉMATA A KOMPLEXNÍ KONTEXT**\n"
        if kw_details:
            report += "\n".join(kw_details) + "\n\n"
        else:
            report += "• Nebyla nalezena žádná výrazná specifická témata.\n\n"

        # 3. Quantitative Indicators
        s7 = ctx.get("stats_7d", {})
        total_w = len(full_text.split())
        report += f"📈 **KVANTITATIVNÍ UKAZATELE (7d)**\n"
        report += f"• **Frekvence:** {s7.get('msg_count', 0)} příspěvků / celkem ~{total_w} slov\n"
        report += f"• **Slovní diverzita:** {len(freq)} unikátních významových pojmů\n"
        report += f"• **Poslední aktivita:** {ctx.get('last_msg_date', '?')}\n\n"

        # 4. Diagnostic Summary
        alerts = ctx.get("alerts", [])
        notes = ctx.get("notes", [])
        
        report += f"🎯 **POZOROVANÉ VZORCE A ANAMNÉZA**\n"
        if alerts:
            al_str = ", ".join([f"[{a.pattern_name.upper()}]" for a in alerts])
            report += f"• Aktivní vzorce: {al_str}\n"
        else:
            report += "• Žádné specifické vzorce chování nebyly v tomto okně detekovány.\n"

        if notes:
            last_note = notes[-1]
            ts = last_note.get('ts')
            dt = datetime.fromtimestamp(ts).strftime("%d.%m.") if ts else "??"
            author = last_note.get('author', 'Tým')
            content = last_note.get('content', '')
            report += f"• Poznámka týmu ({dt}): \"{content[:100]}...\"\n"
        report += "\n"

        # 5. Conclusion
        report += f"🚑 **ZÁVĚR A PRIORITA**\n"
        urgency = ctx.get('urgency_text', '⚪ Nízká')
        report += f"• **Priorita:** {urgency}\n"
        report += f"• **Doporučení:** Komplexní náhled na uživatele naznačuje výše uvedené trendy. Prověřit deník.\n"

        return report
