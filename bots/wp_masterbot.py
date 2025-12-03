from engine import BaseAgent, Action, ActionType, PlayerState
from treys import Card, Evaluator, Deck
import random
import time

class MasterBot(BaseAgent):
    """
    MasterBot v2.0 (Terminator Edition)
    Ulepszenia:
    1. Ninja Module (Push/Fold Logic dla Short Stacka)
    2. Position Awareness (Luźniejsza gra na późnej pozycji)
    3. River Optimization (Zero MC na końcu gry)
    """
    def __init__(self, name: str):
        super().__init__(name)
        self.evaluator = Evaluator()
        self.SIMULATION_COUNT = 1000
        
        # --- KONFIGURACJA STRATEGII ---
        
        # 1. Ręce na wczesną pozycję (Gramy tylko TOP)
        self.range_tight = [
            'AA', 'KK', 'QQ', 'JJ', 'TT', 'AKs', 'AKo', 'AQs', 'AJs'
        ]
        
        # 2. Ręce na późną pozycję (Gramy szerzej, kradniemy blindy)
        self.range_loose = self.range_tight + [
            '99', '88', '77', '66', '55',           # Niskie pary
            'ATs', 'KQs', 'KJs', 'QJs', 'JTs',      # Figury w kolorze
            'AQo', 'KQo', 'AJo', 'KJo',             # Figury offsuit
            'T9s', '98s', '87s'                     # Suited Connectors (do stritów)
        ]

    def act(self, state: PlayerState) -> Action:
        start_time = time.time()
        
        try:
            # ---------------------------------------------------------
            # MODUŁ 1: NINJA (Survival Mode)
            # Jeśli mamy mniej niż 12 Big Blindów, włączamy tryb przetrwania
            # ---------------------------------------------------------
            bb_estimate = 20 # Zakładamy BB = 20
            if state.stack < (bb_estimate * 12):
                return self._ninja_strategy(state)

            # ---------------------------------------------------------
            # MODUŁ 2: PRE-FLOP (Z uwzględnieniem pozycji)
            # ---------------------------------------------------------
            if len(state.community_cards) == 0:
                return self._play_preflop(state)

            # ---------------------------------------------------------
            # MODUŁ 3: POST-FLOP (Analiza i Matematyka)
            # ---------------------------------------------------------
            
            # Optymalizacja River: Jeśli to koniec gry, nie robimy Monte Carlo
            is_river = len(state.community_cards) == 5
            
            if is_river:
                # Na Riverze liczy się tylko: czy mam najlepszą rękę teraz?
                # Equity to 1.0 (wygrana) lub 0.0 (przegrana) w symulacji, 
                # więc tutaj używamy Static Strength jako Equity.
                final_equity = self._calculate_static_strength(state.hand, state.community_cards)
                divergence = 0 # Nie ma już drawów na riverze
            else:
                # Flop/Turn -> Monte Carlo
                mc_equity = self._calculate_monte_carlo(state.hand, state.community_cards, time_limit=2.0)
                static_strength = self._calculate_static_strength(state.hand, state.community_cards)
                
                # Analiza Drawów
                divergence = mc_equity - static_strength
                final_equity = mc_equity
                
                # Kara za ryzyko (jeśli gonimy wynik)
                if divergence > 0.15:
                    final_equity = mc_equity * 0.95

            # Sklansky Dollars (EV)
            cost_to_call = state.current_bet
            total_pot = state.pot + cost_to_call
            ev = (total_pot * final_equity) - cost_to_call

            # --- DECYZJA ---

            # A. Darmowe czekanie
            if cost_to_call == 0:
                # Value Bet (mamy dobrą rękę) lub Semi-Bluff (mamy mocny draw)
                if final_equity > 0.65 or (divergence > 0.2 and final_equity > 0.45):
                    amount = self._get_dynamic_bet_size(state, final_equity)
                    return Action(ActionType.RAISE, amount=int(amount))
                return Action(ActionType.CHECK_CALL)

            # B. Płatna decyzja
            else:
                if ev > 0:
                    # Ochrona przed All-inami (chyba że Ninja Mode już nas nie dotyczy)
                    is_huge_bet = cost_to_call > state.stack * 0.40
                    
                    # Jeśli rywal zagrywa za pół naszego stacka, musimy być pewni
                    if is_huge_bet and final_equity < 0.75:
                        return Action(ActionType.FOLD)
                    
                    # Agresja: Jeśli EV jest bardzo wysokie -> Przebijamy
                    if ev > state.pot * 0.25 and final_equity > 0.8:
                         # Ale nie na Riverze, jeśli mamy tylko "ok" rękę (nie nuts)
                         if is_river and final_equity < 0.95:
                             return Action(ActionType.CHECK_CALL)

                         dynamic_amount = self._get_dynamic_bet_size(state, final_equity)
                         target = max(dynamic_amount, state.min_raise + cost_to_call)
                         # Cap na stack
                         target = min(target, state.stack)
                         return Action(ActionType.RAISE, amount=int(target))
                    
                    return Action(ActionType.CHECK_CALL)
                
                else:
                    # Crying Call (bardzo tanio sprawdzamy)
                    if cost_to_call < state.pot * 0.08:
                        return Action(ActionType.CHECK_CALL)
                    return Action(ActionType.FOLD)

        except Exception:
            return Action(ActionType.CHECK_CALL)

    # ---------------------------------------------------------
    # METODY LOGICZNE
    # ---------------------------------------------------------

    def _ninja_strategy(self, state: PlayerState) -> Action:
        """
        Push or Fold Strategy (Tabela Nasha dla Short Stacka).
        Gdy mamy mało żetonów, nie bawimy się w "Call".
        """
        hand_str = self._format_hand(state.hand)
        
        # Definicja rąk, z którymi wchodzimy ALL-IN będąc na skraju śmierci
        # 1. Każda Para
        is_pair = hand_str[0] == hand_str[1]
        # 2. Każdy As
        has_ace = 'A' in hand_str
        # 3. Silne figury (KQ, KJ, QJ)
        high_cards = hand_str[0] in 'KQJ' and hand_str[1] in 'KQJ'
        
        should_push = is_pair or has_ace or high_cards
        
        if should_push:
            # ALL-IN!
            return Action(ActionType.RAISE, amount=state.stack)
        
        # Jeśli ręka słaba, a musimy zapłacić -> FOLD
        if state.current_bet > 0:
            # Chyba że to my jesteśmy na Big Blindzie i mamy Check za darmo
            if state.current_bet <= 0: return Action(ActionType.CHECK_CALL)
            return Action(ActionType.FOLD)
            
        return Action(ActionType.CHECK_CALL)

    def _play_preflop(self, state: PlayerState) -> Action:
        """
        Pre-flop z uwzględnieniem "wirtualnej pozycji".
        """
        hand_str = self._format_hand(state.hand)
        
        # Heurystyka pozycji:
        # Jeśli pula jest mała (tylko blindy), to jesteśmy 'wcześnie' lub nikt nie grał.
        # Jeśli pula jest podbita, gramy ostrożniej.
        
        bb = 20 # assumption
        is_raised_pot = state.pot > (bb * 3.5)
        
        # Wybór tabeli
        if is_raised_pot:
            # Ktoś podbił -> Gramy wąsko (Tight)
            playable_hands = self.range_tight
        else:
            # Pula niepodbita -> Możemy kraść blindy (Loose)
            playable_hands = self.range_loose

        # Sprawdzenie ręki
        is_playable = False
        if hand_str in playable_hands: is_playable = True
        # Obsługa 's'/'o' (jeśli w tabeli jest AKs, a my mamy AKs, to ok)
        if not is_playable and len(hand_str) == 3:
             if hand_str[:2] in playable_hands: is_playable = True

        if is_playable:
            # Jeśli ręka jest z listy Tight (Premium), przebijamy mocno
            if hand_str in self.range_tight or hand_str[:2] in self.range_tight:
                amt = max(state.min_raise * 3, state.pot)
                return Action(ActionType.RAISE, amount=int(amt))
            
            # Jeśli ręka jest z listy Loose (Speculative), podbijamy standardowo
            amt = state.min_raise * 2.5
            return Action(ActionType.RAISE, amount=int(amt))
        
        # Tanie wejście spekulacyjne (tylko jeśli tanio i suited)
        if state.current_bet <= state.stack * 0.02 and 's' in hand_str:
            return Action(ActionType.CHECK_CALL)
            
        return Action(ActionType.FOLD)

    # ---------------------------------------------------------
    # METODY OBLICZENIOWE (Te same co wcześniej, ale zoptymalizowane)
    # ---------------------------------------------------------

    def _calculate_monte_carlo(self, hand_strs, board_strs, time_limit):
        start = time.time()
        my_hand = [Card.new(c) for c in hand_strs]
        board = [Card.new(c) for c in board_strs]
        deck = Deck()
        known_cards = set(my_hand + board)
        stub_deck = [c for c in deck.cards if c not in known_cards]
        
        wins = 0
        splits = 0
        cards_to_deal = 5 - len(board)
        executed_sims = 0

        for i in range(self.SIMULATION_COUNT):
            if i % 50 == 0:
                if (time.time() - start) > time_limit: break
            
            needed = 2 + cards_to_deal
            drawn = random.sample(stub_deck, needed)
            opp_hand = drawn[:2]
            sim_board = board + drawn[2:]

            my_rank = self.evaluator.evaluate(sim_board, my_hand)
            opp_rank = self.evaluator.evaluate(sim_board, opp_hand)

            if my_rank < opp_rank: wins += 1
            elif my_rank == opp_rank: splits += 1
            executed_sims += 1

        if executed_sims == 0: return 0.5
        return (wins + (splits * 0.5)) / executed_sims

    def _calculate_static_strength(self, hand_strs, board_strs):
        my_hand = [Card.new(c) for c in hand_strs]
        board = [Card.new(c) for c in board_strs]
        rank = self.evaluator.evaluate(board, my_hand)
        return 1.0 - (rank / 7462.0)

    def _get_dynamic_bet_size(self, state, equity):
        # Prosta analiza tekstury dla bet size
        is_wet_board = False
        board = state.community_cards
        if len(board) >= 3:
            suits = [c[1] for c in board]
            if max(suits.count(s) for s in set(suits)) >= 2: is_wet_board = True
        
        multiplier = 0.6
        if equity > 0.85: multiplier = 0.8 if is_wet_board else 0.4 # Trap na suchym
        elif equity > 0.7: multiplier = 0.75
        
        bet = int(state.pot * multiplier)
        return max(bet, state.min_raise)

    def _format_hand(self, hand):
        ranks_order = "23456789TJQKA"
        cards = sorted(hand, key=lambda x: ranks_order.index(x[0]), reverse=True)
        r1, s1 = cards[0][0], cards[0][1]
        r2, s2 = cards[1][0], cards[1][1]
        suffix = 's' if s1 == s2 else 'o'
        if r1 == r2: return f"{r1}{r2}"
        return f"{r1}{r2}{suffix}"