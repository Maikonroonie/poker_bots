from engine import BaseAgent, Action, ActionType, PlayerState
from treys import Card, Evaluator, Deck
import random

class MasterBot(BaseAgent):
    """
    Kompletny bot turniejowy implementujący:
    1. Pre-flop: Tight-Aggressive
    2. Post-flop: Hybrydowe Equity (Monte Carlo + Static Strength)
    3. Decyzje: Sklansky Dollars (EV)
    4. Betting: Dynamic Bet Sizing (analiza tekstury stołu)
    """
    def __init__(self, name: str):
        super().__init__(name)
        self.evaluator = Evaluator()
        self.SIMULATION_COUNT = 800  # Optymalna liczba dla limitu 3s
        
        # Definicja silnych rąk startowych
        self.strong_hands = [
            'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88',
            'AK', 'AQ', 'KQ', 'AJ', 'AT',
            'AKs', 'AQs', 'KQs', 'JTs', 'QJs'
        ]

    # --- GŁÓWNA PĘTLA DECYZYJNA ---

    def act(self, state: PlayerState) -> Action:
        try:
            # 1. PRE-FLOP
            if len(state.community_cards) == 0:
                return self._play_preflop(state)

            # 2. POST-FLOP (Analiza)
            # A. Obliczamy Equity dwiema metodami
            mc_equity = self._calculate_monte_carlo(state.hand, state.community_cards)
            static_strength = self._calculate_static_strength(state.hand, state.community_cards)

            # B. Analiza dywergencji (Wykrywanie Drawów)
            divergence = mc_equity - static_strength
            final_equity = mc_equity

            if divergence > 0.2:
                # Wykryto Draw (potencjał > obecna siła). 
                # Obniżamy equity o 5% jako "podatek od ryzyka", że nie dobierzemy
                final_equity = mc_equity * 0.95 
            elif divergence < -0.2:
                # Sytuacja rzadka: statycznie silna ręka, która straci wartość (vulnerable)
                final_equity = mc_equity

            # C. Sklansky Dollars & EV
            cost_to_call = state.current_bet
            total_pot_after_call = state.pot + cost_to_call
            
            # Ile z tej puli teoretycznie należy do nas?
            sklansky_value = total_pot_after_call * final_equity
            
            # Czy zyskujemy czy tracimy decydując się na sprawdzenie?
            ev = sklansky_value - cost_to_call

            # Debug logs (widoczne w history.txt)
            # print(f"[Bot] Eq: {final_equity:.2f} (MC:{mc_equity:.2f}/Stat:{static_strength:.2f}) | EV: {ev:.1f}")

            # 3. PODEJMOWANIE DECYZJI
            
            # Sytuacja A: Check (za darmo)
            if cost_to_call == 0:
                # Value Bet lub Semi-Bluff, jeśli equity jest dobre
                if final_equity > 0.6 or (divergence > 0.25 and final_equity > 0.4):
                    amount = self._get_dynamic_bet_size(state, final_equity)
                    return Action(ActionType.RAISE, amount=amount)
                return Action(ActionType.CHECK_CALL)

            # Sytuacja B: Musimy zapłacić (Call/Raise vs Fold)
            else:
                if ev > 0:
                    # --- FIX: OCHRONA PRZED CIĄGŁYM PRZEBIJANIEM ---
                    
                    # Czy przeciwnik zagrał za dużą część naszego stacka? (np. > 30%)
                    is_huge_bet = cost_to_call > state.stack * 0.3
                    
                    # Jeśli zakład jest ogromny, podbijamy TYLKO z absolutnym topem (> 90%)
                    # W przeciwnym razie tylko sprawdzamy (Call), żeby nie wyrzucić się z turnieju
                    if is_huge_bet and final_equity < 0.9:
                        return Action(ActionType.CHECK_CALL)
                    
                    # --- KONIEC FIXU ---

                    # Standardowa logika podbijania (dla mniejszych zakładów lub potworów)
                    if ev > state.pot * 0.15 and final_equity > 0.7:
                         # ... (reszta kodu bez zmian) ...
                         dynamic_amount = self._get_dynamic_bet_size(state, final_equity)
                         total_raise = dynamic_amount + cost_to_call
                         
                         if total_raise > state.stack * 0.6:
                             total_raise = state.stack
                         
                         return Action(ActionType.RAISE, amount=min(total_raise, state.stack))
                    
                    return Action(ActionType.CHECK_CALL)
                
                else:
                    # Ujemne EV -> Fold, chyba że to grosze (crying call)
                    if cost_to_call < state.stack * 0.02 and cost_to_call < state.pot * 0.05:
                        return Action(ActionType.CHECK_CALL)
                    
                    return Action(ActionType.FOLD)

        except Exception as e:
            print(f"CRITICAL ERROR in act: {e}")
            # W razie awarii gramy bezpiecznie check/call zamiast foldować (chyba że bet jest ogromny)
            return Action(ActionType.CHECK_CALL)

    # --- METODY POMOCNICZE (OBLICZENIA) ---

