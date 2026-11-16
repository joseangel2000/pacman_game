# Pacman Capture the Flag — EUTOPIA Pacman Contest

A two-person team project for **Autonomous Systems** (EMAI 2026-27, UPF):
**@diegogreaza03** and **@joseangel2000**.

Two agents (Pacman when attacking, ghost when defending) that eat the opponent's food and protect ours,
playing on the course's `pacman-contest` platform. All the team's code lives in **`my_team.py`** (repo
root); every other folder is tooling to measure and improve that one file.

| Date | What |
|---|---|
| Nov 23 | Test run |
| Dec 3, 23:59 | Final submission |
| Dec 4 | Final tournament |

> **Only have 10 minutes?** Read [Current status](#1-current-status), follow
> [Getting started](#3-getting-started), run `python tools/defensa_bench.py` to check that everything
> works, then jump to [Next steps](#9-next-steps-ordered-by-expected-payoff).

> **Language note:** the code comments, tool docstrings and the *output* of the tools (e.g. the column
> names of `defensa_bench.py`) are written in **Spanish**. This README is in English and lists the Spanish
> names next to their meaning, so you can match them up.

---

## Table of contents

1. [Current status](#1-current-status)
2. [Rules and constraints that shape the design](#2-rules-and-constraints-that-shape-the-design)
3. [Getting started](#3-getting-started)
4. [Repository layout](#4-repository-layout)
5. [How the agent works](#5-how-the-agent-works)
6. [Measurement and learning tools](#6-measurement-and-learning-tools)
7. [How we work: measure before you believe](#7-how-we-work-measure-before-you-believe)
8. [Measured results and what was discarded](#8-measured-results-and-what-was-discarded)
9. [Next steps (ordered by expected payoff)](#9-next-steps-ordered-by-expected-payoff)
10. [Before submitting (checklist)](#10-before-submitting-checklist)
11. [Working as a pair with git](#11-working-as-a-pair-with-git)
12. [Known pitfalls](#12-known-pitfalls)

---

## 1. Current status

- **Version: v4.3** = v4.2 + `pocket_safe=1` (the attacker only goes for food in a dead end if it can eat it and get
  back out of the mouth before any ghost, seen or estimated, can reach that mouth; section 8.4). **Phase 2 (attack)
  closed on 2026-11-16** with 3 of its 4 exit criteria met.
- **v4.2** = v4.1 + `seal=2` ("seal and squeeze": close **all** the invader's exits and our capsules,
  then close in on it; section 8.3). Phase 1 (defence) closed with this version.
- **v4.1** = v4 + `intercept_fallback=1` (the missing half of playbook point 1, section 8.1).
- **v4** is v3 (attack with stuck detection, Bayesian tracking of hidden opponents, dynamic
  roles) plus a new defence (interception on the invader's escape route, a "leash" on defender raids,
  dead-end handling). With `intercept`, `pocket_trap` and `leash_mode` set to 0, v3 is recovered exactly.
- Everything switched on in `PARAMS` has been **measured** (section 8). Anything that did not help is
  implemented but **switched off**.
- Time per action in the worst case measured: **~57 ms** for v4; v4.2: **36 ms**; v4.3: **38 ms** max in 6 timed games
  against `greedy_v4` (the limit is 1 s). Start-up: ~0.7 s (limit 15 s).
- Compatible with **Python 3.8**: v4 was verified by playing complete games on 3.8.20; v4.2 and v4.3 have only been
  checked for 3.8 *syntax* (`ast.parse(..., feature_version=(3, 8))`). **Play full games on a real 3.8 before
  submitting.**

Key results: wins-draws-losses, win rate and tournament points per game (win 3, draw 1, loss 0).

| Against | v4 | v4.2 | **v4.3 (current)** |
|---|---|---|---|
| Own league, 11 opponents, training maps (308 games) | 235-13-60 · 76 % · 2.33 | 252-15-41 · 82 % · 2.50 | **250-14-44 · 81 % · 2.48** |
| Own league, **new** maps RANDOM101-112 (264) | 194-22-48 · 73 % · 2.29 | 198-24-42 · 75 % · 2.34 | **195-26-43 · 74 % · 2.31** |
| `greedy_v4` (a classmate's agent, 500) | 146-59-295 · 29 % · 0.99 | 204-83-213 · 41 % · 1.39 | **240-79-181 · 48 % · 1.60** |
| `greedy_v4`, **new** maps RANDOM301-400 (200) | 66-23-111 · 33 % · 1.10 | 87-24-89 · 44 % · 1.43 | **89-27-84 · 44 % · 1.47** |

(v3 for reference: league 2.20, new maps 1.95, `greedy_v4` 0.81. v4.1: 2.35 / 2.30 / 1.16 / 1.22.) v4 numbers were
re-measured on 2026-11-15 with freshly cloned opponents and reproduce the original ones (2.33 / 2.29 / 0.99).

**Against `greedy_v4` we now win more often than we lose** (240 vs 181 out of 500), and our pacmans get eaten
0.39 times per game (0.82 with v4.2). The weakest point left is still **how much food we deposit ourselves**: 12.0 per
game versus his 10.0 (section 8.4 and section 9).

---

## 2. Rules and constraints that shape the design

From `pacman-contest/src/contest/CONTEST.md`, the course's project PDF and the code (`capture.py`):

- **Submission:** a `my_team.py` in the repo root exposing `create_team(first_index, second_index, is_red, **kwargs)`
  that returns two agents inheriting from `CaptureAgent`.
- **Time:** 1 s per action; three timeout warnings, or a single action over 3 s, means forfeit.
  15 s start-up allowance. At most 1200 moves across the four agents (300 per agent).
- **Python 3.8** is the version the course recommends. Every tournament game is a fresh process, so
  **nothing can be learned between games**: all learning is offline (`tools/aprender.py`).
- **Map:** red half on the left (`x < width // 2`), blue on the right. Red agents have even indices.
- **Scoring:** only **food deposited** on our own side counts. Eating an opponent gives **no points**
  (`KILL_POINTS = 0`), but it makes them drop the food they carried and sends them back to their spawn.
- **Capsules:** when one is eaten, **both** agents of the opposing team become scared for 40 moves (they
  cannot eat pacmans and can be eaten).
- **Partial observability:** an opponent is only visible if it is within Manhattan distance ≤ 5 of one of our
  two agents. Otherwise `get_agent_position(i)` returns `None`, but `is_pacman`, `num_carrying`,
  `scared_timer` and `num_returned` **are still readable** (extra information from the teaching staff).
  There is also noisy sonar: `get_agent_distances()` with uniform integer noise in [−6, +6].
- **Collision:** `check_death` runs after every individual move and fires when two opposing agents are on
  the same cell (distance <= 0.7). Who eats whom depends only on roles and `scared_timer`, not on who moved:
  a non-scared ghost kills the pacman; if the ghost is scared, the pacman sends it back to its start.
  Whoever dies respawns with `scared_timer = 0`. In a one-cell-wide corridor two opposing agents cannot
  swap places.
- ⚠️ **Positions of hidden opponents produced by our `EnemyTracker` are inferences, not facts.** Only
  `get_agent_position(i) is not None` is an observation.

---

## 3. Getting started

```bash
git clone --recurse-submodules https://github.com/joseangel2000/pacman_game.git
cd pacman_game
# (if you forgot --recurse-submodules)  git submodule update --init --remote

python3.8 -m venv venv              # use 3.8 if you have it; newer versions also work
source venv/bin/activate            # on Windows: venv\Scripts\activate

cd pacman-contest
pip install -r requirements.txt
pip install -e .
cd ..
```

To watch games with graphics you need tkinter (`sudo apt install python3-tk` on Debian/Ubuntu).

A test game (run from `pacman-contest/src/contest/`):

```bash
cd pacman-contest/src/contest
python capture.py -r ../../../my_team.py -b baseline_team                 # with graphics, us as red
python capture.py -r ../../../my_team.py -b baseline_team -l RANDOM7 -Q   # no graphics, random map 7
python capture.py -r ../../../my_team.py -b baseline_team --record --record-log   # record the game
python capture.py --replay=path/to/the/game.replay                                 # replay it
```

Check that the tooling works (from the repo **root**, venv active):

```bash
python tools/bench.py my_team.py baseline_team 5      # 15 maps, red and blue: should win almost everything
```

---

## 4. Repository layout

```
my_team.py                 ← THE AGENT (the only thing that gets submitted)
TEAM.md                    ← team details required by the course (fill in)
README.md                  ← this file
requirements.txt           ← template dependencies
pacman-contest/            ← git submodule with the instructors' framework (do NOT edit)
opponents/                 ← practice opponents written by us
    rival_espejo.py        a copy of our v1 ("mirror")
    rival_muro.py          two defenders splitting the border ("wall"; tests whether we can break a closed defence)
    rival_asalto.py        two attackers at once, one greedy (returns at 10) and one cautious (at 4) ("assault")
    rival_capsula.py       its attacker goes for the capsule first, then eats fearlessly while we are scared; has a defender
    rival_codicioso.py     two attackers that hoard 14 and 12 food before returning ("greedy")
tools/
    run_one.py             plays ONE game and writes a JSON summary + real-state metrics
    bench.py               my_team vs one opponent over several maps (red and blue)
    liga.py                my_team vs baseline + every opponent in opponents/ and rivales_ext/
    defensa_bench.py       fixed league with the defensive metrics (the main tool)
    aprender.py            automatic PARAMS tuning (coordinate descent)
    descargar_rivales.py   downloads previous-edition teams into rivales_ext/
    diag_capsulas.py       capsule-loss diagnosis (instrumentation only; does not change any game)
    diag_defensa.py        "wait or hunt" diagnosis: what our defender does while there is an invader (same idea)
    diag_ataque.py         attack diagnosis: every raid of ours, how it ends and why we die (same idea)
    empaquetar.py          builds an obfuscated copy of my_team.py to share privately
scripts/                   ← scripts from the course template
```

Folders that are **not** committed (they are in `.gitignore`): `venv/`, `__pycache__/`, `rivales_ext/`
(other teams' code), `compartir/` (output of `empaquetar.py`), `tools/aprendizaje_log.json`.

---

## 5. How the agent works

`my_team.py` has three parts. A single agent type (`SmartAgent`) knows how to attack, raid and defend;
**the team brain assigns its role every turn**.

### 5.1 `EnemyTracker` — where the hidden opponents are

An exact discrete Bayesian filter per opponent over all free cells. Every turn it updates with:

- **Sonar** (distance with uniform noise in [−6, +6]).
- **`is_pacman`**: a pacman is on our side; a ghost is on its own side.
- **"I can't see it within 5"**: rules out the cells near our agents.
- **Disappearing food**: if one of our pellets is gone, the opponent was just there.
- **Deaths**: if an opponent loses its food without `num_returned` going up, we ate it and it respawns at
  its start position.

`most_likely(enemy)` returns the most probable cell. It is an **estimate**, never a fact.

### 5.2 `TeamBrain` — roles per turn

| Role | What it does |
|---|---|
| `attack` | Main attacker: eats and returns once it carries `return_threshold` food. |
| `raid` | Short raid by the defender when the opponent has not attacked for a while; returns at `raid_threshold`. |
| `return` | Go home now and deposit what we carry. |
| `defend` | Protect our side. |

Main rules (see `decide_role`): if we are winning near the end (`endgame_defend`), we defend; if an invader
carries `help_carry` or more, the attacker helps defend; if the defender has been scared for more than
`scared_switch` turns, it attacks (a scared ghost cannot eat anyone); if the opponent has not invaded for
`passive_turns`, the defender goes out to attack. `aggressiveness()` is the fraction of the last 200 turns
in which the opponent had an invader (an opponent profile).

### 5.3 `SmartAgent` — `attack()` and `defend()`

**Attack** (`attack`): BFS to the nearest food while avoiding ghosts (seen or estimated) and dead ends when
we carry food; it heads home when it passes the threshold, when few moves remain, or when a ghost gets
close; **stuck detection** (`stuck_turns`): after a long time without eating or depositing, it commits to a
pellet far from the ghosts.

**Safe dead ends** (`pocket_safe=1`, v4.3). For a pellet `f` inside a dead end with mouth `m` (precomputed),
`f` is only a target if `d(me, f) + d(f, m) < d(ghost, m)` for **every** threatening ghost: the ones we see (not
scared) plus, for the hidden ones, the tracker's most likely cell (an *inference*). In a one-cell corridor we cannot
get past a ghost, so if it reaches the mouth first we die. If no pellet is safe, all of them count as in v4.2; if
there are safe pellets but no path reaches them while avoiding the ghosts, it goes for any pellet or capsule as in
v4.2 rather than standing still.

**Defence v4.2** (`defend`), in this order:

1. If we are a Pacman, go home.
2. Pick a target invader (a seen one, or the most likely one according to the tracker) and split
   man-to-man if there are two.
3. If we are scared: do not approach (flee if the invader is within 2, otherwise shadow at distance 2).
4. **Seal and squeeze** (`seal=2`, v4.2; `seal_action`). The *margin* of a cell `n` is the minimum, over all our
   border gates `g`, of `d(invader, g) − d(us, g)`, where "us" is the better of `n` and our teammate if it also
   defends. Margin ≥ 0 means it cannot leave through **any** gate: if we arrive at the same time we eat it before
   it crosses (deaths are checked after every move and a non-scared ghost always wins). Our capsules are
   sealed too, but there we must arrive **strictly** first (the pacman eats the capsule before the collision is
   checked). Among our moves with margin ≥ 0 we prefer margin ≥ 1, then the one that gets closest to the
   invader. If the capsules cannot be sealed, we only squeeze (exits only) when it is farther than
   `capsule_radius` from all of them. If no move seals, we fall through to step 5.
5. **Interception** (`intercept=1`): if the invader carries ≥ `intercept_min_carry` food, instead of chasing
   from behind we compute its exit (the border gate nearest to it) and pick a cell on its shortest route that
   **we reach before it does** (`route_cell`); with two defenders, the closer one chases and the other
   intercepts. Within `chase_dist` of a visible invader: direct chase. If there is no such cell
   (`intercept_fallback=1`, v4.1), we go to the border gate nearest to the invader instead of chasing it.
6. **Dead ends** (`pocket_trap=1`): if the invader is in a dead end, its "exit" is the mouth of that dead end
   (computed once in `precompute_defense`).
7. BFS chase restricted to our side.
8. No invaders: patrol the border near where we estimate the opponent to be.

**Leash** (`leash_mode=1`, only against opponents that invade ≥ `leash_aggr` of the time): during a defender
raid, a pellet `f` is only taken if `dist(me, f) + dist(f, border) ≤ ETA_rival + leash_margin`, where
`ETA_rival` is the 0.15-quantile of the tracker's belief about when an opponent could reach our border
(`rival_eta`). This keeps the defender from arriving late to the next invasion.

### 5.4 `PARAMS`

Every number that controls behaviour is in the block between `# --- PARAMS START ---` and
`# --- PARAMS END ---` in `my_team.py` (each one has a comment, in Spanish). `tools/aprender.py` rewrites
that block. To try a variant without editing the file:

```bash
PACMAN_PARAMS='{"leash_mode": 0, "intercept": 0}' python capture.py ...   # local training only
```

The tournament does not set `PACMAN_PARAMS`, so the values in the file are used.

Summary by group (current values):

| Group | Parameters (value) |
|---|---|
| Attack | `return_threshold` 6, `ghost_alert` 3, `danger_radius` 1, `avoid_pockets` 1, `pocket_min_carry` 1, `stuck_turns` 40, **`pocket_safe` 1** |
| Attack **off** | `pocket_safe` 2 and 3 (with `roam_depth`), `stuck_mode` |
| Roles | `raid_threshold` 3, `passive_turns` 10, `scared_switch` 6, `help_carry` 20, `endgame_defend` 40 |
| Defence **on** | `seal` 2, `intercept` 1, `intercept_min_carry` 3, `intercept_fallback` 1, `pocket_trap` 1, `leash_mode` 1, `leash_margin` 4, `leash_aggr` 0.1, `chase_dist` 2 |
| Defence **off** | `seal_press`, `seal_patience`, `capsule_guard` (1 and 2), `capsule_contain`, `patrol_mode`, `gates`, `zone_split`, `pocket_kill`, `intercept_pick`/`slack`, `leash_mode` 2, `cut_exit`, `double_defense`, `stuck_defend` |

---

## 6. Measurement and learning tools

Run everything from the repo **root** with the venv active. The tools play games in parallel on all cores
and use **the same seeds** for every configuration, so two runs can be compared game by game.

### `tools/defensa_bench.py` — the main tool

```bash
python tools/defensa_bench.py                                   # default league with your current my_team.py
python tools/defensa_bench.py --params '{"leash_mode": 0}' --salida a.json
python tools/defensa_bench.py --fijos 0 --mapas 12 --desde 101  # NEW maps only (validation)
python tools/defensa_bench.py --rivales rival_capsula lorecleme__pacman-agent
python tools/defensa_bench.py --comparar a.json b.json          # compare two runs
```

Options: `--team`, `--params`, `--rivales`, `--mapas N` (extra RANDOM maps), `--fijos N` (how many of the 10
fixed maps), `--desde N` (first RANDOM map), `--salida` (output JSON), `--comparar`, `--workers`. The default
league is 11 opponents (baseline, the 5 in `opponents/`, and 5 previous-edition teams) on 10 fixed + 4 RANDOM
maps, red and blue = 308 games per configuration (~3.5 min on 2 cores). Opponents missing from
`rivales_ext/` are skipped with a warning.

The tool prints Spanish column names. All of them are computed from the **real game state** at every move,
not estimated:

| Column | Meaning |
|---|---|
| `V-E-D`, `pts` | wins-draws-losses and tournament points per game (3/1/0) |
| `marg` | mean score difference (ours − theirs) |
| `ellos dep.` | food the **opponent deposits** per game (what we concede) |
| `inv.comidos` | opponent pacmans eaten by our ghosts, per game |
| `muertes` | our pacmans eaten, per game |
| `turnos/inv` | mean turns an opponent invader spends on our side per incursion |
| `cáps.perd`, `asust.` | our capsules eaten by the opponent, and turns our ghosts spend scared |
| `carga/com` | mean food carried by the opponent invaders we eat (`n/d` in JSON files made before this column) |

> How it is measured: `run_one.py` hooks `CaptureRules.process`, which the game calls **once per real
> move**. `check_death`/`generate_successor` cannot be used for this, because the agents also call them
> when simulating.

### `tools/diag_capsulas.py` — why we lose capsules

```bash
python tools/diag_capsulas.py --rivales tian__greedy_v4 --mapas 40 --salida diag.json \
    --verificar mediciones/v4_greedy.json      # checks the scores are identical to a defensa_bench run
python tools/diag_capsulas.py --resumen diag.json
```

Plays the same games as `defensa_bench.py` (same seeds) and, for every capsule we lose, records the real state
(who ate it, how far each of our agents was, roles, whether `capsule_guard` fired or would have fired, tracker
error). It only *records*: it wraps `SmartAgent` methods without changing their result, uses no random numbers,
and does the expensive counterfactual after the game. `--verificar` confirmed 100/100 identical scores.

### `tools/diag_defensa.py` — wait or hunt?

```bash
python tools/diag_defensa.py --rivales tian__greedy_v4 --mapas 40 --salida d.json --verificar mediciones/base_greedy.json
python tools/diag_defensa.py --resumen d.json --por-rival
```

Same approach as `diag_capsulas.py` (records only; `--verificar` gave 100/100 and 308/308 identical scores). For
every turn of our defender with a real invader on our side: which branch decided (intercept on route / go to gate /
chase / scared), whether it stood still or got closer, and whether the invader was in a dead end, visible or loaded.
For every invasion: how it ended (deposited / eaten / went back empty / end of game), how long it lasted, how much
it carried and, if it deposited, how far our nearest ghost was from the cell it crossed from.

### `tools/diag_ataque.py` — why we deposit little and why we die

```bash
python tools/diag_ataque.py --rivales tian__greedy_v4 --mapas 40 --salida a.json --verificar mediciones/v43_greedy.json
python tools/diag_ataque.py --resumen a.json --por-rival
```

Same approach (records only; it wraps `choose_action` to log the role of every turn). For every raid of ours
(ghost → pacman → back): who (attacker or defender), how it ends (deposits / dies / comes back empty / end of game),
duration and max carry; if it dies, the food lost, whether it was in a dead end, how far from home, how many ghosts
within 3, and for how many moves the killer had been visible. Per game: how the attacker spends its turns (on their
side / at home / **stuck at the border without crossing**), food deposited by each agent and while their ghosts were
scared. `--verificar` gave 99/100 identical scores under full CPU load (the opponent is time-dependent; re-run
unloaded, it reproduces).

### The rest

- **`run_one.py`**: one game → a `RESULT {json}` line with `score` (from red's point of view),
  `red_returned`, `blue_returned`, `agent_crashed`, `secs` and `metrics`.
- **`bench.py`**: `python tools/bench.py [my_team.py] [rival|path.py] [n_random]`.
- **`liga.py`**: `python tools/liga.py [n_random]` — against every opponent in `opponents/` and `rivales_ext/`.
- **`descargar_rivales.py`**: downloads the previous-edition teams (the list the instructor shared) into
  `rivales_ext/<user>__<repo>/`. It is other people's code: **do not commit it**. Some are old-style
  (`from capture_agents import ...`); `run_one.py` already adds `src/contest` to `sys.path` to support them.
- **`aprender.py`**: coordinate-descent search over `PARAMS`. Each candidate plays exactly the same games; at
  the end the winner is validated on new maps and only written into `my_team.py` if it also wins there.
  Options: `--rapido` (quick), `--pasadas N` (passes), `--solo p1 p2` (only those parameters),
  `--externos team1 team2` (add teams from `rivales_ext/`), `--random N`, `--no-escribir` (do not write),
  `--workers`. A full league takes **hours**; use `--solo` and `--rapido` to experiment.
  ⚠️ Start with `--no-escribir` if you do not want it to rewrite the `PARAMS` block.
- **`empaquetar.py`**: to hand `my_team.py` to a classmate privately without exposing the strategy
  (`--un-archivo --python /path/to/python3.8`). **Bytecode is not encryption**; it only makes the file
  harder to read.

---

## 7. How we work: measure before you believe

Rules we follow (worth keeping):

1. **Every change is tied to something checkable**: a point of our defensive playbook or a fact verified
   in `capture.py`. No "I think that...".
2. **Every claim carries a label**: *verified in the code*, *measured*, or *hypothesis*.
3. **Same games before and after** (same seeds) and **validation on new maps** that were not used to decide
   (`--fijos 0 --desde 101`).
4. **Every change goes in switched off** (parameter at 0) and is only switched on if it proves itself.
5. **Noise rules**: with ~300 games the uncertainty is about ±0.07 points per game. Smaller differences mean
   nothing. That is why we compare game by game (paired) and repeat on new maps.
6. **Do not optimise against a single opponent**: look at the TOTAL and at the per-opponent breakdown.
7. **Look at several metrics**: points, margin, food we concede, invaders eaten and our own deaths. An
   improvement in one can hide a regression in another (see `intercept` in section 8).

### Defensive playbook and the status of each point

| # | Playbook point | Status |
|---|---|---|
| 1 | Interception on the escape route (a cell I reach before the invader) | **Implemented and on**, both halves. The "if I can't get there first, go to the border cell nearest to it" half (`intercept_fallback`) is on since v4.1: +0.17 pts vs `greedy_v4`. v4.2 extends "close its exit" to **all** its exits plus our capsules (`seal=2`, our own design inspired by dominance regions in pursuit-evasion): +0.15 league, +0.23 `greedy_v4`. |
| 2 | Base position at border gates weighted by food/capsules | Implemented (`gates`), **worse** (2.11 vs 2.20). Off. |
| 3 | Protect our capsule | **Diagnosed** (section 8.2). `capsule_guard=1` can only act when we are already closer to the capsule than the invader; the playbook's version (`capsule_guard=2`) and a containment variant (`capsule_contain`) were measured: fewer capsules lost does **not** turn into points. Off. |
| 4 | Act on the tracker's estimates | v3 already did it (chases `most_likely`). |
| 5 | Transition discipline / leash | **Implemented and on** (`leash_mode=1`). |
| 6 | Dead-end trap | `pocket_trap` on. `pocket_kill` (going in after it) works but does not improve points: off. |
| 7 | Man-to-man vs zone | Man-to-man already in v3; `zone_split` did not help. "Don't bite the fake" (`patrol_mode=1`) measured: no gain, −0.64 vs `rival_capsula`. Off. |

---

## 8. Measured results and what was discarded

11-opponent league, 308 games per row (training maps), tournament points per game:

| Configuration | pts | margin | opponent deposits | invaders eaten | turns/invasion |
|---|---|---|---|---|---|
| v3 (v4 switched off) | 2.20 | +7.8 | 12.6 | 1.55 | 14.2 |
| `intercept` only | 2.15 | +8.8 | 11.3 | 1.16 | 18.9 |
| `capsule_guard` | 2.19 | +7.7 | 12.6 | 1.55 | 15.0 |
| `gates` | 2.11 | +7.2 | 12.7 | 1.50 | 8.0 |
| `leash_mode=1` only | 2.22 | +7.2 | 9.3 | 0.93 | 11.8 |
| `intercept` + `pocket_trap` | 2.24 | +9.1 | 11.0 | 1.22 | 18.5 |
| **v4 final** | **2.32** | **+9.0** | **10.4** | 1.43 | 15.1 |

New maps (RANDOM101-112, 264 games): v3 **1.95** (163-26-75) → v4 **2.29** (194-22-48). The biggest gains are
against `rival_codicioso` (1.00 → 2.00), `rival_asalto` (1.62 → 2.38) and flagrats (1.88 → 2.62).
`rival_capsula` remains the worst (0.71).

**`greedy_v4`** (a classmate's agent, **not included in this repo**), 500 games (10 fixed + 240 RANDOM, red and
blue, same seeds). Our replication of his evaluation matches his own (v3: 124-31-345, 0.81 pts, versus the
0.78 he measured):

| | v3 | v4 |
|---|---|---|
| W-D-L | 124-31-345 | 146-59-295 |
| pts/game | 0.81 | 0.99 |
| margin | −4.6 | −2.5 |
| we deposit / he deposits | 14.0 / 18.5 | 11.8 / 14.3 |
| invaders eaten | 0.38 | 0.16 |
| our deaths | 1.15 | 0.92 |
| turns/invasion | 36.8 | 44.2 |
| our capsules lost | 1.55 | 1.28 |

On the same 500 games: **+0.19 ± 0.07** pts/game (z ≈ 2.5), margin +2.0 ± 0.4.

### 8.1 v4.1 (2026-11-15): playbook variants, paired against v4

Same games and seeds; difference B − A ± 1 paired standard error. League = 308 games, `greedy_v4` = 500.

| Variant | League pts | `greedy_v4` pts | `greedy_v4`: he deposits | capsules lost (`greedy_v4`) | Decision |
|---|---|---|---|---|---|
| `intercept_fallback=1` (point 1) | +0.02 ± 0.04 | **+0.17 ± 0.05** | **−1.10 ± 0.29** | −0.06 ± 0.02 | **On** |
| ...validation, new maps | +0.01 ± 0.04 (264) | +0.11 ± 0.08 (200, RANDOM301-400) | −0.75 ± 0.41 | −0.04 ± 0.03 | |
| `capsule_guard=2` (point 3) | −0.07 ± 0.05 | −0.02 ± 0.06 | −0.20 ± 0.38 | −0.05 ± 0.04 | Off |
| `patrol_mode=1` (point 7) | −0.04 ± 0.06 | +0.00 ± 0.05 | +0.05 ± 0.23 | −0.01 ± 0.02 | Off |
| `capsule_contain=1` (vs v4.1) | −0.06 ± 0.05 | −0.07 ± 0.07 | +0.31 ± 0.40 | **−0.14 ± 0.03** | Off |

Worst measured time per action with v4.1: 30 ms.

### 8.3 v4.2 (2026-11-15): seal and squeeze, paired against v4.1

**Why** (`tools/diag_defensa.py`, 100 games vs `greedy_v4` with v4.1): with an invader on our side our defender stood
still **35 %** of the turns (95 % of them on a gate, 99 % with the invader carrying ≥ 3): it closes *one* exit and
waits. Only **6 %** of `greedy_v4`'s invasions ended with us eating it; 47 % ended with a deposit (8.0 food, 59 turns
on average), and 65 % of the food it deposited came from invasions in which it also ate our capsule. In 46 % of the
deposits a non-scared ghost of ours was within 3 of the cell it crossed from: it left through a neighbouring gate.

**Opponents used.** Besides `greedy_v4`: the 8 league opponents that still beat us sometimes (`rival_espejo`,
`rival_asalto`, `rival_capsula`, `rival_codicioso`, lorecleme, Supergodgg, flagrats, DotGobblers) and 4 of the 12
extra previous-edition teams in `rivales_ext/` that scored < 2.6 pts against v4.1 in a 28-game screen (rcrtss 2.39,
Scooooooott 2.43, despookjes 2.50, dea2001 2.57). The other 8 extra teams scored 2.61-3.00 and were not used.

Difference B − A ± 1 paired standard error:

| Variant | 12 competitive opponents (336) | `greedy_v4` (500) | Decision |
|---|---|---|---|
| `seal=1` (exits only) | +0.02 ± 0.06 | +0.04 ± 0.07 (invaders eaten 0.17 → 0.44, but capsules lost +0.09) | Off |
| `seal=1` + `capsule_contain=1` | +0.07 ± 0.06 | +0.07 ± 0.08 | Off |
| **`seal=2`** (exits + capsules) | **+0.12 ± 0.06** (they deposit −2.60) | **+0.23 ± 0.07** (he deposits −2.62, capsules −0.17) | **On** |

Validation of `seal=2` on data not used to decide:

| Set | pts | they deposit | we deposit |
|---|---|---|---|
| Full league, training maps (308) | **+0.15 ± 0.06** | −2.74 ± 0.49 | −0.80 ± 0.37 |
| League, new maps RANDOM101-112 (264) | +0.05 ± 0.06 | −0.15 ± 0.42 | +0.02 ± 0.25 |
| `greedy_v4`, new maps RANDOM301-400 (200) | +0.21 ± 0.11 | −2.44 ± 0.65 | −0.81 ± 0.37 |
| 4 extra teams, new maps (96) | −0.01 ± 0.03 | −0.39 ± 0.34 | −0.66 ± 0.49 |
| Weak league teams: baseline, sta05, `rival_muro` (84) | +0.07 ± 0.05 | | |

**Known weakness: a stand-off against lorecleme** on some maps (−0.36 on training maps, but −0.04 on new maps).
In `crowdedCapture` its invader parks hidden with 9 food in a spot where the only cell that seals both of its
routes is ours: we keep it sealed (it never deposits those 9), but we cannot squeeze without opening an exit, so
there is always "an invasion", our defender never raids, and our lone attacker is blocked by their defender.
`seal_press` (squeeze first) and `seal_patience` (give up sealing after N turns without getting closer) did not fix
that game; neither has been measured on the full battery. Both are off.

**Cost:** we deposit a bit less (−0.5 to −0.8 per game): the defender spends more time defending and raids less.

### 8.4 v4.3 (2026-11-16): phase 2, attack, paired against v4.2

**Exit criterion agreed before starting** (v4.3 against v4.2, same games): `greedy_v4` ≥ +0.15 pts; we deposit
≥ +1.5 more against `greedy_v4`; our pacmans eaten −0.2 per game; league and new maps not down more than 0.07.

**Why** (`tools/diag_ataque.py` with v4.2, 100 games vs `greedy_v4` and the 12 competitive opponents): **82-92 % of our
attacker's deaths happen inside a dead end**, and in 95-97 % of them the ghost that kills it had been visible for 3 or
more of our own turns: we see it coming and walk in anyway. The attacker also spends 21-24 % of its turns at the border
without crossing. Against `greedy_v4` the attacker deposits 9.6 per game and the defender 2.4; 5.4 of those 12 are
deposited while his ghosts are scared.

The plan had three parts: **A** safe dead ends, **B** a border stall-breaker, **C** re-tune `PARAMS` with
`aprender.py`. Difference B − A ± 1 paired standard error, against v4.2:

| Variant | `greedy_v4` (500) | 12 competitive (336) | Weak: baseline, sta05, `rival_muro` (84) | Decision |
|---|---|---|---|---|
| **A: `pocket_safe=1`** (seen + estimated ghosts) | **+0.21 ± 0.06** | +0.06 ± 0.05 | −0.11 ± 0.05 | **On** |
| A: `pocket_safe=2` (seen ghosts only) | +0.19 ± 0.06 | +0.03 ± 0.05 | −0.08 ± 0.05 | Off |
| A: `pocket_safe=3` (only ghosts seen ≥ `roam_depth` deep in their half) | +0.15 ± 0.05 | +0.00 ± 0.04 | −0.06 ± 0.04 | Off |
| B: `stuck_mode=1` (stuck: my distance goes *around* the danger zone) | +0.03 ± 0.03 | −0.01 ± 0.04 | +0.02 ± 0.02 | Off |

`pocket_safe=1` in detail, and its validation on data not used to decide:

| Set | pts | we deposit | they deposit | our pacmans eaten |
|---|---|---|---|---|
| `greedy_v4` (500) | **+0.21 ± 0.06** | +0.69 ± 0.28 | −0.64 ± 0.34 | **−0.43 ± 0.04** (0.82 → 0.39) |
| 12 competitive (336) | +0.06 ± 0.05 | +0.65 ± 0.32 | −0.28 ± 0.22 | −0.27 ± 0.04 |
| Full league, training maps (308) | −0.02 ± 0.04 | +0.20 ± 0.33 | −0.09 ± 0.22 | −0.31 ± 0.05 |
| League, **new** maps RANDOM101-112 (264) | −0.03 ± 0.06 | +0.74 ± 0.37 | +0.53 ± 0.28 | −0.23 ± 0.05 |
| `greedy_v4`, **new** maps RANDOM301-400 (200) | +0.04 ± 0.11 | +0.95 ± 0.42 | +0.10 ± 0.48 | −0.37 ± 0.06 |
| 4 extra teams, new maps (96) | +0.21 ± 0.10 | +2.80 ± 0.69 | +0.34 ± 0.58 | −0.43 ± 0.10 |

**C: re-tuning** (`aprender.py --no-escribir --pasadas 1 --random 4`, 9 attack/role parameters, 25 candidates of 420
games each against baseline, the 5 opponents in `opponents/`, `greedy_v4` and the 8 competitive previous-edition
teams). Only `return_threshold`
6 → 8 passed the training margin (+0.04 pts); on the validation maps RANDOM101-115 (450 games) it gave **+0.00**, and
paired with our protocol `greedy_v4` −0.03 ± 0.06, competitive −0.01. Discarded. Clearly worse in training (single
run, not paired): `return_threshold` 3 or 4, `danger_radius` 2, `stuck_turns` 15 or 25 (−0.08 to −0.16).

**Exit criterion: 3 of 4 met.**

| Criterion | Target | v4.3 vs v4.2 | |
|---|---|---|---|
| Points against `greedy_v4` | ≥ +0.15 (≥ 1.54) | +0.21 (1.60) | ✔ |
| Food we deposit against `greedy_v4` | ≥ +1.5 | +0.69 | ✘ |
| Our pacmans eaten per game | ≤ −0.2 | −0.43 | ✔ |
| League and new maps | ≥ −0.07 | league −0.02, new maps −0.03, `greedy_v4` new maps +0.04 | ✔ |

**What changed and what did not** (measured): `pocket_safe=1` halves our deaths, which is where the points come
from: we lose much less food on the way. It does **not** make us deposit much more, and the time stuck at the border
did not go down (24 % → 26 % of the attacker's turns, `diag_ataque.py` with `pocket_safe=1` before the last fallback
was added, 100 games vs `greedy_v4`).

**Known weakness: defenders that wall the border.** Against `rival_muro` (two defenders splitting the border) and
sta05, the attacker refuses most dead-end food while their ghosts stand nearby (on RANDOM4, 20 of the 30 pellets
are in dead ends): weak teams −0.11 (`rival_muro` −0.14, sta05 −0.18). `pocket_safe=3` was designed for this (a
ghost that never comes deep into its own half does not count) and recovers that game, but is weaker against
`greedy_v4` (+0.15 vs +0.21). Kept off.

### 8.2 Capsules: diagnosis (`tools/diag_capsulas.py`, 100 games vs `greedy_v4`)

- **Why `capsule_guard=1` did nothing** (verified + measured). If `route_cell` finds a cell `c` on the invader's
  path to the capsule, then `d(me, cap) <= d(me, c) + d(c, cap) <= d(him, c) + d(c, cap) = d(him, cap)`: the guard
  can only act when we are **already** closer to the capsule than him. When he enters the capsule radius we are
  closer in only 3-5 % of the losses, so in ~96 % the guard returned `None`.
- **Standing on the capsule does not protect it** (verified): in `apply_action` the pacman eats the capsule
  (`consume`) before `check_death`, so we become scared and it is him who eats us.
- In 45-63 % of the losses one of our non-scared ghosts was within 3 just before (he uses the capsule to escape);
  he hovers ~15 own turns within the radius; tracker error on the hidden eater is only 1.2-1.4 cells; the eater never
  dies before getting home.
- `capsule_contain=1` (do not press him when he wins the race to the capsule; go round to the capsule side)
  works as designed: ghost-within-3 drops from 45 % to 21 % and capsules lost from 1.22 to 1.08 per game, scared
  turns −5. **But points do not move** (league −0.06, `greedy_v4` −0.07, both within noise): the capsule loss
  correlates with losing, but protecting it costs at least as much as it saves.

### What we learned (data, not opinions)

- **v4 closes the exit but then waits.** Against lorecleme the defender goes from standing still 1 % of the
  turns with an invader present (v3) to **39 %** (v4). The invader stays longer on our side and piles up more
  food (63 % of turns with ≥ 3 carried, versus 41 %): it deposits less, but we eat fewer invaders.
- **With the invader in a dead end, v4 stood still 66 % of the turns** at the mouth without going in.
  `pocket_kill` fixes that (0 %) and raises invaders eaten (0.92 → 1.08 on new maps), but **does not move
  the points**.
- **Losing the capsule correlates with losing points** (active opponents: 2.07 pts with ≥ 1 capsule lost
  versus 2.31 without; the opponent deposits 15.0 versus 11.0). That is a correlation, not a demonstrated
  cause, and it does not hold against lorecleme, DotGobblers or sta05.
- **Whoever eats the capsule does not make a direct dash for it**: it has spent 18-45 turns on our side and
  carries ~2.5 food. In 30-37 % of cases our ghost was within 3 cells and it was not enough (once it is
  eaten we are scared and cannot catch the invader).

### Discarded or no effect (switched off, but the code is there)

`gates`, `zone_split`, `capsule_guard` (1 and 2), `capsule_contain`, `patrol_mode=1`, `seal=1`, `pocket_kill`, `intercept_pick=1`, `intercept_slack=1`,
`chase_dist=4`, `leash_mode=2`, `cut_exit`, `double_defense`, `stuck_defend`, `raid_max_aggr`; attack (phase 2):
`pocket_safe` 2 and 3, `stuck_mode=1`, `return_threshold=8`.

---

## 9. Next steps (ordered by expected payoff)

1. **Capsules: diagnosed and tried (section 8.2).** Reducing capsule losses did not turn into points. Do not
   retry without a new reason.
2. **Deposit more** (the criterion phase 2 did not meet): against `greedy_v4` (v4.3) we deposit 12.0 versus his
   10.0 and only get eaten 0.39 times per game, so dying is no longer the problem. The attacker still spends about a
   quarter of its turns at the border without crossing. Start by running `tools/diag_ataque.py` on v4.3 to see where
   those turns go. Neither a smarter stuck target (`stuck_mode=1`) nor re-tuned thresholds (C) helped.
3. **Walls at the border** (section 8.4): `pocket_safe=1` is too cautious against defenders that stay near their
   border (`rival_muro`, sta05).
4. **Done:** the omitted half of playbook point 1 (`intercept_fallback`, v4.1), waiting vs hunting (`seal=2`, v4.2),
   safe dead ends (`pocket_safe=1`, v4.3) and re-learning the attack `PARAMS` with `greedy_v4` in the league (no change).
5. **Stand-off against parked invaders** (section 8.3, lorecleme): e.g. call the attacker back to squeeze with two,
   or give up the seal; measure `seal_patience` on the full battery first.
6. Richer coordination between the two agents (today: dynamic roles and man-to-man assignment).

---

## 10. Before submitting (checklist)

- [ ] `my_team.py` is in the repo **root** and `create_team(first_index, second_index, is_red, **kwargs)` works.
- [ ] It compiles on **Python 3.8** (`python3.8 -c "import ast;ast.parse(open('my_team.py').read())"` or,
      better, play full games with a real 3.8).
- [ ] No debug `print`s and no disk writes.
- [ ] `python tools/defensa_bench.py` runs with no errors, no crashes and no time warnings.
- [ ] Worst per-action time well below 1 s (v4: ~57 ms; v4.2: 36 ms; v4.3: 38 ms in 6 timed games) and start-up well
      below 15 s.
- [ ] `PACMAN_PARAMS` is for training only: it does not exist in the tournament.
- [ ] `TEAM.md` filled in.
- [ ] No other teams' code in the repo (`rivales_ext/` is ignored).

---

## 11. Working as a pair with git

- `main` must always work (`my_team.py` playable). Every new change goes on a **branch**
  (`git switch -c name`) and is merged into `main` once it has been measured (section 7).
- One change = one commit, with a message saying **what** and **with what result** (e.g. *"leash_mode=1:
  2.22 pts, opponent deposits 9.3 (was 12.6)"*).
- Tell each other before editing `PARAMS` by hand: `aprender.py` rewrites that block and can cause conflicts.
- If you both change the same block of `my_team.py`, resolve the conflict **and run the league again**: a
  merge that compiles can still play worse.
- Do not commit `venv/`, `rivales_ext/` or `compartir/` (already in `.gitignore`).

---

## 12. Known pitfalls

- `ModuleNotFoundError: No module named 'contest'` → `pip install -e .` is missing inside `pacman-contest/`
  with the venv active, or you are running from the wrong directory.
- `No module named 'tkinter'` → `sudo apt install python3-tk`.
- Old-style teams with `from capture_agents import ...` or `import util` → `tools/run_one.py` already adds
  `src/contest` to `sys.path`; if you run them with `capture.py` directly, do it from `src/contest`.
- `Actions.get_legal_neighbors` **includes the cell itself** (equivalent to STOP). When computing neighbours
  to detect dead ends you must exclude it (a bug already fixed in `compute_pockets`).
- A `.pyc` only works with the same Python version it was compiled with (*bad magic number* error).
  `empaquetar.py --un-archivo` warns if the version does not match.
- `game_state.data.timeleft` counts the moves of **all four** agents: divide by 4 to get the number of own
  turns left.
- Other teams' code can crash or be slow: the `crashes` that the bench reports for flagrats are the
  opponent's, not ours.

---

## References

- `pacman-contest/src/contest/CONTEST.md` and `capture.py` (the source of truth for the rules).
- The course's *Programming Project* PDF and the instructor's email about the hidden opponent state
  (`configuration = None`, but `is_pacman`, `num_carrying`, `scared_timer` and `num_returned` remain visible).
- `pacman-contest/src/contest/baseline_team.py`: the reference reflex agents.
