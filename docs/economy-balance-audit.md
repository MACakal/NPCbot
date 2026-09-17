# NPCbot Economy Balance Audit

Status: fixes implemented in 5 phases (see [Implementation status](#implementation-status))
Scope: every place in `bot/` that creates, destroys, or moves money, plus the
features that change how much money a player gets (NPC perks, shop items, odds).
Date: 2026-09-17

## Implementation status

All tunables live in `bot/config.py`. Tests live in `tests/`; run them with
`cd tests && python -W ignore -m unittest` (they use a temp data dir, never
the real database).

| Phase | Findings | What changed |
|---|---|---|
| 1. Critical exploits | C1, C2, C3 | Amount validation and atomic wallet/bank moves; guarded `try_debit_user` for jackpot, blackjack and NPC costs |
| 2. Bank interest | H1, H2, L4 (labels) | `2%/day · B·K/(K+B)` with K = 5000 (at most $100/day), accrued hourly by whole periods, no dependence on others' balances |
| 3. Gambling | H3, H4, M1, M2, L3, L5 | Coin flip pays 0.95×, $1,000 max bet, 25% of losses destroyed, green pays 11×, blackjack Double Down, jackpot pays 50% of pool with a pool-scaled ticket price and 5-min cooldown |
| 4. Earnings & crime | H6, H7, M3, M4, M5 | 60s chat-reward cooldown (guild only), 8 work shifts/day, daily streak up to +50%, 5% destroyed transfer tax and $5,000/day limit, robbery minimum wallet / $500 steal cap / fine ≥ 50% of attempt / 2h target protection, trivia channel cooldown / 5 wins/day (starters may answer their own rounds; the daily cap bounds self-farming) / $25 minted prize / 60 questions |
| 5. NPCs, shop, polish | H5, L1, L2, M6, M7, L4, timestamps | Perks 5%/5%/10% per level, choose your archetype, 30-min training cooldown, 25% training refund on release, Discount Badge $100 for 25%, no duplicate permanent items, consumables (Lockpick, Padlock, Energy Drink) with `/use`, leaderboard by wallet + bank, true UTC timestamps |

**Not done (needs a decision from you):**
- **Existing live balances** were left untouched. Balances that were already
  inflated stop compounding but aren't reduced. Run Appendix B to decide
  whether to cap or rescale them, and to find negative balances left by
  C1–C3.
- **NPC upkeep and a wealth tax** (M7) weren't added. The sinks that now exist
  are: burned gambling losses, the transfer tax, and consumable items.
- **Blackjack hands lost on restart** (M2) still aren't persisted.

**Deployment notes:**
- Schema changes are additive only (`user_timers`, `daily_streaks`,
  `daily_counters`). The NPC roster and shop catalog now *upsert* on startup,
  so their new values reach the live DB.
- The bot needs a restart to pick up the changes. Slash-command option
  changes (bet ranges, archetype choice, `/use`) show up after the command
  tree re-syncs on startup.
- The host is UTC+2, and old timestamps were stored 2h behind real time. After
  the switch, existing cooldowns expire up to 2h early once. This is harmless.

## How to read this document

Each finding lists:

- **Where**: file and line
- **What's wrong**: the exact mechanic
- **When it breaks**: the concrete situation where it gets abused or drifts
- **Fix**: what to change, with suggested numbers

Findings are sorted by severity:

| Severity | Meaning |
|---|---|
| 🔴 Critical | Free or unlimited money right now. Fix before anything else. |
| 🟠 High | Breaks the economy over days or weeks, or one strategy clearly beats all others. |
| 🟡 Medium | Clear imbalance that players will find and use, but it's bounded. |
| 🟢 Low | Tuning, UX, or correctness details that nudge balance. |

All numbers below come from the formulas in the code. The interest and
blackjack figures come from simulations (5-minute interest ticks, and 400k
blackjack hands using basic strategy).

> The local `database/database.db` is a test copy (1 user, empty bank), so no
> production data was used. Before rolling out fixes, run the audit queries
> in [Appendix B](#appendix-b-audit-queries-for-the-live-db) on the live DB.

---

## 0. The big picture: where money comes from and where it goes

**Faucets (money is created):**

| Source | Amount | Limit |
|---|---|---|
| Starting balance | $100 | once per user |
| Message | $0.50 | **none**, every message counts |
| `/daily-claim` | $250 (up to +15% with an NPC) | 24h |
| `/work` | $40 (up to +15% with an NPC) | 30 min, so up to 48/day |
| Coin flip win | +bet | **none** |
| Roulette win | +bet, or +10×bet on green | **none** |
| Blackjack win | +bet, or +1.5×bet on a blackjack | **none** |
| **Bank interest** | **10%/day compounding** (2.15% to 10% depending on your share) | **none** |

**Transfers (money moves, total stays the same):** `/give`, a successful
`/rob`, a failed-rob fine (goes to the pool), gambling losses (go to the pool),
the jackpot (pool goes to a player), trivia (pool goes to a player).

**Sinks (money is destroyed):** shop purchases, NPC recruit and training.
That's all. Both are **one-time purchases** with a small, fixed total cost
(about $630 to max an NPC, $650 for all three shop items).

**The core problem:** nearly every faucet is uncapped or recurring, and every
sink is one-time. Gambling losses aren't destroyed either; they're recycled
into the pool and paid back out. So total money only goes up, and bank
interest makes it go up **exponentially**. Every fixed price and reward in
`config.py` loses value over time.

---

## 🔴 Critical

### C1. Negative `/deposit` makes free money

**Where:** `bot/cogs/economy.py:193-223`, `bot/database/manager.py:493-499`

**What's wrong:** `amount` is never checked for `> 0`. With `amount = -1000000`:

1. `user_data["money"] < amount` is false, so the "insufficient funds" check passes.
2. `deposite_money_to_bank` runs `money = money + (-1000000)`. That query has
   no `money >= ?` guard, so the bank balance goes to **-1,000,000**.
3. The wallet becomes `money - (-1000000)`, so it goes **up by $1,000,000**.

**When it breaks:** any time, for any user. The negative bank balance never
has to be repaid. It also pushes `get_total_money_in_circulation()` down,
which changes everyone else's interest rate (see H1). If the total drops to 1
or less, `max(total, 1)` makes every depositor's share `p = 1`.

**Fix:**
- Reject `amount <= 0` in `/deposit` and `/withdraw`, the same way `/give`
  already does. Better: use `app_commands.Range[float, 0.01, None]` so
  Discord blocks it before it reaches the bot.
- Make the deposit a single atomic transaction in the DB layer, like
  `transfer_money`: `UPDATE users SET money = money - ? WHERE id = ? AND money >= ?`,
  then credit the bank, in one `BEGIN`/`COMMIT`. Stop using `set_user_money`
  with a stale `user_data` value.
- Run the Appendix B queries to find and reset anyone who already has a
  negative bank balance.

### C2. Negative `/withdraw` puts money you don't have in the bank, and it earns interest

**Where:** `bot/cogs/economy.py:225-246`, `bot/database/manager.py:501-507`

**What's wrong:** with `amount = -1000000`, the guard `money >= -1000000` is
always true. The bank gains $1M, `total_withdrawn` drops, and the wallet goes
to **-$1M** with no check.

**When it breaks:** the fake $1M earns interest right away. Even at the lowest
rate (p = 1), that's **about $21,500 a day of new money**. The player can
later withdraw the principal to pay off the negative wallet and keep all the
interest. A negative wallet also can't be robbed (`crime.py:58` rejects
`money <= 0`), so the debt is safe.

**Fix:** same as C1: validate `amount > 0` and make withdrawals atomic. Also
add a rule that wallet balances can never go negative anywhere (see C3).

### C3. Jackpot doesn't recheck your balance when you click "Buy Ticket", so wallets go negative

**Where:** `bot/cogs/games.py:419-431` (the check) vs `games.py:175-183` (the charge)

**What's wrong:** `/jackpot` checks `money >= 50` when the message is posted.
The charge happens up to 30 seconds later when the button is clicked, with no
second check. `update_user_money(-50)` has no floor.

**When it breaks:** a player with $50 opens five `/jackpot` prompts, or opens
one and then spends their money on a coin flip, then clicks Buy on each prompt.
They buy tickets with money they don't have, and their wallet goes negative.
When the pool is large, this is a free shot at the entire pool (see H3).

**Fix:** charge the ticket atomically on click:
`UPDATE users SET money = money - ? WHERE id = ? AND money >= ?`, and abort
if `rowcount == 0`. As a safety net, reuse this "guarded debit" helper for
every place that takes money from a user (blackjack at `games.py:393`, NPC
costs at `npc.py:76` and `npc.py:153`).

---

## 🟠 High

### H1. Compounding bank interest grows without limit. The "dampener" only slows it down.

**Where:** `bot/database/manager.py:532-562`

**How it works now:**

```
period_rate = 1.10^(1/288) - 1        # 10%/day, compounded every 5 min
p           = your_bank / (all wallets + all banks)
f           = exp(-1.5 * p)           # between 1.0 and 0.223
r_eff       = period_rate * f * (1 + npc_bank_bonus)
new_balance = bank * (1 + r_eff) ^ periods_passed
```

**Why "balanced by total economy" doesn't actually balance it:**

`f` never goes below `e^-1.5 = 0.223`. It lowers the growth rate but never
turns exponential growth into bounded growth. Even the biggest whale keeps
compounding forever:

| Your share `p` | `f` | Daily rate | Doubling time |
|---|---|---|---|
| 0.00 (small depositor) | 1.000 | 10.00% | 7.3 days |
| 0.10 | 0.861 | 8.55% | 8.4 days |
| 0.25 | 0.687 | 6.77% | 10.6 days |
| 0.50 | 0.472 | 4.61% | 15.4 days |
| 0.75 | 0.325 | 3.14% | 22.4 days |
| 1.00 (owns everything) | 0.223 | 2.15% | 32.6 days |

For comparison, a real savings account pays roughly 4–5% **per year**. The
lowest rate here is 2.15% **per day**, which is about 2,300× per year.

**Simulated scenarios** (interest applied every 5 minutes, wallets held fixed):

| Scenario | Day 7 | Day 30 | Day 90 | Day 180 | Day 365 |
|---|---|---|---|---|---|
| **S1.** Only depositor, $1,000 in bank, $2,000 in wallets server-wide | $1,460 | $3,845 | $20,942 | $159,137 | **$8.3M** |
| **S2.** Whale $10,000 plus 4 players with $200 each (the whale's balance) | $12,299 | $25,721 | $522K | $211M | **$94 trillion** |
| S2, each $200 player | $382 | $2,951 | $311K | $196M | $94 trillion |

What these show:

1. **The dampener evens out depositors but inflates everyone.** In S2, the
   small depositors catch up to the whale by around day 180, but only because
   everyone is heading toward infinity. The dampener changes who gets rich,
   not whether money runs away.
2. **Fixed rewards become meaningless.** In S1, a $1,000 deposit earns more
   interest per day than `/daily-claim` ($250) after **58 days**, with no
   effort. After that, `/work`, `/daily-claim`, messages, trivia, and every
   price in the shop don't matter.
3. **Supply growth is driven by the number of depositors.** With N equal
   depositors, each has `p ≈ 1/N`, so a busier server gets a *higher* rate
   for everyone (N=5 gives about 7.3%/day, and total supply doubles about
   every 10 days).

**Fix (recommended): switch to interest that is bounded per account.**

Replace the share-based `f(p)` with a per-account limit so the dollar amount
of interest per day has a ceiling:

```
daily_interest(B) = base_rate * B * K / (K + B)
```

- Small balances (B much less than K) earn about `base_rate`. That keeps
  saving worthwhile for new players.
- Large balances (B much greater than K) earn at most `base_rate * K` per
  day. Growth becomes **linear, not exponential**.
- Suggested values: `base_rate = 0.02` (2%/day), `K = 5000`, so the cap is
  **$100/day**. That's 40% of a daily claim, which is meaningful but won't
  replace playing.

Simulated with the proposal (daily ticks):

| Starting balance | Day 7 | Day 30 | Day 90 | Day 365 |
|---|---|---|---|---|
| $1,000 | $1,122 | $1,608 | $3,579 | $21,972 |
| $100,000 | $100,667 | $102,859 | $108,588 | $134,999 |

Additional changes:

- **Stop compounding every 5 minutes.** Pay interest once per full day,
  computed per day (loop the days, or use a closed form). This also fixes H2.
- **Set a hard cap on interest-bearing balance** (for example, $50,000).
  Anything above it earns nothing. This is a simpler alternative, or an
  addition, to the K formula.
- **Optionally, fund interest from a reserve instead of creating it.** Pay
  interest out of a "central bank" row that fills up from the sinks below
  (transfer tax, rob fines, part of gambling losses). When the reserve is
  empty, no interest is paid. This makes the economy closed.
- **Add a recurring sink** so money actually leaves the economy (see M7).
- Move the constants (`0.10`, `1.5`, `300`, `288`) into `Config` so they can
  be tuned without editing SQL-layer code. They're currently duplicated in
  `apply_interest` and `return_interest_rate`.

**Migration note:** existing live bank balances may already be inflated.
Decide whether to (a) keep them, (b) cap them at the new cap, or (c) rescale
all balances by the same factor. Run the Appendix B queries first to see how
big the problem is.

### H2. Claiming interest rarely pays far more than claiming often

**Where:** `bot/database/manager.py:539-549`

**What's wrong:** `p` (and so `f`) is measured **once, at claim time**, using
the balance *before* any of the unpaid interest is added. That single rate is
then applied to **every** 5-minute period since the last claim. So the longer
you wait, the more your real share is understated, and the higher your rate.

**Simulated** (S1 setup: $1,000 in bank, $2,000 in wallets, 90 days):

| Claims interest (by running any bank command)... | Balance on day 90 |
|---|---|
| every 5 min | $20,942 |
| daily | $21,165 |
| weekly | $22,614 |
| monthly | $31,278 |
| **once, on day 90** | **$181,836 (8.7× more)** |

**When it breaks:** anyone who understands the formula deposits once and
never runs `/bank-balance`, `/deposit`, `/withdraw`, or `/bank-stats` until
they're ready to cash out. The same thing makes the rate retroactive: if other
players' balances change right before your claim, your rate for the whole gap
changes too.

A smaller, opposite issue: `last_interest` is set to `now` instead of
`last_interest + periods_passed * 300`, so up to 299 seconds of accrual is
lost on every claim. Players who check often are slightly penalized.

**Fix:** compute interest period by period (or day by day with H1), using a
closed form or a bounded loop, and set
`last_interest += periods_passed * PERIOD`. With the H1 formula, the result no
longer depends on everyone else's balance, so the retroactive problem goes
away.

### H3. The jackpot is profitable once the pool passes $950, and whoever has $1,000 can take it

**Where:** `bot/cogs/games.py:174-210`, `config.py:26-28`

**What's wrong:** the ticket costs $50, wins 5% of the time, and pays the
whole pool (including the ticket just bought). Expected value is
`0.05 × (pool + 50) − 50`, which is positive once **pool > $950**. There's no
cooldown and no limit on tickets. On average it takes 20 tickets ($1,000) to
win.

**When it breaks:** the pool grows from everyone's gambling losses and rob
fines. Once it passes about $950, any player with around $1,000 can spam
tickets until they win. Poorer players' losses end up with whoever has the
most cash to spend. With C3, they don't even need the cash.

**Fix (pick one or more):**
- **Per-user cooldown** on buying tickets (for example, 1 ticket every 10 minutes).
- **Pay out only part of the pool** (for example, 50%) and keep the rest as the next seed. This keeps the pool from being emptied in one go.
- **Scale ticket price with the pool** (for example, `max(50, pool × 2%)`). At 5% odds, EV then stays negative at every pool size.
- **Switch to a timed raffle**: tickets are collected over 24h and one winner is drawn. This rewards participation instead of having the most cash.
- Set `JACKPOT_POOL_SEED` above 0 (for example, $500) so the pool doesn't sit at $0 after a win and trivia still has something to pay (see M3).

### H4. Coin flip has no house edge and every win creates new money

**Where:** `bot/cogs/games.py:254-299`

**What's wrong:** 50/50 odds at 1:1 is **0% house edge**. Wins are created
from nothing; losses go to the pool. On average, each coin flip adds
`0.5 × bet` of **new money** to the economy (wallets plus pool). There's no
maximum bet.

**When it breaks:**
- A rich player (especially one fed by bank interest) can use a martingale
  strategy (double the bet after each loss). With no table limit and no house
  edge, a big bankroll almost always walks away with its target profit.
- Every flip feeds the pool, which feeds H3.

**Fix:**
- Add a house edge: pay 0.95× on a win (or win 48% of the time). This matches
  roulette and blackjack being negative-EV.
- Add `MAX_BET` (for example, $1,000 or 10% of wallet, whichever is lower)
  for all gambling commands.
- Consider destroying a share of every loss (for example, 25% burned, 75% to
  the pool) so gambling becomes a real sink.

### H5. The banker NPC outperforms every other companion once your bank passes about $2,500

**Where:** `bot/database/manager.py:174-189` (templates), `manager.py:547-548` (how it's applied)

**What's wrong:** every perk is `perk_value × level`, but they apply to
different kinds of rewards:

| NPC | Perk at L5 | Value per day |
|---|---|---|
| Reggie (daily_bonus) | +15% daily | +$37.50, fixed |
| Big Clavicle (work_bonus) | +15% work | +$6 per shift, up to about +$48 with heavy play |
| **Dr. Ledger (bank_interest_bonus)** | **multiplies the interest rate by 1.15** | **about 1.5% of bank balance per day at f=1, with no upper limit** |
| The Sternum (rob_defense) | −25 pp chance of being robbed | situational |
| Slippery Sinew (rob_success_bonus) | +25 pp chance to rob successfully | situational |

Dr. Ledger's bonus beats Reggie's once the bank holds about $2,500, and from
there the gap keeps growing because it compounds. Simulated: two players with
$1,000 each (wallets $5,000), one with a L5 banker: day 30 is $8,583 vs
$7,132, and day 90 is **$188K vs $155K**.

Recruitment is random (`get_random_npc_template`), and `/npc-release` is
free, so the best play is to recruit and release until you get the banker.
That costs an average of 5 × $150 = $750 and throws away any training.

**Fix:**
- After fixing H1, make the banker bonus a **flat add-on**, like
  `+0.2 pp/level` to `base_rate`, or raise `K` instead of multiplying the rate.
  Its payoff is then capped like the others.
- Make the daily and work perks larger (for example, 5%/level) so they stay
  competitive, or give them flat bonuses (+$15/level on daily).
- Let players **choose** their companion archetype (costs the same) instead
  of a random roll, **or** add a cooldown to recruiting (for example, once
  every 24h) to stop reroll spam.

### H6. Messages pay money with no cooldown

**Where:** `bot/cogs/economy.py:14-21`

**What's wrong:** every non-bot message pays $0.50 with no rate limit, no
minimum length, and no channel filter. DMs to the bot count too, because
`on_message` fires for them.

**When it breaks:** 500 one-character messages is **$250**, the same as a
daily claim. A simple macro, or pasting a few lines at a time, farms without
limit and spams the server. Trivia answers and all normal chat also earn money.

**Fix:**
- Add a per-user cooldown: pay at most once every 60 seconds (MEE6-style),
  tracked in memory as `dict[user_id] -> last_paid_ts`. No schema change needed.
- Ignore DMs (`if message.guild is None: return`) and messages shorter than
  a few characters.
- Optional daily cap (for example, $50/day from chat).

### H7. Robbery is free for broke players and can target the same person over and over

**Where:** `bot/cogs/crime.py:55-94`, `config.py:34-37`

**What's wrong:** robber EV = `0.5 × 0.20 × target − 0.5 × 0.15 × robber` =
**`0.10·T − 0.075·R`**. The fine scales with the robber's wallet, so:

- A robber with a **$0 wallet risks nothing**. Every attempt is pure profit.
  New accounts or alts can rob wealthy players for free once an hour each.
- Robbing only makes sense when `T > 0.75·R`, so it's always "poor robs rich".
  The poor can't lose and the rich can't fight back.
- There's **no cooldown on being robbed**. Ten players with cooldowns ready
  can each take 20% in turn. With a 50% success rate, the target keeps about
  0.8^5 ≈ 33% on average.
- Bank money can't be robbed at all, so combined with H1, the obvious choice
  is to keep everything in the bank. Robbery then only hits casual players who
  leave cash in their wallet.

**Fix:**
- Require a minimum robber wallet (for example, `R ≥ $100`), and set the fine
  to `max(15% of R, 50% of the amount they tried to steal)`. Failing then
  always costs something that scales with the reward.
- Add a **target-side protection window** (for example, a successful robbery
  protects the target for 2h). This needs a `last_robbed` column or a small
  new table, following the additive schema rule in `feature-roadmap.md`.
- Cap each successful theft (for example, `min(20% of T, $500)`) so one lucky
  roll can't take a whale's entire wallet.
- Optional: let robbery reach a small share of bank balances only when the
  robber has the gambler NPC. That gives the bank some risk.

---

## 🟡 Medium

### M1. Roulette green pays less than red or black

**Where:** `bot/cogs/games.py:241, 339-364`

There are 39 slots: 18 red, 18 black, 3 green.

| Bet | Profit on win | Win chance | Player EV |
|---|---|---|---|
| Red / Black | 1× | 18/39 | **−7.7%** |
| Green | 10× | 3/39 | **−15.4%** |

Green, the "jackpot" option, is twice as bad as red. The fair payout for 3/39
is 12×.

**Fix:** pay **11× profit** on green. That matches red/black at −7.7%
(`3·11 − 36 = −3`). If you want red/black closer to blackjack, use 37 slots
(18/18/1) with green at 35×, which is standard European roulette at −2.7% for
every bet.

### M2. Blackjack edge is higher than it looks, and the rules are limited

**Where:** `bot/cogs/games.py:47-157`

With the current rules (no double down, no split, dealer stands on all 17s,
blackjack pays 3:2, fresh deck every hand), a simulated basic-strategy player
has an EV of about **−1.9%**. That's fine as a house edge. But:

- Standard casino blackjack is about −0.5% because players can double and
  split. Without those, a lot of the skill is gone.
- A bet is **lost (destroyed, not sent to the pool)** if the bot restarts or
  the `View` breaks mid-hand, because the bet is taken up front
  (`games.py:393`) and only settled by the view. `on_timeout` handles normal
  timeouts, but not a crash or restart.

**Fix:** add **Double Down** (easy: take one card, double the bet with a
guarded debit, then settle), which brings the edge to about −1%. Optionally
add splits. On startup, there's no stored game state, so either accept the
loss and document it, or persist open hands.

### M3. Trivia can drain the pool with no limit, and the person who starts it can answer it

**Where:** `bot/cogs/trivia.py:15-67`, `config.py:45-46`, `manager.py:231-242`

**What's wrong:**
- No cooldown on `/trivia`. A player can run it repeatedly and answer every
  question themselves. Nothing stops the starter from answering.
- Only **10 questions**, and the answer is shown on timeout, so they're easy
  to memorize within minutes.
- Each correct answer pays $75 **from the pool**, and the pool is the jackpot.
  Trivia farmers drain the jackpot. Once the pool is $0, trivia pays nothing,
  and the embed still says "$75".

**When it breaks:** pool at $900 means 12 quick `/trivia` + answer rounds
empty it. That's roughly two minutes of work for $900.

**Fix:**
- Add a per-channel cooldown (for example, 1 trivia every 5 minutes) and a
  per-user win cap (for example, 3 wins/hour).
- Don't let the starter answer their own question (`message.author.id != interaction.user.id`).
- Expand the question bank a lot (at least 100), or pull from an API like
  Open Trivia DB.
- Pay a smaller, fixed amount that is **created** (for example, $25), or pay
  `min(75, 5% of pool)`, so trivia doesn't compete with the jackpot.
- Show the amount that will actually be paid (`min(reward, pool)`) in the
  prompt.

### M4. `/work` earns up to 7× more than `/daily-claim` for active players

**Where:** `config.py:25, 32-33`

`/work` pays $40 every 30 minutes, which is up to **$1,920/day** for someone
online all day, and about $320 for 8 shifts. `/daily-claim` pays $250 once.
The command called "daily" ends up being the smaller reward, and very active
(or scripted) users pull far ahead.

**Fix:** pick one:
- 1-hour cooldown with a daily cap (for example, 8 shifts/day, so at most $320).
- Pay less for each shift after the Nth that day ($40, $40, $40, $20, $10, …).
- Add a **daily streak** multiplier (+10% per consecutive day, up to +100%) so
  daily claims reward consistency.

### M5. `/give` lets players pass money to alts and dodge the interest dampener

**Where:** `bot/cogs/economy.py:117-142`, `manager.py:337-358`

No tax, no limit, no account-age check. Combined with H1, splitting $10,000
across 5 alts (each then has a lower `p`, so a higher `f`) gives:

| Setup | Day 7 | Day 30 | Day 90 |
|---|---|---|---|
| One account, $10,000 | $12,064 | $21,505 | $84,684 |
| **5 alts, $2,000 each (total)** | **$16,730** | **$87,190** | **$6.07M** |

That's about **72× more** by day 90. Alts can also give their robbery winnings
and trivia prizes to a main account.

**Fix:**
- A transfer tax (for example, 5%) that goes to the pool or is destroyed.
  This also becomes a recurring sink.
- A daily send limit per user.
- Switching to H1's per-account `K` formula mostly removes the alt benefit on
  its own (each alt is capped at $100/day, which still pays for more alts, so
  combine it with the tax).

### M6. Shop items are poor value, and buying duplicates wastes money

**Where:** `manager.py:202-224, 694-743`

| Item | Price | What it actually does | Payback |
|---|---|---|---|
| Discount Badge | $300 | 10% off recruit ($15) and each training ($3 × 16 = $48) = **$63 per NPC maxed** | about 5 maxed NPCs. Almost never pays off. |
| Insurance Policy | $250 | Halves failed-rob fines forever | Only matters for rich robbers, who rarely rob because of H7 |
| Golden Feather | $100 | Cosmetic | n/a |

- Items are permanent (never used up), so the shop is a single one-time sink
  of $650 at most.
- `purchase_item` lets you buy the same item again, but
  `get_item_effect_value` ignores quantity (by design, it doesn't stack). A
  second Discount Badge takes $300 and does nothing, with no warning.

**Fix:**
- Block buying a second copy of functional items (or refund them), or make
  quantity matter.
- Lower the Discount Badge to about $100, or increase it to 25% and apply it
  to jackpot tickets too.
- Add **consumable** items to create recurring sinks: a "Lockpick" (+10% rob
  chance on the next attempt), a "Coffee" (skip the `/work` cooldown once), a
  "Padlock" (24h rob protection), a "Lottery Scratch-off". These keep money
  leaving the economy.

### M7. There's no recurring money sink

**Where:** the whole economy (see section 0)

Once someone owns a maxed NPC and the shop items, nothing takes money out of
the economy again. Everything that looks like a sink (gambling losses, rob
fines) just moves money to the pool, which gets paid back out.

**Fix (combine with H1):**
- Burn part of each gambling loss (see H4).
- Transfer tax (see M5).
- Consumable shop items (see M6).
- An NPC upkeep fee: a small daily cost to keep perks active, charged when
  the perk is used. Or let NPCs lose XP if they aren't trained weekly.
- Optional: a small wealth tax above a threshold (for example, 0.5%/day on
  bank balances over $50,000).

---

## 🟢 Low

### L1. NPC training has no cooldown, so "training" is just a one-time $480 fee

**Where:** `bot/cogs/npc.py:117-171`

Going from level 1 to 5 takes `4 × 100 XP / 25 = 16` trainings × $30 =
**$480**, which can be done in one sitting. The progression system has no
time dimension.

**Fix:** one training per hour (or per `/work` cooldown), or raise the XP
needed per level (100, 150, 200, 250). Total cost to max an NPC (with the
$150 recruit) should be compared against each perk's payoff in H5.

### L2. Releasing an NPC throws away everything you put into it, with no refund

**Where:** `bot/cogs/npc.py:173-193`

Releasing a L5 NPC loses $630. This works against H5 rerolling (good), but it
feels bad if a player picked the wrong one early. It becomes more important if
companions stay random.

**Fix:** refund part of the training cost (for example, 25%), or allow a paid
"re-specialize" that swaps the archetype and keeps the level.

### L3. Achievement thresholds are fixed, while the economy inflates

**Where:** `config.py:43-44`

`HIGH_ROLLER_BET_THRESHOLD = 500` and `BIG_WINNER_WIN_THRESHOLD = 1000` become
trivial once interest inflates balances (see H1). Also,
`check_gamble_achievements` passes the **whole pool** as "profit" for jackpot
wins (`games.py:208`), while other games pass net profit.

**Fix:** after H1 is fixed, the fixed numbers are fine. Pass
`won_amount - ticket_price` as profit for jackpot wins so all games measure it
the same way.

### L4. Some displayed numbers are wrong or misleading

- `/interest-rate-person` (`admin.py:34`) says "X% interest **every 5 minutes**"
  but shows the **daily** rate.
- `/bank-stats` (`economy.py:264`) labels the nominal
  `10% × f × (1+bonus)` as "Daily interest". That's only exact at `f = 1`,
  because the real compounding rate is `(1+PR·f)^288 − 1`.
- `/leaderboard` (`economy.py:144-165`) only sorts by **wallet**, so the
  richest bank savers are hidden. Players can't see how uneven things are.
- The trivia prompt always shows $75, even when the pool has less (see M3).

**Fix:** correct the labels, show the real effective daily rate, and rank the
leaderboard by `wallet + bank` (or show both columns).

### L5. `/give`, coin flip, and blackjack accept tiny or fractional amounts

`amount: float` allows bets like `0.0001`. That's harmless for EV, but it can
be used to farm achievements or spam, and it clutters balances with long
decimals.

**Fix:** use `app_commands.Range[float, 1, MAX_BET]` (or cents as integers),
and round stored balances to 2 decimals.

---

## Non-balance bugs found during the audit (for reference)

These aren't balance issues, but they affect the numbers above:

- `datetime.utcnow().timestamp()` (used in `economy.py`, `crime.py`, `npc.py`,
  `manager.py`) treats UTC time as if it were **local** time. Cooldowns stay
  consistent on one machine, but they shift by an hour when daylight saving
  time changes, and "Next Claim … UTC" is actually wrong unless the host is in
  UTC. Use `int(time.time())` or `datetime.now(timezone.utc).timestamp()`.
- `/deposit` and `/withdraw` use read-then-`set_user_money` (absolute write)
  instead of a relative update. That's safe under asyncio today because nothing
  awaits in between, but it breaks as soon as anything async is added. Covered
  by the atomic fix in C1 and C2.

---

## Suggested fix order

1. **C1, C2, C3.** Validate amounts and add guarded debits. Then audit the live DB (Appendix B).
2. **H1 + H2.** Replace the interest formula (bounded per account, daily, no retroactive `p`). Decide how to migrate existing balances.
3. **H6, H4, H3.** Message cooldown, coin-flip edge and max bet, jackpot cooldown or partial payout.
4. **H7, H5.** Robbery floor and protection, rebalance NPC perks and recruit choice.
5. **M1–M7.** Roulette payout, trivia cooldown, work cap, transfer tax, shop and consumables, recurring sinks.
6. **L1–L5.** Polish.

Once the fixes are in, move every tunable (`base_rate`, `K`, tax rates, max
bet, cooldowns) into `Config` so balance changes only need edits in
`config.py`.

---

## Appendix A: Key formulas

```
Bank interest (current)
  PR    = 1.10^(1/288) − 1
  p     = clamp(bank / (Σwallets + Σbanks), 0, 1)
  f     = e^(−1.5·p)                  ∈ [0.223, 1]
  daily = (1 + PR·f·(1+bonus))^288 − 1   ∈ [2.15%, 10%]  (before bonus)

Bank interest (proposed)
  daily_interest(B) = base · B · K / (K + B)     → ≤ base·K per day
  base = 0.02, K = 5000 → at most $100/day

Robbery EV for the robber
  0.5·0.20·T − 0.5·0.15·R = 0.10·T − 0.075·R

Jackpot EV per ticket
  0.05·(pool + 50) − 50   > 0  ⇔  pool > 950

Roulette EV (39 slots: 18R/18B/3G)
  red/black: (18·1 − 21)/39 = −7.7%
  green:     (3·10 − 36)/39 = −15.4%   (11× → −7.7%)

Coin flip: EV 0; new money created per flip = 0.5·bet
Blackjack (as implemented, basic strategy, simulated): ≈ −1.9%
```

## Appendix B: Audit queries for the live DB

Run these against a **copy** of the live `database/database.db`:

```sql
-- Negative balances (C1/C2/C3 exploits already used?)
SELECT id, money FROM users WHERE money < 0;
SELECT id, money, total_deposited, total_withdrawn FROM Bank WHERE money < 0;
SELECT id, total_deposited, total_withdrawn FROM Bank
 WHERE total_deposited < 0 OR total_withdrawn < 0;

-- Size of the interest problem (H1)
SELECT COUNT(*), SUM(money), MAX(money), SUM(total_interest_earned) FROM Bank;
SELECT SUM(money) FROM users;
SELECT id, money, total_deposited, total_interest_earned,
       total_interest_earned / NULLIF(total_deposited, 0) AS interest_ratio
  FROM Bank ORDER BY money DESC LIMIT 10;

-- Pool state (H3/M3)
SELECT money FROM pool WHERE id = 1;

-- NPC distribution (H5): is everyone running the banker?
SELECT t.name, u.level, COUNT(*) FROM user_npcs u
  JOIN npc_templates t ON t.id = u.npc_template_id GROUP BY 1, 2;

-- Useless duplicate shop purchases (M6)
SELECT user_id, item_id, quantity FROM user_inventory WHERE quantity > 1;
```
