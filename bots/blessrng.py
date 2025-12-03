from engine import BaseAgent, Action, ActionType, PlayerState
from treys import Card, Evaluator, Deck
import random

class MasterBot(BaseAgent):
    def __init__(self, name: str):
        super().__init__(name)
        self.evaluator = Evaluator()
        self.SIMULATION_COUNT = 800
        self.strong_hands = [
            'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88',
            'AK', 'AQ', 'KQ', 'AJ', 'AT',
            'AKs', 'AQs', 'KQs', 'JTs', 'QJs'
        ]
        self.raise_counter = 0  # Śledzenie liczby podbić w rundzie
        self.last_pot_size = 0
    
    def act(self, state: PlayerState) -> Action:
        try:
            # Reset licznika przy nowej rundzie
            if len(state.community_cards) == 0:
                self.raise_counter = 0
            
            # Sprawdź, czy sytuacja się powtarza (przeciwnik odpowiada podbiciami)
            pot_growth = state.pot / self.last_pot_size if self.last_pot_size > 0 else 1
            self.last_pot_size = state.pot
            
            action = None
            
            if len(state.community_cards) == 0:
                action = self._play_preflop(state)
            else:
                opponent_is_aggressive = state.current_bet > state.min_raise * 2 or state.pot > state.stack * 0.2
                
                # Jeśli przeciwnik jest agresywny, bądź bardziej konserwatywny
                mc_equity = self._calculate_monte_carlo(state.hand, state.community_cards, is_aggressor=opponent_is_aggressive)
                static_strength = self._calculate_static_strength(state.hand, state.community_cards)

                divergence = mc_equity - static_strength
                final_equity = mc_equity
                if divergence > 0.2:
                    final_equity = mc_equity * 0.95 

                cost_to_call = state.current_bet
                total_pot = state.pot + cost_to_call
                ev = (total_pot * final_equity) - cost_to_call

                # OGRANICZENIE: maksymalnie 3 podbicia w rundzie
                if cost_to_call == 0:
                    if final_equity > 0.75 and self.raise_counter < 3:  # Zwiększony próg z 0.6 do 0.75
                        amount = self._get_dynamic_bet_size(state, final_equity)
                        action = Action(ActionType.RAISE, amount=amount)
                        self.raise_counter += 1
                    else:
                        action = Action(ActionType.CHECK_CALL)
                else:
                    if ev < 0:
                        if cost_to_call < state.stack * 0.02:
                            action = Action(ActionType.CHECK_CALL)
                        else:
                            action = Action(ActionType.FOLD)
                    else:
                        is_monster = final_equity > 0.85
                        is_nuts = final_equity > 0.93

                        if is_monster:
                            if is_nuts and self.raise_counter < 2:  # Ogranicz podbicia z nuts
                                action = Action(ActionType.RAISE, amount=state.stack)
                                self.raise_counter += 1
                            elif self.raise_counter < 2:
                                strong_raise = int(total_pot * 0.5)  # Zmniejszone z 0.6
                                final_raise = max(strong_raise, state.min_raise * 2)
                                if final_raise > state.stack * 0.7:
                                    final_raise = state.stack
                                action = Action(ActionType.RAISE, amount=min(final_raise, state.stack))
                                self.raise_counter += 1
                            else:
                                action = Action(ActionType.CHECK_CALL)
                        else:
                            action = Action(ActionType.CHECK_CALL)

            return self._safety_check(action, state)

        except Exception:
            return Action(ActionType.CHECK_CALL)
    
    def _get_dynamic_bet_size(self, state: PlayerState, equity: float) -> int:
        texture = self._analyze_board_texture(state.community_cards)
        pot = state.pot
        
        # Zmniejszone mnożniki dla podbić
        if equity > 0.85: 
            if texture > 0.4: multiplier = 0.75  # Zmniejszone z 1.1
            else: multiplier = 0.4 
        elif equity > 0.7: 
            multiplier = 0.5 + (texture * 0.2)  # Zmniejszone z 0.7 + (texture * 0.3)
        else: 
            multiplier = 0.4 if texture < 0.5 else 0.6  # Zmniejszone

        noise = random.uniform(0.95, 1.05)  # Zmniejszona zmienność
        bet = int(pot * multiplier * noise)
        
        # Ogranicz maksymalne podbicie do 2/3 stacka
        max_bet = int(state.stack * 0.67)
        bet = min(bet, max_bet)
        
        return max(bet, state.min_raise)