# ardupilot-mcp

MCP-сервер, що надає запити й відповіді про параметри прошивки ArduPilot — пошук за ключовими
словами, семантичний пошук і порівняння між апаратами — для Claude Desktop, Claude Code та інших
MCP-клієнтів. Працює на 100% локально поверх сховища SQLite + LanceDB, зібраного зі згенерованої
Sphinx HTML-документації параметрів ArduPilot.

*[English version below](#english) — англійська версія нижче.*

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
2. **Термінал** — на Mac відкрийте програму «Terminal» (знайдіть через Spotlight, `Cmd+Space`).
   На Windows відкрийте «Command Prompt» або «PowerShell» (пошук у меню «Пуск»).

Усі команди нижче вводяться у це вікно термінала, по одній, з натисканням Enter.

## Покрокове налаштування

1. Отримайте копію проєкту на свій комп'ютер. Якщо вам дали теку — просто запам'ятайте, де вона.
   У терміналі перейдіть у цю теку:

   ```bash
   cd path/to/ardupilot-mcp
   ```

   (Замініть `path/to/ardupilot-mcp` на реальний шлях — зазвичай можна просто перетягнути теку у
   вікно термінала замість того, щоб набирати шлях вручну.)

2. Зберіть застосунок (потрібно один раз, або після оновлення):

   ```bash
   docker compose build
   ```

   Перший раз це триває кілька хвилин. Дочекайтеся завершення.

3. Завантажте дані параметрів — одна команда тягне всі увімкнені апарати з Реєстру апаратів
   (`plane`, `copter`, `rover`, `sub` за замовчуванням) напряму з ardupilot.org:

   ```bash
   docker compose run --rm mcp-stdio ardupilot-refresh --all --build-vectors
   ```

   Апарат і версія прошивки визначаються автоматично. Потрібен лише один апарат, або сторінка,
   якої немає в реєстрі?

   ```bash
   docker compose run --rm mcp-stdio ardupilot-refresh --url https://ardupilot.org/plane/docs/parameters.html --build-vectors
   ```

   > Немає інтернету на цій машині, або треба зафіксувати конкретну збережену сторінку? Відкрийте
   > посилання вище у браузері, зробіть «Save Page As…» у теку `data/ardupilot-docs/` всередині
   > проєкту (створіть її, якщо немає), потім запустіть ту саму команду з
   > `--html "data/ardupilot-docs/<назва збереженого файлу>.html" --vehicle plane --firmware-version 4.8.0 --source-url https://ardupilot.org/plane/docs/parameters.html`
   > замість `--url ...`.

Готово. Наступний розділ пояснює, як цим користуватися.

## Використання з Claude Desktop / Claude Code

Цей застосунок — «інструмент», який викликає Claude. Ви не запускаєте його самі: ви кажете Claude,
де його знайти, а далі спілкуєтеся з Claude як зазвичай.

1. Відкрийте файл налаштувань Claude Desktop / Claude Code (якщо не впевнені, де він — пошукайте
   «MCP servers» у налаштуваннях вашого застосунку Claude).
2. Додайте цей запис, замінивши `/path/to/ardupilot-mcp` на реальний шлях до теки з кроку 1:

   ```json
   {
     "mcpServers": {
       "ardupilot": {
         "command": "docker",
         "args": ["compose", "-f", "/path/to/ardupilot-mcp/docker-compose.yml", "run", "--rm", "mcp-stdio"]
       }
     }
   }
   ```

   > Деякі MCP-клієнти не враховують поле `cwd`, через що `docker compose` падає з помилкою
   > `no configuration file provided: not found`, бо не може знайти `docker-compose.yml`.
   > Передача `-f /path/to/ardupilot-mcp/docker-compose.yml` це обходить — працює незалежно від
   > робочої теки клієнта.

3. Перезапустіть Claude Desktop / Claude Code.
4. Запитайте у Claude щось на кшталт «що робить параметр RC_OPTIONS?» — Claude скористається цим
   інструментом автоматично.

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

`--all` тягне всі увімкнені апарати з Реєстру апаратів. Для одного апарата апарат і версія
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
(`vehicles.json`, запакований разом із застосунком). З коробки шість апаратів: `plane`, `copter`,
`rover`, `sub` увімкнені; `blimp` і `antennatracker` присутні, але вимкнені.

Щоб змінити URL, зафіксувати апарат на старішій версії прошивки (ArduPilot публікує версіоновані
сторінки на кшталт `parameters-Copter-stable-V4.7.0.html` для попередніх релізів) або
увімкнути/вимкнути апарат: покладіть власний `vehicles.json` у `data/` (теку, яку Docker уже
монтує) — він повністю замінює запакований реєстр, тож включіть у нього всі апарати, які вам ще
потрібні. `--vehicles-config PATH` вибирає файл реєстру поза `data/` для одного запуску.

Запис `enabled: false` впливає лише на `--all` — `ardupilot-refresh --url ... --vehicle blimp`
все одно імпортує його як свідомий разовий виняток, і після імпорту він лишається доступним за
іменем; його просто виключено з пошукових інструментів із необмеженою областю (`vehicle=None`).

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
  Точка входу CLI; `--all` проходить по увімкнених апаратах Реєстру та перебудовує вектори один
  раз наприкінці.
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

<a name="english"></a>

# English

# ardupilot-mcp

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
2. **A terminal app** — on Mac, open the app called "Terminal" (search for it with Spotlight,
   `Cmd+Space`). On Windows, open "Command Prompt" or "PowerShell" (search in the Start menu).

Every command below gets typed into that terminal window, one at a time, followed by Enter.

## Step-by-step setup

1. Get a copy of this project onto your computer. If you were given a folder, just make sure you
   know where it is. In the terminal, move into that folder:

   ```bash
   cd path/to/ardupilot-mcp
   ```

   (Replace `path/to/ardupilot-mcp` with the real folder location — you can usually drag the
   folder into the terminal window instead of typing the path.)

2. Build the app (only needed once, or after an update):

   ```bash
   docker compose build
   ```

   This takes a few minutes the first time. Wait for it to finish.

3. Load parameter data — one command fetches every enabled vehicle on the Vehicle Roster
   (`plane`, `copter`, `rover`, `sub` by default) directly from ardupilot.org:

   ```bash
   docker compose run --rm mcp-stdio ardupilot-refresh --all --build-vectors
   ```

   Vehicle and firmware version are detected automatically. Only want one vehicle, or a page
   the roster doesn't already list?

   ```bash
   docker compose run --rm mcp-stdio ardupilot-refresh --url https://ardupilot.org/plane/docs/parameters.html --build-vectors
   ```

   > No internet access on this machine, or want to pin a specific saved-locally page? Open the
   > link above in a browser, "Save Page As…" into the `data/ardupilot-docs/` folder inside the
   > project folder (create it if it doesn't exist), then run the same command with
   > `--html "data/ardupilot-docs/<the saved file name>.html" --vehicle plane --firmware-version 4.8.0 --source-url https://ardupilot.org/plane/docs/parameters.html`
   > in place of `--url ...`.

You're set up. The next section explains how to actually use it.

## Using it with Claude Desktop / Claude Code

This app is a "tool" that Claude can call — you don't run it by itself, you tell Claude how to
find it, then talk to Claude as usual.

1. Open your Claude Desktop / Claude Code settings file (search your Claude app's settings for
   "MCP servers" if unsure where this lives).
2. Add this entry, replacing `/path/to/ardupilot-mcp` with the real folder path from setup step 1:

   ```json
   {
     "mcpServers": {
       "ardupilot": {
         "command": "docker",
         "args": ["compose", "-f", "/path/to/ardupilot-mcp/docker-compose.yml", "run", "--rm", "mcp-stdio"]
       }
     }
   }
   ```

   > Some MCP clients don't honor a `cwd` field, which makes `docker compose` fail with
   > `no configuration file provided: not found` since it can't locate `docker-compose.yml`.
   > Passing `-f /path/to/ardupilot-mcp/docker-compose.yml` sidesteps that — it works
   > regardless of the client's working directory.

3. Restart Claude Desktop / Claude Code.
4. Ask Claude something like "what does the RC_OPTIONS parameter do?" — Claude will use this tool
   automatically.

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

`--all` fetches every enabled vehicle on the Vehicle Roster. For a single vehicle, vehicle and
firmware version are auto-detected from the URL and page text: `uv run python -m
ardupilot_mcp.ingest --url https://ardupilot.org/plane/docs/parameters.html --build-vectors`. Pass
`--vehicle`/`--firmware-version` to override, or swap `--url <url>` for `--html "<path>" --vehicle
plane --firmware-version 4.8.0 --source-url https://ardupilot.org/plane/docs/parameters.html` to
ingest from a page you already downloaded instead of fetching it.

Console script entry points (`pyproject.toml`): `ardupilot-mcp` → `server:main`,
`ardupilot-refresh` → `ingest:main`.

## The Vehicle Roster

Which vehicles exist, their source URLs, and whether `--all` fetches them live in the **Vehicle
Roster** — `vehicles.json`, packaged with the app. Ships with six vehicles: `plane`, `copter`,
`rover`, `sub` enabled; `blimp` and `antennatracker` present but disabled.

To change a URL, pin a vehicle to an older firmware version (ArduPilot publishes versioned pages
like `parameters-Copter-stable-V4.7.0.html` for superseded releases), or enable/disable a vehicle:
drop your own `vehicles.json` into `data/` (the directory Docker already bind-mounts) — it fully
replaces the packaged roster, so include every vehicle you still want. `--vehicles-config PATH`
picks a roster file outside `data/` for a single invocation.

An `enabled: false` entry only affects `--all` — `ardupilot-refresh --url ... --vehicle blimp`
still ingests it as a deliberate one-off, and once ingested it stays queryable by name; it's just
excluded from the unscoped `vehicle=None` search tools.

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
  CLI entry point; `--all` loops the Roster's enabled vehicles and rebuilds vectors once at the end.
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
