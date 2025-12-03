from engine import BaseAgent, Action, ActionType, PlayerState
import random

class Bot4_Aggressive(BaseAgent):
    def act(self, state: PlayerState) -> Action:
        if random.random() < 0.7:
            # Raise
            amount = state.min_raise + int(state.pot * 0.5)
            return Action(ActionType.RAISE, amount=amount)
        return Action(ActionType.CHECK_CALL)
