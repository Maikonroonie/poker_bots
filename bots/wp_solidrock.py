from engine import BaseAgent, Action, ActionType, PlayerState
from treys import Card, Evaluator

class BenchmarkBot(BaseAgent):
    def __init__(self, name: str):
        super().__init__(name)
        self.evaluator = Evaluator()
        # Lista rąk, z którymi ten bot w ogóle wchodzi do gry. Resztę pasuje.
        self.playable_hands = [
            'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88',       # Pary
            'AKs', 'AQs', 'AJs', 'ATs', 'KQs', 'KJs', 'QJs', # Figury w kolorze
            'AKo', 'AQo', 'KQo'                             # Mocne figury
        ]

    def act(self, state: PlayerState) -> Action:
        try:
            # 1. Sprawdzamy fazę gry
            if len(state.community_cards) == 0:
                return self._play_preflop(state)
            else:
                return self._play_postflop(state)

        except Exception as e:
            # W razie błędu bezpieczny Check/Call
            return Action(ActionType.CHECK_CALL)

    def _play_preflop(self, state):
        """Gra tylko "z książki". Żadnych eksperymentów."""
        hand_str = self._format_hand(state.hand)

        # Jeśli ręka jest na liście grywalnych
        if hand_str in self.playable_hands:
            # Jeśli mamy super premium (AA, KK, AK) -> Podbijamy
            if hand_str in ['AA', 'KK', 'QQ', 'AKs', 'AKo']:
                return Action(ActionType.RAISE, amount=max(state.min_raise, state.pot))
            
            # Jeśli mamy dobrą, ale nie super -> Sprawdzamy (chyba że podbicie jest tanie)
            return Action(ActionType.CHECK_CALL)
        
        # Jeśli ręka jest słaba (nie ma jej na liście)
        else:
            # Jeśli możemy wejść za darmo (jesteśmy na Big Blindzie i nikt nie podbił)
            if state.current_bet == 0:
                return Action(ActionType.CHECK_CALL)
            # W przeciwnym razie Fold
            return Action(ActionType.FOLD)

    def _play_postflop(self, state):
        """Gra 'Hit or Fold'. Jeśli trafił w stół - gra. Jak nie - pasuje."""
        # Konwersja kart dla biblioteki treys
        hand = [Card.new(c) for c in state.hand]
        board = [Card.new(c) for c in state.community_cards]
        
        # Ocena siły (0.0 słaba, 1.0 silna)
        rank = self.evaluator.evaluate(board, hand)
        strength = 1.0 - (rank / 7462.0)

        # Jeśli mamy układ lepszy niż Para (siła ok. 0.7 w górę w treys)
        # Uwaga: W treys 0.7 to często już przyzwoita para.
        
        if strength > 0.8:
            # Mamy coś silnego (Dwie pary, Trójka) -> RAISE
            return Action(ActionType.RAISE, amount=state.min_raise * 2)
        
        elif strength > 0.5:
            # Mamy coś średniego (Para) -> CALL
            # Ale jeśli zakład jest ogromny (np. All-in), to pasujemy
            if state.current_bet > state.stack * 0.5:
                return Action(ActionType.FOLD)
            return Action(ActionType.CHECK_CALL)
            
        else:
            # Nie mamy nic (Nietrafione karty)
            # Jeśli za darmo -> Check
            if state.current_bet == 0:
                return Action(ActionType.CHECK_CALL)
            # Jeśli trzeba płacić -> FOLD
            return Action(ActionType.FOLD)

    def _format_hand(self, hand):
        """Pomocnik: zamienia karty na format czytelny dla naszej listy (np. 'AKs')"""
        ranks = "23456789TJQKA"
        # Sortujemy karty, żeby zawsze mieć wyższą pierwszą (np. AK, a nie KA)
        cards = sorted(hand, key=lambda x: ranks.index(x[0]), reverse=True)
        
        r1, s1 = cards[0][0], cards[0][1]
        r2, s2 = cards[1][0], cards[1][1]
        
        suffix = 's' if s1 == s2 else 'o'
        if r1 == r2: return f"{r1}{r2}" # Para
        return f"{r1}{r2}{suffix}"