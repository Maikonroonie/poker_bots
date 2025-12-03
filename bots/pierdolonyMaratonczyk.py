from engine import BaseAgent, Action, ActionType, PlayerState
import random
import time
import math
from collections import deque

# Zabezpieczenie importów
try:
    from treys import Card, Evaluator, Deck
except ImportError:
    pass

class MasterBot(BaseAgent):
    """
    MasterBot v5.0 (Marathon Edition)
    - Zaprojektowany na tysiące rozdań.
    - Adaptywny: Dostosowuje się do agresji stołu (średnia pula).
    - Nieprzewidywalny: Używa strategii mieszanych (Mixed Strategy) z entropią.
    - Odporny: Zarządzanie pamięcią (deque) i ochrona przed 'wykrwawieniem'.
    """
    def __init__(self, name: str):
        super().__init__(name)
        self.evaluator = Evaluator()
        
        # --- ZASOBY ---
        self.FULL_DECK = Deck.GetFullDeck()
        self.SIMULATION_COUNT = 2500 
        self.MC_BATCH = 50

        # --- PAMIĘĆ DŁUGOTERMINOWA (Marathon) ---
        # Śledzimy ostatnie 50 wielkości puli (w BB), żeby ocenić stół
        self.pot_history = deque(maxlen=50)
        self.hands_played = 0
        self.initial_stack = None # Zapiszemy przy pierwszym ruchu

        # --- ZAKRESY BAZOWE ---
        self.range_premium = ['AA', 'KK', 'QQ', 'AKs', 'AKo']
        self.range_strong = self.range_premium + ['JJ', 'TT', '99', 'AQs', 'AJs', 'KQs']
        
        # Zakres do kradzieży (szeroki)
        self.range_steal = self.range_strong + [
            '88','77','66','55','44','33','22',
            'ATs','KJs','QJs','JTs','T9s','98s','87s',
            'AQo','KQo','AJo','KJo','QJo'
        ]

    def act(self, state: PlayerState) -> Action:
        # Inicjalizacja stacka startowego
        if self.initial_stack is None:
            self.initial_stack = state.stack

        start_time = time.time()
        
        try:
            # 1. ANALIZA METADANYCH (ADAPTACJA)
            bb = self._estimate_big_blind(state)
            
            # Aktualizacja historii stołu (tylko jeśli pula jest znacząca)
            if state.pot > bb * 3:
                self.pot_history.append(state.pot / bb)
            
            # Ocena agresji stołu (średnia pula w BB)
            avg_pot_bb = sum(self.pot_history) / len(self.pot_history) if self.pot_history else 5
            
            # Jeśli średnia pula > 15 BB -> Stół jest SZALONY (Maniacy).
            # Kontra: Gramy super bezpiecznie (tylko Premium/Strong).
            is_crazy_table = avg_pot_bb > 15

            # 2. NINJA MODE (Short Stack)
            # Jeśli mamy < 12 BB, włączamy tryb przetrwania
            if state.stack < (bb * 12):
                return self._ninja_strategy(state)
            
            # Jeśli powoli umieramy (mamy < 50% startowego stacka), zwiększamy ryzyko
            is_bleeding_out = state.stack < (self.initial_stack * 0.5)

            # 3. PRE-FLOP
            if len(state.community_cards) == 0:
                return self._play_preflop(state, bb, is_crazy_table, is_bleeding_out)

            # 4. POST-FLOP
            # Czy to River?
            is_river = len(state.community_cards) == 5
            
            # Szybka ocena siły
            static_strength = self._calculate_static_strength(state.hand, state.community_cards)
            
            # Optymalizacja: Jeśli mamy Nuts (1.0) lub River, pomijamy MC
            if is_river or static_strength >= 0.98:
                final_equity = static_strength
                divergence = 0.0
            else:
                # Monte Carlo
                mc_equity = self._calculate_monte_carlo(state.hand, state.community_cards, time_limit=1.5)
                divergence = mc_equity - static_strength
                final_equity = mc_equity
                
                # Jeśli Drawujemy, obniżamy equity (chyba że musimy ryzykować bo is_bleeding_out)
                if divergence > 0.15 and not is_bleeding_out:
                    final_equity *= 0.95

            # --- ENTROPIA I DECYZJA ---
            
            # Dodajemy losowy "szum" do equity (+/- 2%), żeby zmylić boty profilujące
            entropy = random.uniform(-0.02, 0.02)
            perceived_equity = final_equity + entropy

            # Obliczanie EV
            cost_to_call = getattr(state, 'current_bet', 0) or 0
            ev = ((state.pot + cost_to_call) * perceived_equity) - cost_to_call

            # A. Darmowe Czekanie
            if cost_to_call == 0:
                # Jeśli stół jest szalony, częściej czekamy z dobrymi kartami (Trap)
                trap_threshold = 0.8 if is_crazy_table else 0.95
                
                # Betujemy jeśli mamy przewagę
                if perceived_equity > 0.60:
                    # MIXED STRATEGY: 15% szans na Check z silną ręką (Trap)
                    if perceived_equity > trap_threshold and random.random() < 0.15:
                        return Action(ActionType.CHECK_CALL)
                    
                    amount = self._get_dynamic_bet_size(state, perceived_equity)
                    return Action(ActionType.RAISE, amount=min(int(amount), state.stack))
                
                return Action(ActionType.CHECK_CALL)

            # B. Płacenie
            else:
                if ev > 0:
                    # Ochrona przed All-inami
                    # Na szalonym stole pasujemy chętniej na wielkie bety
                    safety_threshold = 0.85 if is_crazy_table else 0.75
                    is_huge_bet = cost_to_call > (state.stack * 0.40)
                    
                    if is_huge_bet and perceived_equity < safety_threshold:
                         return Action(ActionType.FOLD)

                    # Raise (Agresja)
                    if ev > (state.pot * 0.3) and perceived_equity > 0.80:
                        # Na Riverze rzadziej przebijamy bez Nutsów
                        if is_river and perceived_equity < 0.95:
                            return Action(ActionType.CHECK_CALL)
                        
                        dynamic_amt = self._get_dynamic_bet_size(state, perceived_equity)
                        target = max(dynamic_amt, state.min_raise + cost_to_call)
                        return Action(ActionType.RAISE, amount=min(int(target), state.stack))

                    return Action(ActionType.CHECK_CALL)
                
                else:
                    # Bluff Catching / Crying Call
                    # Jeśli stół jest pasywny, a bet jest mały -> Call
                    if cost_to_call < (state.pot * 0.10) and not is_crazy_table:
                        return Action(ActionType.CHECK_CALL)
                    return Action(ActionType.FOLD)

        except Exception:
            return Action(ActionType.CHECK_CALL)

    # ------------------------------------------------------------------
    # STRATEGIE ADAPTYWNE
    # ------------------------------------------------------------------

    def _play_preflop(self, state, bb, is_crazy_table, is_bleeding_out):
        hand_str = self._format_hand(state.hand)
        cost_to_call = getattr(state, 'current_bet', 0) or 0
        
        # 1. Wybór zakresu rąk (Dynamic Range)
        if is_crazy_table:
            # Na wariatów gramy tylko Top 5%
            playable_range = self.range_premium
            # Jeśli 3-bet jest duży, zrzucamy nawet AQ
            if cost_to_call > bb * 10 and hand_str not in ['AA', 'KK', 'QQ', 'AKs']:
                return Action(ActionType.FOLD)
        elif is_bleeding_out:
            # Jak przegrywamy, gramy szeroko (desperacja/zmienność)
            playable_range = self.range_steal
        else:
            # Normalna gra - zależy czy ktoś podbił
            is_raised = state.pot > (bb * 3.5)
            playable_range = self.range_strong if is_raised else self.range_steal

        # 2. Decyzja
        if self._match_hand(hand_str, playable_range):
            # Jeśli mamy kartę z zakresu...
            
            # Premium zawsze przebijamy
            if self._match_hand(hand_str, self.range_premium):
                amt = max(state.min_raise * 3, state.pot)
                return Action(ActionType.RAISE, amount=int(min(amt, state.stack)))
            
            # Reszta: Mixed Strategy (90% Raise, 10% Call/Trap)
            if random.random() < 0.90:
                amt = state.min_raise * 2.5
                return Action(ActionType.RAISE, amount=int(min(amt, state.stack)))
            else:
                return Action(ActionType.CHECK_CALL)

        # 3. Kradzież z pozycji (jeśli tanio i mamy 's')
        if cost_to_call <= (state.stack * 0.02) and hand_str.endswith('s'):
             return Action(ActionType.CHECK_CALL)

        return Action(ActionType.FOLD)

    def _ninja_strategy(self, state: PlayerState) -> Action:
        # Push/Fold - uproszczony Nash
        hand_str = self._format_hand(state.hand)
        
        should_push = (
            hand_str[0] == hand_str[1] or # Pary
            'A' in hand_str[:2] or        # Asy
            (hand_str[0] in 'KQJ' and hand_str[1] in 'KQJ') # Figury
        )
        
        if should_push:
            return Action(ActionType.RAISE, amount=state.stack)
        
        if (getattr(state, 'current_bet', 0) or 0) > 0:
            return Action(ActionType.FOLD)
        return Action(ActionType.CHECK_CALL)

    # ------------------------------------------------------------------
    # CORE CALCS
    # ------------------------------------------------------------------

    def _calculate_monte_carlo(self, hand_strs, board_strs, time_limit):
        start = time.time()
        my_hand = [Card.new(c) for c in hand_strs]
        board = [Card.new(c) for c in board_strs]
        
        known_mask = set(my_hand + board)
        stub_deck = [c for c in self.FULL_DECK if c not in known_mask]
        
        wins, splits, executed = 0, 0, 0
        cards_to_deal = 5 - len(board)
        eval_func = self.evaluator.evaluate
        sample_func = random.sample

        for i in range(self.SIMULATION_COUNT):
            if (i % self.MC_BATCH) == 0:
                if (time.time() - start) > time_limit: break
            
            drawn = sample_func(stub_deck, 2 + cards_to_deal)
            opp_hand = drawn[:2]
            sim_board = board + drawn[2:]

            my_r = eval_func(sim_board, my_hand)
            opp_r = eval_func(sim_board, opp_hand)

            if my_r < opp_r: wins += 1
            elif my_r == opp_r: splits += 1
            executed += 1

        if executed == 0: return 0.5
        return (wins + splits * 0.5) / executed

    def _calculate_static_strength(self, hand_strs, board_strs):
        my_hand = [Card.new(c) for c in hand_strs]
        board = [Card.new(c) for c in board_strs]
        rank = self.evaluator.evaluate(board, my_hand)
        return 1.0 - (rank / 7462.0)

    def _get_dynamic_bet_size(self, state, equity):
        # Texture check
        board = state.community_cards
        is_wet = False
        if len(board) >= 3:
            suits = [c[1] for c in board]
            if any(suits.count(s) >= 3 for s in set(suits)): is_wet = True
        
        # Randomizacja wielkości betu (żeby nie być czytelnym)
        variation = random.uniform(0.9, 1.1)
        
        multiplier = 0.55
        if equity > 0.90: multiplier = 0.75 if is_wet else 0.40 
        elif equity > 0.80: multiplier = 0.80 if is_wet else 0.65
        elif equity > 0.65: multiplier = 0.60
        
        bet = int(state.pot * multiplier * variation)
        return max(bet, state.min_raise)

    # ------------------------------------------------------------------
    # UTILS
    # ------------------------------------------------------------------

    def _estimate_big_blind(self, state):
        bb = getattr(state, 'big_blind', None)
        if bb: return int(bb)
        if state.pot and state.pot > 0:
            return max(1, int(state.pot / 1.5))
        return 20

    def _format_hand(self, hand):
        ranks = "23456789TJQKA"
        cards = sorted(hand, key=lambda x: ranks.index(x[0]), reverse=True)
        r1, s1 = cards[0][0], cards[0][1]
        r2, s2 = cards[1][0], cards[1][1]
        if r1 == r2: return f"{r1}{r2}"
        suffix = 's' if s1 == s2 else 'o'
        return f"{r1}{r2}{suffix}"

    def _match_hand(self, hand_str, range_list):
        if hand_str in range_list: return True
        rank = hand_str[:2]
        for r in range_list:
            if r == rank: return True
            if len(r) == 3 and r[:2] == rank and r[2] == hand_str[2]: return True
        return False