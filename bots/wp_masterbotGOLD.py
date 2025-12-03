from engine import BaseAgent, Action, ActionType, PlayerState
# Zabezpieczenie na wypadek problemów z importem treys na serwerze
try:
    from treys import Card, Evaluator, Deck
except ImportError:
    # Fallback - to nie powinno się wydarzyć, ale ratuje przed dyskwalifikacją
    pass

import random
import time
import math
from typing import List

class MasterBot(BaseAgent):
    """
    MasterBot v3.1 (Gold Edition)
    - Naprawiony wzór EV (nie folduje opłacalnych drawów)
    - Zoptymalizowane Monte Carlo (batching)
    - Inteligentne wykrywanie BB
    - Tryb Ninja (Push/Fold)
    """
    def __init__(self, name: str):
        super().__init__(name)
        self.evaluator = Evaluator()
        self.SIMULATION_COUNT = 2000
        self.MC_BATCH = 50 # Sprawdzamy czas co 50 symulacji (oszczędność CPU)

        # Definicje zakresów (Ranges)
        self.range_tight = [
            'AA', 'KK', 'QQ', 'JJ', 'TT', 'AKs', 'AKo', 'AQs', 'AJs'
        ]

        self.range_loose = self.range_tight + [
            '99', '88', '77', '66', '55',
            'ATs', 'KQs', 'KJs', 'QJs', 'JTs',
            'AQo', 'KQo', 'AJo', 'KJo',
            'T9s', '98s', '87s'
        ]

    def act(self, state: PlayerState) -> Action:
        start_time = time.time()
        try:
            # 1. Szacowanie stawek (Blindów)
            bb_estimate = self._estimate_big_blind(state)

            # 2. NINJA MODE (Short Stack Strategy)
            # Jeśli mamy mniej niż 12 BB, włączamy tryb przetrwania (Push or Fold)
            if state.stack < (bb_estimate * 12):
                return self._ninja_strategy(state)

            # 3. PRE-FLOP
            if len(state.community_cards) == 0:
                return self._play_preflop(state, bb_estimate)

            # 4. POST-FLOP
            # Czy to ostatnia runda (River)?
            is_river = len(state.community_cards) == 5

            if is_river:
                # Na Riverze nie ma Monte Carlo (brak przyszłości), liczymy siłę tu i teraz
                final_equity = self._calculate_static_strength(state.hand, state.community_cards)
                divergence = 0.0
            else:
                # Flop/Turn -> Monte Carlo z limitem 1.5 sekundy
                mc_equity = self._calculate_monte_carlo(state.hand, state.community_cards, time_limit=1.5)
                static_strength = self._calculate_static_strength(state.hand, state.community_cards)
                
                # Divergence: Różnica między potencjałem (MC) a stanem obecnym (Static)
                divergence = mc_equity - static_strength
                final_equity = mc_equity
                
                # Jeśli mocno gonimy wynik (Draw), lekko obniżamy pewność (podatek od ryzyka)
                if divergence > 0.15:
                    final_equity = mc_equity * 0.95

            # --- MATEMATYKA EV (Poprawiona) ---
            # Pobieramy koszt sprawdzenia (bezpiecznie)
            cost_to_call = getattr(state, 'current_bet', 0) or 0
            
            # Wzór: (Pula po sprawdzeniu * Szansa wygranej) - Koszt inwestycji
            total_pot = state.pot + cost_to_call
            ev = (total_pot * final_equity) - cost_to_call

            # --- DECYZJA ---
            
            # A. Czy możemy czekać za darmo? (Check)
            if cost_to_call == 0:
                # Value Bet (mamy przewagę) lub Semi-Bluff (mamy draw)
                if final_equity > 0.65 or (divergence > 0.2 and final_equity > 0.45):
                    amount = self._get_dynamic_bet_size(state, final_equity)
                    # Nie betujemy więcej niż mamy
                    return Action(ActionType.RAISE, amount=int(min(amount, state.stack)))
                return Action(ActionType.CHECK_CALL)

            # B. Musimy płacić (Call/Raise/Fold)
            else:
                if ev > 0:
                    # 1. Ochrona przed All-inami
                    # Jeśli rywal zagrywa za >40% naszego stacka, sprawdzamy tylko z topem
                    is_huge_bet = cost_to_call > (state.stack * 0.40)
                    if is_huge_bet and final_equity < 0.75:
                        return Action(ActionType.FOLD)

                    # 2. Agresja (Raise)
                    # Jeśli EV jest wysokie i mamy silną rękę
                    if ev > (state.pot * 0.25) and final_equity > 0.80:
                        # Na Riverze gramy ostrożniej (tylko Call, chyba że mamy Nuts)
                        if is_river and final_equity < 0.95:
                            return Action(ActionType.CHECK_CALL)
                        
                        dynamic_amount = self._get_dynamic_bet_size(state, final_equity)
                        target = max(dynamic_amount, state.min_raise + cost_to_call)
                        target = min(target, state.stack)
                        return Action(ActionType.RAISE, amount=int(target))

                    # 3. Standardowy Call (opłacalny)
                    return Action(ActionType.CHECK_CALL)
                
                else:
                    # Ujemne EV -> Fold
                    # Wyjątek: Crying Call (bardzo tanio, np. < 8% puli)
                    if cost_to_call < state.pot * 0.08:
                        return Action(ActionType.CHECK_CALL)
                    return Action(ActionType.FOLD)

        except Exception as e:
            # SAFETY NET: W razie błędu gramy bezpiecznie Check/Call
            try:
                # Opcjonalnie: print(f"[Bot Error] {e}")
                pass
            except:
                pass
            return Action(ActionType.CHECK_CALL)

    # -------------------------
    # STRATEGIE POMOCNICZE
    # -------------------------
    
    def _ninja_strategy(self, state: PlayerState) -> Action:
        """Strategia Push-or-Fold dla małego stacka."""
        hand_str = self._format_hand(state.hand)
        
        is_pair = hand_str[0] == hand_str[1]
        has_ace = 'A' in hand_str[:2]
        high_cards = hand_str[0] in 'KQJ' and hand_str[1] in 'KQJ'
        
        # Wchodzimy ALL-IN z parą, asem lub figurami
        if is_pair or has_ace or high_cards:
            return Action(ActionType.RAISE, amount=state.stack)

        # Jeśli musimy płacić, a nie mamy ręki -> Fold
        if state.current_bet and state.current_bet > 0:
            return Action(ActionType.FOLD)

        return Action(ActionType.CHECK_CALL)

    def _play_preflop(self, state: PlayerState, bb_estimate: int) -> Action:
        hand_str = self._format_hand(state.hand)
        
        # Heurystyka: Czy pula jest podbita? (Raised Pot)
        is_raised_pot = state.pot > (bb_estimate * 3.5)
        playable_hands = self.range_tight if is_raised_pot else self.range_loose

        if self._match_hand(hand_str, playable_hands):
            # Jeśli mamy Premium Hand -> Mocny Raise
            if self._match_hand(hand_str, self.range_tight):
                amt = max(state.min_raise * 3, state.pot)
                return Action(ActionType.RAISE, amount=int(min(amt, state.stack)))
            
            # Standardowy Raise
            amt = int(state.min_raise * 2.5)
            return Action(ActionType.RAISE, amount=int(min(amt, state.stack)))

        # Tanie wejście spekulacyjne (tylko suited)
        current_bet = getattr(state, 'current_bet', 0)
        if current_bet <= state.stack * 0.02 and hand_str.endswith('s'):
            return Action(ActionType.CHECK_CALL)

        return Action(ActionType.FOLD)

    # -------------------------
    # OBLICZENIA (Monte Carlo & Texture)
    # -------------------------

    def _calculate_monte_carlo(self, hand_strs, board_strs, time_limit):
        start = time.time()
        my_hand = [Card.new(c) for c in hand_strs]
        board = [Card.new(c) for c in board_strs]
        deck = Deck()
        
        # Optymalizacja: Set lookup jest O(1)
        known = set(my_hand + board)
        stub_deck = [c for c in deck.cards if c not in known]

        wins = 0
        splits = 0
        executed = 0
        cards_to_deal = 5 - len(board)

        for i in range(self.SIMULATION_COUNT):
            # Batching: sprawdzamy czas co 50 iteracji
            if (i % self.MC_BATCH) == 0:
                if (time.time() - start) > time_limit:
                    break

            needed = 2 + cards_to_deal
            drawn = random.sample(stub_deck, needed)
            opp_hand = drawn[:2]
            sim_board = board + drawn[2:]

            my_rank = self.evaluator.evaluate(sim_board, my_hand)
            opp_rank = self.evaluator.evaluate(sim_board, opp_hand)

            if my_rank < opp_rank:
                wins += 1
            elif my_rank == opp_rank:
                splits += 1
            executed += 1

        if executed == 0: return 0.5
        return (wins + splits * 0.5) / executed

    def _calculate_static_strength(self, hand_strs, board_strs):
        my_hand = [Card.new(c) for c in hand_strs]
        board = [Card.new(c) for c in board_strs]
        rank = self.evaluator.evaluate(board, my_hand)
        return 1.0 - (rank / 7462.0)

    def _get_dynamic_bet_size(self, state, equity):
        is_wet = self._is_wet_board(state.community_cards)
        multiplier = 0.6

        if equity > 0.85:
            multiplier = 0.8 if is_wet else 0.45 # Trap na suchym stole
        elif equity > 0.7:
            multiplier = 0.75
        elif equity > 0.55:
            multiplier = 0.6
        else:
            multiplier = 0.4

        bet = int(state.pot * multiplier)
        return max(bet, state.min_raise)

    def _is_wet_board(self, board_strs) -> bool:
        """Wykrywa niebezpieczny stół (kolor, strit, pary)."""
        if len(board_strs) < 3: return False
        
        ranks = [c[0] for c in board_strs]
        suits = [c[1] for c in board_strs]
        
        # 1. Flush draw (3+ karty w kolorze)
        flush_danger = any(suits.count(s) >= 3 for s in set(suits))
        
        # 2. Sparowany stół (Full House danger)
        pair_danger = len(set(ranks)) < len(ranks)
        
        # 3. Straight danger (uproszczony)
        # Sprawdzamy czy są 3 karty blisko siebie (np. 5, 6, 8)
        rank_indices = sorted(['23456789TJQKA'.index(r) for r in set(ranks)])
        straight_danger = False
        for i in range(len(rank_indices) - 2):
            if rank_indices[i+2] - rank_indices[i] <= 4:
                straight_danger = True
                break

        # Stół jest "mokry", jeśli spełnia 2 z 3 warunków lub ma flush draw
        return flush_danger or (pair_danger and straight_danger)

    def _estimate_big_blind(self, state):
        """Szacuje BB na podstawie puli, jeśli silnik nie podaje."""
        bb = getattr(state, 'big_blind', None)
        if bb: return int(bb)
        
        # Fallback: W pre-flopie pula to zazwyczaj 1.5 BB (SB+BB)
        if state.pot and state.pot > 0:
            return max(1, int(state.pot / 1.5))
        return 20

    def _format_hand(self, hand):
        ranks_order = "23456789TJQKA"
        cards = sorted(hand, key=lambda x: ranks_order.index(x[0]), reverse=True)
        r1, s1 = cards[0][0], cards[0][1]
        r2, s2 = cards[1][0], cards[1][1]
        if r1 == r2: return f"{r1}{r2}"
        suffix = 's' if s1 == s2 else 'o'
        return f"{r1}{r2}{suffix}"

    def _match_hand(self, hand_str, range_list):
        if hand_str in range_list: return True
        rank = hand_str[:2]
        for r in range_list:
            if r == rank: return True # Np. 'AK' pasuje do 'AKs' i 'AKo'
            if len(r) == 3 and r[:2] == rank and r[2] == hand_str[2]: return True
        return False