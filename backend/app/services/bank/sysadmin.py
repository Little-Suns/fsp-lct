"""SysAdmin / Support, сюжет «Понедельник в офисе»: офис на ~300 сотрудников — очередь обращений, сеть, серверы, бэкапы, учётки.
По одному простому семейству и по 3 сценарных на компетенцию плюс 4 сложных (Senior/Lead, b 2,4–2,9)."""

from app.services.items import _choice, _log, family, simple

SPEC = "SysAdmin / Support"
DOMAINS = ["corp.local", "office.lan", "ad.severvet.lan", "hq.local"]


def _mac(rng) -> str:
    return ":".join(f"{rng.randint(0, 255):02x}" for _ in range(6))


# ============================== простые ==============================

simple(SPEC, "Диагностика инцидентов", -1.2, "Интернет не работает", "⟨who⟩ пишет: «не работает интернет». Сайты по имени не открываются, а ping ⟨ip⟩ по адресу проходит.",
       "Где искать причину?", "В DNS: какой сервер имён получил компьютер и отвечает ли он",
       ["В кабеле: заменить патч-корд от компьютера до сетевой розетки", "В браузере: сбросить его настройки и очистить кэш и cookie", "В сетевой карте: переустановить драйвер и сбросить стек TCP/IP"],
       {"who": ["Бухгалтер", "Менеджер отдела продаж", "Секретарь приёмной"], "ip": ["77.88.8.8", "8.8.8.8", "1.1.1.1"]})
simple(SPEC, "Сети", -0.5, "Новый VLAN", "Офис расширяется: в VLAN ⟨v⟩ нужно разместить до ⟨n⟩ устройств, адреса выдаются из 10.⟨v⟩.0.0.",
       "Какую наименьшую подсеть выделить?", "⟨r⟩", ["⟨w1⟩", "⟨w2⟩", "⟨w3⟩"],
       lambda rng: (lambda v, n: (lambda p: {"v": v, "n": n, **{k: f"/{q} — до {2 ** (32 - q) - 2} узлов" for k, q in zip(("r", "w1", "w2", "w3"), (p, p + 1, p - 1, p + 2))}})(
           23 if n <= 510 else 22))(rng.choice([20, 30, 40]), rng.choice([300, 420, 480, 700, 900])))
simple(SPEC, "Учётные записи и доступ", -1.4, "Новый сотрудник", "В ⟨dep⟩ вышел новый сотрудник. Ему нужен доступ к общей папке отдела «⟨f⟩».",
       "Как выдать доступ правильно?", "Добавить его в доменную группу отдела, которой выданы права на папку",
       ["Выдать права на папку лично его учётной записи, чтобы не трогать группы", "Передать ему логин и пароль коллеги, пока доступ оформляется", "Включить его в группу «Администраторы домена» на испытательный срок"],
       {"dep": ["бухгалтерию", "отдел продаж", "отдел кадров"], "f": ["Документы", "Отчёты", "Шаблоны"]})
simple(SPEC, "Резервное копирование", -1.0, "Бэкап рядом", "Ночные копии файлового сервера ⟨srv⟩ складываются на второй диск этого же сервера, ⟨n⟩ последних копий.",
       "Что не так?", "Нет копии на другом носителе и вне офиса (правило 3-2-1): пожар или шифровальщик заберут всё сразу",
       ["Хранится слишком мало копий: нужно держать хотя бы 30 ночных копий на этом же диске", "Второй диск надо объединить с первым в RAID 1 — зеркало и будет надёжной резервной копией", "Копии нужно делать каждый час, а не раз в сутки, иначе теряется рабочий день"],
       {"srv": ["fs01", "srv-files", "fs-main"], "n": [7, 14]})
simple(SPEC, "Серверы и ОС", -0.8, "Медленный сервер", "Сервер ⟨srv⟩ отвечает медленно. В top: load average ⟨la⟩ при 4 ядрах, us 6 %, sy 3 %, wa ⟨wa⟩ %.",
       "Что вероятнее всего?", "Узкое место — диск: процессы ждут ввода-вывода, смотреть iostat и iotop",
       ["Не хватает ядер: добавить виртуальной машине ещё 4 vCPU и перезагрузить её", "Утечка памяти: перезапустить самые «тяжёлые» службы", "Сеть перегружена: проверить загрузку интерфейса"],
       {"srv": ["srv-1c", "fs01", "db01"], "la": [9.8, 12.4, 15.1], "wa": [64, 72, 81]})
simple(SPEC, "Работа с обращениями", -1.6, "Ничего не работает", "В очередь пришло обращение от ⟨who⟩: «Ничего не работает!!! Срочно!»",
       "Что сделать первым?", "Уточнить: что именно не работает, с какого времени, какая ошибка и у кого ещё",
       ["Сразу поднять приоритет до критического и эскалировать обращение на третью линию", "Закрыть обращение: в нём нет описания проблемы", "Удалённо перезагрузить компьютер пользователя"],
       {"who": ["сотрудника склада", "менеджера отдела продаж", "юриста"]})


# ============================== Диагностика инцидентов ==============================


