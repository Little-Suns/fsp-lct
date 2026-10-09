"""SysAdmin / Support, сюжет «Понедельник в офисе»: офис на ~300 сотрудников — очередь обращений, сеть, серверы, бэкапы, учётки.
По одному простому семейству и по 3 сценарных на компетенцию плюс 4 сложных (Senior/Lead, b 2,4–2,9).
У каждого семейства три варианта механики (items._variant), правильные ответы других вариантов — среди дистракторов."""

from app.services.items import _log, _options, _variant, family, simple

SPEC = "SysAdmin / Support"
DOMAINS = ["corp.local", "office.lan", "ad.severvet.lan", "hq.local"]


def _mac(rng) -> str:
    return ":".join(f"{rng.randint(0, 255):02x}" for _ in range(6))


# ============================== простые ==============================

simple(SPEC, "Диагностика инцидентов", -1.2, "Интернет не работает", "Где искать причину?", [
    ("⟨who⟩ пишет: «не работает интернет». Сайты по имени не открываются, а ping ⟨ip⟩ по адресу проходит.",
     "В DNS: какой сервер имён получил компьютер и отвечает ли он"),
    ("⟨who⟩ пишет: «не работает интернет». ipconfig показывает адрес 169.254.⟨x⟩.⟨y⟩ и пустой шлюз, сеть — «Неопознанная сеть».",
     "В DHCP: почему компьютер не получил адрес от сервера"),
    ("⟨who⟩ пишет: «не работает интернет». На значке сети красный крестик: «Сетевой кабель не подключён». У соседа по столу всё работает.",
     "В подключении: кабель, сетевая розетка и порт коммутатора"),
], ["В браузере: сбросить его настройки и очистить кэш и cookie", "В антивирусе: отключить его и проверить, откроются ли сайты"],
    {"who": ["Бухгалтер", "Менеджер отдела продаж", "Секретарь приёмной"], "ip": ["77.88.8.8", "8.8.8.8", "1.1.1.1"], "x": [12, 87, 203], "y": [5, 44, 190]})
# v0 — до 510 устройств → /23, больше → /22; камеры: k + 2 ∈ (14, 30] → /27; гости: g + 2 ∈ (126, 254] → /24
simple(SPEC, "Сети", -0.5, "Новый VLAN", "Какую наименьшую подсеть выделить?", [
    ("Офис расширяется: в VLAN ⟨v⟩ нужно разместить до ⟨n⟩ устройств, адреса выдаются из 10.⟨v⟩.0.0.", "⟨r⟩"),
    ("Для видеонаблюдения заводят VLAN ⟨v⟩: ⟨k⟩ камер, видеорегистратор и шлюз.", "/27 — до 30 узлов"),
    ("Для гостевого Wi-Fi заводят VLAN ⟨v⟩: до ⟨g⟩ гостей одновременно, плюс шлюз и контроллер точек доступа.", "/24 — до 254 узлов"),
], ["/25 — до 126 узлов", "/28 — до 14 узлов"],
    lambda rng: (lambda n: {"v": rng.choice([20, 30, 40]), "n": n, "r": "/23 — до 510 узлов" if n <= 510 else "/22 — до 1022 узлов",
                            "k": rng.choice([16, 20, 24, 28]), "g": rng.choice([130, 160, 200, 240])})(rng.choice([300, 420, 480, 700, 900])))
simple(SPEC, "Учётные записи и доступ", -1.4, "Учётка сотрудника", "Как поступить правильно?", [
    ("В ⟨dep⟩ вышел новый сотрудник. Ему нужен доступ к общей папке отдела «⟨f⟩».", "Добавить его в доменную группу отдела, которой выданы права на папку"),
    ("Сотрудник ⟨depg⟩ сегодня уволился. Руководитель просит месяц хранить его почту и документы из папки «⟨f⟩».",
     "Отключить учётную запись сегодня, а удалить её после передачи почты и файлов"),
    ("Сотрудник перешёл из ⟨depg⟩ в другой отдел. Новые папки ему открыли, но он по-прежнему видит папку «⟨f⟩» прежнего отдела.",
     "Исключить его из группы прежнего отдела, через которую выданы права на папку"),
], ["Выдать права на папку лично его учётной записи, а группы не трогать", "Включить его в «Администраторы домена», чтобы права больше не мешали"],
    lambda rng: (lambda d: {"dep": d[0], "depg": d[1], "f": rng.choice(["Документы", "Отчёты", "Шаблоны"])})(
        rng.choice([("бухгалтерию", "бухгалтерии"), ("отдел продаж", "отдела продаж"), ("отдел кадров", "отдела кадров")])))
simple(SPEC, "Резервное копирование", -1.0, "Слабое место бэкапа", "Что не так?", [
    ("Ночные копии файлового сервера ⟨srv⟩ складываются на второй диск этого же сервера, ⟨n⟩ последних копий. Восстановление из них проверяют раз в квартал.",
     "Все копии лежат рядом с данными: пожар или шифровальщик заберут и их — нужна копия вне сервера и офиса"),
    ("Ночные копии ⟨srv⟩ уходят на NAS и в облако, ⟨n⟩ последних копий. Задание каждую ночь «зелёное», но восстановить из копии ни разу не пробовали.",
     "Копии ни разу не проверены восстановлением: «зелёное» задание не гарантирует, что из них можно подняться"),
    ("Копии ⟨srv⟩ делаются раз в неделю, в воскресенье, на NAS и в облако; восстановление проверяют раз в квартал. Бухгалтерия правит файлы каждый день.",
     "Копии слишком редкие: при сбое в пятницу пропадёт почти неделя работы — копировать хотя бы каждую ночь"),
], ["Второй диск надо объединить с первым в RAID 1 — зеркало и будет надёжной резервной копией",
    "Копии надо хранить без сжатия и шифрования, иначе восстановить из них потом не получится"],
    {"srv": ["fs01", "srv-files", "fs-main"], "n": [7, 14]})
simple(SPEC, "Серверы и ОС", -0.8, "Медленный сервер", "Что вероятнее всего?", [
    ("Сервер ⟨srv⟩ отвечает медленно. В top: load average ⟨la⟩ при 4 ядрах, us 6 %, sy 3 %, wa ⟨wa⟩ %, swap не используется.",
     "Узкое место — диск: процессы ждут ввода-вывода, смотреть iostat и iotop"),
    ("Сервер ⟨srv⟩ отвечает медленно. В top: load average ⟨la⟩ при 4 ядрах, us 94 %, wa 0 %; процесс ⟨proc⟩ занимает 370 % CPU.",
     "Узкое место — процессор: его занял ⟨proc⟩, разбираться, что он делает"),
    ("Сервер ⟨srv⟩ отвечает медленно, службы иногда падают. В top: us 7 %, wa 2 %; свободно 90 МБ памяти, swap 3,9 из 4 ГБ; в dmesg — «Out of memory: Killed process».",
     "Кончается память: OOM killer убивает процессы, искать, кто её занял"),
], ["Перегружена сеть: проверить загрузку сетевого интерфейса и канала", "Сбились часы сервера: настроить синхронизацию времени по NTP"],
    {"srv": ["srv-1c", "fs01", "db01"], "la": [9.8, 12.4, 15.1], "wa": [64, 72, 81], "proc": ["rphost", "java", "clamd"]})
simple(SPEC, "Работа с обращениями", -1.6, "Срочное обращение", "Что сделать первым?", [
    ("В очередь пришло обращение от ⟨who⟩: «Ничего не работает!!! Срочно!»", "Уточнить: что именно не работает, с какого времени, какая ошибка и у кого ещё"),
    ("За 10 минут пришло ⟨k⟩ обращений с ⟨fl⟩-го этажа от разных людей: у всех одновременно перестала открываться 1С.",
     "Объединить обращения в массовый инцидент и сообщить этажу, что проблема известна"),
    ("Звонит ⟨who2⟩: на экране требование выкупа, а файлы на рабочем столе сменили расширение.",
     "Сразу отключить компьютер от сети, не выключая его, и сообщить в ИБ"),
], ["Закрыть обращение как неполное и попросить пользователя завести новое", "Удалённо перезагрузить компьютер пользователя и посмотреть, повторится ли"],
    {"who": ["сотрудника склада", "менеджера отдела продаж", "юриста"], "who2": ["бухгалтер", "менеджер отдела продаж", "юрист"],
     "k": [6, 9, 12], "fl": [2, 3, 4]})


# ============================== Диагностика инцидентов ==============================


