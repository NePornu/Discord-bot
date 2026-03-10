"""
Algoritmický hodnotící engine pro moderátorské odpovědi.
Nepoužívá AI pro skórování — pouze deterministické pravidla a vzory.
"""
import re
import json

# ============ SLOVNÍKY PRO DETEKCI ============

# Empatická slova a fráze
EMPATHY_POSITIVE = [
    "chápu", "rozumím", "jsem tu", "neboj", "drž se", "není to tvoje vina",
    "podporuji", "slyším tě", "to je pochopitelné", "to je normální",
    "cítím s tebou", "jsi odvážný", "odvaha", "síla", "respektuji",
    "děkuji za sdílení", "děkuji že to píšeš", "vážím si", "jsi tu správně",
    "nejsi v tom sám", "nejsi sám", "nejsi sama", "jsme tu pro tebe",
    "to zvládneš", "věřím ti", "oceňuji", "stojíme za tebou",
    "je v pořádku cítit", "je ok", "to je v pohodě", "žádný strach",
    "každý má právo", "vítáme tě", "krásně napsáno",
]

# Negativní / soudící slova (penalizace)
EMPATHY_NEGATIVE = [
    "idiot", "blbec", "debil", "hloupý", "neschopný", "trapný",
    "selhání", "selhal jsi", "tvoje chyba", "měl bys", "musíš",
    "přestaň", "co to děláš", "proč to děláš", "je ti to jedno",
    "nedělej drama", "nekecej", "zbytečný", "nevymlouvej se",
    "prostě přestaň", "buď chlap", "vyber si", "jsi slabý",
    "vůle", "nemáš vůli", "jsi nula", "ubožák", "vypatlaný",
    "drž hubu", "neotravuj", "táhni", "vypadni", "nesmysl",
]

# Kritické urážky (Zero-score policy)
TOXIC_KEYWORDS = [
    "idiot", "debil", "kretén", "vypatlan", "blbec", "hovno",
    "nula", "ubožák", "drž hubu", "neotravuj", "vypadni",
    "táhni", "hnus", "odporný", "hajzl", "mrd", "čurák",
]

# Procedurální klíčová slova
PROCEDURE_KEYWORDS = [
    # Odkazy na sekce a pravidla
    "pravidla", "pravidlo", "sekce", "kategorie", "deníky", "deník",
    "vlákno", "příspěvek", "přesunout", "přesuň", "smazat", "smaž",
    # Upozornění a moderace
    "upozornění", "varování", "ban", "blokace", "nahlásit",
    "moderátor", "admin", "správce", "tým",
    # Odkazování na správné místo
    "partnerská sekce", "závislý partner", "fórum", "nový uživatel",
    "projekt nepornu", "komunita", "pravidla komunity",
]

# Krizová klíčová slova
CRISIS_RESPONSE_KEYWORDS = [
    # Krizové linky a pomoc
    "linka bezpečí", "linka důvěry", "krizová linka", "krizové centrum",
    "116 111", "116111", "odborník", "odborná pomoc", "terapeut",
    "psycholog", "psychiatr", "záchranná služba", "155", "112",
    # Eskalace
    "eskalovat", "eskaluji", "nahlásit", "správce", "okamžitě",
    "bezpečí", "bezpečný", "jsi v bezpečí", "bezprostřední",
    # Deeskalace
    "neodsuzuji", "žádné soudy", "tvoje pocity jsou validní",
]

# Spam/reklama detekce
SPAM_RESPONSE_KEYWORDS = [
    "smazat", "smaž", "spam", "reklama", "komerční", "ban",
    "blokovat", "porušení", "pravidla", "neověřený", "podezřelý",
    "přezkoumáme", "prověříme", "nedůvěřuj", "opatrnost",
]

