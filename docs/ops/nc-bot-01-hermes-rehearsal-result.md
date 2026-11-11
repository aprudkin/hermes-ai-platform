# nc-bot-01 — результат подготовки Hermes rehearsal

Дата: 2026-10-27 UTC. Выполнен **только этап A** задания
`chatgpt-hermes-restore-rehearsal-checklist.md`, редакция 2.
Репозиторий обслуживания: `aprudkin/hermes-ai-platform`.

## 1. Итог по уровням

| Уровень | Результат |
| --- | --- |
| Подготовка A | **Частично.** Приватное место, host-side cgroup и filesystem smoke проверены; Docker-изоляция заблокирована отсутствием Docker |
| Архив / B1 | **Этап не выполнялся.** Источник архива не согласован, доставка/verify/restore-state не запускались |
| Offline runtime / B2 | **Не проверен.** Сохранённый образ отсутствует, не загружался и не запускался |
| Инициализация / C | **Не поручена и не выполнялась** |
| Production | **Не запускался.** Старый сервер, Telegram, jobs и ownership не затрагивались |

[Заполненный чеклист](nc-bot-01-hermes-rehearsal-checklist-status.md) содержит
66 пунктов: **19 PASS, 9 BLOCKED, 5 NOT TESTED, 33 N/A**.
N/A разделов 5–6 означает «вне этапа A», не выполненное восстановление.
[Policy и численные лимиты](nc-bot-01-hermes-rehearsal-policy.json) содержат
явно неисполняемый Docker-план с пустыми image/entrypoint, а не готовый launcher.

Разрешённые независимые работы завершены. Ключевые blockers:

1. Docker/Compose/containerd и отчёт подготовки общего Docker-хоста отсутствуют.
   Этот чеклист не разрешает их устанавливать, менять firewall или перезапускать
   общий runtime. Нужен отдельный этап окружения.
2. Без точного bundle/metadata неизвестны image identity/architecture/compression,
   дисковый пик и совместимость decoder/image store. Это условия допуска к B,
   а не причина отменять выполненную подготовку каталогов.
3. Нет разрешённого безвредного smoke image с digest и проверенным бинарником.
   Container barrier и effective inspect не проверены.
4. До доставки секретов нужны решение по шифрованию/допустимости хранения и
   согласованный срок/ответственный для всех секретосодержащих копий.

## 2. Контекст, источники и границы

Прочитаны применимые AGENTS, README, INSTALLATION_GUIDE, architecture, state-first,
personal-backup и backup-restore. Локальный checkout до работы был чистым.
Выбрана существующая committed ревизия, а не содержимое будущего архива:

- Git SHA: `17564ca3ba31ff0c33ff8bad7441272820be0147`.
- Helper: `scripts/hermes_backup_bundle.py`.
- SHA-256: `d19f118925ec3075b0b6eb48449335144ebfbf032f72b57a09cf4e35a578ce85`.
- Прочитаны verify, restore_state, layer_digest, validate_container и CLI dispatch.
  Рабочий файл совпал с committed bytes; checksum повторён на сервере,
  AST разобран точным серверным Python без исполнения helper.

Указанный в задании `docs/migration.md` в выбранной ревизии отсутствует.
Вместо выдуманного документа использованы фактические migration/recovery sections
state-first и backup-restore. Файлов с буквальными именами `standard-security-agent-checklist.md`
и `standard-environment-plan.md` среди выбранных источников нет. Фактический security
report прочитан в `example_bot/docs/ops/nc-bot-01-security-result.md`; прежний
environment plan был планом, не отчётом выполненной установки Docker.

Security baseline переиспользован без преувеличений: ops/sudo, root SSH no и
контрольный reboot проверены в предыдущем задании. MFA/резерв ключа, внешний IPv6,
полный внешний autoban и доставка alerts остаются там непроверенными/заблокированными.

GitHub прочитан только для поиска существующей задачи. Подходящей открытой issue
не найдено; closed backup/recovery issues не переоткрывались. Новая issue и публикации
не создавались из-за прямого запрета текущего чеклиста. Commit/push не выполнялись.
Это ограничение регистрации, а не блокер независимой подготовки A.

Не выполнялись Terraform/Ansible installer, capture старого сервера, загрузка архива,
image pull/load, Compose, изменения Docker/firewall, установка пакетов/host uv,
PostgreSQL, reboot, внешние вызовы с credentials Чеби или изменения example_bot.
Восстановленных instructions/skills/state не было; ничего из архива не исполнялось.

