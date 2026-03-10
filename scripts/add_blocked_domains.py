import asyncio
import json
import re
from shared.python.redis_client import get_redis_client

# Domains from user request
DOMAINS = [
    "anybunny.org", "badfetish.org", "ballbustinfootlovin.fetlovin.com", "ballbusting.cc",
    "ballbusting-guru.org", "bangbros.com", "b-ass.org", "bestsexxxporn.com",
    "blacked.com", "bongacams.com", "brazzers.com", "br.spankbang.com",
    "cambro.com", "clips4sale.com", "cn.pornhub.com", "cs.spankbanglive.com",
    "cuntwars.com", "cz.pornhub.com", "cz.xhamster1.com", "cz.xhamster1.desi",
    "pornub.com", "pornub.co",
    "cz.xhamster2.com", "cz.xhamster2.desi", "cz.xhamster.com", "cz.xhamster.desi",
    "darknessporn.com", "de.pornhub.com", "de.spankbang.com", "de.xhamster1.com",
    "de.xhamster2.com", "de.xhamster.com", "dlouha-videa.cz", "dogfartnetwork.com",
    "erothots.co", "es.pornhub.com", "es.spankbang.com", "es.xhamster1.com",
    "es.xhamster2.com", "es.xhamster.com", "faperoni.com", "faphouse.com",
    "feetadoration.com", "femdom-pov.me", "femdomup.net", "femdomzzz.com",
    "fetishbreak.com", "fetish-island.com", "ffetish.video", "footadoration.com",
    "footstockings.com", "fr.pornhub.com", "fr.spankbang.com", "fr.xhamster1.com",
    "fr.xhamster2.com", "fr.xhamster.com", "hdxporntube.com", "hentaiheroes.com",
    "hotmovs.com", "id.spankbang.com", "imagefap.com", "iporntv.net",
    "it.pornhub.com", "it.spankbang.com", "it.xhamster1.com", "it.xhamster2.com",
    "it.xhamster.com", "iwantclips.com", "jerkplanet.org", "joi4you.com",
    "joiasmr.com", "joi-me.com", "jp.pornhub.com", "jp.spankbang.com",
    "la.spankbang.com", "livejasmin.com", "loveherfeet.com", "manyvids.com",
    "megaxh.com", "menareslaves.com", "mixfemdomcc.com", "motherless.com",
    "m.spankbang.com", "ms.spankbang.com", "m.tnaflix.com", "nesaporn.com",
    "new-porn.video", "nl.pornhub.com", "nl.spankbang.com", "noodlemagazine.com",
    "norcalfeet.com", "nudevista.com", "onlyfans.com", "onlyfootfetish.net",
    "pictoa.com", "pl.pornhub.com", "pl.spankbang.com", "pl.xhamster1.com",
    "pl.xhamster2.com", "pl.xhamster.com", "popsexy.net", "pornfd.com",
    "porngeek.com", "porngo.xxx", "pornhub.com", "pornmate.com",
    "pornmedium.com", "pornpics.com", "pornpictureshq.com", "pornuj.cz",
    "pornX.to", "pornzog.com", "pt.pornhub.com", "pt.spankbang.com",
    "pvideo.cz", "qoqh.com", "realitykings.com", "redtube.com",
    "rexxx.com", "rt.pornhub.com", "ru.spankbang.com", "se.spankbang.com",
    "sex.com", "spankbang.com", "spankbanglive.com", "spankbang.party",
    "static.spankbang.com", "theporndude.com", "th.spankbang.com", "tnaflix.com",
    "toppornsites.com", "tr.spankbang.com", "tubator.com", "tubesafari.com",
    "tushy.com", "twpornstars.com", "txxx.com", "videosection.com",
    "wikifeet.com", "wonporn.com", "xhamster1.com", "xhamster1.desi",
    "xhamster2.com", "xhamster2.desi", "xhamster.com", "xhamster.desi",
    "xhamsters.club", "xmegadrive.com", "xnxx.com", "xvideos.com",
    "xxxfemdom.org", "xxxin.mobi", "x-x-x.tube", "xxxvideos247.com",
    "yespornpics.com", "youjizz.com", "youporn.com"
]

GUILD_IDS = [
    882936285738704897, # NePornu.cz Main
    1240685784915382343 # Moderator Training Ground
]

async def add_filters():
    # Build a regex that matches any of these domains
    # We escape dots and use word boundaries to avoid false positives (e.g., examplepornhub.com)
    pattern = r"(?:https?://)?(?:[^/\s]+\.)?(" + "|".join([re.escape(d) for d in DOMAINS]) + r")(?:\/|\s|$)"
    
    r = await get_redis_client()
    for guild_id in GUILD_IDS:
        key = f"automod:filters:{guild_id}"
        val = await r.get(key)
        filters = json.loads(val) if val else []
        
        # Check if already exists
        if any(f["pattern"] == pattern for f in filters):
            print(f"Filter already exists for guild {guild_id}")
            continue
            
        filters.append({
            "pattern": pattern,
            "allowed_roles": [],
            "allowed_channels": [],
            "whitelist": [],
            "action": "auto_reject"
        })
        await r.set(key, json.dumps(filters))
        print(f"Added auto-reject filter to guild {guild_id}")
    await r.close()

if __name__ == "__main__":
    asyncio.run(add_filters())
