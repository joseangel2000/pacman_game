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

- **Version: v4.** It is v3 (attack with stuck detection, Bayesian tracking of hidden opponents, dynamic
  roles) plus a new defence (interception on the invader's escape route, a "leash" on defender raids,
  dead-end handling). With `intercept`, `pocket_trap` and `leash_mode` set to 0, v3 is recovered exactly.
- Everything switched on in `PARAMS` has been **measured** (section 8). Anything that did not help is
  implemented but **switched off**.
- Time per action in the worst case measured: **~57 ms** (the limit is 1 s). Start-up: ~0.7 s (limit 15 s).
- Compatible with **Python 3.8** (verified by playing complete games on 3.8.20).

Key results (tournament points per game: win 3, draw 1, loss 0; 308 games per cell unless noted):

| | v3 | v4 |
|---|---|---|
| Own league, training maps | 2.20 | **2.32** |
| Own league, **new** maps (not used for any decision) | 1.95 | **2.29** |
| `greedy_v4` (a classmate's agent), 500 games | 0.81 | **0.99** |
| lorecleme (previous edition) | 2.40 | 2.36 (statistical tie) |

**We still lose most games against `greedy_v4`** (v4: 146 wins, 59 draws, 295 losses). The weakest points
measured are **capsules** and **how much food we deposit ourselves** (see section 9).

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
- **Collision:** `check_death` kills when both are on the same cell; the one that *moves into* the other's
  cell is the one that eats. In a one-cell-wide corridor two agents cannot pass each other.
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

**Defence v4** (`defend`), in this order:

1. If we are a Pacman, go home.
2. Pick a target invader (a seen one, or the most likely one according to the tracker) and split
   man-to-man if there are two.
3. If we are scared: do not approach (flee if the invader is within 2, otherwise shadow at distance 2).
4. **Interception** (`intercept=1`): if the invader carries ≥ `intercept_min_carry` food, instead of chasing
   from behind we compute its exit (the border gate nearest to it) and pick a cell on its shortest route that
   **we reach before it does** (`route_cell`); with two defenders, the closer one chases and the other
   intercepts. Within `chase_dist` of a visible invader: direct chase.
5. **Dead ends** (`pocket_trap=1`): if the invader is in a dead end, its "exit" is the mouth of that dead end
   (computed once in `precompute_defense`).
6. BFS chase restricted to our side.
7. No invaders: patrol the border near where we estimate the opponent to be.

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
| Attack | `return_threshold` 6, `ghost_alert` 3, `danger_radius` 1, `avoid_pockets` 1, `pocket_min_carry` 1, `stuck_turns` 40 |
| Roles | `raid_threshold` 3, `passive_turns` 10, `scared_switch` 6, `help_carry` 20, `endgame_defend` 40 |
| Defence v4 **on** | `intercept` 1, `intercept_min_carry` 3, `pocket_trap` 1, `leash_mode` 1, `leash_margin` 4, `leash_aggr` 0.1, `chase_dist` 2 |
| Defence v4 **off** | `capsule_guard`, `gates`, `zone_split`, `pocket_kill`, `intercept_pick`/`slack`, `leash_mode` 2, `cut_exit`, `double_defense`, `stuck_defend` |

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

> How it is measured: `run_one.py` hooks `CaptureRules.process`, which the game calls **once per real
> move**. `check_death`/`generate_successor` cannot be used for this, because the agents also call them
> when simulating.

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
| 1 | Interception on the escape route (a cell I reach before the invader) | **Implemented and on.** The "if I can't get there first, go to the border cell nearest to it" half is missing: today we chase directly. **Still to test.** |
| 2 | Base position at border gates weighted by food/capsules | Implemented (`gates`), **worse** (2.11 vs 2.20). Off. |
| 3 | Protect our capsule | Implemented (`capsule_guard`), **does not reduce losses**. Off. Cause not diagnosed. |
| 4 | Act on the tracker's estimates | v3 already did it (chases `most_likely`). |
| 5 | Transition discipline / leash | **Implemented and on** (`leash_mode=1`). |
| 6 | Dead-end trap | `pocket_trap` on. `pocket_kill` (going in after it) works but does not improve points: off. |
| 7 | Man-to-man vs zone | Man-to-man already in v3; `zone_split` did not help. |

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

`gates`, `zone_split`, `capsule_guard`, `pocket_kill`, `intercept_pick=1`, `intercept_slack=1`,
`chase_dist=4`, `leash_mode=2`, `cut_exit`, `double_defense`, `stuck_defend`, `raid_max_aggr`.

---

## 9. Next steps (ordered by expected payoff)

1. **Capsules against `greedy_v4`-style opponents** (1.28 capsules lost and ~33 scared turns per game).
   First diagnose *why* `capsule_guard` does not prevent it: does it even trigger? does it arrive late? does
   the invader use the capsule to escape when we chase it? More measurement is needed before implementing
   anything.
2. **Attack**: we deposit 11.8 versus the opponent's 14.3, and we get eaten about 0.9 times per game. This
   explains a good part of the losses and it is not a defence problem.
3. **Test the omitted half of playbook point 1** (go to the border cell nearest the invader when we cannot
   intercept it), as a switched-off variant.
4. **Waiting vs hunting** (39 % of turns standing still): if `pocket_kill` is not enough, study what to do
   once the exit is closed. There is no playbook backing here: it would be our own design and should be
   labelled a hypothesis.
5. **Re-learn the `PARAMS`** with `tools/aprender.py`, adding a `greedy_v4`-style opponent to the league
   (`--externos ...`). Do it with `--no-escribir` first.
6. Richer coordination between the two agents (today: dynamic roles and man-to-man assignment).

---

## 10. Before submitting (checklist)

- [ ] `my_team.py` is in the repo **root** and `create_team(first_index, second_index, is_red, **kwargs)` works.
- [ ] It compiles on **Python 3.8** (`python3.8 -c "import ast;ast.parse(open('my_team.py').read())"` or,
      better, play full games with a real 3.8).
- [ ] No debug `print`s and no disk writes.
- [ ] `python tools/defensa_bench.py` runs with no errors, no crashes and no time warnings.
- [ ] Worst per-action time well below 1 s (currently ~57 ms) and start-up well below 15 s.
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
