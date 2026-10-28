<!-- Recovered from the linked ChatGPT branch. Heading markers were added only for readability. -->
<!-- This is a reusable task template; it is not automatically active unless the user explicitly asks to execute it. -->

# Codex CLI Prompt — настройка Hermes AI Platform после распаковки проекта

Ты работаешь внутри уже скачанной и распакованной папки проекта Hermes AI Platform.

Твоя задача — полностью подготовить проект к первому реальному развёртыванию, исходя из текущего содержимого репозитория.

ВАЖНО:

Не предполагай, что проект уже корректно настроен.

Сначала проанализируй фактическое содержимое текущей директории.

Используй существующие файлы проекта как источник истины.

Не переписывай всё с нуля без необходимости.

Если находишь placeholder/skeleton вместо рабочей реализации — замени его рабочим вариантом.

Не удаляй полезные наработки.

Все изменения должны быть воспроизводимыми и пригодными для Git.

Не клади реальные секреты в Git.

Не копируй приватные SSH-ключи на сервер.

Не создавай несколько независимых Hermes Core для ролей: базовая архитектура проекта — один Hermes Core + роли/profiles + skills + memory + policies.

## ЭТАП 1 — АУДИТ ПРОЕКТА

Сначала ничего не меняй.

Проверь текущую директорию:

структуру каталогов;

README;

INSTALLATION_GUIDE;

QUICKSTART;

installer;

Terraform;

Ansible;

Docker Compose;

prompts;

scripts;

configs;

docs;

GitHub Actions;

.gitignore.

Найди:

пустые файлы;

placeholder;

skeleton;

недописанные shell scripts;

нерабочие Terraform-конфигурации;

отсутствующие Ansible roles;

фиктивные Docker image names;

hardcoded secrets;

несогласованности между README и реальным проектом.

Особенно проверь, действительно ли присутствуют все prompt-этапы 00–31.

Создай:

PROJECT_AUDIT.md

В нём укажи:

Что уже готово.

Что является skeleton/placeholder.

Что отсутствует.

Что надо исправить до первого deployment.

Какие архитектурные противоречия найдены.

## ЭТАП 2 — ПЛАН РЕАЛИЗАЦИИ

После аудита составь конкретный план.

Раздели работы на:

### MUST HAVE

То, без чего нельзя сделать первый Minimal deployment.

### SHOULD HAVE

То, что желательно для Optimal.

### LATER

Advanced / Maximum функции.

Первый deployment должен быть ориентирован только на:

MINIMAL

То есть:

VPS;

OS hardening;

Docker;

Hermes Core;

Manager role;

DevOps role;

Coding role;

Research role;

базовая persistence;

health check.

Не реализовывай Maximum-функции, если они не нужны для Minimal.

После подготовки плана продолжай реализацию самостоятельно.

Не жди дополнительных подтверждений для безопасных локальных изменений внутри проекта.

Для действий, которые:

создают/удаляют облачные ресурсы;

стоят денег;

меняют удалённый production сервер;

меняют firewall/SSH на удалённом сервере;

сначала покажи команду и попроси подтверждение.

## ЭТАП 3 — ПРИВЕДИ РЕПОЗИТОРИЙ В ПОРЯДОК

Проверь и при необходимости создай/исправь:

README.md
INSTALLATION_GUIDE.md
QUICKSTART.md
CHANGELOG.md
ROADMAP.md
CONTRIBUTING.md
.gitignore

Структура должна быть примерно такой:

.
├── README.md
├── INSTALLATION_GUIDE.md
├── QUICKSTART.md
├── CHANGELOG.md
├── ROADMAP.md
├── CONTRIBUTING.md
├── Makefile
│
├── installer/
├── terraform/
├── ansible/
├── docker/
├── configs/
├── prompts/
├── profiles/
├── skills/
├── scripts/
├── tests/
├── docs/
└── .github/

Если текущая структура отличается, не ломай её без причины — приведи к логичной и документированной форме.

## ЭТАП 4 — GIT

Проверь:

git status

Если Git ещё не инициализирован:

git init

Установи основную ветку:

main

Проверь .gitignore.

Обязательно исключи:

.env
.env.*
!.env.example
*.pem
*.key
*.p12
.pfx
secrets/
credentials/
terraform.tfstate
terraform.tfstate.
.tfvars
!.tfvars.example
backup/
backups/
logs/

Не делай commit реальных секретов.

Если Git уже настроен — сохрани существующую историю.

## ЭТАП 5 — ПРОВЕРЬ ЛОКАЛЬНЫЕ ЗАВИСИМОСТИ

Определи ОС текущей машины.

