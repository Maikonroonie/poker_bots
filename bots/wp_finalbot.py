from engine import BaseAgent, Action, ActionType, PlayerState
from treys import Card, Evaluator, Deck
import random
import time

class MasterBot(BaseAgent):
    """
    Finalna wersja bota turniejowego (Team Edition).
    Cechy:
    - Monte Carlo z limitem czasu (Safety First)
    - Dynamic Bet Sizing (czytanie tekstury stołu)
    - Sklansky Dollars (EV Decision Making)
    """
    def __init__(self, name: str):
        super().__init__(name)
        self.evaluator = Evaluator()
        self.SIMULATION_COUNT = 1000  # Próbujemy zrobić 1000, ale zegar nas pilnuje
        
        # Lista rąk, z którymi gramy agresywnie pre-flop
        self.strong_hands = [
            'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88',       # Pary
            'AKs', 'AQs', 'KQs', 'AJs', 'ATs', 'KJs', 'QJs', # Figury w kolorze
            'AKo', 'AQo', 'KQo', 'AJo'                      # Mocne figury offsuit
        ]

    def act(self, state: PlayerState) -> Action:
        start_time = time.time()
        
        try:
            # --- FAZA 1: PRE-FLOP ---
            if len(state.community_cards) == 0:
                return self._play_preflop(state)

            # --- FAZA 2: POST-FLOP ---
            
            # A. Obliczenia (z limitem czasu 2.0s na Monte Carlo)
            mc_equity = self._calculate_monte_carlo(state.hand, state.community_cards, time_limit=2.0)
            static_strength = self._calculate_static_strength(state.hand, state.community_cards)

            # B. Analiza Drawów (Dywergencja)
            # Jeśli MC > Static, to znaczy, że gonimy wynik (mamy Draw)
            divergence = mc_equity - static_strength
            final_equity = mc_equity

            if divergence > 0.15:
                # Obniżamy lekko equity (podatek od ryzyka), bo draw może nie wejść
                final_equity = mc_equity * 0.95 

            # C. Matematyka EV (Sklansky Dollars)
            cost_to_call = state.current_bet
            total_pot_after_call = state.pot + cost_to_call
            
            # EV = (Potencjalna wygrana * Szansa) - Koszt
            ev = (total_pot_after_call * final_equity) - cost_to_call

            # --- FAZA 3: DECYZJA ---

            # SCENARIUSZ A: Możemy czekać (Check)
            if cost_to_call == 0:
                # Jeśli mamy przewagę (>60%) lub mocny draw -> Betujemy
                if final_equity > 0.6 or (divergence > 0.2 and final_equity > 0.4):
                    amount = self._get_dynamic_bet_size(state, final_equity)
                    return Action(ActionType.RAISE, amount=int(amount))
                return Action(ActionType.CHECK_CALL)

            # SCENARIUSZ B: Musimy płacić (Call vs Fold vs Raise)
            else:
                if ev > 0:
                    # FIX: Ochrona przed All-inami
                    is_huge_bet = cost_to_call > state.stack * 0.35
                    
                    # Jeśli rywal wrzuca >35% naszego stacka, sprawdzamy tylko z silną ręką (>80%)
                    if is_huge_bet and final_equity < 0.80:
                        return Action(ActionType.FOLD)
                    
                    # Jeśli mamy bardzo dużą przewagę -> Przebijamy (Raise)
                    if ev > state.pot * 0.2 and final_equity > 0.75:
                         dynamic_amount = self._get_dynamic_bet_size(state, final_equity)
                         # Raise to min. 2x tego co rywal zagrał
                         target_raise = max(dynamic_amount, state.min_raise + cost_to_call)
                         # Cap na stack (nie więcej niż mamy)
                         target_raise = min(target_raise, state.stack)
                         
                         return Action(ActionType.RAISE, amount=int(target_raise))
                    
                    # Standardowy Call (opłacalny matematycznie)
                    return Action(ActionType.CHECK_CALL)
                
                else:
                    # Ujemne EV -> Fold
                    # Wyjątek: Crying Call (jeśli bardzo tanio, np. 1 BB do wielkiej puli)
                    if cost_to_call < state.stack * 0.05 and cost_to_call < state.pot * 0.1:
                        return Action(ActionType.CHECK_CALL)
                    
                    return Action(ActionType.FOLD)

        except Exception as e:
            # SAFETY NET: W razie błędu gramy bezpiecznie Check/Call
            # print(f"CRITICAL ERROR: {e}") 
            return Action(ActionType.CHECK_CALL)

    # --- METODY POMOCNICZE ---

    def _play_preflop(self, state: PlayerState) -> Action:
        """Strategia Pre-flop: Tight-Aggressive"""
        hand_str = self._format_hand(state.hand)

        if hand_str in self.strong_hands:
            # Raise 3x MinRaise (agresywnie)
            amt = state.min_raise * 3
            return Action(ActionType.RAISE, amount=int(amt))
        
        # Jeśli tanio (Big Blind lub mały bet), wchodzimy spekulacyjnie
        if state.current_bet <= state.stack * 0.02:
            return Action(ActionType.CHECK_CALL)
            
        return Action(ActionType.FOLD)

    def _calculate_monte_carlo(self, hand_strs, board_strs, time_limit):
        """Symulacja z limitem czasu (Time-Aware Monte Carlo)"""
        start = time.time()
        
        my_hand = [Card.new(c) for c in hand_strs]
        board = [Card.new(c) for c in board_strs]

        # Tworzenie talii bez znanych kart
        deck = Deck()
        known_cards = set(my_hand + board)
        # Szybka filtracja (list comprehension jest szybsze niż pętla remove)
        stub_deck = [c for c in deck.cards if c not in known_cards]
        
        wins = 0
        splits = 0
        cards_to_deal = 5 - len(board)
        executed_sims = 0

        for i in range(self.SIMULATION_COUNT):
            # Co 50 iteracji sprawdzamy zegar (narzut time.time() jest spory)
            if i % 50 == 0:
                if (time.time() - start) > time_limit:
                    break
            
            # Losowanie kart
            needed = 2 + cards_to_deal
            drawn = random.sample(stub_deck, needed)
            
            opp_hand = drawn[:2]
            sim_board = board + drawn[2:]

            # Ewaluacja (Treys: mniejszy wynik = lepszy)
            my_rank = self.evaluator.evaluate(sim_board, my_hand)
            opp_rank = self.evaluator.evaluate(sim_board, opp_hand)

            if my_rank < opp_rank:
                wins += 1
            elif my_rank == opp_rank:
                splits += 1
            
            executed_sims += 1

        if executed_sims == 0: return 0.5 # Fallback
        return (wins + (splits * 0.5)) / executed_sims

    def _calculate_static_strength(self, hand_strs, board_strs):
        """Ocena siły 'tu i teraz'"""
        my_hand = [Card.new(c) for c in hand_strs]
        board = [Card.new(c) for c in board_strs]
        rank = self.evaluator.evaluate(board, my_hand)
        return 1.0 - (rank / 7462.0)

    def _analyze_board_texture(self, board_strs):
        """Ocena niebezpieczeństwa stołu (0.0 - 1.0)"""
        ranks = [c[0] for c in board_strs]
        suits = [c[1] for c in board_strs]
        danger = 0.0
        
        # Kolor (Flush draw)
        suit_counts = {s: suits.count(s) for s in set(suits)}
        if max(suit_counts.values()) >= 3: danger += 0.4
        
        # Strit (prostym sposobem: bliskość rang)
        rank_indices = sorted(['23456789TJQKA'.index(r) for r in ranks])
        gaps = 0
        for i in range(len(rank_indices)-1):
            if rank_indices[i+1] - rank_indices[i] == 1:
                gaps += 1
        if gaps >= 2: danger += 0.3

        return min(danger, 1.0)

    def _get_dynamic_bet_size(self, state, equity):
        """Dostosowanie zakładu do sytuacji"""
        texture = self._analyze_board_texture(state.community_cards)
        
        # Mnożnik puli (od 0.5 do 1.2)
        multiplier = 0.6 # Standard
        
        if equity > 0.85: # Bardzo silna
            # Na mokrym stole walimy mocno, żeby nie dobrali
            if texture > 0.3: multiplier = 1.0
            # Na suchym stole pułapka (mały bet)
            else: multiplier = 0.4
        elif equity > 0.7:
            multiplier = 0.7 + (texture * 0.2)
            
        bet = int(state.pot * multiplier)
        # Bet musi być co najmniej min_raise
        return max(bet, state.min_raise)

    def _format_hand(self, hand):
        """Formatowanie kart do stringa (['Ah', 'Ks'] -> 'AKs')"""
        ranks_order = "23456789TJQKA"
        cards = sorted(hand, key=lambda x: ranks_order.index(x[0]), reverse=True)
        
        r1, s1 = cards[0][0], cards[0][1]
        r2, s2 = cards[1][0], cards[1][1]
        
        suffix = 's' if s1 == s2 else 'o'
        if r1 == r2: return f"{r1}{r2}"
        return f"{r1}{r2}{suffix}"