import time # Pamiętaj o imporcie

def _calculate_monte_carlo(self, hand_strs: list, board_strs: list) -> float:
    start_time = time.time()
    
    my_hand = [Card.new(c) for c in hand_strs]
    board = [Card.new(c) for c in board_strs]

    deck = Deck()
    known_cards = my_hand + board
    # Szybsze usuwanie kart (set lookup jest O(1), lista O(N))
    deck_cards_set = set(deck.cards)
    for card in known_cards:
        if card in deck_cards_set:
            deck.cards.remove(card)
    
    stub_deck_cards = deck.cards 
    wins = 0
    splits = 0
    cards_to_deal_count = 5 - len(board)
    
    # Dynamiczna liczba symulacji
    # Jeśli mamy mało czasu, zrobimy mniej, ale nie zcrashujemy
    limit_time = 2.0  # Zostawiamy 1s na resztę logiki

    for i in range(self.SIMULATION_COUNT):
        # Co 100 iteracji sprawdzamy zegar
        if i % 100 == 0 and (time.time() - start_time) > limit_time:
            # Przerywamy i liczymy średnią z tego co mamy
            return (wins + (splits * 0.5)) / (i + 1)

        needed_cards = 2 + cards_to_deal_count
        drawn_cards = random.sample(stub_deck_cards, needed_cards)

        opponent_hand = drawn_cards[:2]
        simulation_board = board + drawn_cards[2:]

        my_score = self.evaluator.evaluate(simulation_board, my_hand)
        opp_score = self.evaluator.evaluate(simulation_board, opponent_hand)

        if my_score < opp_score:
            wins += 1
        elif my_score == opp_score:
            splits += 1

    return (wins + (splits * 0.5)) / self.SIMULATION_COUNT

    def _calculate_static_strength(self, hand_strs: list, board_strs: list) -> float:
        """Ocena siły ręki TU I TERAZ (bez patrzenia w przyszłość)."""
        if not board_strs:
            return 0.5
        my_hand = [Card.new(c) for c in hand_strs]
        board = [Card.new(c) for c in board_strs]
        
        # 1 = Best, 7462 = Worst
        rank = self.evaluator.evaluate(board, my_hand)
        return 1.0 - (rank / 7462.0)

    def _analyze_board_texture(self, board_strs: list) -> float:
        """Zwraca 0.0 (suchy) do 1.0 (mokry/niebezpieczny)."""
        if not board_strs: return 0.0
        
        ranks = [c[0] for c in board_strs]
        suits = [c[1] for c in board_strs]
        danger = 0.0
        
        # Flush check
        suit_counts = {s: suits.count(s) for s in set(suits)}
        if max(suit_counts.values()) >= 3: danger += 0.5
        elif max(suit_counts.values()) == 2: danger += 0.2
        
        # Straight check (uproszczony)
        rank_map = {r: i for i, r in enumerate('23456789TJQKA')}
        idx = sorted([rank_map[r] for r in ranks])
        gaps = 0
        for i in range(len(idx)-1):
            if idx[i+1] - idx[i] == 1: danger += 0.15
        
        return min(danger, 1.0)

    def _get_dynamic_bet_size(self, state: PlayerState, equity: float) -> int:
        """Dostosowuje mnożnik zakładu do sytuacji."""
        texture = self._analyze_board_texture(state.community_cards)
        pot = state.pot
        
        # Logika mnożnika
        if equity > 0.85: # Monster hand
            if texture > 0.4: multiplier = 1.1 # Protection (mokry stół)
            else: multiplier = 0.4 # Trap (suchy stół)
        elif equity > 0.7: # Strong hand
            multiplier = 0.7 + (texture * 0.3)
        else: # Bluff / Semi-Bluff
            multiplier = 0.6 if texture < 0.5 else 0.9

        bet = int(pot * multiplier)
        return max(bet, state.min_raise)

    def _play_preflop(self, state: PlayerState) -> Action:
        """Strategia Tight-Aggressive Pre-flop."""
        hand = state.hand
        # Konwersja do formatu string (np. 'AK', 'T9s')
        ranks = sorted([c[0] for c in hand], key=lambda x: '23456789TJQKA'.index(x), reverse=True)
        suited = 's' if hand[0][1] == hand[1][1] else ''
        hand_str = ''.join(ranks) + suited
        
        # Sprawdzenie alternatywnej nazwy (bez 's' jeśli nie znaleziono)
        is_strong = hand_str in self.strong_hands
        if not is_strong and len(hand_str) == 3:
            is_strong = hand_str[:2] in self.strong_hands

        if is_strong:
            # Raise 3x BB lub przebicie min_raise
            amt = max(state.min_raise * 2, 60) # Zakładamy BB=20, więc 3BB=60
            return Action(ActionType.RAISE, amount=amt)
        
        # Tanie sprawdzenie spekulacyjne
        if state.current_bet <= state.stack * 0.02:
            return Action(ActionType.CHECK_CALL)
            
        return Action(ActionType.FOLD)