from engine import BaseAgent, Action, ActionType, PlayerState

class Bot3_Conservative(BaseAgent):
    def act(self, state: PlayerState) -> Action:
        # Fold if bet is too high relative to stack, otherwise call
        if state.current_bet > state.stack * 0.1:
             return Action(ActionType.FOLD)
        return Action(ActionType.CHECK_CALL)
