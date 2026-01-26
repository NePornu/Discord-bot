# DNS Nastavení pro discord.nepornu.cz

## ✅ Reverse Proxy Nakonfigurován

Nginx reverse proxy byl úspěšně nakonfigurován v Discourse containeru.

## Informace o serveru

- **IP adresa serveru**: `207.180.223.191`
- **Dashboard port (interní)**: `8092`
- **Přístup (po DNS)**: `http://discord.nepornu.cz` (bez portu!)

## DNS Konfigurace

V DNS správě pro doménu `nepornu.cz` přidejte následující záznam:

### Typ A záznam

```
Název (Host):    discord
Typ:             A
Hodnota (IP):    207.180.223.191
TTL:             3600 (nebo výchozí)
```

Nebo v textovém formátu:
```
discord.nepornu.cz.  IN  A  207.180.223.191
```

## Přístup k Dashboardu

Po propagaci DNS (obvykle 5-60 minut) bude dashboard dostupný na:

**URL**: `http://discord.nepornu.cz` ✅ **BEZ PORTU!**

### Test připojení

Ihned přes IP (s portem):
```bash
http://207.180.223.191:8092
```

## Ověření DNS

Po nastavení můžete ověřit DNS záznam pomocí:

```bash
# Linux/Mac
nslookup discord.nepornu.cz

# Nebo
dig discord.nepornu.cz

# Windows
nslookup discord.nepornu.cz
```

Očekávaný výstup:
```
discord.nepornu.cz has address 207.180.223.191
```

## Důležité poznámky

⚠️ **Port 8092 musí být ve firewallu povolen**:
```bash
# Zkontrolujte, zda je port otevřený
ufw status | grep 8092

# Pokud není, otevřete jej:
ufw allow 8092/tcp
```

✅ **Dashboard již běží** na `http://207.180.223.191:8092`

## Pro budoucí HTTPS

Pokud budete chtít později přidat HTTPS bez portu, budete potřebovat:
1. Reverse proxy (Nginx/Apache)
2. SSL certifikát (Let's Encrypt)

To ale vyžaduje zastavení Discourse containeru nebo jiné řešení konfliktu portu 80/443.
