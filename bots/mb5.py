import time
import random
from engine import BaseAgent, Action, ActionType, PlayerState
from treys import Card, Evaluator, Deck

class AnalyticBot(BaseAgent):
    def __init__(self, name: str):
        super().__init__(name)
        self.evaluator = Evaluator()
        # Predefiniowane silne ręce startowe (Tier List), żeby nie liczyć tego w czasie gry
        self.preflop_tiers = {
            'Tier1': ['AA', 'KK', 'QQ', 'JJ', 'AKs'],              # Raise/All-in
            'Tier2': ['TT', '99', '88', 'AQs', 'AJs', 'KQs', 'AKo'], # Raise
            'Tier3': ['77', '66', 'ATs', 'KJs', 'QJs', 'JTs', 'AQo'] # Call/Check
        }

    def act(self, state: PlayerState) -> Action:
        start_time = time.time()
        
        try:
            # 1. Konwersja danych
            hand = [Card.new(c) for c in state.hand]
            board = [Card.new(c) for c in state.community_cards]
            
            # 2. Szacowanie liczby rywali (Twoja funkcja!)
            num_opponents = self._estimate_active_players(state)
            
            # 3. Decyzja
            if len(board) == 0:
                return self._play_preflop(state, num_opponents)
            else:
                # Na post-flopie uruchamiamy symulację
                # Dajemy sobie max 2.0 sekundy na myślenie
                equity = self._monte_carlo_simulation(hand, board, num_opponents, time_limit=2.0)
                return self._play_postflop(state, equity, num_opponents)

        except Exception as e:
            # Fallback w razie błędu obliczeń
            # print(f"AnalyticBot Error: {e}")
            return Action(ActionType.CHECK_CALL)

    def _play_preflop(self, state, num_opponents):
        """Strategia tabelkowa, ale dostosowana do tłumu."""
        hand_str = self._format_hand(state.hand)
        
        # Jeśli gramy 1 na 1, gramy luźniej. Jeśli tłum (5+ graczy), gramy tylko Tier 1.
        
        if hand_str in self.preflop_tiers['Tier1']:
            # Premium -> Zawsze agresywnie
            raise_amt = max(state.min_raise, state.pot * 0.75)
            return Action(ActionType.RAISE, amount=int(raise_amt))
            
        if hand_str in self.preflop_tiers['Tier2']:
            if num_opponents > 4: 
                # W tłumie Tier 2 jest ryzykowny -> tylko Call
                return Action(ActionType.CHECK_CALL)
            return Action(ActionType.RAISE, amount=state.min_raise)
            
        if hand_str in self.preflop_tiers['Tier3']:
            # Sprawdzamy tylko, jeśli tanio
            if state.current_bet <= state.stack * 0.05:
                return Action(ActionType.CHECK_CALL)
                
        # Zawsze Call jeśli za darmo (Big Blind)
        if state.current_bet == 0:
            return Action(ActionType.CHECK_CALL)
            
        return Action(ActionType.FOLD)

    def _play_postflop(self, state, equity, num_opponents):
        """Podejmuje decyzję na podstawie wyliczonego Equity i Pot Odds."""
        
        # Obliczamy Pot Odds (jaki % puli musimy dołożyć)
        to_call = state.current_bet
        pot_total = state.pot + to_call
        
        if to_call == 0:
            pot_odds = 0
        else:
            pot_odds = to_call / pot_total

        # Wprowadzamy "Margines Bezpieczeństwa"
        # Im więcej graczy, tym większy margines potrzebujemy, 
        # bo Equity dzielone jest na więcej osób.
        # Wzór: equity musi być lepsze niż (1/N graczy)
        
        # Sytuacja: Mamy 80% szans (Nuts)
        if equity > 0.85:
            # Value Bet - chcemy, żeby sprawdzili, ale nie za dużo
            bet = state.pot * 0.5
            return Action(ActionType.RAISE, amount=int(state.min_raise + bet))

        # Sytuacja: Mamy dobre szanse (większe niż Pot Odds + Margines)
        # Margines: 5% + (2% za każdego rywala)
        safety_margin = 0.05 + (0.02 * num_opponents)
        
        if equity > (pot_odds + safety_margin):
            # Jeśli mamy bardzo dużą przewagę -> Raise
            if equity > (pot_odds * 2):
                return Action(ActionType.RAISE, amount=state.min_raise)
            # W przeciwnym razie bezpieczny Call
            return Action(ActionType.CHECK_CALL)
            
        # Jeśli możemy czekać za darmo
        if to_call == 0:
            return Action(ActionType.CHECK_CALL)
            
        return Action(ActionType.FOLD)

    def _monte_carlo_simulation(self, my_hand, board, num_opponents, time_limit):
        """
        Symuluje rozdania, aby obliczyć szansę wygranej (Equity).
        Działa na zasadzie: Co by było, gdyby gra potoczyła się do końca 500 razy?
        """
        start = time.time()
        wins = 0
        iterations = 0
        
        # Tworzymy talię bazową (usuwamy znane karty)
        # To jest operacja kosztowna, więc robimy ją raz
        full_deck = Deck.GetFullDeck()
        known_cards = my_hand + board
        # Usuwamy znane karty z talii (inty)
        remaining_deck = [c for c in full_deck if c not in known_cards]

        # Ile kart brakuje na stole?
        cards_to_deal = 5 - len(board)

        # Pętla symulacji
        while True:
            iterations += 1
            
            # Sprawdzamy czas co 100 iteracji, żeby nie marnować CPU na 'time.time()'
            if iterations % 100 == 0:
                if (time.time() - start) > time_limit:
                    break
                # Limit iteracji (dla bezpieczeństwa)
                if iterations > 1000:
                    break

            # 1. Tasujemy resztę talii
            random.shuffle(remaining_deck)
            
            # 2. Dobieramy karty wspólne (jeśli brakuje)
            sim_board = board + remaining_deck[:cards_to_deal]
            
            # 3. Dobieramy karty dla przeciwnika (zakładamy 1 najsilniejszego rywala)
            # Symulacja 'vs Random Hand'
            opp_hand = remaining_deck[cards_to_deal:cards_to_deal+2]
            
            # 4. Ewaluacja
            my_rank = self.evaluator.evaluate(sim_board, my_hand)
            opp_rank = self.evaluator.evaluate(sim_board, opp_hand)
            
            # treys: Im niższy rank, tym lepiej (1 = Royal Flush)
            if my_rank < opp_rank:
                wins += 1
            elif my_rank == opp_rank:
                wins += 0.5 # Remis
        
        if iterations == 0: return 0
        return wins / iterations

    def _estimate_active_players(self, state):
        """Logika szacowania liczby graczy na podstawie puli"""
        # Domyślnie zakładamy 2 (my + jeden rywal)
        estimated = 2
        
        # Faza Pre-Flop
        if len(state.community_cards) == 0:
            bb = 20 # Zakładamy standardowy Big Blind
            initial_pot = 30 # SB + BB
            surplus = state.pot - initial_pot
            if surplus > 0:
                callers = surplus // bb
                estimated = 2 + callers
        
        # Faza Post-Flop (Heurystyka)
        else:
            bb = 20
            if state.pot > bb * 25: estimated = 4
            elif state.pot > bb * 10: estimated = 3
            
        # Zabezpieczenie: nie może być mniej niż 2 i więcej niż 10
        return max(2, min(estimated, 10))

    def _format_hand(self, hand):
        """Pomocnik do Tier Listy (['Ah', 'Ks'] -> 'AKs')"""
        ranks = "23456789TJQKA"
        cards = sorted(hand, key=lambda x: ranks.index(x[0]), reverse=True)
        r1, s1 = cards[0][0], cards[0][1]
        r2, s2 = cards[1][0], cards[1][1]
        suffix = 's' if s1 == s2 else 'o'
        if r1 == r2: return f"{r1}{r2}"
        return f"{r1}{r2}{suffix}"