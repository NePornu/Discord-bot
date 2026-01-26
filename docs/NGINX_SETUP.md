# Nginx Setup for Discord Dashboard

## Issue

Apache již běží na portu 80/443, proto nelze použít Nginx přímo.

## Řešení: Apache VirtualHost

Místo Nginxu použijeme Apache jako reverse proxy pro dashboard.

### Krok 1: Vytvoření Apache VirtualHost

Vytvořte soubor `/etc/apache2/sites-available/discord-dashboard.conf`:

```apache
<VirtualHost *:80>
    ServerName discord.nepornu.cz

    # Reverse proxy to dashboard on port 8092
    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:8092/
    ProxyPassReverse / http://127.0.0.1:8092/

    # Static files
    ProxyPass /static/ http://127.0.0.1:8092/static/
    ProxyPassReverse /static/ http://127.0.0.1:8092/static/

    # Logs
    ErrorLog /var/log/apache2/discord_dashboard_error.log
    CustomLog /var/log/apache2/discord_dashboard_access.log combined
</VirtualHost>
```

### Krok 2: Enable mod_proxy

```bash
a2enmod proxy
a2enmod proxy_http
a2ensite discord-dashboard
systemctl reload apache2
```

### Krok 3: DNS

Ujistěte se, že DNS záznam pro `discord.nepornu.cz` ukazuje na IP serveru.

### Krok 4: Test

```bash
curl -I http://discord.nepornu.cz
```

Dashboard bude dostupný na: **http://discord.nepornu.cz**

## Pro HTTPS

Pokud chcete HTTPS, použijte Certbot:

```bash
certbot --apache -d discord.nepornu.cz
```
