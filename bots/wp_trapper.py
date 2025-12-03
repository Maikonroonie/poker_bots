from engine import BaseAgent, Action, ActionType, PlayerState
from treys import Card, Evaluator
import random

class TrapperBot(BaseAgent):
    def __init__(self, name: str):
        super().__init__(name)
        self.evaluator = Evaluator()

    def act(self, state: PlayerState) -> Action:
        try:
            # 1. Konwersja kart
            if len(state.community_cards) > 0:
                hand = [Card.new(c) for c in state.hand]
                board = [Card.new(c) for c in state.community_cards]
                # Obliczamy siłę (1.0 = Royal Flush, 0.0 = High Card)
                rank = self.evaluator.evaluate(board, hand)
                strength = 1.0 - (rank / 7462.0)
            else:
                strength = 0.5 # Preflop placeholder

            # 2. Decyzja
            return self._play_trap(state, strength)

        except Exception as e:
            # print(f"Trapper Error: {e}")
            return Action(ActionType.CHECK_CALL)

    def _play_trap(self, state, strength):
        is_preflop = len(state.community_cards) == 0
        is_river = len(state.community_cards) == 5
        
        # --- FAZA PRE-FLOP (Tutaj nie zastawiamy pułapek, gramy normalnie) ---
        if is_preflop:
            return self._standard_preflop(state)

        # --- FAZA POST-FLOP (Tutaj dzieje się magia) ---
        
        # WARUNEK 1: MAMY POTWORA (Siła > 0.85, np. Kolor, Strit, Trójka)
        if strength > 0.85:
            
            # Jeśli to RIVER (koniec gry) -> Zamykamy pułapkę!
            if is_river:
                # Jeśli przeciwnik zabetował -> PRZEBIJAMY (RAISE)
                if state.current_bet > 0:
                    # All-in lub bardzo mocne przebicie
                    return Action(ActionType.RAISE, amount=state.stack)
                
                # Jeśli przeciwnik czekał -> Robimy Value Bet (chcemy, żeby sprawdził)
                else:
                    # Zagrywamy 50% puli (wygląda jak normalny zakład)
                    bet_size = state.pot * 0.5
                    return Action(ActionType.RAISE, amount=int(state.min_raise + bet_size))

            # Jeśli to FLOP lub TURN -> Udajemy trupa (Slowplay)
            else:
                # Jeśli przeciwnik betuje -> Tylko CALL (nie płoszymy go)
                if state.current_bet > 0:
                    return Action(ActionType.CHECK_CALL)
                
                # Jeśli przeciwnik czeka -> My też czekamy (CHECK)
                # Dajemy mu darmową kartę, może trafi coś słabszego i zacznie betować
                else:
                    return Action(ActionType.CHECK_CALL)

        # WARUNEK 2: MAMY NIC LUB ŚREDNIĄ RĘKĘ
        # Trapper nie blefuje. Jeśli nie ma pułapki, gra szczerze i nudno.
        else:
            pot_odds = 0
            if state.current_bet > 0:
                pot_odds = state.current_bet / (state.pot + state.current_bet)

            # Jeśli mamy coś sensownego (np. Top Parę) i tanio -> Call
            if strength > (pot_odds + 0.15):
                return Action(ActionType.CHECK_CALL)
            
            # Jeśli za darmo -> Check
            if state.current_bet == 0:
                return Action(ActionType.CHECK_CALL)
            
            # Inaczej Fold
            return Action(ActionType.FOLD)

    def _standard_preflop(self, state):
        """Prosta strategia Pre-Flop (Tylko silne karty)"""
        # Nie chcemy tracić żetonów zanim złapiemy potwora
        tiers = {
            'Premium': ['AA', 'KK', 'QQ', 'AKs'],
            'Good': ['JJ', 'TT', '99', 'AQs', 'AJs', 'KQs', 'AKo']
        }
        hand_str = self._format_hand(state.hand)

        if hand_str in tiers['Premium']:
            # Z premium gramy agresywnie, żeby zbudować pulę pod przyszłą pułapkę
            amt = max(state.min_raise, state.pot * 0.8)
            return Action(ActionType.RAISE, amount=int(amt))
        
        if hand_str in tiers['Good']:
            return Action(ActionType.CHECK_CALL)
        
        # Jeśli tanio (mniej niż 2% stacka) lub za darmo (BB) -> Call
        if state.current_bet <= state.stack * 0.02:
             return Action(ActionType.CHECK_CALL)
             
        return Action(ActionType.FOLD)

    def _format_hand(self, hand):
        """Helper ['Ah', 'Ks'] -> 'AKo'"""
        ranks = "23456789TJQKA"
        cards = sorted(hand, key=lambda x: ranks.index(x[0]), reverse=True)
        r1, s1 = cards[0][0], cards[0][1]
        r2, s2 = cards[1][0], cards[1][1]
        suffix = 's' if s1 == s2 else 'o'
        if r1 == r2: return f"{r1}{r2}"
        return f"{r1}{r2}{suffix}"