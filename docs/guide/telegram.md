# Telegram

## Telegram channel notifications

Fleet can forward blocked-agent questions to a Telegram channel so you get a push notification instead of having to watch the UI. When `TELEGRAM_BOT_TOKEN` and `telegram_chat_id` are set, new questions posted by agents are sent to the channel as messages. You can answer directly from Telegram (see [Answering chat questions from Telegram](#answering-chat-questions-from-telegram)) or via the fleet chat UI.

### Quick start

1. Create a bot with **@BotFather** on Telegram (see Step 1 below) and copy the token.
2. Add the bot as an admin to your channel or group.
3. Export the token and run the wizard:

```bash
export TELEGRAM_BOT_TOKEN="123456:ABCDefgh..."
fleet telegram setup
```

The wizard validates your token, asks you to post a message in your channel so it can discover the chat ID, optionally sets up inbound task commands (writing `telegram_allowed_ids` and `telegram_default_cwd` for you), and sends a confirmation message. All values are written to `runtime.toml` automatically.

Add the `export TELEGRAM_BOT_TOKEN=…` line to your shell profile so it is set whenever `fleet serve` starts — or, since launchd daemons run with a bare environment, write the token to `~/.fleet/telegram_token` (chmod 600) instead, which fleet reads whenever the env var is unset.

To verify the setup at any time:

```bash
fleet telegram status   # shows token, bot username, config values, and pass/fail verdict
fleet telegram test     # sends a live message to the configured chat
```

### Alternatively, configure by hand

#### Step 1 — Create a bot

1. Open Telegram and start a chat with **@BotFather**.
2. Send `/newbot`, follow the prompts to choose a name and username.
3. BotFather returns a token that looks like `123456:ABCDefgh...` — copy it.

#### Step 2 — Add the bot to your channel

1. Open the target channel in Telegram.
2. Go to **Manage channel → Administrators → Add Administrator**.
3. Search for your bot by its username and add it. It only needs the **Post messages** permission.

#### Step 3 — Obtain the chat ID

For a **public** channel, the chat ID is `@your_channel_username`.

For a **private** channel, forward any message from the channel to **@userinfobot** (or send a message and call `getUpdates` on your bot's token) — the `chat.id` field is a negative number like `-1001234567890`.

#### Step 4 — Configure fleet serve

Set the bot token as an environment variable **before** starting `fleet serve`:

```bash
export TELEGRAM_BOT_TOKEN="123456:ABCDefgh..."
fleet serve start
```

For a persistent setup, add the export to the shell profile or process manager that launches `fleet serve`.

#### Step 5 — Set the chat ID

Either edit `$FLEET_HOME/runtime.toml` directly:

```toml
telegram_chat_id = "-1001234567890"
```

or use the config commands / Config panel in the web UI:

```bash
fleet config set telegram_chat_id=-1001234567890
```

`fleet serve` reads `runtime.toml` on every polling cycle, so the change takes effect immediately — no restart needed.

### How it works

`fleet serve` polls for new agent questions every 2 seconds. When both `TELEGRAM_BOT_TOKEN` and `telegram_chat_id` are set, each new question is sent to the channel as a plain-text message: the agent ID followed by the question text (and numbered options, if any). Notifications stop if either value is cleared.

---

## Inbound task creation from Telegram

Fleet can receive commands from Telegram to create and inspect tasks — no web UI needed, no public URL or webhook required (long polling is used). Four commands are supported: `/new_task` creates a task, `/tasks` lists open tasks, `/task <id>` shows details for one task, and `/help` (or `/start`) shows command usage.

**This feature is off by default.** Until `telegram_allowed_ids` is set, the listener runs but accepts no commands.

> **Tip:** If you ran `fleet telegram setup` and chose to enable inbound task commands, the wizard already captured your Telegram user ID and wrote `telegram_allowed_ids` and `telegram_default_cwd` to `runtime.toml` for you. The steps below describe the manual path.

### Commands

All inbound commands are only processed for senders whose user ID or chat ID appears in `telegram_allowed_ids`.

#### `/new_task` — create a task

```
/new_task <title>
```

or multiline (title on the line after the command):

```
/new_task
<title>
<optional description lines>
```

The first non-empty token or line after `/new_task` becomes the task title. All subsequent non-blank lines become the description. Fleet replies with the new task ID and title on success.

Examples:

```
/new_task Fix the login timeout bug
```

```
/new_task Refactor the auth module
Extract the JWT logic into its own class and add unit tests.
Target: src/auth/jwt.py
```

```
/new_task
Add dark-mode support to the dashboard
Update the CSS variables and toggle logic.
```

#### `/tasks` — list open tasks

```
/tasks
```

Fleet replies with two sections — **In progress** and **Ready** — each showing up to 15 tasks in the format `- <id> <title>`. If a section is empty it is omitted. If both are empty, Fleet replies `No open tasks.`

#### `/task <id>` — show task details

```
/task <id>
```

Fleet looks up the task and replies with its ID, status, title, and description (if any):

```
ID: <id>
Status: <status>
Title: <title>

<description if present>
```

If the task ID is not found, Fleet suggests using `/new_task` to create one.

#### `/help` — show command usage

```
/help
```

Fleet replies with a summary of all available commands and the answer flow. Telegram clients send `/start` automatically when a user first opens the bot — Fleet treats `/start` as an alias for `/help` and replies with the same message.

### Step 1 — Find your numeric Telegram user ID

Your Telegram ID is a plain integer (e.g. `123456789`), not your username. To look it up:

1. Open Telegram and start a chat with **@userinfobot**.
2. Send any message; it replies with your **Id** field — copy that number.

For a group chat, forward any message from that chat to **@userinfobot** to obtain the group's numeric ID (a negative number).

### Step 2 — Set the allowlist

Add the numeric ID(s) to `telegram_allowed_ids` as a comma-separated list:

```toml
# $FLEET_HOME/runtime.toml
telegram_allowed_ids = "123456789"
```

Multiple IDs:

```toml
telegram_allowed_ids = "123456789,987654321"
```

Or via the config command:

```bash
fleet config set telegram_allowed_ids=123456789
```

The change takes effect immediately — no restart needed.

### Step 3 — (Optional) Set the default working directory

Tasks created via Telegram inherit `telegram_default_cwd` as their working directory. Set it to the repo you want agents to work in:

```toml
telegram_default_cwd = "/Users/you/git/myproject"
```

```bash
fleet config set telegram_default_cwd=/Users/you/git/myproject
```

If left empty, tasks are created without an explicit `cwd`.

### Security model

The allowlist is **default-deny**: if `telegram_allowed_ids` is empty, no inbound messages are processed. Any message from a sender or chat ID **not** on the list is silently rejected and logged at WARNING level.

> **Keep the allowlist tight.** Anyone whose numeric ID appears in `telegram_allowed_ids` can send arbitrary task titles and descriptions that spawn coding agents on your machine with full filesystem access.

---

## Answering chat questions from Telegram

When an agent blocks on an `ask_human` question, Fleet sends the question to your configured chat prefixed with the agent/task ID. You can answer directly from Telegram without opening the web UI.

### How to answer

There are three ways to submit an answer:

1. **Reply to the bot message (recommended)** — use Telegram's built-in reply on the exact message the bot sent. This works regardless of how many questions are currently pending and is the most reliable method.
2. **Plain-text message** — send a free-text answer when exactly one question is pending. Fleet routes it to the only open question automatically. If more than one question is pending, Fleet refuses the message and replies with a hint to use reply-to instead.
3. **Bare option number** — when the question lists numbered options, send the number alone (e.g. `2`) to select that choice. Obeys the same single-question rule as plain text when not using reply-to.

### What happens after you answer

The answer is recorded with `answered_by = telegram` and unblocks the waiting agent immediately — no further action needed in the web UI.

### Security

Answering is gated by the same `telegram_allowed_ids` allowlist that controls all inbound commands. Messages from unlisted senders or chats are silently rejected.

### Message mapping

Fleet maintains `$FLEET_HOME/telegram_question_msgs.json` — a mapping from Telegram message IDs to open questions:

- **Auto-managed** — created on first use, no setup required.
- **Capped at 200 entries** — older entries are pruned automatically when the cap is hit.

If you reply to a message that is no longer in the map (pruned after the cap, or the question was already answered), Fleet sends back an error reply.
