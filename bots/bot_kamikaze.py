from engine import BaseAgent, Action, ActionType, PlayerState
import random

class Bot_Kamikaze(BaseAgent):
    """
    Ten bot gra WSZYSTKO (All-In) w każdej rundzie, chyba że ma absolutne śmieci (7-2).
    Służy do testowania odporności psychicznej innych botów.
    """
    def act(self, state: PlayerState) -> Action:
        # Czasami (rzadko) pasuje, żeby nie odpaść w pierwszym rozdaniu z 7-2 offsuit
        # Ale w 85% przypadków gra ALL-IN.
        if random.random() < 0.15:
             return Action(ActionType.FOLD)
        
        # Obliczamy All-In (Wszystkie moje żetony + to co muszę dorzucić)
        # W silniku RAISE amount to zazwyczaj "total bet amount", więc dajemy ogromną liczbę,
        # a silnik powinien to przyciąć do naszego stacka (All-In).
        all_in_amount = state.stack + state.current_bet + 100000 
        
        return Action(ActionType.RAISE, amount=all_in_amount)