## 3. Фактическая инвентаризация

Fresh key-only SSH использовал ops/luk без ControlMaster, с pinned host key
и строгой проверкой. Sudo без прежнего cache подтвердил uid=0 через отдельно
согласованный скрытый ввод; root SSH не возвращался.

| Свойство | Наблюдение |
| --- | --- |
| ОС / архитектура | Debian 13 trixie, x86_64 |
| Ядро / CPU | 6.12.113+deb13-amd64; 4 vCPU |
| RAM | 8333348864 B всего; перед probe MemAvailable 7996968960 B |
| Swap | 0 |
| Root/run-dir FS | ext4 на обычном разделе; run-dir и дисковый TMPDIR на одной FS |
| Свободный диск | Внутри probe: 159618146304 B; это измерение момента, не зарезервированное место |
| Свободные inode | Внутри probe: 10283229 |
| /tmp | **tmpfs**, 4166676480 B; для verifier/restore не использовать |
| Cgroups | v2; cpu/io/memory/pids controllers доступны |
| Python | /usr/bin/python3, 3.13.5; фактический import compression.zstd неуспешен |
| GNU tar | 1.35; ACL/xattr flags и реальный roundtrip проверены |
| ACL tools | setfacl/getfacl отсутствуют; readback выполнен через установленную libacl |
| Docker / Compose / containerd | Бинарники/пакеты/socket/стандартные data paths отсутствуют |
| Workload | /root/example_bot и /opt/hermes отсутствуют по привилегированному preflight |
| Listeners | Только TCP/22 IPv4/IPv6, до/после без изменения |
| Failed units | Отсутствуют до и после probe |

Container names/networks/mounts/image IDs/tag mappings неприменимы к отсутствующему
runtime; полный Docker inspect не выполнялся. Произвольные чужие каталоги,
архивы и секреты не сканировались. Старый production не опрашивался, его бизнес-здоровье
не проверялось и не объявляется доказанным.

## 4. Подготовленное место и сохранённые артефакты

Run-dir:

`/srv/hermes-rehearsal/20261027T013444Z-ahmyve/`

Все каталоги — 0700 ops:ops, файлы — 0600; root имеет административный доступ.
Новый родитель `/srv/hermes-rehearsal` создан приватно; права `/srv` и чужих
каталогов не менялись. Проверены realpath, отсутствие symlink/collision и
непересечение с application paths.

| Подкаталог | Назначение / итог |
| --- | --- |
| incoming/ | Для будущей отдельно разрешённой доставки; сейчас пуст |
| verifier-tmp/ | Дисковый TMPDIR, не /tmp tmpfs; после теста пуст |
| results/ | Приватные численные результаты, inventory, scripts и отчёт |
| test-copy/ | Для минимальных обезвреженных копий; синтетический fixture удалён, каталог пуст |
| trusted/ | Pinned helper и доверенный host-probe, вне будущего restored tree |
| restored/ | **Не создан и отсутствует**, включая symlink |

В results сохранены host-probe.json, unit-effective.txt, helper.sha256,
trusted-revision.txt, filesystem.txt, disk.before.txt, inodes.before.txt,
guest-storage.txt, listeners.before/after.txt, runtime-inventory.txt, cleanup.txt
и точный одноразовый prepare.sh. Точная unit:
`hermes-prep-probe-ahmyve.service`. После завершения LoadState=not-found,
ActiveState=inactive; persistent service/timer не установлены.

Локальные приватные результаты: `/tmp/nc-hermes-stageA.AHmYVE/`.
Контроллерные sshai receipts: a9792 — inventory, a9793 — staging,
a9794 — финальный readback. Они не включены в Git.
Временный серверный staging и локальный secret-input helper удалены; sudo cache очищен.

## 5. Что реально проверено

### Host-side ограничения — не Docker isolation

Безопасный доверенный probe выполнялся от UID/GID 1000 в отдельной transient unit.
Прочитаны настройки systemd и реальные cgroup/process values изнутри:

| Контроль | Фактическое значение |
| --- | --- |
| CPU | cpu.max = 100000 100000, то есть 1 CPU |
| RAM max / high | 2147483648 / 1610612736 B |
| Swap / Tasks | 0 / 128 |
| IOWeight / nice / I/O class | 10 / 10 / idle |
| RuntimeMaxSec | 60, readback RuntimeMaxUSec=1min |
| UID / CapEff / NoNewPrivs | 1000 / 0 / 1 |
| Network namespace | Только lo, IPv4 route table пустая |
| Write boundary | ProtectSystem=strict, ReadWritePaths только run-dir |
| Дополнительные flags | PrivateNetwork, PrivateDevices, ProtectHome, NoNewPrivileges |