@family("adm_inc_dupip", SPEC, "Диагностика инцидентов", "choice", 2.2, -1.1)
def _(rng):
    net = rng.choice(["192.168.10", "10.10.20", "172.16.5", "192.168.40"])
    ip, pc = f"{net}.{rng.randint(60, 180)}", f"PC-{rng.choice(['BUH', 'SALES', 'HR', 'LOG'])}-{rng.randint(1, 30):02d}"
    prn = rng.choice(["PRN-2ETAZH", "MFU-BUH", "PRN-SKLAD", "MFU-PRIEM"])
    mac_pc, mac_prn, m = _mac(rng), _mac(rng), rng.randint(10, 40)
    lines = [
        _log(f"08:{m:02d}:02", "dhcp01", "INFO", f"scope {net}.0/24: range {net}.50–{net}.200, exclusions: none, reservations: 0"),
        _log(f"08:{m:02d}:14", "dhcp01", "INFO", f"DHCPACK {ip} to {mac_pc} ({pc}), lease 8h"),
        _log(f"08:{m + 1:02d}:40", pc, "ERROR", f"Tcpip 4199: обнаружен конфликт IP-адреса {ip} с системой, имеющей адрес {mac_prn}"),
        _log(f"08:{m + 3:02d}:05", "print01", "WARN", f"PrintService: порт {ip} принтера {prn} не отвечает, задание отложено"),
        _log(f"08:{m + 4:02d}:21", "inventory", "INFO", f"{prn}: MAC {mac_prn}, адрес задан вручную в веб-интерфейсе"),
    ]
    opts, key = _choice(rng, rng.choice(["Принтеру вручную задан адрес из пула DHCP: исключить адрес из пула или сделать резервирование",
                                         f"У {prn} статический адрес из пула DHCP: исключить его из пула или зарезервировать за MAC принтера, а принтер перевести на DHCP"]), [
        "Сервер DHCP выдаёт один адрес двум устройствам: пересоздать область и перезапустить службу DHCP на dhcp01",
        f"Сбоит порт принтера: заменить патч-корд и перенести {prn} на другой порт",
        f"Драйвер принтера на {pc} перехватывает его адрес: переустановить драйвер",
    ])
    return {"scene_title": "То печатает, то нет", "story": f"С утра {prn} то печатает, то нет, а у сотрудника за {pc} то и дело пропадает сеть.",
            "prompt": "В чём причина и как исправить?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("adm_inc_skew", SPEC, "Диагностика инцидентов", "choice", 2.3, 1.0)
def _(rng):
    dom, dc, other = rng.choice(DOMAINS), rng.choice(["dc01", "dc02"]), rng.choice(["fs01", "srv-files", "fs-main"])
    drift, m, pc = rng.randint(7, 25), rng.randint(10, 40), f"PC-{rng.choice(['BUH', 'SALES', 'HR'])}-{rng.randint(1, 30):02d}"
    src = rng.choice(["Local CMOS Clock", "VM IC Time Synchronization Provider"])
    lines = [
        _log(f"08:{m:02d}:03", pc, "ERROR", f"Security-Kerberos 4: получена ошибка KRB_AP_ERR_SKEW от сервера {other}.{dom}"),
        _log(f"08:{m:02d}:05", pc, "WARN", "Winlogon: не удаётся подключить сетевые диски H: и S:"),
        _log(f"08:{m:02d}:31", dc, "WARN", f"Time-Service 36: служба времени не синхронизировалась {rng.randint(30, 90)} ч"),
        _log(f"08:{m + 1:02d}:10", "admin", "INFO", f"w32tm /query /source на {dc} (PDC-эмулятор): {src}"),
        _log(f"08:{m + 1:02d}:12", "admin", "INFO", f"w32tm /stripchart {dc} → ntp.example: смещение +00:{drift:02d}:{rng.randint(0, 59):02d}"),
    ]
    opts, key = _choice(rng, f"Часы {dc} ушли более чем на 5 мин, Kerberos отвергает билеты: настроить NTP на PDC-эмуляторе", [
        "Истёк срок действия паролей у сотрудников: принудительно сбросить пароли и попросить всех войти заново",
        f"Нарушена репликация между контроллерами домена: выполнить repadmin /syncall /AdeP и перезагрузить {dc}",
        "Учётки заблокированы после неверных попыток входа: разблокировать их в ADUC",
    ])
    return {"scene_title": "Не пускает в сеть", "story": f"С утра часть сотрудников входит в Windows, но не видит сетевых дисков и получает «Отказано в доступе» к {other}.",
            "prompt": "Что происходит и как исправить?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("adm_inc_monday", SPEC, "Диагностика инцидентов", "choice", 2.3, 2.0)
def _(rng):
    srv, grow, end = rng.choice(["fs01", "srv-files", "fs-main"]), rng.randint(30, 60), rng.choice([6, 7])
    x = ["Вс 22:00"] + [f"Пн {h:02d}:00" for h in range(0, 15, 2)]
    bak = [rng.randint(85, 120) if i <= end else 0 for i in range(9)]
    lat = [rng.randint(15, 30) if i < 5 else (rng.randint(120, 180) if i <= end else rng.randint(5, 12)) for i in range(9)]
    panel = {"type": "chart", "x": x, "marker": {"i": 5, "label": "начало рабочего дня"}, "series": [
        {"name": f"задержка дисков {srv}, мс", "axis": "left", "max": 200, "data": lat},
        {"name": "поток задания резервного копирования, МБ/с", "axis": "right", "max": 150, "data": bak},
    ]}
    opts, key = _choice(rng, "Полная копия выходного дня перестала укладываться в ночное окно и теперь идёт в рабочие часы", [
        f"Утром все одновременно входят в систему, и {srv} не справляется с наплывом: нужен второй файловый сервер",
        "Антивирус по понедельникам сканирует общие папки: перенести проверку на ночь",
        f"Диски {srv} изношены и деградируют под нагрузкой: заменить их по одному с ребилдом массива",
    ])
    return {"scene_title": "Тяжёлый понедельник", "story": f"Каждый понедельник до обеда файловый сервер {srv} «тормозит», потом всё проходит. Месяц назад такого не было, "
                                                           f"а объём общих папок с тех пор вырос на {grow} %.",
            "prompt": "Что вероятнее всего?", "panel": panel, "options": opts, "key": key}


@family("adm_inc_stale_dc", SPEC, "Диагностика инцидентов", "choice", 2.3, 2.5)
def _(rng):
    dom, net = rng.choice(DOMAINS), rng.choice(["10.0.0", "10.10.1", "192.168.100", "172.20.0"])
    names = ["dc01", "dc02", rng.choice(["dc03", "dc-old", "dc2012"])]
    ips = [f"{net}.{n}" for n in rng.sample(range(5, 40), 3)]
    dead = 2
    lines = [f"PS> nslookup {dom}", f"Имя:       {dom}", f"Addresses: {ips[0]}", f"           {ips[1]}", f"           {ips[2]}",
             "PS> Get-ADDomainController -Filter * | Select Name, IPv4Address"] + [f"{n:<8}{ip}" for n, ip in zip(names, ips)] + [
             f"PS> Test-Connection {ips[dead]} -Count 1", "Test-Connection: превышен интервал ожидания для запроса",
             "PS> Get-WinEvent GroupPolicy | Select -First 1", "1129: обработка групповой политики не удалась из-за отсутствия связи с контроллером домена"]
    opts, key = _choice(rng, f"{names[dead]} выключили без понижения: провести очистку метаданных и удалить его A/SRV-записи из DNS", [
        "Клиенты закэшировали старый контроллер: выполнить на всех ПК ipconfig /flushdns",
        f"Двум оставшимся контроллерам не хватает мощности: вернуть {names[dead]} в работу или поднять новый третий",
        f"Сломана репликация SYSVOL между {names[0]} и {names[1]}: перезапустить DFSR и выполнить авторитетное восстановление",
    ])
    return {"scene_title": "Долгий вход", "story": f"Месяц назад старый сервер {names[dead]} просто выключили и списали. С тех пор у части сотрудников вход длится "
                                                   f"по {rng.randint(2, 4)} минуты, а групповые политики применяются через раз.",
            "prompt": "В чём причина и что сделать?", "panel": {"type": "code", "lang": "powershell", "lines": lines}, "options": opts, "key": key}


# ============================== Сети ==============================


@family("adm_net_trunk", SPEC, "Сети", "mark", 2.2, -1.0)
def _(rng):
    corp, voice, guest = rng.choice([10, 100]), rng.choice([20, 40]), rng.choice([30, 50, 99])
    port, floor = rng.randint(5, 20), rng.randint(2, 6)
    lines = [f"hostname sw-floor{floor}", "!", f"vlan {corp}", " name CORP", f"vlan {voice}", " name VOICE", f"vlan {guest}", " name GUEST", "!"]
    if rng.random() < 0.5:
        lines += [f"interface GigabitEthernet1/0/{port - 1}", " description PC-reception", " switchport mode access", f" switchport access vlan {corp}",
                  f" switchport voice vlan {voice}", "!"]
    lines += [f"interface GigabitEthernet1/0/{port}", f" description AP-meeting-{floor}{rng.randint(1, 9):02d}", " switchport mode trunk",
              f" switchport trunk native vlan {corp}", f" switchport trunk allowed vlan {min(corp, voice)},{max(corp, voice)}"]
    key = len(lines)
    lines += [" spanning-tree portfast trunk", "!"]
    return {"scene_title": "Гостевой Wi-Fi", "story": f"В переговорной на {floor}-м этаже повесили новую точку доступа. Корпоративная сеть Wi-Fi работает, "
                                                      f"а гости в сети «Guest» (VLAN {guest}) не получают адрес.",
            "prompt": "Нажмите на строку с ошибкой.", "panel": {"type": "code", "lang": "text", "lines": lines}, "key": key}


@family("adm_net_vpn_overlap", SPEC, "Сети", "choice", 2.3, 0.5)
def _(rng):
    net = rng.choice(["192.168.0", "192.168.1", "192.168.88"])
    fs, home, v = rng.choice(["fs01", "srv-files", "srv-1c"]), rng.randint(100, 200), rng.randint(10, 250)
    srv = f"{net}.{rng.randint(10, 40)}"
    lines = [f"Wi-Fi:  IPv4 {net}.{home}/24, шлюз {net}.1", f"VPN:    IPv4 10.8.0.{v}/24", "", "PS> route print -4  (фрагмент)",
             f"{net}.0    255.255.255.0    On-link     {net}.{home}   метрика 25",
             f"{net}.0    255.255.255.0    10.8.0.1    10.8.0.{v}     метрика 35", "10.8.0.0      255.255.255.0    On-link     10.8.0." + str(v) + "     метрика 35",
             "", f"PS> Test-NetConnection {srv} -Port 445", "TcpTestSucceeded : False"]
    opts, key = _choice(rng, f"Домашняя сеть совпадает с офисной: трафик к {srv} уходит в домашний Wi-Fi, а не в туннель", [
        "VPN-шлюз не пропускает SMB: открыть порт 445 на межсетевом экране для всего пула адресов 10.8.0.0/24",
        "Домашний провайдер блокирует порт 445: перевести общий доступ к файлам на нестандартный порт",
        f"Сотруднику не выданы права на общую папку: добавить его в группу с доступом к ресурсам {fs}",
    ])
    return {"scene_title": "Из дома не видно", "story": f"Сотрудник работает из дома через VPN. Почта и портал открываются, а файловый сервер {fs} ({srv}) недоступен. "
                                                        "У коллег на том же VPN всё работает.",
            "prompt": "В чём причина?", "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}


@family("adm_net_loop", SPEC, "Сети", "choice", 2.3, 1.9)
def _(rng):
    floor, vlan, m = rng.randint(2, 6), rng.choice([10, 20, 100]), rng.randint(10, 40)
    a, b = rng.sample(range(5, 24), 2)
    sw = f"sw-floor{floor}"
    lines = [_log(f"10:{m:02d}:02", sw, "INFO", f"%LINK-3-UPDOWN: Interface Gi1/0/{b} (meeting-{floor}02), changed state to up")]
    for i in range(3):
        lines.append(_log(f"10:{m:02d}:{5 + 4 * i:02d}", sw, "WARN",
                          f"%SW_MATM-4-MACFLAP_NOTIF: Host {_mac(rng)} in vlan {vlan} is flapping between port Gi1/0/{a} and port Gi1/0/{b}"))
    lines += [_log(f"10:{m:02d}:20", sw, "WARN", "CPU utilization 98 %, broadcast input 41 000 pps on Gi1/0/49 (uplink)"),
              _log(f"10:{m + 1:02d}:03", "helpdesk", "INFO", f"обращений с {floor}-го этажа за 5 минут: {rng.randint(6, 14)} — «сеть пропадает каждые несколько секунд»")]
    opts, key = _choice(rng, f"Петля через Gi1/0/{a} и Gi1/0/{b}: отключить порт, затем включить BPDU Guard на портах доступа", [
        "Кто-то в сети запустил ARP-спуфинг: заблокировать на коммутаторе MAC-адреса, которые «прыгают» между портами",
        f"Сбоит аплинк коммутатора {sw}: заменить SFP-модуль и патч-корд до ядра сети",
        f"Исчерпан пул DHCP в VLAN {vlan}: расширить область и сократить срок аренды",
    ])
    return {"scene_title": "Сеть мигает", "story": f"В 10 утра на {floor}-м этаже сеть начала пропадать у всех сразу. Утром в переговорную занесли настольный коммутатор для презентации.",
            "prompt": "Что произошло и что делать?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("adm_net_snooping", SPEC, "Сети", "choice", 2.4, 2.5)
def _(rng):
    acc, chg, vl = f"sw-acc-{rng.randint(1, 8)}", rng.randint(100, 999), rng.choice(["10-40", "10-60", "20-50"])
    srv, core, m = rng.choice(["dhcp01", "dc01", "srv-infra"]), _mac(rng), rng.randint(10, 40)
    ip = f"10.{rng.choice([10, 20, 30])}.{rng.randint(0, 3)}.{rng.randint(20, 200)}"
    pc = _mac(rng)
    lines = [
        _log("Пт 18:42:10", acc, "INFO", f"CHG-{chg}: ip dhcp snooping; ip dhcp snooping vlan {vl}"),
        _log("Пт 18:43:02", acc, "INFO", f"interface Gi1/0/48: description uplink-core, neighbor MAC {core}"),
        _log(f"Пн 08:{m:02d}:01", srv, "INFO", f"DHCPDISCOVER from {pc} via relay; DHCPOFFER {ip}"),
        _log(f"Пн 08:{m:02d}:05", acc, "INFO", f"%DHCP_SNOOPING-5-DHCP_SNOOPING_UNTRUSTED_PORT: drop message on untrusted port Gi1/0/48, message type: DHCPOFFER, MAC sa: {core}"),
        _log(f"Пн 08:{m:02d}:09", srv, "INFO", f"DHCPDISCOVER from {pc} via relay; DHCPOFFER {ip}"),
        _log(f"Пн 08:{m + 7:02d}:00", "helpdesk", "INFO", f"{rng.randint(15, 40)} обращений «нет сети»: в основном стационарные ПК, ноутбуки с прошлой недели работают"),
    ]
    opts, key = _choice(rng, "Аплинк Gi1/0/48 не помечен доверенным: snooping режет ответы сервера — нужен ip dhcp snooping trust", [
        "В сети появился чужой DHCP-сервер, и snooping правильно режет его ответы: найти устройство за портом Gi1/0/48",
        f"Пул на {srv} исчерпан: сервер предлагает адреса, но не может их закрепить — расширить область",
        "У всех клиентов аренда истекла одновременно, и сервер не справляется с потоком запросов: увеличить срок аренды",
    ])
    return {"scene_title": "Нет адреса", "story": "В пятницу вечером на коммутаторах доступа включили защиту от чужих DHCP-серверов. В понедельник утром "
                                                  "компьютеры массово не получают адрес.",
            "prompt": "В чём причина?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# ============================== Учётные записи и доступ ==============================

DEPS = [("Buh", "Бухгалтерия", "зарплатными ведомостями"), ("HR", "Кадры", "личными делами сотрудников"), ("Legal", "Юристы", "договорами с контрагентами"),
        ("Fin", "Финансы", "бюджетом на следующий год")]


@family("adm_acc_ntfs", SPEC, "Учётные записи и доступ", "mark", 2.2, -1.1)
def _(rng):
    code, dep, secret = rng.choice(DEPS)
    dom = rng.choice(["CORP", "OFFICE", "SEVERVET"])
    path = f"D:\\Shares\\{code}"
    bad = rng.choice([f"{dom}\\Domain Users:(OI)(CI)(RX)", "Everyone:(OI)(CI)(M)", "NT AUTHORITY\\Authenticated Users:(OI)(CI)(RX)", "BUILTIN\\Users:(OI)(CI)(RX)"])
    aces = ["BUILTIN\\Administrators:(OI)(CI)(F)", f"{dom}\\GG_{code}_RW:(OI)(CI)(M)", f"{dom}\\GG_{code}_RO:(OI)(CI)(RX)", bad]
    if rng.random() < 0.5:
        aces.append(f"{dom}\\GG_IT_Admins:(OI)(CI)(F)")
    rng.shuffle(aces)
    pad = " " * (len(path) + 1)
    lines = [f"PS> icacls {path}", f"{path} NT AUTHORITY\\SYSTEM:(OI)(CI)(F)"] + [pad + a for a in aces] + [pad + "CREATOR OWNER:(OI)(CI)(IO)(F)", "",
                                                                                                         "Успешно обработано 1 файлов; не удалось обработать 0 файлов"]
    key = lines.index(pad + bad) + 1
    return {"scene_title": "Папка для всех", "story": f"Аудит: папку «{dep}» с {secret} может открыть любой сотрудник компании. Права выдавались группам GG_{code}_RW и GG_{code}_RO.",
            "prompt": "Нажмите на строку, из-за которой папка открыта всем.", "panel": {"type": "code", "lang": "powershell", "lines": lines}, "key": key}


LEVELS = ["Нет доступа", "Чтение", "Изменение", "Полный доступ"]


@family("adm_acc_share_ntfs", SPEC, "Учётные записи и доступ", "choice", 2.2, 0.4)
def _(rng):
    (code, dep, _), (other, _, _) = rng.sample(DEPS, 2)
    srv, login = rng.choice(["fs01", "srv-files", "fs-main"]), rng.choice(["a.morozova", "k.sokolov", "e.belova", "d.orlov", "n.zaitseva"])
    eff = rng.choice([0, 1, 2])
    # итог — минимум из прав общего ресурса и NTFS; 0 — ни одна группа сотрудника не указана в NTFS
    share, groups = rng.choice({0: [(2, [f"GG_{other}_RW"]), (3, [f"GG_{other}_RO", f"GG_{other}_RW"])],
                                1: [(1, [f"GG_{code}_RO", f"GG_{code}_RW"]), (3, [f"GG_{code}_RO"]), (2, [f"GG_{code}_RO"])],
                                2: [(2, [f"GG_{code}_RO", f"GG_{code}_RW"]), (3, [f"GG_{code}_RW"])]}[eff])
    lines = [f"Общий ресурс \\\\{srv}\\{code}", f"  Разрешения общего ресурса: Everyone — {LEVELS[share]}", f"Разрешения NTFS на D:\\Shares\\{code}:",
             f"  CORP\\GG_{code}_RO — Чтение и выполнение", f"  CORP\\GG_{code}_RW — Изменение", "  BUILTIN\\Administrators — Полный доступ",
             f"Учётная запись {login}: группы {', '.join(groups)}"]
    texts = {0: "Нет доступа: папка не откроется", 1: "Чтение: открыть и скопировать файлы", 2: "Изменение: править и удалять файлы",
             3: "Полный доступ, включая смену прав"}
    opts, key = _choice(rng, texts[eff], [t for lv, t in texts.items() if lv != eff])
    return {"scene_title": "Права через сеть", "story": f"Сотрудник открывает папку отдела «{dep}» по сети: \\\\{srv}\\{code}.",
            "prompt": f"Какой доступ к файлам по сети получит {login}?", "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}


@family("adm_acc_gpo", SPEC, "Учётные записи и доступ", "choice", 2.3, 1.8)
def _(rng):
    dom, (code, dep, _) = rng.choice(DOMAINS), rng.choice(DEPS)
    x, y, z = rng.sample([5, 10, 15, 20, 30], 3)
    enf, blk = rng.random() < 0.5, rng.random() < 0.5
    pc = f"PC-{code.upper()}-{rng.randint(1, 30):02d}"
    lines = ["Параметр: Конфигурация компьютера → Параметры безопасности → «Интерактивный вход в систему: предел простоя компьютера»",
             f"{dom} (домен)", f"  └ GPO «Default Security» [Принудительный: {'да' if enf else 'нет'}] — {x * 60} с", "  OU Компьютеры",
             f"    └ OU {dep} [Блокировка наследования: {'да' if blk else 'нет'}]", f"        └ GPO «{dep}: простой» — {y * 60} с",
             f"Локальная политика {pc}: {z * 60} с", f"Компьютер {pc} находится в OU {dep}"]
    right = (f"{x} мин: принудительная доменная политика побеждает, даже если наследование заблокировано" if enf
             else f"{y} мин: политика, привязанная к OU компьютера, применяется последней и побеждает")
    opts, key = _choice(rng, right, [
        f"{y} мин: политика, привязанная к OU компьютера, применяется последней и побеждает" if enf
        else f"{x} мин: принудительная доменная политика побеждает, даже если наследование заблокировано",
        f"{z} мин: при конфликте доменных политик остаётся локальная настройка компьютера",
        "Ни одна: при конфликте значений из разных объектов политики параметр не задаётся",
    ])
    return {"scene_title": "Чья политика", "story": f"Служба безопасности спрашивает, через сколько минут простоя {pc} заблокирует сеанс (Interactive logon: Machine inactivity limit). Структура политик — на панели.",
            "prompt": "Какое значение применится?", "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}


@family("adm_acc_adminsd", SPEC, "Учётные записи и доступ", "choice", 2.3, 2.6)
def _(rng):
    login, dom = rng.choice(["s.volkov", "o.lebedeva", "p.kuznetsov", "t.egorova"]), rng.choice(["corp", "office", "hq"])
    grp, ago = rng.choice(["Account Operators", "Backup Operators", "Domain Admins", "Server Operators"]), rng.randint(6, 18)
    lines = [f"PS> Get-ADUser {login} -Properties adminCount, memberOf | Select adminCount, memberOf",
             "adminCount : 1", f"memberOf   : {{CN=GG_Sales,OU=Группы,DC={dom},DC=local}}",
             f"PS> (Get-Acl \"AD:CN={login},OU=Сотрудники,DC={dom},DC=local\").AreAccessRulesProtected", "True",
             f"PS> Get-ADReplicationAttributeMetadata (Get-ADUser {login}) -Server dc01 -Properties nTSecurityDescriptor | Select LastOriginatingChangeTime",
             f"LastOriginatingChangeTime : сегодня 10:{rng.randint(0, 59):02d}  (ручная правка прав — сегодня 09:{rng.randint(0, 59):02d})",
             f"# {ago} мес. назад {login} на время отпуска коллеги добавляли в «{grp}»"]
    opts, key = _choice(rng, "Учётка была в защищённой группе: SDProp раз в час возвращает ей права по шаблону AdminSDHolder, сбросить adminCount", [
        "Делегирование применилось не ко всем вложенным OU: заново запустить мастер делегирования управления на OU «Сотрудники»",
        "Права перезатирает репликация со старого контроллера: найти DC с устаревшей копией и выполнить принудительную репликацию",
        "Политика «Группы с ограниченным доступом» при обновлении возвращает права к исходным",
    ])
    return {"scene_title": "Права откатываются", "story": f"Поддержке делегировали сброс паролей в OU «Сотрудники». У всех работает, а у {login} — «Отказано в доступе». "
                                                           "Права на его учётку добавили вручную, через час они пропали снова.",
            "prompt": "В чём причина?", "panel": {"type": "code", "lang": "powershell", "lines": lines}, "options": opts, "key": key}


# ============================== Резервное копирование ==============================


@family("adm_bak_mirror", SPEC, "Резервное копирование", "mark", 2.2, -1.2)
def _(rng):
    srv, share = rng.choice(["fs01", "srv-files", "fs-main"]), rng.choice(["share", "public", "depts"])
    folder = rng.choice(["Договоры 2026", "Отчёты Q3", "Сметы", "Прайсы поставщиков"])
    lines = ["#!/bin/bash", f"# ночной бэкап общих папок {srv} на NAS, cron: 0 2 * * *", "set -euo pipefail", f"SRC=/srv/{share}/",
             f"DST=/mnt/nas/backup/{share}/", f"LOG=/var/log/backup-{share}.log"]
    if rng.random() < 0.5:
        lines.append("mountpoint -q /mnt/nas || mount /mnt/nas")
    lines.append(f'rsync -a{rng.choice(["", "v", "h"])} --delete "$SRC" "$DST" >> "$LOG" 2>&1')
    key = len(lines)
    if rng.random() < 0.5:
        lines.append('find /var/log -name "backup-*.log" -mtime +30 -delete')
    lines.append('echo "$(date \'+%F %T\') ok" >> "$LOG"')
    return {"scene_title": "Пустой бэкап", "story": f"В пятницу сотрудник случайно удалил папку «{folder}» на {srv}. В понедельник её нет и в бэкапе на NAS, "
                                                    "хотя скрипт каждую ночь отрабатывает без ошибок.",
            "prompt": "Нажмите на строку, из-за которой бэкап не защищает от удаления.", "panel": {"type": "code", "lang": "bash", "lines": lines}, "key": key}


DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт"]


@family("adm_bak_chain", SPEC, "Резервное копирование", "choice", 2.2, 0.6)
def _(rng):
    srv, inc = rng.choice(["fs01", "srv-1c", "srv-files"]), rng.random() < 0.5
    t = rng.randint(2, 4)
    full = rng.randint(400, 900)
    sizes, acc = [], 0
    for _ in DAYS:
        d = rng.randint(6, 20)
        acc += d
        sizes.append(d if inc else acc)
    kind = "инкрементная" if inc else "разностная"
    lines = [f"Задание «{srv}», хранилище nas01", f"Вс 23:00  полная        {full} ГБ"] + [f"{d} 23:00  {kind:<13} {s} ГБ" for d, s in zip(DAYS, sizes)]
    a = f"Полную за Вс и все копии с Пн по {DAYS[t]} по порядку"
    b = f"Полную за Вс и только копию за {DAYS[t]}"
    opts, key = _choice(rng, a if inc else b, [b if inc else a, f"Только копию за {DAYS[t]}: в ней уже есть все файлы на этот день",
                                               f"Полную за Вс и копию за {DAYS[t - 1]}, остальное — из корзины пользователей"])
    return {"scene_title": "Цепочка копий", "story": f"Нужно восстановить {srv} на состояние вечера {DAYS[t]}. В хранилище — цепочка копий за неделю.",
            "prompt": "Какие копии понадобятся?", "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}


@family("adm_bak_ransom", SPEC, "Резервное копирование", "choice", 2.3, 2.0)
def _(rng):
    srv, full, keep = rng.choice(["fs01", "srv-files", "fs-main"]), rng.choice([1200, 1500, 1800]), rng.choice([7, 10])
    d0, k = rng.randint(1, 15), rng.choice([7, 8])
    x = [f"{d0 + i:02d}.10" for i in range(10)]
    inc = [rng.randint(4, 9) if i < k else rng.randint(280, 450) for i in range(10)]
    files = [round(rng.uniform(1.5, 4.0), 1) if i < k else round(rng.uniform(140, 190), 1) for i in range(10)]
    panel = {"type": "chart", "x": x, "marker": {"i": k, "label": "резкий рост"}, "series": [
        {"name": "инкрементная копия, ГБ", "axis": "left", "max": 500, "data": inc},
        {"name": "изменённых файлов, тыс.", "axis": "right", "max": 200, "data": files},
    ]}
    opts, key = _choice(rng, "Массово изменились файлы: проверить сервер на шифровальщика и остановить ротацию, пока чистые копии не вытеснены", [
        f"Сбилась цепочка, и задание стало делать полные копии: пересоздать задание и начать новую цепочку с полной копии {srv}",
        "Сотрудники загрузили много новых файлов: расширить хранилище копий и увеличить срок хранения",
        "Сломалась дедупликация хранилища: запустить её задание вручную и дождаться, пока копии сожмутся",
    ])
    return {"scene_title": "Распухшие копии", "story": f"Ночные инкрементные копии {srv} обычно весят 4–9 ГБ, полная — около {full} ГБ. Последние ночи копии "
                                                       f"резко выросли. Хранятся последние {keep} копий, старые удаляются автоматически.",
            "prompt": "Что делать?", "panel": panel, "options": opts, "key": key}


def _num(v: float) -> str:
    return f"{v:g}".replace(".", ",")


@family("adm_bak_rto", SPEC, "Резервное копирование", "choice", 2.3, 2.7)
def _(rng):
    srv, rto = rng.choice(["fs01", "srv-files", "srv-1c"]), rng.choice([4, 6])
    size, mbit = rng.choice([(1.5, 200), (2, 200), (2, 500), (3, 500), (4, 1000), (3, 300)])
    h = size * 8e6 / mbit / 3600  # ТБ → Мбит → ч; при любом наборе — от 8,9 ч, то есть больше RTO
    nightly = rng.random() < 0.5
    lines = [f"План восстановления {srv}", f"RTO: {rto} ч, RPO: 24 ч", f"Объём данных {srv}: {_num(size)} ТБ",
             "Копия 1: NAS в серверной, каждую ночь, хранение 14 дней (SMB-ресурс, доменная учётка)",
             f"Копия 2: облачное хранилище, {'каждую ночь' if nightly else 'каждое воскресенье'}, хранение 8 недель", f"Канал офиса в интернет: {mbit} Мбит/с"]
    rto_ok, rto_bad = f"RTO — да: скачается примерно за {_num(round(h / 8, 1))} ч", f"RTO — нет: скачивание займёт около {h:.0f} ч"
    if nightly:
        rpo_ok, rpo_bad = "RPO — да: копия ночная, потеряем не больше суток", f"RPO — нет: за {h:.0f} ч простоя потеряем больше суток"
    else:
        rpo_ok, rpo_bad = "RPO — да: в облаке 8 недель копий, данные целы", "RPO — нет: копия недельная, потеряем до 7 дней"
    rpo_right, rpo_wrong = (rpo_ok, rpo_bad) if nightly else (rpo_bad, rpo_ok)
    opts, key = _choice(rng, f"{rto_bad}; {rpo_right}", [f"{rto_ok}; {rpo_right}", f"{rto_bad}; {rpo_wrong}", f"{rto_ok}; {rpo_wrong}"])
    return {"scene_title": "Осталось облако", "story": f"Шифровальщик зашифровал {srv}, а заодно и NAS с копиями: тот был подключён по SMB под доменной учёткой. "
                                                       "Цела только облачная копия. Директор спрашивает, уложитесь ли в план.",
            "prompt": "Что ответить директору по RTO и RPO из плана?", "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}


# ============================== Серверы и ОС ==============================

MOUNTS = [("/srv", "/srv/1c/bases/ut11"), ("/var/lib/pgsql", "/var/lib/pgsql/16/data/base"), ("/opt/backup", "/opt/backup/daily"),
          ("/home", "/home/share/scan")]


@family("adm_srv_df", SPEC, "Серверы и ОС", "mark", 2.1, -1.3)
def _(rng):
    host, (mnt, path) = rng.choice(["srv-1c", "db01", "srv-app", "fs-linux"]), rng.choice(MOUNTS)
    lv = mnt.strip("/").replace("/", "_")
    size = rng.choice([100, 200, 500])
    rows = [("/dev/mapper/vg0-root", "20G", f"{rng.randint(5, 9)}.{rng.randint(0, 9)}G", f"{rng.randint(80, 91)}%", "/"),
            ("/dev/sda1", "976M", "941M", f"{rng.randint(96, 98)}%", "/boot"),
            ("/dev/mapper/vg0-var", "30G", f"{rng.randint(8, 14)}G", f"{rng.randint(30, 50)}%", "/var"),
            (f"/dev/mapper/vg0-{lv}", f"{size}G", f"{size}G", "100%", mnt),
            ("tmpfs", "3.9G", "0", "0%", "/dev/shm")]
    head, tail = rows[:1], rows[1:]
    rng.shuffle(tail)
    lines = ["$ df -h", f"{'Filesystem':<28}{'Size':>6}{'Used':>6}{'Use%':>6}  Mounted on"] + [f"{fs:<28}{s:>6}{u:>6}{p:>6}  {m}" for fs, s, u, p, m in head + tail]
    key = next(i for i, ln in enumerate(lines, 1) if ln.endswith(f"  {mnt}"))
    return {"scene_title": "Нет места", "story": f"На сервере {host} служба перестала сохранять данные: «No space left on device» при записи в {path}.",
            "prompt": "Нажмите на строку файловой системы, где кончилось место.", "panel": {"type": "code", "lang": "bash", "lines": lines}, "key": key}


@family("adm_srv_deleted", SPEC, "Серверы и ОС", "choice", 2.2, 0.8)
def _(rng):
    host, app = rng.choice(["srv-app", "srv-1c", "web01"]), rng.choice(["nginx", "tomcat", "rabbitmq", "srv1cv8"])
    total = rng.choice([40, 50, 80])
    big = total - rng.randint(10, 18)
    lines = [f"$ sudo du -sh /var/log/{app}/*.log", f"{big}G   /var/log/{app}/{app}.log", f"$ sudo rm /var/log/{app}/{app}.log", "$ df -h /var",
             f"/dev/mapper/vg0-var  {total}G  {total}G  0  100% /var", "$ sudo du -sh /var", f"{total - big}G  /var"]
    opts, key = _choice(rng, rng.choice([f"Файл удалён, но {app} держит его открытым: место вернётся после перезапуска службы",
                                         f"{app} держит удалённый файл открытым: перезапустить службу или усечь файл через /proc/<pid>/fd, место вернётся сразу"]), [
        "Файловой системе нужно время: место освобождается фоновым процессом за несколько часов",
        "На разделе закончились иноды: удалить мелкие файлы во /var/spool и /var/tmp",
        "Удалённый файл попал в корзину root: очистить ~/.local/share/Trash и повторить df",
    ])
    return {"scene_title": "Место не вернулось", "story": f"На {host} кончилось место во /var. Вы удалили огромный лог {app}, но df всё ещё показывает 100 %.",
            "prompt": "Почему место не освободилось?", "panel": {"type": "code", "lang": "bash", "lines": lines}, "options": opts, "key": key}


@family("adm_srv_raid", SPEC, "Серверы и ОС", "choice", 2.3, 2.1)
def _(rng):
    host, size, hrs, days = rng.choice(["srv-1c", "fs01", "db01"]), rng.choice([4, 8, 12]), rng.choice([18, 24, 36]), rng.randint(5, 12)
    failed, weak = rng.sample(["sda", "sdb", "sdc", "sdd"], 2)
    m, pend = rng.randint(10, 40), rng.randint(24, 180)
    lines = [
        _log(f"07:{m:02d}:12", "kernel", "ERROR", f"md/raid:md0: Disk failure on {failed}1, disabling device. Operation continuing on 3 devices"),
        _log(f"07:{m:02d}:13", "mdadm", "WARN", "DegradedArray event detected on md device /dev/md0 (raid5, 4 devices)"),
        _log(f"07:{m + 2:02d}:40", "smartd", "WARN", f"Device /dev/{weak} [SAT]: {pend} Currently unreadable (pending) sectors"),
        _log(f"07:{m + 2:02d}:41", "smartd", "WARN", f"Device /dev/{weak} [SAT]: SMART Usage Attribute: 5 Reallocated_Sector_Ct changed from 100 to 97"),
        _log(f"07:{m + 3:02d}:05", "backup", "INFO", f"последнее успешное задание {host}: {days} дн. назад"),
    ]
    opts, key = _choice(rng, f"Пока массив жив, снять свежую копию данных: при ребилде нечитаемые сектора {weak} могут погубить массив", [
        "Срочного ничего нет: RAID 5 переживает отказ одного диска — дождаться замены и запустить ребилд",
        f"Сначала заменить {weak} с ошибками на запасной диск, а {failed} — когда привезут: два ребилда подряд безопаснее",
        "Запустить fsck на /dev/md0, чтобы найти и исправить повреждённые сектора до ребилда",
    ])
    return {"scene_title": "Вылетел диск", "story": f"На {host} в RAID 5 из четырёх дисков по {size} ТБ вылетел диск. Замену привезут через {hrs} ч.",
            "prompt": "Что сделать прямо сейчас?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# ============================== Работа с обращениями ==============================

LOW = [("генеральный директор", "второй монитор иногда мерцает, просит заменить"), ("бухгалтер", "нужна новая мышь, колёсико заедает"),
       ("менеджер отдела продаж", "установить на ноутбук программу для видеозвонков"), ("новый сотрудник", "добавить в почтовую рассылку отдела"),
       ("юрист", "поменять фон рабочего стола на корпоративный"), ("секретарь", "заказать картридж впрок, текущий заканчивается через неделю")]
HIGH = [("касса магазина №{k}", "не пробиваются чеки, у кассы очередь покупателей"), ("отдел продаж ({k} чел.)", "ни у кого не открывается CRM"),
        ("склад", "не печатаются накладные, {k} машин ждут отгрузки")]


@family("adm_tkt_queue", SPEC, "Работа с обращениями", "mark", 2.1, -1.0)
def _(rng):
    k = rng.randint(3, 12)
    who, what = rng.choice(HIGH)
    tickets = [(who.format(k=k), what.format(k=k), True)] + [(w, t, False) for w, t in rng.sample(LOW, rng.randint(3, 4))]
    rng.shuffle(tickets)
    times = sorted(f"08:{rng.randint(0, 19):02d}" for _ in tickets)
    lines = ["№ | создано | от кого | суть"]
    key = 0
    for i, ((w, t, hot), tm) in enumerate(zip(tickets, times)):
        lines.append(f"INC-{rng.randint(1000, 9999)} | {tm} | {w} | {t}")
        if hot:
            key = i + 2
    return {"scene_title": "Очередь с утра", "story": "Понедельник, 08:20. В очереди первой линии несколько обращений, вы на смене один.",
            "prompt": "Нажмите на обращение, которое нужно взять первым.", "panel": {"type": "code", "lang": "text", "lines": lines}, "key": key}


WEEK = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def _add_work(day: int, minute: int, mins: int, workdays: int) -> tuple[int, int]:
    """Прибавить mins рабочих минут (09:00–18:00, рабочие дни — первые workdays дней недели)."""
    while True:
        if day % 7 < workdays and 540 <= minute < 1080:
            if mins <= 1080 - minute:
                return day, minute + mins
            mins -= 1080 - minute
        day, minute = day + 1, 540


def _fmt(day: int, minute: int) -> str:
    return f"{WEEK[day % 7]}, {minute // 60:02d}:{minute % 60:02d}"


@family("adm_tkt_sla", SPEC, "Работа с обращениями", "choice", 2.2, 0.5)
def _(rng):
    sla = {"P1": 4, "P2": 8, "P3": 16}
    while True:
        prio, day, minute = rng.choice(list(sla)), rng.choice([2, 3, 4]), rng.choice(range(14 * 60, 17 * 60 + 31, 30))
        mins = sla[prio] * 60
        right = _fmt(*_add_work(day, minute, mins, 5))
        cal = day * 1440 + minute + mins
        wrong = [_fmt(cal // 1440, cal % 1440), _fmt(*_add_work(day, minute, mins, 6)), _fmt(*_add_work(day + 1, 540, mins, 5))]
        if len({right, *wrong}) == 4:
            break
    topic = rng.choice(["не работает сканер в бухгалтерии", "не синхронизируется почта на телефоне", "ошибка при выгрузке отчёта из 1С"])
    lines = ["Регламент поддержки: рабочие часы Пн–Пт 09:00–18:00, срок SLA идёт только в рабочие часы",
             "P1 — реакция 15 мин, решение 4 ч", "P2 — реакция 30 мин, решение 8 ч", "P3 — реакция 2 ч, решение 16 ч", "",
             f"INC-{rng.randint(1000, 9999)}: приоритет {prio}, создано {_fmt(day, minute)}, «{topic}»"]
    opts, key = _choice(rng, right, wrong)
    return {"scene_title": "Срок по SLA", "story": "Руководитель поддержки просит проставить в обращении крайний срок решения.",
            "prompt": "Когда истекает срок решения по SLA?", "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}


@family("adm_tkt_mass", SPEC, "Работа с обращениями", "choice", 2.3, 1.8)
def _(rng):
    floor, other, m = rng.sample(range(2, 7), 2) + [rng.randint(5, 30)]
    sym = rng.sample(["не открывается 1С", "не печатает принтер", "долго грузится портал", "письма висят в исходящих", "отключается телефония"], 4)
    rooms = rng.sample(range(1, 30), 4)
    lines = [_log(f"09:{m + 4 * i:02d}", "helpdesk", "INFO", f"INC-{rng.randint(1000, 9999)} каб. {floor}{r:02d}: «{s}» — L1: перезагрузили ПК, решено")
             for i, (r, s) in enumerate(zip(rooms[:3], sym[:3]))]
    lines.insert(rng.randint(1, 3), _log(f"09:{m + 2:02d}", "helpdesk", "INFO", f"INC-{rng.randint(1000, 9999)} каб. {other}{rooms[3]:02d}: «забыл пароль» — L1: сброшен, решено"))
    lines.append(_log(f"09:{m + 13:02d}", "monitoring", "WARN", f"sw-floor{floor}: uplink Gi1/0/49 — {rng.randint(3, 9)} % пакетов с ошибками CRC"))
    lines.append(_log(f"09:{m + 15:02d}", "helpdesk", "INFO", f"каб. {floor}{rooms[0]:02d}: повторное обращение — «опять {sym[0]}»"))
    opts, key = _choice(rng, rng.choice([f"Это один сбой на {floor}-м этаже: связать обращения в массовый инцидент и проверить коммутатор этажа",
                                         f"Это один сбой на {floor}-м этаже: завести массовый инцидент, привязать к нему обращения, проверить sw-floor{floor} и оповестить этаж"]), [
        "Обращения разные и уже решены: разбирать их дальше по одному в порядке SLA",
        "Эскалировать каждое обращение на L3 отдельно: перезагрузки на L1 только маскируют настоящие причины сбоев",
        "Разослать всем сотрудникам инструкцию: перед обращением в поддержку перезагружать компьютер самостоятельно",
    ])
    return {"scene_title": "Перезагрузили — решено", "story": "За утро первая линия закрыла несколько разных обращений одной и той же перезагрузкой. Вы просматриваете журнал смены.",
            "prompt": "Что делать?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}
