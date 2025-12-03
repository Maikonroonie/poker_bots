from engine import BaseAgent, Action, ActionType, PlayerState
from treys import Card, Evaluator
import random

class Bot_Trapper(BaseAgent):
    def __init__(self, name: str):
        super().__init__(name)
        self.evaluator = Evaluator()

    def get_preflop_strength(self, hand_strs):
        ranks = {'2':2, '3':3, '4':4, '5':5, '6':6, '7':7, '8':8, '9':9, 'T':10, 'J':11, 'Q':12, 'K':13, 'A':14}
        c1_rank = ranks[hand_strs[0][0]]
        c2_rank = ranks[hand_strs[1][0]]
        c1_suit = hand_strs[0][1]
        c2_suit = hand_strs[1][1]
        high, low = sorted([c1_rank, c2_rank], reverse=True)
        score = 0
        if high == 14: score = 10
        elif high == 13: score = 8
        elif high == 12: score = 7
        elif high == 11: score = 6
        else: score = high / 2.0
        if high == low: score *= 2
        if score < 5 and high == low: score = 5
        if c1_suit == c2_suit: score += 2
        gap = high - low
        if gap == 1: score += 1
        elif gap == 2: score -= 1
        elif gap > 4: score -= 4
        return min(max(score / 20.0, 0), 1.0)

    def calculate_strength(self, state):
        if len(state.community_cards) == 0:
            return self.get_preflop_strength(state.hand)
        else:
            hand_cards = [Card.new(c) for c in state.hand]
            board_cards = [Card.new(c) for c in state.community_cards]
            score = self.evaluator.evaluate(board_cards, hand_cards)
            return 1.0 - (score / 7462.0)

    def act(self, state: PlayerState) -> Action:
        strength = self.calculate_strength(state)
        
        # Solidne wymagania
        threshold = 0.5

        if strength > threshold:
            # Zamiast przebijać, często tylko sprawdza (Slow Play)
            # Przebija tylko na Riverze (koniec gry) albo jak ma absolutnego "nutsa" (>0.95)
            is_river = len(state.community_cards) == 5
            
            if strength > 0.95 or (is_river and strength > 0.8):
                return Action(ActionType.RAISE, amount=state.min_raise * 3)
            
            return Action(ActionType.CHECK_CALL)

        if state.current_bet <= state.stack * 0.05: # Tanie sprawdzanie
            return Action(ActionType.CHECK_CALL)

        return Action(ActionType.FOLD)