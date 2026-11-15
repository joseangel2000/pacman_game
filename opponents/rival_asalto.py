# my_team.py
# ---------------
# Equipo v1 para el EUTOPIA Pacman Contest (Autonomous Systems, EMAI 2026-27).
#
# Estructura:
#   - EnemyTracker: estimación compartida (entre nuestros 2 agentes) de dónde
#     están los rivales cuando no los vemos. Usa: lecturas de sonar ruidosas,
#     is_pacman (en qué mitad del mapa está), comida que desaparece y respawns.
#   - TeamAgent: utilidades comunes (BFS, casillas frontera, peligro...).
#   - AttackerAgent: come comida, vuelve a casa a depositar, huye de fantasmas.
#   - DefenderAgent: persigue invasores (visibles o estimados) y patrulla.
#
# IMPORTANTE: las posiciones que da EnemyTracker son INFERENCIAS, no
# observaciones. Solo game_state.get_agent_position(i) != None es un hecho.

from collections import deque

from contest.capture_agents import CaptureAgent
from contest.game import Directions, Actions


#################
# Team creation #
#################

def create_team(first_index, second_index, is_red,
                first='AttackerAgent', second='DefenderAgent', num_training=0):
    # Un único tracker compartido por los dos agentes del equipo.
    tracker = EnemyTracker()
    return [eval(first)(first_index, tracker), eval(second)(second_index, tracker)]


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
        self.neighbors = {c: Actions.get_legal_neighbors(c, walls) + [c] for c in self.cells}
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


##############
# Base agent #
##############

class TeamAgent(CaptureAgent):

    def __init__(self, index, tracker, time_for_computing=.1):
        super().__init__(index, time_for_computing)
        self.tracker = tracker
        self.start = None

    def register_initial_state(self, game_state):
        CaptureAgent.register_initial_state(self, game_state)  # precalcula distancias del laberinto
        self.start = game_state.get_agent_position(self.index)
        self.walls = game_state.get_walls()
        w = self.walls.width
        # Columna de nuestro lado pegada a la frontera.
        home_x = w // 2 - 1 if self.red else w // 2
        self.home_cells = [(home_x, y) for y in range(self.walls.height) if not self.walls[home_x][y]]
        self.tracker.initialize(self, game_state)

    # ---------- utilidades ----------

    def is_home_side(self, pos):
        return (pos[0] < self.walls.width // 2) == self.red

    def moves_left(self, game_state):
        # timeleft cuenta movimientos de los 4 agentes.
        return game_state.data.timeleft // 4

    def dist(self, a, b):
        return self.get_maze_distance(a, b)

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
        legal = game_state.get_legal_actions(self.index)
        frontier = deque()
        seen = {start}
        for a in legal:
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
        """Acción que maximiza la distancia al fantasma más cercano."""
        my_pos = game_state.get_agent_position(self.index)
        best, best_val = None, -1
        for a in game_state.get_legal_actions(self.index):
            nxt = Actions.get_successor(my_pos, a)
            nxt = (int(nxt[0]), int(nxt[1]))
            d = min(self.dist(nxt, t) for t in threats)
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

    def choose_action(self, game_state):
        self.tracker.observe(self, game_state)
        action = self.decide(game_state)
        legal = game_state.get_legal_actions(self.index)
        if action not in legal:
            action = Directions.STOP if Directions.STOP in legal else legal[0]
        # El rival que juega justo después de nosotros mueve antes de nuestro
        # compañero: avanzamos su creencia un paso.
        nxt_enemy = (self.index + 1) % game_state.get_num_agents()
        if nxt_enemy in self.tracker.beliefs:
            self.tracker.elapse_time(nxt_enemy)
        return action

    def decide(self, game_state):
        raise NotImplementedError

    # ---------- comportamiento defensivo (lo usan ambos agentes) ----------

    def defend(self, game_state):
        my_state = game_state.get_agent_state(self.index)
        my_pos = my_state.get_position()
        enemy_side = {c for c in self.tracker.cells if not self.is_home_side(c)}

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

        if invaders:
            # Prioridad: los vistos, y entre ellos el más cercano; desempate por comida.
            target = min(invaders, key=lambda inv: (not inv[2], self.dist(my_pos, inv[0]) - 2 * inv[1]))
            tpos = target[0]
            if my_state.scared_timer > 0 and target[2]:
                # Asustados: seguirle de cerca sin dejar que nos coma.
                if self.dist(my_pos, tpos) <= 2:
                    return self.flee_action(game_state, [tpos])
                blocked = enemy_side | self.danger_zone([tpos], 1)
                return self.bfs_first_action(game_state, self.danger_zone([tpos], 2), blocked) or Directions.STOP
            act = self.bfs_first_action(game_state, [tpos], enemy_side)
            if act is not None:
                return act

        # Sin invasores: patrullar la frontera cerca de donde estimamos al rival.
        guesses = [self.tracker.most_likely(i) for i in self.get_opponents(game_state)]
        guesses = [g for g in guesses if g is not None]
        if guesses:
            nearest_enemy = min(guesses, key=lambda g: min(self.dist(g, h) for h in self.home_cells))
            post = min(self.home_cells, key=lambda h: self.dist(h, nearest_enemy))
        else:
            post = self.home_cells[len(self.home_cells) // 2]
        if my_pos == post:
            return Directions.STOP
        return self.bfs_first_action(game_state, [post], enemy_side) or Directions.STOP


##########
# Agents #
##########

class AttackerAgent(TeamAgent):

    RETURN_THRESHOLD = 6  # comida que llevamos antes de volver a depositar

    def decide(self, game_state):
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
        near_ghosts = [g for g in ghosts if self.dist(my_pos, g) <= 5]

        # Oportunista: si estamos en casa y un invasor visible está cerca, a por él.
        if not my_state.is_pacman and my_state.scared_timer == 0:
            for _, st in self.visible_enemies(game_state):
                if st.is_pacman and self.dist(my_pos, st.get_position()) <= 3:
                    act = self.bfs_first_action(game_state, [st.get_position()])
                    if act is not None:
                        return act

        # Final de partida: si vamos ganando y queda poco, a defender.
        if carrying == 0 and self.get_score(game_state) > 0 and moves_left < 40:
            return self.defend(game_state)

        blocked = self.danger_zone(ghosts, 1) if ghosts else set()

        go_home = (
            len(food) <= 2
            or (carrying > 0 and moves_left <= dist_home + 6)
            or carrying >= self.RETURN_THRESHOLD
            or (carrying > 0 and near_ghosts)
        )

        if go_home:
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

        # Buscar comida (o cápsulas) evitando fantasmas.
        targets = food + capsules if near_ghosts else food
        act = self.bfs_first_action(game_state, targets, blocked)
        if act is not None:
            return act
        if near_ghosts:
            return self.flee_action(game_state, near_ghosts)
        return self.bfs_first_action(game_state, self.home_cells) or Directions.STOP


class DefenderAgent(TeamAgent):

    def decide(self, game_state):
        return self.defend(game_state)


# ======================================================================
# RIVAL "ASALTO": dos atacantes a la vez (uno codicioso y uno prudente).
# Sirve para probar si nuestra defensa aguanta dos invasores.
# ======================================================================

class GreedyAttacker(AttackerAgent):
    RETURN_THRESHOLD = 10


class CautiousAttacker(AttackerAgent):
    RETURN_THRESHOLD = 4


def create_team(first_index, second_index, is_red, num_training=0, **kwargs):
    tracker = EnemyTracker()
    return [GreedyAttacker(first_index, tracker), CautiousAttacker(second_index, tracker)]