Дочерние GNU tar процессы находились под ресурсной границей unit.
Это проверка effective ограничений, **не стресс-тест OOM/CPU/disk exhaustion**.
Не заявляются actual I/O throughput guarantees для виртуального диска.

Не выполнялись Docker inspect, container seccomp/AppArmor/UID/network smoke.
Успех systemd PrivateNetwork **не доказывает** Docker network none или защищённость
будущего контейнера. Default daemon logging/security settings не менялись.

### Tar, ACL/xattr и независимые файлы

Внутри test-copy создан один крошечный синтетический файл без данных Чеби.
На него установлены POSIX ACL и user.hermes_rehearsal_probe. GNU tar выполнил
create → extract с ACL/xattrs → compare. Затем независимо проверены:

- точные bytes файла;
- равенство ACL через libacl acl_get_file/acl_cmp;
- точное значение user xattr;
- отсутствие общей пары device/inode у исходного и извлечённого файла.

Архив fixture, файлы и их временные подкаталоги удалены только по собственным
известным путям. Ничего не восстанавливалось в restored.
Этот тест **не проверяет** security.* attributes, произвольные archived UID/GID,
SQLite/WAL, нативные зависимости или реальные ACL конкретного bundle.

Первый ввод sudo не подтвердился до запуска prepare.sh; /srv run-dir тогда
ещё не создавался. Повторный доверенный ввод был успешен. Локальный ShellCheck
inventory сначала остановился на source /etc/os-release; до запуска заменено
чтением только нужных полей. Проверки не обходились, слабые разрешения не добавлялись.

## 6. Ресурсный бюджет и допуск к B

### Численные границы

- Root/run-dir/TMPDIR: сохранять минимум **34359738368 B (32 GiB)** свободными
  и **1000000 inode**. Это порог прекращения своей работы, не filesystem reservation.
- По измерению probe остаток сверх disk floor: **125258407936 B**.
  Это верхний доступный бюджет для расчёта, **не доказательство, что архив поместится**.
- Host-side verifier/restore: CPU 100%, MemoryMax 2 GiB, MemoryHigh 1.5 GiB,
  MemorySwapMax 0, TasksMax 128, nice 10, IOWeight 10, ionice idle.
- Перед тяжёлым host-side запуском MemAvailable минимум **4 GiB**, из которых
  **2 GiB** остаётся запасом ОС/другой нагрузки. Обновить расчёт при появлении example_bot/БД.
- Не более одной тяжёлой операции одновременно. До B нужен disk watchdog,
  останавливающий только свою unit при пересечении floors; такой аварийный stop
  на реальном тяжёлом процессе в A не испытывался.
- Плановые deadlines: verify 3600 s, restore 10800 s, Docker load client 3600 s,
  smoke 60 s. В A проверен только безопасный 60-секундный unit deadline как настройка;
  это не измерение скорости реального восстановления.
- Кандидат контейнера: 1 CPU, 1 GiB RAM, memory+swap 1 GiB, 128 PID, tmpfs 64 MiB,
  local logs 10m × 3. Effective container limits пока BLOCKED.
- Docker/containerd пути/FS пока неизвестны: до B установить их фактические mounts,
  проверить те же floors на каждой FS и не считать общий запас дважды, если FS одна.

### Формула пика по выбранному коду

Обозначения:

- A — доставленный сжатый bundle.
- P — все распакованные payloads, включая state.tar, image.tar и metadata.
- E — фактическое размещение извлечённого состояния.
- Dpeak / Dretained — пиковый / остающийся прирост image store с учётом backend.
- T — отдельная разрешённая тестовая копия.
- R — свободный резерв, заданный выше.

При последовательных операциях на одной FS:

| Фаза | Одновременно существующие bytes, без R |
| --- | --- |
| Явный verify full | A + P |
| Повторный verifier внутри restore-state | 2A + P |
| Извлечение после verifier | 2A + P + E |
| После завершения restore-state | A + P + E |
| Импорт образа | A + P + E + Dpeak |
| Offline test copy | A + P + E + Dretained + T |

Итого: max(2A + P + E, A + P + E + Dpeak,
A + P + E + Dretained + T) + R. Добавить любую отдельно запланированную копию,
filesystem allocation/sparse/hardlink overhead и запас под logs/metadata.
Число inode считать по реальным деревьям, а не из сжатых bytes.

