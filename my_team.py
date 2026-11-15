# my_team.py
# ---------------
# Equipo v4.2 para el EUTOPIA Pacman Contest (Autonomous Systems, EMAI 2026-27).
#
# Estructura:
#   - PARAMS: números que controlan el comportamiento. Los ajusta
#     automáticamente tools/aprender.py jugando contra nuestros rivales.
#   - EnemyTracker: estimación compartida de dónde están los rivales ocultos
#     (sonar, is_pacman, comida que desaparece, respawns).
#   - TeamBrain: decide el ROL de cada agente en cada turno (adaptación
#     dentro de la partida) y coordina a quién persigue cada uno.
#   - SmartAgent: un único tipo de agente que sabe atacar, incursionar y
#     defender; el rol se lo da el TeamBrain.
#
# IMPORTANTE: las posiciones que da EnemyTracker son INFERENCIAS, no
# observaciones. Solo game_state.get_agent_position(i) != None es un hecho.

import json
import os
from collections import deque

from contest.capture_agents import CaptureAgent
from contest.game import Directions, Actions


##############
# Parámetros #
##############

# Valores por defecto. tools/aprender.py los sustituye por los aprendidos.
# --- PARAMS START ---
PARAMS = {
    'return_threshold': 6,     # pellets que lleva el atacante antes de volver a casa
    'raid_threshold': 3,       # pellets que lleva el defensor en una incursión
    'passive_turns': 10,       # turnos sin invasores para que el defensor salga a atacar
    'scared_switch': 6,        # si nuestro defensor está asustado más turnos que esto, ataca
    'danger_radius': 1,        # casillas alrededor de un fantasma que no pisamos
    'ghost_alert': 3,          # distancia a la que un fantasma nos hace volver/huir
    'avoid_pockets': 1,        # 1 = evitar callejones sin salida con fantasma cerca
    'pocket_min_carry': 1,     # ...solo si llevamos al menos esta comida (sin comida, morir cuesta poco)
    'double_defense': 0,       # 1 = el atacante vuelve a defender ante 2 invasores
    'double_defense_carry': 0, # ...solo si entre los dos invasores llevan al menos esto
    'double_defense_dist': 99, # ...solo si el atacante está a esta distancia de casa o menos
    'help_carry': 20,          # el atacante ayuda a defender si UN invasor lleva esto o más
    'scared_raid_max_carry': 99,  # asustado, el defensor solo ataca si el invasor lleva menos que esto
    'stuck_turns': 40,         # turnos sin comer para que el atacante cambie de entrada (999 = nunca)
    'stuck_defend': 0,         # si el atacante está atascado, defiende estos turnos antes de reintentar
    'raid_max_aggr': 1.0,      # el defensor solo incursiona si el rival invade menos de esta fracción del tiempo
    'cut_exit': 0,             # 1 = el defensor corta la salida del invasor en vez de perseguirlo
    'endgame_defend': 40,      # turnos finales en los que, si ganamos, defendemos
    # --- Defensa v4 (playbook). Con estos valores a 0 se recupera el comportamiento v3. ---
    'intercept': 1,            # 1 = salir al paso del invasor en su ruta de huida (en vez de perseguirlo por detrás)
    'intercept_min_carry': 3,  # ...solo si el invasor lleva al menos esta comida
    'intercept_slack': 0,      # ...casillas de margen: valen las que llego como mucho 'slack' pasos después que él
    'intercept_pick': 0,       # 0 = casilla factible más cercana a la salida, 1 = la más cercana al invasor
    'intercept_hidden': 1,     # 1 = también con invasor solo estimado (no visto)
    'chase_dist': 2,           # a esta distancia o menos de un invasor visible, persecución directa
    'intercept_fallback': 1,   # 1 = libro p.1: si no llego antes a ninguna casilla de su ruta, voy a la puerta más cercana a él
    'pocket_trap': 1,          # 1 = si el invasor está en un callejón, su "salida" es la boca del callejón
    'pocket_kill': 0,          # 1 = invasor visible en un callejón y llego a su boca antes que él: entro a por él
    'capsule_guard': 0,        # 1 = proteger nuestra cápsula interponiéndonos entre el invasor y ella
                               # 2 = versión del libro (p.3): también si la cápsula está más cerca de él que de mí;
                               #     si no llego antes a su ruta, me pongo en la vecina de la cápsula de su lado
    'capsule_radius': 6,       # ...cuando el invasor está a esta distancia de la cápsula o menos
    'capsule_contain': 0,      # 1 = contención de la cápsula: si el invasor está en su radio y llega antes que yo,
                               #     no le presiono; rodeo hasta quedar más cerca de ella que él (diseño nuestro)
    'contain_dist': 3,         # ...distancia mínima al invasor mientras rodeo
    'seal': 2,                 # 1 = sellar y apretar: si (con mi compañero defensor) llego a TODAS sus puertas antes
                               #     o a la vez que él, me acerco sin abrir ninguna; si no se puede, como antes
                               # 2 = además sella nuestras cápsulas (llegar ESTRICTAMENTE antes); si no puede,
                               #     solo aprieta (sin cápsulas) cuando está a más de capsule_radius de todas
    'seal_press': 0,           # 0 = sellando, preferir margen >= 1 y luego acercarse
                               # 1 = con el invasor VISIBLE, acercarse manda; 2 = acercarse manda siempre
                               #     (bloqueo medido contra lorecleme: invasor oculto quieto y sellado ~500 turnos)
    'seal_patience': 0,        # >0 = si sellando no me acerco a él en estos turnos seguidos, dejo de sellar hasta que
                               #     acabe la invasión (vuelvo a v4.1). 0 = sin límite
    'gates': 0,                # 1 = sin invasores, esperar en el punto que cubre las puertas ponderadas por comida/rival
    'gate_enemy_w': 2.0,       # ...peso de la cercanía del rival a cada puerta
    'zone_split': 0,           # 1 = con dos defensores, cada uno cubre las puertas más cercanas a él
    'patrol_mode': 0,          # sin invasores: 0 = frontera frente al rival estimado más cercano (v3)
                               # 1 = libro p.7 "no morder el amago": casilla que minimiza la peor distancia a las puertas de los dos rivales
    'leash_mode': 1,           # incursión del defensor: 0 = libre, 1 = solo si vuelve antes que el rival, 2 = solo comida pegada a la frontera
    'leash_margin': 4,         # modo 1: pasos de margen sobre la llegada estimada del rival a nuestra frontera
    'leash_k': 4,              # modo 2: distancia máxima a nuestra frontera de la comida permitida
    'leash_aggr': 0.1,         # la correa solo se aplica si el rival invade al menos esta fracción del tiempo
}
# --- PARAMS END ---

