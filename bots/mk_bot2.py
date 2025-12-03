from engine import BaseAgent, Action, ActionType, PlayerState
from treys import Card, Evaluator, Deck
import random

class EVBot(BaseAgent):
    def __init__(self, name: str):
        super().__init__(name)
        self.evaluator = Evaluator()
        # Zmienna do zapamiętania szacowanej liczby graczy między turami
        self.estimated_opponents = 2 

    def _to_treys_cards(self, card_strs):
        """Konwertuje karty z formatu silnika ['Ah', 'Td'] na format biblioteki treys."""
        return [Card.new(c) for c in card_strs]

    def estimate_opponent_count(self, state: PlayerState):
        """
        Sprytna heurystyka:
        Zgadujemy ilu jest graczy na podstawie wielkości puli i etapu gry.
        """
        # Zakładamy standardowy Big Blind = 20 (zgodnie z dokumentacją)
        BIG_BLIND = 20
        
        # Etap 1: PRE-FLOP (Brak kart wspólnych)
        if not state.community_cards:
            # Dzielimy pulę przez BB. Np. Pula 60 / 20 = 3 graczy.
            # Odejmujemy 1 (to my).
            # Wynik: przybliżona liczba rywali, którzy dołożyli się do puli.
            load = state.pot / BIG_BLIND
            opponents = int(load) - 1
            
            # Zabezpieczenia: minimum 1 rywal, maksimum 5 (dla bezpieczeństwa obliczeń)
            self.estimated_opponents = max(1, min(5, opponents))
        
        # Etap 2: POST-FLOP (Są karty na stole)
        else:
            # Tutaj pula rośnie, więc nie możemy już dzielić przez 20.
            # Zamiast tego zakładamy naturalne "wykruszanie się" graczy.
            
            current_opponents = self.estimated_opponents
            
            # Na Turnie (4 karty) i Riverze (5 kart) zazwyczaj zostaje mniej osób
            if len(state.community_cards) >= 4: 
                current_opponents = max(1, current_opponents - 1)
            
            self.estimated_opponents = current_opponents

        return self.estimated_opponents

    def calculate_multiplayer_equity(self, hand, community_cards, num_opponents=2, iterations=500):
        """
        Symulacja Monte Carlo uwzględniająca liczbę przeciwników.
        """
        wins = 0
        for _ in range(iterations):
            deck = Deck()
            
            # Usuwamy znane karty
            known_cards = hand + community_cards
            for card in known_cards:
                if card in deck.cards:
                    deck.cards.remove(card)

            # Dobieramy stół
            n_community_needed = 5 - len(community_cards)
            board = community_cards + deck.draw(n_community_needed)

            # Losujemy ręce dla SZACOWANEJ liczby rywali
            opponents_hands = []
            for _ in range(num_opponents):
                opponents_hands.append(deck.draw(2))

            # Ewaluacja
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
                if is_tie:
                    wins += (1.0 / (num_opponents + 1))
                else:
                    wins += 1.0
        
        return wins / iterations

    def act(self, state: PlayerState) -> Action:
        try:
            # 1. Aktualizujemy szacowaną liczbę graczy
            num_opponents = self.estimate_opponent_count(state)
            
            # 2. Konwersja kart
            hand = self._to_treys_cards(state.hand)
            community = self._to_treys_cards(state.community_cards)
            
            call_cost = state.current_bet
            total_pot_after_call = state.pot + call_cost

            # 3. Liczymy Equity dla wykrytej liczby graczy
            # Pre-flop dajemy mniej iteracji dla szybkości (bo dużo graczy = wolniej)
            iters = 300 if not community else 600
            
            equity = self.calculate_multiplayer_equity(
                hand, community, num_opponents=num_opponents, iterations=iters
            )

            # 4. Obliczamy EV (Expected Value)
            ev_value = (total_pot_after_call * equity) - call_cost

            # DEBUG: Odkomentuj, żeby widzieć co myśli bot w history.txt
            # print(f"[{state.name}] Opps:{num_opponents} Eq:{equity:.2f} EV:{ev_value:.0f}")

            # 5. Decyzje
            
            # Sytuacja A: Check (za darmo)
            if call_cost == 0:
                # Jeśli mamy przewagę nad szacowaną liczbą graczy -> Bet
                # Próg 1/(N+1) to średnia szansa. Np. dla 2 rywali średnia to 33%.
                avg_equity = 1.0 / (num_opponents + 1)
                
                if equity > (avg_equity * 1.5): # Mamy 50% więcej niż średnia
                    return Action(ActionType.RAISE, amount=state.min_raise * 2)
                return Action(ActionType.CHECK_CALL)

            # Sytuacja B: Call/Raise vs Fold
            if ev_value > 0:
                # Jeśli EV jest bardzo wysokie (dominacja), przebijamy
                if ev_value > (state.pot * 0.6) and equity > 0.5:
                    target = int(state.pot * 0.8) + state.min_raise
                    return Action(ActionType.RAISE, amount=target)
                
                return Action(ActionType.CHECK_CALL)
            else:
                # Wyjątek: Implied Odds (tanie oglądanie flopa)
                if call_cost < (state.stack * 0.05) and equity > 0.15:
                     return Action(ActionType.CHECK_CALL)
                
                return Action(ActionType.FOLD)

        except Exception as e:
            print(f"Błąd EVBota: {e}")
            return Action(ActionType.CHECK_CALL)