@family("adm_inc_dupip", SPEC, "Диагностика инцидентов", "choice", 2.2, -1.1)
def _(rng):
    net = rng.choice(["192.168.10", "10.10.20", "172.16.5", "192.168.40"])
    ip, pc = f"{net}.{rng.randint(60, 180)}", f"PC-{rng.choice(['BUH', 'SALES', 'HR', 'LOG'])}-{rng.randint(1, 30):02d}"
    prn = rng.choice(["PRN-2ETAZH", "MFU-BUH", "PRN-SKLAD", "MFU-PRIEM"])
    mac_pc, mac_prn, m = _mac(rng), _mac(rng), rng.randint(10, 40)
    t = lambda dm, s: f"08:{m + dm:02d}:{s:02d}"  # noqa: E731
    scope = f"scope {net}.0/24: range {net}.50–{net}.200"
    v = _variant(rng, 3)
    if v == 0:  # принтеру вручную задан адрес из пула
        lines = [_log(t(0, 2), "dhcp01", "INFO", f"{scope}, exclusions: none, reservations: 0, used {rng.randint(40, 70)} %"),
                 _log(t(0, 14), "dhcp01", "INFO", f"DHCPACK {ip} to {mac_pc} ({pc}), lease 8h"),
                 _log(t(1, 40), pc, "ERROR", f"Tcpip 4199: обнаружен конфликт IP-адреса {ip} с системой, имеющей адрес {mac_prn}"),
                 _log(t(3, 5), "print01", "WARN", f"PrintService: порт {ip} принтера {prn} не отвечает, задание отложено"),
                 _log(t(4, 21), "inventory", "INFO", f"{prn}: MAC {mac_prn}, адрес задан вручную в веб-интерфейсе")]
    elif v == 1:  # чужой DHCP-сервер
        rogue, port = _mac(rng), rng.randint(5, 40)
        lines = [_log(t(0, 2), "dhcp01", "INFO", f"{scope}, used {rng.randint(40, 70)} %"),
                 _log(t(0, 14), pc, "INFO", f"Dhcp: получен адрес 192.168.0.{rng.randint(100, 199)} от сервера 192.168.0.1, шлюз 192.168.0.1"),
                 _log(t(1, 40), pc, "ERROR", "NETLOGON 5719: не удалось связаться с контроллером домена"),
                 _log(t(3, 5), "print01", "WARN", f"PrintService: {prn} не отвечает по адресу {ip}, задание отложено"),
                 _log(t(4, 21), "sw-floor2", "INFO", f"Gi1/0/{port}: новый MAC {rogue}, с него идут DHCPOFFER")]
    else:  # пул исчерпан гостевыми устройствами
        lines = [_log(t(0, 2), "dhcp01", "WARN", f"{scope}: 151 of 151 addresses in use (100 %), lease 8 days"),
                 _log(t(0, 14), "dhcp01", "WARN", f"DHCPDISCOVER from {mac_pc} ({pc}): no free leases"),
                 _log(t(1, 40), pc, "ERROR", f"Dhcp 1002: аренда адреса {ip} истекла и не продлена, сервер не выдал новый адрес"),
                 _log(t(3, 5), "print01", "WARN", f"PrintService: {prn} не получил адрес по DHCP и не отвечает, задание отложено"),
                 _log(t(4, 21), "wlc", "INFO", f"гостевой Wi-Fi в той же области {net}.0/24, разных устройств за неделю: {rng.randint(180, 260)}")]
    opts, key = _options(rng, [f"У {prn} вручную задан адрес из пула DHCP: исключить адрес из пула или зарезервировать его за MAC принтера",
                               "В сети чужой DHCP-сервер раздаёт свои адреса: найти его по MAC на коммутаторе и включить DHCP snooping",
                               f"Область {net}.0/24 исчерпана гостевыми устройствами: вынести гостей в отдельную сеть и сократить аренду"], v,
                         ["Сервер DHCP выдаёт один адрес двум устройствам: пересоздать область и перезапустить службу DHCP на dhcp01",
                          f"Драйвер принтера на {pc} перехватывает его адрес: переустановить драйвер и перезагрузить {pc}"])
    return {"scene_title": "То печатает, то нет", "story": f"С утра {prn} то печатает, то нет, а у сотрудника за {pc} то и дело пропадает сеть.",
            "prompt": "В чём причина и как исправить?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("adm_inc_skew", SPEC, "Диагностика инцидентов", "choice", 2.3, 1.0)
def _(rng):
    dom, dc, other = rng.choice(DOMAINS), rng.choice(["dc01", "dc02"]), rng.choice(["fs01", "srv-files", "fs-main"])
    m, pc = rng.randint(10, 40), f"PC-{rng.choice(['BUH', 'SALES', 'HR'])}-{rng.randint(1, 30):02d}"
    drives = _log(f"08:{m:02d}:05", pc, "WARN", "Winlogon: не удаётся подключить сетевые диски H: и S:")
    clock_ok = _log(f"08:{m + 1:02d}:12", "admin", "INFO", f"w32tm /stripchart {dc} → ntp.example: смещение +00:00:0{rng.randint(0, 2)}")
    v = _variant(rng, 3)
    if v == 0:  # часы PDC-эмулятора ушли
        src = rng.choice(["Local CMOS Clock", "VM IC Time Synchronization Provider"])
        lines = [_log(f"08:{m:02d}:03", pc, "ERROR", f"Security-Kerberos 4: получена ошибка KRB_AP_ERR_SKEW от сервера {other}.{dom}"), drives,
                 _log(f"08:{m:02d}:31", dc, "WARN", f"Time-Service 36: служба времени не синхронизировалась {rng.randint(30, 90)} ч"),
                 _log(f"08:{m + 1:02d}:10", "admin", "INFO", f"w32tm /query /source на {dc} (PDC-эмулятор): {src}"),
                 _log(f"08:{m + 1:02d}:12", "admin", "INFO", f"w32tm /stripchart {dc} → ntp.example: смещение +00:{rng.randint(7, 25):02d}:{rng.randint(0, 59):02d}")]
    elif v == 1:  # сервер откатили на старый снимок — пароль учётки компьютера разошёлся с доменом
        lines = [_log(f"08:{m:02d}:03", pc, "ERROR", f"Security-Kerberos 4: получена ошибка KRB_AP_ERR_MODIFIED от сервера {other}.{dom}"), drives,
                 _log(f"08:{m:02d}:40", other, "ERROR", f"NETLOGON 3210: не удалось пройти проверку подлинности на {dc}: пароль учётной записи компьютера не принят"),
                 _log(f"08:{m + 1:02d}:02", "admin", "INFO", f"vCenter: ВМ {other} в выходные откатили на снимок {rng.randint(40, 90)}-дневной давности"),
                 clock_ok]
    else:  # хранилище умеет только SMB1, а его отключили политикой
        lines = [_log(f"07:{m:02d}:00", dc, "INFO", "GPO «Безопасность рабочих станций»: клиент SMB 1.0 отключён, применяется при перезагрузке"),
                 _log(f"08:{m:02d}:03", pc, "ERROR", f"SMBClient 32000: {other} поддерживает только диалект SMB1, а он отключён на клиенте"), drives,
                 _log(f"08:{m + 1:02d}:02", "inventory", "INFO", f"{other}: сетевое хранилище, прошивка {rng.randint(2012, 2015)} г."),
                 clock_ok]
    opts, key = _options(rng, [f"Часы {dc} ушли более чем на 5 мин, Kerberos отвергает билеты: настроить NTP на PDC-эмуляторе",
                               f"{other} откатили на старый снимок, его пароль в домене разошёлся: восстановить защищённый канал",
                               f"{other} понимает только SMB1, который отключили политикой: обновить хранилище или перенести данные"], v,
                         ["Истёк срок действия паролей у сотрудников: принудительно сбросить пароли и попросить всех войти заново",
                          f"Нарушена репликация между контроллерами домена: выполнить repadmin /syncall /AdeP и перезагрузить {dc}"])
    return {"scene_title": "Не пускает в сеть", "story": f"С утра часть сотрудников входит в Windows, но не может подключить сетевые диски с {other}.",
            "prompt": "Что происходит и как исправить?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("adm_inc_monday", SPEC, "Диагностика инцидентов", "choice", 2.3, 2.0)
def _(rng):
    srv, grow, end = rng.choice(["fs01", "srv-files", "fs-main"]), rng.randint(30, 60), rng.choice([6, 7])
    v = _variant(rng, 3)
    start = [0, 2, 1][v]  # фоновая работа: копия — с вечера воскресенья, антивирус — с 02:00, проверка массива — с полуночи
    x = ["Вс 22:00"] + [f"Пн {h:02d}:00" for h in range(0, 15, 2)]
    job = [rng.randint(85, 120) if start <= i <= end else 0 for i in range(9)]
    lat = [rng.randint(15, 30) if i < 5 else (rng.randint(120, 180) if i <= end else rng.randint(5, 12)) for i in range(9)]
    name = ["поток задания резервного копирования, МБ/с", "чтение антивирусной проверкой, МБ/с", "фоновая проверка массива контроллером, МБ/с"][v]
    panel = {"type": "chart", "x": x, "marker": {"i": 5, "label": "начало рабочего дня"}, "series": [
        {"name": f"задержка дисков {srv}, мс", "axis": "left", "max": 200, "data": lat},
        {"name": name, "axis": "right", "max": 150, "data": job},
    ]}
    story = f"Каждый понедельник до обеда файловый сервер {srv} «тормозит», потом всё проходит. Месяц назад такого не было"
    story += [f", а объём общих папок с тех пор вырос на {grow} %.",
              f", а объём общих папок с тех пор вырос на {grow} %. Резервная копия по журналу заканчивается в воскресенье к 23:00.",
              "; тогда же диски массива заменили на вдвое более ёмкие, а объём данных почти не изменился. Резервная копия заканчивается в воскресенье к 23:00."][v]
    opts, key = _options(rng, ["Полная копия выходного дня перестала укладываться в ночное окно и теперь идёт в рабочие часы",
                               "Еженедельная антивирусная проверка общих папок разрослась и теперь захватывает рабочие часы",
                               "Плановая проверка массива на новых, более ёмких дисках идёт дольше и захватывает рабочие часы"], v,
                         [f"Утром все одновременно входят в систему, и {srv} не справляется с наплывом: нужен второй файловый сервер",
                          "На томе общих папок кончается место, и файлы сильно фрагментируются: запустить дефрагментацию"])
    return {"scene_title": "Тяжёлый понедельник", "story": story, "prompt": "Что вероятнее всего?", "panel": panel, "options": opts, "key": key}


@family("adm_inc_stale_dc", SPEC, "Диагностика инцидентов", "choice", 2.3, 2.5)
def _(rng):
    dom, net = rng.choice(DOMAINS), rng.choice(["10.0.0", "10.10.1", "192.168.100", "172.20.0"])
    net2 = rng.choice(["10.0.40", "10.10.50", "10.20.60"])
    names = ["dc01", "dc02", rng.choice(["dc03", "dc-old", "dc2012"])]
    ips = [f"{net}.{n}" for n in rng.sample(range(5, 40), 3)]
    city = rng.choice(["Kazan", "Tver", "Samara", "Perm"])
    mins = rng.randint(2, 4)
    gpo = ["PS> Get-WinEvent GroupPolicy | Select -First 1", "1129: обработка групповой политики не удалась из-за отсутствия связи с контроллером домена"]
    dcs = ["PS> Get-ADDomainController -Filter * | Select Name, IPv4Address"]
    v = _variant(rng, 3)
    if v == 0:  # контроллер выключили без понижения — его записи остались в DNS
        dead = 2
        lines = [f"PS> nslookup {dom}", f"Имя:       {dom}", f"Addresses: {ips[0]}", f"           {ips[1]}", f"           {ips[2]}"] + dcs + [
            f"{n:<8}{ip}" for n, ip in zip(names, ips)] + [f"PS> Test-Connection {ips[dead]} -Count 1", "Test-Connection: превышен интервал ожидания для запроса"] + gpo
        story = f"Месяц назад старый сервер {names[dead]} просто выключили и списали. С тех пор"
    elif v == 1:  # DHCP на новом роутере раздаёт внешние DNS
        gw = f"{net}.1"
        lines = ["PS> ipconfig /all | Select-String 'DHCP-сервер|DNS-серверы'", f"   DHCP-сервер . . . : {gw}", "   DNS-серверы . . . : 8.8.8.8, 77.88.8.8",
                 f"PS> nslookup -type=SRV _ldap._tcp.dc._msdcs.{dom}", f"*** dns.google не удалось найти _ldap._tcp.dc._msdcs.{dom}: Non-existent domain"] + dcs + [
            f"{n:<8}{ip}" for n, ip in zip(names[:2], ips[:2])] + [f"PS> Test-Connection {ips[0]} -Count 1", "Ответ от " + ips[0] + ": время<1 мс"] + gpo
        story = "Месяц назад раздачу адресов в офисе перенесли с сервера на новый роутер. С тех пор"
    else:  # подсеть нового этажа не привязана к сайту AD — клиенты ходят к контроллеру филиала
        far, far_ip = f"dc-{city.lower()}", f"10.50.0.{rng.randint(5, 20)}"
        lines = [f"PS> nltest /dsgetdc:{dom}", f"           DC: \\\\{far}.{dom}", f"      Address: \\\\{far_ip}", f"  Dc Site Name: {city}", "Our Site Name: (не определён)",
                 "PS> ipconfig | Select-String IPv4", f"   IPv4-адрес . . . : {net2}.{rng.randint(20, 200)}",
                 "PS> Get-ADReplicationSubnet -Filter * | Select Name, Site", f"{net}.0/24      HQ", f"10.50.0.0/24     {city}",
                 f"PS> Test-Connection {far} -Count 1", f"Ответ от {far_ip}: время={rng.randint(38, 70)} мс",
                 "PS> Get-WinEvent GroupPolicy | Select -First 1", "5327: обнаружен медленный канал до контроллера домена, часть политик пропущена"]
        story = f"Месяц назад несколько отделов переехали на новый этаж с подсетью {net2}.0/24. С тех пор"
    story += f" у части сотрудников вход длится по {mins} минуты, а групповые политики применяются через раз."
    opts, key = _options(rng, [f"{names[2]} выключили без понижения: очистить метаданные и удалить его A- и SRV-записи из DNS",
                               "Клиенты получают по DHCP внешние DNS: в настройках роутера указать только DNS контроллеров домена",
                               f"Подсеть {net2}.0/24 не привязана к сайту AD: клиенты ходят к контроллеру филиала — добавить её"], v,
                         ["Клиенты закэшировали старый контроллер: выполнить на всех ПК ipconfig /flushdns и перезагрузить их",
                          f"Сломана репликация SYSVOL между {names[0]} и {names[1]}: перезапустить DFSR и выполнить авторитетное восстановление"])
    return {"scene_title": "Долгий вход", "story": story, "prompt": "В чём причина и что сделать?", "panel": {"type": "code", "lang": "powershell", "lines": lines},
            "options": opts, "key": key}


# ============================== Сети ==============================


@family("adm_net_trunk", SPEC, "Сети", "mark", 2.2, -1.0)
def _(rng):
    corp, voice, guest = rng.choice([10, 100]), rng.choice([20, 40]), rng.choice([30, 50, 99])
    port, floor = rng.randint(5, 20), rng.randint(2, 6)
    v = _variant(rng, 3)  # 0 — гостевой VLAN не пропущен в транк, 1 — интерфейс VLAN выключен, 2 — весь пул исключён из раздачи
    lines = [f"hostname sw-floor{floor}", "!", f"vlan {corp}", " name CORP", f"vlan {voice}", " name VOICE", f"vlan {guest}", " name GUEST", "!"]
    if rng.random() < 0.5:
        lines += [f"interface GigabitEthernet1/0/{port - 1}", " description PC-reception", " switchport mode access", f" switchport access vlan {corp}",
                  f" switchport voice vlan {voice}", "!"]
    allowed = sorted([corp, guest] if v else [corp, voice])
    lines += [f"interface GigabitEthernet1/0/{port}", f" description AP-meeting-{floor}{rng.randint(1, 9):02d}", " switchport mode trunk",
              f" switchport trunk native vlan {corp}", f" switchport trunk allowed vlan {allowed[0]},{allowed[1]}"]
    if v == 0:
        key = len(lines)
    lines += [" spanning-tree portfast trunk", "!", f"ip dhcp excluded-address 10.{guest}.0.1 10.{guest}.0.{254 if v == 2 else 10}"]
    if v == 2:
        key = len(lines)
    lines += ["ip dhcp pool GUEST", f" network 10.{guest}.0.0 255.255.255.0", f" default-router 10.{guest}.0.1", f" dns-server {rng.choice(['77.88.8.8', '1.1.1.1'])}",
              "!", f"interface Vlan{guest}", " description GUEST", f" ip address 10.{guest}.0.1 255.255.255.0", " shutdown" if v == 1 else " no shutdown"]
    if v == 1:
        key = len(lines)
    lines.append("!")
    return {"scene_title": "Гостевой Wi-Fi", "story": f"В переговорной на {floor}-м этаже повесили новую точку доступа. Корпоративная сеть Wi-Fi работает, "
                                                      f"а гости в сети «Guest» (VLAN {guest}) не получают адрес. Адреса гостям раздаёт сам коммутатор.",
            "prompt": "Нажмите на строку с ошибкой.", "panel": {"type": "code", "lang": "text", "lines": lines}, "key": key}


@family("adm_net_vpn_overlap", SPEC, "Сети", "choice", 2.3, 0.5)
def _(rng):
    fs, dom = rng.choice(["fs01", "srv-files", "srv-1c"]), rng.choice(DOMAINS)
    h, o = rng.randint(100, 200), rng.randint(10, 250)
    v = _variant(rng, 3)
    net = rng.choice(["192.168.0", "192.168.1", "192.168.88"]) if v == 0 else rng.choice(["10.0.10", "10.1.20", "172.16.10"])
    home = net if v == 0 else rng.choice(["192.168.0", "192.168.1"])
    srv = f"{net}.{rng.randint(10, 40)}"
    if v == 0:  # домашняя сеть совпадает с офисной
        lines = [f"Wi-Fi:  IPv4 {home}.{h}/24, шлюз {home}.1", f"VPN:    IPv4 10.8.0.{o}/24", "", "PS> route print -4  (фрагмент)",
                 f"{net}.0    255.255.255.0    On-link     {home}.{h}   метрика 25",
                 f"{net}.0    255.255.255.0    10.8.0.1    10.8.0.{o}     метрика 35", f"10.8.0.0      255.255.255.0    On-link     10.8.0.{o}     метрика 35",
                 "", f"PS> Test-NetConnection {srv} -Port 445", "TcpTestSucceeded : False"]
        story = "Сотрудник работает из дома через VPN. Почта и портал открываются, а файловый сервер {fs} ({srv}) недоступен. У коллег на том же VPN всё работает."
    elif v == 1:  # VPN-клиент не получил корпоративный DNS
        lines = [f"Wi-Fi:  IPv4 {home}.{h}/24, шлюз {home}.1, DNS {home}.1", f"VPN:    IPv4 10.8.0.{o}/24, DNS-серверы: не заданы", "",
                 f"PS> Resolve-DnsName {fs}.{dom}", f"Resolve-DnsName: {fs}.{dom}: DNS name does not exist", "",
                 f"PS> Test-NetConnection {srv} -Port 445", "TcpTestSucceeded : True"]
        story = "Сотрудник работает из дома через VPN. Почта и портал открываются, а файловый сервер \\\\{fs} не открывается. У коллег на том же VPN всё работает."
    else:  # брандмауэр сервера пускает SMB только из офисной подсети
        lines = [f"Wi-Fi:  IPv4 {home}.{h}/24, шлюз {home}.1", f"VPN:    IPv4 10.8.0.{o}/24, DNS {net}.5", "",
                 f"PS> Test-NetConnection {fs} -Port 445", f"RemoteAddress    : {srv}", "PingSucceeded    : True", "TcpTestSucceeded : False", "",
                 f"PS> Get-NetFirewallRule -DisplayName 'SMB-In' -CimSession {fs} | Get-NetFirewallAddressFilter", "RemoteAddress : LocalSubnet"]
        story = "Со вчерашнего дня сотрудники на VPN не могут открыть файловый сервер {fs} ({srv}); почта и портал открываются, из офиса {fs} работает."
    opts, key = _options(rng, [f"Домашняя сеть совпадает с офисной: трафик к {srv} уходит в домашний Wi-Fi, а не в туннель",
                               f"VPN-клиент не получил корпоративный DNS: имя {fs} не разрешается, хотя по адресу сервер доступен",
                               f"Брандмауэр {fs} пускает SMB только из офисной подсети: добавить в правило пул VPN 10.8.0.0/24"], v,
                         ["Домашний провайдер блокирует порт 445: перевести общий доступ к файлам на нестандартный порт",
                          f"Сотруднику не выданы права на общую папку: добавить его в группу с доступом к ресурсам {fs}"])
    return {"scene_title": "Из дома не видно", "story": story.format(fs=fs, srv=srv),
            "prompt": "В чём причина?", "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}


@family("adm_net_loop", SPEC, "Сети", "choice", 2.3, 1.9)
def _(rng):
    floor, vlan, m = rng.randint(2, 6), rng.choice([10, 20, 100]), rng.randint(10, 40)
    a, b = rng.sample(range(5, 24), 2)
    sw = f"sw-floor{floor}"
    up = _log(f"10:{m:02d}:02", sw, "INFO", f"%LINK-3-UPDOWN: Interface Gi1/0/{b} (meeting-{floor}02), changed state to up")
    calls = _log(f"10:{m + 1:02d}:03", "helpdesk", "INFO", f"обращений с {floor}-го этажа за 5 минут: {rng.randint(6, 14)} — «сеть пропадает каждые несколько секунд»")
    v = _variant(rng, 3)
    if v == 0:  # петля через настольный коммутатор
        lines = [up] + [_log(f"10:{m:02d}:{5 + 4 * i:02d}", sw, "WARN",
                             f"%SW_MATM-4-MACFLAP_NOTIF: Host {_mac(rng)} in vlan {vlan} is flapping between port Gi1/0/{a} and port Gi1/0/{b}") for i in range(3)]
        lines += [_log(f"10:{m:02d}:20", sw, "WARN", "CPU utilization 98 %, broadcast input 41 000 pps on Gi1/0/49 (uplink)"), calls]
    elif v == 1:  # устройство в переговорной заняло адрес шлюза
        rogue = _mac(rng)
        lines = [up] + [_log(f"10:{m:02d}:{5 + 4 * i:02d}", "core-sw", "WARN", f"%IP-4-DUPADDR: Duplicate address 10.{vlan}.0.1 on Vlan{vlan}, sourced by {rogue}")
                        for i in range(3)]
        lines += [_log(f"10:{m:02d}:20", sw, "INFO", f"show mac address-table address {rogue}: vlan {vlan}, port Gi1/0/{b}"), calls]
    else:  # аплинк этажа падает из-за слабого оптического сигнала
        lines = [up, _log(f"10:{m:02d}:05", sw, "ERROR", "%LINK-3-UPDOWN: Interface Gi1/0/49 (uplink), changed state to down"),
                 _log(f"10:{m:02d}:07", sw, "INFO", "%LINK-3-UPDOWN: Interface Gi1/0/49 (uplink), changed state to up"),
                 _log(f"10:{m:02d}:12", sw, "WARN", f"%SFF8472-5-THRESHOLD_VIOLATION: Gi1/0/49: Rx power low alarm; -{rng.randint(19, 23)}.{rng.randint(0, 9)} dBm"),
                 _log(f"10:{m:02d}:19", sw, "ERROR", "%LINK-3-UPDOWN: Interface Gi1/0/49 (uplink), changed state to down"), calls]
    opts, key = _options(rng, [f"Петля через Gi1/0/{a} и Gi1/0/{b}: отключить порт, затем включить BPDU Guard на портах доступа",
                               f"Устройство за Gi1/0/{b} заняло адрес шлюза: отключить порт и найти владельца устройства по MAC",
                               "Аплинк Gi1/0/49 падает из-за слабого оптического сигнала: заменить SFP-модуль и патч-корд"], v,
                         [f"Исчерпан пул DHCP в VLAN {vlan}: расширить область и сократить срок аренды",
                          f"Перегрелся коммутатор {sw}: проверить вентиляторы и температуру в шкафу этажа"])
    return {"scene_title": "Сеть мигает", "story": f"На {floor}-м этаже сеть пропадает у всех сразу. Незадолго до этого в переговорной подключали оборудование для презентации.",
            "prompt": "Что произошло и что делать?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("adm_net_snooping", SPEC, "Сети", "choice", 2.4, 2.5)
def _(rng):
    acc, chg, vl = f"sw-acc-{rng.randint(1, 8)}", rng.randint(100, 999), rng.choice(["10-40", "10-60", "20-50"])
    srv, core, m = rng.choice(["dhcp01", "dc01", "srv-infra"]), _mac(rng), rng.randint(10, 40)
    ip = f"10.{rng.choice([10, 20, 30])}.{rng.randint(0, 3)}.{rng.randint(20, 200)}"
    pc, p, calls = _mac(rng), rng.randint(1, 47), rng.randint(15, 40)
    base = f"CHG-{chg}: ip dhcp snooping; ip dhcp snooping vlan {vl}"
    uplink = _log("Пт 18:43:02", acc, "INFO", f"interface Gi1/0/48: description uplink-core, neighbor MAC {core}")
    v = _variant(rng, 3)
    if v == 0:  # аплинк не доверенный — snooping режет ответы настоящего сервера
        lines = [_log("Пт 18:42:10", acc, "INFO", base), uplink,
                 _log(f"Пн 08:{m:02d}:01", srv, "INFO", f"DHCPDISCOVER from {pc} via relay; DHCPOFFER {ip}"),
                 _log(f"Пн 08:{m:02d}:05", acc, "INFO", f"%DHCP_SNOOPING-5-DHCP_SNOOPING_UNTRUSTED_PORT: drop message on untrusted port Gi1/0/48, message type: DHCPOFFER, MAC sa: {core}"),
                 _log(f"Пн 08:{m:02d}:09", srv, "INFO", f"DHCPDISCOVER from {pc} via relay; DHCPOFFER {ip}"),
                 _log(f"Пн 08:{m + 7:02d}:00", "helpdesk", "INFO", f"обращений «нет сети»: {calls}, в основном стационарные ПК, ноутбуки с прошлой недели работают")]
    elif v == 1:  # коммутатор вставляет option 82, сервер такие запросы отбрасывает
        lines = [_log("Пт 18:42:10", acc, "INFO", f"{base}; Gi1/0/48: ip dhcp snooping trust"), uplink,
                 _log(f"Пн 08:{m:02d}:01", acc, "INFO", f"DHCP_SNOOPING: option 82 inserted (circuit-id Gi1/0/{p}, remote-id {acc}) into DHCPDISCOVER from {pc}"),
                 _log(f"Пн 08:{m:02d}:02", srv, "WARN", f"DHCPDISCOVER from {pc}: option 82 present, giaddr 0.0.0.0 — packet dropped"),
                 _log(f"Пн 08:{m:02d}:09", srv, "WARN", f"DHCPDISCOVER from {pc}: option 82 present, giaddr 0.0.0.0 — packet dropped"),
                 _log(f"Пн 08:{m + 7:02d}:00", "helpdesk", "INFO", f"обращений «нет сети»: {calls}, в основном стационарные ПК, ноутбуки с прошлой недели работают")]
    else:  # слишком строгий лимит DHCP-пакетов на портах доступа
        lines = [_log("Пт 18:42:10", acc, "INFO", f"{base}; Gi1/0/48: ip dhcp snooping trust; Gi1/0/1-47: ip dhcp snooping limit rate 2"), uplink,
                 _log(f"Пн 08:{m:02d}:01", srv, "INFO", f"DHCPDISCOVER from {pc} via relay; DHCPOFFER {ip}; DHCPACK"),
                 _log(f"Пн 08:{m:02d}:04", acc, "WARN", f"%DHCP_SNOOPING-4-DHCP_SNOOPING_ERRDISABLE_WARNING: DHCP Snooping received {rng.randint(3, 6)} DHCP packets on interface Gi1/0/{p}"),
                 _log(f"Пн 08:{m:02d}:04", acc, "ERROR", f"%PM-4-ERR_DISABLE: dhcp-rate-limit error detected on Gi1/0/{p}, putting Gi1/0/{p} in err-disable state"),
                 _log(f"Пн 08:{m + 7:02d}:00", "helpdesk", "INFO", f"обращений «нет сети»: {calls}, в основном ПК, подключённые через IP-телефон")]
    opts, key = _options(rng, ["Аплинк Gi1/0/48 не помечен доверенным: snooping режет ответы сервера — нужен ip dhcp snooping trust",
                               "Коммутатор вставляет в запросы option 82, а сервер такие отбрасывает: отключить вставку option 82",
                               "Порты доступа ушли в err-disable по лимиту DHCP-пакетов: поднять лимит и включить автовосстановление"], v,
                         ["В сети появился чужой DHCP-сервер, и snooping правильно режет его ответы: найти устройство за портом Gi1/0/48",
                          f"Пул на {srv} исчерпан: сервер предлагает адреса, но не может их закрепить — расширить область"])
    return {"scene_title": "Нет адреса", "story": "В пятницу вечером на коммутаторах доступа включили защиту от чужих DHCP-серверов. Сегодня с утра "
                                                  "компьютеры массово остаются без сети.",
            "prompt": "В чём причина?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# ============================== Учётные записи и доступ ==============================

DEPS = [("Buh", "Бухгалтерия", "зарплатными ведомостями"), ("HR", "Кадры", "личными делами сотрудников"), ("Legal", "Юристы", "договорами с контрагентами"),
        ("Fin", "Финансы", "бюджетом на следующий год")]
LOGINS = ["a.morozova", "k.sokolov", "e.belova", "d.orlov", "n.zaitseva", "s.volkov"]


@family("adm_acc_ntfs", SPEC, "Учётные записи и доступ", "mark", 2.2, -1.1)
def _(rng):
    code, dep, secret = rng.choice(DEPS)
    dom, srv = rng.choice(["CORP", "OFFICE", "SEVERVET"]), rng.choice(["fs01", "srv-files", "fs-main"])
    path = f"D:\\Shares\\{code}"
    v = _variant(rng, 3)  # 0 — лишняя запись в ACL папки, 1 — в группу чтения вложена группа всех сотрудников, 2 — все сотрудники в локальных админах сервера
    bad = [rng.choice([f"{dom}\\Domain Users:(OI)(CI)(RX)", "Everyone:(OI)(CI)(M)", "NT AUTHORITY\\Authenticated Users:(OI)(CI)(RX)", "BUILTIN\\Users:(OI)(CI)(RX)"]),
           "group   GG_All_Staff", f"Группа         {dom}\\Domain Users"][v]
    aces = ["BUILTIN\\Administrators:(OI)(CI)(F)", f"{dom}\\GG_{code}_RW:(OI)(CI)(M)", f"{dom}\\GG_{code}_RO:(OI)(CI)(RX)"] + ([bad] if v == 0 else [])
    if rng.random() < 0.5:
        aces.append(f"{dom}\\GG_IT_Admins:(OI)(CI)(F)")
    rng.shuffle(aces)
    members = [f"user    {u}" for u in rng.sample(LOGINS, 3)] + ([bad] if v == 1 else [])
    rng.shuffle(members)
    admins = [f"Группа         {dom}\\Domain Admins", f"Группа         {dom}\\GG_IT_Admins", f"Пользователь   {srv}\\Administrator"] + ([bad] if v == 2 else [])
    rng.shuffle(admins)
    pad = " " * (len(path) + 1)
    lines = [f"PS> icacls {path}", f"{path} NT AUTHORITY\\SYSTEM:(OI)(CI)(F)"] + [pad + a for a in aces] + [pad + "CREATOR OWNER:(OI)(CI)(IO)(F)", "",
             f"PS> Get-ADGroupMember GG_{code}_RO | Select objectClass, SamAccountName"] + members + ["",
             f"PS> Get-LocalGroupMember Administrators -CimSession {srv}"] + admins
    key = lines.index(pad + bad if v == 0 else bad) + 1
    return {"scene_title": "Папка для всех", "story": f"Аудит: папку «{dep}» на {srv} с {secret} может открыть любой сотрудник компании. "
                                                      f"Права выдавались группам GG_{code}_RW и GG_{code}_RO.",
            "prompt": "Нажмите на строку, из-за которой папка открыта всем.", "panel": {"type": "code", "lang": "powershell", "lines": lines}, "key": key}


LEVELS = ["Нет доступа", "Чтение", "Изменение", "Полный доступ"]


@family("adm_acc_share_ntfs", SPEC, "Учётные записи и доступ", "choice", 2.2, 0.4)
def _(rng):
    (code, dep, _), (other, _, _) = rng.sample(DEPS, 2)
    srv, login = rng.choice(["fs01", "srv-files", "fs-main"]), rng.choice(LOGINS)
    eff = _variant(rng, 3)
    # итог — минимум из прав общего ресурса и NTFS; 0 — ни одна группа сотрудника не указана в NTFS
    share, groups = rng.choice({0: [(2, [f"GG_{other}_RW"]), (3, [f"GG_{other}_RO", f"GG_{other}_RW"])],
                                1: [(1, [f"GG_{code}_RO", f"GG_{code}_RW"]), (3, [f"GG_{code}_RO"]), (2, [f"GG_{code}_RO"])],
                                2: [(2, [f"GG_{code}_RO", f"GG_{code}_RW"]), (3, [f"GG_{code}_RW"])]}[eff])
    lines = [f"Общий ресурс \\\\{srv}\\{code}", f"  Разрешения общего ресурса: Everyone — {LEVELS[share]}", f"Разрешения NTFS на D:\\Shares\\{code}:",
             f"  CORP\\GG_{code}_RO — Чтение и выполнение", f"  CORP\\GG_{code}_RW — Изменение", "  BUILTIN\\Administrators — Полный доступ",
             f"Учётная запись {login}: группы {', '.join(groups)}"]
    opts, key = _options(rng, ["Нет доступа: папка не откроется", "Чтение: открыть и скопировать файлы", "Изменение: править и удалять файлы"], eff,
                         ["Полный доступ, включая смену прав"])
    return {"scene_title": "Права через сеть", "story": f"Сотрудник открывает папку отдела «{dep}» по сети: \\\\{srv}\\{code}.",
            "prompt": f"Какой доступ к файлам по сети получит {login}?", "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}


@family("adm_acc_gpo", SPEC, "Учётные записи и доступ", "choice", 2.3, 1.8)
def _(rng):
    dom, (code, dep, _) = rng.choice(DOMAINS), rng.choice(DEPS)
    x, y, z = rng.sample([5, 10, 15, 20, 30], 3)
    blk = rng.random() < 0.5
    pc = f"PC-{code.upper()}-{rng.randint(1, 30):02d}"
    v = _variant(rng, 3)  # 0 — доменная политика принудительная, 1 — побеждает политика OU, 2 — доменные политики параметр не задают
    lines = ["Параметр: Конфигурация компьютера → Параметры безопасности → «Интерактивный вход в систему: предел простоя компьютера»",
             f"{dom} (домен)", f"  └ GPO «Default Security» [Принудительный: {'да' if v == 0 else 'нет'}] — {'не задан' if v == 2 else f'{x * 60} с'}", "  OU Компьютеры",
             f"    └ OU {dep} [Блокировка наследования: {'да' if blk else 'нет'}]",
             f"        └ GPO «{dep}: простой» [связь {'отключена' if v == 2 else 'включена'}] — {y * 60} с",
             f"Локальная политика {pc}: {z * 60} с", f"Компьютер {pc} находится в OU {dep}"]
    opts, key = _options(rng, [f"{x} мин: принудительная доменная политика побеждает, даже если наследование заблокировано",
                               f"{y} мин: политика, привязанная к OU компьютера, применяется последней и побеждает",
                               f"{z} мин: ни одна доменная политика параметр не задаёт, и действует локальная настройка"], v,
                         ["Ни одна: при конфликте значений из разных объектов политики параметр не задаётся вовсе"])
    return {"scene_title": "Чья политика", "story": f"Служба безопасности спрашивает, через сколько минут простоя {pc} заблокирует сеанс (Interactive logon: Machine inactivity limit). Структура политик — на панели.",
            "prompt": "Какое значение применится?", "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}


@family("adm_acc_adminsd", SPEC, "Учётные записи и доступ", "choice", 2.3, 2.6)
def _(rng):
    login, dom = rng.choice(["s.volkov", "o.lebedeva", "p.kuznetsov", "t.egorova"]), rng.choice(["corp", "office", "hq"])
    grp, ago = rng.choice(["Account Operators", "Backup Operators", "Domain Admins", "Server Operators"]), rng.randint(6, 18)
    ou = rng.choice(["Подрядчики", "Практиканты", "Временные"])
    base = f"DC={dom},DC=local"
    v = _variant(rng, 3)  # 0 — бывший член защищённой группы (AdminSDHolder), 1 — у объекта отключено наследование, 2 — учётка в другом OU
    where = ou if v == 2 else "Сотрудники"
    lines = [f"PS> Get-ADUser {login} -Properties adminCount, memberOf | Select DistinguishedName, adminCount, memberOf",
             f"DistinguishedName : CN={login},OU={where},{base}", f"adminCount        : {'1' if v == 0 else ''}", f"memberOf          : {{CN=GG_Sales,OU=Группы,{base}}}",
             f"PS> (Get-Acl \"AD:CN={login},OU={where},{base}\").AreAccessRulesProtected", "False" if v == 2 else "True"]
    if v == 0:
        lines += [f"PS> Get-ADReplicationAttributeMetadata (Get-ADUser {login}) -Server dc01 -Properties nTSecurityDescriptor | Select LastOriginatingChangeTime",
                  f"LastOriginatingChangeTime : сегодня 10:{rng.randint(0, 59):02d}  (ручная правка прав — сегодня 09:{rng.randint(0, 59):02d})",
                  f"# {ago} мес. назад {login} на время отпуска коллеги добавляли в «{grp}»"]
        story = " Права на эту учётку добавили вручную, через час они пропали снова."
    elif v == 1:
        lines.append(f"# {ago} мес. назад учётку {login} перенесли из старого домена инструментом миграции")
        story = " Повторный запуск мастера делегирования не помог."
    else:
        lines.append(f"# {ago} мес. назад {login} оформили в штат")
        story = " Повторный запуск мастера делегирования не помог."
    opts, key = _options(rng, ["Учётка была в защищённой группе: SDProp раз в час возвращает ей права по шаблону AdminSDHolder, сбросить adminCount",
                               "У объекта учётки отключено наследование прав: делегирование с OU на него не действует — включить наследование",
                               f"Учётка лежит не в OU «Сотрудники», а в «{ou}»: делегирование туда не распространяется — перенести учётку"], v,
                         ["Права перезатирает репликация со старого контроллера: найти DC с устаревшей копией и выполнить принудительную репликацию",
                          "Политика «Группы с ограниченным доступом» при каждом обновлении возвращает права на учётку к исходным"])
    return {"scene_title": "Права не действуют", "story": f"Поддержке делегировали сброс паролей в OU «Сотрудники». У всех работает, а у {login} — «Отказано в доступе»." + story,
            "prompt": "В чём причина?", "panel": {"type": "code", "lang": "powershell", "lines": lines}, "options": opts, "key": key}


# ============================== Резервное копирование ==============================

SHARES = ["share", "public", "depts"]


@family("adm_bak_mirror", SPEC, "Резервное копирование", "mark", 2.2, -1.2)
def _(rng):
    srv, (share, share2) = rng.choice(["fs01", "srv-files", "fs-main"]), rng.sample(SHARES, 2)
    folder = rng.choice(["Договоры 2026", "Отчёты Q3", "Сметы", "Прайсы поставщиков"])
    flag = rng.choice(["", "v", "h"])
    v = _variant(rng, 3)  # 0 — зеркало с --delete, 1 — снимки хранятся двое суток, 2 — копируется не тот ресурс
    lines = ["#!/bin/bash", f"# ночной бэкап общих папок {srv} (ресурс \\\\{srv}\\имя = /srv/имя) на NAS, cron: 0 2 * * *", "set -euo pipefail", f"SRC=/srv/{share}/"]
    if v == 2:
        key = len(lines)
    lines += [f"DST=/mnt/nas/backup/{share}", f"LOG=/var/log/backup-{share}.log"]
    if rng.random() < 0.5:
        lines.append("mountpoint -q /mnt/nas || mount /mnt/nas")
    if v == 1:
        lines += ["SNAP=$(date +%F)", f'rsync -a{flag} --link-dest="$DST/latest" "$SRC" "$DST/$SNAP" >> "$LOG" 2>&1', 'ln -sfn "$DST/$SNAP" "$DST/latest"',
                  "# храним ежедневные копии 30 дней", 'find "$DST" -mindepth 1 -maxdepth 1 -mtime +1 -exec rm -rf {} +']
        key = len(lines)
    else:
        lines.append(f'rsync -a{flag}{" --delete" if v == 0 else ""} "$SRC" "$DST/" >> "$LOG" 2>&1')
        if v == 0:
            key = len(lines)
    if rng.random() < 0.5:
        lines.append('find /var/log -name "backup-*.log" -mtime +30 -delete')
    lines.append('echo "$(date \'+%F %T\') ok" >> "$LOG"')
    where = f"ресурсе \\\\{srv}\\{share2 if v == 2 else share}"
    story = [f"В пятницу сотрудник случайно удалил папку «{folder}» в {where}. Сегодня её нет и в бэкапе на NAS",
             f"В пятницу сотрудник случайно удалил папку «{folder}» в {where}. Сегодня её нет ни в одной копии на NAS",
             f"В пятницу сотрудник случайно удалил папку «{folder}» в {where}. Сегодня её не находят в бэкапе на NAS"][v]
    return {"scene_title": "Пустой бэкап", "story": story + ", хотя скрипт каждую ночь отрабатывает без ошибок.",
            "prompt": "Нажмите на строку, из-за которой папки нет в бэкапе.", "panel": {"type": "code", "lang": "bash", "lines": lines}, "key": key}


DAYS = ["Пн", "Вт", "Ср", "Чт", "Пт"]


@family("adm_bak_chain", SPEC, "Резервное копирование", "choice", 2.2, 0.6)
def _(rng):
    srv, t = rng.choice(["fs01", "srv-1c", "srv-files"]), rng.randint(2, 4)
    w, full = rng.randint(1, t - 1), rng.randint(400, 900)
    v = _variant(rng, 3)  # 0 — инкрементные, 1 — разностные, 2 — разностные с полной копией посреди недели
    rows, acc = [], 0
    for i, d in enumerate(DAYS):
        if v == 2 and i == w:
            acc = 0
            rows.append(f"{d} 23:00  {'полная':<13} {full + rng.randint(20, 60)} ГБ")
            continue
        step = rng.randint(6, 20)
        acc += step
        rows.append(f"{d} 23:00  {'инкрементная' if v == 0 else 'разностная':<13} {step if v == 0 else acc} ГБ")
    lines = [f"Задание «{srv}», хранилище nas01", f"Вс 23:00  {'полная':<13} {full} ГБ"] + rows
    opts, key = _options(rng, [f"Полную за Вс и все копии с Пн по {DAYS[t]} по порядку", f"Полную за Вс и только копию за {DAYS[t]}",
                               f"Полную за {DAYS[w]} и только копию за {DAYS[t]}"], v,
                         [f"Только копию за {DAYS[t]}: в ней уже есть все файлы на этот день",
                          f"Полную за Вс и копию за {DAYS[t - 1]}, остальное — из корзины пользователей"])
    return {"scene_title": "Цепочка копий", "story": f"Нужно восстановить {srv} на состояние вечера {DAYS[t]}. В хранилище — цепочка копий за неделю.",
            "prompt": "Какой наименьший набор копий нужен?", "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}


@family("adm_bak_ransom", SPEC, "Резервное копирование", "choice", 2.3, 2.0)
def _(rng):
    srv, full, keep = rng.choice(["fs01", "srv-files", "fs-main"]), rng.choice([1200, 1500, 1800]), rng.choice([7, 10])
    d0, k = rng.randint(1, 15), rng.choice([7, 8])
    x = [f"{d0 + i:02d}.10" for i in range(10)]
    v = _variant(rng, 3)  # 0 — шифровальщик, 1 — задание стало делать полные копии, 2 — дефрагментация раздувает блочный инкремент
    after = [lambda: rng.randint(280, 450), lambda: round(full * rng.uniform(0.97, 1.0)), lambda: rng.randint(150, 300)][v]
    inc = [rng.randint(4, 9) if i < k else after() for i in range(10)]
    files = [round(rng.uniform(140, 190), 1) if v == 0 and i >= k else round(rng.uniform(1.5, 4.0), 1) for i in range(10)]
    label = ["резкий рост", "задание перенесено на новый сервер копий", "включена дефрагментация по расписанию"][v]
    panel = {"type": "chart", "x": x, "marker": {"i": k, "label": label}, "series": [
        {"name": "инкрементная копия, ГБ", "axis": "left", "max": 2000 if v == 1 else 500, "data": inc},
        {"name": "изменённых файлов, тыс.", "axis": "right", "max": 200, "data": files},
    ]}
    opts, key = _options(rng, ["Массово изменились файлы: проверить сервер на шифровальщика и остановить ротацию, пока чистые копии не вытеснены",
                               "После переноса задание каждую ночь делает полную копию, хотя изменений мало: заново настроить цепочку инкрементов",
                               "Дефрагментация двигает блоки, и блочный инкремент считает их изменёнными: исключить том из дефрагментации"], v,
                         ["Сотрудники загрузили много новых файлов: расширить хранилище копий и увеличить срок хранения",
                          "Сломалась дедупликация хранилища: запустить её задание вручную и дождаться, пока копии сожмутся"])
    return {"scene_title": "Распухшие копии", "story": f"Ночные инкрементные копии {srv} обычно весят 4–9 ГБ, полная — около {full} ГБ. Последние ночи копии "
                                                       f"резко выросли. Хранятся последние {keep} копий, старые удаляются автоматически.",
            "prompt": "Что делать?", "panel": panel, "options": opts, "key": key}


def _num(v: float) -> str:
    return f"{v:g}".replace(".", ",")


@family("adm_bak_rto", SPEC, "Резервное копирование", "choice", 2.3, 2.7)
def _(rng):
    srv, rto = rng.choice(["fs01", "srv-files", "srv-1c"]), rng.choice([4, 6])
    v = _variant(rng, 3)  # 0 — канал медленный, облако раз в неделю; 1 — канал медленный, облако каждую ночь; 2 — канал быстрый, облако каждую ночь
    size, mbit = rng.choice([(0.5, 1000), (1, 1000), (1.5, 1000), (0.8, 500)] if v == 2 else [(1.5, 200), (2, 200), (2, 500), (3, 500), (4, 1000), (3, 300)])
    h = size * 8e6 / mbit / 3600  # ТБ → Мбит → ч; быстрый набор — до 3,6 ч (укладывается в RTO), медленный — от 8,9 ч
    nightly = v != 0
    lines = [f"План восстановления {srv}", f"RTO: {rto} ч, RPO: 24 ч", f"Объём данных {srv}: {_num(size)} ТБ",
             "Копия 1: NAS в серверной, каждую ночь, хранение 14 дней (SMB-ресурс, доменная учётка)",
             f"Копия 2: облачное хранилище, {'каждую ночь' if nightly else 'каждое воскресенье'}, хранение 8 недель", f"Канал офиса в интернет: {mbit} Мбит/с"]
    # ловушки: байты вместо битов в расчёте времени, «8 недель хранения» вместо частоты копий
    if h <= rto:
        rto_yes, rto_no = f"RTO — да: всё скачается примерно за {_num(round(h, 1))} ч", f"RTO — нет: скачивание займёт около {h * 8:.0f} ч"
    else:
        rto_yes, rto_no = f"RTO — да: всё скачается примерно за {_num(round(h / 8, 1))} ч", f"RTO — нет: скачивание займёт около {h:.0f} ч"
    if nightly:
        rpo_yes, rpo_no = "RPO — да: копии каждую ночь, потеряем не больше суток", f"RPO — нет: за {h:.0f} ч простоя потеряем больше суток работы"
    else:
        rpo_yes, rpo_no = "RPO — да: в облаке хранятся 8 недель копий, данные целы", "RPO — нет: копия недельная, пропадут изменения до 7 дней"
    opts, key = _options(rng, [f"{rto_no}; {rpo_no}", f"{rto_no}; {rpo_yes}", f"{rto_yes}; {rpo_yes}"], v, [f"{rto_yes}; {rpo_no}"])
    return {"scene_title": "Осталось облако", "story": f"Шифровальщик зашифровал {srv}, а заодно и NAS с копиями: тот был подключён по SMB под доменной учёткой. "
                                                       "Цела только облачная копия. Директор спрашивает, уложитесь ли в план.",
            "prompt": "Что ответить директору по RTO и RPO из плана?", "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}


# ============================== Серверы и ОС ==============================

MOUNTS = [("/srv", "/srv/1c/bases/ut11"), ("/var/lib/pgsql", "/var/lib/pgsql/16/data/base"), ("/opt/backup", "/opt/backup/daily"),
          ("/home", "/home/share/scan")]


@family("adm_srv_df", SPEC, "Серверы и ОС", "mark", 2.1, -1.3)
def _(rng):
    v = _variant(rng, 3)  # 0 — кончилось место, 1 — кончились иноды, 2 — том не смонтировался, запись идёт в корень
    # без тома каталог под /var лёг бы на раздел /var, а не в корень — для v2 берём только точки монтирования вне /var
    host, (mnt, path) = rng.choice(["srv-1c", "db01", "srv-app", "fs-linux"]), rng.choice([m for m in MOUNTS if v != 2 or not m[0].startswith("/var")])
    lv = "/dev/mapper/vg0-" + mnt.strip("/").replace("/", "_")
    size = rng.choice([100, 200, 500])
    pct = rng.randint(35, 60)
    root = ("/dev/sda2", "20G", "20G" if v == 2 else f"{rng.randint(16, 18)}G", "100%" if v == 2 else f"{rng.randint(80, 91)}%", "/")
    rows = [("/dev/sda1", "976M", "941M", f"{rng.randint(96, 98)}%", "/boot"),
            ("/dev/mapper/vg0-var", "30G", f"{rng.randint(8, 14)}G", f"{rng.randint(30, 50)}%", "/var"),
            ("tmpfs", "3.9G", "0", "0%", "/dev/shm")]
    if v != 2:
        rows.append((lv, f"{size}G", f"{size}G" if v == 0 else f"{size * pct // 100}G", "100%" if v == 0 else f"{pct}%", mnt))
    rng.shuffle(rows)
    fmt = lambda fs, s, u, p, m: f"{fs:<28}{s:>9}{u:>9}{p:>6}  {m}"  # noqa: E731
    head = ["$ df -h", fmt("Filesystem", "Size", "Used", "Use%", "Mounted on")] + [fmt(*r) for r in [root] + rows]
    irows = [("/dev/sda2", "1310720", str(rng.randint(90000, 200000)), f"{rng.randint(7, 15)}%", "/"),
             ("/dev/mapper/vg0-var", "1966080", str(rng.randint(30000, 90000)), f"{rng.randint(2, 5)}%", "/var")]
    if v != 2:
        ino = size * 65536
        irows.append((lv, str(ino), str(ino if v == 1 else rng.randint(ino // 100, ino // 20)), "100%" if v == 1 else f"{rng.randint(1, 5)}%", mnt))
    lines = head + ["$ df -i", fmt("Filesystem", "Inodes", "IUsed", "IUse%", "Mounted on")] + [fmt(*r) for r in irows]
    target = fmt(*root) if v == 2 else fmt(*irows[-1]) if v == 1 else next(ln for ln in head if ln.endswith(f"  {mnt}"))
    key = lines.index(target) + 1
    return {"scene_title": "Нет места", "story": f"Ночью {host} перезагрузили после обновлений, и теперь служба не может сохранять данные: «No space left on device» при записи в {path}.",
            "prompt": "Нажмите на строку, которая объясняет ошибку.", "panel": {"type": "code", "lang": "bash", "lines": lines}, "key": key}


@family("adm_srv_deleted", SPEC, "Серверы и ОС", "choice", 2.2, 0.8)
def _(rng):
    host, app = rng.choice(["srv-app", "srv-1c", "web01"]), rng.choice(["nginx", "tomcat", "rabbitmq", "srv1cv8"])
    total = rng.choice([40, 50, 80])
    big = total - rng.randint(10, 18)
    v = _variant(rng, 3)  # 0 — файл держит открытым служба, 1 — файл остался в снимках btrfs, 2 — лог лежал на отдельном разделе
    head = [f"$ sudo du -sh /var/log/{app}/*.log", f"{big}G   /var/log/{app}/{app}.log", f"$ sudo rm /var/log/{app}/{app}.log"]
    fs, dev = ("btrfs", "/dev/sdb1") if v == 1 else ("ext4", "/dev/mapper/vg0-var")
    df = ["$ df -hT /var", f"{dev}  {fs}  {total}G  {total}G  0  100% /var"]
    lsof = ["$ sudo lsof +L1 /var", "COMMAND   PID   USER  FD  SIZE/OFF  NLINK  NAME"]
    if v == 0:
        lines = head + df + lsof + [f"{app[:8]:<9} {rng.randint(800, 9000)}  {app[:5]:<5} {rng.randint(3, 9)}w  {big}G  0  /var/log/{app}/{app}.log (deleted)"]
    elif v == 1:  # /var/log на том же разделе, что и /var — отдельный раздел логов исключён панелью
        lines = head + ["$ df -hT /var /var/log", df[1], df[1]] + lsof + ["(пусто)", "$ sudo snapper -c var list | tail -3"] + [
            f"{n} | single | {d:02d}.10 03:00 | timeline" for n, d in zip(range(41, 44), range(rng.randint(1, 20), 30))]
    else:
        logsz, used = rng.choice([60, 100]) if big <= 45 else 100, rng.randint(5, 15)  # удалённый лог должен был помещаться на раздел
        avail = logsz * 95 // 100 - used  # 5 % ext4 резервирует под root
        lines = head + ["$ df -hT /var /var/log", f"{dev}  {fs}  {total}G  {total}G  0  100% /var",
                        f"/dev/mapper/vg0-log  ext4  {logsz}G  {used}G  {avail}G  {-(-100 * used // (used + avail))}% /var/log"] + lsof + ["(пусто)"]
    opts, key = _options(rng, [f"Файл удалён, но {app} держит его открытым: место вернётся после перезапуска службы",
                               "Файл остался в снимках файловой системы: место вернётся, когда удалят снимки с ним",
                               "Лог лежал на отдельном разделе /var/log: место освободилось там, а /var занят другим"], v,
                         ["Файловой системе нужно время: место освобождается фоновым процессом за несколько часов",
                          "На разделе закончились иноды: удалить мелкие файлы во /var/spool и /var/tmp"])
    return {"scene_title": "Место не вернулось", "story": f"На {host} кончилось место во /var. Вы удалили огромный лог {app}, но df всё ещё показывает 100 %.",
            "prompt": "Почему место не освободилось?", "panel": {"type": "code", "lang": "bash", "lines": lines}, "options": opts, "key": key}


@family("adm_srv_raid", SPEC, "Серверы и ОС", "choice", 2.3, 2.1)
def _(rng):
    host, size, hrs, days = rng.choice(["srv-1c", "fs01", "db01"]), rng.choice([4, 8, 12]), rng.choice([18, 24, 36]), rng.randint(5, 12)
    failed, weak = rng.sample(["sda", "sdb", "sdc", "sdd"], 2)
    m, pend = rng.randint(10, 40), rng.randint(24, 180)
    v = _variant(rng, 3)  # 0 — у второго диска нечитаемые сектора, копия старая; 1 — остальные диски здоровы, копия свежая; 2 — выпал второй диск
    lines = [_log(f"07:{m:02d}:12", "kernel", "ERROR", f"md/raid:md0: Disk failure on {failed}1, disabling device. Operation continuing on 3 devices"),
             _log(f"07:{m:02d}:13", "mdadm", "WARN", "DegradedArray event detected on md device /dev/md0 (raid5, 4 devices)")]
    if v == 0:
        lines += [_log(f"07:{m + 2:02d}:40", "smartd", "WARN", f"Device /dev/{weak} [SAT]: {pend} Currently unreadable (pending) sectors"),
                  _log(f"07:{m + 2:02d}:41", "smartd", "WARN", f"Device /dev/{weak} [SAT]: SMART Usage Attribute: 5 Reallocated_Sector_Ct changed from 100 to 97"),
                  _log(f"07:{m + 3:02d}:05", "backup", "INFO", f"последнее успешное задание {host}: {days} дн. назад")]
    elif v == 1:
        lines += [_log(f"07:{m + 2:02d}:40", "smartd", "INFO", "Devices /dev/" + ", /dev/".join(sorted({"sda", "sdb", "sdc", "sdd"} - {failed}))
                       + ": SMART overall-health PASSED, 0 pending sectors"),
                  _log(f"07:{m + 3:02d}:05", "backup", "INFO", f"последнее успешное задание {host}: сегодня в 02:{rng.randint(0, 59):02d}")]
    else:
        lines += [_log(f"07:{m + 2:02d}:40", "kernel", "ERROR", f"md/raid:md0: Disk failure on {weak}1, disabling device"),
                  _log(f"07:{m + 2:02d}:41", "kernel", "ERROR", "md/raid:md0: not enough operational devices (2/4 failed); md0: raid5 inactive"),
                  _log(f"07:{m + 3:02d}:05", "backup", "INFO", f"последнее успешное задание {host}: сегодня в 02:{rng.randint(0, 59):02d}")]
    opts, key = _options(rng, [f"Пока массив жив, снять свежую копию данных: при ребилде нечитаемые сектора {weak} могут погубить массив",
                               "Срочного ничего нет: копия свежая, остальные диски здоровы — дождаться замены и запустить ребилд",
                               f"Массив уже потерян — выпал и {weak}: не собирать его силой, а восстановить данные из копии на новые диски"], v,
                         [f"Сначала заменить {weak} на запасной диск, а {failed} — когда привезут: два ребилда подряд безопаснее одного",
                          "Запустить fsck на /dev/md0, чтобы найти и исправить повреждённые сектора до начала ребилда"])
    return {"scene_title": "Вылетел диск", "story": f"На {host} в RAID 5 из четырёх дисков по {size} ТБ вылетел диск. Замену привезут через {hrs} ч.",
            "prompt": "Что сделать прямо сейчас?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# ============================== Работа с обращениями ==============================

LOW = [("генеральный директор", "второй монитор иногда мерцает, просит заменить"), ("бухгалтер", "нужна новая мышь, колёсико заедает"),
       ("менеджер отдела продаж", "установить на ноутбук программу для видеозвонков"), ("новый сотрудник", "добавить в почтовую рассылку отдела"),
       ("юрист", "поменять фон рабочего стола на корпоративный"), ("секретарь", "заказать картридж впрок, текущий заканчивается через неделю")]
HIGH = [("касса магазина №{k}", "не пробиваются чеки, у кассы очередь покупателей"), ("отдел продаж ({k} чел.)", "ни у кого не открывается CRM"),
        ("склад", "не печатаются накладные, {k} машин ждут отгрузки")]
SEC = [("бухгалтер", "открыл вложение из письма «от налоговой», теперь файлы на диске не открываются"),
       ("менеджер отдела продаж", "ввёл логин и пароль на странице из письма «смена пароля почты»"),
       ("секретарь", "на ПК сам двигается курсор и открываются окна, хотя никто не подключался по заявке")]
OVERDUE = [("отдел кадров", "не сканирует МФУ в кабинете, пока сканируют на соседнем"), ("юрист", "не открываются вложения .p7s в почте"),
           ("бухгалтер", "1С выдаёт ошибку при печати накладных, печатают из PDF")]


@family("adm_tkt_queue", SPEC, "Работа с обращениями", "mark", 2.1, -1.0)
def _(rng):
    k = rng.randint(3, 12)
    v = _variant(rng, 3)  # 0 — встал бизнес-процесс, 1 — инцидент безопасности, 2 — у мелкого обращения сейчас истечёт SLA
    if v == 0:
        who, what = rng.choice(HIGH)
        hot = (who.format(k=k), what.format(k=k))
    elif v == 1:
        hot = rng.choice(SEC)
    else:
        who, what = rng.choice(OVERDUE)
        hot = (who, f"{what} — P2, перенесено с пятницы, срок по SLA: сегодня 08:{rng.randint(30, 45)}")
    tickets = [(*hot, True)] + [(w, t, False) for w, t in rng.sample(LOW, rng.randint(3, 4))]
    rng.shuffle(tickets)
    times = sorted(f"08:{rng.randint(0, 19):02d}" for _ in tickets)
    lines = ["№ | создано | от кого | суть"]
    for (w, t, h), tm in zip(tickets, times):
        lines.append(f"INC-{rng.randint(1000, 9999)} | {f'Пт 17:{rng.randint(10, 50)}' if h and v == 2 else tm} | {w} | {t}")
        if h:
            key = len(lines)
    return {"scene_title": "Очередь с утра", "story": "08:20, в очереди первой линии несколько обращений, а вы на смене один.",
            "prompt": "Нажмите на обращение, которое нужно взять первым.", "panel": {"type": "code", "lang": "text", "lines": lines}, "key": key}


WEEK = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def _add_work(day: int, minute: int, mins: int, workdays: int, off: tuple = ()) -> tuple[int, int]:
    """Прибавить mins рабочих минут (09:00–18:00, рабочие дни — первые workdays дней недели, кроме праздников off)."""
    while True:
        if day % 7 < workdays and day not in off and 540 <= minute < 1080:
            if mins <= 1080 - minute:
                return day, minute + mins
            mins -= 1080 - minute
        day, minute = day + 1, 540


def _fmt(day: int, minute: int) -> str:
    return f"{WEEK[day % 7]}, {minute // 60:02d}:{minute % 60:02d}"


@family("adm_tkt_sla", SPEC, "Работа с обращениями", "choice", 2.2, 0.5)
def _(rng):
    sla = {"P1": 4, "P2": 8, "P3": 16}
    v = _variant(rng, 3)  # 0 — срок в рабочих часах, 1 — P1 идёт круглосуточно, 2 — на следующий день праздник
    while True:
        prio, day, minute = "P1" if v == 1 else rng.choice(["P2", "P3"]), rng.choice([1, 2, 3]), rng.choice(range(14 * 60, 17 * 60 + 31, 30))
        mins, hol = sla[prio] * 60, day + 1
        cal = day * 1440 + minute + mins
        rights = [_fmt(*_add_work(day, minute, mins, 5)), _fmt(cal // 1440, cal % 1440), _fmt(*_add_work(day, minute, mins, 5, (hol,)))]
        wrong = [_fmt(*_add_work(day + 1, 540, mins, 5))]
        if len({*rights, *wrong}) == 4:
            break
    topic = rng.choice(["не работает сканер в бухгалтерии", "не синхронизируется почта на телефоне", "ошибка при выгрузке отчёта из 1С"])
    lines = ["Регламент поддержки: рабочие часы Пн–Пт 09:00–18:00; срок P2 и P3 идёт только в рабочие часы",
             "P1 — реакция 15 мин, решение 4 ч, круглосуточно", "P2 — реакция 30 мин, решение 8 ч", "P3 — реакция 2 ч, решение 16 ч"]
    if v == 2:
        lines.append(f"{WEEK[hol]} на этой неделе — праздничный день, поддержка не работает")
    lines += ["", f"INC-{rng.randint(1000, 9999)}: приоритет {prio}, создано {_fmt(day, minute)}, «{topic}»"]
    opts, key = _options(rng, rights, v, wrong)
    return {"scene_title": "Срок по SLA", "story": "Руководитель поддержки просит указать в обращении срок решения.",
            "prompt": "Когда истекает срок решения по SLA?", "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}


@family("adm_tkt_mass", SPEC, "Работа с обращениями", "choice", 2.3, 1.8)
def _(rng):
    floor, other, m = rng.sample(range(2, 7), 2) + [rng.randint(5, 30)]
    sym = rng.sample(["не открывается 1С", "не печатает принтер", "долго грузится портал", "письма висят в исходящих", "отключается телефония"], 4)
    rooms = rng.sample(range(1, 30), 4)
    floors = rng.sample(range(2, 7), 3)
    rm = f"{floors[1]}{rooms[1]:02d}"
    inc = lambda: f"INC-{rng.randint(1000, 9999)}"  # noqa: E731
    pwd = _log(f"09:{m + 2:02d}", "helpdesk", "INFO", f"{inc()} каб. {other}{rooms[3]:02d}: «забыл пароль» — L1: сброшен, решено")
    v = _variant(rng, 3)  # 0 — сбой коммутатора этажа, 1 — повторяющийся сбой одного ПК, 2 — сбой сервера 1С у всех этажей
    if v == 0:
        lines = [_log(f"09:{m + 4 * i:02d}", "helpdesk", "INFO", f"{inc()} каб. {floor}{r:02d}: «{s}» — L1: перезагрузили ПК, решено")
                 for i, (r, s) in enumerate(zip(rooms[:3], sym[:3]))]
        lines.insert(rng.randint(1, 3), pwd)
        lines.append(_log(f"09:{m + 13:02d}", "monitoring", "WARN", f"sw-floor{floor}: uplink Gi1/0/49 — {rng.randint(3, 9)} % пакетов с ошибками CRC"))
    elif v == 1:
        lines = [_log(f"09:{m + 4 * i:02d}", "helpdesk", "INFO", f"{inc()} каб. {f}{r:02d}: «{s}» — L1: перезагрузили ПК, решено")
                 for i, (f, r, s) in enumerate(zip(floors, rooms[:3], sym[:3]))]
        lines.insert(rng.randint(1, 3), pwd)
        lines += [_log(f"09:{m + 13:02d}", "helpdesk", "INFO", f"каб. {rm}: третье обращение с этого ПК за неделю, каждый раз — перезагрузка"),
                  _log(f"09:{m + 15:02d}", "monitoring", "WARN", f"PC-{rm}: WHEA-Logger 19, исправленных ошибок памяти за сутки: {rng.randint(120, 400)}")]
    else:
        lines = [_log(f"09:{m + 4 * i:02d}", "helpdesk", "INFO", f"{inc()} каб. {f}{r:02d}: «не открывается 1С» — L1: перезагрузили ПК, решено")
                 for i, (f, r) in enumerate(zip(floors, rooms[:3]))]
        lines.insert(rng.randint(1, 3), pwd)
        lines.append(_log(f"09:{m + 13:02d}", "monitoring", "WARN", f"srv-1c: перезапусков агента сервера 1С за час: {rng.randint(3, 6)}, rphost: out of memory"))
    lines.sort(key=lambda ln: ln["t"])
    opts, key = _options(rng, [f"Это один сбой на {floor}-м этаже: завести массовый инцидент, привязать обращения и проверить sw-floor{floor}",
                               f"Сбой повторяется на одном ПК в каб. {rm}: завести проблему и искать причину в нём, а не перезагружать",
                               "Это сбой сервера 1С, а не ПК: завести массовый инцидент, привязать обращения и разбираться с srv-1c"], v,
                         ["Разослать всем сотрудникам инструкцию: перед обращением в поддержку перезагружать компьютер самостоятельно",
                          "Эскалировать каждое обращение на L3 отдельно: перезагрузки на L1 только маскируют настоящие причины сбоев"])
    return {"scene_title": "Перезагрузили — решено", "story": "Первая линия закрыла несколько обращений одной и той же перезагрузкой. Вы разбираете журнал смены.",
            "prompt": "Что делать?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}