# Konflikt detekce
CONFLICT_RESPONSE_KEYWORDS = [
    "respekt", "respektovat", "slušnost", "pravidla diskuse",
    "osobní útok", "nekonstruktivní", "upozornění",
    "oba", "obě strany", "pochopení", "klid", "zklidnit",
    "soukromá zpráva", "dm", "osobně", "vysvětlení",
]


def _normalize(text: str) -> str:
    """Lowercase, strip accents for matching."""
    return text.lower().strip()


def _count_matches(text: str, keywords: list) -> int:
    """Count how many keywords appear in text."""
    t = _normalize(text)
    return sum(1 for kw in keywords if kw.lower() in t)


def _has_any(text: str, keywords: list) -> bool:
    return _count_matches(text, keywords) > 0


# ============ SCORING FUNCTIONS ============

def score_empathy(reply: str, scenario_category: str) -> tuple:
    """
    Score empathy 0-3.
    Returns (score, reasons_positive, reasons_negative).
    """
    positives = []
    negatives = []
    score = 0
    t = _normalize(reply)
    
    # Check positive empathy markers
    pos_count = _count_matches(reply, EMPATHY_POSITIVE)
    if pos_count >= 3:
        score = 3
        positives.append("Odpověď obsahuje silné empatické vyjádření.")
    elif pos_count >= 2:
        score = 2
        positives.append("Dobrá úroveň empatie.")
    elif pos_count >= 1:
        score = 1
        positives.append("Částečná empatie.")
    else:
        negatives.append("Chybí empatické vyjádření (např. 'chápu', 'jsem tu pro tebe').")
    
    # Check negative markers (penalize)
    neg_count = _count_matches(reply, EMPATHY_NEGATIVE)
    if neg_count >= 2:
        score = max(0, score - 2)
        negatives.append("Odpověď obsahuje soudící nebo útočný jazyk!")
    elif neg_count >= 1:
        score = max(0, score - 1)
        negatives.append("Zaznamětán nevhodný tón v odpovědi.")
    
    # Length check — very short = low effort
    if len(reply.strip()) < 30:
        score = max(0, score - 1)
        negatives.append("Odpověď je příliš krátká pro smysluplnou komunikaci.")
    
    return score, positives, negatives


def score_procedure(reply: str, scenario_category: str) -> tuple:
    """
    Score procedure 0-3.
    Category-specific procedural checks.
    """
    positives = []
    negatives = []
    score = 0
    t = _normalize(reply)
    
    proc_count = _count_matches(reply, PROCEDURE_KEYWORDS)
    
    if scenario_category == "spam":
        spam_count = _count_matches(reply, SPAM_RESPONSE_KEYWORDS)
        if spam_count >= 3:
            score = 3
            positives.append("Správný postup: identifikace spamu a akce (smazání/ban).")
        elif spam_count >= 2:
            score = 2
            positives.append("Dobrý postup při řešení spamu.")
        elif spam_count >= 1:
            score = 1
            positives.append("Částečně správný postup.")
        else:
            negatives.append("Nezmiňuje smazání, blokaci ani pravidla komunity.")
    
    elif scenario_category == "konflikt":
        conf_count = _count_matches(reply, CONFLICT_RESPONSE_KEYWORDS)
        if conf_count >= 3:
            score = 3
            positives.append("Výborná mediace konfliktu — oslovuje obě strany.")
        elif conf_count >= 2:
            score = 2
            positives.append("Dobrý přístup ke konfliktu.")
        elif conf_count >= 1:
            score = 1
            positives.append("Základní řešení konfliktu.")
        else:
            negatives.append("Chybí mediační přístup (oslovení obou stran, pravidla diskuse).")
    
    elif scenario_category == "pravidla":
        if proc_count >= 3:
            score = 3
            positives.append("Důkladná práce s pravidly fóra.")
        elif proc_count >= 2:
            score = 2
            positives.append("Pravidla zmíněna.")
        elif proc_count >= 1:
            score = 1
            positives.append("Částečný odkaz na pravidla.")
        else:
            negatives.append("Neodkazuje na pravidla ani postup moderace.")
    
    else:  # podpora, krize
        if proc_count >= 2:
            score = 3
            positives.append("Správně odkazuje na zdroje a postupy komunity.")
        elif proc_count >= 1:
            score = 2
            positives.append("Zmíněny postupy.")
        else:
            score = 1
            negatives.append("Mohl by explicitně odkázat na sekci fóra nebo pravidla.")
    
    return score, positives, negatives


