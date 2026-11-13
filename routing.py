# routing.py
"""
Модуль правил маршрутизации и DNS для OverlordMasque.
"""

PRESET_RU = "ru_services"
PRESET_CINEMA = "cinema"
PRESET_BITTORRENT = "bittorrent"
PRESET_GAMES = "online_games"
PRESET_ADS = "ads"


PRESETS = {
    PRESET_RU: {
        "label": "Российские сервисы",
        "domains": [
            "geosite:category-gov-ru",
            "geosite:yandex",
            "domain:gosuslugi.ru",
            "domain:sberbank.ru",
            "domain:tinkoff.ru",
            "domain:vtb.ru",
            "domain:alfabank.ru",
            "domain:yandex.ru",
            "domain:yandex.net",
            "domain:vk.com",
            "domain:vk.ru",
            "domain:mail.ru",
            "domain:imgsmail.ru",
            "domain:mycdn.me",
            "domain:vkuserphoto.ru",
            "domain:userapi.com",
            "domain:ozon.ru",
            "domain:ozone.ru",
            "domain:ozonusercontent.com",
            "domain:wildberries.ru",
            "domain:avito.ru",
            "domain:avito.st",
            "domain:kinopoisk.ru",
            "domain:pikabu.ru",
            "domain:ok.ru",
            "domain:okcdn.ru",
            "domain:dzen.ru",
            "domain:dzeninfra.ru",
        ],
        "ips": ["geoip:ru"],
        "action": "direct",
    },
    PRESET_CINEMA: {
        "label": "Онлайн-кинотеатры",
        "domains": [
            "domain:ivi.ru",
            "domain:okko.tv",
            "domain:wink.ru",
            "domain:more.tv",
            "domain:premier.one",
            "domain:start.ru",
            "domain:kion.ru",
            "domain:amediateka.ru",
            "geosite:netflix",
            "geosite:hbo",
            "geosite:disney",
        ],
        "ips": [],
        "action": "direct",
    },
    PRESET_BITTORRENT: {
        "label": "BitTorrent (по протоколу)",
        "domains": [],
        "ips": [],
        "action": "direct",
    },
    PRESET_GAMES: {
        "label": "Онлайн-игры",
        "domains": [
            "domain:tanki.su",
            "domain:lesta.ru",
            "domain:korabli.su",
            "domain:tanksblitz.ru",
            "domain:wargaming.net",
            "domain:steampowered.com",
            "domain:steamcommunity.com",
            "domain:dota2.com",
            "domain:csgo.com",
            "domain:valvesoftware.com",
            "domain:mihoyo.com",
            "domain:hoyoverse.com",
            "domain:warface.com",
            "domain:warface.ru",
            "domain:crossout.net",
            "domain:crossout.ru",
            "domain:pubgmobile.com",
        ],
        "ips": [],
        "action": "direct",
    },
    PRESET_ADS: {
        "label": "Заблокировать рекламу и трекеры",
        "domains": ["geosite:category-ads-all"],
        "ips": [],
        "action": "block",
    },
}


RU_DNS_PRIMARY = "77.88.8.8"
RU_DNS_SECONDARY = "76.76.2.0"
DEFAULT_DNS = ["1.1.1.1", "8.8.8.8"]


def parse_custom_line(line: str):
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith(("geosite:", "geoip:")):
        if line.startswith("geoip:"):
            return ("ip", line)
        return ("domain", line)
    if line.startswith(("domain:", "domainKeyword:", "domainRegex:", "full:", "keyword:", "regexp:")):
        return ("domain", line)
    if line.startswith("domainSuffix:"):
        return ("domain", "domain:" + line[len("domainSuffix:"):])
    if line.startswith("ip:"):
        return ("ip", line)
    if "/" in line and all(c.isdigit() or c in ".:" for c in line):
        return ("ip", f"ip:{line}")
    parts = line.split(".")
    if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return ("ip", f"ip:{line}")
    return ("domain", f"domain:{line}")


def build_direct_lists(presets: list, custom_lines: list) -> tuple:
    direct_domains = []
    direct_ips = []
    block_domains = []
    block_ips = []

    for preset_id in presets:
        preset = PRESETS.get(preset_id)
        if not preset:
            continue
        target_domains = block_domains if preset["action"] == "block" else direct_domains
        target_ips = block_ips if preset["action"] == "block" else direct_ips
        target_domains.extend(preset["domains"])
        target_ips.extend(preset["ips"])

    for line in custom_lines:
        parsed = parse_custom_line(line)
        if not parsed:
            continue
        kind, value = parsed
        if kind == "domain":
            direct_domains.append(value)
        else:
            direct_ips.append(value)

    return direct_domains, direct_ips, block_domains, block_ips


def build_routing_rules(presets: list, custom_lines: list,
                        bypass_bittorrent: bool,
                        use_ru_blocked_filter: bool = False,
                        bypass_ru_tld: bool = False) -> list:
    rules = []

    if bypass_bittorrent:
        rules.append({
            "type": "field",
            "protocol": ["bittorrent"],
            "outboundTag": "direct",
        })

    # Все .ru и .рф домены — напрямую (до geoip/geosite)
    if bypass_ru_tld:
        rules.append({
            "type": "field",
            "domain": [
                "regexp:\\.ru$",
                "regexp:\\.xn--p1ai$",
            ],
            "outboundTag": "direct",
        })

    direct_domains, direct_ips, block_domains, block_ips = build_direct_lists(presets, custom_lines)

    if use_ru_blocked_filter:
        rules.append({
            "type": "field",
            "domain": ["geosite:category-ru"],
            "ip": ["geoip:ru-blocked"],
            "outboundTag": "proxy",
        })

    if direct_domains:
        rules.append({
            "type": "field",
            "domain": direct_domains,
            "outboundTag": "direct",
        })

    if direct_ips:
        rules.append({
            "type": "field",
            "ip": direct_ips,
            "outboundTag": "direct",
        })

    if block_domains:
        rules.append({
            "type": "field",
            "domain": block_domains,
            "outboundTag": "block",
        })

    if block_ips:
        rules.append({
            "type": "field",
            "ip": block_ips,
            "outboundTag": "block",
        })

    rules.append({
        "type": "field",
        "inboundTag": ["tun-in"],
        "outboundTag": "proxy",
    })

    return rules


def build_dns_config(direct_domains: list, use_ru_dns: bool) -> dict:
    if not use_ru_dns or not direct_domains:
        return {"servers": list(DEFAULT_DNS)}

    return {
        "servers": [RU_DNS_PRIMARY, RU_DNS_SECONDARY] + DEFAULT_DNS,
        "rules": [
            {"domain": direct_domains, "server": RU_DNS_PRIMARY},
        ],
    }