# Solo para entrenamiento local: tools/aprender.py prueba variantes pasando
# los parámetros por una variable de entorno. En el torneo no existe y se
# usan los PARAMS de arriba.
try:
    _override = os.environ.get('PACMAN_PARAMS')
    if _override:
        PARAMS.update(json.loads(_override))
except Exception:
    pass


#################
# Team creation #
#################

def create_team(first_index, second_index, is_red,
                first='attack', second='defend', num_training=0):
    tracker = EnemyTracker()
    brain = TeamBrain(tracker)
    return [SmartAgent(first_index, tracker, brain, first),
            SmartAgent(second_index, tracker, brain, second)]


###########################
# Estimación de enemigos  #
###########################


SONAR_NOISE = 6  # capture.py: SONAR_NOISE_RANGE = 13 -> ruido uniforme en [-6, +6]
SIGHT_RANGE = 5  # capture.py: SIGHT_RANGE = 5 (Manhattan)


def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


class EnemyTracker:
    """Distribución de probabilidad sobre la posición de cada rival.

    Filtro bayesiano discreto (las casillas libres del mapa son pocas, así que
    es barato hacerlo exacto en vez de con partículas).
    """

    def __init__(self):
        self.initialized = False
        self.beliefs = {}        # enemy index -> {pos: prob}
        self.prev_state = None   # última observación procesada (de cualquiera de los dos)

    def initialize(self, agent, game_state):
        if self.initialized:
            return
        self.initialized = True
        walls = game_state.get_walls()
        self.width = walls.width
        self.cells = [(x, y) for x in range(walls.width) for y in range(walls.height) if not walls[x][y]]
        # get_legal_neighbors incluye la propia casilla (Directions.STOP = (0, 0)):
        # así el rival puede quedarse quieto o moverse a un vecino.
        self.neighbors = {c: list(set(Actions.get_legal_neighbors(c, walls))) for c in self.cells}
        self.enemies = agent.get_opponents(game_state)
        self.enemies_red = not agent.red
        for e in self.enemies:
            self.reset_to_start(e, game_state)

    def reset_to_start(self, enemy, game_state):
        self.beliefs[enemy] = {game_state.get_initial_agent_position(enemy): 1.0}

    def on_enemy_side(self, pos):
        """True si pos está en la mitad propia del rival (donde es fantasma)."""
        is_red_half = pos[0] < self.width // 2
        return is_red_half == self.enemies_red

    def elapse_time(self, enemy):
        """El rival ha hecho un movimiento: la probabilidad se reparte a vecinos."""
        new = {}
        for pos, p in self.beliefs[enemy].items():
            nbrs = self.neighbors[pos]
            share = p / len(nbrs)
            for n in nbrs:
                new[n] = new.get(n, 0.0) + share
        self.beliefs[enemy] = new

    def observe(self, agent, game_state):
        """Incorpora todo lo que sabemos en este turno."""
        my_pos = game_state.get_agent_position(agent.index)
        team_positions = [game_state.get_agent_position(i) for i in agent.get_team(game_state)]
        distances = game_state.get_agent_distances()
        prev = self.prev_state

        eaten_food = set()
        if prev is not None:
            before = agent.get_food_you_are_defending(prev).as_list()
            now = set(agent.get_food_you_are_defending(game_state).as_list())
            eaten_food = {f for f in before if f not in now}
            before_caps = agent.get_capsules_you_are_defending(prev)
            now_caps = set(agent.get_capsules_you_are_defending(game_state))
            eaten_food |= {c for c in before_caps if c not in now_caps}

        for e in self.enemies:
            st = game_state.get_agent_state(e)
            pos = st.get_position()

            # 1) Observación exacta: hecho, no inferencia.
            if pos is not None:
                self.beliefs[e] = {pos: 1.0}
                continue

            # 2) ¿Ha muerto? Llevaba comida y ahora 0 sin haber depositado,
            #    o lo veíamos muy cerca de uno de los nuestros y ha desaparecido.
            #    Entre dos observaciones el rival se mueve como mucho 1 casilla
            #    y nuestro agente otra, así que si estaba a <= 3 seguiría a <= 5
            #    (visible). Si no lo vemos, es que ha respawneado.
            if prev is not None:
                pst = prev.get_agent_state(e)
                died = (pst.num_carrying > 0 and st.num_carrying == 0
                        and st.num_returned == pst.num_returned)
                ppos = pst.get_position()
                if ppos is not None and any(manhattan(ppos, t) <= 3 for t in team_positions):
                    died = True
                if died:
                    self.reset_to_start(e, game_state)
                    continue

            # 3) Comida nuestra que desaparece -> sabemos dónde estaba un invasor.
            if eaten_food and st.is_pacman:
                candidates = [f for f in eaten_food if self.beliefs[e].get(f, 0) > 0] or list(eaten_food)
                if len(candidates) == 1 or len(self.enemies) == 1:
                    self.beliefs[e] = {candidates[0]: 1.0}
                    eaten_food.discard(candidates[0])
                    continue

            # 4) Filtro bayesiano: sonar + mitad del mapa + "no lo vemos".
            new = {}
            noisy = distances[e] if distances is not None else None
            for p, prob in self.beliefs[e].items():
                if st.is_pacman == self.on_enemy_side(p):
                    continue  # is_pacman nos dice en qué mitad está
                if any(manhattan(p, t) <= SIGHT_RANGE for t in team_positions):
                    continue  # si estuviera ahí lo veríamos
                if noisy is not None and abs(manhattan(my_pos, p) - noisy) > SONAR_NOISE:
                    continue
                new[p] = prob
            if not new:
                # Inconsistencia (p.ej. respawn no detectado): reiniciamos con
                # todas las casillas compatibles con la evidencia actual.
                for p in self.cells:
                    if st.is_pacman == self.on_enemy_side(p):
                        continue
                    if any(manhattan(p, t) <= SIGHT_RANGE for t in team_positions):
                        continue
                    if noisy is not None and abs(manhattan(my_pos, p) - noisy) > SONAR_NOISE:
                        continue
                    new[p] = 1.0
            if not new:
                new = {game_state.get_initial_agent_position(e): 1.0}
            total = sum(new.values())
            self.beliefs[e] = {p: v / total for p, v in new.items()}

        self.prev_state = game_state

    def most_likely(self, enemy):
        b = self.beliefs.get(enemy)
        if not b:
            return None
        return max(b.items(), key=lambda kv: kv[1])[0]