Проверь наличие:

git
gh
ssh
curl
jq
terraform
ansible
docker
docker compose

На macOS при необходимости используй Homebrew.

Не устанавливай ничего автоматически без необходимости.

Если чего-то не хватает:

покажи, что отсутствует;

установи только то, что действительно нужно для выбранного workflow.

После этого создай:

scripts/check-local-requirements.sh

Он должен повторно проверять зависимости.

## ЭТАП 6 — СДЕЛАЙ НАСТОЯЩИЙ INSTALLER

Главный entrypoint:

./installer/install.sh

Он должен быть реально рабочим, а не placeholder.

Installer должен поддерживать два режима.

### MODE A — CREATE NEW VPS

Terraform создаёт новый VPS.

### MODE B — USE EXISTING VPS

Пользователь вводит:

IP/hostname;

SSH port;

SSH user;

SSH private key.

Terraform provisioning VPS в таком режиме пропускается.

## ЭТАП 7 — HETZNER КАК ПЕРВЫЙ ПОДДЕРЖИВАЕМЫЙ PROVIDER

Сначала полноценно реализуй Hetzner Cloud.

DigitalOcean/AWS можно оставить как будущие провайдеры, если их реализация увеличивает объём работ для Minimal.

Installer для Hetzner должен запросить:

HCLOUD_TOKEN

Но:

не записывать его в Git;

предпочтительно использовать environment variable;

разрешить пользователю ввести его интерактивно без echo.

Использовать:

HCLOUD_TOKEN

Terraform provider должен читать его из environment.

## ЭТАП 8 — SSH

Installer должен спросить:

SSH public key:
например:
~/.ssh/id_ed25519.pub

SSH private key:
например:
~/.ssh/id_ed25519

Проверить существование обоих файлов.

PUBLIC KEY:
используется Terraform/Hetzner для VPS.

PRIVATE KEY:
остаётся локально и используется Ansible.

Приватный ключ:

НЕ:

копировать в repository;

отправлять на VPS;

помещать в Docker;

помещать в Terraform state.

## ЭТАП 9 — HETZNER TERRAFORM

Создай рабочий:

terraform/hetzner/

Минимум:

versions.tf
provider.tf
variables.tf
main.tf
outputs.tf
terraform.tfvars.example

Использовать официальный Hetzner Cloud Terraform provider.

Terraform должен уметь создать:

SSH key;

server;

IPv4;

IPv6, если разумно;

labels.

Image:

Ubuntu 24.04

Installer должен позволять выбрать:

location;

server type;

hostname.

Если возможно, получай актуальные доступные Hetzner server types / locations через CLI/API или Terraform data sources, а не hardcode.

Если это существенно усложняет installer, обеспечь надёжные defaults и возможность override.

## ЭТАП 10 — РЕСУРСЫ СЕРВЕРА

Для Minimal предложи разумный default.

Целевая конфигурация нашего проекта:

примерно:

8 vCPU
16 GB RAM

=160 GB disk

НО:

не хардкодь несуществующий Hetzner flavor.

Проверь, какие актуальные server types доступны через Hetzner API/provider.

Покажи пользователю варианты.

Если выбран VPS с ресурсами ниже рекомендуемых:

вывести warning.

Не блокировать установку без серьёзной причины.

## ЭТАП 11 — TERRAFORM OUTPUT → ANSIBLE

После:

terraform apply

получи:

public IPv4;

hostname/server id.

Автоматически сгенерируй Ansible inventory.

Например:

ansible/inventory/generated.ini

Содержимое должно использовать:

ansible_host
ansible_user
ansible_port
ansible_ssh_private_key_file

Не добавляй приватный ключ в inventory как содержимое.

Только путь.

## ЭТАП 12 — ANSIBLE SERVER BASELINE

Сделай рабочий:

ansible/site.yml

Роли:

base
security
docker
hermes

Все роли должны быть идемпотентными.

## ЭТАП 13 — BASE ROLE

Выполнить:

apt update
package upgrades

Установить минимальные утилиты:

curl
ca-certificates
git
jq
unzip
rsync
htop
ufw
fail2ban

Не ставить лишнее.

Настроить:

timezone
locale при необходимости

## ЭТАП 14 — SECURITY HARDENING

Особенно осторожно.

До изменения SSH:

Сделать backup текущего sshd_config.

Определить активный SSH port.

Проверить, что public key действительно установлен.

Проверить новый SSH login.

Только после этого:

Before choosing the SSH directives, read the current root `AGENTS.md`, `ansible/README.md`, and `ansible/roles/base` SSH tasks; this historical template never overrides them. Do not set `PermitRootLogin no`: keep `prohibit-password` so project-required key-only root access remains available. Preserve the dashboard-only exception exactly as implemented: the root authorized key remains restricted, with forwarding limited to local TCP and `127.0.0.1:9119` (`AllowTcpForwarding local`, `PermitOpen 127.0.0.1:9119`, and the matching `permitopen` key option). Do not enable remote forwarding or other destinations. If the current instructions, role, or target host conflict, stop before changing SSH and report the discrepancy.

PermitRootLogin prohibit-password;

PasswordAuthentication no;

PubkeyAuthentication yes.

Перед reload:

sshd -t

Firewall:

default deny incoming
default allow outgoing

Разрешить:

SSH PORT

Не закрывать текущую SSH сессию.

Fail2ban:

включить sshd jail.

Настроить unattended-upgrades.

Не применять экзотический sysctl hardening, который может повредить Docker/networking.

Использовать conservative production defaults.

## ЭТАП 15 — СЕРВИСНЫЙ ПОЛЬЗОВАТЕЛЬ

Создай:

ai-agent

Для runtime Hermes.

Принцип:

least privilege.

Не выдавай ему полный passwordless sudo без необходимости.

Docker group рассматривать как root-equivalent.

Если Docker доступ роли DevOps действительно нужен:

документировать риск.

## ЭТАП 16 — DOCKER

Установи Docker Engine официальным поддерживаемым способом.

Предпочтительно Docker official apt repository, а не старый docker.io пакет Ubuntu, если это соответствует актуальной документации.

Установить:

Docker Engine
Docker Compose plugin

Создать:

/etc/docker/daemon.json

Настроить:

log rotation.

Например:

json-file max-size/max-file

Не использовать опасные experimental flags.

## ЭТАП 17 — HERMES

Это критический пункт.

Не используй фиктивный image:

hermes-agent

Сначала проверь актуальный официальный способ установки Hermes Agent от Nous Research.

Используй:

официальный repository;

официальную документацию;

официальный Docker image, если он существует и документирован;

либо официальный Docker build workflow.

Не придумывай image name/tag.

Зафиксируй выбранный способ в документации.

Создай структуру:

/opt/hermes/

или другой официальный/логичный runtime path.

Persistence должна включать:

config;

memory;

skills;

workspace;

logs, если нужно.

## ЭТАП 18 — ОДИН HERMES CORE

Архитектурное правило проекта:

один Hermes Core.

Не создавать:

hermes-manager container
hermes-devops container
hermes-coding container
hermes-research container

если официальная архитектура Hermes не требует этого.

Роли реализовать через поддерживаемые Hermes механизмы.

Сначала проверь реальные возможности Hermes:

profiles;

SOUL/system instructions;

skills;

memory;

session/config separation.

Если ранее разработанная терминология "profiles" не соответствует Hermes API/config:

адаптируй проект к реальным механизмам Hermes.

Документируй изменение.

## ЭТАП 19 — РОЛИ MINIMAL

Настрой минимум:

Manager
DevOps
Coding
Research

Каждая роль должна иметь:

назначение;

system/persona instructions;

skills;

memory scope;

permission assumptions.

Создай или исправь:

profiles/

или официальный эквивалент Hermes.

## ЭТАП 20 — MODEL PROVIDERS

Installer должен спросить, какой backend использовать.

Поддержать хотя бы:

OpenAI
Anthropic
OpenRouter

Не требовать все сразу.

Не записывать API keys в repository.

Сделай:

configs/.env.example

но реальные secrets хранить только локально/на сервере с:

chmod 600

Если Hermes поддерживает более безопасный механизм secrets — используй его.

## ЭТАП 21 — DOCKER COMPOSE

Создай рабочий docker-compose.yml только из действительно необходимых компонентов.

Для MINIMAL не тащи автоматически:

Prometheus
Grafana
Loki
Redis
Postgres
pgvector
Traefik

если Hermes для работы их не требует.

Minimal должен быть действительно минимальным.

Если Hermes самодостаточен:

Minimal =
Hermes Core

и только необходимые persistence volumes.

Postgres/pgvector/RAG — позже.

Monitoring — Optimal.

## ЭТАП 22 — DEPLOYMENT LEVELS

Installer должен поддерживать:

minimal
optimal
advanced
maximum

Но реально в этой задаче полностью реализуй:

MINIMAL.

Для остальных:

подготовь архитектуру;

hooks;

feature flags;

документацию.

Не расходуй время и complexity на реализацию Maximum сейчас.

## ЭТАП 23 — MINIMAL FLOW

Minimal installer должен сделать:

preflight;

получить параметры пользователя;