def score_risk_analysis(reply: str, scenario_category: str, has_crisis: bool) -> tuple:
    """
    Score risk analysis 0-4.
    Highest weight — did they catch crisis signals?
    """
    positives = []
    negatives = []
    score = 0
    
    if has_crisis:
        # KRIZOVÝ SCÉNÁŘ — musí reagovat na krizi
        crisis_count = _count_matches(reply, CRISIS_RESPONSE_KEYWORDS)
        if crisis_count >= 3:
            score = 4
            positives.append("Excelentní krizová reakce — zmíněna linka bezpečí a odborná pomoc.")
        elif crisis_count >= 2:
            score = 3
            positives.append("Dobrá krizová reakce.")
        elif crisis_count >= 1:
            score = 2
            positives.append("Částečná identifikace krize.")
            negatives.append("Měl by explicitně zmínit krizovou linku (116 111).")
        else:
            score = 0
            negatives.append("KRITICKÁ CHYBA: Neidentifikoval krizový signál! Chybí odkaz na Linku bezpečí.")
    
    elif scenario_category == "spam":
        spam_count = _count_matches(reply, SPAM_RESPONSE_KEYWORDS)
        if spam_count >= 2:
            score = 4
            positives.append("Správně identifikován spam a učiněna akce.")
        elif spam_count >= 1:
            score = 2
            positives.append("Rozeznal podezřelý obsah.")
        else:
            score = 1
            negatives.append("Neidentifikoval komerční spam.")
    
    elif scenario_category == "konflikt":
        # Měl rozeznat toxicitu
        if _has_any(reply, ["útok", "osobní útok", "toxický", "nevhodný", "urážka", "upozornění", "varování"]):
            score = 3
            positives.append("Identifikoval toxické chování.")
        elif _has_any(reply, ["konflikt", "problém", "řešit"]):
            score = 2
            positives.append("Zaznamenal konflikt.")
        else:
            score = 1
            negatives.append("Mohl explicitněji pojmenovat problém (osobní útok).")
    
    else:
        # Podpora — nízké riziko
        if _has_any(reply, ["bezpečí", "pomoc", "odborník", "podpora"]):
            score = 3
            positives.append("Nabídl podporu a bezpečný prostor.")
        elif len(reply.strip()) > 50:
            score = 2
            positives.append("Přiměřená reakce na situaci.")
        else:
            score = 1
            negatives.append("Odpověď by mohla nabídnout více podpory.")
    
    return score, positives, negatives


import random

# ============ PRE-WRITTEN RESPONSE POOLS ============

SUMMARY_POOL = {
    "excellent": [
        "Excelentní odpověď — profesionální a empatická.",
        "Vzorová reakce moderátora. Tak se to dělá!",
        "Výborně zvládnutá situace. Ukázkový přístup.",
        "Skvělá práce! Odpověď pokrývá všechny klíčové oblasti.",
    ],
    "good": [
        "Velmi dobrá reakce s drobnými rezervami.",
        "Solidní odpověď. Jen pár detailů ke zlepšení.",
        "Dobrý základ — s drobnými úpravami by to bylo perfektní.",
        "Kvalitní odpověď. Pár věcí by šlo vylepšit.",
    ],
    "average": [
        "Průměrná odpověď — některé části vyžadují zlepšení.",
        "Základ je správný, ale chybí důležité prvky.",
        "Odpověď pokrývá jen část toho, co situace vyžaduje.",
        "Na správné cestě, ale je potřeba víc hloubky.",
    ],
    "weak": [
        "Slabá odpověď — chybí klíčové prvky moderace.",
        "Odpověď nesplňuje základní požadavky na moderování.",
        "Je potřeba výrazně zlepšit přístup k situaci.",
        "Odpověď nedostatečně reaguje na podstatu problému.",
    ],
    "harmful": [
        "Nevhodná reakce — může způsobit škodu.",
        "Tato odpověď by mohla situaci zhoršit.",
        "POZOR: Odpověď je potenciálně škodlivá pro uživatele.",
        "Odpověď je v rozporu se zásadami moderace.",
    ]
}

