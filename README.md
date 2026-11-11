# Private Chef

A local-first cooking assistant for two people. Both people share recipes, selected
meals and shopping lists, while keeping their own preferences and dish ratings.
OpenAI provides inference; no model runs on your computer. WhatsApp connects through
a small OpenClaw plugin.

The Python application has **no third-party runtime dependencies**. It uses SQLite
and calls the OpenAI Responses API over HTTPS with structured function tools.

## Start locally

Requires Python 3.12 or later. From this directory:

```bash
python3 run.py setup
```

All application paths are relative to this repository root: `src/`, `tests/`,
`openclaw/`, `.env`, and `data/`. There is no nested `private-chef/` application folder.

This creates `.env` with a random local service token and private file permissions,
initializes `data/chef.sqlite3`, and adds six original starter recipes. Re-running
setup preserves your `.env` and existing records.

Edit `.env` locally:

```dotenv
OPENAI_API_KEY=your-key-here
OPENAI_MODEL=gpt-4.1-mini
CHEF_USER_1_NAME=Your name
CHEF_USER_2_NAME=Partner's name
```

Use a model available to your API account that supports Responses function calling.
The default is a configurable starting point, not a requirement to use that model.
API usage is billed by your provider. There are no hosted workflow subscriptions.

Start a terminal conversation:

```bash
python3 run.py chat --member person-1
```

Type `/member` to switch person and `/quit` to leave. Example messages:

- “I like lentils and dislike olives. Remember that.”
- “My diet is vegetarian.”
- “Recommend three dishes that we would both enjoy.”
- “Let's cook recipe 2.”
- “I give recipe 2 four out of five; it could use more lemon.”
- “Generate the shopping list for our selected meals.”
- “We bought the spinach.”

Preferences are lasting unless explicitly removed. Changing a like to a dislike
replaces the opposite taste preference. Ingredient exclusions remain until explicitly
removed. Feedback belongs to the authenticated person; neither can record a rating
as the other person. Temporary preparation feedback does not change preferences.

There is no grocery-budget, pantry, time-limit or current-situation tracking.

## Try the tools without an API key

Setup, the domain tools and tests work without credentials or internet access:

```bash
python3 run.py tool get_household
python3 run.py tool set_preference --member person-2 --json '{"kind":"like","value":"lentils","remove":false}'
python3 run.py tool recommend_recipes --json '{"count":3}'
python3 run.py tool select_recipe --json '{"recipe_id":2,"servings":2}'
python3 run.py tool build_shopping_list
python3 run.py state
```

CLI tool calls are trusted local administration. Avoid putting sensitive information
in shell history. `state` prints personal records; do not post its output publicly.

## Use WhatsApp

Follow [the OpenClaw setup guide](docs/openclaw.md). Start the local service in one terminal:

```bash
python3 run.py serve
```

The service listens only on `127.0.0.1:8787`. An OpenClaw gateway runs in a second
terminal and forwards requests such as:

```text
/chef Recommend three dishes
/chef Remember that I dislike mushrooms
/chef Show our shopping list
```

The gateway can connect from this machine without a public inbound HTTP endpoint.
The machine must be awake and online. WhatsApp setup requires a manual linked-device
QR scan. A separate bot number is recommended. See the guide for optional ordinary
natural-language routing and group configuration.

## Shopping-list behaviour

- Only explicitly selected meals contribute. Merely suggesting a dish does not select it.
- Recipe quantities scale to the selected portions; default portions are two.
- Exact normalized ingredient names and units merge. Different units remain separate
  rather than guessing conversions or supermarket package sizes.
- Rebuilding is idempotent and retains manual additions and bought flags. An increased
  quantity reopens an item as unbought.
- Cancelling a meal removes its contribution while retaining other meals and extras.
- Marking a meal cooked preserves its existing shopping entries until you clear/remove them.
- Removing an item affects the current list; rebuilding can re-add it from planned meals.
- Clearing the list does not cancel planned meals. Mark meals cooked or cancelled before
  starting another week's list if they should no longer contribute.

## Tests and development

No network access, API keys or paired WhatsApp account are needed:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
node openclaw/test.mjs
```

The optional installed `private-chef` CLI uses the current working directory for
configuration and data, and ships its own setup template. WhatsApp setup uses the
repository's `openclaw/` adapter, so run gateway setup and launch commands from this
checkout as documented above.

The plugin tests require Node.js 20 or newer. Installing/running OpenClaw itself may
require a newer Node.js version; follow its current installation documentation.

Optional linting and formatting:

```bash
python3 -m pip install ruff==0.15.12
ruff check .
ruff format --check .
```

CI runs Python tests, plugin contract tests and lint checks. Tests cover persistent
profiles, ranking, identity enforcement, shopping arithmetic, simultaneous writes,
HTTP parsing/authentication, tool execution, provider failures and request replay.
Model behaviour and the live OpenClaw/WhatsApp integration need credentialed smoke
tests after configuration; fake-model tests cannot establish recommendation quality.

Existing version-1 databases are upgraded automatically on startup to version 2.
The migration preserves shopping items, quantities and bought flags, while preventing
deleted item IDs from being reused for different ingredients. Keep a private backup
before updating an existing installation.

## Privacy, limitations and deployment

For the always-on WhatsApp setup, follow the [Oracle Cloud VM deployment
guide](docs/oracle-deployment.md), including migration, systemd services and backups.

`.env`, databases, OpenClaw sessions, logs and runtime directories are ignored by Git.
Never add a real key to examples or generated configuration. The `.env` reader does
not execute shell expressions. Restart the processes after editing configuration.

Preferences, recipes, feedback and relevant chat context are sent to OpenAI for inference.
Requests use `store: false`; this does **not** override the provider's abuse-monitoring
or retention policies. Both people can see household preferences and ratings. Recent
conversation context is kept separately for each person; the app does not automatically
relay private-chat transcripts to the other person. Requests and their replies are
also retained locally for replay protection. Local records are not encrypted at rest;
protect this machine and its backups. Source URLs are stored as references, not fetched.

Recipe exclusions use text matching and dietary tags. Tags on generated or saved
recipes are assertions, not independently verified allergen information. Check labels,
related ingredients, substitutions and cross-contamination for allergies.

The current HTTP server is for local development. It deliberately refuses public
binding. Do not expose it directly to the internet. See [architecture and deployment
notes](docs/architecture.md) for the later migration path and consistency boundaries.

To back up SQLite while the app runs, use SQLite's backup API rather than copying
only the database file while WAL files are active:

```bash
python3 - <<'PY'
import sqlite3
from pathlib import Path
Path('data/backups').mkdir(parents=True, exist_ok=True)
with sqlite3.connect('data/chef.sqlite3') as source:
    with sqlite3.connect('data/backups/chef.sqlite3') as target:
        source.backup(target)
PY
```

Back up `.env` and `data/openclaw` separately and privately. Deleting the runtime
database removes the local household records; cloud-provider retention is separate.