Явный verify full и restore-state дают **два последовательных полных прохода**,
а не одновременно два verifier payload staging. Private copy A живёт до конца
restore-state; payloads P остаются в restored/.recovery. Код проверен по SHA выше.

Размеры A/P/E/D/T не получены: архив не открывался и источник не согласован.
Измеренный свободный диск или размер старого compressed archive не заменяют расчёт.

### Import — отдельная операция

Cgroup клиента docker load не ограничивает работу общего daemon. До импорта:
проверить archive tags/identity и конфликты с image store, прогноз Dpeak, резервы
Docker/containerd FS и read-only baseline соседней нагрузки. Наблюдать диск/I/O
во время импорта без изменения общего daemon. По таймауту/disconnect сначала
выяснять фактические mappings/import outcome; не повторять вслепую и не считать
разрыв клиента отменой. Установка/смена image store и global prune не разрешены.

## 7. Хранение, Docker-план и условия продолжения

Guest lsblk показывает обычный ext4-раздел, без наблюдаемого LUKS/dm-crypt.
Шифрование на стороне провайдера не проверено. 0700/0600 не являются шифрованием.
Пока сохранены только trusted code, синтетические результаты и операционная
диагностика. Архивов, memory/session DB и credentials Чеби нет.

До B требуется решение владельца: защищённое место либо явная допустимость
хранения plaintext recovery data; срок до конкретного события/даты, ответственный,
перечень incoming/private verifier/.recovery/restored/test copies/logs/snapshots.
Никакого scheduled cleanup нет. Не обещается secure erase на SSD/CoW.

Несекретные артефакты A сохраняются до принятой замены подготовки или закрытия
репетиции владельцем. Ответственный — владелец сервера; агент удаляет только
по соответствующему поручению. Исходные независимые backups не затрагиваются.

Docker-план в policy содержит network none, no ports, no-healthcheck, restart no,
cap-drop ALL, no-new-privileges, read-only rootfs, private namespaces, UID 65534,
ограниченный tmpfs и per-container logs. Нельзя исполнять этот план, пока:

1. Отдельно не подготовлены Docker/Compose и выбранный backend, с отчётом.
2. Не согласован безопасный existing/public image с точным digest/ID и проверенным
   absolute entrypoint; Config.Env образа проверен до исполнения.
3. Не проверены actual inspect, UID/CapEff/NNP/seccomp/AppArmor и сеть именно контейнера.
4. Перед B не согласованы exact full bundle source, хранение/retention,
   architecture/compression compatibility и ресурсный бюджет.

Восстановленные Compose, SOUL, AGENTS, skills и scripts остаются данными проверки.
Не запускать compose.restore.json, gateway, scheduler, hermes setup или новый пустой
профиль. B1/B2 не разрешают C; никакой этап не разрешает production cutover автоматически.

## 8. Матрица пунктов

