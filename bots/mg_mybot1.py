from engine import BaseAgent, Action, ActionType, PlayerState
from treys import Card, Evaluator
import random

class MathMacheteBot(BaseAgent):
    def __init__(self, name: str):
        super().__init__(name)
        self.evaluator = Evaluator()

    def get_preflop_strength(self, hand_strs):
        """
        Ocenia siłę ręki przed flopem (0-100 pkt).
        Prosta heurystyka dla 2 kart.
        """
        # Mapowanie figur na liczby
        ranks = {'2':2, '3':3, '4':4, '5':5, '6':6, '7':7, '8':8, '9':9, 'T':10, 'J':11, 'Q':12, 'K':13, 'A':14}
            
        # Rozparsowanie ręki (np. ['Ah', 'Kd'])
        c1_rank = ranks[hand_strs[0][0]]
        c2_rank = ranks[hand_strs[1][0]]
        c1_suit = hand_strs[0][1]
        c2_suit = hand_strs[1][1]
        
        # Sortowanie: wysoka, niska
        high, low = sorted([c1_rank, c2_rank], reverse=True)
        
        # Punkty bazowe (Metoda Chena - uproszczona)
        score = 0
        
        # 1. Najwyższa karta
        if high == 14: score = 10  # Ace
        elif high == 13: score = 8 # King
        elif high == 12: score = 7 # Queen
        elif high == 11: score = 6 # Jack
        else: score = high / 2.0
        
        # 2. Para
        if high == low:
            score *= 2
            if score < 5: score = 5 # Minimum dla pary
        
        # 3. Kolor (Suited)
        if c1_suit == c2_suit:
            score += 2
        
        # 4. Bliskość (Connectors) - szansa na strita
        gap = high - low
        if gap == 1: score += 1
        elif gap == 2: score -= 1
        elif gap > 4: score -= 4
        
        # Normalizacja do 0-1.0 (20 pkt to max ~AA)
        return min(max(score / 20.0, 0), 1.0)

    def act(self, state: PlayerState) -> Action:
        # 1. Konwersja kart
        hand_cards = [Card.new(c) for c in state.hand]
        board_cards = [Card.new(c) for c in state.community_cards]

        is_preflop = len(state.community_cards) == 0
        strength = 0.0

        # 2. Ocena siły ręki
        if is_preflop:
            strength = self.get_preflop_strength(state.hand)
            # Pre-flop thresholdy są inne
            strong_threshold = 0.5  # Np. para 66+, AK, AQ
            medium_threshold = 0.35 # Np. JT, 98s
        else:
            # Post-flop: używamy Treys
            # Wynik 1 (najlepszy) do 7462 (najgorszy)
            score = self.evaluator.evaluate(board_cards, hand_cards)
            # Odwracamy: 1.0 = Royal Flush, 0.0 = High Card 7
            strength = 1.0 - (score / 7462.0)
            
            strong_threshold = 0.85 # Np. Trójka, Strit
            medium_threshold = 0.50 # Np. Para

        # 3. Obliczanie Pot Odds
        call_cost = state.current_bet
        pot_total = state.pot + call_cost
        
        if pot_total == 0: 
            pot_odds = 0 
        else:
            pot_odds = call_cost / pot_total

        # 4. Decyzja
        
        # Jeśli nikt nie przebił (Check/Call za darmo)
        if state.current_bet == 0:
            if strength > strong_threshold:
                # Value Bet - podbijamy, żeby wyciągnąć kasę od słabych botów
                return Action(ActionType.RAISE, amount=state.min_raise)
            return Action(ActionType.CHECK_CALL)

        # Jeśli trzeba zapłacić (Ktoś przebił)
        else:
            # Czy opłaca się sprawdzić? (Siła > Koszt)
            # Dodajemy 10% marginesu na blef/potencjał poprawy (implied odds)
            if strength * 1.1 > pot_odds:
                if strength > strong_threshold:
                    # Mamy potwora -> Przebijamy jeszcze raz (Re-raise)
                    raise_amt = state.current_bet * 2 + state.min_raise
                    return Action(ActionType.RAISE, amount=raise_amt)
                else:
                    # Mamy ok rękę -> Sprawdzamy
                    return Action(ActionType.CHECK_CALL)
            else:
                # Matematyka mówi NIE -> Pas
                return Action(ActionType.FOLD)