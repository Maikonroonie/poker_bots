from engine import BaseAgent, Action, ActionType, PlayerState
import random

class Bot8_Random(BaseAgent):
    def act(self, state: PlayerState) -> Action:
        r = random.random()
        if r < 0.2:
            return Action(ActionType.FOLD)
        elif r < 0.6:
            return Action(ActionType.CHECK_CALL)
        else:
            return Action(ActionType.RAISE, amount=state.min_raise + 100)
