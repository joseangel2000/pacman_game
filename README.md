# Pacman Capture the Flag — EUTOPIA Pacman Contest

A two-person team project for **Autonomous Systems** (EMAI 2026-27, UPF):
**@diegogreaza03** and **@joseangel2000**.

Two agents (Pacman when attacking, ghost when defending) that eat the opponent's food and protect ours,
playing on the course's `pacman-contest` platform. All the team's code lives in **`my_team.py`** (repo root).

| Date | What |
|---|---|
| Nov 23 | Test run |
| Dec 3, 23:59 | Final submission |
| Dec 4 | Final tournament |

> **Language note:** the code comments and the output of the helper scripts are written in **Spanish**.
> This README is in English.

---

## Table of contents

1. [Rules of the contest](#1-rules-of-the-contest)
2. [Getting started](#2-getting-started)
3. [Repository layout](#3-repository-layout)
4. [Known pitfalls](#4-known-pitfalls)
5. [References](#5-references)

---

## 1. Rules of the contest

From `pacman-contest/src/contest/CONTEST.md`, the course's project PDF and the framework code
(`capture.py`):

- **Submission:** a `my_team.py` in the repo root exposing `create_team(first_index, second_index, is_red, **kwargs)`
  that returns two agents inheriting from `CaptureAgent`.
- **Time:** 1 s per action; three timeout warnings, or a single action over 3 s, means forfeit.
  15 s start-up allowance (`register_initial_state`). At most 1200 moves across the four agents
  (300 per agent).
- **Python 3.8** is the version the course uses, on Ubuntu. Every tournament game is a fresh process, so
  nothing can be learned between games.
- **Map:** red half on the left (`x < width // 2`), blue on the right. Red agents have even indices.
  On its own side an agent is a ghost; once it crosses, it becomes a Pacman.
- **Scoring:** only **food deposited** back on your own side counts. Eating an opponent gives **no points**
  (`KILL_POINTS = 0`), but it makes them drop the food they were carrying and sends them back to their spawn.
- **Capsules:** when one is eaten, **both** agents of the opposing team become scared for 40 moves (they
  cannot eat pacmans and can be eaten themselves).
- **Partial observability:** an opponent's position is only visible if it is within Manhattan distance ≤ 5
  of one of your two agents; otherwise `get_agent_position(i)` returns `None`. There is also a noisy sonar
  reading for every agent, `get_agent_distances()`, with uniform integer noise in [−6, +6].
- **Collision:** `check_death` runs after every individual move and fires when two opposing agents are on
  the same cell (distance ≤ 0.7). Who eats whom depends only on the roles and on `scared_timer`, not on who
  moved: a non-scared ghost kills the pacman; if the ghost is scared, the pacman sends it back to its start.
  Whoever dies respawns with `scared_timer = 0`. In a one-cell-wide corridor two opposing agents cannot
  swap places.
- **Winning:** a game ends when one team returns all but two of the opponent's dots, or when the move limit
  is reached, in which case whoever returned more food wins. Tournament points: win 3, draw 1, loss 0.

---

## 2. Getting started

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

---

## 3. Repository layout

```
my_team.py                 ← THE AGENT (the only thing that gets submitted)
TEAM.md                    ← team details required by the course
README.md                  ← this file
requirements.txt           ← template dependencies
pacman-contest/            ← git submodule with the instructors' framework (do NOT edit)
opponents/                 ← practice opponents we wrote, to test against something other than baseline
tools/                     ← helper scripts to play games in batch and collect results
scripts/                   ← scripts from the course template
```

Folders that are **not** committed (they are in `.gitignore`): `venv/`, `__pycache__/`, `mediciones/`
(our local measurements), `rivales_ext/` (other teams' code, which must not be redistributed) and
`compartir/`.

---

## 4. Known pitfalls

- `ModuleNotFoundError: No module named 'contest'` → `pip install -e .` is missing inside `pacman-contest/`
  with the venv active, or you are running from the wrong directory.
- `No module named 'tkinter'` → `sudo apt install python3-tk`.
- Old-style teams with `from capture_agents import ...` or `import util` need `src/contest` on `sys.path`;
  if you run them with `capture.py` directly, do it from `src/contest`.
- `Actions.get_legal_neighbors` **includes the cell itself** (equivalent to STOP), so remember to exclude it
  when you count a cell's real neighbours.
- `game_state.data.timeleft` counts the moves of **all four** agents: divide by 4 to get the number of your
  own turns left.

---

## 5. References

- `pacman-contest/src/contest/CONTEST.md` and `capture.py` (the source of truth for the rules).
- The course's *Programming Project* PDF.
- `pacman-contest/src/contest/baseline_team.py`: the reference reflex agents.
