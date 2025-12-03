from engine import BaseAgent, Action, ActionType, PlayerState
from treys import Card, Evaluator, Deck
import random

class ScientificBot(BaseAgent):
    """
    Zaawansowany bot hybrydowy:
    - Pre-flop: Tight-Aggressive (Tabela rąk)
    - Post-flop: Porównuje Monte Carlo (potencjał) z oceną statyczną (obecna siła).
    - Decyzja: Oparta na Sklansky Dollars (EV).
    """

    def __init__(self, name: str):
        super().__init__(name)
        self.evaluator = Evaluator()
        self.strong_hands_preflop = [
            'AA', 'KK', 'QQ', 'JJ', 'TT', '99',  # Pary
            'AK', 'AQ', 'KQ', 'AJ', 'AT',        # Wysokie karty
            'JTs', 'QJs', 'KQs'                  # Suited connectors (opcjonalnie)
        ]
        self.MONTE_CARLO_ITERATIONS = 800  # Wystarczająco dla precyzji w 3s

    def _get_hand_type_str(self, hand: list) -> str:
        """Pomocnicza funkcja do strategii Pre-flop (Twoja implementacja)."""
        # Sortujemy rangi, żeby 'Ka' i 'Ak' było tym samym
        ranks = sorted([card[0] for card in hand], 
                       key=lambda x: '23456789TJQKA'.index(x), reverse=True)
        # Sprawdzamy czy suited (kolor)
        suited = 's' if hand[0][1] == hand[1][1] else ''
        
        # Zwracamy np. 'AK' lub 'JTs'
        hand_str = ''.join(ranks) + suited
        
        # Jeśli nie ma na liście z 's', sprawdzamy bez 's' (offsuit)
        if len(hand_str) == 3 and hand_str not in self.strong_hands_preflop:
             return hand_str[:2]
        return hand_str

    def _calculate_monte_carlo(self, hand_strs, board_strs) -> float:
        """Metoda 1: Symulacja przyszłości (Stub Deck Optimization)."""
        my_hand = [Card.new(c) for c in hand_strs]
        board = [Card.new(c) for c in board_strs]

        deck = Deck()
        known_cards = my_hand + board
        # Usuwamy znane karty raz
        for card in known_cards:
            if card in deck.cards:
                deck.cards.remove(card)
        stub_deck = deck.cards

        wins = 0
        splits = 0
        cards_to_deal = 5 - len(board)

        for _ in range(self.MONTE_CARLO_ITERATIONS):
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
        
        return (wins + (splits * 0.5)) / self.MONTE_CARLO_ITERATIONS

    def _calculate_static_strength(self, hand_strs, board_strs) -> float:
        """
        Metoda 2: Ocena statyczna "Tu i Teraz".
        Zwraca siłę ręki jako percentyl (0.0 - 1.0).
        Nie patrzy w przyszłość (nie widzi drawów).
        """
        my_hand = [Card.new(c) for c in hand_strs]
        board = [Card.new(c) for c in board_strs]
        
        # Treys zwraca rank od 1 (najlepszy) do 7462 (najgorszy)
        rank = self.evaluator.evaluate(board, my_hand)
        
        # Odwracamy i normalizujemy: 1.0 to Royal Flush, 0.0 to 7-high
        strength = 1.0 - (rank / 7462.0)
        return strength

    def act(self, state: PlayerState) -> Action:
        try:
            # --- FAZA 1: PRE-FLOP (Tabela) ---
            if len(state.community_cards) == 0:
                hand_type = self._get_hand_type_str(state.hand)
                
                if hand_type in self.strong_hands_preflop:
                    # Podbijamy 3x BB lub 2x min_raise
                    amt = max(state.min_raise * 2, 60)
                    return Action(ActionType.RAISE, amount=amt)
                elif state.current_bet <= state.stack * 0.05:
                    return Action(ActionType.CHECK_CALL)
                else:
                    return Action(ActionType.FOLD)

            # --- FAZA 2: POST-FLOP (Analiza Naukowa) ---

            # KROK A: Obliczamy Equity dwiema metodami
            mc_equity = self._calculate_monte_carlo(state.hand, state.community_cards)
            static_strength = self._calculate_static_strength(state.hand, state.community_cards)

            # KROK B: Porównanie metod (Logika Hybrydowa)
            divergence = mc_equity - static_strength
            
            final_equity = mc_equity # Domyślnie ufamy Monte Carlo
            
            # Analiza rozbieżności
            status_msg = "Normal"
            if divergence > 0.2:
                # MC widzi dużą szansę (np. 50%), a Statyczna widzi zero (np. 20%)
                # To znaczy, że mamy DRAW (dążymy do strita/koloru)
                status_msg = "DRAW DETECTED"
                # W przypadku drawów lekko obniżamy zaufanie do MC (bezpiecznik)
                final_equity = mc_equity * 0.95 
            elif divergence < -0.2:
                # Statyczna jest wysoka, a MC niskie? 
                # To rzadkie, oznacza "vulnerable hand" (np. niska para na groźnym stole)
                status_msg = "VULNERABLE HAND"
                final_equity = mc_equity # Tu MC ma rację, zaraz przegramy

            # KROK C: Sklansky Dollars & EV Calculation
            # Sklansky Dollars = (Cała Pula po sprawdzeniu) * Twoje Equity
            
            cost_to_call = state.current_bet
            total_pot = state.pot + cost_to_call
            
            sklansky_dollars = total_pot * final_equity
            
            # EV = To co "zarabiamy" teoretycznie - to co musimy wydać
            ev = sklansky_dollars - cost_to_call

            # Debugowanie (Widać w konsoli/history.txt)
            print(f"[{status_msg}] MC: {mc_equity:.2f} | Static: {static_strength:.2f} | EV: {ev:.1f}")

            # --- FAZA 3: DECYZJA ---
            
            # 1. Jeśli sprawdzenie jest za darmo (Check)
            if cost_to_call == 0:
                if final_equity > 0.6 or (ev > 50): # Wartość dodatnia? Podbijamy
                    target = int(state.pot * 0.5)
                    return Action(ActionType.RAISE, amount=max(state.min_raise, target))
                return Action(ActionType.CHECK_CALL)

            # 2. Jeśli musimy zapłacić
            if ev > 0:
                # Mamy dodatnie EV -> Zazwyczaj sprawdzamy lub podbijamy
                
                # Jeśli EV jest bardzo wysokie (> 20% puli), graj agresywnie
                if ev > state.pot * 0.2:
                    raise_amt = int(state.pot * 0.75) + cost_to_call
                    # Ale nie wchodzimy All-in bez naprawdę potężnej ręki (>80%)
                    if raise_amt > state.stack * 0.5 and final_equity < 0.8:
                        return Action(ActionType.CHECK_CALL)
                    return Action(ActionType.RAISE, amount=max(state.min_raise, raise_amt))
                
                # Standardowe dodatnie EV
                return Action(ActionType.CHECK_CALL)
            
            else:
                # Ujemne EV -> Fold, chyba że bardzo tanio
                # "Crying Call" - sprawdzamy jeśli kosztuje grosze (<2% stacka)
                if cost_to_call < state.stack * 0.02:
                     return Action(ActionType.CHECK_CALL)
                
                return Action(ActionType.FOLD)

        except Exception as e:
            print(f"ERROR in ScientificBot: {e}")
            return Action(ActionType.CHECK_CALL) # Safety net   