POSITIVE_POOL = {
    "empathy_high": [
        "Odpověď vyjadřuje hluboké pochopení a empatii vůči uživateli.",
        "Výborně navázaný lidský kontakt — uživatel se cítí vyslyšen.",
        "Empatický tón je přesně to, co uživatel v této chvíli potřebuje.",
    ],
    "empathy_medium": [
        "Dobrá úroveň empatie v odpovědi.",
        "Moderátor projevuje zájem o uživatele.",
        "Odpověď nese empatický nádech.",
    ],
    "procedure_good": [
        "Správně odkazuje na pravidla a postupy komunity.",
        "Dobrá znalost moderátorských postupů.",
        "Procedurálně správný přístup k situaci.",
    ],
    "crisis_good": [
        "Správně identifikoval krizový signál a reagoval protokolem.",
        "Zmíněna Linka bezpečí — klíčový krok v krizové situaci.",
        "Excelentní krizová reakce s odkázáním na odbornou pomoc.",
    ],
    "spam_good": [
        "Správně identifikoval podezřelý obsah a jednal.",
        "Dobrý postup při řešení komerčního spamu.",
    ],
    "conflict_good": [
        "Dobrá mediace — oslovuje obě strany konfliktu.",
        "Správně pojmenoval problém a nabídl řešení.",
    ],
    "default": [
        "Moderátor se pokusil reagovat na situaci.",
    ]
}

IMPROVE_POOL = {
    "no_empathy": [
        "Chybí empatické vyjádření. Zkus začít větou jako 'Chápu, jak se cítíš' nebo 'Jsem tu pro tebe'.",
        "Odpověď je příliš strohá. Přidej lidský rozměr — uživatel potřebuje vědět, že není sám.",
        "Vřelejší tón by pomohl. Moderátor není robot — ukaž pochopení.",
    ],
    "judgmental": [
        "Odpověď obsahuje soudící jazyk! Moderátor NIKDY nesoudí uživatele.",
        "Nevhodný tón — urážky nebo sarkasmus nemají v moderaci místo.",
        "POZOR: Soudící jazyk může uživatele odradit od hledání pomoci.",
    ],
    "too_short": [
        "Odpověď je příliš krátká. Uživatel si zaslouží víc pozornosti.",
        "Rozveď svou odpověď — jednovětná reakce nestačí na složitou situaci.",
    ],
    "missing_crisis": [
        "KRITICKÁ CHYBA: Neidentifikoval jsi krizový signál! Vždy zmiň Linku bezpečí (116 111).",
        "Přehlédl jsi varovné znaky. U zmínek o beznaději VŽDY odkaž na krizovou pomoc.",
    ],
    "missing_procedure": [
        "Neodkazuješ na pravidla komunity ani na správné sekce fóra.",
        "Zkus zmínit konkrétní pravidlo nebo sekci, kam uživatele nasměrovat.",
    ],
    "missing_spam_action": [
        "U spamu musíš jasně říct: smazat příspěvek + upozornění/ban.",
        "Chybí konkrétní akce. Spam = okamžité smazání + vysvětlení proč.",
    ],
    "missing_conflict_mediation": [
        "Chybí mediace. Oslav obě strany a nabídni soukromé řešení.",
        "U konfliktu je klíčové pojmenovat problém a oslovit OBĚ strany.",
    ],
    "none": [
        "Výborný výkon, bez větších výhrad.",
        "Žádné zásadní nedostatky. Drž se tohoto přístupu!",
    ]
}

