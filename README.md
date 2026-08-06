# ardupilot-mcp

MCP-сервер, що надає запити й відповіді про параметри прошивки ArduPilot — пошук за ключовими
словами, семантичний пошук і порівняння між апаратами — для Claude Desktop, Claude Code та інших
MCP-клієнтів. Працює на 100% локально поверх сховища SQLite + LanceDB, зібраного зі згенерованої
Sphinx HTML-документації параметрів ArduPilot.

*[English version below](#ardupilot-mcp-english) — англійська версія нижче.*

## Можливості

- **Точний пошук за іменем** — знайти параметр за назвою з повними метаданими (опис, одиниці
  вимірювання, діапазон, значення enum/бітмаски).
- **Пошук за ключовими словами** — на базі FTS5, обмежений одним апаратом або по всіх увімкнених.
- **Семантичний пошук** — на базі ембедингів (`intfloat/multilingual-e5-small`), з тим самим
  обмеженням області; параметр, знайдений у кількох апаратах, дедуплікується й позначається тим,
  де саме він збігся.
- **Порівняння між апаратами** — порівняння визначення параметра поле за полем між двома апаратами
  (наприклад, «чим `LOG_BITMASK` відрізняється між plane і copter?»).
- **Тільки локально** — жодних мережевих запитів під час роботи, окрім одноразового завантаження
  моделі ембедингів.

Кожен апарат зберігає рівно одну версію прошивки за раз — ту, на яку зараз указує URL у Реєстрі
апаратів (Vehicle Roster). Див. розділ «Реєстр апаратів» нижче.

## Вимоги

Перед початком на комп'ютері потрібні дві речі:

1. **Docker Desktop** — завантажте з [docker.com](https://www.docker.com/products/docker-desktop/)
   і встановіть як звичайну програму. Це єдиний спосіб запуску — Python чи інші інструменти
   розробника встановлювати не треба.
2. **Git** — потрібен, щоб завантажити проєкт. На Mac уже встановлений (або запропонує
   встановитися при першому запуску `git`). На Windows завантажте з
   [git-scm.com](https://git-scm.com/download/win) і встановіть з усіма параметрами за
   замовчуванням.
3. **Термінал** — на Mac відкрийте програму «Terminal» (знайдіть через Spotlight, `Cmd+Space`).
   На Windows відкрийте «Command Prompt» або «PowerShell» (пошук у меню «Пуск»).

Усі команди нижче вводяться у це вікно термінала, по одній, з натисканням Enter.

## Покрокове налаштування

1. Завантажте проєкт із GitHub. У терміналі спершу перейдіть туди, де хочете тримати теку
   проєкту, потім склонуйте репозиторій:

   **macOS / Linux:**

   ```bash
   cd ~/Documents
   git clone https://github.com/Chevit/ardupilot-mcp.git
   cd ardupilot-mcp
   ```

   **Windows (Command Prompt або PowerShell):**

   ```powershell
   cd %USERPROFILE%\Documents
   git clone https://github.com/Chevit/ardupilot-mcp.git
   cd ardupilot-mcp
   ```

   Тепер запам'ятайте **повний шлях** до цієї теки — він знадобиться для налаштування Claude
   Desktop. Дізнатися його:

   - **macOS / Linux:** виконайте `pwd` → щось на кшталт `/Users/ваше-ім'я/Documents/ardupilot-mcp`
   - **Windows:** виконайте `cd` (без аргументів) → щось на кшталт
     `C:\Users\ваше-ім'я\Documents\ardupilot-mcp`

   > Уже маєте теку проєкту (вам її передали, без git)? Тоді просто перейдіть у неї:
   > `cd path/to/ardupilot-mcp`. Зазвичай можна перетягнути теку у вікно термінала замість того,
   > щоб набирати шлях вручну.
   >
   > Пізніше, щоб оновитися до нової версії: `git pull` у цій самій теці, потім повторіть крок 2.

2. Зберіть застосунок (потрібно один раз, або після оновлення):

   ```bash
   docker compose build
   ```

   Перший раз це триває кілька хвилин. Дочекайтеся завершення.

3. Завантажте дані параметрів — одна команда тягне всі увімкнені апарати з Реєстру апаратів
   (`plane` і `copter` за замовчуванням) напряму з ardupilot.org:

   ```bash
   docker compose run --rm mcp-stdio ardupilot-refresh --all --build-vectors
   ```

   Апарат і версія прошивки визначаються автоматично. Потрібні лише окремі апарати з реєстру —
   назвіть їх через `--roster` (працює й для апаратів із `enabled: false`, які пропускає `--all`):

   ```bash
   docker compose run --rm mcp-stdio ardupilot-refresh --roster plane --build-vectors
   docker compose run --rm mcp-stdio ardupilot-refresh --roster plane copter --build-vectors
   ```

   Потрібна сторінка, якої немає в реєстрі?

   ```bash
   docker compose run --rm mcp-stdio ardupilot-refresh --url https://ardupilot.org/plane/docs/parameters.html --build-vectors
   ```

   > Немає інтернету на цій машині, або треба зафіксувати конкретну збережену сторінку? Відкрийте
   > посилання вище у браузері, зробіть «Save Page As…» у теку `data/ardupilot-docs/` всередині
   > проєкту (створіть її, якщо немає), потім запустіть ту саму команду з
   > `--html "data/ardupilot-docs/<назва збереженого файлу>.html" --vehicle plane --firmware-version 4.8.0 --source-url https://ardupilot.org/plane/docs/parameters.html`
   > замість `--url ...`.

Готово. Наступний розділ пояснює, як цим користуватися.

## Використання з Claude Desktop

Цей застосунок — «інструмент», який викликає Claude. Ви не запускаєте його самі: ви кажете Claude,
де його знайти, а далі спілкуєтеся з Claude як зазвичай.

### Крок 1 — знайдіть файл `claude_desktop_config.json`

Найпростіше: у Claude Desktop відкрийте **Settings → Developer → Edit Config** — файл відкриється
у редакторі. Якщо його немає, Claude Desktop створить порожній.

Або відкрийте його вручну:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
  (тобто `C:\Users\ваше-ім'я\AppData\Roaming\Claude\claude_desktop_config.json`)
- **Linux:** `~/.config/Claude/claude_desktop_config.json`

### Крок 2 — дізнайтеся свій шлях до `docker-compose.yml`

Це шлях до теки з кроку 1 налаштування, плюс `/docker-compose.yml` у кінці:

- **macOS / Linux:** `/Users/ваше-ім'я/Documents/ardupilot-mcp/docker-compose.yml`
- **Windows:** `C:\Users\ваше-ім'я\Documents\ardupilot-mcp\docker-compose.yml` — але у JSON кожен
  зворотний слеш треба **подвоїти**, тобто записати як
  `C:\\Users\\ваше-ім'я\\Documents\\ardupilot-mcp\\docker-compose.yml`.
  (Або використайте звичайні слеші: `C:/Users/ваше-ім'я/Documents/ardupilot-mcp/docker-compose.yml`
  — Docker це теж розуміє, і подвоювати нічого не треба.)

### Крок 3 — додайте запис у файл

**Випадок A — файл порожній або в ньому `{}`** (жодних MCP-серверів ще немає). Замініть увесь
вміст файлу на це:

```json
{
  "mcpServers": {
    "ardupilot": {
      "command": "docker",
      "args": ["compose", "-f", "/Users/ваше-ім'я/Documents/ardupilot-mcp/docker-compose.yml", "run", "--rm", "mcp-stdio"]
    }
  }
}
```

Windows-версія того самого:

```json
{
  "mcpServers": {
    "ardupilot": {
      "command": "docker",
      "args": ["compose", "-f", "C:\\Users\\ваше-ім'я\\Documents\\ardupilot-mcp\\docker-compose.yml", "run", "--rm", "mcp-stdio"]
    }
  }
}
```

**Випадок B — у файлі вже є блок `"mcpServers"` з іншими серверами.** Не замінюйте файл цілком —
додайте `"ardupilot"` як ще один запис **усередині** наявного `"mcpServers"`, і не забудьте кому
після попереднього запису:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/ваше-ім'я/Documents"]
    },
    "ardupilot": {
      "command": "docker",
      "args": ["compose", "-f", "/Users/ваше-ім'я/Documents/ardupilot-mcp/docker-compose.yml", "run", "--rm", "mcp-stdio"]
    }
  }
}
```

(`"filesystem"` тут — просто приклад того, що у вас уже могло бути. Залиште свої записи як є,
допишіть лише `"ardupilot"`.)

> Три найчастіші помилки у цьому файлі:
>
> 1. **Забута кома** між записами серверів — Claude Desktop мовчки проігнорує весь файл.
> 2. **Зайва кома** після останнього запису — JSON цього не дозволяє.
> 3. **Одинарний зворотний слеш** у шляху Windows — треба `\\`, а не `\`.
>
> Деякі MCP-клієнти не враховують поле `cwd`, через що `docker compose` падає з помилкою
> `no configuration file provided: not found`, бо не може знайти `docker-compose.yml`.
> Передача `-f <повний шлях до docker-compose.yml>` це обходить — працює незалежно від робочої
> теки клієнта. Тому шлях тут має бути **повним (абсолютним)**, а не відносним.

### Крок 4 — перезапустіть і перевірте

1. Повністю закрийте Claude Desktop (на macOS — `Cmd+Q`, не просто закрити вікно) і відкрийте
   знову.
2. Переконайтеся, що **Docker Desktop запущений** — без нього сервер не стартує.
3. Запитайте у Claude щось на кшталт «що робить параметр RC_OPTIONS?» — Claude скористається цим
   інструментом автоматично.

## Щоденне використання: запуск без перезбирання

`docker compose build` потрібен **лише один раз** — і потім тільки після `git pull` або зміни
`Dockerfile`/залежностей. Дані параметрів лежать у теці `data/` і переживають зупинку та
видалення контейнерів, тож `ardupilot-refresh` теж не треба повторювати (хіба що хочете свіжішу
версію прошивки).

**Якщо ви користуєтесь Claude Desktop (stdio):** запускати нічого не треба. Claude Desktop сам
стартує контейнер щоразу, коли відкривається, і зупиняє його при виході — тому побачити
`ardupilot-mcp` серед запущених контейнерів між сесіями ви й не повинні. Це нормально. Єдина
умова — **Docker Desktop має бути запущений** до старту Claude Desktop. Після перезавантаження
комп'ютера: відкрийте Docker Desktop, дочекайтеся, поки він покаже «Engine running», потім
відкрийте Claude Desktop. Якщо Claude каже, що сервер не стартував — саме це майже завжди й
причина.

**Якщо ви користуєтесь спільним HTTP-сервером:** після зупинки чи перезавантаження підніміть його
знову — образ уже зібраний, перезбирання не буде:

```bash
docker compose up -d mcp-http
```

Корисні команди у теці проєкту:

```bash
docker compose ps              # чи працює mcp-http зараз
docker compose logs mcp-http   # логи, якщо щось пішло не так
docker compose stop mcp-http   # зупинити (дані лишаються)
docker compose start mcp-http  # підняти зупинений контейнер назад
```

Сервіс `mcp-http` має `restart: unless-stopped`, тож після перезавантаження комп'ютера він
підніметься сам, щойно стартує Docker Desktop — крім випадку, коли ви зупинили його вручну через
`docker compose stop`.

## Додатково: запуск як спільного сервера

Якщо потрібно, щоб один комп'ютер запускав це, а клієнти Claude інших людей підключалися до нього
мережею, запустіть довгоживучу версію:

```bash
docker compose up -d mcp-http
```

Інші тоді вказують своєму клієнту Claude адресу `http://<адреса-цього-комп'ютера>:8000/mcp`
замість команди `docker compose run` вище. Вбудованого логіну/пароля немає, тому робіть це лише в
мережі, якій довіряєте (домашня мережа, VPN тощо) — не виставляйте у відкритий інтернет.