##########################################
# Coordinación: roles dinámicos del equipo #
##########################################

ROLE_ATTACK = 'attack'   # atacante principal: come comida y vuelve con return_threshold
ROLE_RAID = 'raid'       # incursión corta: ataca pero vuelve con raid_threshold
ROLE_RETURN = 'return'   # volver a casa ya a depositar lo que llevamos
ROLE_DEFEND = 'defend'   # proteger nuestro lado


class TeamBrain:
    """Decide el rol de cada agente en cada turno a partir de lo que vemos
    del rival. Todo lo que usa para decidir son HECHOS de la observación
    (is_pacman, num_carrying, scared_timer, marcador, tiempo); las posiciones
    estimadas solo se usan dentro de cada rol para moverse."""

    def __init__(self, tracker):
        self.tracker = tracker
        self.last_invasion = None   # timeleft de la última vez que algún rival era Pacman
        self.roles = {}             # índice de agente -> rol en su último turno
        self.invasion_history = deque(maxlen=200)  # ¿había invasor? en los últimos turnos (perfil del rival)

    def update(self, agent, game_state):
        tl = game_state.data.timeleft
        if self.last_invasion is None:
            self.last_invasion = tl
        invaded = any(game_state.get_agent_state(e).is_pacman for e in agent.get_opponents(game_state))
        if invaded:
            self.last_invasion = tl
        self.invasion_history.append(invaded)

    def aggressiveness(self):
        """Fracción de los últimos turnos en que el rival tenía algún invasor."""
        if not self.invasion_history:
            return 0.0
        return sum(self.invasion_history) / len(self.invasion_history)

    def decide_role(self, agent, game_state):
        me = game_state.get_agent_state(agent.index)
        invaders = [e for e in agent.get_opponents(game_state) if game_state.get_agent_state(e).is_pacman]
        moves_left = game_state.data.timeleft // 4
        endgame_lead = agent.get_score(game_state) > 0 and moves_left < PARAMS['endgame_defend']

        if agent.preferred == ROLE_ATTACK:
            if endgame_lead:
                return ROLE_RETURN if me.num_carrying > 0 else ROLE_DEFEND
            if PARAMS['double_defense'] and len(invaders) >= 2:
                # Dos invasores: un solo defensor no basta. Solo vamos si
                # traen bastante comida y si no estamos demasiado lejos.
                carried = sum(game_state.get_agent_state(e).num_carrying for e in invaders)
                my_pos = me.get_position()
                d_home = min(agent.dist(my_pos, h) for h in agent.home_cells)
                if carried >= PARAMS['double_defense_carry'] and d_home <= PARAMS['double_defense_dist']:
                    return ROLE_RETURN if me.num_carrying > 0 else ROLE_DEFEND
            tl = game_state.data.timeleft
            if PARAMS['stuck_defend'] > 0 and me.num_carrying == 0 and not me.is_pacman \
                    and (agent.last_progress - tl) // 4 >= PARAMS['stuck_turns']:
                # Llevamos mucho sin poder entrar: ayudamos a defender un rato
                # y luego lo volvemos a intentar.
                agent.stuck_defend_until = tl - 4 * PARAMS['stuck_defend']
                # El reloj de "atascado" vuelve a empezar cuando acabe la defensa.
                agent.last_progress = agent.stuck_defend_until
            if agent.stuck_defend_until is not None and tl > agent.stuck_defend_until:
                return ROLE_DEFEND
            if any(game_state.get_agent_state(e).num_carrying >= PARAMS['help_carry'] for e in invaders):
                # Un invasor lleva muchísima comida: entre los dos lo cazamos.
                return ROLE_RETURN if me.num_carrying > 0 else ROLE_DEFEND
            return ROLE_ATTACK

        # Agente defensor
        if endgame_lead:
            return ROLE_RETURN if me.num_carrying > 0 else ROLE_DEFEND
        if invaders:
            max_carry = max(game_state.get_agent_state(e).num_carrying for e in invaders)
            if me.scared_timer > PARAMS['scared_switch'] and max_carry < PARAMS['scared_raid_max_carry']:
                # Asustado no puede comerse a nadie: mejor ser útil atacando.
                return ROLE_RAID
            return ROLE_RETURN if me.num_carrying > 0 else ROLE_DEFEND
        passive_moves = (self.last_invasion - game_state.data.timeleft) // 4
        if passive_moves >= PARAMS['passive_turns'] and self.aggressiveness() < PARAMS['raid_max_aggr']:
            # El rival lleva tiempo sin atacar: salimos los dos a por comida.
            return ROLE_RAID
        return ROLE_RETURN if me.num_carrying > 0 else ROLE_DEFEND


##############
# Base agent #
##############