TIPS = {
    "krize": [
        "U krizových situací VŽDY zmiň Linku bezpečí (116 111) a nenech uživatele samotného.",
        "Krizový protokol: 1) Empatická reakce 2) Odkaz na odbornou pomoc 3) Eskalace správci.",
        "Nikdy neříkej 'to bude dobré'. Místo toho: 'Chápu, že je to těžké. Jsi tu správně a pomoc existuje.'",
    ],
    "pravidla": [
        "Vždy odkaž na konkrétní pravidlo a vysvětli, PROČ existuje.",
        "Nebuď robot — i při vymáhání pravidel buď lidský. 'Chápu tvůj záměr, ale...'",
        "Pravidla existují pro ochranu komunity. Komunikuj to s respektem.",
    ],
    "konflikt": [
        "Oslav obě strany, pojmenuj problém a nabídni soukromé řešení (DM/soukromá zpráva).",
        "Nikdy se nestav na jednu stranu. Tvá role je mediátor, ne soudce.",
        "Klíč ke konfliktu: pojmenuj co se děje + nastav hranici + nabídni další krok.",
    ],
    "podpora": [
        "Nové uživatele vřele přivítej a nasměruj do správné sekce fóra (Deníky, Partner).",
        "První příspěvek je nejtěžší. Oceň odvahu a nabídni konkrétní další krok.",
        "Nový uživatel potřebuje slyšet: 'Jsi tu správně. Nejsi v tom sám.'",
    ],
    "spam": [
        "Spam = smazat + ban + krátké vysvětlení ostatním, proč byl příspěvek odstraněn.",
        "I u spamu buď profesionální. 'Tento příspěvek porušuje pravidla o komerčním obsahu.'",
        "Spam řeš rychle a razantně, ale vždy vysvětli důvod.",
    ],
}


