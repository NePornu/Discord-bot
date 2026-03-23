import time
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Set, Optional
from .common import PatternAlert, K_MSG, K_KW, K_EDIT, K_JOIN, K_DIARY, K_QUESTION, K_STAFF_RESPONSE, K_FIRST

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
    
    async def get_total_months_active(self, r, gid: int, uid: int, months: int = 6) -> int:
        return 0 # Placeholder

    async def get_join_days(self, r, gid: int, uid: int) -> Optional[int]:
        ts_str = await r.get(K_JOIN(gid, uid))
        if ts_str:
            join_ts = int(ts_str)
            return (int(time.time()) - join_ts) // 86400
        return None

    async def scan_user(self, r, gid: int, uid: int, now: datetime, today: str) -> List[PatternAlert]:
        alerts = []
        stats_7d = await self.get_user_msg_stats(r, gid, uid, 7)
        stats_14d = await self.get_user_msg_stats(r, gid, uid, 14)
        stats_30d = await self.get_user_msg_stats(r, gid, uid, 30)
        days_inactive = await self.days_since_last_activity(r, gid, uid, 180)
        join_days = await self.get_join_days(r, gid, uid)
        
        # --- Time-based context for UI ---
        last_msg_date = (now - timedelta(days=days_inactive)).strftime("%d.%m.%Y") if days_inactive < 180 else "Nikdy"
        first_msg_ts = await r.hgetall(K_FIRST(gid, uid))
        first_msg_date = datetime.fromtimestamp(int(first_msg_ts["timestamp"])).strftime("%d.%m.%Y") if first_msg_ts else "Neznámo"

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
        if (euphoria_kw_7d >= 4 and methodology_kw_7d == 0) or (join_days and 75 <= join_days <= 95 and euphoria_kw_7d >= 3):
            alerts.append(PatternAlert(
                pattern_name="Falešný vrchol", user_id=uid, risk_level="warning",
                description="Extrémní euforie bez zmínky o metodice. Často kolem 90. dne abstinence.",
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
        if total_msgs_hourly >= 8 and night_msgs / total_msgs_hourly >= 0.4:
            alerts.append(PatternAlert(
                pattern_name="Noční sova", user_id=uid, risk_level="warning",
                description=f"{int((night_msgs/total_msgs_hourly)*100)}% zpráv v čase 01-04 (Riziko relapsu 3x vyšší).",
                recommended_action="Doporučit spánek. Noční aktivita supluje dopamin.", emoji="🦉"
            ))

        # ── 5. Rytmus 90 dní ──
        if join_days is not None:
            for milestone in [21, 60, 90]:
                if milestone - 3 <= join_days <= milestone + 1:
                    if stats_7d["msg_count"] > 0:
                        prev_avg = stats_30d["msg_count"] / 30 * 7
                        curr_7d = stats_7d["msg_count"]
                        if curr_7d < prev_avg * 0.75:
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
        if absolutisms_kw_7d >= 8 and stats_7d["msg_count"] > 3:
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

        # ── 8b. Náhlé zmizení ──
        if days_inactive >= 3 and days_inactive <= 7:
            stats_before = await self.get_user_msg_stats(r, gid, uid, 14)
            msgs_prev_week = sum(stats_before["daily_counts"][7:])
            if msgs_prev_week >= 5 and stats_7d["msg_count"] == 0:
                alerts.append(PatternAlert(
                    pattern_name="Náhlé zmizení", user_id=uid, risk_level="warning",
                    description=f"Uživatel byl velmi aktivní ({msgs_prev_week} zpráv minulý týden), ale už {days_inactive} dní mlčí.",
                    recommended_action="Nezávazné pošťouchnutí. Zjistit, jestli se něco nestalo.", emoji="👻"
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
        edit_count_7d = await r.get(f"pat:edit:{gid}:{uid}:{today}") or 0
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
                description="Zprávy se zkrátily pod 5 slov (Díky, OK...). Ztráta motivace.",
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
        cursor = "0"
        while True:
            cursor, keys = await r.scan(cursor=cursor, match=f"pat:reply_pair:{gid}:{uid}:*", count=100)
            for k in keys:
                val = await r.get(k)
                if val and int(val) >= 5:
                    alerts.append(PatternAlert(
                        pattern_name="Vrstevnické pouto", user_id=uid, risk_level="info",
                        description="Vytvořeno silné pouto s parťákem. Pozor na jeho případný odchod.",
                        recommended_action="Kultivovat toto pouto. Pokud jeden přestane psát, oslovit oba.", emoji="🤝"
                    ))
            if cursor == 0 or cursor == "0": break

        # ── 14. Nadšený pomocník ──
        help_kw_7d = await self.get_keyword_count(r, gid, uid, "help_others", 7)
        personal_kw_7d = await self.get_keyword_count(r, gid, uid, "methodology", 7)
        if help_kw_7d >= 10:
            risk = "info"
            if personal_kw_7d < 2: risk = "warning"
            alerts.append(PatternAlert(
                pattern_name="Nadšený pomocník", user_id=uid, risk_level=risk,
                description=f"Vysoká koncentrace na pomoc ostatním ({help_kw_7d}x). Hrozí sekundární trauma.",
                recommended_action="Ocenit práci, ale připomenout vlastní deník a odpočinek.", emoji="🦸"
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
                        description="Otázka bez odpovědi více než 6 hodin. Riziko pocitu osamocení.",
                        recommended_action="Rychlá reakce od moderátora nebo mentora.", emoji="❓"
                    ))
            if cursor == 0 or cursor == "0": break

        # ── 16. Víkendový propad ──
        day_of_week = now.weekday()
        if day_of_week in [0, 1]: 
            weekend_msgs = sum(stats_7d["daily_counts"][day_of_week+1:day_of_week+4])
            weekday_avg = sum(stats_14d["daily_counts"]) / 14 * 3
            if weekday_avg > 1 and weekend_msgs < weekday_avg * 0.4:
                 alerts.append(PatternAlert(
                    pattern_name="Víkendový propad", user_id=uid, risk_level="warning",
                    description="Pád aktivity o víkendu o 60%+. Často předchází ohlášení relapsu.",
                    recommended_action="Zavést 'Friday Check-in' – vyžadovat plán na víkend.", emoji="📉"
                ))

        # ── 17. Tichý boj ──
        if days_inactive >= 90 and stats_7d["msg_count"] == 1:
            alerts.append(PatternAlert(
                pattern_name="Tichý boj", user_id=uid, risk_level="critical",
                description="Návrat po 90+ dnech jedinou zprávou. Volání o pomoc.",
                recommended_action="Extrémně silná podpora. Žádné výčitky za neaktivitu.", emoji="🏹"
            ))

        # ── 18. Sezónní návrat ──
        if join_days and join_days >= 365 and stats_7d["msg_count"] == 1 and days_inactive >= 180:
            alerts.append(PatternAlert(
                pattern_name="Sezónní návrat", user_id=uid, risk_level="info",
                description="Návrat po více než roce. Fórum je vnímáno jako stabilní záchranný bod.",
                recommended_action="Vřelé 'Vítej zpátky'. Usnadnit orientaci v případných novinkách.", emoji="🍂"
            ))

        # ── 21. Aktivní pozorovatel ──
        if stats_7d["msg_count"] == 1:
            first_data = await r.hgetall(K_FIRST(gid, uid))
            if first_data:
                 first_ts = int(first_data["timestamp"])
                 join_ts_str = await r.get(K_JOIN(gid, uid))
                 if join_ts_str:
                     silent_time = first_ts - int(join_ts_str)
                     if silent_time > 30 * 86400:
                         alerts.append(PatternAlert(
                            pattern_name="Aktivní pozorovatel", user_id=uid, risk_level="info",
                            description="První příspěvek po více než měsíci tichého pozorování.",
                            recommended_action="Okamžité nasměrování na krizový plán nebo deník.", emoji="⚡"
                        ))

        # ── 22. Autoritativní přijetí ──
        staff_resp_time = await r.get(K_STAFF_RESPONSE(gid, uid))
        if staff_resp_time and int(staff_resp_time) < 2 * 3600:
            alerts.append(PatternAlert(
                pattern_name="Autoritativní přijetí", user_id=uid, risk_level="info",
                description="Rychlá reakce mentora na první post (<2h). Zvyšuje retenci o 70%.",
                recommended_action="Skvělá práce týmu! Udržet vřelou komunikaci.", emoji="⭐"
            ))

        # ── 25. Stud po dumpingu ──
        long_del_7d = await r.get(f"pat:del_long:{gid}:{uid}:{today}")
        if long_del_7d and int(long_del_7d) >= 1:
            alerts.append(PatternAlert(
                pattern_name="Stud po dumpingu", user_id=uid, risk_level="warning",
                description="Smazání dlouhého příspěvku krátce po odeslání. Pocit studu.",
                recommended_action="Mentor by měl napsat do DM: 'Viděl jsem to, bylo to silné, neřeš to'.", emoji="🙈"
            ))

        # ── 26. Moderátorský syndrom ──
        preachy_kw_7d = await self.get_keyword_count(r, gid, uid, "preachy", 7)
        out_in_ratio = stats_7d["msg_count"] / (stats_7d["reply_count"] or 1)
        if preachy_kw_7d >= 3 and out_in_ratio > 4:
            alerts.append(PatternAlert(
                pattern_name="Moderátorský syndrom", user_id=uid, risk_level="warning",
                description="Přílišná snaha 'kázat' ostatním. Podrážděný tón. Riziko vyhoření.",
                recommended_action="Povinná pauza. Mentor by měl uživatele zbrzdit.", emoji="🧘"
            ))

        # ── 27. Komunitní lepidlo ──
        mention_count = await self.get_keyword_count(r, gid, uid, "interaction", 7)
        reply_count = stats_7d["reply_count"]
        social_ratio = (reply_count + mention_count) / max(stats_7d["msg_count"], 1)
        if (mention_count >= 10 or social_ratio > 0.6) and stats_7d["msg_count"] >= 10:
            alerts.append(PatternAlert(
                pattern_name="Komunitní lepidlo", user_id=uid, risk_level="info",
                description=f"Vysoká sociální interaktivita ({int(social_ratio*100)}% zpráv je interakce).",
                recommended_action="Ocenit přínos pro komunitu a podporu ostatních.", emoji="🤝"
            ))

        return alerts

    async def analyze_user_affinity(self, r, gid: int, uid: int, now: datetime, today: str, stats_7d: Dict, stats_30d: Dict, days_inactive: int) -> List[Dict]:
        affinities = []
        
        # 0. Active Alerts - Force 100% fulfillment
        alerts = await self.scan_user(r, gid, uid, now, today)
        active_names = {a.pattern_name for a in alerts}
        for a in alerts:
             affinities.append({
                "name": a.pattern_name, "score": 100, "emoji": a.emoji,
                "desc": "Vzorec je aktivní.",
                "hint": a.recommended_action
            })

        # 1. Nocturnal Activity %
        total_hourly, night_msgs = 0, 0
        for i in range(7):
            d = (now - timedelta(days=i)).strftime("%Y%m%d")
            hour_data = await r.hgetall(f"pat:hour:{gid}:{uid}:{d}")
            for h, c in hour_data.items():
                total_hourly += int(c)
                if 1 <= int(h) <= 4: night_msgs += int(c)
        
        if "Noční sova" not in active_names:
            score = 0
            desc = "Nezjištěno."
            if total_hourly > 0:
                night_pct = (night_msgs / total_hourly) * 100
                score = min(100, int((night_pct / 40) * 100))
                desc = f"{int(night_pct)}% zpráv v noci (01-04)"
            
            if score > 0 or total_hourly > 0:
                affinities.append({
                    "name": "Noční sova", "score": score, "emoji": "🦉", 
                    "desc": desc, "hint": "Sledovat biorytmus."
                })
        
        # 2. Relapse Fatigue %
        if "Relapsová únava" not in active_names:
            relapse_fatigue_kw = await self.get_keyword_count(r, gid, uid, "relapse_fatigue", 7)
            score = min(100, int((relapse_fatigue_kw / 3) * 100))
            if score > 0 or stats_7d["msg_count"] > 0:
                affinities.append({
                    "name": "Relapsová únava", "score": score, "emoji": "🔁",
                    "desc": f"Nalezeno {relapse_fatigue_kw}/3 klíčových slov.",
                    "hint": "Bránit pocitu točení v kruhu."
                })

        # 3. Emotional Dumping %
        if "Emoční dumping" not in active_names:
            absolutisms_kw = await self.get_keyword_count(r, gid, uid, "absolutisms", 7)
            score = min(100, int((absolutisms_kw / 8) * 100))
            if score > 0 or stats_7d["msg_count"] > 0:
                affinities.append({
                    "name": "Emoční dumping", "score": score, "emoji": "🤮",
                    "desc": f"Nalezeno {absolutisms_kw}/8 absolutismů.",
                    "hint": "Pozor na slova 'vždy' a 'nikdy'."
                })

        # 4. Help Others
        if "Pomocník" not in active_names:
            help_others = await self.get_keyword_count(r, gid, uid, "help_others", 7)
            score = min(100, int((help_others / 10) * 100))
            if score > 0:
                affinities.append({
                    "name": "Pomocník", "score": score, "emoji": "🦸",
                    "desc": f"{help_others} podporujících zpráv.",
                    "hint": "Skvělá aktivita pro komunitu."
                })
            
        # 5. Euphoria
        if "Růžový obláček" not in active_names:
            euphoria_kw = await self.get_keyword_count(r, gid, uid, "euphoria", 7)
            score = min(100, int((euphoria_kw / 4) * 100))
            if score > 0:
                affinities.append({
                    "name": "Růžový obláček", "score": score, "emoji": "☁️",
                    "desc": f"Míra euforie: {euphoria_kw}/4.",
                    "hint": "Neponechat nic náhodě."
                })

        affinities.sort(key=lambda x: x["score"], reverse=True)
        return affinities[:6]

    async def scan_group_patterns(self, r, gid: int, now: datetime, today: str, user_ids: Set[int]) -> List[PatternAlert]:
        alerts = []
        relapse_uids = []
        for uid in user_ids:
            relapse_kw = await self.get_keyword_count(r, gid, uid, "relapse_word", 1) 
            if relapse_kw > 0:
                relapse_uids.append(uid)
        
        if len(relapse_uids) >= 3:
            for uid in relapse_uids:
                alerts.append(PatternAlert(
                    pattern_name="Zrcadlový relaps", user_id=uid, risk_level="critical",
                    description=f"Detekována 'nákaza' relapsem v kanálu. {len(relapse_uids)} lidí selhalo v krátkém čase.",
                    recommended_action="Okamžitý intervenční post moderátora. Změnit téma na pozitivní aktivitu.", emoji="🌋"
                ))
        return alerts
