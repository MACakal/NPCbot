# NPCbot Feature Roadmap

Status: implemented (all 8 features below have shipped)
Audience: whoever (human or Claude) picks up implementation next

## Why this document exists

This is a plan for a batch of new features for NPCbot. The single hard
constraint driving every design choice below:

> **The live `database.db` on the production machine must never break when
> this repo is pulled and the bot is restarted.**

`database.db` is gitignored (`.gitignore` excludes `/database/`, `*.db`,
`*.sqlite3`) and there is currently no migration system in this codebase —
`DatabaseManager` never issues `CREATE TABLE`. The existing tables (`users`,
`pool`, `Bank`) already exist on the live DB and are assumed present. Every
feature below is designed to be **purely additive**:

- New features get their **own new tables**, created defensively with
  `CREATE TABLE IF NOT EXISTS` the first time the relevant `DatabaseManager`
  method runs.
- If a feature truly needs a new column on an existing table (`users` /
  `Bank`), it must be added via `ALTER TABLE ... ADD COLUMN ...` wrapped in a
  `try/except sqlite3.OperationalError` (SQLite has no `ADD COLUMN IF NOT
  EXISTS`), run once at `DatabaseManager.__init__` time, so it's a safe no-op
  on a DB that already has the column and a one-time upgrade on a DB that
  doesn't.
- **Never** drop, rename, or change the type of an existing column or table.
- **Never** assume a fresh/empty DB — always `get_or_create_user` /
  equivalent guards before reading, exactly like the existing code does.

Each feature section below calls out its exact schema additions so this rule
stays auditable.

## Theme note

"NPC" in NPCbot originally just abbreviated the Discord server name ("Niche
Physiology Central"), with no actual NPC content in the bot. Feature #1 below
leans into "NPC" literally as a bit — the bot gains actual NPC companions —
which is a nice coincidental joke on the server's own name.

## Implementation notes (decisions made during build)

- **NPC perks are real, not cosmetic.** When asked, the choice was to have
  recruited NPCs grant real (small, capped) bonuses to existing commands
  rather than be a purely self-contained collection system. Perks are
  additive percentages, non-stacking beyond one companion per user, capped
  at `Config.NPC_MAX_LEVEL` (5), so the maximum swing on any hooked command
  is a modest +15–25%.
- **Shop item effects were scoped away from gambling odds.** To avoid
  touching the balance of the existing coin-flip/roulette/blackjack win
  probabilities, functional shop items only discount NPC costs
  (`npc_cost_discount`) or reduce the rob failure penalty
  (`rob_penalty_reduction`) — both non-critical-path economy levers.
- **Jackpot was redesigned, not resurrected** — see the deviation note in
  its section below.
- **Achievements ended up covering all 8 features**, including two not in
  the original plan: `jackpot_winner` and `first_trivia_win`, added once
  those features existed since the hook points were trivial.

## Feature list

### 1. NPC Companions (headline feature)

Users can recruit a small roster of NPC companions, feed/train them with
in-game money, and level them up for small passive perks. This is the first
real "NPC" content the bot has ever had.

- New cog: `bot/cogs/npc.py`
- New tables (both created in a new `DatabaseManager` method, e.g.
  `_init_npc_tables()`, called once from `__init__`):
  ```sql
  CREATE TABLE IF NOT EXISTS npc_templates (
      id INTEGER PRIMARY KEY,
      name TEXT NOT NULL,
      archetype TEXT NOT NULL,      -- e.g. "merchant", "guard", "gambler"
      flavor_text TEXT,
      base_perk TEXT NOT NULL       -- e.g. "daily_bonus", "interest_boost"
  );

  CREATE TABLE IF NOT EXISTS user_npcs (
      user_id INTEGER NOT NULL,
      npc_template_id INTEGER NOT NULL,
      level INTEGER NOT NULL DEFAULT 1,
      xp INTEGER NOT NULL DEFAULT 0,
      acquired_at INTEGER NOT NULL,
      PRIMARY KEY (user_id, npc_template_id)
  );
  ```
- Commands: `/npc-recruit`, `/npc-list`, `/npc-train` (spends money, adds
  xp), `/npc-info`.
- Perk hook: a small helper (`get_active_perk_multiplier(user_id, perk_type)`)
  that `/daily-claim` and bank interest can optionally call — additive call
  site, doesn't change behavior for users with no NPCs (multiplier defaults
  to 1.0).
- `npc_templates` is seeded with `INSERT OR IGNORE` on init so re-running
  never duplicates rows.

### 2. `/work` command

A lower-effort companion to `/daily-claim` with a short cooldown and a small
payout, flavored as your NPC helping out when you have one recruited.

- New column: `users.last_work` (INTEGER, nullable) via guarded
  `ALTER TABLE users ADD COLUMN last_work INTEGER`.
- New `Config` constants: `WORK_REWARD`, `WORK_COOLDOWN_SECONDS`.
- Command lives in `bot/cogs/economy.py` next to `/daily-claim`, reusing
  `update_user_money` / `get_or_create_user`.

### 3. `/rob` (heist)

Risky player-vs-player money transfer: chance of success steals a percentage
of the target's cash into the robber's balance; chance of failure sends a
penalty from the robber into the shared `pool` (reusing the existing pool
mechanic that gambling already feeds).

- New table for cooldown tracking (kept separate from `users` to avoid
  touching that table at all):
  ```sql
  CREATE TABLE IF NOT EXISTS rob_cooldowns (
      user_id INTEGER PRIMARY KEY,
      last_attempt INTEGER NOT NULL
  );
  ```
- New `Config` constants: `ROB_COOLDOWN_SECONDS`, `ROB_SUCCESS_CHANCE`,
  `ROB_STEAL_PERCENT`, `ROB_FAIL_PENALTY_PERCENT`.
