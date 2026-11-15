"""Run a single capture game and print a JSON summary (score from RED's point of view)."""
import sys, json, io, contextlib, time
import os
# Igual que al ejecutar "python capture.py": la carpeta src/contest en sys.path
# (algunos equipos antiguos hacen "from capture_agents import CaptureAgent").
sys.path.insert(0, os.getcwd())
import contest.capture as capture

# --- Métricas defensivas medidas sobre el estado REAL de cada jugada (no estimadas) ---
# Se engancha en CaptureRules.process, que game.py llama una vez por jugada real
# (generate_successor que usan los agentes para simular NO pasa por aquí).
M = {k: {'red': 0, 'blue': 0} for k in (
    'pac_deaths',      # pacmans de ese color comidos por un fantasma
    'ghost_eaten',     # fantasmas de ese color comidos estando asustados
    'lost_carry',      # comida que llevaban esos pacmans al morir (se devuelve al tablero)
    'pac_turns',       # turnos propios de ese color como pacman (en campo rival)
    'pac_episodes',    # incursiones: transiciones fantasma -> pacman
    'capsules_lost',   # cápsulas de ese color (en su mitad) comidas por el rival
    'scared_turns',    # turnos propios de ese color como FANTASMA asustado (scared_timer > 0)
)}
_prev_caps = [None]
_prev = {}
_orig_process = capture.CaptureRules.process


def _team(state, i):
    return 'red' if state.is_on_red_team(i) else 'blue'


def _process(state, game):
    ads = state.data.agent_states
    mover = getattr(state.data, '_agent_moved', None)
    caps = list(state.data.capsules)
    if _prev_caps[0] is not None:
        half = state.data.layout.width // 2
        for c in _prev_caps[0]:
            if c not in caps:
                M['capsules_lost']['red' if c[0] < half else 'blue'] += 1
    _prev_caps[0] = caps
    for i, a in enumerate(ads):
        p = _prev.get(i)
        cur = (a.is_pacman, a.scared_timer, a.num_carrying)
        if p is not None:
            t = _team(state, i)
            pos = a.get_position()
            at_start = pos is not None and pos == a.start.pos
            if p[0] and not a.is_pacman and at_start:
                M['pac_deaths'][t] += 1
                M['lost_carry'][t] += p[2]
            elif (not p[0]) and (not a.is_pacman) and p[1] > 0 and a.scared_timer == 0 and at_start:
                M['ghost_eaten'][t] += 1
            if i == mover:
                if (not a.is_pacman) and a.scared_timer > 0:
                    M['scared_turns'][t] += 1
                if a.is_pacman:
                    M['pac_turns'][t] += 1
                if a.is_pacman and not p[0]:
                    M['pac_episodes'][t] += 1
        _prev[i] = cur
    return _orig_process(state, game)


capture.CaptureRules.process = staticmethod(_process)

args = sys.argv[1:]
buf = io.StringIO()
t0 = time.time()
with contextlib.redirect_stdout(buf):
    opts = capture.read_command(args)
    games = capture.run_games(**opts)
g = games[0]
st = g.state
red = st.get_red_team_indices()
out = {
    'score': st.data.score,
    'red_returned': sum(st.data.agent_states[i].num_returned for i in red),
    'blue_returned': sum(st.data.agent_states[i].num_returned for i in st.get_blue_team_indices()),
    'metrics': M,
    'agent_crashed': getattr(g, 'agent_crashed', False),
    'secs': round(time.time() - t0, 2),
    'log_tail': buf.getvalue()[-300:],
}
print('RESULT ' + json.dumps(out))
