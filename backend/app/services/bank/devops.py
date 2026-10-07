"""DevOps / SRE, сюжет «Миграция в облако»: сценарные семейства с логами, графиками и манифестами (по 3 на компетенцию).
У каждого семейства три варианта механики (items._variant), правильные ответы других вариантов — среди дистракторов."""

from app.services.items import _log, _options, _variant, family

SPEC = "DevOps / SRE"
SVCS = ["billing", "orders", "reports", "catalog", "checkout", "profile"]


def _v(rng) -> str:
    return f"{rng.randint(1, 4)}.{rng.randint(10, 40)}.{rng.randint(0, 9)}"


# --- Диагностика инцидентов ---


@family("ops_inc_x509", SPEC, "Диагностика инцидентов", "choice", 2.2, 0.3)
def _(rng):
    svc, ver = rng.choice(SVCS), _v(rng)
    legacy = rng.choice(["ledger.dc1.internal", "erp.dc1.internal", "ldap.corp.local", "crm.dc1.internal"])
    base = rng.choice(["python:3.12-slim", "gcr.io/distroless/base", "alpine:3.20", "eclipse-temurin:21-jre"])
    m = rng.randint(10, 50)
    v = _variant(rng, 3)
    short = legacy.split(".")[0]
    alias = f"{short}.dc1.internal" if legacy.endswith(".corp.local") else f"{short}.corp.local"  # имя из сертификата ≠ имени, по которому ходят
    err, vm = [(f"GET https://{legacy}/api/v2/accounts: x509: certificate signed by unknown authority",
                f"curl https://{legacy}/api/v2/health from old VM: HTTP/1.1 200 OK"),
               (f"GET https://{legacy}/api/v2/accounts: x509: certificate has expired or is not yet valid: current time is after 2026-10-0{rng.randint(1, 4)}T00:00:00Z",
                f"curl https://{legacy}/api/v2/health from old VM: SSL certificate problem: certificate has expired"),
               (f"GET https://{legacy}/api/v2/accounts: x509: certificate is valid for {alias}, not {legacy}",
                f"curl https://{alias}/api/v2/health from old VM (старый конфиг): HTTP/1.1 200 OK")][v]
    lines = [
        _log(f"23:{m:02d}:01", "argocd", "INFO", f"sync {svc}: image {svc}:{ver} (base {base})"),
        _log(f"23:{m:02d}:14", svc, "INFO", "connected to postgres (managed, TLS)"),
        _log(f"23:{m:02d}:15", svc, "ERROR", err),
        _log(f"23:{m:02d}:15", svc, "WARN", "retry 1/3 in 2s"),
        _log(f"23:{m:02d}:22", svc, "ERROR", err),
        _log(f"23:{m:02d}:40", "debug-vm", "INFO", vm),
    ]
    opts, key = _options(rng, ["В новом образе нет корневого сертификата старого ЦОДа: добавить корпоративный CA в trust store",
                               f"Сертификат {legacy} истёк: перевыпустить его и поставить алерт на срок действия",
                               "В облаке ходят по имени, которого нет в сертификате: использовать имя из сертификата или перевыпустить с нужным SAN"], v,
                         ["Облачный файрвол режет исходящий HTTPS в старый ЦОД: открыть 443 в egress-правилах кластера",
                          "В облаке другой часовой пояс, и для подов сертификат ещё «не начал действовать» по времени"])
    return {"scene_title": "Чужой сертификат", "story": f"Сервис {svc} переехал в облако на базовый образ {base}. Запросы к {legacy} в старом ЦОДе падают с ошибкой TLS.",
            "prompt": "В чём причина?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("ops_inc_throttle", SPEC, "Диагностика инцидентов", "choice", 2.3, 1.2)
def _(rng):
    svc = rng.choice(SVCS)
    m0, at = rng.randint(0, 20), rng.randint(2, 4)
    x = [f"00:{m0 + 5 * i:02d}" for i in range(8)]
    p99 = [rng.randint(100, 140) if i < at else rng.randint(600, 1300) for i in range(8)]
    use = rng.randint(35, 55)
    v = _variant(rng, 3)
    mark, name, mx, data = [("limits.cpu: 1", "периоды с троттлингом CPU, %", 100, [rng.randint(0, 3) if i < at else rng.randint(40, 75) for i in range(8)]),
                            ("limits.memory: 512Mi", "время в паузах GC, мс в секунду", 1000, [rng.randint(5, 20) if i < at else rng.randint(350, 700) for i in range(8)]),
                            ("переезд на пул spot-узлов", "steal time узлов, %", 100, [rng.randint(0, 2) if i < at else rng.randint(25, 45) for i in range(8)])][v]
    panel = {"type": "chart", "x": x, "marker": {"i": at, "label": mark}, "series": [
        {"name": f"p99 {svc}, мс", "axis": "left", "max": 1500, "data": p99}, {"name": name, "axis": "right", "max": mx, "data": data}]}
    opts, key = _options(rng, ["CFS-троттлинг: потоки выбирают квоту CPU в начале периода и ждут его конца, хотя в среднем загрузка низкая",
                               "Лимит памяти впритык к рабочему набору: сборщик мусора работает почти непрерывно — поднять лимит или настроить кучу",
                               "Соседние ВМ забирают процессорное время узла (высокий steal): сменить тип узлов"], v,
                         ["После переезда выросла сетевая задержка между зонами доступности, и p99 вырос вместе с ней",
                          "Вырос входящий трафик: добавить реплики и поднять лимиты CPU"])
    return {"scene_title": "Медленно без нагрузки", "story": f"В облачном кластере p99 {svc} вырос в разы, хотя средняя загрузка CPU — {use} % лимита, а трафик прежний.",
            "prompt": "Что происходит?", "panel": panel, "options": opts, "key": key}


@family("ops_inc_clock", SPEC, "Диагностика инцидентов", "choice", 2.3, 1.9)
def _(rng):
    m, skew = rng.randint(10, 50), rng.randint(40, 180)
    nodes = [f"pool-b-{rng.randint(100, 999)}" for _ in range(2)]
    v = _variant(rng, 3)
    if v == 0:
        story = "Через два часа после переезда части подов на новый пул узлов auth-gw начал отклонять токены. Ошибки — только для подов на pool-b."
        lines = [_log(f"01:{m:02d}:00", "netops", "INFO", "egress policy applied to pool-b: allow tcp/443, tcp/5432, tcp/6379"),
                 _log(f"01:{m:02d}:05", "scheduler", "INFO", "pool-b ready: 6 nodes, pods migrating from pool-a"),
                 _log(f"03:{m:02d}:12", "auth-gw", "ERROR", f"token rejected: iat is in the future (skew {skew}s) issuer=auth node={nodes[0]}"),
                 _log(f"03:{m:02d}:12", "auth-gw", "INFO", "token accepted issuer=auth node=pool-a-412"),
                 _log(f"03:{m:02d}:15", "auth-gw", "ERROR", f"token rejected: iat is in the future (skew {skew + rng.randint(1, 4)}s) issuer=auth node={nodes[1]}")]
    elif v == 1:
        story = "Через час после плановой ротации ключа подписи auth-gw начал отклонять часть токенов на всех узлах."
        lines = [_log(f"01:{m:02d}:00", "auth", "INFO", "signing key rotated: kid=k8 active, kid=k7 retired"),
                 _log(f"01:{m:02d}:30", "auth-gw", "ERROR", "token rejected: unknown kid=k8 (jwks cache: k6, k7, refreshed 22h ago, ttl 24h)"),
                 _log(f"01:{m:02d}:31", "auth-gw", "INFO", "token accepted kid=k7 (issued before rotation)"),
                 _log(f"01:{m + 5:02d}:02", "auth-gw", "ERROR", "token rejected: unknown kid=k8")]
    else:
        story = "В вечерний пик auth-gw начал отклонять часть токенов на всех узлах; днём ошибок нет."
        lines = [_log(f"19:{m:02d}:00", "auth", "INFO", "access token ttl = 30s"),
                 _log(f"19:{m:02d}:12", "auth-gw", "WARN", f"queue wait p99 {rng.randint(28, 45)}s (пик)"),
                 _log(f"19:{m:02d}:13", "auth-gw", "ERROR", f"token rejected: exp in the past by {rng.randint(1, 15)}s, clock ok (chrony offset 2ms)"),
                 _log(f"19:{m:02d}:14", "auth-gw", "INFO", "token accepted (queue wait 0.3s)")]
    opts, key = _options(rng, ["Часы узлов pool-b уплыли: egress пропускает только TCP, и NTP (UDP 123) до серверов времени не доходит",
                               "auth-gw держит старый набор ключей в кэше: перечитывать JWKS при неизвестном kid и публиковать ключ заранее",
                               "Срок жизни токена меньше времени в очереди в пик: увеличить срок и добавить небольшой допуск по времени"], v,
                         ["На узлах другой часовой пояс, и iat сравнивается с местным временем: выставить TZ=UTC в контейнерах",
                          "Сертификат auth-gw истёк: клиенты не могут установить TLS"])
    return {"scene_title": "Отклонённые токены", "story": story, "prompt": "В чём причина?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# --- Сети ---


@family("ops_net_bind", SPEC, "Сети", "choice", 2.1, -1.3)
def _(rng):
    svc, port = rng.choice(SVCS), rng.choice([8000, 8080, 9000, 3000])
    proc = rng.choice(["uvicorn", "node", "java", "gunicorn"])
    ip = f"10.42.{rng.randint(1, 9)}.{rng.randint(10, 250)}"
    v = _variant(rng, 3)
    lines = [f"$ kubectl exec deploy/{svc} -- ss -ltnp", "State   Recv-Q  Send-Q  Local Address:Port   Peer Address:Port  Process",
             f'LISTEN  0       4096    {"127.0.0.1" if v == 0 else "0.0.0.0"}:{port}       0.0.0.0:*          users:(("{proc}",pid=1,fd=7))']
    if v == 1:
        lines += [f"$ kubectl get networkpolicy -n {svc}", "NAME                   POD-SELECTOR   AGE", "default-deny-ingress   <none>         2d"]
    if v == 2:
        lines += [f"$ kubectl get peerauthentication -n {svc}", "NAME      MODE     AGE", "default   STRICT   2d"]
    lines.append(f"$ kubectl exec deploy/debug -- curl -s {ip}:{port}/health")
    lines.append([f"curl: (7) Failed to connect to {ip} port {port}: Connection refused", f"curl: (28) Failed to connect to {ip} port {port}: Timed out",
                  "curl: (56) Recv failure: Connection reset by peer"][v])
    opts, key = _options(rng, ["Приложение слушает только 127.0.0.1 внутри контейнера: нужно слушать 0.0.0.0",
                               "NetworkPolicy запрещает входящий трафик к поду: добавить разрешающее правило для клиентов",
                               "В namespace строгий mTLS сервис-меша: клиент без сайдкара не проходит, проверять из пода с сайдкаром"], v,
                         [f"Порт {port} внутри контейнера уже занят другим процессом, и запрос уходит не туда",
                          f"Процессу без root нельзя открывать порт {port}, поэтому сокет на нём не создан"])
    return {"scene_title": "Под недоступен", "story": f"Под {svc} в статусе Running, в логе «listening on port {port}». Из соседнего пода по IP он недоступен.",
            "prompt": "В чём дело?", "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}


@family("ops_net_mtu", SPEC, "Сети", "choice", 2.3, 1.3)
def _(rng):
    host = rng.choice(["erp.dc1.internal", "files.dc1.internal", "reports.dc1.internal"])
    ip = f"172.{rng.randint(16, 31)}.{rng.randint(0, 255)}.{rng.randint(2, 250)}"
    ok = rng.choice([1350, 1372, 1400])
    v = _variant(rng, 3)
    if v == 0:
        story = f"Короткие запросы к {host} проходят, большие ответы зависают."
        lines = [f"$ curl -s -o /dev/null -w '%{{http_code}} %{{size_download}}' https://{host}/ping", f"200 {rng.randint(2, 40)}",
                 f"$ curl -s -o /dev/null -w '%{{http_code}} %{{size_download}}' https://{host}/export?limit={rng.choice([500, 1000, 5000])}",
                 "(нет ответа 60 с) curl: (28) Operation timed out", f"$ ping -M do -c 3 -s 1472 {ip}", "3 packets transmitted, 0 received, 100% packet loss",
                 f"$ ping -M do -c 3 -s {ok} {ip}", "3 packets transmitted, 3 received, 0% packet loss"]
    elif v == 1:
        idle = rng.choice([300, 350, 600])
        story = f"Запросы к {host} проходят, но после затишья первый запрос из пула соединений висит до таймаута, следующие — нормально."
        lines = ["$ grep -c 'Connection reset' app.log  # за сутки", f"{rng.randint(40, 90)}",
                 "$ grep 'Connection reset' app.log | head -2", f"pool conn idle {idle + rng.randint(2, 30)}s → POST /api/sync: Connection reset by peer",
                 f"pool conn idle {idle + rng.randint(2, 30)}s → GET /api/items: Connection reset by peer",
                 "$ vpn-gw show session-timeout", f"tcp idle timeout: {idle}s", "$ grep keepalive client.yaml", "pool_idle_timeout: 900s, tcp_keepalive: off"]
    else:
        story = f"Запросы из облака к {host} не проходят совсем, со старых ВМ всё работает."
        lines = [f"$ kubectl exec deploy/debug -- nslookup {host}", f"Address: 203.0.113.{rng.randint(10, 250)}   # публичный адрес из облачного DNS",
                 f"$ (старая ВМ) nslookup {host}", f"Address: {ip}", f"$ kubectl exec deploy/debug -- curl -m 5 https://{ip}/ping -H 'Host: {host}'", "200 OK"]
    opts, key = _options(rng, ["MTU туннеля меньше 1500, а ICMP «нужна фрагментация» теряется: включить MSS clamping",
                               "Шлюз рвёт простаивающие соединения раньше, чем их закрывает пул: включить TCP keepalive или укоротить простой в пуле",
                               f"В облаке {host} резолвится в публичный адрес: настроить пересылку DNS-зоны dc1.internal на DNS старого ЦОДа"], v,
                         [f"{host} долго формирует ответы: поднять таймауты клиента и балансировщика до 5 минут",
                          "В канале теряются пакеты: включить на туннеле повторную передачу и коррекцию ошибок"])
    return {"scene_title": "Через туннель", "story": f"Между облаком и старым ЦОДом подняли VPN-туннель. {story}",
            "prompt": "Что происходит и как исправить?", "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}


@family("ops_net_snat", SPEC, "Сети", "choice", 2.3, 2.2)
def _(rng):
    svc = rng.choice(["payments-gw", "notify", "partner-sync"])
    dst = f"203.0.113.{rng.randint(10, 250)}"
    m, rps = rng.randint(10, 50), rng.randint(900, 2500)
    v = _variant(rng, 3)
    if v == 0:
        lines = [_log(f"19:{m:02d}:00", svc, "INFO", f"outgoing {rps} rps to partner api, http client keep_alive=false"),
                 _log(f"19:{m:02d}:04", svc, "ERROR", f"dial tcp {dst}:443: i/o timeout"),
                 _log(f"19:{m:02d}:04", "nat-gw-1", "WARN", f"port allocation failed for {dst}:443: 64512/64512 in use"),
                 _log(f"19:{m:02d}:05", svc, "INFO", "POST /v1/notify 200 (84 ms)"),
                 _log(f"19:{m:02d}:30", "nat-gw-1", "INFO", "bandwidth 180 Mbit/s of 5 Gbit/s")]
    elif v == 1:
        lines = [_log(f"19:{m:02d}:00", svc, "INFO", f"outgoing {rps} rps to partner api, keep_alive=true, pool 50"),
                 _log(f"19:{m:02d}:04", svc, "ERROR", "POST /v1/notify 429 Too Many Requests, Retry-After: 2"),
                 _log(f"19:{m:02d}:04", svc, "WARN", "retry immediately (attempt 2/5)"),
                 _log(f"19:{m:02d}:05", svc, "INFO", f"partner headers: X-RateLimit-Limit: {rps // 2}, X-RateLimit-Remaining: 0"),
                 _log(f"19:{m:02d}:30", "nat-gw-1", "INFO", "ports in use 800/64512, bandwidth 90 Mbit/s of 5 Gbit/s")]
    else:
        v6 = f"2001:db8::{rng.randint(10, 99)}"
        lines = [_log(f"19:{m:02d}:00", svc, "INFO", f"resolve partner api: {dst}, {v6}"),
                 _log(f"19:{m:02d}:04", svc, "ERROR", f"dial tcp [{v6}]:443: connect: network is unreachable"),
                 _log(f"19:{m:02d}:05", svc, "INFO", f"dial tcp {dst}:443: ok, POST /v1/notify 200 (84 ms)"),
                 _log(f"19:{m:02d}:30", "netops", "INFO", "cluster egress: IPv4 only")]
    opts, key = _options(rng, ["Кончились SNAT-порты NAT-шлюза к одному адресу: включить keep-alive и пул соединений",
                               "Партнёр ограничивает частоту: держать темп в пределах лимита и повторять по Retry-After, а не сразу",
                               "Клиент пробует IPv6, которого нет на выходе из кластера: предпочитать IPv4 или включить Happy Eyeballs"], v,
                         ["NAT-шлюзу не хватает пропускной способности в пик: взять тип шлюза побольше",
                          "DNS партнёра иногда отдаёт недоступный адрес: закрепить рабочий IP в /etc/hosts подов"])
    return {"scene_title": "Ошибки на выходе", "story": f"После переезда {svc} ходит к партнёру через облачный NAT-шлюз. В вечерний пик часть запросов падает.",
            "prompt": "В чём причина?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# --- Kubernetes ---


TYPO = {"payments": "payment", "checkout": "chekout", "catalog": "catalogue", "profile": "profiles", "orders": "order"}


@family("ops_k8s_selector", SPEC, "Kubernetes", "mark", 2.2, -1.5)
def _(rng):
    svc = rng.choice(list(TYPO))
    port = rng.choice([8000, 8080])
    v = _variant(rng, 3)
    lines = ["apiVersion: apps/v1", "kind: Deployment", "metadata:", f"  name: {svc}", "  namespace: prod", "spec:", f"  replicas: {rng.randint(2, 4)}",
             "  selector:", "    matchLabels:", f"      app: {svc}", "  template:", "    metadata:", "      labels:", f"        app: {svc}", "    spec:",
             "      containers:", f"        - name: {svc}", f"          ports: [{{containerPort: {port}}}]",
             "---", "apiVersion: v1", "kind: Service", "metadata:", f"  name: {svc}"]
    lines.append("  namespace: default" if v == 2 else "  namespace: prod")
    key = len(lines)
    if rng.random() < 0.5:
        lines += ["  annotations:", f"    owner: team-{rng.choice(['core', 'platform', 'growth'])}"]
    lines += ["spec:", "  selector:", f"    app: {TYPO[svc] if v == 0 else svc}"]
    if v == 0:
        key = len(lines)
    lines += ["  ports:", "    - port: 80", f"      targetPort: {port + 1 if v == 1 else port}"]
    if v == 1:
        key = len(lines)
    story = [f"После переноса манифестов сервис {svc} не получает трафик: kubectl get endpoints {svc} пуст, а все поды Running и Ready.",
             f"После переноса манифестов запросы к сервису {svc} получают Connection refused, хотя endpoints заполнены и поды Ready.",
             f"После переноса манифестов приложения в namespace prod не могут достучаться до {svc}: имя {svc}.prod не резолвится, а поды Running и Ready."][v]
    return {"scene_title": "Сервис без трафика", "story": story, "prompt": "Нажмите на строку с ошибкой.", "panel": {"type": "code", "lang": "yaml", "lines": lines}, "key": key}


@family("ops_k8s_pdb", SPEC, "Kubernetes", "choice", 2.2, 1.0)
def _(rng):
    svc, n, m = rng.choice(SVCS), rng.randint(2, 4), rng.randint(15, 40)
    node = f"pool-a-{rng.randint(100, 999)}"
    v = _variant(rng, 3)
    if v == 0:
        lang = "yaml"
        lines = [f"# Deployment {svc}: replicas: {n}", "apiVersion: policy/v1", "kind: PodDisruptionBudget", "metadata:", f"  name: {svc}-pdb", "spec:",
                 f"  minAvailable: {n}", "  selector:", "    matchLabels:", f"      app: {svc}"]
        story = "«Cannot evict pod as it would violate the pod's disruption budget»."
    elif v == 1:
        lang = "text"
        lines = [f"$ kubectl get pdb {svc}-pdb", "NAME        MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS", f"{svc}-pdb   N/A             1                 0",
                 f"$ kubectl get pods -l app={svc}", f"{svc}-7d9f-x2k   0/1   Pending   0   {m}m", f"$ kubectl describe pod {svc}-7d9f-x2k | tail -1",
                 f"  Warning  FailedScheduling  0/{rng.randint(3, 6)} nodes are available: Insufficient cpu"]
        story = f"один под {svc} уже выселен, второй drain выселить не даёт."
    else:
        lang = "text"
        lines = [f"$ kubectl drain {node} --ignore-daemonsets", f"error: unable to drain node \"{node}\": cannot delete Pods not managed by ReplicationController, "
                 f"ReplicaSet, Job, DaemonSet or StatefulSet (use --force to override): default/{svc}-debug"]
        story = "drain останавливается с ошибкой на одном поде."
    opts, key = _options(rng, ["minAvailable равен числу реплик: PDB не пускает ни одного выселения, нужен maxUnavailable: 1",
                               "Замене не хватает ресурсов на других узлах: сначала добавить узлы в новый пул, потом продолжать drain",
                               "Под создан вручную, без контроллера: после drain его никто не пересоздаст — перенести в Deployment или удалить осознанно"], v,
                         ["drain нужно запускать с --disable-eviction: тогда поды удаляются без проверки бюджета и drain пройдёт",
                          f"Поды {svc} не обрабатывают SIGTERM, и выселение ждёт весь terminationGracePeriod"])
    return {"scene_title": "Drain не идёт", "story": f"Переводите кластер на новый пул узлов, drain старого узла не проходит уже {m} мин: {story}",
            "prompt": "Что мешает и как исправить?", "panel": {"type": "code", "lang": lang, "lines": lines}, "options": opts, "key": key}


@family("ops_k8s_liveness", SPEC, "Kubernetes", "choice", 2.3, 2.3)
def _(rng):
    svc, n, m = rng.choice(SVCS), rng.choice([4, 6, 8]), rng.randint(10, 40)
    pod = f"{svc}-{rng.randint(100, 999)}x"
    v = _variant(rng, 3)
    if v == 0:
        story = f"База переключилась на реплику за 20 секунд, а сервис {svc} лежал {rng.randint(6, 12)} минут: все {n} {'пода' if n == 4 else 'подов'} ушли в рестарт."
        lines = [_log(f"11:{m:02d}:00", "pg-ha", "INFO", "failover started: primary pg-0 -> pg-1"),
                 _log(f"11:{m:02d}:06", svc, "WARN", "GET /healthz -> 503: database unreachable"),
                 _log(f"11:{m:02d}:09", "kubelet", "WARN", f"{pod}: Liveness probe failed: HTTP probe failed with statuscode: 503"),
                 _log(f"11:{m:02d}:09", "kubelet", "INFO", f"{pod}: Container {svc} failed liveness probe, will be restarted"),
                 _log(f"11:{m:02d}:19", "pg-ha", "INFO", "failover complete in 19 s"),
                 _log(f"11:{m + 4:02d}:10", "kubelet", "WARN", f"{svc}: 0/{n} pods ready, Back-off restarting failed container")]
    elif v == 1:
        story = f"После переезда новые поды {svc} не поднимаются никогда: каждый перезапускается через минуту после старта."
        lines = [_log(f"11:{m:02d}:00", svc, "INFO", "starting, warming up cache: ~90 s before ready"),
                 _log(f"11:{m:02d}:30", "kubelet", "INFO", f"{pod}: liveness initialDelaySeconds=30, periodSeconds=10, failureThreshold=3"),
                 _log(f"11:{m + 1:02d}:00", "kubelet", "WARN", f"{pod}: Liveness probe failed: connection refused"),
                 _log(f"11:{m + 1:02d}:00", "kubelet", "INFO", f"{pod}: Container {svc} failed liveness probe, will be restarted"),
                 _log(f"11:{m + 6:02d}:10", "kubelet", "WARN", f"{svc}: 0/{n} pods ready, Back-off restarting failed container")]
    else:
        story = f"Изменили ConfigMap {svc} — и сервис на несколько минут полностью пропал."
        lines = [_log(f"11:{m:02d}:00", "argocd", "INFO", f"sync {svc}: configmap changed, rollout restart"),
                 _log(f"11:{m:02d}:01", "deployment", "INFO", f"{svc}: strategy RollingUpdate maxUnavailable=100%, maxSurge=0"),
                 _log(f"11:{m:02d}:01", "kubelet", "INFO", f"{svc}: terminating {n}/{n} pods"),
                 _log(f"11:{m + 2:02d}:30", "ingress", "ERROR", f"{svc}: no healthy upstream"),
                 _log(f"11:{m + 4:02d}:10", "deployment", "INFO", f"{svc}: {n}/{n} pods ready")]
    opts, key = _options(rng, ["Liveness проверяет базу: вынести эту проверку в readiness, а liveness — только сам процесс",
                               "Прогрев дольше задержки liveness-пробы: добавить startupProbe на время прогрева",
                               "Выкладка гасит все поды разом: ограничить maxUnavailable и разрешить maxSurge"], v,
                         ["Ускорить failover базы до 5 секунд, чтобы liveness-проба не успевала сработать",
                          f"Поднять число реплик {svc} вдвое, чтобы часть подов пережила сбой без рестарта"])
    return {"scene_title": "Сервис пропал", "story": story, "prompt": "Что исправить в первую очередь?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# --- CI/CD ---


@family("ops_ci_secret", SPEC, "CI/CD", "mark", 2.2, -1.6)
def _(rng):
    svc = rng.choice(SVCS)
    var = rng.choice(["DB_PASSWORD", "S3_SECRET_KEY", "PSP_API_KEY", "SMTP_PASSWORD"])
    secret = "".join(rng.choice("abcdef0123456789") for _ in range(16))
    v = _variant(rng, 3)
    lines = [f"FROM {'node:22-slim' if v == 2 else rng.choice(['python:3.12-slim', 'python:3.13-slim'])}", "WORKDIR /app"]
    if v == 2:
        lines.append("ARG NPM_TOKEN")
        lines += ["COPY package.json package-lock.json ./", 'RUN echo "//registry.example.ru/:_authToken=${NPM_TOKEN}" > .npmrc && npm ci']
        key = len(lines)
        story = f"Образ {svc} собирается с токеном приватного реестра пакетов. Образ уходит в общий реестр, и токен из него достали."
    else:
        lines += ["COPY requirements.txt .", "RUN pip install --no-cache-dir -r requirements.txt"]
        story = (f"Чтобы «не возиться с секретами в кластере», разработчик зашил {var} прямо при сборке образа {svc}. Образ уходит в общий реестр." if v == 0 else
                 f"В образе {svc} из общего реестра нашли файл .env с {var}, хотя в Dockerfile секретов нет. .dockerignore в репозитории нет.")
    if rng.random() < 0.5:
        lines.append(f'LABEL org.opencontainers.image.source="https://git.example.ru/{svc}"')
    if rng.random() < 0.5:
        lines.append("ENV PYTHONUNBUFFERED=1")
    if v == 0:
        lines.append(f"ENV {var}={secret}")
        key = len(lines)
    lines.append("COPY . .")
    if v == 1:
        key = len(lines)
    lines += ["USER 10001", 'CMD ["node", "server.js"]' if v == 2 else f'CMD ["python", "-m", "{svc}"]']
    return {"scene_title": "Образ с секретом", "story": story, "prompt": "Нажмите на строку, из-за которой секрет утекает вместе с образом.",
            "panel": {"type": "code", "lang": "dockerfile", "lines": lines}, "key": key}


@family("ops_ci_latest", SPEC, "CI/CD", "choice", 2.2, 0.9)
def _(rng):
    svc = rng.choice(SVCS)
    ns = rng.choice(["prod", "production", "main"])
    v = _variant(rng, 3)
    if v == 0:
        lines = ["build:", "  stage: build", "  script:", f"    - docker build -t $REGISTRY/{svc}:latest .", f"    - docker push $REGISTRY/{svc}:latest",
                 "deploy:", "  stage: deploy", "  script:", f"    - kubectl -n {ns} set image deploy/{svc} {svc}=$REGISTRY/{svc}:latest",
                 f"    - kubectl -n {ns} rollout restart deploy/{svc}"]
        story = f"После выкладки часть подов {svc} работает со старым кодом, а «откат на предыдущую ревизию» вернул тот же сломанный релиз."
    elif v == 1:
        lines = ["test:", "  stage: test", "  script: [make test]", "deploy:", "  stage: test", "  needs: [build]", "  script:",
                 f"    - kubectl -n {ns} set image deploy/{svc} {svc}=$REGISTRY/{svc}:$CI_COMMIT_SHA"]
        story = f"В прод уехал релиз {svc}, у которого в том же пайплайне упали тесты."
    else:
        lines = ["deploy:", "  stage: deploy", "  script:", f"    - kubectl -n {ns} set image deploy/{svc} {svc}=$REGISTRY/{svc}:$CI_COMMIT_SHA",
                 f"    - kubectl -n {ns} rollout status deploy/{svc}", f"    - kubectl -n {ns} exec deploy/{svc} -- python -m {svc}.migrate"]
        story = f"Сразу после каждой выкладки {svc} несколько минут сыплет ошибками «column does not exist», потом всё проходит само."
    opts, key = _options(rng, ["Тегировать образ SHA коммита и выкатывать по этому неизменяемому тегу или по дайджесту",
                               "Выкладка не ждёт тестов: deploy должен зависеть от успешного test (needs и стадия после тестов)",
                               "Миграции — отдельным шагом до выкладки кода, и обратно совместимые с текущей версией"], v,
                         ["Поставить imagePullPolicy: Always — тогда все поды подтянут свежий образ и откат заработает",
                          "Чистить кэш образов на узлах после каждой сборки, чтобы на них не оставалось старых образов"])
    return {"scene_title": "Пайплайн", "story": story, "prompt": "Что исправить в пайплайне?",
            "panel": {"type": "code", "lang": "yaml", "lines": lines, "caption": ".gitlab-ci.yml"}, "options": opts, "key": key}


@family("ops_ci_prt", SPEC, "CI/CD", "mark", 2.3, 2.0)
def _(rng):
    tok = rng.choice(["REGISTRY_TOKEN", "DEPLOY_KEY", "CLOUD_API_TOKEN"])
    test = rng.choice(["make test", "npm test", "pytest -q"])
    v = _variant(rng, 3)
    if v == 0:
        lines = [f"name: {rng.choice(['pr-checks', 'ci', 'tests'])}", "on:", "  pull_request_target:", "    types: [opened, synchronize]", "permissions:",
                 "  contents: read", "  pull-requests: write"]
        if rng.random() < 0.5:
            lines += ["concurrency:", "  group: pr-${{ github.event.number }}"]
        lines += ["jobs:", "  test:", "    runs-on: ubuntu-latest", "    steps:", "      - uses: actions/checkout@v4", "        with:",
                  "          ref: ${{ github.event.pull_request.head.sha }}"]
        ref = len(lines)
        lines += [f"      - run: {test}", "        env:", f"          {tok}: ${{{{ secrets.{tok} }}}}"]
        key = [ref, len(lines)]
        lines += ["      - uses: ./.github/actions/comment-results"]
        story = "pull_request_target выбран, чтобы бот мог комментировать PR из форков. Проект открытый, PR присылает кто угодно."
        prompt = "Нажмите на строку, из-за которой чужой код получает доступ к секретам."
    elif v == 1:
        lines = ["name: label-bot", "on:", "  issue_comment:", "    types: [created]", "jobs:", "  label:", "    runs-on: ubuntu-latest", "    steps:",
                 "      - run: |", '          echo "Команда: ${{ github.event.comment.body }}"']
        key = len(lines)
        lines += ["          ./scripts/apply-label.sh", "        env:", f"          {tok}: ${{{{ secrets.{tok} }}}}"]
        story = "Бот ставит метки по командам из комментариев к задачам. Проект открытый, комментировать может кто угодно."
        prompt = "Нажмите на строку, через которую текст комментария исполняется как команда."
    else:
        lines = ["name: ci", "on:", "  pull_request:", "jobs:", "  test:", "    runs-on: [self-hosted, office-net]"]
        key = len(lines)
        lines += ["    steps:", "      - uses: actions/checkout@v4", f"      - run: {test}"]
        story = "Тесты гоняются на своём раннере внутри сети компании — так быстрее. Проект открытый, PR из форков присылает кто угодно."
        prompt = "Нажмите на строку, из-за которой чужой код из PR выполняется внутри сети компании."
    return {"scene_title": "Чужой код в CI", "story": story, "prompt": prompt,
            "panel": {"type": "code", "lang": "yaml", "lines": lines, "caption": ".github/workflows/ci.yml"}, "key": key}


# --- Наблюдаемость ---


@family("ops_obs_rate", SPEC, "Наблюдаемость", "choice", 2.1, -1.0)
def _(rng):
    svc, w = rng.choice(SVCS), rng.choice(["1m", "2m", "5m"])
    sel = f'http_requests_total{{job="{svc}"}}'
    q = f'queue_depth{{job="{svc}"}}'
    err = f'http_requests_total{{job="{svc}", status=~"5.."}}'
    v = _variant(rng, 3)
    lines, story = [([f"# панель «RPS {svc}», сейчас:", sel], f"График RPS {svc} на новом дашборде только растёт «лесенкой» и падает до нуля при каждом рестарте пода."),
                    ([f"# панель «очередь {svc}», сейчас:", f"deriv({q}[{w}])"], f"График длины очереди {svc} скачет около нуля и уходит в минус, хотя в очереди тысячи задач."),
                    ([f"# панель «доля ошибок {svc}», сейчас:", f"sum(rate({err}[{w}]))"], f"Панель «доля ошибок» {svc} растёт вместе с трафиком, хотя доля ошибок не меняется.")][v]
    opts, key = _options(rng, [f"sum(rate({sel}[{w}]))", f"sum({q})", f"sum(rate({err}[{w}])) / sum(rate({sel}[{w}]))"], v,
                         [f"sum({sel}) / 300", f"max_over_time({sel}[{w}])"])
    return {"scene_title": "Странный график", "story": story, "prompt": "Каким запросом построить панель?",
            "panel": {"type": "code", "lang": "promql", "lines": lines}, "options": opts, "key": key}


@family("ops_obs_cardinality", SPEC, "Наблюдаемость", "mark", 2.2, 0.2)
def _(rng):
    bad = rng.choice(["user_id", "order_id", "session_id", "request_id"])
    v = _variant(rng, 3)
    lines = ["from prometheus_client import Counter, Histogram", ""]
    if v == 2:
        lines.append("BUCKETS = tuple(i / 1000 for i in range(1, 5001))")
        key = len(lines)
    elif rng.random() < 0.5:
        lines.append("BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2.5)")
    in_hist = rng.random() < 0.5
    lines += ["REQUESTS = Counter(", '    "http_requests_total", "HTTP-запросы",']
    lines.append(f'    ["method", "route", "{bad if v == 0 and not in_hist else "status"}"],')
    if v == 0 and not in_hist:
        key = len(lines)
    lines += [")", "LATENCY = Histogram(", '    "http_request_duration_seconds", "Время ответа",']
    lines.append(f'    ["method", "route", "{bad if v == 0 and in_hist else "status"}"],')
    if v == 0 and in_hist:
        key = len(lines)
    lines.append("    buckets=BUCKETS)" if v == 2 else ")")
    if v == 1:
        lines += ["", "", "async def metrics_mw(request, call_next):", "    resp = await call_next(request)",
                  "    REQUESTS.labels(request.method, request.url.path, resp.status_code).inc()"]
        key = len(lines)
        lines += ["    return resp"]
    story = [f"После переезда Prometheus съел {rng.randint(20, 60)} ГБ памяти: число серий выросло в сотни раз после последнего релиза метрик.",
             f"После переезда Prometheus съел {rng.randint(20, 60)} ГБ памяти: серий http_requests_total — сотни тысяч, по одной на каждый заказ и пользователя в URL.",
             f"После переезда Prometheus съел {rng.randint(20, 60)} ГБ памяти: у http_request_duration_seconds тысячи серий на каждый маршрут."][v]
    return {"scene_title": "Prometheus распух", "story": story, "prompt": "Нажмите на строку, из-за которой растёт число серий.",
            "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("ops_obs_quantile", SPEC, "Наблюдаемость", "choice", 2.3, 2.1)
def _(rng):
    svc = rng.choice(SVCS)
    shown, real = rng.randint(180, 320), rng.randint(900, 1800)
    v = _variant(rng, 3)
    if v == 0:
        lines = [f"# SLO-панель: p99 {svc} по всем подам (метрика — summary)", f'avg(http_request_duration_seconds{{job="{svc}", quantile="0.99"}})']
        story = f"p99 считается в каждом поде отдельно. На панели p99 {svc} — {shown} мс, а по логам балансировщика — {real} мс."
    elif v == 1:
        lines = [f"# SLO-панель: p99 {svc}", f'histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket{{job="{svc}"}}[1h])))']
        story = f"Утром {svc} пять минут отвечал по {real} мс, а на SLO-панели p99 этот сбой почти не виден."
    else:
        lines = [f"# SLO-панель: доступность {svc}", f'avg_over_time(probe_success{{target="{svc}/health"}}[30d])']
        story = f"Панель SLO показывает 100 % доступности {svc}, а пользователи всё утро получали ошибки на половине запросов: /health при этом отвечал 200."
    opts, key = _options(rng, ["Перейти на histogram и считать histogram_quantile(0.99, sum by (le) (rate(…_bucket[5m])))",
                               "Считать по короткому окну rate (1–5 минут): в часовом окне короткий всплеск растворяется",
                               "Считать доступность по реальным запросам — доле успешных ответов, а не по пробе раз в минуту"], v,
                         ['Взять max() вместо avg() по quantile="0.99": максимум из p99 подов и есть p99 всего сервиса',
                          "Считать p99 как среднее плюс три стандартных отклонения, восстановив их по _sum и _count"])
    return {"scene_title": "SLO-панель врёт", "story": story, "prompt": "Как исправить панель?", "panel": {"type": "code", "lang": "promql", "lines": lines}, "options": opts, "key": key}


# --- План отката ---


@family("ops_rb_undo", SPEC, "План отката", "choice", 2.1, -1.2)
def _(rng):
    svc, r = rng.choice(SVCS), rng.randint(5, 40)
    major, minor = rng.randint(1, 3), rng.randint(10, 30)
    vs = [f"{major}.{minor + i}.0" for i in range(3)]  # версии растут по ревизиям
    v = _variant(rng, 3)
    cur = vs[1] if v == 2 else vs[2]  # что сейчас крутится в проде
    lines = [f"$ kubectl rollout history deploy/{svc}", "REVISION  CHANGE-CAUSE", f"{r - 2:<9} image {svc}:{vs[0]}", f"{r - 1:<9} image {svc}:{vs[1]}"]
    if v == 2:
        # ConfigMap правят на месте под тем же именем: ревизия r — только rollout restart, undo вернёт тот же образ с новым конфигом
        lines += [f"{r:<9} image {svc}:{vs[1]}   # 5 минут назад: правка ConfigMap {svc}-config на месте + rollout restart"]
        story = f"После выкладки нового конфига {svc} отдаёт 500 на каждом третьем запросе. Образ не менялся."
    else:
        lines += [f"{r:<9} image {svc}:{vs[2]}   # выкатили 5 минут назад"]
        story = (f"Новый релиз {svc}:{vs[2]} отдаёт 500 на каждом третьем запросе. Миграций базы в нём не было." if v == 0 else
                 f"Новый релиз {svc}:{vs[2]} отдаёт 500 на каждом третьем запросе. В релизе была миграция, которая удалила старую колонку — {vs[1]} её читает.")
    opts, key = _options(rng, [f"kubectl rollout undo deploy/{svc} — вернуть ревизию {r - 1}",
                               f"Откат кода сломается о новую схему: выпускать исправление поверх {cur}",
                               f"Вернуть прошлую версию ConfigMap {svc}-config и перезапустить поды"], v,
                         [f"Удалить Deployment и создать заново из манифеста {vs[1]}", f"Масштабировать {svc} до нуля и обратно, чтобы сбросить состояние"])
    return {"scene_title": "Плохой релиз", "story": story, "prompt": "Как быстрее всего и безопасно вернуть сервис?",
            "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}


@family("ops_rb_canary", SPEC, "План отката", "choice", 2.2, 0.4)
def _(rng):
    m0, at = rng.randint(0, 20), 2
    m = 4 * (7 - at)  # минут от включения канарейки до последней точки графика
    x = [f"22:{m0 + 4 * i:02d}" for i in range(8)]
    stable = [round(rng.uniform(0.2, 0.5), 1) for _ in range(8)]
    v = _variant(rng, 3)
    if v == 0:
        canary = [0.0 if i < at else round(rng.uniform(3.0, 6.5), 1) for i in range(8)]
    elif v == 1:
        stable = [s if i < 1 else round(rng.uniform(3.0, 6.0), 1) for i, s in enumerate(stable)]
        canary = [0.0 if i < at else round(stable[i] + rng.uniform(-0.3, 0.3), 1) for i in range(8)]
    else:
        canary = [0.0 if i < at else round(s + rng.uniform(-0.1, 0.1), 1) for i, s in enumerate(stable)]
    panel = {"type": "chart", "x": x, "marker": {"i": at, "label": "канарейка 10 %"}, "series": [
        {"name": "ошибки 5xx канарейки, %", "axis": "left", "max": 10, "data": canary},
        {"name": "ошибки 5xx стабильной версии, %", "axis": "left", "max": 10, "data": stable},
    ]}
    opts, key = _options(rng, ["Остановить канарейку и вернуть весь трафик на стабильную версию, потом разбирать ошибки",
                               "Ошибки у обеих версий одинаковые и начались раньше канарейки: искать общую причину, канарейка ни при чём",
                               "Метрики канарейки не хуже стабильной: переходить к следующему шагу раскатки"], v,
                         ["Ничего не делать: в среднем по всему трафику доля ошибок пока меньше одного процента",
                          "Откатить и стабильную версию тоже: при канареечном выпуске версии надо откатывать вместе"])
    return {"scene_title": "Канарейка", "story": f"Новый ingress-контроллер в облаке выкатываете канарейкой на 10 % трафика. Прошло {m} минут.",
            "prompt": "Что делать?", "panel": panel, "options": opts, "key": key}


@family("ops_rb_replace", SPEC, "План отката", "mark", 2.3, 1.4)
def _(rng):
    name = rng.choice(["main", "orders", "billing"])
    attr, a1, a2 = rng.choice([("zone", '"ru-central-a"', '"ru-central-b"'), ("subnet_id", '"subnet-0a1f"', '"subnet-7c2e"'),
                               ("storage_type", '"network-ssd"', '"network-hdd"')])
    d1, dbid = rng.choice([100, 200, 400]), f"db-{rng.randint(1000, 9999)}"
    v = _variant(rng, 3)
    if v == 1:
        lines = ["Terraform will perform the following actions:", "", f"  # cloud_db_instance.{name} will be destroyed",
                 f"  # (because cloud_db_instance.{name} is not in configuration)", f'  - resource "cloud_db_instance" "{name}" {{']
        key = [len(lines) - 2, len(lines)]
        lines += [f'      - id   = "{dbid}" -> null', f'      - name = "{name}" -> null', "    }", "", "  # cloud_db_instance.primary will be created",
                  '  + resource "cloud_db_instance" "primary" {', "      + id   = (known after apply)", f'      + name = "{name}"', "    }", "",
                  "Plan: 1 to add, 0 to change, 1 to destroy."]
        story, prompt = (f"При рефакторинге модулей ресурс базы {name} в коде переименовали в primary. Перед apply смотрите план: в базе живые данные.",
                         "Нажмите на строку, из-за которой apply удалит базу с данными.")
    else:
        attrs = [(f'      ~ disk_size_gb          = {d1} -> {d1 * 2}', False), (f'        name                  = "{name}"', False),
                 (f'        engine_version        = "{rng.choice(["15", "16"])}"', False),
                 ('      ~ backup_window         = "02:00-03:00" -> "03:00-04:00"', False)]
        if v == 0:
            attrs.append((f'      ~ {attr:<21} = {a1} -> {a2}', True))
            head = [f'-/+ resource "cloud_db_instance" "{name}" {{', f'      ~ id                    = "{dbid}" -> (known after apply)']
            tail = "Plan: 1 to add, 0 to change, 1 to destroy."
            story, prompt = (f"Откатываете конфигурацию базы {name} к версии прошлого релиза. Перед apply смотрите план: в базе живые данные.",
                             "Нажмите на строку, из-за которой apply удалит базу и создаст пустую.")
        else:
            attrs.append((f'      ~ backup_retention_days = {rng.choice([7, 14, 30])} -> 0', True))
            head = [f'  ~ resource "cloud_db_instance" "{name}" {{', f'        id                    = "{dbid}"']
            tail = "Plan: 0 to add, 1 to change, 0 to destroy."
            story, prompt = (f"Откатываете конфигурацию базы {name} к версии прошлого релиза — тогда модуль ещё не умел задавать параметры резервного копирования.",
                             "Нажмите на строку, после которой база останется без резервных копий.")
        rng.shuffle(attrs)
        lines = ["Terraform will perform the following actions:", "", *head]
        for text, bad in attrs:
            lines.append(text)
            if bad:
                key = len(lines)
        lines += ["    }", "", tail]
    return {"scene_title": "План перед apply", "story": story, "prompt": prompt, "panel": {"type": "code", "lang": "hcl", "lines": lines}, "key": key}


# --- уровень Lead: компромиссы надёжности, диагностика по нескольким сигналам, тонкие ошибки конфигурации ---


@family("ops_inc_retry_budget", SPEC, "Диагностика инцидентов", "choice", 2.4, 2.4)
def _(rng):
    svc, db = rng.choice(SVCS), rng.choice(["orders-db", "billing-db", "pg-main"])
    t_gw, t_svc, n_retry = rng.choice([2, 3]), rng.choice([4, 5]), rng.choice([3, 4])
    m0, blip = rng.randint(0, 20), rng.randint(2, 3)
    x = [f"20:{m0 + 2 * i:02d}" for i in range(8)]
    v = _variant(rng, 3)
    if v == 0:
        inc = [rng.randint(900, 1000) for _ in range(8)]
        q = [rng.randint(950, 1050) if i < blip else rng.randint(900 * n_retry * 2, 1000 * n_retry * 2) for i in range(8)]
        p99 = [rng.randint(80, 120) if i < blip else rng.randint(t_svc * 900, t_svc * 1000) for i in range(8)]
        top = 1000 * n_retry * 2 + 1000
        mark = f"{db}: медленные запросы 40 с"
        series = [{"name": f"запросы к {svc}-api, RPS", "axis": "left", "max": top, "data": inc},
                  {"name": f"запросы {svc}-api → {db}, RPS", "axis": "left", "max": top, "data": q},
                  {"name": f"p99 {svc}-api, мс", "axis": "right", "max": t_svc * 1000, "data": p99}]
        story = (f"{db} тормозил 40 секунд и восстановился, а {svc}-api до сих пор не отвечает. "
                 f"Шлюз: таймаут {t_gw} с, 2 повтора; {svc}-api: таймаут к базе {t_svc} с, {n_retry} повтора.")
    elif v == 1:
        mark = "сообщение с новой схемой"
        series = [{"name": f"лаг консьюмера {svc}, тыс. сообщений", "axis": "left", "max": 500,
                   "data": [rng.randint(0, 3) if i < blip else 40 * (i - blip + 1) + rng.randint(0, 20) for i in range(8)]},
                  {"name": "ошибки обработки в секунду", "axis": "right", "max": 50, "data": [0 if i < blip else rng.randint(30, 45) for i in range(8)]}]
        story = f"Консьюмер {svc} упирается в одну партицию: лаг растёт, в логах одна и та же ошибка разбора по одному и тому же смещению, повтор — бесконечный."
    else:
        mark = "рост трафика"
        series = [{"name": f"реплики {svc}-api", "axis": "left", "max": 50, "data": [6 if i < blip else rng.choice([38, 40, 12, 10, 36, 8]) for i in range(8)]},
                  {"name": "CPU подов, % от requests", "axis": "right", "max": 300, "data": [rng.randint(60, 80) if i < blip else rng.randint(150, 280) for i in range(8)]}]
        story = f"Трафик вырос на 30 %, а {svc}-api с тех пор то раздувается до 40 подов, то сжимается до 8. Новые поды первые 2 минуты прогревают JIT и грузят CPU."
    panel = {"type": "chart", "x": x, "marker": {"i": blip, "label": mark}, "series": series}
    opts, key = _options(rng, [f"Повторы шлюза и {svc}-api перемножаются, а таймаут сервиса ({t_svc} с) длиннее шлюза ({t_gw} с): повторять на одном уровне, передавать дедлайн",
                               "Отравленное сообщение повторяется бесконечно и держит партицию: ограничить повторы и уводить такие сообщения в DLQ",
                               "Автоскейлер реагирует на всплеск CPU при прогреве новых подов: окно стабилизации и не учитывать неготовые поды"], v,
                         [f"{db} не вытягивает нагрузку: масштабировать базу вертикально и поднять пул соединений {svc}-api",
                          f"Таймауты слишком короткие: поднять их до 10 с на всех уровнях, чтобы медленные запросы к {db} успевали завершиться и не уходили в повтор",
                          f"Поставить circuit breaker на шлюзе и поднять там повторы до 5: клиенты реже увидят ошибку, пока {svc}-api восстанавливается"])
    return {"scene_title": "Самоподдерживающийся сбой", "story": story,
            "prompt": "Почему сбой не проходит сам и что менять в первую очередь?", "panel": panel, "options": opts, "key": key}


@family("ops_net_conntrack_dns", SPEC, "Сети", "choice", 2.3, 2.6)
def _(rng):
    svc, host = rng.choice(SVCS), rng.choice(["db.internal", "kafka.internal", "auth.svc.cluster.local"])
    node, n = f"node-{rng.randint(1, 9)}", rng.randint(30, 60) * 1000
    t = lambda s: f"03:{10 + s // 60:02d}:{s % 60:02d}"  # noqa: E731
    ext = rng.choice(["api.partner.example", "pay.example", "maps.example"])
    v = _variant(rng, 3)
    if v == 0:
        story = f"После переезда в облачный Kubernetes часть запросов {svc} замирает ровно на 5 секунд. Всё упирается в резолв имён, но не всегда."
        lines = [_log(t(1), svc, "WARN", f"resolve {host} took {rng.randint(5001, 5012)} ms"),
                 _log(t(3), svc, "INFO", f"resolve {host} took {rng.randint(1, 4)} ms"),
                 _log(t(9), "coredns", "INFO", f"p99 latency {rng.randint(2, 6)} ms, errors 0, cache hit {rng.randint(85, 95)} %"),
                 _log(t(14), svc, "WARN", f"resolve {host} took {rng.randint(5001, 5012)} ms"),
                 _log(t(20), node, "INFO", f"conntrack -S: insert_failed={rng.randint(3000, 9000)} (+{rng.randint(40, 90)}/min), drop=0"),
                 _log(t(21), node, "INFO", f"nf_conntrack count {n} / max 262144")]
    elif v == 1:
        story = f"После переезда запросы {svc} к внешним API стали медленнее на десятки миллисекунд, а нагрузка на CoreDNS выросла в разы."
        lines = [_log(t(1), "coredns", "INFO", f"{ext}.{svc}.svc.cluster.local A → NXDOMAIN"),
                 _log(t(1), "coredns", "INFO", f"{ext}.svc.cluster.local A → NXDOMAIN"),
                 _log(t(1), "coredns", "INFO", f"{ext}.cluster.local A → NXDOMAIN"),
                 _log(t(1), "coredns", "INFO", f"{ext}.ru-central1.internal A → NXDOMAIN"),
                 _log(t(2), "coredns", "INFO", f"{ext} A → NOERROR"),
                 _log(t(9), node, "INFO", "conntrack -S: insert_failed=0, drop=0; coredns CPU 40 % от лимита")]
    else:
        story = f"В вечерний пик часть запросов {svc} падает с ошибкой резолва; днём всё работает."
        lines = [_log(t(1), svc, "ERROR", f"resolve {host}: SERVFAIL"),
                 _log(t(2), "coredns", "WARN", f"plugin/forward: i/o timeout, {rng.randint(800, 1500)} queries in flight"),
                 _log(t(3), "kubelet", "INFO", "coredns-0, coredns-1: CPU throttled 78 % of periods (limit 100m)"),
                 _log(t(9), node, "INFO", "conntrack -S: insert_failed=0, drop=0"),
                 _log(t(10), "coredns", "INFO", "replicas 2, autoscaler: none")]
    opts, key = _options(rng, ["Гонка conntrack на параллельных A/AAAA по UDP (растёт insert_failed): NodeLocal DNSCache или single-request-reopen",
                               "ndots:5 гоняет внешние имена через все search-домены: ndots пониже или FQDN с точкой на конце",
                               "CoreDNS упирается в лимит CPU в пик: поднять лимиты, добавить реплики и автоскейлинг по нагрузке"], v,
                         ["Таблица conntrack на узле переполняется и пакеты отбрасываются: поднять nf_conntrack_max и уменьшить таймауты UDP-записей",
                          f"Резолвер {host} в старом ЦОДе медленный: прописать адреса в /etc/hosts подов"])
    return {"scene_title": "Резолв имён", "story": story, "prompt": "В чём причина?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("ops_k8s_qos_eviction", SPEC, "Kubernetes", "mark", 2.3, 2.75)
def _(rng):
    """При MemoryPressure kubelet ранжирует поды по превышению потребления над requests, а не по priorityClass;
    варианты: мало памяти в requests, BestEffort без resources или кэш в emptyDir в памяти (tmpfs считается потреблением пода)."""
    svc = rng.choice(["payments-api", "checkout-api", "auth-api"])
    mode = ["main", "besteffort", "tmpfs"][_variant(rng, 3)]
    req, used = rng.choice([("128Mi", "1.1Gi"), ("256Mi", "1.4Gi"), ("300Mi", "1.6Gi")])
    lines = ["apiVersion: apps/v1", "kind: Deployment", "metadata:", f"  name: {svc}", "spec:", "  template:", "    spec:",
             "      priorityClassName: business-critical", "      containers:", f"        - name: {svc}", f"          image: registry.local/{svc}:{_v(rng)}"]
    if rng.random() < 0.5:
        lines += ["          env:", "            - name: GOMEMLIMIT", "              value: 1800MiB"]
    if mode == "besteffort":
        lines.append("          resources: {}")
        key = len(lines)
        tail = f"контейнер {svc} без requests и limits"
    elif mode == "main":
        lines += ["          resources:", "            requests:", f"              cpu: {rng.choice(['250m', '500m'])}", f"              memory: {req}"]
        key = len(lines)
        lines += ["            limits:", "              memory: 2Gi"]
        if rng.random() < 0.5:
            lines.append(f"              cpu: {rng.choice(['1', '2'])}")
        tail = f"потребление {svc} — {used}"
    else:
        lines += ["          resources:", "            requests: {cpu: 500m, memory: 1536Mi}", "            limits: {cpu: '1', memory: 2Gi}",
                  "          volumeMounts: [{name: cache, mountPath: /var/cache/app}]", "      volumes:", "        - name: cache", "          emptyDir:",
                  "            medium: Memory"]
        key = len(lines)
        tail = f"процесс {svc} в пределах requests, но кэш в /var/cache/app занял {used}"
    batch = rng.choice(["report-batch", "etl-nightly", "export-job"])
    return {"scene_title": "Выселили не тех", "story": f"Узел ушёл в MemoryPressure. Kubelet выселил {svc} ({tail}, приоритет высокий), "
                                                       f"а {batch} с низким приоритетом и requests = limits остался работать.",
            "prompt": f"Нажмите на строку, из-за которой {svc} выселяется первым, несмотря на приоритет.",
            "panel": {"type": "code", "lang": "yaml", "lines": lines}, "key": key}


@family("ops_rb_error_budget", SPEC, "План отката", "choice", 2.3, 2.9)
def _(rng):
    d, spike = rng.choice([20, 21, 22]), 4
    v = _variant(rng, 3)
    early, late = [(rng.choice([1.2, 1.5]), rng.choice([7, 8, 9])), (rng.choice([1.2, 1.5]), rng.choice([1.2, 1.5])), (4.0, 9)][v]
    left = [100.0]
    for day in range(1, d + 1):
        left.append(max(0.0, left[-1] - (late if day > d - spike else early)))
    rest = 30 - d
    days = range(d - 9, d + 1)
    panel = {"type": "chart", "x": [f"д{day}" for day in days], "marker": {"i": 9 - spike + 1, "label": f"релиз {_v(rng)}"}, "series": [
        {"name": "остаток бюджета ошибок, %", "axis": "left", "max": 100, "data": [round(left[day]) for day in days]},
        {"name": "расход бюджета за день, %", "axis": "right", "max": 10, "data": [late if day > d - spike else early for day in days]},
    ]}
    f = lambda x: f"{x:.1f}".replace(".", ",")  # noqa: E731
    avg = (100 - left[-1]) / d
    wrong = [[f"Средний расход за окно — {f(avg)} %/день, бюджета хватит на ~{f(left[-1] / avg)} дн., а до конца окна {rest}: релиз можно выкатывать",
              f"Осталось {round(left[-1])} % бюджета: он и нужен на рискованные изменения — выкатить релиз сразу на весь трафик"],
             [f"Осталось {round(left[-1])} % бюджета: он и нужен на рискованные изменения — выкатить релиз сразу на весь трафик",
              "Перейти на окно SLO 90 дней: бюджет станет втрое больше, и запас вырастет"],
             ["Перейти на окно SLO 90 дней: бюджет станет втрое больше, и нынешний всплеск ошибок в нём растворится",
              "Выкатить канарейкой на 1 % трафика: так бюджет почти не расходуется"]][v]
    opts, key = _options(rng, ["Свежий расход в разы выше среднего: бюджет кончится раньше конца окна — заморозить рискованные релизы",
                               f"Расход ровный, {round(left[-1])} % бюджета хватает до конца окна с запасом: выкатывать обычным порядком, с канарейкой",
                               "Бюджет исчерпан: до конца окна выпускать только исправления надёжности, фичи — после"], v, wrong)
    return {"scene_title": "Бюджет ошибок", "story": f"SLO доступности 99,9 % за 30 дней, идёт {d}-й день окна. Продукт просит завтра выкатить "
                                                     "большую фичу с миграцией данных.",
            "prompt": "Что решить по релизу?", "panel": panel, "options": opts, "key": key}