class SmartAgent(CaptureAgent):

    def __init__(self, index, tracker, brain, preferred, time_for_computing=.1):
        super().__init__(index, time_for_computing)
        self.tracker = tracker
        self.brain = brain
        self.preferred = preferred
        self.start = None
        self.last_progress = None   # timeleft de la última vez que comimos o depositamos
        self.prev_food_count = None
        self.commit_target = None   # comida elegida para entrar por otro sitio si estamos atascados
        self.commit_until = None
        self.stuck_defend_until = None  # timeleft hasta el que el atacante atascado defiende
        self.contain_cap = None     # cápsula que estamos conteniendo (histéresis de capsule_contain)
        self.seal_best = None       # menor distancia al invasor conseguida sellando (seal_patience)
        self.seal_stall = 0         # turnos seguidos sellando sin mejorar esa distancia

    def register_initial_state(self, game_state):
        CaptureAgent.register_initial_state(self, game_state)  # precalcula distancias del laberinto
        self.start = game_state.get_agent_position(self.index)
        self.walls = game_state.get_walls()
        w = self.walls.width
        # Columna de nuestro lado pegada a la frontera.
        home_x = w // 2 - 1 if self.red else w // 2
        self.home_cells = [(home_x, y) for y in range(self.walls.height) if not self.walls[home_x][y]]
        self.tracker.initialize(self, game_state)
        self.pockets = self.compute_pockets()
        self.enemy_side = {c for c in self.tracker.cells if not self.is_home_side(c)}
        self.precompute_defense()

    def precompute_defense(self):
        """Estructuras de la defensa v4 (se calculan una vez, en los 15 s de arranque)."""
        cells = self.tracker.cells
        self.home_set = {c for c in cells if self.is_home_side(c)}
        # Puertas: casillas pegadas a la frontera que de verdad comunican con el otro campo.
        cross = 1 if self.red else -1
        self.gates = [h for h in self.home_cells
                      if 0 <= h[0] + cross < self.walls.width and not self.walls[h[0] + cross][h[1]]]
        if not self.gates:
            self.gates = list(self.home_cells)
        # Distancia de cada casilla a su puerta más cercana (para estimar cuándo llega un rival).
        self.gate_dist = {c: min(self.dist(c, g) for g in self.gates) for c in cells}
        # Boca de cada callejón: la única casilla fuera del callejón pegada a él.
        self.pocket_mouth = {}
        seen = set()
        for c0 in self.pockets:
            if c0 in seen:
                continue
            comp, mouths, stack = set(), set(), [c0]
            while stack:
                c = stack.pop()
                if c in comp:
                    continue
                comp.add(c)
                for n in Actions.get_legal_neighbors(c, self.walls):
                    if n == c:
                        continue
                    if n in self.pockets:
                        stack.append(n)
                    else:
                        mouths.add(n)
            seen |= comp
            if len(mouths) == 1:
                m = next(iter(mouths))
                for c in comp:
                    self.pocket_mouth[c] = m
        # Casillas donde puede esperar un defensor: nuestro campo, cerca de la frontera, fuera de callejones.
        self.wait_cells = [c for c in self.home_set if self.gate_dist[c] <= 5 and c not in self.pockets] \
            or list(self.gates)
        self.post = None
        self.post_cost = None

    def compute_pockets(self):
        """Casillas de callejones sin salida: se obtienen podando hojas
        (casillas con un solo vecino) repetidamente. Lo que queda son los
        ciclos del laberinto; lo podado son los callejones."""
        cells = self.tracker.cells
        # Ojo: get_legal_neighbors incluye la propia casilla (STOP); la quitamos.
        nbrs = {c: [n for n in Actions.get_legal_neighbors(c, self.walls) if n != c] for c in cells}
        degree = {c: len(nbrs[c]) for c in cells}
        queue = deque(c for c in cells if degree[c] <= 1)
        pockets = set()
        while queue:
            c = queue.popleft()
            if c in pockets:
                continue
            pockets.add(c)
            for n in nbrs[c]:
                if n not in pockets:
                    degree[n] -= 1
                    if degree[n] == 1:
                        queue.append(n)
        return pockets

    # ---------- utilidades ----------

    def is_home_side(self, pos):
        return (pos[0] < self.walls.width // 2) == self.red

    def moves_left(self, game_state):
        return game_state.data.timeleft // 4  # timeleft cuenta movimientos de los 4 agentes

    def dist(self, a, b):
        return self.get_maze_distance(a, b)

    def teammate(self, game_state):
        return [i for i in self.get_team(game_state) if i != self.index][0]

    def visible_enemies(self, game_state):
        out = []
        for i in self.get_opponents(game_state):
            st = game_state.get_agent_state(i)
            if st.get_position() is not None:
                out.append((i, st))
        return out

    def bfs_first_action(self, game_state, targets, blocked=frozenset()):
        """Primer paso del camino más corto hacia el objetivo alcanzable más
        cercano, sin pisar casillas bloqueadas. None si no hay camino."""
        start = game_state.get_agent_position(self.index)
        targets = set(targets) - set(blocked)
        if not targets:
            return None
        if start in targets:
            return Directions.STOP
        frontier = deque()
        seen = {start}
        for a in game_state.get_legal_actions(self.index):
            if a == Directions.STOP:
                continue
            nxt = Actions.get_successor(start, a)
            nxt = (int(nxt[0]), int(nxt[1]))
            if nxt in blocked or nxt in seen:
                continue
            seen.add(nxt)
            frontier.append((nxt, a))
        while frontier:
            pos, first = frontier.popleft()
            if pos in targets:
                return first
            for n in Actions.get_legal_neighbors(pos, self.walls):
                if n not in seen and n not in blocked:
                    seen.add(n)
                    frontier.append((n, first))
        return None

    def flee_action(self, game_state, threats):
        """Acción que maximiza la distancia al peligro más cercano."""
        my_pos = game_state.get_agent_position(self.index)
        best, best_val = None, -1
        for a in game_state.get_legal_actions(self.index):
            nxt = Actions.get_successor(my_pos, a)
            nxt = (int(nxt[0]), int(nxt[1]))
            d = min(self.dist(nxt, t) for t in threats)
            if nxt in self.pockets and my_pos not in self.pockets:
                d -= 0.5  # a igualdad, no huir hacia un callejón
            if d > best_val:
                best, best_val = a, d
        return best

    def danger_zone(self, positions, radius=1):
        """Casillas a distancia <= radius de alguna posición."""
        zone = set()
        for p in positions:
            frontier, seen = [p], {p}
            for _ in range(radius):
                nxt = []
                for c in frontier:
                    for n in Actions.get_legal_neighbors(c, self.walls):
                        if n not in seen:
                            seen.add(n)
                            nxt.append(n)
                frontier = nxt
            zone |= seen
        return zone

    # ---------- defensa v4: utilidades ----------

    def step_toward(self, game_state, cell, blocked=None):
        """Un paso hacia 'cell' por nuestro lado (STOP si ya estamos). None si no hay camino."""
        my_pos = game_state.get_agent_position(self.index)
        if my_pos == cell:
            return Directions.STOP
        return self.bfs_first_action(game_state, [cell], self.enemy_side if blocked is None else blocked)

    def route_cell(self, my_pos, ipos, goal, slack, pick, min_goal_dist=0):
        """Casilla de la ruta ipos -> goal (camino más corto del invasor) a la que
        llego antes que él (my_d <= inv_d + slack). None si no llego a ninguna.
        pick 0: la más cercana a goal (cierra la salida); pick 1: la más cercana al invasor.
        min_goal_dist: descarta casillas a menos de esa distancia de goal."""
        total = self.dist(ipos, goal)
        best, best_key = None, None
        for c in self.home_set:
            di = self.dist(ipos, c)
            dg = self.dist(c, goal)
            if di + dg != total or dg < min_goal_dist:
                continue  # no está en el camino más corto del invasor (o es la propia meta)
            dm = self.dist(my_pos, c)
            if dm > di + slack:
                continue  # él llega antes que yo
            key = (self.dist(c, goal), dm) if pick == 0 else (di, dm)
            if best_key is None or key < best_key:
                best, best_key = c, key
        return best

    def invader_exit(self, ipos):
        """Por dónde saldrá el invasor: la boca de su callejón o, si no, su puerta más cercana."""
        if PARAMS['pocket_trap'] and ipos in self.pocket_mouth:
            return self.pocket_mouth[ipos]
        return min(self.gates, key=lambda g: self.dist(ipos, g))

    def intercept_action(self, game_state, my_pos, ipos):
        goal = self.invader_exit(ipos)
        cell = self.route_cell(my_pos, ipos, goal, PARAMS['intercept_slack'], PARAMS['intercept_pick'])
        if cell is None:
            if PARAMS['intercept_fallback']:
                # Libro p.1: no llego antes a ninguna casilla de su ruta -> me pongo en la casilla
                # de frontera (puerta) más cercana a él y le cierro la salida.
                gate = min(self.gates, key=lambda g: self.dist(ipos, g))
                return self.step_toward(game_state, gate)
            return None
        return self.step_toward(game_state, cell)

    def capsule_guard_action(self, game_state, my_pos, invaders):
        """Si un invasor se acerca a nuestra cápsula, nos ponemos en su camino hacia ella."""
        caps = self.get_capsules_you_are_defending(game_state)
        mode = PARAMS['capsule_guard']
        best = None
        for cap in caps:
            for inv in invaders:
                d = self.dist(inv[0], cap)
                hot = d <= PARAMS['capsule_radius'] or (mode == 2 and d < self.dist(my_pos, cap))
                if hot and (best is None or d < best[0]):
                    best = (d, cap, inv[0])
        if best is None:
            return None
        _, cap, ipos = best
        if mode != 2:
            cell = self.route_cell(my_pos, ipos, cap, PARAMS['intercept_slack'], 0)
            if cell is None:
                return None
            return self.step_toward(game_state, cell)
        # Modo 2 (libro p.3). Nunca nos quedamos SOBRE la cápsula: en apply_action el pacman
        # se la come (consume) antes de check_death, así que nos asusta y nos come él.
        cell = self.route_cell(my_pos, ipos, cap, PARAMS['intercept_slack'], 0, min_goal_dist=1)
        if cell is None:
            # Él está más cerca (desigualdad triangular: ninguna casilla de su ruta es mía).
            # Vamos a la vecina de la cápsula por la que llegaría él, para estar en medio cuanto antes.
            nbrs = [n for n in Actions.get_legal_neighbors(cap, self.walls) if n != cap and n in self.home_set]
            if not nbrs:
                return None
            d_cap = self.dist(ipos, cap)
            on_route = [n for n in nbrs if self.dist(ipos, n) + 1 == d_cap] or nbrs
            cell = min(on_route, key=lambda n: self.dist(my_pos, n))
        return self.step_toward(game_state, cell)

    def seal_action(self, game_state, my_pos, ipos, mate_pos, caps=(), visible=False):
        """Sellar y apretar. Extiende el punto 1 del libro ("le cierras la salida") a TODAS sus
        salidas, con la idea de región de dominancia de pursuit-evasion. Margen de una casilla n:
        min sobre nuestras puertas g de d(él, g) - d(nosotros, g), donde "nosotros" es el mejor de
        n y mi compañero defensor. Con margen >= 0 no puede salir por ninguna puerta: si él llega
        a la puerta a la vez que yo, me lo como antes de que cruce (check_death tras cada
        movimiento; un fantasma no asustado se come al pacman). Entre mis movimientos con margen
        >= 0 prefiero los de margen >= 1 (aguanta su siguiente paso) y, a igualdad, el que más me
        acerca a él. None si ningún movimiento sella. ipos puede ser una ESTIMACIÓN.
        caps: cápsulas que también hay que sellar. Ahí el empate NO vale: el pacman se come la
        cápsula (consume) antes de check_death, así que hay que llegar estrictamente antes."""
        gates = list(self.gates) + list(caps)
        strict = [0] * len(self.gates) + [1] * len(caps)
        d_inv = [self.dist(ipos, g) - strict[k] for k, g in enumerate(gates)]
        d_mate = [self.dist(mate_pos, g) for g in gates] if mate_pos is not None else None
        best, best_key = None, None
        for a in game_state.get_legal_actions(self.index):
            n = Actions.get_successor(my_pos, a)
            n = (int(n[0]), int(n[1]))
            if n in self.enemy_side:
                continue
            m = None
            for k, g in enumerate(gates):
                ours = self.dist(n, g)
                if d_mate is not None and d_mate[k] < ours:
                    ours = d_mate[k]
                v = d_inv[k] - ours
                if m is None or v < m:
                    m = v
                if m < 0:
                    break
            if m is None or m < 0:
                continue
            if PARAMS['seal_press'] == 2 or (visible and PARAMS['seal_press'] == 1):
                key = (self.dist(n, ipos), -min(m, 1))
            else:
                key = (-min(m, 1), self.dist(n, ipos))
            if best_key is None or key < best_key:
                best, best_key = a, key
        return best

    def capsule_contain_action(self, game_state, my_pos, ipos, can_eat):
        """Contención de la cápsula. Diseño nuestro (HIPÓTESIS), inspirado en el juego de "guardar un
        objetivo" (Isaacs): la cápsula solo está a salvo si queda en MI región de dominancia, es decir,
        si llego a su ruta hacia ella antes que él. Medido contra greedy_v4: al entrar en el radio de la
        cápsula casi nunca estamos más cerca que él, y en ~50-60 % de las cápsulas perdidas teníamos un
        fantasma a <= 3 justo antes. Por eso, si él gana la carrera, no le presionamos: rodeamos.
        ipos puede ser una ESTIMACIÓN del tracker. Devuelve None si no hay cápsula en juego."""
        caps = self.get_capsules_you_are_defending(game_state)
        if not caps:
            self.contain_cap = None
            return None
        # Histéresis: entramos a capsule_radius y salimos a capsule_radius + 2 (evita oscilar).
        radius = PARAMS['capsule_radius'] + (2 if self.contain_cap is not None else 0)
        cap = min(caps, key=lambda c: self.dist(ipos, c))
        d_inv = self.dist(ipos, cap)
        if d_inv > radius:
            self.contain_cap = None
            return None
        self.contain_cap = cap
        if can_eat:
            return None  # puedo comérmelo en este movimiento: lo hace la persecución normal
        # 1) Si llego antes que él a alguna casilla de su ruta a la cápsula (sin pisar la cápsula:
        #    consume va antes que check_death), me pongo ahí: le mantengo "delante".
        cell = self.route_cell(my_pos, ipos, cap, 0, 0, min_goal_dist=1)
        if cell is not None:
            return self.step_toward(game_state, cell)
        # 2) Él gana la carrera: rodeo sin acercarme a menos de contain_dist hasta una casilla
        #    que esté más cerca de la cápsula que él.
        k = PARAMS['contain_dist']
        near = self.danger_zone([ipos], k - 1)
        if my_pos not in near:
            targets = [c for c in self.home_set if c not in near and self.dist(c, cap) < d_inv]
            act = self.bfs_first_action(game_state, targets, self.enemy_side | near)
            if act is not None:
                return act
            return Directions.STOP
        # Demasiado cerca: me separo sin cruzar al campo rival.
        best, best_d = Directions.STOP, self.dist(my_pos, ipos)
        for a in game_state.get_legal_actions(self.index):
            nxt = Actions.get_successor(my_pos, a)
            nxt = (int(nxt[0]), int(nxt[1]))
            if nxt in self.enemy_side:
                continue
            d = self.dist(nxt, ipos)
            if d > best_d:
                best, best_d = a, d
        return best

    def rival_eta(self, game_state):
        """Pasos que tardaría en llegar a nuestra frontera el primer rival que aún es fantasma:
        cuantil bajo (pesimista) de su creencia. Es una INFERENCIA, no un hecho."""
        eta = 999
        for e in self.get_opponents(game_state):
            if game_state.get_agent_state(e).is_pacman:
                continue
            belief = self.tracker.beliefs.get(e)
            if not belief:
                continue
            items = sorted((self.gate_dist[p], pr) for p, pr in belief.items())
            acc = 0.0
            for d, pr in items:
                acc += pr
                if acc >= 0.15:
                    eta = min(eta, d)
                    break
        return eta

    def leash_filter(self, game_state, food, my_pos):
        """Comida que puede coger el defensor en una incursión sin quedar lejos de casa."""
        mode = PARAMS['leash_mode']
        if mode == 1:
            limit = self.rival_eta(game_state) + PARAMS['leash_margin']
            return [f for f in food if self.dist(my_pos, f) + self.gate_dist[f] <= limit]
        if mode == 2:
            return [f for f in food if self.gate_dist[f] <= PARAMS['leash_k']]
        return food

    def gate_post(self, game_state, my_pos, mate_pos):
        """Casilla de espera que minimiza la distancia ponderada a las puertas.
        Peso de una puerta = comida/cápsulas cerca de ella x cercanía estimada del rival."""
        food = self.get_food_you_are_defending(game_state).as_list() + \
            list(self.get_capsules_you_are_defending(game_state))
        enemies = [e for e in self.get_opponents(game_state)
                   if not game_state.get_agent_state(e).is_pacman and self.tracker.beliefs.get(e)]
        weights = {}
        for g in self.gates:
            food_w = 1.0 + sum(1.0 / (1 + self.dist(g, f)) for f in food)
            if enemies:
                near = 0.0
                for e in enemies:
                    near += sum(pr * 2.718281828 ** (-self.dist(p, g) / 4.0)
                                for p, pr in self.tracker.beliefs[e].items())
                enemy_w = 0.1 + PARAMS['gate_enemy_w'] * near / len(enemies)
            else:
                enemy_w = 1.0
            w = food_w * enemy_w
            if PARAMS['zone_split'] and mate_pos is not None and self.dist(mate_pos, g) < self.dist(my_pos, g):
                w *= 0.25  # esa puerta la cubre mejor mi compañero
            weights[g] = w
        best, best_cost = None, None
        for c in self.wait_cells:
            cost = sum(w * self.dist(c, g) for g, w in weights.items())
            if best_cost is None or cost < best_cost:
                best, best_cost = c, cost
        # Histéresis: no cambiamos de puesto por mejoras mínimas (evita oscilar).
        if self.post is not None and self.post_cost is not None:
            old = sum(w * self.dist(self.post, g) for g, w in weights.items())
            if old <= best_cost * 1.05 + 0.5:
                best, best_cost = self.post, old
        self.post, self.post_cost = best, best_cost
        return best

    # ---------- bucle principal ----------

    def update_progress(self, game_state):
        st = game_state.get_agent_state(self.index)
        tl = game_state.data.timeleft
        progress = (st.num_carrying, st.num_returned)
        if self.last_progress is None or progress != self.prev_food_count and \
                (progress[0] > self.prev_food_count[0] or progress[1] > self.prev_food_count[1]):
            self.last_progress = tl
        self.prev_food_count = progress

    def choose_action(self, game_state):
        self.update_progress(game_state)
        self.tracker.observe(self, game_state)
        self.brain.update(self, game_state)
        role = self.brain.decide_role(self, game_state)
        self.brain.roles[self.index] = role

        if role == ROLE_DEFEND:
            action = self.defend(game_state)
        elif role == ROLE_RETURN:
            action = self.attack(game_state, threshold=0, force_home=True)
        elif role == ROLE_RAID:
            action = self.attack(game_state, threshold=PARAMS['raid_threshold'], leash=True)
        else:
            action = self.attack(game_state, threshold=PARAMS['return_threshold'])

        legal = game_state.get_legal_actions(self.index)
        if action not in legal:
            action = Directions.STOP if Directions.STOP in legal else legal[0]
        # El rival que juega justo después de nosotros mueve antes de nuestro
        # compañero: avanzamos su creencia un paso.
        nxt_enemy = (self.index + 1) % game_state.get_num_agents()
        if nxt_enemy in self.tracker.beliefs:
            self.tracker.elapse_time(nxt_enemy)
        return action

    # ---------- ataque ----------

    def attack(self, game_state, threshold, force_home=False, leash=False):
        my_state = game_state.get_agent_state(self.index)
        my_pos = my_state.get_position()
        carrying = my_state.num_carrying
        food = self.get_food(game_state).as_list()
        capsules = self.get_capsules(game_state)
        dist_home = min(self.dist(my_pos, h) for h in self.home_cells)
        moves_left = self.moves_left(game_state)

        # Fantasmas rivales peligrosos (vistos, no asustados o casi sin susto).
        ghosts = [st.get_position() for _, st in self.visible_enemies(game_state)
                  if not st.is_pacman and st.scared_timer <= 2]
        near_ghosts = [g for g in ghosts if self.dist(my_pos, g) <= PARAMS['ghost_alert']]

        # Oportunista: si estamos en casa y un invasor visible está cerca, a por él.
        if not my_state.is_pacman and my_state.scared_timer == 0:
            for _, st in self.visible_enemies(game_state):
                if st.is_pacman and self.dist(my_pos, st.get_position()) <= 3:
                    act = self.bfs_first_action(game_state, [st.get_position()], self.enemy_side)
                    if act is not None:
                        return act

        danger = self.danger_zone(ghosts, PARAMS['danger_radius']) if ghosts else set()
        blocked = danger
        if near_ghosts and PARAMS['avoid_pockets'] and my_pos not in self.pockets \
                and carrying >= PARAMS['pocket_min_carry']:
            blocked = blocked | self.pockets

        # Correa (playbook, punto 5): el defensor que incursiona solo coge comida
        # si puede estar de vuelta antes de que el rival llegue a nuestra frontera.
        leash_idle = False
        invaded_now = any(game_state.get_agent_state(e).is_pacman for e in self.get_opponents(game_state))
        if leash and PARAMS['leash_mode'] and not invaded_now and self.brain.aggressiveness() >= PARAMS['leash_aggr']:
            food_t = self.leash_filter(game_state, food, my_pos)
            leash_idle = not food_t
            if leash_idle and not my_state.is_pacman:
                return self.defend(game_state)
        else:
            food_t = food

        go_home = (
            force_home
            or leash_idle
            or len(food) <= 2
            or (carrying > 0 and moves_left <= dist_home + 6)
            or (threshold > 0 and carrying >= threshold)
            or (carrying > 0 and near_ghosts)
        )

        if go_home:
            if carrying == 0 and not my_state.is_pacman and force_home:
                return Directions.STOP
            # Con fantasma cerca, una cápsula más cercana que casa nos salva.
            if near_ghosts and capsules:
                cap = min(capsules, key=lambda c: self.dist(my_pos, c))
                if self.dist(my_pos, cap) < dist_home:
                    act = self.bfs_first_action(game_state, [cap], blocked)
                    if act is not None:
                        return act
            act = self.bfs_first_action(game_state, self.home_cells, blocked)
            if act is not None:
                return act
            if near_ghosts:
                return self.flee_action(game_state, near_ghosts)
            act = self.bfs_first_action(game_state, self.home_cells)
            if act is not None:
                return act

        # Atascado (p.ej. un fantasma vigila la entrada y oscilamos): elegimos
        # una comida lejos de los fantasmas y nos comprometemos con ella.
        stuck_moves = (self.last_progress - game_state.data.timeleft) // 4
        if carrying == 0 and stuck_moves >= PARAMS['stuck_turns']:
            tl = game_state.data.timeleft
            if self.commit_target not in food or self.commit_until is None or tl < self.commit_until:
                guards = list(ghosts)
                for e in self.get_opponents(game_state):
                    if not game_state.get_agent_state(e).is_pacman:
                        est = self.tracker.most_likely(e)
                        if est is not None:
                            guards.append(est)
                if guards and food:
                    self.commit_target = max(food, key=lambda f: min(self.dist(f, g) for g in guards)
                                             - self.dist(my_pos, f))
                    self.commit_until = tl - 4 * 40
            if self.commit_target in food:
                act = self.bfs_first_action(game_state, [self.commit_target], danger)
                if act is not None:
                    return act

        # Si el compañero también ataca, repartimos la comida: cada uno va a
        # por la que le queda más cerca a él que al compañero.
        targets = food_t
        mate = self.teammate(game_state)
        if self.brain.roles.get(mate) in (ROLE_ATTACK, ROLE_RAID):
            mate_pos = game_state.get_agent_position(mate)
            mine = [f for f in food_t if self.dist(my_pos, f) <= self.dist(mate_pos, f)]
            if mine:
                targets = mine
        if near_ghosts:
            targets = targets + capsules
        act = self.bfs_first_action(game_state, targets, blocked)
        if act is None and targets is not food_t:
            act = self.bfs_first_action(game_state, food_t + capsules, blocked)
        if act is None and blocked is not danger:
            # Sin camino evitando callejones: probamos solo evitando al fantasma.
            act = self.bfs_first_action(game_state, food_t + capsules, danger)
        if act is not None:
            return act
        if near_ghosts:
            return self.flee_action(game_state, near_ghosts)
        return self.bfs_first_action(game_state, self.home_cells) or Directions.STOP

    # ---------- defensa ----------

    def defend(self, game_state):
        my_state = game_state.get_agent_state(self.index)
        my_pos = my_state.get_position()

        # Si estamos en campo rival (p.ej. veníamos de atacar), volver primero.
        if my_state.is_pacman:
            act = self.bfs_first_action(game_state, self.home_cells)
            if act is not None:
                return act

        invaders = []  # (pos, carrying, observed?)
        for i in self.get_opponents(game_state):
            st = game_state.get_agent_state(i)
            if not st.is_pacman:
                continue
            pos = st.get_position()
            if pos is not None:
                invaders.append((pos, st.num_carrying, True))
            else:
                est = self.tracker.most_likely(i)
                if est is not None:
                    invaders.append((est, st.num_carrying, False))

        if not invaders:
            self.contain_cap = None
            self.seal_best, self.seal_stall = None, 0
        if invaders:
            mate = self.teammate(game_state)
            mate_pos = game_state.get_agent_position(mate)
            mate_defends = self.brain.roles.get(mate) == ROLE_DEFEND and mate_pos is not None
            key = lambda pos, inv: (not inv[2], self.dist(pos, inv[0]) - 2 * inv[1])

            if mate_defends and len(invaders) >= 2:
                # Dos defensores, dos invasores: reparto que minimiza la distancia total.
                a, b = invaders[0], invaders[1]
                cost_ab = self.dist(my_pos, a[0]) + self.dist(mate_pos, b[0])
                cost_ba = self.dist(my_pos, b[0]) + self.dist(mate_pos, a[0])
                target = a if cost_ab <= cost_ba else b
            else:
                target = min(invaders, key=lambda inv: key(my_pos, inv))
            tpos = target[0]

            mate_closer = mate_defends and len(invaders) == 1 \
                and self.dist(mate_pos, tpos) < self.dist(my_pos, tpos)

            if PARAMS['capsule_contain'] and my_state.scared_timer == 0:
                can_eat = target[2] and self.dist(my_pos, tpos) <= 1
                act = self.capsule_contain_action(game_state, my_pos, tpos, can_eat)
                if act is not None:
                    return act

            give_up = PARAMS['seal_patience'] and self.seal_stall >= PARAMS['seal_patience']
            if PARAMS['seal'] and my_state.scared_timer == 0 and not give_up \
                    and not (target[2] and self.dist(my_pos, tpos) <= 1):
                # (Si está a 1 y lo vemos, la persecución directa de abajo se lo come.)
                mst = game_state.get_agent_state(mate)
                seal_mate = mate_pos if (mate_defends and len(invaders) == 1 and not mst.is_pacman
                                         and mst.scared_timer == 0) else None
                caps = self.get_capsules_you_are_defending(game_state) if PARAMS['seal'] == 2 else []
                act = self.seal_action(game_state, my_pos, tpos, seal_mate, caps, target[2])
                if act is None and caps and all(self.dist(tpos, c) > PARAMS['capsule_radius'] for c in caps):
                    act = self.seal_action(game_state, my_pos, tpos, seal_mate, (), target[2])
                if act is not None:
                    d_now = self.dist(my_pos, tpos)
                    if self.seal_best is None or d_now < self.seal_best:
                        self.seal_best, self.seal_stall = d_now, 0
                    else:
                        self.seal_stall += 1
                    return act

            if PARAMS['pocket_kill'] and my_state.scared_timer == 0 and target[2] and not mate_closer \
                    and tpos in self.pockets:
                # Callejón de 1 casilla de ancho: si llego a la boca antes de que él pueda salir,
                # no puede cruzarse conmigo (check_death se evalúa tras cada movimiento). Al coincidir
                # en una casilla, un fantasma no asustado se come al pacman, se mueva quien se mueva.
                mouth = self.pocket_mouth.get(tpos)
                if mouth is not None and self.dist(my_pos, mouth) <= self.dist(tpos, mouth):
                    act = self.bfs_first_action(game_state, [tpos], self.enemy_side)
                    if act is not None:
                        return act

            if my_state.scared_timer == 0 and (PARAMS['capsule_guard'] or PARAMS['intercept']):
                # Con dos defensores y un invasor, el más cercano lo persigue directamente
                # y el otro se interpone (cápsula o ruta de huida).
                i_cut = mate_closer or not (mate_defends and len(invaders) == 1)
                close = target[2] and self.dist(my_pos, tpos) <= PARAMS['chase_dist']
                if PARAMS['capsule_guard'] == 2 and i_cut and close and self.dist(my_pos, tpos) > 1:
                    # Libro p.3: con la cápsula en juego, ponerse en medio tiene prioridad sobre
                    # perseguirle (salvo que pueda comérmelo en este movimiento). Medido: en ~50 % de
                    # las cápsulas perdidas teníamos un fantasma a <= 3 justo antes (la usa para huir).
                    act = self.capsule_guard_action(game_state, my_pos, invaders)
                    if act is not None:
                        return act
                if i_cut and not close:
                    if PARAMS['capsule_guard']:
                        act = self.capsule_guard_action(game_state, my_pos, invaders)
                        if act is not None:
                            return act
                    if PARAMS['intercept'] and target[1] >= PARAMS['intercept_min_carry'] \
                            and (target[2] or PARAMS['intercept_hidden']):
                        act = self.intercept_action(game_state, my_pos, tpos)
                        if act is not None:
                            return act

            if mate_defends and len(invaders) == 1 and self.dist(mate_pos, tpos) < self.dist(my_pos, tpos) \
                    and self.dist(my_pos, tpos) > 3:
                # El compañero lo persigue; yo me adelanto. Si llego antes que él
                # a la comida que tiene más cerca, le espero ahí; si no, le
                # corto la huida en la frontera.
                our_food = self.get_food_you_are_defending(game_state).as_list()
                ahead = [f for f in our_food if self.dist(my_pos, f) < self.dist(tpos, f)]
                if ahead:
                    spot = min(ahead, key=lambda f: self.dist(tpos, f))
                else:
                    spot = min(self.home_cells, key=lambda h: self.dist(h, tpos))
                if my_pos == spot:
                    return Directions.STOP
                act = self.bfs_first_action(game_state, [spot], self.enemy_side)
                if act is not None:
                    return act

            if PARAMS['cut_exit'] and target[2] and target[1] > 0 and self.dist(my_pos, tpos) > 2:
                # Invasor visible con comida: para puntuar tiene que cruzar la
                # frontera. Vamos a la salida más cercana a él si llegamos antes.
                exits = [h for h in self.home_cells if self.dist(my_pos, h) < self.dist(tpos, h)]
                if exits:
                    escape = min(exits, key=lambda h: self.dist(h, tpos))
                    if my_pos != escape:
                        act = self.bfs_first_action(game_state, [escape], self.enemy_side)
                        if act is not None:
                            return act

            if my_state.scared_timer > 0 and target[2]:
                # Asustados: seguirle de cerca sin dejar que nos coma.
                if self.dist(my_pos, tpos) <= 2:
                    return self.flee_action(game_state, [tpos])
                blocked = self.enemy_side | self.danger_zone([tpos], 1)
                return self.bfs_first_action(game_state, self.danger_zone([tpos], 2), blocked) or Directions.STOP
            act = self.bfs_first_action(game_state, [tpos], self.enemy_side)
            if act is not None:
                return act

        if PARAMS['gates']:
            mate = self.teammate(game_state)
            mate_pos = game_state.get_agent_position(mate) \
                if self.brain.roles.get(mate) == ROLE_DEFEND else None
            post = self.gate_post(game_state, my_pos, mate_pos)
            act = self.step_toward(game_state, post)
            if act is not None:
                return act

        # Sin invasores: patrullar la frontera cerca de donde estimamos al rival.
        guesses = [self.tracker.most_likely(i) for i in self.get_opponents(game_state)]
        guesses = [g for g in guesses if g is not None]
        if guesses and PARAMS['patrol_mode'] == 1:
            # Libro p.7: si los rivales están estimados frente a puertas distintas, no irse a un
            # extremo. Casilla de frontera que minimiza la PEOR distancia a sus puertas; a igualdad,
            # la más cercana a la puerta más amenazada.
            their_gates = list({min(self.gates, key=lambda gt: self.dist(g, gt)) for g in guesses})
            first = min(their_gates, key=lambda gt: min(self.dist(g, gt) for g in guesses))
            post = min(self.home_cells, key=lambda h: (max(self.dist(h, gt) for gt in their_gates),
                                                       self.dist(h, first)))
        elif guesses:
            nearest_enemy = min(guesses, key=lambda g: min(self.dist(g, h) for h in self.home_cells))
            post = min(self.home_cells, key=lambda h: self.dist(h, nearest_enemy))
        else:
            post = self.home_cells[len(self.home_cells) // 2]
        if my_pos == post:
            return Directions.STOP
        return self.bfs_first_action(game_state, [post], self.enemy_side) or Directions.STOP
