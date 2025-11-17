# Bezpečnost a soukromí

- **Token** nenechávej v repozitáři. `bot_token.py` drž lokálně/na serveru.
- **Message Content Intent** používej proto, že bot čte obsah zpráv (purge, výzvy, emojirole, reporty).
- Respektuj **Discord ToS** a rate-limity (notify má úmyslně velké rozestupy).
- Pro **Manage Roles** zajisti, aby botova role byla **nad** rolemi, které spravuje.
- Při nasazení používej *least privilege* a oddělený účet (uživatele) pro běh služby.
