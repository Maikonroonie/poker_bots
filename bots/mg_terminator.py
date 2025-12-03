from engine import BaseAgent, Action, ActionType, PlayerState
from treys import Card, Evaluator, Deck
import random

class TerminatorHunter(BaseAgent):
    """
    TERMINATOR v2: HUNTER EDITION
    Agresywna wersja nastawiona na dominację i budowanie dużego stacka.
    - Szerszy zakres rąk (gra suited connectors i niskie pary).
    - Agresywniejsze betowanie (Overbets).
    - Mniejszy lęk przed odpadnięciem (luźniejsze All-Iny).
    """
    def __init__(self, name: str):
        super().__init__(name)
        self.evaluator = Evaluator()
        self.SIMULATION_COUNT = 400 
        
        # --- ZMIANA 1: Szerszy zakres rąk (LOOSE) ---
        # Dodajemy niskie pary i suited connectors (np. 87s), żeby łapać strity/kolory
        self.hunter_hands = [
            'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88', '77', '66', # Pary
            'AK', 'AQ', 'KQ', 'AJ', 'AT', 'KJ', 'QJ',             # Wysokie
            'AKs', 'AQs', 'KQs', 'JTs', 'QJs', 'T9s', '98s', '87s', 'A5s', 'A4s' # Suited & Connectors
        ]

    def _to_treys_cards(self, card_strs):
        return [Card.new(c) for c in card_strs]

    def calculate_multiplayer_equity(self, hand, community_cards, num_opponents=2, iterations=400):
        wins = 0
        for _ in range(iterations):
            deck = Deck()
            known_cards = hand + community_cards
            for card in known_cards:
                if card in deck.cards: deck.cards.remove(card)

            n_community_needed = 5 - len(community_cards)
            board = community_cards + deck.draw(n_community_needed)

            opponents_hands = []
            for _ in range(num_opponents):
                opponents_hands.append(deck.draw(2))

            my_score = self.evaluator.evaluate(board, hand)
            won_hand = True
            is_tie = False
            
            for opp_hand in opponents_hands:
                opp_score = self.evaluator.evaluate(board, opp_hand)
                if opp_score < my_score: 
                    won_hand = False
                    break
                elif opp_score == my_score:
                    is_tie = True

            if won_hand:
                wins += (1.0 / (num_opponents + 1)) if is_tie else 1.0
        
        return wins / iterations

    # --- ZMIANA 2: Agresywniejszy Bet Sizing ---
    def _get_hunter_bet_size(self, state: PlayerState, equity: float, num_opponents: int) -> int:
        pot = state.pot
        
        # Hunter bije mocniej. Podbijamy stawkę o 20% względem standardu.
        aggression_bonus = 1.2
        
        if equity > 0.85: # Monster - wciągamy albo miażdżymy
            multiplier = 0.9 * aggression_bonus
        elif equity > 0.6: # Strong - protection
            multiplier = 0.75 * aggression_bonus
        else: # Semi-Bluff
            multiplier = 0.6

        bet = int(pot * multiplier)
        return max(bet, state.min_raise)

    def act(self, state: PlayerState) -> Action:
        try:
            if state.stack == 0: return Action(ActionType.CHECK_CALL)

            # 1. PRE-FLOP
            if len(state.community_cards) == 0:
                return self._play_preflop(state)

            # 2. PRZYGOTOWANIE
            hand = self._to_treys_cards(state.hand)
            community = self._to_treys_cards(state.community_cards)
            
            if len(community) == 3: simulated_opponents = 2 
            else: simulated_opponents = 1

            # 3. OBLICZENIA
            equity = self.calculate_multiplayer_equity(
                hand, community, num_opponents=simulated_opponents, iterations=self.SIMULATION_COUNT
            )
            
            call_cost = state.current_bet
            total_pot = state.pot + call_cost
            ev = (total_pot * equity) - call_cost

            # 4. DECYZJA HUNTERA

            # A. Check (Darmowe)
            if call_cost == 0:
                # Hunter atakuje częściej. Jeśli ma equity > 40% na flopie, próbuje ukraść pulę.
                threshold = (1.0 / (simulated_opponents + 1)) * 0.9 # Obniżony próg
                
                if equity > threshold:
                    amt = self._get_hunter_bet_size(state, equity, simulated_opponents)
                    if amt > state.stack: amt = state.stack
                    if amt < state.min_raise: amt = state.min_raise
                    return Action(ActionType.RAISE, amount=amt)
                return Action(ActionType.CHECK_CALL)

            # B. Płatne wejście (Call/Raise)
            if ev > -50: # --- ZMIANA 3: Callujemy nawet z lekkim minusem EV (implied odds) ---
                
                # Anti-Loop (Luźniejszy bezpiecznik)
                is_huge_bet = call_cost > state.stack * 0.45 # Pozwalamy na zakłady do 45% stacka
                
                # Jeśli ktoś gra All-In, sprawdzamy z szerszym zakresem (0.65 zamiast 0.85)
                if is_huge_bet and equity < 0.65:
                     return Action(ActionType.CHECK_CALL) # Just call, don't re-raise huge bets without nuts

                # Logika Agresji (Re-Raise)
                avg_win_rate = 1.0 / (simulated_opponents + 1)
                
                # --- ZMIANA 4: Częstszy Raise ---
                # Przebijamy jeśli mamy 1.2x średniej szansy (wcześniej 1.5x)
                if equity > (avg_win_rate * 1.2): 
                    amt = self._get_hunter_bet_size(state, equity, simulated_opponents)
                    total_raise = amt + call_cost
                    
                    # === CRITICAL FIXES (Zachowane) ===
                    if total_raise > state.stack * 0.7: # Szybciej wchodzimy w All-In
                        total_raise = state.stack
                    else:
                        total_raise = min(total_raise, state.stack)
                    
                    if total_raise < state.min_raise and total_raise < state.stack:
                        return Action(ActionType.CHECK_CALL)
                        
                    if total_raise <= state.current_bet:
                         return Action(ActionType.CHECK_CALL)
                    # ==================================

                    return Action(ActionType.RAISE, amount=total_raise)
                
                return Action(ActionType.CHECK_CALL)
            
            else:
                # Crying Call - Hunter rzadziej pasuje na małe bety
                if call_cost < state.stack * 0.08 and equity > 0.15:
                    return Action(ActionType.CHECK_CALL)
                
                return Action(ActionType.FOLD)

        except Exception as e:
            print(f"HUNTER ERROR: {e}")
            return Action(ActionType.CHECK_CALL)

    def _play_preflop(self, state: PlayerState) -> Action:
        hand = state.hand
        ranks = sorted([c[0] for c in hand], key=lambda x: '23456789TJQKA'.index(x), reverse=True)
        suited = 's' if hand[0][1] == hand[1][1] else ''
        hand_str = ''.join(ranks) + suited
        
        is_strong = hand_str in self.hunter_hands
        if not is_strong and len(hand_str) == 3:
            is_strong = hand_str[:2] in self.hunter_hands

        if is_strong:
            # Agresywny start: 3.5x BB zamiast 3x
            amt = max(int(state.min_raise * 2.5), 80)
            if amt > state.stack: amt = state.stack
            return Action(ActionType.RAISE, amount=amt)
        
        # Szersze sprawdzanie na blindach
        if state.current_bet <= state.stack * 0.04:
            return Action(ActionType.CHECK_CALL)
            
        return Action(ActionType.FOLD)