| Пункт | Статус | Метод | Доказательство / ограничение |
| --- | --- | --- | --- |
| 3.1 | BLOCKED | AGENTS/операционные docs, Git SHA, security report | Прочитан фактический отчёт безопасности; выбран чистый commit 17564ca3ba31ff0c33ff8bad7441272820be0147. Docker ещё не подготовлен, отчёта его подготовки нет; standard-* и docs/migration.md в выбранных источниках отсутствуют. |
| 3.2 | PASS | Fresh SSH -S none + sudo без cache | ops/luk, pinned host key и строгая проверка; sudo подтвердил uid=0. Root SSH не возвращался. |
| 3.3 | BLOCKED | uname, df/free, lsblk, cgroup, package/binary inventory | Debian 13 x86_64, 4 vCPU, 8333348864 B RAM, cgroup v2/ext4. Docker/Compose/containerd отсутствуют: их версии/backend проверить нельзя. |
| 3.4 | PASS | Привилегированный preflight, package/socket/path metadata, ss | Docker/socket/data-root и runtime paths example_bot/Hermes отсутствуют; контейнерных ресурсов нет; listeners только TCP/22. Env/секреты не выводились. |
| 3.5 | N/A | Инвентаризация новой машины | Другой application workload здесь не обнаружен; running/health/restart count неприменимы. Старый production не запрашивался. |
| 3.6 | PASS | realpath/lstat guards, exclusive mkdir | Новый /srv/hermes-rehearsal/20261027T013444Z-ahmyve; symlink/collision не допущены; чужие mounts/владельцы/права не менялись. |
| 3.7 | NOT TESTED | GNU tar 1.35; Python 3.13.5; synthetic ACL/xattr roundtrip | Tar/ACL/user.xattr прошли реальный readback. compression.zstd отсутствует; совместимость decoder с точным архивом неизвестна. Для zstd-слоёв B будет BLOCKED. |
| 3.8 | BLOCKED | Docker отсутствует; metadata exact image не передана | Image store и OCI identity compatibility не проверены; backend не менялся и Docker не устанавливался. |
| 3.9 | NOT TESTED | Host x86_64 установлен; archive metadata отсутствует | Архитектура сохранённого образа/нативных зависимостей и совместимость Debian с ними не доказаны. |
| 3.10 | BLOCKED | Разбор verify/restore_state выбранного SHA; формула пика в отчёте | Пик описан по коду, включая private archive и .recovery. Числа A/P/E/D/T неизвестны без согласованного архива/metadata; достаточность не заявлена. |
| 3.11 | PASS | df/statvfs, /proc/meminfo | Доступный root disk около 159618146304 B, свободно 10283229 inode; численные резервы записаны. Точный archive budget остаётся BLOCKED. |
| 3.12 | BLOCKED | Подготовленная policy; Docker отсутствует | Кандидат smoke: 1 CPU/1 GiB/128 PID, без swap; effective container limits ещё не проверены. Это не production sizing. |
| 3.13 | NOT TESTED | Один малый probe; headroom до/после | Параллельных тяжёлых операций не было. Для B записаны concurrency=1 и пороги; остановка тяжёлой операции по disk watchdog ещё не проверена. |
| 3.14 | PASS | nc-bot-01-hermes-rehearsal-policy.json | Заданы disk/inode/RAM floors, CPU/RAM/PID caps и отдельные timeouts. До B требуются свежая сверка Docker filesystems, archive budget и запуск guards; планы не выданы за испытание restore. |
| 3.15 | PASS | Отдельная systemd cgroup; readback из процесса и systemctl | Фактически CPU 100000/100000, RAM 2 GiB/high 1.5 GiB, swap=0, PID=128, IOWeight=10, nice=10, ionice idle; RuntimeMax=60s. Probe и дочерние tar вне общей нагрузки. |
| 3.16 | PASS | Отдельный план import в отчёте | Docker daemon не считается ограниченным cgroup клиента. Импорт требует отдельного headroom/I/O наблюдения и выяснения исхода после disconnect; сейчас не выполнялся. |
| 4.1 | PASS | install -d + stat | Run-dir и подкаталоги 0700 ops:ops, файлы 0600, umask 077; доступ только ops/root. |
| 4.2 | PASS | Directory readback | incoming/verifier-tmp/results/test-copy/trusted созданы отдельно. restored отсутствует, incoming/verifier-tmp/test-copy пусты после probe. |
| 4.3 | BLOCKED | lsblk/findmnt | Guest ext4 непосредственно на разделе, гостевое шифрование не наблюдается; provider encryption не проверено. Решения владельца о хранении секретов нет; доставка B заблокирована, каталог A допустим. |
| 4.4 | BLOCKED | План хранения в policy/result | Срок/ответственный для будущих секретосодержащих копий не согласованы; архивов нет. Несекретные A-артефакты сохраняются до замены/закрытия задачи владельцем; cleanup timer не создавался. |
| 4.5 | BLOCKED | Официальные Docker docs + неисполняемая policy | Ограничения запуска описаны; Docker, разрешённый image digest и безопасный entrypoint не выбраны/не проверены. Это не готовая проверенная команда запуска. |
| 4.6 | BLOCKED | Docker отсутствует | Безвредный Docker smoke не запускался; образ не загружался. Host-side private-network probe не подменяет container isolation. |
| 4.7 | PASS | Scope/code review и фактический resource ledger | Docker socket, host PID/IPC/network, устройства, admin home и чужие mounts не подключались. Секреты приложений тесту не передавались. |
| 4.8 | NOT TESTED | Контейнер отсутствует | Container inspect/UID/seccomp/AppArmor не проверены. UID=1000, CapEff=0, NNP=1 установлены только для отдельного host-side probe. |
| 4.9 | NOT TESTED | Контейнер отсутствует; host-side netns проверен отдельно | Host-side процесс видел только lo и пустую route table. Container network/port/socket barrier пока не доказан. |
| 4.10 | PASS | Удаление своих fixtures и transient unit; readback | Синтетические файлы/tar удалены; unit not-found/inactive, staging удалён. Контейнеров/образов/сетей не создавалось. |
| 5.1 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 5.2 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 5.3 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 5.4 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 5.5 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 5.6 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 5.7 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 5.8 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 5.9 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 5.10 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 5.11 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 6.1 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 6.2 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 6.3 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 6.4 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 6.5 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 6.6 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 6.7 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 6.8 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 6.9 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 6.10 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 6.11 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 6.12 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 6.13 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 6.14 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 6.15 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 6.16 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 6.17 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 6.18 | N/A | Вне разрешённого этапа A | Этап B/B1/B2 не поручен и источник архива не согласован. C требует отдельного поручения; этот пункт не выполнялся. |
| 7.1 | PASS | Пути, имена и ledger | Каталог репетиции отделён от будущих данных example_bot; /opt/hermes не создавался. Имена контейнеров только запланированы, credentials отсутствуют. |
| 7.2 | PASS | Docker/network ledger | Docker сетей и присоединений к application/DB networks нет; host firewall не менялся. |
| 7.3 | N/A | Контейнер не создан | Daemon logging defaults не менялись. В будущем smoke policy задан local driver с 10m/3; фактической container-проверки пока нет. |
| 7.4 | PASS | Зафиксированная административная граница | Rootful Docker не объявлен изоляцией от host admin; доступ к docker group/socket никому не выдавался. |
| 7.5 | PASS | cmp listeners before/after; systemctl failed; runtime paths | Listeners не изменились, failed units нет, другой application workload отсутствует. Бизнес-функции старого production не проверялись. |
| 9.1 | PASS | Policy ledger и private run-dir | Записаны собственные пути и transient unit; списки container/image/tag/network/volume IDs пусты, выдуманных IDs нет. |
| 9.2 | PASS | Явная очистка own fixtures/unit/staging | Удалены только свои синтетические копии и staging; образы/общие layers не затрагивались. |
| 9.3 | PASS | Выполненные скрипты | Global prune, compose down и удаление volumes не выполнялись. |
| 9.4 | N/A | Архив не доставлялся, restored отсутствует | Секретосодержащих copies/TMPDIR payloads нет; решение об их хранении требуется до B. |
| 9.5 | PASS | Final readback | Своих работающих services/timers/listeners нет; файлы и каталоги приватны; host не перезагружался и runtime не стартовал. |
| 9.6 | N/A | Host-side probe завершился успешно | Первый отказ sudo был до создания run-dir; повтор с доверенным вводом успешен. Частичного восстановления/общего rollback нет. |