- Command lives in `bot/cogs/economy.py` or a new `bot/cogs/crime.py`.

### 4. Shop + inventory

Spend money on items — cosmetic (cash-sink) and functional (small gambling
luck boost, NPC training discount, etc.).

- New tables:
  ```sql
  CREATE TABLE IF NOT EXISTS shop_items (
      id INTEGER PRIMARY KEY,
      name TEXT NOT NULL,
      description TEXT,
      price INTEGER NOT NULL,
      effect TEXT              -- e.g. "luck_boost", "cosmetic"
  );

  CREATE TABLE IF NOT EXISTS user_inventory (
      user_id INTEGER NOT NULL,
      item_id INTEGER NOT NULL,
      quantity INTEGER NOT NULL DEFAULT 1,
      PRIMARY KEY (user_id, item_id)
  );
  ```
- Commands: `/shop`, `/buy`, `/inventory`.
- `shop_items` seeded with `INSERT OR IGNORE`, same as NPC templates.

### 5. Blackjack

A proper multi-round card game to sit next to `/coin-flip` and
`/roulette-color` in `bot/cogs/games.py`.

- **No schema changes at all** — reuses `update_user_money` /
  `update_pool_money` exactly like the existing games. Pure game-logic
  addition.

### 6. Achievements / badges

Passive tracking of milestones (first daily claim, biggest single win,
richest-ever balance, first NPC recruited, etc.), viewable via
`/achievements`.

- New table:
  ```sql
  CREATE TABLE IF NOT EXISTS user_achievements (
      user_id INTEGER NOT NULL,
      achievement_id TEXT NOT NULL,
      unlocked_at INTEGER NOT NULL,
      PRIMARY KEY (user_id, achievement_id)
  );
  ```
- Achievement definitions live in code (a small static dict), not a DB
  table, so no seeding step is needed — only unlocks are persisted.
- Hook points: small `check_and_award(user_id, event_type, value)` calls
  added at the end of existing commands (`/daily-claim`, `/coin-flip`,
  `/npc-recruit`, etc.) — additive, no change to existing return values.

### 7. Jackpot (redesigned)

**Deviated from the original plan.** The original commented-out `/jackpot`
command was mathematically broken — winning paid out exactly what you paid
in (`jackpot_amount == price_entry`), so there was no actual prize, which is
why it was dead code. Rather than resurrect that math, it was rebuilt as a
real progressive jackpot funded by the shared `pool` (which accumulates from
everyone else's gambling losses and otherwise never left the system):

- Fixed cheap ticket price (`Config.JACKPOT_TICKET_PRICE`, $50) and a small
  fixed win chance (`Config.JACKPOT_WIN_CHANCE`, 5%) — decoupled from pool
  size, so it's always affordable regardless of how big the jackpot has
  grown.
- The ticket price is added to the pool *before* the draw, then on a win the
  **entire current pool** (including the ticket just paid) goes to the
  winner and the pool resets to `Config.JACKPOT_POOL_SEED` (0). On a loss,
  the ticket price simply stays in the pool, growing it for the next player.
- Replaced the old chat-based "type yes/no" confirmation (which needed
  `bot.wait_for` on a text message) with a `discord.ui.View` Confirm/Cancel
  button pair, matching the pattern established by blackjack — more
  reliable and consistent with the rest of the UI.
- No scheduled auto-draw / no channel-ID config needed — it's purely
  on-demand via `/jackpot`, avoiding the deployment decision the original
  plan would have required (a specific channel ID for a scheduled
  announcement).
- No new tables — reuses `pool` and `users` via existing `DatabaseManager`
  methods (`update_pool_money`, `set_pool_money`, `update_user_money`).
- Ties into achievements: winning unlocks `jackpot_winner`, and a
  sufficiently large win also counts toward `big_winner`.

### 8. Trivia / quiz for cash

Low-effort engagement filler: `/trivia` posts a question, first correct
answer wins a small payout from the pool.

- New table for question bank (seeded once, `INSERT OR IGNORE`):
  ```sql
  CREATE TABLE IF NOT EXISTS trivia_questions (
      id INTEGER PRIMARY KEY,
      question TEXT NOT NULL,
      answer TEXT NOT NULL
  );
  ```
- Command in a new `bot/cogs/trivia.py`, using `discord.py`'s `wait_for` for
  the answer window (same pattern already sketched in the commented-out
  `/jackpot`).

## Suggested implementation order

1. Blackjack (#5) — zero schema risk, validates nothing else breaks first.
2. `/work` (#2) and `/rob` (#3) — small, additive, immediate economy payoff.
3. NPC Companions (#1) — the headline feature, biggest new surface area.
4. Shop + inventory (#4) — depends conceptually on NPCs/economy being in
   place for item effects to matter.
5. Achievements (#6) — hooks into everything above, so easiest to do once
   the other systems exist.
6. Weekly jackpot draw (#7) and Trivia (#8) — polish/engagement passes, no
   dependencies on the others.

## Rollout checklist per feature (apply every time)

- [ ] New tables use `CREATE TABLE IF NOT EXISTS`; any new column on an
      existing table uses a guarded `ALTER TABLE`.
- [ ] Any seed data uses `INSERT OR IGNORE` (or an equivalent existence
      check) so re-running `DatabaseManager.__init__` never duplicates rows.
- [ ] No existing method's SQL, return shape, or column usage is changed.
- [ ] New `Config` constants added, no existing ones changed.
- [ ] Tested against a **copy of the live `database.db`**, not just a fresh
      empty one, before merging — a fresh DB will hide bugs where a feature
      assumes a column/table exists that only a migration would have added.
- [ ] `requirements.txt` created/updated if a new dependency is introduced
      (none of the features above currently require one).
