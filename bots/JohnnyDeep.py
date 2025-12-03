from engine import BaseAgent, Action, ActionType, PlayerState
from treys import Card, Evaluator, Deck
import random

class MasterBot(BaseAgent):
    def __init__(self, name: str):
        super().__init__(name)
        self.evaluator = Evaluator()
        self.SIMULATION_COUNT = 500
        
        # Liczniki do śledzenia agresji
        self.raise_counter = 0  # Liczba podbić w danej rundzie
        self.last_pot_size = 0
        self.consecutive_raises = 0  # Kolejne podbicia bez odpowiedzi sprawdzającej
        self.round_start_pot = 0
        
        # Definicje zakresów rąk Preflop
        self.PREFLOP_RANGES = {
            'premium': ['AA', 'KK', 'QQ', 'AKs', 'AK'],
            'strong': ['JJ', 'TT', '99', 'AQs', 'AQ', 'KQs', 'AJs'],
            'playable': ['88', '77', '66', 'ATs', 'KJs', 'QJs', 'JTs', 'KQ', 'AJ', 'AT', 'KJ']
        }

    def act(self, state: PlayerState) -> Action:
        try:
            # Śledzenie zmiany ulicy (flop, turn, river)
            street_start = len(state.community_cards) == 0 or (self.round_start_pot == 0)
            if street_start:
                self.raise_counter = 0
                self.consecutive_raises = 0
                self.round_start_pot = state.pot
            
            # Wykrywanie eskalacji potu
            pot_growth = state.pot / self.round_start_pot if self.round_start_pot > 0 else 1
            
            # 1. PREFLOP
            if len(state.community_cards) == 0:
                return self._play_preflop(state)

            # 2. POSTFLOP - Obliczenia
            hand_cards = [Card.new(c) for c in state.hand]
            board_cards = [Card.new(c) for c in state.community_cards]

            equity = self._calculate_monte_carlo(hand_cards, board_cards)
            texture_danger = self._analyze_board_texture(board_cards)
            
            call_cost = state.current_bet
            pot_odds = call_cost / (state.pot + call_cost) if (state.pot + call_cost) > 0 else 0

            is_draw = self._detect_draws(hand_cards, board_cards)

            # 3. ZABEZPIECZENIA PRZED NIESKOŃCZONĄ PĘTLĄ
            
            # A. Ograniczenie liczby podbić w rundzie
            max_raises_per_street = 2  # Maksymalnie 2 podbicia na ulicę
            if self.raise_counter >= max_raises_per_street:
                # Zbyt wiele podbić - sprawdź nawet z silną ręką
                if call_cost == 0:
                    return Action(ActionType.CHECK_CALL)
                elif pot_odds < equity:
                    return Action(ActionType.CHECK_CALL)
                else:
                    return Action(ActionType.FOLD)
            
            # B. Wykrywanie pot warfare (za duży wzrost potu)
            if pot_growth > 4.0:  # Pot wzrósł ponad 4x od początku ulicy
                # Jesteśmy w niebezpiecznej sytuacji - bądź defensywny
                if equity > 0.85:  # Tylko z monsterem graj agresywnie
                    return self._make_action(ActionType.RAISE, state, multiplier=0.5)
                elif call_cost > state.stack * 0.4:  # Duży bet - all-in lub fold
                    if equity > 0.65:
                        return Action(ActionType.RAISE, amount=state.stack)
                    else:
                        return Action(ActionType.FOLD)
                else:
                    return Action(ActionType.CHECK_CALL)
            
            # C. Przeciwnik jest bardzo agresywny (wielokrotne podbicia)
            opponent_aggression = self._detect_opponent_aggression(state)
            if opponent_aggression > 2:  # Przeciwnik podbijał wiele razy
                # Bądź bardziej konserwatywny
                equity_threshold = 0.75
                if equity < equity_threshold and call_cost > 0:
                    return Action(ActionType.FOLD)
            
            # 4. NORMALNA LOGIKA DECYZYJNA (z ograniczeniami)
            
            # A. Monster (Nuts lub prawie nuts) - Equity > 90%
            if equity > 0.90:
                self.raise_counter += 1
                self.consecutive_raises += 1
                if texture_danger > 0.6:
                    return self._make_action(ActionType.RAISE, state, multiplier=0.8)
                return self._make_action(ActionType.RAISE, state, multiplier=0.6)

            # B. Bardzo silna ręka - Equity > 70%
            elif equity > 0.70:
                self.raise_counter += 1
                self.consecutive_raises += 1
                return self._make_action(ActionType.RAISE, state, multiplier=0.5)

            # C. Dobra ręka lub Bardzo silny Draw (Semi-Bluff)
            elif equity > 0.55 or (is_draw and equity > 0.40):
                if call_cost == 0:
                    # Ogranicz podbicia z draw
                    if is_draw and self.raise_counter > 0:
                        return Action(ActionType.CHECK_CALL)
                    self.raise_counter += 1
                    self.consecutive_raises += 1
                    return self._make_action(ActionType.RAISE, state, multiplier=0.4)
                elif pot_odds < equity:
                    if random.random() < 0.2 and self.raise_counter < 1:  # Rzadziej przebijamy
                        self.raise_counter += 1
                        self.consecutive_raises += 1
                        return self._make_action(ActionType.RAISE, state, multiplier=0.4)
                    return Action(ActionType.CHECK_CALL)
                else:
                    return Action(ActionType.CHECK_CALL)
            
            # D. Słaba ręka, ale dobre Pot Odds
            elif pot_odds < equity:
                return Action(ActionType.CHECK_CALL)

            # E. Fold
            else:
                if call_cost == 0:
                    return Action(ActionType.CHECK_CALL)
                return Action(ActionType.FOLD)

        except Exception as e:
            # Fallback w razie błędu
            return Action(ActionType.CHECK_CALL)

    def _play_preflop(self, state: PlayerState) -> Action:
        hand = state.hand
        ranks = sorted([c[0] for c in hand], reverse=True)
        suits = [c[1] for c in hand]
        is_suited = suits[0] == suits[1]
        
        ranks_str = "".join(ranks)
        hand_str = f"{ranks_str}{'s' if is_suited else ''}"
        
        cost = state.current_bet
        stack = state.stack

        # OGRANICZENIA PREFLOP
        max_preflop_raises = 3
        if self.raise_counter >= max_preflop_raises:
            # Zbyt wiele podbić preflop - tylko z najsilniejszymi rękami
            if hand_str not in ['AA', 'KK', 'QQ', 'AKs']:
                if cost == 0:
                    return Action(ActionType.CHECK_CALL)
                elif cost > stack * 0.1:
                    return Action(ActionType.FOLD)
                else:
                    return Action(ActionType.CHECK_CALL)

        # Strategia
        if hand_str in self.PREFLOP_RANGES['premium'] or ranks[0] == ranks[1]:
            if ranks[0] == ranks[1] and ranks_str not in ['AA', 'KK', 'QQ', 'JJ', 'TT']:
                 if cost > stack * 0.1: 
                     return Action(ActionType.FOLD)
                 return Action(ActionType.CHECK_CALL)
            
            self.raise_counter += 1
            self.consecutive_raises += 1
            return self._make_action(ActionType.RAISE, state, multiplier=3.0, preflop=True)

        if hand_str in self.PREFLOP_RANGES['strong']:
            if cost < stack * 0.15:
                self.raise_counter += 1
                self.consecutive_raises += 1
                return self._make_action(ActionType.RAISE, state, multiplier=2.5, preflop=True)
            return Action(ActionType.CHECK_CALL)

        if hand_str in self.PREFLOP_RANGES['playable']:
            if cost < stack * 0.05:
                return Action(ActionType.CHECK_CALL)
            
        if cost == 0:
            return Action(ActionType.CHECK_CALL)
            
        return Action(ActionType.FOLD)

    def _make_action(self, action_type: ActionType, state: PlayerState, multiplier: float = 0.5, preflop: bool = False) -> Action:
        """Inteligentne dobieranie wielkości zakładu z zabezpieczeniami."""
        if action_type == ActionType.RAISE:
            pot = state.pot
            min_raise = state.min_raise
            
            if preflop:
                bet_size = max(min_raise * 3, int(pot * 0.5))
            else:
                bet_size = int(pot * multiplier)

            # ZMNIEJSZONA LOSOWOŚĆ dla stabilności
            noise = random.uniform(0.95, 1.05)
            bet_size = int(bet_size * noise)

            # BEZPIECZNE OGRANICZENIA
            bet_size = max(bet_size, min_raise)
            bet_size = min(bet_size, state.stack)

            # Jeśli już raz podbiliśmy, nie róbmy gigantycznego raise'a
            if self.raise_counter > 1:
                bet_size = min(bet_size, int(pot * 0.7))
            
            # Nie pozwól na zbyt małe podbicia (które mogłyby powodować pętle)
            if bet_size < min_raise * 1.5:
                bet_size = min_raise * 2

            # Jeśli podbicie jest niewiele większe od call, lepiej sprawdź
            if state.current_bet > 0 and bet_size < state.current_bet * 1.5:
                return Action(ActionType.CHECK_CALL)

            return Action(ActionType.RAISE, amount=bet_size)
            
        return Action(action_type)

    def _calculate_monte_carlo(self, hand, community_cards) -> float:
        deck = Deck()
        
        visible_cards = hand + community_cards
        for card in visible_cards:
            if card in deck.cards:
                deck.cards.remove(card)

        wins = 0
        iterations = min(self.SIMULATION_COUNT, 100)  # Ograniczone dla szybkości
        
        if len(community_cards) == 5:
            iterations = 1
        
        cards_to_draw = 5 - len(community_cards)

        for _ in range(iterations):
            _deck = list(deck.cards)
            random.shuffle(_deck)
            
            sim_board = community_cards + _deck[:cards_to_draw]
            opp_hand = _deck[cards_to_draw:cards_to_draw+2]

            my_score = self.evaluator.evaluate(sim_board, hand)
            opp_score = self.evaluator.evaluate(sim_board, opp_hand)

            if my_score < opp_score:
                wins += 1
            elif my_score == opp_score:
                wins += 0.5

        return wins / max(iterations, 1)

    def _analyze_board_texture(self, board_cards) -> float:
        if len(board_cards) < 3:
            return 0.5
            
        ranks = [Card.get_rank_int(c) for c in board_cards]
        suits = [Card.get_suit_int(c) for c in board_cards]
        
        danger_score = 0.0
        
        suit_counts = {s: suits.count(s) for s in set(suits)}
        max_suit = max(suit_counts.values())
        if max_suit >= 3: danger_score += 0.4
        elif max_suit == 2: danger_score += 0.1
        
        ranks.sort()
        gaps = 0
        for i in range(len(ranks) - 1):
            if ranks[i+1] - ranks[i] == 1:
                gaps += 1
        
        if gaps >= 2: danger_score += 0.3
        
        if len(set(ranks)) < len(ranks):
            danger_score += 0.2
            
        return min(danger_score, 1.0)

    def _detect_draws(self, hand, board) -> bool:
        if len(board) == 5: return False
        
        all_cards = hand + board
        suits = [Card.get_suit_int(c) for c in all_cards]
        ranks = sorted([Card.get_rank_int(c) for c in all_cards])
        
        for s in set(suits):
            if suits.count(s) == 4:
                return True
                
        consecutive = 0
        for i in range(len(ranks) - 1):
            diff = ranks[i+1] - ranks[i]
            if diff == 1:
                consecutive += 1
            elif diff > 1:
                consecutive = 0
            if consecutive >= 3:
                return True
                
        return False

    def _detect_opponent_aggression(self, state: PlayerState) -> int:
        """Proste wykrywanie agresji przeciwnika."""
        # Jeśli przeciwnik wielokrotnie podbijał w tej rundzie
        # (to jest uproszczone - w rzeczywistości potrzebowałbyś historii)
        aggression_score = 0
        
        # Duży bet względem potu
        if state.current_bet > state.pot * 0.5:
            aggression_score += 2
        
        # Wielokrotne min-raisy
        if state.current_bet == state.min_raise and self.consecutive_raises > 0:
            aggression_score += 1
            
        return aggression_score