## Додатково: запуск без Docker

Якщо волієте запускати напряму через Python замість Docker, потрібні
[`uv`](https://docs.astral.sh/uv/) і Python 3.10+. Далі:

```bash
uv sync
uv run python -m ardupilot_mcp.ingest --all --build-vectors
uv run python -m ardupilot_mcp.server
```

`--all` тягне всі увімкнені апарати з Реєстру апаратів; `--roster plane copter` — лише названі
(будь-які імена з реєстру, навіть вимкнені). Для сторінки поза реєстром апарат і версія
прошивки визначаються автоматично з URL і тексту сторінки: `uv run python -m ardupilot_mcp.ingest
--url https://ardupilot.org/plane/docs/parameters.html --build-vectors`. Передайте
`--vehicle`/`--firmware-version`, щоб перевизначити, або замініть `--url <url>` на `--html
"<шлях>" --vehicle plane --firmware-version 4.8.0 --source-url
https://ardupilot.org/plane/docs/parameters.html`, щоб імпортувати вже завантажену сторінку
замість того, щоб тягнути її з мережі.

Консольні точки входу (`pyproject.toml`): `ardupilot-mcp` → `server:main`,
`ardupilot-refresh` → `ingest:main`.

## Реєстр апаратів (Vehicle Roster)

Які апарати існують, їхні URL-джерела та чи тягне їх `--all` — усе це живе у **Реєстрі апаратів**
(`vehicles.json`, запакований разом із застосунком). З коробки шість апаратів: `plane` і `copter`
увімкнені; `rover`, `sub`, `blimp` і `antennatracker` присутні, але вимкнені.

Щоб змінити URL, зафіксувати апарат на старішій версії прошивки (ArduPilot публікує версіоновані
сторінки на кшталт `parameters-Copter-stable-V4.7.0.html` для попередніх релізів) або
увімкнути/вимкнути апарат: покладіть власний `vehicles.json` у `data/` (теку, яку Docker уже
монтує) — він повністю замінює запакований реєстр, тож включіть у нього всі апарати, які вам ще
потрібні. `--vehicles-config PATH` вибирає файл реєстру поза `data/` для одного запуску.

Запис `enabled: false` впливає лише на `--all` — `ardupilot-refresh --roster blimp` (або
`--url ... --vehicle blimp`) все одно імпортує його як свідомий разовий виняток, і після імпорту
він лишається доступним за іменем; його просто виключено з пошукових інструментів із необмеженою
областю (`vehicle=None`).

Імена для `--roster` перевіряються за завантаженим реєстром, а не за жорстко зашитим списком —
тож апарат, доданий у ваш `data/vehicles.json`, одразу доступний для `--roster`. Помилка в імені
зупиняє весь запуск ще до першого звернення до мережі й показує повний список імен реєстру.

## MCP-інструменти

`server.py` надає шість інструментів через FastMCP. `vehicle` ніде не має значення за
замовчуванням — викличте `list_vehicles()`, якщо не впевнені, що передавати.

- `list_vehicles` — усі апарати з Реєстру, їхній прапорець enabled та ingested_version (null,
  якщо ніколи не імпортувався).
- `lookup_parameter` — точний пошук за іменем для одного апарата, з обробкою backend-варіантів.
- `search_parameters` — пошук за ключовими словами через FTS5. Без `vehicle` шукає по всіх
  увімкнених апаратах.
- `semantic_search` — пошук на базі ембедингів, область така сама, як вище.
- `list_parameters` — перегляд параметрів одного апарата за префіксом/секцією.
- `diff_parameter` — порівняння параметра поле за полем між двома апаратами.

## Структура проєкту

- `src/ardupilot_mcp/roster.py` — завантажує Реєстр апаратів (`vehicles.json`): авторитетний
  список того, які апарати існують, їхні URL-джерела та чи тягне їх `--all`.
- `src/ardupilot_mcp/db.py` — схема SQLite + шар запитів. Таблиці `parameters` +
  `parameter_values`, віртуальна таблиця FTS5 для пошуку за ключовими словами. Унікальний ключ:
  `(vehicle, name, backend)` — одна версія прошивки на апарат за раз.
- `src/ardupilot_mcp/scraper.py` — парсить згенерований Sphinx HTML параметрів ArduPilot у записи
  `Parameter`.
- `src/ardupilot_mcp/fetch.py` — мережеве завантаження (`fetch_url`) і визначення апарата з URL
  (`detect_vehicle_from_url`, звіряється з іменами в Реєстрі апаратів) для шляхів імпорту
  `--url`/`--all`.
- `src/ardupilot_mcp/ingest.py` — оркеструє scrape → запис у SQLite → опційну перебудову векторів.
  Точка входу CLI; `--all` проходить по увімкнених апаратах Реєстру, `--roster NAME...` — лише по
  названих, і обидва перебудовують вектори один раз наприкінці.
- `src/ardupilot_mcp/vectors.py` — шар семантичного пошуку на LanceDB, що тримає всі апарати
  одночасно.
- `src/ardupilot_mcp/catalog.py` — шов, через який усі шість інструментів звертаються до SQLite,
  векторного сховища та Реєстру апаратів.
- `src/ardupilot_mcp/server.py` — FastMCP-сервер, що надає шість інструментів вище.
- `Dockerfile`, `docker-compose.yml` — збірка контейнера та сервіси запуску stdio/http.

Див. `docs/adr/` — обґрунтування моделі зберігання «одна версія на апарат» і Реєстру апаратів, а
також `CONTEXT.md` — глосарій проєкту.

## Запуск тестів

```bash
uv run pytest
```

Golden-тести скрейпера читають `tests/fixtures/` (у gitignore, це не тека `data/`, куди пише
`ardupilot-refresh`) — перегенеруйте через `scripts/fetch_test_fixtures.sh`, якщо їх немає; на
свіжому клоні вони `skip`, а не падають.

## Відомі обмеження

- Пошук по всіх апаратах (`vehicle=None`) у семантичному індексі бере із запасом і дедуплікує за
  іменем параметра на боці клієнта, тож запитаний `k` — приблизна, а не точна кількість
  результатів.

## Ліцензія

Apache License 2.0 — див. [LICENSE](LICENSE).

---

# ardupilot-mcp (English)

MCP server exposing ArduPilot firmware parameter Q&A — keyword search, semantic search, and
cross-vehicle diffing — to Claude Desktop, Claude Code, and other MCP clients. Runs 100% locally
against a SQLite + LanceDB store scraped from ArduPilot's Sphinx-generated HTML parameter docs.

## Features

- **Exact lookup** — look up a parameter by name, with full metadata (description, units, range,
  enum/bitmask values).
- **Keyword search** — FTS5-backed search, scoped to one vehicle or across every enabled vehicle.
- **Semantic search** — embedding-based search (`intfloat/multilingual-e5-small`), same scoping;
  a parameter matching in several vehicles is deduped and tagged with which ones matched.
- **Cross-vehicle diffing** — field-by-field diff of a parameter's definition between two vehicles
  (e.g. "how does `LOG_BITMASK` differ between plane and copter?").
- **Local-only** — no network calls at query time beyond the one-time embedding model download.

Each vehicle stores exactly one firmware version at a time — whichever the Vehicle Roster's URL
currently points at. See "The Vehicle Roster" below.

## Requirements

Before you start, you need two things installed on your computer:

1. **Docker Desktop** — download from [docker.com](https://www.docker.com/products/docker-desktop/)
   and install it like any other app. This is the only way you'll run things — no need to install
   Python or any other developer tools.
2. **Git** — needed to download the project. Already installed on Mac (or it offers to install
   itself the first time you run `git`). On Windows, download from
   [git-scm.com](https://git-scm.com/download/win) and install with all the default options.
3. **A terminal app** — on Mac, open the app called "Terminal" (search for it with Spotlight,
   `Cmd+Space`). On Windows, open "Command Prompt" or "PowerShell" (search in the Start menu).

Every command below gets typed into that terminal window, one at a time, followed by Enter.

## Step-by-step setup

1. Download the project from GitHub. In the terminal, first move to wherever you want the project
   folder to live, then clone the repository:

   **macOS / Linux:**

   ```bash
   cd ~/Documents
   git clone https://github.com/Chevit/ardupilot-mcp.git
   cd ardupilot-mcp
   ```

   **Windows (Command Prompt or PowerShell):**

   ```powershell
   cd %USERPROFILE%\Documents
   git clone https://github.com/Chevit/ardupilot-mcp.git
   cd ardupilot-mcp
   ```

   Now note the **full path** to this folder — you'll need it to configure Claude Desktop. To find
   it:

   - **macOS / Linux:** run `pwd` → something like `/Users/your-name/Documents/ardupilot-mcp`
   - **Windows:** run `cd` (with no arguments) → something like
     `C:\Users\your-name\Documents\ardupilot-mcp`

   > Already have the project folder (someone handed it to you, no git)? Then just move into it:
   > `cd path/to/ardupilot-mcp`. You can usually drag the folder into the terminal window instead
   > of typing the path.
   >
   > Later, to update to a newer version: `git pull` in that same folder, then redo step 2.

2. Build the app (only needed once, or after an update):

   ```bash
   docker compose build
   ```

   This takes a few minutes the first time. Wait for it to finish.

3. Load parameter data — one command fetches every enabled vehicle on the Vehicle Roster
   (`plane` and `copter` by default) directly from ardupilot.org:

   ```bash
   docker compose run --rm mcp-stdio ardupilot-refresh --all --build-vectors
   ```

   Vehicle and firmware version are detected automatically. Only want some of the roster's
   vehicles? Name them with `--roster` (this works for vehicles marked `enabled: false` too,
   which only `--all` skips):

   ```bash
   docker compose run --rm mcp-stdio ardupilot-refresh --roster plane --build-vectors
   docker compose run --rm mcp-stdio ardupilot-refresh --roster plane copter --build-vectors
   ```

   Want a page the roster doesn't already list?

   ```bash
   docker compose run --rm mcp-stdio ardupilot-refresh --url https://ardupilot.org/plane/docs/parameters.html --build-vectors
   ```

   > No internet access on this machine, or want to pin a specific saved-locally page? Open the
   > link above in a browser, "Save Page As…" into the `data/ardupilot-docs/` folder inside the
   > project folder (create it if it doesn't exist), then run the same command with
   > `--html "data/ardupilot-docs/<the saved file name>.html" --vehicle plane --firmware-version 4.8.0 --source-url https://ardupilot.org/plane/docs/parameters.html`
   > in place of `--url ...`.

You're set up. The next section explains how to actually use it.

## Using it with Claude Desktop

This app is a "tool" that Claude can call — you don't run it by itself, you tell Claude how to
find it, then talk to Claude as usual.

### Step 1 — find `claude_desktop_config.json`

Easiest way: in Claude Desktop, open **Settings → Developer → Edit Config** — the file opens in an
editor. If it doesn't exist yet, Claude Desktop creates an empty one.

Or open it by hand:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
  (i.e. `C:\Users\your-name\AppData\Roaming\Claude\claude_desktop_config.json`)
- **Linux:** `~/.config/Claude/claude_desktop_config.json`

### Step 2 — work out your path to `docker-compose.yml`

It's the folder path from setup step 1, with `/docker-compose.yml` on the end:

- **macOS / Linux:** `/Users/your-name/Documents/ardupilot-mcp/docker-compose.yml`
- **Windows:** `C:\Users\your-name\Documents\ardupilot-mcp\docker-compose.yml` — but inside JSON
  every backslash must be **doubled**, so write it as
  `C:\\Users\\your-name\\Documents\\ardupilot-mcp\\docker-compose.yml`.
  (Or use forward slashes: `C:/Users/your-name/Documents/ardupilot-mcp/docker-compose.yml` —
  Docker understands those too, and nothing needs doubling.)

### Step 3 — add the entry to the file

**Case A — the file is empty or contains `{}`** (no MCP servers configured yet). Replace the whole
file contents with this:

```json
{
  "mcpServers": {
    "ardupilot": {
      "command": "docker",
      "args": ["compose", "-f", "/Users/your-name/Documents/ardupilot-mcp/docker-compose.yml", "run", "--rm", "mcp-stdio"]
    }
  }
}
```

The Windows version of the same:

```json
{
  "mcpServers": {
    "ardupilot": {
      "command": "docker",
      "args": ["compose", "-f", "C:\\Users\\your-name\\Documents\\ardupilot-mcp\\docker-compose.yml", "run", "--rm", "mcp-stdio"]
    }
  }
}
```

**Case B — the file already has an `"mcpServers"` block with other servers in it.** Don't replace
the whole file — add `"ardupilot"` as one more entry **inside** the existing `"mcpServers"`, and
don't forget the comma after the previous entry:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/your-name/Documents"]
    },
    "ardupilot": {
      "command": "docker",
      "args": ["compose", "-f", "/Users/your-name/Documents/ardupilot-mcp/docker-compose.yml", "run", "--rm", "mcp-stdio"]
    }
  }
}
```

(`"filesystem"` is just an example of what you might already have. Leave your own entries alone
and add only `"ardupilot"`.)

> The three most common mistakes in this file:
>
> 1. **Missing comma** between server entries — Claude Desktop silently ignores the whole file.
> 2. **Trailing comma** after the last entry — JSON doesn't allow it.
> 3. **Single backslash** in a Windows path — it has to be `\\`, not `\`.
>
> Some MCP clients don't honor a `cwd` field, which makes `docker compose` fail with
> `no configuration file provided: not found` since it can't locate `docker-compose.yml`.
> Passing `-f <full path to docker-compose.yml>` sidesteps that — it works regardless of the
> client's working directory. That's why the path here must be **full (absolute)**, not relative.

### Step 4 — restart and check

1. Quit Claude Desktop completely (on macOS that's `Cmd+Q`, not just closing the window) and open
   it again.
2. Make sure **Docker Desktop is running** — the server won't start without it.
3. Ask Claude something like "what does the RC_OPTIONS parameter do?" — Claude will use this tool
   automatically.

## Day-to-day use: starting it without rebuilding

`docker compose build` is needed **only once** — and after that only following a `git pull` or a
change to the `Dockerfile`/dependencies. Parameter data lives in the `data/` folder and survives
containers being stopped and deleted, so `ardupilot-refresh` doesn't need repeating either (unless
you want a fresher firmware version).

**If you're using Claude Desktop (stdio):** there's nothing to start. Claude Desktop launches the
container itself every time it opens and stops it on exit — so you shouldn't expect to see
`ardupilot-mcp` among the running containers between sessions. That's normal. The only requirement
is that **Docker Desktop is running** before Claude Desktop starts. After a reboot: open Docker
Desktop, wait for it to say "Engine running", then open Claude Desktop. If Claude reports the
server failed to start, that's almost always the reason.

**If you're using the shared HTTP server:** after a stop or a reboot, bring it back up — the image
is already built, so nothing gets rebuilt:

```bash
docker compose up -d mcp-http
```

Useful commands from inside the project folder:

```bash
docker compose ps              # is mcp-http running right now
docker compose logs mcp-http   # logs, if something went wrong
docker compose stop mcp-http   # stop it (data is kept)
docker compose start mcp-http  # bring a stopped container back up
```

The `mcp-http` service is set to `restart: unless-stopped`, so it comes back on its own after a
reboot once Docker Desktop starts — unless you stopped it deliberately with `docker compose stop`.

## Advanced: running as a shared server

If you want one computer to run this and other people's Claude clients to connect to it over the
network, start the long-running version instead:

```bash
docker compose up -d mcp-http
```

Other people then point their Claude client at `http://<this-computer's-address>:8000/mcp` instead
of using the `docker compose run` command above. There's no login/password built in, so only do
this on a network you trust (home network, VPN, or similar) — don't expose it to the open
internet.

## Advanced: running without Docker

If you'd rather run this with Python directly instead of Docker, you need
[`uv`](https://docs.astral.sh/uv/) and Python 3.10+ installed. Then:

```bash
uv sync
uv run python -m ardupilot_mcp.ingest --all --build-vectors
uv run python -m ardupilot_mcp.server
```

`--all` fetches every enabled vehicle on the Vehicle Roster; `--roster plane copter` fetches only
the ones you name (any name in the roster, disabled ones included). For a page that isn't on the
roster, vehicle and firmware version are auto-detected from the URL and page text: `uv run python -m
ardupilot_mcp.ingest --url https://ardupilot.org/plane/docs/parameters.html --build-vectors`. Pass
`--vehicle`/`--firmware-version` to override, or swap `--url <url>` for `--html "<path>" --vehicle
plane --firmware-version 4.8.0 --source-url https://ardupilot.org/plane/docs/parameters.html` to
ingest from a page you already downloaded instead of fetching it.

Console script entry points (`pyproject.toml`): `ardupilot-mcp` → `server:main`,
`ardupilot-refresh` → `ingest:main`.

## The Vehicle Roster

Which vehicles exist, their source URLs, and whether `--all` fetches them live in the **Vehicle
Roster** — `vehicles.json`, packaged with the app. Ships with six vehicles: `plane` and `copter`
enabled; `rover`, `sub`, `blimp` and `antennatracker` present but disabled.

To change a URL, pin a vehicle to an older firmware version (ArduPilot publishes versioned pages
like `parameters-Copter-stable-V4.7.0.html` for superseded releases), or enable/disable a vehicle:
drop your own `vehicles.json` into `data/` (the directory Docker already bind-mounts) — it fully
replaces the packaged roster, so include every vehicle you still want. `--vehicles-config PATH`
picks a roster file outside `data/` for a single invocation.

An `enabled: false` entry only affects `--all` — `ardupilot-refresh --roster blimp` (or
`--url ... --vehicle blimp`) still ingests it as a deliberate one-off, and once ingested it stays
queryable by name; it's just excluded from the unscoped `vehicle=None` search tools.

`--roster` names are checked against the roster you actually loaded, not a hardcoded list, so a
vehicle you add to your own `data/vehicles.json` can be named right away. A misspelled name stops
the whole run before anything is fetched and prints the roster's full list of names.

## MCP tools

`server.py` exposes six tools via FastMCP. `vehicle` has no default anywhere — call
`list_vehicles()` if unsure what to pass.

- `list_vehicles` — every vehicle on the Roster, its enabled flag, and its ingested_version (null
  if never ingested).
- `lookup_parameter` — exact-name lookup for one vehicle, with backend-variant handling.
- `search_parameters` — FTS5 keyword search. `vehicle` omitted searches every enabled vehicle.
- `semantic_search` — embedding-based search, same scoping as above.
- `list_parameters` — browse one vehicle's parameters by prefix/section.
- `diff_parameter` — field-by-field diff of a parameter between two vehicles.

## Project structure

- `src/ardupilot_mcp/roster.py` — loads the Vehicle Roster (`vehicles.json`): the authoritative
  list of which vehicles exist, their source URLs, and whether `--all` fetches them.
- `src/ardupilot_mcp/db.py` — SQLite schema + query layer. `parameters` + `parameter_values`
  tables, FTS5 virtual table for keyword search. Unique key: `(vehicle, name, backend)` — one
  firmware version stored per vehicle at a time.
- `src/ardupilot_mcp/scraper.py` — parses Sphinx-generated ArduPilot parameter HTML into
  `Parameter` records.
- `src/ardupilot_mcp/fetch.py` — network fetch (`fetch_url`) and URL → vehicle detection
  (`detect_vehicle_from_url`, matched against the Vehicle Roster's names) for the `--url`/`--all`
  ingest paths.
- `src/ardupilot_mcp/ingest.py` — orchestrates scrape → SQLite write → optional vector rebuild.
  CLI entry point; `--all` loops the Roster's enabled vehicles and `--roster NAME...` only the ones
  named, both rebuilding vectors once at the end.
- `src/ardupilot_mcp/vectors.py` — LanceDB-backed semantic search layer, holding every vehicle at
  once.
- `src/ardupilot_mcp/catalog.py` — the seam through which all six tools query the SQLite + vector
  stores + Vehicle Roster.
- `src/ardupilot_mcp/server.py` — FastMCP server exposing the six tools above.
- `Dockerfile`, `docker-compose.yml` — container build and stdio/http launch services.

See `docs/adr/` for the reasoning behind the single-version-per-vehicle storage model and the
Vehicle Roster, and `CONTEXT.md` for the project's glossary.

## Running tests

```bash
uv run pytest
```

Golden scraper tests read `tests/fixtures/` (gitignored, not the `data/` directory `ardupilot-refresh`
writes to) — regenerate with `scripts/fetch_test_fixtures.sh` if missing; they `skip` rather than
fail on a fresh clone.

## Known limitations

- The semantic index's `vehicle=None` cross-vehicle search over-fetches and dedupes by parameter
  name client-side, so the requested `k` is an approximate result count, not an exact one.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
