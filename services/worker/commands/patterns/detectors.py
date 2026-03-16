import time
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Set, Optional
from .common import PatternAlert, K_MSG, K_KW, K_EDIT, K_JOIN, K_DIARY, K_QUESTION

logger = logging.getLogger("PatternDetector")

class PatternDetectors:
    def __init__(self, guild_id):
        self._guild_id = guild_id

    async def get_user_msg_stats(self, r, gid: int, uid: int, days: int) -> Dict:
        now = datetime.now(timezone.utc)
        total = {"word_count": 0, "msg_count": 0, "char_count": 0,
                 "reply_count": 0, "mention_count": 0, "days_active": 0}
        daily_counts = []

        for i in range(days):
            d = (now - timedelta(days=i)).strftime("%Y%m%d")
            data = await r.hgetall(K_MSG(gid, uid, d))
            if data:
                mc = int(data.get("msg_count", 0))
                total["word_count"] += int(data.get("word_count", 0))
                total["msg_count"] += mc
                total["char_count"] += int(data.get("char_count", 0))
                total["reply_count"] += int(data.get("reply_count", 0))
                total["mention_count"] += int(data.get("mention_count", 0))
                if mc > 0:
                    total["days_active"] += 1
                daily_counts.append(mc)
            else:
                daily_counts.append(0)

        total["daily_counts"] = daily_counts
        total["avg_words_per_msg"] = (
            total["word_count"] / total["msg_count"]
            if total["msg_count"] > 0 else 0
        )
        return total

    async def get_keyword_count(self, r, gid: int, uid: int, group: str, days: int) -> int:
        now = datetime.now(timezone.utc)
        total = 0
        for i in range(days):
            d = (now - timedelta(days=i)).strftime("%Y%m%d")
            val = await r.get(K_KW(gid, uid, d, group))
            if val:
                total += int(val)
        return total

    async def get_user_daily_total(self, r, gid: int, uid: int, date_str: str) -> int:
        score = await r.zscore(f"stats:user_daily:{gid}:{date_str}", str(uid))
        return int(score) if score else 0

    async def days_since_last_activity(self, r, gid: int, uid: int, max_lookback: int = 180) -> int:
        now = datetime.now(timezone.utc)
        for i in range(max_lookback):
            d = (now - timedelta(days=i)).strftime("%Y%m%d")
            count = await self.get_user_daily_total(r, gid, uid, d)
            if count > 0:
                return i
        return max_lookback

    async def get_join_days(self, r, gid: int, uid: int) -> Optional[int]:
        ts_str = await r.get(K_JOIN(gid, uid))
        if ts_str:
            join_ts = int(ts_str)
            return (int(time.time()) - join_ts) // 86400
        return None

    async def scan_user(self, r, gid: int, uid: int, now: datetime, today: str) -> List[PatternAlert]:
        alerts = []
        stats_7d = await self.get_user_msg_stats(r, gid, uid, 7)
        stats_30d = await self.get_user_msg_stats(r, gid, uid, 30)
        days_inactive = await self.days_since_last_activity(r, gid, uid, 180)
        join_days = await self.get_join_days(r, gid, uid)

        # ── 1. Jednorázovka ──
        if stats_30d["msg_count"] == 1 and days_inactive >= 1:
            total_90 = (await self.get_user_msg_stats(r, gid, uid, 90))["msg_count"]
            if total_90 == 1:
                alerts.append(PatternAlert(
                    pattern_name="Jednorázovka", user_id=uid, risk_level="info",
                    description=f"Uživatel napsal pouze 1 příspěvek a poté zmlkl ({days_inactive}d neaktivní).",
                    recommended_action="Okamžitý uvítací DM od mentora. První den je kritický.", emoji="👋"
                ))

        # ── 2. Falešný vrchol (Růžový obláček) ──
        euphoria_kw_7d = await self.get_keyword_count(r, gid, uid, "euphoria", 7)
        methodology_kw_7d = await self.get_keyword_count(r, gid, uid, "methodology", 7)
        if euphoria_kw_7d >= 4 and methodology_kw_7d == 0:
            alerts.append(PatternAlert(
                pattern_name="Falešný vrchol", user_id=uid, risk_level="warning",
                description="Extrémní euforie bez zmínky o metodice (deník, parťák). Riziko nečekaného pádu.",
                recommended_action="Zadat 'servisní úkol' (pomoc nováčkovi) pro ukotvení v realitě.", emoji="☁️"
            ))

        # ── 3. Relapsová únava ──
        relapse_kw_7d = await self.get_keyword_count(r, gid, uid, "relapse_fatigue", 7)
        if relapse_kw_7d >= 3:
            alerts.append(PatternAlert(
                pattern_name="Relapsová únava", user_id=uid, risk_level="critical",
                description=f"Shlukování slov 'znovu'/'zase' ({relapse_kw_7d}x za 7d). Pocit točení se v kruhu.",
                recommended_action="Změna narativu. Přesměrovat na analýzu příčin (Small Wins) místo 'zvedání se'.", emoji="🔁"
            ))

        # ── 4. Noční sova (Biorytmus) ──
        night_msgs, total_msgs_hourly = 0, 0
        for i in range(7):
            d = (now - timedelta(days=i)).strftime("%Y%m%d")
            hour_data = await r.hgetall(f"pat:hour:{gid}:{uid}:{d}")
            for h, c in hour_data.items():
                h_int = int(h)
                total_msgs_hourly += int(c)
                if 1 <= h_int <= 4: night_msgs += int(c)
        if total_msgs_hourly >= 10 and night_msgs / total_msgs_hourly >= 0.4:
            alerts.append(PatternAlert(
                pattern_name="Noční sova", user_id=uid, risk_level="warning",
                description=f"{int((night_msgs/total_msgs_hourly)*100)}% zpráv v čase 01-04. Riziko relapsu 3x vyšší.",
                recommended_action="Doporučit spánek. Noční aktivita supluje dopamin.", emoji="🦉"
            ))

        # ── 5. Rytmus 90 dní ──
        if join_days is not None:
            for milestone in [21, 60, 90]:
                if milestone - 3 <= join_days <= milestone + 1:
                    if stats_7d["msg_count"] > 0:
                        prev_avg = stats_30d["msg_count"] / 30 * 7
                        curr_7d = stats_7d["msg_count"]
                        if curr_7d < prev_avg * 0.7:
                            alerts.append(PatternAlert(
                                pattern_name="Rytmus 90 dní", user_id=uid, risk_level="warning",
                                description=f"Kritický milník {milestone} dní. Aktivita klesla o {int((1 - curr_7d/prev_avg)*100)}%.",
                                recommended_action="Oslava milníku! Mentor by měl pogratulovat dříve, než nastane propad.", emoji="📆"
                            ))

        # ── 6. Explozivní návrat ──
        if days_inactive == 0:
            recent_counts = stats_7d["daily_counts"]
            today_msgs = recent_counts[0] if recent_counts else 0
            if today_msgs >= 15:
                silence_before = 0
                for i in range(1, min(30, len(stats_30d["daily_counts"]))):
                    if stats_30d["daily_counts"][i] == 0: silence_before += 1
                    else: break
                if silence_before >= 10:
                    alerts.append(PatternAlert(
                        pattern_name="Explozivní návrat", user_id=uid, risk_level="warning",
                        description=f"Po {silence_before} dnech ticha napsal {today_msgs}+ zpráv. Riziko 'přepálení'.",
                        recommended_action="Brzdit nadšení. Nařídit klidový režim (max 3 zprávy denně).", emoji="💥"
                    ))

        # ── 7. Emocionální dumping ──
        absolutisms_kw_7d = await self.get_keyword_count(r, gid, uid, "absolutisms", 7)
        if absolutisms_kw_7d >= 8 and stats_7d["msg_count"] > 5:
            alerts.append(PatternAlert(
                pattern_name="Emocionální dumping", user_id=uid, risk_level="critical",
                description=f"Vysoká frekvence absolutismů (vždy, nikdy, všechno). Hrozí stud a burnout.",
                recommended_action="Přesunout do vlákna/ventingu. Snížit tlak na okamžité 'řešení'.", emoji="🤮"
            ))

        # ── 8. Tiché vyhoření ──
        despair_kw = await self.get_keyword_count(r, gid, uid, "despair", 14)
        if despair_kw >= 2 and days_inactive >= 2 and stats_30d["msg_count"] > 5:
            alerts.append(PatternAlert(
                pattern_name="Tiché vyhoření", user_id=uid, risk_level="critical",
                description=f"Pochybnosti ({despair_kw}x za 14d) následované tichem ({days_inactive}d).",
                recommended_action="Okamžitý osobní DM od mentora.", emoji="🕯️"
            ))

        # ── 9. Zdi odvykání ──
        wall_kw_7d = await self.get_keyword_count(r, gid, uid, "wall_keywords", 7)
        if wall_kw_7d >= 4 and stats_7d["avg_words_per_msg"] < 8:
            alerts.append(PatternAlert(
                pattern_name="Zdi odvykání", user_id=uid, risk_level="warning",
                description="Pocit stagnace ('nevím', 'stále stejné') + krátké zprávy. Hrozí ghosting.",
                recommended_action="Výzva k sdílení jednoho konkrétního detailu dne (ne celkového stavu).", emoji="🧱"
            ))

        # ── 10. Osobní investice (Edity) ──
        edit_count_7d = await r.get(K_EDIT(gid, uid, today)) or 0
        if int(edit_count_7d) >= 3:
            alerts.append(PatternAlert(
                pattern_name="Osobní investice", user_id=uid, risk_level="info",
                description="Uživatel intenzivně edituje své příspěvky. Projev vysoké kognitivní investice.",
                recommended_action="Intelektuální výzva nebo hlubší analýza od mentora.", emoji="✍️"
            ))

        # ── 11. Sémantický útlum ──
        if stats_7d["msg_count"] >= 3 and stats_7d["avg_words_per_msg"] < 5:
            alerts.append(PatternAlert(
                pattern_name="Sémantický útlum", user_id=uid, risk_level="info",
                description="Zprávy se zkrátily pod 4 slova (Díky, OK...). Ztráta motivace.",
                recommended_action="Přímá otevřená otázka od mentora vyžadující delší odpověď.", emoji="📉"
            ))

        # ── 12. Poslední monolog ──
        diary_entries = await r.lrange(K_DIARY(gid, uid), 0, -1)
        if len(diary_entries) >= 3:
            alerts.append(PatternAlert(
                pattern_name="Poslední monolog", user_id=uid, risk_level="critical",
                description=f"{len(diary_entries)} příspěvků v deníku bez odpovědi. Hrozí pocit ignorace.",
                recommended_action="Mentor MUSÍ reagovat na každý druhý nepokrytý post.", emoji="📢"
            ))

        # ── 13. Vrstevnické pouto ──
        # Check if user has strong interaction with someone
        cursor = "0"
        while True:
            cursor, keys = await r.scan(cursor=cursor, match=f"pat:reply_pair:{gid}:{uid}:*", count=100)
            for k in keys:
                val = await r.get(k)
                if val and int(val) >= 5:
                    alerts.append(PatternAlert(
                        pattern_name="Vrstevnické pouto", user_id=uid, risk_level="info",
                        description="Vytvořeno silné pouto s jiným uživatelem. Pozor na odchod parťáka.",
                        recommended_action="Kultivovat toto pouto. Pokud jeden přestane psát, oslovit oba.", emoji="🤝"
                    ))
            if cursor == 0 or cursor == "0": break

        # ── 14. Budoucí moderátor / Nadšený pomocník ──
        help_kw_7d = await self.get_keyword_count(r, gid, uid, "help_others", 7)
        if help_kw_7d >= 10:
            risk_level = "info"
            if stats_7d["msg_count"] > 20 and stats_7d["word_count"] < 100:
                 risk_level = "warning" # Dumper of greetings
            
            alerts.append(PatternAlert(
                pattern_name="Nadšený pomocník", user_id=uid, risk_level=risk_level,
                description="Bere na sebe roli neoficiálního moderátora. Hrozí sekundární trauma.",
                recommended_action="Ocenit práci. Pokud je stabilní, zvážit pozvání do týmu.", emoji="🦸"
            ))

        # ── 15. Nenaplněná reciprocita ──
        cursor = "0"
        while True:
            cursor, keys = await r.scan(cursor=cursor, match=K_QUESTION(gid, uid, "*"), count=100)
            for k in keys:
                ts = await r.get(k)
                if ts and (int(time.time()) - int(ts)) > 6 * 3600:
                    alerts.append(PatternAlert(
                        pattern_name="Nenaplněná reciprocita", user_id=uid, risk_level="warning",
                        description="Otázka zůstala bez odpovědi více než 6 hodin. Riziko ztráty důvěry.",
                        recommended_action="Rychlá reakce od moderátora nebo mentora.", emoji="❓"
                    ))
            if cursor == 0 or cursor == "0": break

        # ── 16. Víkendový propad ──
        day_of_week = now.weekday() # 0=Mon, 4=Fri, 5=Sat
        if day_of_week in [0, 1]: # Mon/Tue - check back 3 days
            weekend_sum = sum(stats_7d["daily_counts"][day_of_week+1:day_of_week+4])
            weekday_avg = sum(stats_30d["daily_counts"]) / 30 * 3
            if weekend_sum < weekday_avg * 0.4 and stats_7d["daily_counts"][0] > 0:
                 alerts.append(PatternAlert(
                    pattern_name="Víkendový propad", user_id=uid, risk_level="warning",
                    description="Pád aktivity o víkendu o 60%+. Často spojeno s relapsem.",
                    recommended_action="Zavést 'Friday Check-in' – vyžadovat plán na víkend.", emoji="📉"
                ))

        # ── 17. Tichý boj (Dlouhý restart) ──
        if days_inactive >= 90 and stats_7d["msg_count"] == 1:
            alerts.append(PatternAlert(
                pattern_name="Tichý boj", user_id=uid, risk_level="critical",
                description="Návrat po 90+ dnech jedinou zprávou. Volání o pomoc.",
                recommended_action="Extrémně silná podpora. Žádné výčitky za neaktivitu.", emoji="🏹"
            ))

        # ── 18. Sezónní návrat ──
        if join_days and join_days >= 365 and stats_7d["msg_count"] == 1:
            alerts.append(PatternAlert(
                pattern_name="Sezónní návrat", user_id=uid, risk_level="info",
                description="Návrat po více než roce. Fórum je vnímáno jako bezpečné místo.",
                recommended_action="Vřelé 'Vítej zpátky'. Usnadnit orientaci v novinkách.", emoji="🍂"
            ))

        return alerts

    async def analyze_user_affinity(self, r, gid: int, uid: int, now: datetime, today: str, stats_7d: Dict, stats_30d: Dict, days_inactive: int) -> List[Dict]:
        affinities = []
        # Simplified copy of the logic for brevity in this refactor
        # (Full logic would be migrated here from patterns.py lines 814-900)
        # Adding some key ones for demonstration:
        
        # Night Owl
        total_hourly, night_msgs = 0, 0
        for i in range(7):
            d = (now - timedelta(days=i)).strftime("%Y%m%d")
            hour_data = await r.hgetall(f"pat:hour:{gid}:{uid}:{d}")
            for h, c in hour_data.items():
                total_hourly += int(c)
                if 1 <= int(h) <= 4: night_msgs += int(c)
        if total_hourly > 0:
            score = max(0, min(100, int(((night_msgs/total_hourly) / 0.6) * 100)))
            if score > 10:
                affinities.append({"name": "Noční sova", "score": score, "emoji": "🦉", "desc": f"Noční aktivita.", "hint": "Spánek je základ."})
        
        affinities.sort(key=lambda x: x["score"], reverse=True)
        return affinities[:5]

    async def scan_group_patterns(self, r, gid: int, now: datetime, today: str, user_ids: Set[int]) -> List[PatternAlert]:
        alerts = []
        
        # ── 1. Zrcadlový relaps (Social Contagion) ──
        # Check if multiple users announced relapse in the last 4 hours
        relapse_uids = []
        for uid in user_ids:
            relapse_kw = await self.get_keyword_count(r, gid, uid, "relapse_word", 1) # Just today
            if relapse_kw > 0:
                relapse_uids.append(uid)
        
        if len(relapse_uids) >= 3:
            # Aggregate as a group alert or multiple individual alerts
            for uid in relapse_uids:
                alerts.append(PatternAlert(
                    pattern_name="Zrcadlový relaps", user_id=uid, risk_level="critical",
                    description=f"Detekována 'nákaza' relapsem v kanálu. {len(relapse_uids)} lidí selhalo v krátkém čase.",
                    recommended_action="Okamžitý intervenční post moderátora. Změnit téma na pozitivní aktivitu.", emoji="🌋"
                ))
                
        return alerts
