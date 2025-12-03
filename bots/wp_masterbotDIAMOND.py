from engine import BaseAgent, Action, ActionType, PlayerState
import random
import time
import math
from typing import List, Set

# --- IMPORTY Z ZABEZPIECZENIEM ---
try:
    from treys import Card, Evaluator, Deck
except ImportError:
    pass

class MasterBot(BaseAgent):
    """
    MasterBot v4.0 (Diamond Edition)
    - Turbo Monte Carlo (operacje na setach intów, bez instancjonowania Deck)
    - Crisis Management (inteligentne zrzucanie średnich par przy All-inach)
    - Nuts Detection (maksymalizacja zysku z układem nie do pobicia)
    - Poprawiony Ninja Mode i logika EV
    """
    def __init__(self, name: str):
        super().__init__(name)
        self.evaluator = Evaluator()
        
        # OPTYMALIZACJA: Generujemy pełną talię raz, jako listę intów
        # To drastycznie przyspiesza Monte Carlo
        self.FULL_DECK = Deck.GetFullDeck()
        
        self.SIMULATION_COUNT = 3000 # Możemy pozwolić sobie na więcej dzięki optymalizacji
        self.MC_BATCH = 100 

        # --- ZAKRESY (RANGES) ---
        # 1. Super Premium (Do gry o stacka pre-flop)
        self.range_premium = ['AA', 'KK', 'QQ', 'AKs', 'AKo']

        # 2. Tight (Do otwierania z wczesnej pozycji lub sprawdzania przebić)
        self.range_tight = self.range_premium + [
            'JJ', 'TT', '99', 'AQs', 'AJs', 'KQs'
        ]

        # 3. Loose (Do kradzieży blindów i gry pozycyjnej)
        self.range_loose = self.range_tight + [
            '88', '77', '66', '55', '44', '33', '22', # Wszystkie pary
            'ATs', 'KJs', 'QJs', 'JTs', 'T9s', '98s', # Suited connectors
            'AQo', 'KQo', 'AJo', 'KJo', 'QJo'
        ]

    def act(self, state: PlayerState) -> Action:
        start_time = time.time()
        try:
            # 1. ANALIZA STAWEK
            bb = self._estimate_big_blind(state)
            
            # 2. NINJA MODE (Short Stack < 12 BB)
            if state.stack < (bb * 12):
                return self._ninja_strategy(state)

            # 3. PRE-FLOP
            if len(state.community_cards) == 0:
                return self._play_preflop(state, bb)

            # 4. POST-FLOP
            # Szybka ocena czy mamy Nuts (100% wygranej)
            static_strength = self._calculate_static_strength(state.hand, state.community_cards)
            
            # Jeśli to River lub mamy układ bliski idealnego (np. Kareta), nie marnujemy czasu na MC
            is_river = len(state.community_cards) == 5
            
            if is_river or static_strength >= 0.98:
                final_equity = static_strength
                divergence = 0.0
            else:
                # Monte Carlo z limitem czasu
                mc_equity = self._calculate_monte_carlo(state.hand, state.community_cards, time_limit=1.8)
                divergence = mc_equity - static_strength
                final_equity = mc_equity
                
                # Korekta na ryzyko drawowania
                if divergence > 0.15: 
                    final_equity *= 0.95

            # --- LOGIKA DECYZYJNA (EV) ---
            cost_to_call = getattr(state, 'current_bet', 0) or 0
            pot_total = state.pot + cost_to_call
            
            # EV = (Pula * Equity) - Koszt
            ev = (pot_total * final_equity) - cost_to_call

            # A. Czekanie (Check)
            if cost_to_call == 0:
                # Betujemy dla wartości lub jako semi-bluff
                if final_equity > 0.60 or (divergence > 0.25 and final_equity > 0.4):
                    amount = self._get_dynamic_bet_size(state, final_equity)
                    return Action(ActionType.RAISE, amount=min(int(amount), state.stack))
                return Action(ActionType.CHECK_CALL)

            # B. Płacenie (Call/Raise)
            else:
                if ev > 0:
                    # CRISIS MANAGEMENT: Ochrona przed ogromnymi zakładami
                    # Jeśli rywal chce >40% naszego stacka, wymagamy silnej ręki
                    is_huge_bet = cost_to_call > (state.stack * 0.40)
                    
                    if is_huge_bet:
                        # Na Riverze musimy być bardzo pewni
                        if is_river and final_equity < 0.85: return Action(ActionType.FOLD)
                        # Wcześniej musimy mieć spory potencjał
                        if not is_river and final_equity < 0.60: return Action(ActionType.FOLD)

                    # AGRESJA (Raise)
                    # Przebijamy jeśli mamy dużą przewagę EV i Equity
                    if ev > (state.pot * 0.3) and final_equity > 0.80:
                        # Nie przebijamy na Riverze z "tylko dobrą" ręką (chyba że nuts)
                        if is_river and final_equity < 0.95:
                            return Action(ActionType.CHECK_CALL)
                        
                        dynamic_amt = self._get_dynamic_bet_size(state, final_equity)
                        target = max(dynamic_amt, state.min_raise + cost_to_call)
                        return Action(ActionType.RAISE, amount=min(int(target), state.stack))

                    return Action(ActionType.CHECK_CALL)
                
                else:
                    # Ujemne EV -> Fold, chyba że bardzo tanio (Implied Odds)
                    if cost_to_call < (state.pot * 0.10) and not is_river:
                        return Action(ActionType.CHECK_CALL)
                    return Action(ActionType.FOLD)

        except Exception as e:
            # Fallback w razie błędu krytycznego
            return Action(ActionType.CHECK_CALL)

    # ------------------------------------------------------------------
    # STRATEGIE
    # ------------------------------------------------------------------

    def _ninja_strategy(self, state: PlayerState) -> Action:
        """Push/Fold dla Short Stacka."""
        hand_str = self._format_hand(state.hand)
        
        # Prosta i skuteczna tabela Nasha
        pairs = hand_str[0] == hand_str[1]
        ace_high = 'A' in hand_str[:2]
        broadway = hand_str[0] in 'KQJ' and hand_str[1] in 'KQJ'
        suited_connector = hand_str.endswith('s') and hand_str[0] in '9876' and hand_str[1] in '8765'
        
        should_push = pairs or ace_high or broadway or suited_connector
        
        if should_push:
            return Action(ActionType.RAISE, amount=state.stack)
        
        if (getattr(state, 'current_bet', 0) or 0) > 0:
            return Action(ActionType.FOLD)
            
        return Action(ActionType.CHECK_CALL)

    def _play_preflop(self, state: PlayerState, bb: int) -> Action:
        hand_str = self._format_hand(state.hand)
        cost_to_call = getattr(state, 'current_bet', 0) or 0
        
        # Detekcja 3-betu/All-ina (Crisis Management Pre-flop)
        # Jeśli ktoś chce od nas > 15 BB, to gramy tylko Super Premium
        is_crisis = cost_to_call > (bb * 15)
        
        if is_crisis:
            if self._match_hand(hand_str, self.range_premium):
                return Action(ActionType.CHECK_CALL) # Call all-in lub Raise
            return Action(ActionType.FOLD)

        # Normalna gra
        is_raised_pot = state.pot > (bb * 3.5)
        playable = self.range_tight if is_raised_pot else self.range_loose

        if self._match_hand(hand_str, playable):
            # Premium -> Raise
            if self._match_hand(hand_str, self.range_tight):
                amt = max(state.min_raise * 3, state.pot)
                return Action(ActionType.RAISE, amount=int(min(amt, state.stack)))
            
            # Speculative -> Raise (Steal) or Call
            amt = state.min_raise * 2.5
            return Action(ActionType.RAISE, amount=int(min(amt, state.stack)))

        # Tanie oglądanie flopa (limping / set mining)
        if cost_to_call <= (state.stack * 0.02):
            if hand_str.endswith('s') or hand_str[0] == hand_str[1]:
                return Action(ActionType.CHECK_CALL)

        return Action(ActionType.FOLD)

    # ------------------------------------------------------------------
    # OBLICZENIA (TURBO)
    # ------------------------------------------------------------------

    def _calculate_monte_carlo(self, hand_strs, board_strs, time_limit):
        start = time.time()
        
        # Konwersja raz
        my_hand = [Card.new(c) for c in hand_strs]
        board = [Card.new(c) for c in board_strs]
        
        # OPTYMALIZACJA: Operacje na zbiorach intów są szybsze niż obiekty Deck
        known_mask = set(my_hand + board)
        # List comprehension na liście intów (najszybsza metoda w Pythonie)
        stub_deck = [c for c in self.FULL_DECK if c not in known_mask]
        
        wins = 0
        splits = 0
        executed = 0
        cards_to_deal = 5 - len(board)
        
        # Cache'owanie zmiennych lokalnych (micro-optimization)
        eval_func = self.evaluator.evaluate
        sample_func = random.sample

        for i in range(self.SIMULATION_COUNT):
            if (i % self.MC_BATCH) == 0:
                if (time.time() - start) > time_limit:
                    break
            
            # Losowanie intów
            drawn = sample_func(stub_deck, 2 + cards_to_deal)
            
            opp_hand = drawn[:2]
            sim_board = board + drawn[2:]

            my_rank = eval_func(sim_board, my_hand)
            opp_rank = eval_func(sim_board, opp_hand)

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
        # Texture check
        board = state.community_cards
        is_wet = False
        if len(board) >= 3:
            suits = [c[1] for c in board]
            if any(suits.count(s) >= 3 for s in set(suits)): is_wet = True
        
        multiplier = 0.55
        if equity > 0.90: multiplier = 0.7 if is_wet else 0.35 # Trap
        elif equity > 0.80: multiplier = 0.8 if is_wet else 0.6
        elif equity > 0.65: multiplier = 0.65
        
        bet = int(state.pot * multiplier)
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
            if r == rank: return True
            if len(r) == 3 and r[:2] == rank and r[2] == hand_str[2]: return True
        return False