## 9. Проверки, очистка и доставка

- Bash syntax, ShellCheck и Python compile для подготовленных probe scripts прошли.
- Серверный trusted helper проверен по checksum и AST, не выполнялся с архивом.
- Фактический host-side probe PASS подтверждён readback kernel/unit/filesystem.
- Unit удалён; staging/fixtures очищены. Собственных контейнеров, images, tags,
  networks, volumes, автозапуска или listener не создавалось.
- Исходный пользовательский файл в Downloads сохранён; код/инструкции Hermes repo
  не менялись. Добавлены только локальные отчёт, заполненная копия и JSON policy.
- Независимое ревью не проводилось; полного repository readiness gate с
  Terraform/Ansible/Docker не выполнялось и его успех не заявляется.
- Commit/push, issue creation/comments и публикация приватных результатов запрещены
  этим заданием и не выполнялись.

Обезличенные файлы доступны локально в docs/ops и приватно в results run-dir.
Raw inventory хранится отдельно; в отчёте нет IP, переписок, tokens, memory contents
или полного Docker inspect.

## 10. Проверенные внешние источники

Поиск выполнен через Exa; использованы первичные документы без отправки private
source/state/credentials. Фактические свойства установленного хоста проверены отдельно.

- [Docker container run](https://docs.docker.com/reference/cli/docker/container/run/) —
  entrypoint, no-healthcheck, read-only, limits, security-opt, per-container logs.
- [Docker none driver](https://docs.docker.com/engine/network/drivers/none/) —
  только loopback; это не доказательство конфигурации ещё не созданного контейнера.
- [Containerd image store](https://docs.docker.com/engine/storage/containerd/) —
  fresh Docker 29+ default, classic/store identity differences, compressed + expanded
  layer storage и отдельный containerd data path. Никаких настроек по этой странице не применяли.
- [Python 3.14 compression.zstd](https://docs.python.org/3.14/library/compression.zstd.html) —
  модуль добавлен в 3.14; установленный 3.13.5 фактически его не импортирует.