создать/выбрать VPS;

проверить SSH;

Ansible baseline;

hardening;

Docker;

Hermes Core;

базовые роли;

health validation;

deployment report.

## ЭТАП 24 — PREFLIGHT

Создай:

scripts/preflight.sh

Проверять локально:

Terraform;

Ansible;

SSH;

Git;

curl;

jq.

Для существующего VPS:

проверять SSH connection.

Для нового Hetzner:

проверять HCLOUD_TOKEN.

## ЭТАП 25 — DRY RUN

Добавь:

./installer/install.sh --dry-run

Dry-run должен:

собрать параметры;

показать будущие действия;

проверить prerequisites;

не создавать VPS;

не менять сервер.

## ЭТАП 26 — RESUME

Установка должна быть максимально идемпотентной.

Если install.sh упал посередине:

повторный запуск не должен:

создавать второй VPS;

ломать существующий сервер;

дублировать пользователей;

ломать Docker.

Использовать Terraform state + Ansible idempotency.

## ЭТАП 27 — VALIDATION

Создай:

scripts/validate.sh

После deployment проверить:

SSH login;

UFW;

fail2ban;

Docker service;

Docker containers;

Hermes health;

Hermes logs;

persistence directories;

роли/config.

Не считать installation успешным только потому, что docker compose вернул exit code 0.

## ЭТАП 28 — DEPLOYMENT REPORT

После успешной установки создать:

reports/deployment-report.md

Включить:

provider;

server name;

server IP;

server resources;

OS;

SSH user/port;

Hermes version/commit/tag;

Docker version;

deployment level;

роли;

health status;

paths;

команды управления.

НЕ записывать secrets.

## ЭТАП 29 — MAKEFILE

Создай удобные команды:

make preflight
make dry-run
make install
make validate
make status
make logs
make backup

Если команда пока не реализована полностью:

не делай фиктивную success-команду.

Либо реализуй,
либо явно сообщай "not implemented".

## ЭТАП 30 — QUICKSTART

QUICKSTART.md должен описывать реальный путь для Hetzner:

создать Hetzner Cloud Project;

создать Read/Write API Token;

подготовить SSH key;

export HCLOUD_TOKEN;

запустить installer.

Пример:

export HCLOUD_TOKEN='...'

./installer/install.sh

## ЭТАП 31 — INSTALLATION GUIDE

INSTALLATION_GUIDE.md должен подробно описывать:

### CREATE NEW VPS

Terraform + Ansible.

### EXISTING VPS

Ansible only.

Добавь troubleshooting:

HCLOUD_TOKEN invalid;

SSH key not found;

Terraform apply failed;

SSH timeout;

Ansible unreachable;

Docker failed;

Hermes unhealthy.

## ЭТАП 32 — GITHUB READY

Проверь:

.gitignore

GitHub Actions не должны делать реальный deployment.

CI должна безопасно выполнять:

shellcheck, если доступен;

terraform fmt/check;

terraform validate без credentials, если возможно;

ansible syntax-check;

docker compose config;

repository validation.

Не запускать terraform apply в PR.

## ЭТАП 33 — ВАЛИДАЦИЯ ПРОЕКТА

После изменений выполни всё, что возможно локально:

bash -n scripts/.sh installer/.sh
terraform fmt -check -recursive
terraform validate
ansible-playbook --syntax-check
docker compose config

Если какой-либо инструмент отсутствует:

укажи это в отчёте.

Исправь найденные ошибки.

## ЭТАП 34 — ФИНАЛЬНЫЙ ОТЧЁТ

Создай:

IMPLEMENTATION_REPORT.md

Включить:

Что было placeholder.

Что реализовано.

Что исправлено.

Какая версия Hermes используется.

Как запускается installer.

Как работает Hetzner provisioning.

Как работает existing VPS mode.

Какие secrets нужны.

Что входит в Minimal.

Что пока оставлено для Optimal/Advanced/Maximum.

Результаты локальных validation commands.

Известные ограничения.

## ФИНАЛЬНОЕ ПОВЕДЕНИЕ

После завершения не запускай реальный Terraform apply без моего подтверждения.

Подготовь проект до состояния, когда мне останется сделать примерно:

export HCLOUD_TOKEN='...'
cd <project>
./installer/install.sh

И installer сможет провести меня по созданию нового Hetzner VPS и Minimal deployment Hermes.

Если VPS уже существует:

installer должен позволить выбрать:

USE EXISTING VPS

и запросить:

IP/hostname;

SSH user;

SSH port;

SSH private key.

Главный критерий успеха:

проект не просто красиво выглядит, а действительно готов к первому Minimal deployment.
