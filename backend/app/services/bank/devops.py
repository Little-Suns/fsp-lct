"""DevOps / SRE, сюжет «Миграция в облако»: сценарные семейства с логами, графиками и манифестами (по 3 на компетенцию)."""

from app.services.items import _choice, _log, family

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
    err = f"GET https://{legacy}/api/v2/accounts: x509: certificate signed by unknown authority"
    lines = [
        _log(f"23:{m:02d}:01", "argocd", "INFO", f"sync {svc}: image {svc}:{ver} (base {base})"),
        _log(f"23:{m:02d}:14", svc, "INFO", "connected to postgres (managed, TLS)"),
        _log(f"23:{m:02d}:15", svc, "ERROR", err),
        _log(f"23:{m:02d}:15", svc, "WARN", "retry 1/3 in 2s"),
        _log(f"23:{m:02d}:22", svc, "ERROR", err),
        _log(f"23:{m:02d}:40", "debug-vm", "INFO", f"curl https://{legacy}/api/v2/health from old VM: HTTP/1.1 200 OK"),
    ]
    opts, key = _choice(rng, "В новом образе нет корневого сертификата старого ЦОДа: добавить корпоративный CA в trust store", [
        f"Сертификат {legacy} истёк: перевыпустить его и заодно продлить промежуточный сертификат",
        "Облачный файрвол режет исходящий HTTPS в старый ЦОД: открыть 443 в egress-правилах кластера",
        "В облаке другой часовой пояс, и для подов сертификат ещё «не начал действовать» по времени",
    ])
    return {"scene_title": "Чужой сертификат", "story": f"Сервис {svc} переехал в облако на базовый образ {base}. Запросы к {legacy} в старом ЦОДе падают, со старых ВМ всё работает.",
            "prompt": "В чём причина?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("ops_inc_throttle", SPEC, "Диагностика инцидентов", "choice", 2.3, 1.2)
def _(rng):
    svc = rng.choice(SVCS)
    m0, at = rng.randint(0, 20), rng.randint(2, 4)
    x = [f"00:{m0 + 5 * i:02d}" for i in range(8)]
    p99 = [rng.randint(100, 140) if i < at else rng.randint(600, 1300) for i in range(8)]
    thr = [rng.randint(0, 3) if i < at else rng.randint(40, 75) for i in range(8)]
    use = rng.randint(35, 55)
    panel = {"type": "chart", "x": x, "marker": {"i": at, "label": "limits.cpu: 1"}, "series": [
        {"name": f"p99 {svc}, мс", "axis": "left", "max": 1500, "data": p99},
        {"name": "периоды с троттлингом CPU, %", "axis": "right", "max": 100, "data": thr},
    ]}
    opts, key = _choice(rng, "CFS-троттлинг: потоки выбирают квоту CPU в начале периода и ждут его конца, хотя в среднем загрузка низкая", [
        "Узлам облачного пула не хватает CPU: соседние поды забирают ядра, нужен тип машин с более быстрыми ядрами",
        "Вместе с CPU урезали память: сборщик мусора запускается чаще и на сотни миллисекунд останавливает обработку запросов, отсюда хвост p99",
        "После переезда выросла сетевая задержка между зонами доступности, и p99 вырос вместе с ней",
    ])
    return {"scene_title": "Медленно без нагрузки", "story": f"В облачном кластере подам {svc} выставили limits.cpu: 1. Средняя загрузка CPU — {use} % лимита, а p99 вырос в разы.",
            "prompt": "Что происходит?", "panel": panel, "options": opts, "key": key}


@family("ops_inc_clock", SPEC, "Диагностика инцидентов", "choice", 2.3, 1.9)
def _(rng):
    m, skew = rng.randint(10, 50), rng.randint(40, 180)
    nodes = [f"pool-b-{rng.randint(100, 999)}" for _ in range(2)]
    lines = [
        _log(f"01:{m:02d}:00", "netops", "INFO", "egress policy applied to pool-b: allow tcp/443, tcp/5432, tcp/6379"),
        _log(f"01:{m:02d}:05", "scheduler", "INFO", "pool-b ready: 6 nodes, pods migrating from pool-a"),
        _log(f"03:{m:02d}:12", "auth-gw", "ERROR", f"token rejected: iat is in the future (skew {skew}s) issuer=auth node={nodes[0]}"),
        _log(f"03:{m:02d}:12", "auth-gw", "INFO", "token accepted issuer=auth node=pool-a-412"),
        _log(f"03:{m:02d}:15", "auth-gw", "ERROR", f"token rejected: iat is in the future (skew {skew + rng.randint(1, 4)}s) issuer=auth node={nodes[1]}"),
        _log(f"03:{m:02d}:20", "auth", "INFO", "signing key kid=k7 active since 30 days"),
    ]
    opts, key = _choice(rng, "Часы узлов pool-b уплыли: egress пропускает только TCP, и NTP (UDP 123) до серверов времени не доходит", [
        "Ключ подписи JWT ротировали, и поды на pool-b получили из секрета старый ключ, которым токены не проверить",
        "На узлах pool-b другой часовой пояс, и iat сравнивается с местным временем: выставить TZ=UTC в контейнерах",
        "Токены живут слишком мало и истекают по дороге до auth-gw: увеличить их срок жизни до часа",
    ])
    return {"scene_title": "Токены из будущего", "story": "Через два часа после переезда части подов на новый пул узлов auth-gw начал отклонять токены. Ошибки — только для подов на pool-b.",
            "prompt": "В чём причина?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# --- Сети ---


@family("ops_net_bind", SPEC, "Сети", "choice", 2.1, -1.3)
def _(rng):
    svc, port = rng.choice(SVCS), rng.choice([8000, 8080, 9000, 3000])
    proc = rng.choice(["uvicorn", "node", "java", "gunicorn"])
    ip = f"10.42.{rng.randint(1, 9)}.{rng.randint(10, 250)}"
    lines = [
        f"$ kubectl exec deploy/{svc} -- ss -ltnp",
        "State   Recv-Q  Send-Q  Local Address:Port   Peer Address:Port  Process",
        f'LISTEN  0       4096    127.0.0.1:{port}       0.0.0.0:*          users:(("{proc}",pid=1,fd=7))',
        f"$ kubectl exec deploy/debug -- curl -s {ip}:{port}/health",
        f"curl: (7) Failed to connect to {ip} port {port}: Connection refused",
    ]
    opts, key = _choice(rng, "Приложение слушает только 127.0.0.1 внутри контейнера: нужно слушать 0.0.0.0", [
        "NetworkPolicy запрещает входящий трафик к поду из соседних подов namespace",
        f"Порт {port} внутри контейнера уже занят другим процессом, и запрос уходит не туда",
        f"Процессу без root нельзя открывать порт {port}, поэтому сокет на нём не создан",
    ])
    return {"scene_title": "Отказ в соединении", "story": f"Под {svc} в статусе Running, в логе «listening on port {port}». Из соседнего пода по IP получаете Connection refused.",
            "prompt": "В чём дело?", "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}


@family("ops_net_mtu", SPEC, "Сети", "choice", 2.3, 1.3)
def _(rng):
    host = rng.choice(["erp.dc1.internal", "files.dc1.internal", "reports.dc1.internal"])
    ip = f"172.{rng.randint(16, 31)}.{rng.randint(0, 255)}.{rng.randint(2, 250)}"
    ok = rng.choice([1350, 1372, 1400])
    lines = [
        f"$ curl -s -o /dev/null -w '%{{http_code}} %{{size_download}}' https://{host}/ping",
        f"200 {rng.randint(2, 40)}",
        f"$ curl -s -o /dev/null -w '%{{http_code}} %{{size_download}}' https://{host}/export?limit={rng.choice([500, 1000, 5000])}",
        "(нет ответа 60 с) curl: (28) Operation timed out",
        f"$ ping -M do -c 3 -s 1472 {ip}",
        "3 packets transmitted, 0 received, 100% packet loss",
        f"$ ping -M do -c 3 -s {ok} {ip}",
        "3 packets transmitted, 3 received, 0% packet loss",
    ]
    opts, key = _choice(rng, "MTU туннеля меньше 1500, а ICMP «нужна фрагментация» теряется: включить MSS clamping", [
        f"{host} долго формирует большие выгрузки: поднять таймаут клиента и балансировщика до 5 минут",
        "В канале теряются пакеты: включить на туннеле повторную передачу и коррекцию ошибок",
        "VPN-шлюз ограничивает полосу и рвёт длинные соединения: поднять лимит полосы на шлюзе",
    ])
    return {"scene_title": "Большое не пролезает", "story": f"Между облаком и старым ЦОДом подняли VPN-туннель. Короткие запросы к {host} проходят, большие ответы зависают.",
            "prompt": "Что происходит и как исправить?", "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}


@family("ops_net_snat", SPEC, "Сети", "choice", 2.3, 2.2)
def _(rng):
    svc = rng.choice(["payments-gw", "notify", "partner-sync"])
    dst = f"203.0.113.{rng.randint(10, 250)}"
    m, rps = rng.randint(10, 50), rng.randint(900, 2500)
    lines = [
        _log(f"19:{m:02d}:00", svc, "INFO", f"outgoing {rps} rps to partner api, http client keep_alive=false"),
        _log(f"19:{m:02d}:04", svc, "ERROR", f"dial tcp {dst}:443: i/o timeout"),
        _log(f"19:{m:02d}:04", "nat-gw-1", "WARN", f"port allocation failed for {dst}:443: 64512/64512 in use"),
        _log(f"19:{m:02d}:05", svc, "INFO", "POST /v1/notify 200 (84 ms)"),
        _log(f"19:{m:02d}:06", svc, "ERROR", f"dial tcp {dst}:443: i/o timeout"),
        _log(f"19:{m:02d}:30", "nat-gw-1", "INFO", "bandwidth 180 Mbit/s of 5 Gbit/s"),
    ]
    opts, key = _choice(rng, "Кончились SNAT-порты NAT-шлюза к одному адресу: включить keep-alive и пул соединений", [
        "Партнёрский API ограничивает частоту запросов и молча отбрасывает лишние соединения",
        "DNS партнёра иногда отдаёт недоступный адрес: закрепить рабочий IP в /etc/hosts подов",
        "NAT-шлюзу не хватает пропускной способности в пик: взять тип шлюза побольше",
    ])
    return {"scene_title": "Таймауты на выходе", "story": f"После переезда {svc} ходит к партнёру через облачный NAT-шлюз. В вечерний пик часть новых соединений висит до таймаута.",
            "prompt": "В чём причина?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# --- Kubernetes ---


TYPO = {"payments": "payment", "checkout": "chekout", "catalog": "catalogue", "profile": "profiles", "orders": "order"}


@family("ops_k8s_selector", SPEC, "Kubernetes", "mark", 2.2, -1.5)
def _(rng):
    svc = rng.choice(list(TYPO))
    lines = ["apiVersion: apps/v1", "kind: Deployment", "metadata:", f"  name: {svc}", "spec:", f"  replicas: {rng.randint(2, 4)}",
             "  selector:", "    matchLabels:", f"      app: {svc}", "  template:", "    metadata:", "      labels:", f"        app: {svc}",
             "---", "apiVersion: v1", "kind: Service", "metadata:", f"  name: {svc}"]
    if rng.random() < 0.5:
        lines += ["  annotations:", f"    owner: team-{rng.choice(['core', 'platform', 'growth'])}"]
    lines += ["spec:", "  selector:", f"    app: {TYPO[svc]}"]
    key = len(lines)
    lines += ["  ports:", "    - port: 80", f"      targetPort: {rng.choice([8000, 8080])}"]
    return {"scene_title": "Пустые endpoints", "story": f"После переноса манифестов сервис {svc} не получает трафик: kubectl get endpoints {svc} пуст, а все поды Running и Ready.",
            "prompt": "Нажмите на строку с ошибкой.", "panel": {"type": "code", "lang": "yaml", "lines": lines}, "key": key}


@family("ops_k8s_pdb", SPEC, "Kubernetes", "choice", 2.2, 1.0)
def _(rng):
    svc, n, m = rng.choice(SVCS), rng.randint(2, 4), rng.randint(15, 40)
    lines = [f"# Deployment {svc}: replicas: {n}", "apiVersion: policy/v1", "kind: PodDisruptionBudget", "metadata:", f"  name: {svc}-pdb", "spec:",
             f"  minAvailable: {n}", "  selector:", "    matchLabels:", f"      app: {svc}"]
    opts, key = _choice(rng, "minAvailable равен числу реплик: PDB не пускает ни одного выселения, нужен maxUnavailable: 1", [
        "drain нужно запускать с --force: тогда поды выселяются без проверки PodDisruptionBudget",
        f"На новом пуле не хватает ресурсов: выселенные поды {svc} не могут запланироваться, и drain ждёт, пока замена не станет Ready",
        f"Поды {svc} не обрабатывают SIGTERM, и выселение ждёт весь terminationGracePeriod",
    ])
    return {"scene_title": "Drain не идёт", "story": f"Переводите кластер на новый пул узлов. kubectl drain старого узла висит {m} минут: «Cannot evict pod as it would violate the pod's disruption budget».",
            "prompt": "Что мешает и как исправить?", "panel": {"type": "code", "lang": "yaml", "lines": lines}, "options": opts, "key": key}


@family("ops_k8s_liveness", SPEC, "Kubernetes", "choice", 2.3, 2.3)
def _(rng):
    svc, n, m = rng.choice(SVCS), rng.choice([4, 6, 8]), rng.randint(10, 40)
    pod = f"{svc}-{rng.randint(100, 999)}x"
    lines = [
        _log(f"11:{m:02d}:00", "pg-ha", "INFO", "failover started: primary pg-0 -> pg-1"),
        _log(f"11:{m:02d}:06", svc, "WARN", "GET /healthz -> 503: database unreachable"),
        _log(f"11:{m:02d}:09", "kubelet", "WARN", f"{pod}: Liveness probe failed: HTTP probe failed with statuscode: 503"),
        _log(f"11:{m:02d}:09", "kubelet", "INFO", f"{pod}: Container {svc} failed liveness probe, will be restarted"),
        _log(f"11:{m:02d}:19", "pg-ha", "INFO", "failover complete in 19 s"),
        _log(f"11:{m + 2:02d}:40", svc, "INFO", "warming up cache: 90 s before ready"),
        _log(f"11:{m + 4:02d}:10", "kubelet", "WARN", f"{svc}: 0/{n} pods ready, Back-off restarting failed container"),
    ]
    opts, key = _choice(rng, "Liveness проверяет базу: вынести эту проверку в readiness, а liveness — только сам процесс", [
        "Ускорить failover базы до 5 секунд, чтобы liveness-проба не успевала сработать",
        "Добавить startupProbe на 90 секунд: тогда прогрев кэша после рестарта больше не будет ронять поды, и каскад остановится сам",
        f"Поднять число реплик {svc} вдвое, чтобы часть подов пережила сбой базы без рестарта",
    ])
    return {"scene_title": "Каскад рестартов", "story": f"База переключилась на реплику за 20 секунд, а сервис {svc} лежал {rng.randint(6, 12)} минут: все {n} подов ушли в рестарт.",
            "prompt": "Что исправить в первую очередь?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# --- CI/CD ---


@family("ops_ci_secret", SPEC, "CI/CD", "mark", 2.2, -1.6)
def _(rng):
    svc = rng.choice(SVCS)
    var = rng.choice(["DB_PASSWORD", "S3_SECRET_KEY", "PSP_API_KEY", "SMTP_PASSWORD"])
    secret = "".join(rng.choice("abcdef0123456789") for _ in range(16))
    lines = [f"FROM {rng.choice(['python:3.12-slim', 'python:3.13-slim'])}", "WORKDIR /app", "COPY requirements.txt .", "RUN pip install --no-cache-dir -r requirements.txt"]
    if rng.random() < 0.5:
        lines.append(f'LABEL org.opencontainers.image.source="https://git.example.ru/{svc}"')
    if rng.random() < 0.5:
        lines.append("ENV PYTHONUNBUFFERED=1")
    lines.append(f"ENV {var}={secret}")
    key = len(lines)
    lines += ["COPY . .", "USER 10001", f'CMD ["python", "-m", "{svc}"]']
    return {"scene_title": "Образ с секретом", "story": f"Чтобы «не возиться с секретами в кластере», разработчик зашил {var} прямо при сборке образа {svc}. Образ уходит в общий реестр.",
            "prompt": "Нажмите на строку, из-за которой секрет утечёт вместе с образом.", "panel": {"type": "code", "lang": "dockerfile", "lines": lines}, "key": key}


@family("ops_ci_latest", SPEC, "CI/CD", "choice", 2.2, 0.9)
def _(rng):
    svc = rng.choice(SVCS)
    ns = rng.choice(["prod", "production", "main"])
    lines = ["build:", "  stage: build", "  script:", f"    - docker build -t $REGISTRY/{svc}:latest .", f"    - docker push $REGISTRY/{svc}:latest",
             "deploy:", "  stage: deploy", "  script:", f"    - kubectl -n {ns} set image deploy/{svc} {svc}=$REGISTRY/{svc}:latest",
             f"    - kubectl -n {ns} rollout restart deploy/{svc}"]
    opts, key = _choice(rng, "Тегировать образ SHA коммита и выкатывать по этому неизменяемому тегу или по дайджесту", [
        "Поставить imagePullPolicy: Always — тогда все поды подтянут свежий latest и откат заработает",
        "Чистить кэш образов на узлах после каждой сборки, чтобы на них не оставалось старых latest",
        "Запускать deploy вручную и только после того, как build завершился и образ уже в реестре",
    ])
    return {"scene_title": "Откат в никуда", "story": f"После выкладки часть подов {svc} работает со старым кодом, а «откат на предыдущую ревизию» вернул тот же сломанный релиз.",
            "prompt": "Что исправить в пайплайне?", "panel": {"type": "code", "lang": "yaml", "lines": lines, "caption": ".gitlab-ci.yml"}, "options": opts, "key": key}


@family("ops_ci_prt", SPEC, "CI/CD", "mark", 2.3, 2.0)
def _(rng):
    tok = rng.choice(["REGISTRY_TOKEN", "DEPLOY_KEY", "CLOUD_API_TOKEN"])
    lines = [f"name: {rng.choice(['pr-checks', 'ci', 'tests'])}", "on:", "  pull_request_target:", "    types: [opened, synchronize]", "permissions:",
             "  contents: read", "  pull-requests: write"]
    if rng.random() < 0.5:
        lines += ["concurrency:", "  group: pr-${{ github.event.number }}"]
    lines += ["jobs:", "  test:", "    runs-on: ubuntu-latest", "    steps:", "      - uses: actions/checkout@v4", "        with:",
              "          ref: ${{ github.event.pull_request.head.sha }}"]
    ref = len(lines)
    lines += [f"      - run: {rng.choice(['make test', 'npm test', 'pytest -q'])}", "        env:", f"          {tok}: ${{{{ secrets.{tok} }}}}"]
    env = len(lines)
    lines += ["      - uses: ./.github/actions/comment-results"]
    return {"scene_title": "PR из форка", "story": "pull_request_target выбран, чтобы бот мог комментировать PR из форков. Проект открытый, PR присылает кто угодно.",
            "prompt": "Нажмите на строку, из-за которой чужой код получает доступ к секретам.", "panel": {"type": "code", "lang": "yaml", "lines": lines, "caption": ".github/workflows/pr.yml"},
            "key": [ref, env]}


# --- Наблюдаемость ---


@family("ops_obs_rate", SPEC, "Наблюдаемость", "choice", 2.1, -1.0)
def _(rng):
    svc, w = rng.choice(SVCS), rng.choice(["1m", "2m", "5m"])
    sel = f'http_requests_total{{job="{svc}"}}'
    lines = [f"# панель «RPS {svc}», сейчас:", sel]
    opts, key = _choice(rng, f"sum(rate({sel}[{w}]))", [
        f"sum({sel}) / 300",
        f"max_over_time({sel}[{w}])",
        f"avg({sel}) by (instance)",
    ])
    return {"scene_title": "Лесенка вместо RPS", "story": f"График RPS {svc} на новом дашборде только растёт «лесенкой» и падает до нуля при каждом рестарте пода.",
            "prompt": "Каким запросом построить RPS?", "panel": {"type": "code", "lang": "promql", "lines": lines}, "options": opts, "key": key}


@family("ops_obs_cardinality", SPEC, "Наблюдаемость", "mark", 2.2, 0.2)
def _(rng):
    bad = rng.choice(["user_id", "order_id", "session_id", "request_id"])
    in_hist = rng.random() < 0.5
    lines = ["from prometheus_client import Counter, Histogram", ""]
    if rng.random() < 0.5:
        lines.append("BUCKETS = (0.05, 0.1, 0.25, 0.5, 1, 2.5)")
    lines += ["REQUESTS = Counter(", '    "http_requests_total", "HTTP-запросы",']
    lines.append(f'    ["method", "route", "{"status" if in_hist else bad}"],')
    key = None if in_hist else len(lines)
    lines += [")", "LATENCY = Histogram(", '    "http_request_duration_seconds", "Время ответа",']
    lines.append(f'    ["method", "route", "{bad if in_hist else "status"}"],')
    key = key or len(lines)
    lines.append(")")
    return {"scene_title": "Prometheus распух", "story": f"После переезда Prometheus съел {rng.randint(20, 60)} ГБ памяти: число серий выросло в сотни раз после последнего релиза метрик.",
            "prompt": "Нажмите на строку, из-за которой растёт число серий.", "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("ops_obs_quantile", SPEC, "Наблюдаемость", "choice", 2.3, 2.1)
def _(rng):
    svc = rng.choice(SVCS)
    shown, real = rng.randint(180, 320), rng.randint(900, 1800)
    lines = [f"# SLO-панель: p99 {svc} по всем подам (метрика — summary)", f'avg(http_request_duration_seconds{{job="{svc}", quantile="0.99"}})']
    opts, key = _choice(rng, "Перейти на histogram и считать histogram_quantile(0.99, sum by (le) (rate(…_bucket[5m])))", [
        'Взять max() вместо avg() по quantile="0.99": максимум из p99 подов и есть p99 всего сервиса',
        'Усреднить quantile="0.99" по подам с весами по числу запросов каждого пода за то же окно',
        "Считать p99 как среднее плюс три стандартных отклонения, восстановив их по _sum и _count",
    ])
    return {"scene_title": "Два разных p99", "story": f"p99 считается в каждом поде отдельно. На панели p99 {svc} — {shown} мс, а по логам балансировщика — {real} мс.",
            "prompt": "Как получить честный p99 по сервису?", "panel": {"type": "code", "lang": "promql", "lines": lines}, "options": opts, "key": key}


# --- План отката ---


@family("ops_rb_undo", SPEC, "План отката", "choice", 2.1, -1.2)
def _(rng):
    svc, r = rng.choice(SVCS), rng.randint(5, 40)
    vs = [f"{rng.randint(1, 3)}.{rng.randint(10, 30) + i}.0" for i in range(3)]
    lines = [f"$ kubectl rollout history deploy/{svc}", "REVISION  CHANGE-CAUSE", f"{r - 2:<9} image {svc}:{vs[0]}", f"{r - 1:<9} image {svc}:{vs[1]}",
             f"{r:<9} image {svc}:{vs[2]}   # выкатили 5 минут назад"]
    opts, key = _choice(rng, f"kubectl rollout undo deploy/{svc} — вернуть ревизию {r - 1}", [
        f"Удалить Deployment и создать заново из манифеста {vs[1]}",
        f"Собрать {vs[1]} из ветки заново и прогнать весь пайплайн",
        f"Масштабировать {svc} до нуля и обратно, чтобы сбросить состояние",
    ])
    return {"scene_title": "Плохой релиз", "story": f"Новый релиз {svc}:{vs[2]} отдаёт 500 на каждом третьем запросе. Миграций базы в нём не было.",
            "prompt": "Как быстрее всего и безопасно откатиться?", "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}


@family("ops_rb_canary", SPEC, "План отката", "choice", 2.2, 0.4)
def _(rng):
    m0, at, m = rng.randint(0, 20), 2, rng.choice([10, 15, 20])
    x = [f"22:{m0 + 4 * i:02d}" for i in range(8)]
    canary = [0.0 if i < at else round(rng.uniform(3.0, 6.5), 1) for i in range(8)]
    stable = [round(rng.uniform(0.2, 0.5), 1) for _ in range(8)]
    panel = {"type": "chart", "x": x, "marker": {"i": at, "label": "канарейка 10 %"}, "series": [
        {"name": "ошибки 5xx канарейки, %", "axis": "left", "max": 10, "data": canary},
        {"name": "ошибки 5xx стабильной версии, %", "axis": "left", "max": 10, "data": stable},
    ]}
    opts, key = _choice(rng, "Остановить канарейку и вернуть весь трафик на стабильную версию, потом разбирать ошибки", [
        "Довести канарейку до 50 % трафика, чтобы быстрее набрать статистику для надёжного вывода",
        "Откатить и стабильную версию тоже: ошибки могут быть общими для обеих версий контроллера",
        "Ничего не делать: в среднем по всему трафику доля ошибок пока меньше одного процента",
    ])
    return {"scene_title": "Канарейка", "story": f"Новый ingress-контроллер в облаке выкатываете канарейкой на 10 % трафика. Прошло {m} минут.",
            "prompt": "Что делать?", "panel": panel, "options": opts, "key": key}


@family("ops_rb_replace", SPEC, "План отката", "mark", 2.3, 1.4)
def _(rng):
    name = rng.choice(["main", "orders", "billing"])
    attr, a1, a2 = rng.choice([("zone", '"ru-central-a"', '"ru-central-b"'), ("subnet_id", '"subnet-0a1f"', '"subnet-7c2e"'),
                               ("storage_type", '"network-ssd"', '"network-hdd"')])
    d1 = rng.choice([100, 200, 400])
    attrs = [
        (f'      ~ disk_size_gb   = {d1} -> {d1 * 2}', False),
        (f'        name           = "{name}"', False),
        (f'      ~ {attr:<14} = {a1} -> {a2}', True),
        (f'        engine_version = "{rng.choice(["15", "16"])}"', False),
        ('      ~ backup_window  = "02:00-03:00" -> "03:00-04:00"', False),
    ]
    rng.shuffle(attrs)
    lines = ["Terraform will perform the following actions:", "",
             f'-/+ resource "cloud_db_instance" "{name}" {{', f'      ~ id             = "db-{rng.randint(1000, 9999)}" -> (known after apply)']
    key = None
    for text, bad in attrs:
        lines.append(text)
        if bad:
            key = len(lines)
    lines += ["    }", "", "Plan: 1 to add, 0 to change, 1 to destroy."]
    return {"scene_title": "План перед откатом", "story": f"Откатываете конфигурацию базы {name} к версии прошлого релиза. Перед apply смотрите план: в базе живые данные.",
            "prompt": "Нажмите на строку, из-за которой apply удалит базу и создаст пустую.", "panel": {"type": "code", "lang": "hcl", "lines": lines}, "key": key}


# --- уровень Lead: компромиссы надёжности, диагностика по нескольким сигналам, тонкие ошибки конфигурации ---


@family("ops_inc_retry_budget", SPEC, "Диагностика инцидентов", "choice", 2.4, 2.4)
def _(rng):
    svc, db = rng.choice(SVCS), rng.choice(["orders-db", "billing-db", "pg-main"])
    t_gw, t_svc, n_retry = rng.choice([2, 3]), rng.choice([4, 5]), rng.choice([3, 4])
    m0, blip = rng.randint(0, 20), rng.randint(2, 3)
    x = [f"20:{m0 + 2 * i:02d}" for i in range(8)]
    inc = [rng.randint(900, 1000) for _ in range(8)]
    q = [rng.randint(950, 1050) if i < blip else rng.randint(900 * n_retry * 2, 1000 * n_retry * 2) for i in range(8)]
    p99 = [rng.randint(80, 120) if i < blip else rng.randint(t_svc * 900, t_svc * 1000) for i in range(8)]
    top = 1000 * n_retry * 2 + 1000
    panel = {"type": "chart", "x": x, "marker": {"i": blip, "label": f"{db}: медленные запросы 40 с"}, "series": [
        {"name": f"запросы к {svc}-api, RPS", "axis": "left", "max": top, "data": inc},
        {"name": f"запросы {svc}-api → {db}, RPS", "axis": "left", "max": top, "data": q},
        {"name": f"p99 {svc}-api, мс", "axis": "right", "max": t_svc * 1000, "data": p99},
    ]}
    opts, key = _choice(rng, f"Повторы шлюза и {svc}-api перемножаются, а таймаут сервиса ({t_svc} с) длиннее шлюза ({t_gw} с): "
                             "повторять на одном уровне, передавать дедлайн", [
        f"{db} не вытягивает нагрузку: масштабировать базу вертикально и поднять пул соединений {svc}-api",
        f"Таймауты слишком короткие: поднять их до 10 с на всех уровнях, чтобы медленные запросы к {db} успевали завершиться и не уходили в повтор",
        f"Поставить circuit breaker на шлюзе и поднять там повторы до 5: клиенты реже увидят ошибку, пока {svc}-api восстанавливается",
    ])
    return {"scene_title": "Самоподдерживающийся сбой", "story": f"{db} тормозил 40 секунд и восстановился, а {svc}-api до сих пор не отвечает. "
                                                               f"Шлюз: таймаут {t_gw} с, 2 повтора; {svc}-api: таймаут к базе {t_svc} с, {n_retry} повтора.",
            "prompt": "Почему сбой не проходит сам и что менять в первую очередь?", "panel": panel, "options": opts, "key": key}


@family("ops_net_conntrack_dns", SPEC, "Сети", "choice", 2.3, 2.6)
def _(rng):
    svc, host = rng.choice(SVCS), rng.choice(["db.internal", "kafka.internal", "auth.svc.cluster.local"])
    node, n = f"node-{rng.randint(1, 9)}", rng.randint(30, 60) * 1000
    t = lambda s: f"03:{10 + s // 60:02d}:{s % 60:02d}"
    lines = [
        _log(t(1), svc, "WARN", f"resolve {host} took {rng.randint(5001, 5012)} ms"),
        _log(t(3), svc, "INFO", f"resolve {host} took {rng.randint(1, 4)} ms"),
        _log(t(9), "coredns", "INFO", f"p99 latency {rng.randint(2, 6)} ms, errors 0, cache hit {rng.randint(85, 95)} %"),
        _log(t(14), svc, "WARN", f"resolve {host} took {rng.randint(5001, 5012)} ms"),
        _log(t(20), node, "INFO", f"conntrack -S: insert_failed={rng.randint(3000, 9000)} (+{rng.randint(40, 90)}/min), drop=0"),
        _log(t(21), node, "INFO", f"nf_conntrack count {n} / max 262144"),
    ]
    opts, key = _choice(rng, "Гонка conntrack на параллельных A/AAAA по UDP (растёт insert_failed): NodeLocal DNSCache или single-request-reopen", [
        "CoreDNS не справляется с потоком запросов: добавить реплики CoreDNS и включить автоскейлинг по CPU",
        "Таблица conntrack на узле переполняется и пакеты отбрасываются: поднять nf_conntrack_max и уменьшить таймауты UDP-записей",
        "ndots:5 порождает лишние запросы по search-доменам: поставить ndots:1 и писать FQDN с точкой на конце",
    ])
    return {"scene_title": "Пять секунд тишины", "story": f"После переезда в облачный Kubernetes часть запросов {svc} замирает ровно на 5 секунд. "
                                                          "Всё упирается в резолв имён, но не всегда.",
            "prompt": "В чём причина?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("ops_k8s_qos_eviction", SPEC, "Kubernetes", "mark", 2.3, 2.75)
def _(rng):
    """При MemoryPressure kubelet ранжирует поды по превышению потребления над requests, а не по priorityClass;
    клоны различаются тем, где запрошено мало памяти: основной контейнер, BestEffort без resources или сайдкар."""
    svc = rng.choice(["payments-api", "checkout-api", "auth-api"])
    mode = rng.choice(["main", "besteffort", "sidecar"])
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
        agent = rng.choice(["log-shipper", "envoy-sidecar", "otel-agent"])
        lines += ["          resources:", "            requests: {cpu: 500m, memory: 1536Mi}", "            limits: {cpu: '1', memory: 2Gi}",
                  f"        - name: {agent}", f"          image: registry.local/{agent}:{_v(rng)}", "          resources:", "            requests:",
                  "              cpu: 50m", "              memory: 64Mi"]
        key = len(lines)
        tail = f"основной контейнер в пределах своих requests, {agent} съел {used}"
    batch = rng.choice(["report-batch", "etl-nightly", "export-job"])
    return {"scene_title": "Выселили не тех", "story": f"Узел ушёл в MemoryPressure. Kubelet выселил {svc} ({tail}, приоритет высокий), "
                                                       f"а {batch} с низким приоритетом и requests = limits остался работать.",
            "prompt": f"Нажмите на строку, из-за которой {svc} выселяется первым, несмотря на приоритет.",
            "panel": {"type": "code", "lang": "yaml", "lines": lines}, "key": key}


@family("ops_rb_error_budget", SPEC, "План отката", "choice", 2.3, 2.9)
def _(rng):
    d, early, late, spike = rng.choice([20, 21, 22]), rng.choice([1.2, 1.5]), rng.choice([7, 8, 9]), 4
    left = [100.0]
    for day in range(1, d + 1):
        left.append(left[-1] - (late if day > d - spike else early))
    rest, avg = 30 - d, (100 - left[-1]) / d
    days = range(d - 9, d + 1)
    panel = {"type": "chart", "x": [f"д{day}" for day in days], "marker": {"i": 9 - spike + 1, "label": f"релиз {_v(rng)}"}, "series": [
        {"name": "остаток бюджета ошибок, %", "axis": "left", "max": 100, "data": [round(left[day]) for day in days]},
        {"name": "расход бюджета за день, %", "axis": "right", "max": 10, "data": [late if day > d - spike else early for day in days]},
    ]}
    f = lambda v: f"{v:.1f}".replace(".", ",")
    opts, key = _choice(rng, f"При расходе {late} %/день бюджет кончится через ~{f(left[-1] / late)} дн., до конца окна: заморозить рискованные релизы", [
        f"Средний расход за окно — {f(avg)} %/день, бюджета хватит на ~{f(left[-1] / avg)} дн., а до конца окна {rest}: релиз можно выкатывать",
        f"Осталось {round(left[-1])} % бюджета: он и нужен на рискованные изменения — выкатить релиз сразу на весь трафик",
        "Перейти на окно SLO 90 дней: бюджет станет втрое больше, и нынешний всплеск ошибок в нём растворится",
    ])
    return {"scene_title": "Бюджет ошибок", "story": f"SLO доступности 99,9 % за 30 дней, идёт {d}-й день окна. Продукт просит завтра выкатить "
                                                     "большую фичу с миграцией данных; после переезда в облако ошибок стало больше.",
            "prompt": "Что решить по релизу?", "panel": panel, "options": opts, "key": key}