def evaluate_reply(reply: str, scenario: dict) -> dict:
    """
    Vyhodnotí moderátorskou odpověď algoritmicky.
    Vrací dict s pre-written Czech texty — žádné AI generování.
    """
    category = scenario.get("category", "podpora")
    has_crisis = any(p.get("crisis", False) for p in scenario.get("posts", []))
    q_type = scenario.get("type", "text")

    # === ABC / DROPDOWN EVALUATION ===
    if q_type in ["abc", "dropdown"]:
        options = scenario.get("options", [])
        correct_option = next((opt for opt in options if opt.get("correct")), None)
        
        if not correct_option:
            return {
                "score": 10,
                "summary": "Tento scénář nemá definovanou správnou odpověď, ale vaše volba byla zaznamenána.",
                "positive": "Odpověď uložena.",
                "improve": "",
                "tip": "V administraci můžete u scénáře nastavit, která odpověď je správná.",
                "breakdown": {"empatie": "-/3", "procedura": "-/3", "rizika": "-/4"}
            }

        is_correct = reply.strip().lower() == correct_option.get("text", "").strip().lower()
        
        if is_correct:
            return {
                "score": 10,
                "summary": "Výborně! Vybrali jste správnou odpověď.",
                "positive": f"Vaše volba: \"{reply}\" je naprosto správná.",
                "improve": "",
                "tip": "Zkuste si i jiné typy scénářů pro procvičení různých situací.",
                "breakdown": {"empatie": "3/3", "procedura": "3/3", "rizika": "4/4"}
            }
        else:
            return {
                "score": 0,
                "summary": "Bohužel, toto není správná odpověď.",
                "positive": "",
                "improve": f"Správná odpověď byla: \"{correct_option.get('text')}\".",
                "tip": "Přečtěte si pozorně kontext situace, než vyberete možnost.",
                "breakdown": {"empatie": "0/3", "procedura": "0/3", "rizika": "0/4"}
            }

    # Skóre (Text interpretation)
    emp_score, emp_pos, emp_neg = score_empathy(reply, category)
    proc_score, proc_pos, proc_neg = score_procedure(reply, category)
    risk_score, risk_pos, risk_neg = score_risk_analysis(reply, category, has_crisis)
    total = emp_score + proc_score + risk_score
    
    # === TOXICITY OVERRIDE (Zero-score policy) ===
    is_toxic = _has_any(reply, TOXIC_KEYWORDS)
    if is_toxic:
        total = 0
        emp_score = 0
        proc_score = 0
        risk_score = 0
    
    # === SUMMARY (randomized variant) ===
    if total >= 9:
        summary = random.choice(SUMMARY_POOL["excellent"])
    elif total >= 7:
        summary = random.choice(SUMMARY_POOL["good"])
    elif total >= 5:
        summary = random.choice(SUMMARY_POOL["average"])
    elif total >= 3:
        summary = random.choice(SUMMARY_POOL["weak"])
    else:
        summary = random.choice(SUMMARY_POOL["harmful"])
    
    # === POSITIVE (pick from appropriate pool) ===
    pos_parts = []
    if emp_score >= 2:
        pos_parts.append(random.choice(POSITIVE_POOL["empathy_high"]))
    elif emp_score >= 1:
        pos_parts.append(random.choice(POSITIVE_POOL["empathy_medium"]))
    
    if category == "krize" and risk_score >= 3:
        pos_parts.append(random.choice(POSITIVE_POOL["crisis_good"]))
    elif category == "spam" and risk_score >= 3:
        pos_parts.append(random.choice(POSITIVE_POOL["spam_good"]))
    elif category == "konflikt" and proc_score >= 2:
        pos_parts.append(random.choice(POSITIVE_POOL["conflict_good"]))
    elif proc_score >= 2:
        pos_parts.append(random.choice(POSITIVE_POOL["procedure_good"]))
    
    positive = " ".join(pos_parts) if pos_parts else random.choice(POSITIVE_POOL["default"])
    
    # === IMPROVE (pick from appropriate pool) ===
    imp_parts = []
    neg_count = _count_matches(reply, EMPATHY_NEGATIVE)
    
    if neg_count >= 1:
        imp_parts.append(random.choice(IMPROVE_POOL["judgmental"]))
    elif emp_score == 0:
        imp_parts.append(random.choice(IMPROVE_POOL["no_empathy"]))
    
    if len(reply.strip()) < 30:
        imp_parts.append(random.choice(IMPROVE_POOL["too_short"]))
    
    if has_crisis and risk_score <= 1:
        imp_parts.append(random.choice(IMPROVE_POOL["missing_crisis"]))
    elif category == "spam" and risk_score <= 1:
        imp_parts.append(random.choice(IMPROVE_POOL["missing_spam_action"]))
    elif category == "konflikt" and proc_score <= 1:
        imp_parts.append(random.choice(IMPROVE_POOL["missing_conflict_mediation"]))
    elif proc_score == 0:
        imp_parts.append(random.choice(IMPROVE_POOL["missing_procedure"]))
    
    improve = " ".join(imp_parts) if imp_parts else random.choice(IMPROVE_POOL["none"])
    
    # === TIP ===
    tip = random.choice(TIPS.get(category, ["Vždy kombinuj empatii s jasným postupem."]))
    
    return {
        "score": total,
        "summary": summary,
        "positive": positive,
        "improve": improve,
        "tip": tip,
        "breakdown": {
            "empatie": f"{emp_score}/3",
            "procedura": f"{proc_score}/3",
            "rizika": f"{risk_score}/4"
        }
    }

