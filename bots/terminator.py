from engine import BaseAgent, Action, ActionType, PlayerState
from treys import Card, Evaluator, Deck
import random

class TerminatorBot(BaseAgent):
    """
    OSTATECZNA FUZJA (God Bot) - Wersja Stabilna (Fixed):
    1. Multiplayer Awareness (z Kursa2) - wie, że gra przeciwko tłumowi.
    2. Dynamic Bet Sizing (z MasterBot) - dostosowuje zakład do mokrego stołu.
    3. Aggression Tuned - naprawiona pasywność.
    4. Safety Valve - ochrona przed nieskończonym przebijaniem i błędami raise=0.
    """
    def __init__(self, name: str):
        super().__init__(name)
        self.evaluator = Evaluator()
        # Mniejsza liczba iteracji dla szybkości w multi-player
        self.SIMULATION_COUNT = 400 
        
        # Solidny zakres rąk startowych
        self.strong_hands = [
            'AA', 'KK', 'QQ', 'JJ', 'TT', '99', '88',
            'AK', 'AQ', 'KQ', 'AJ', 'AT',
            'AKs', 'AQs', 'KQs', 'JTs', 'QJs', 'T9s'
        ]

    # --- KONWERSJA ---
    def _to_treys_cards(self, card_strs):
        return [Card.new(c) for c in card_strs]

    # --- CORE: MULTIPLAYER MONTE CARLO ---
    def calculate_multiplayer_equity(self, hand, community_cards, num_opponents=2, iterations=400):
        wins = 0
        for _ in range(iterations):
            deck = Deck()
            known_cards = hand + community_cards
            for card in known_cards:
                if card in deck.cards:
                    deck.cards.remove(card)

            # Dobieramy stół do końca
            n_community_needed = 5 - len(community_cards)
            board = community_cards + deck.draw(n_community_needed)

            # Rozdajemy karty wrogom
            opponents_hands = []
            for _ in range(num_opponents):
                opponents_hands.append(deck.draw(2))

            # Sprawdzamy czy wygraliśmy ze WSZYSTKIMI
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
                wins += (1.0 / (num_opponents + 1)) if is_tie else 1.0
        
        return wins / iterations

    # --- INTELLIGENCE: ANALIZA TEKSTURY I BET SIZING ---
    def _analyze_board_texture(self, board_cards) -> float:
        """Zwraca 0.0 (suchy) do 1.0 (niebezpieczny/mokry)."""
        if not board_cards: return 0.0
        # Uproszczona heurystyka: im więcej kart na stole, tym groźniej
        return len(board_cards) * 0.15 

    def _get_dynamic_bet_size(self, state: PlayerState, equity: float, num_opponents: int) -> int:
        """Dostosowuje mnożnik zakładu."""
        pot = state.pot
        
        # Protection factor: im więcej graczy, tym mocniej bijemy
        protection_factor = 1.0 + (num_opponents * 0.1)
        
        if equity > 0.8: # Monster
            multiplier = 0.8 * protection_factor
        elif equity > 0.5: # Strong
            multiplier = 0.6
        else: # Bluff / Semi
            multiplier = 0.5

        bet = int(pot * multiplier)
        return max(bet, state.min_raise)

    # --- GŁÓWNA PĘTLA DECYZYJNA (FIXED) ---
    def act(self, state: PlayerState) -> Action:
        try:
            # 1. SZYBKA UCIECZKA: Jeśli nie mamy żetonów, możemy tylko czekać/sprawdzać
            if state.stack == 0:
                return Action(ActionType.CHECK_CALL)

            # 2. PRE-FLOP
            if len(state.community_cards) == 0:
                return self._play_preflop(state)

            # 3. PRZYGOTOWANIE DANYCH
            hand = self._to_treys_cards(state.hand)
            community = self._to_treys_cards(state.community_cards)
            
            # Szacowanie liczby rywali
            if len(community) == 3: simulated_opponents = 2 
            else: simulated_opponents = 1

            # 4. OBLICZENIA (Equity & EV)
            equity = self.calculate_multiplayer_equity(
                hand, community, num_opponents=simulated_opponents, iterations=self.SIMULATION_COUNT
            )
            
            call_cost = state.current_bet
            total_pot = state.pot + call_cost
            ev = (total_pot * equity) - call_cost

            # 5. DECYZJA

            # A. Darmowe sprawdzenie (Check)
            if call_cost == 0:
                threshold = 1.0 / (simulated_opponents + 1) + 0.15
                
                if equity > threshold:
                    amt = self._get_dynamic_bet_size(state, equity, simulated_opponents)
                    # FIX: Upewnij się, że nie betujemy więcej niż mamy
                    if amt > state.stack: amt = state.stack
                    # FIX: Upewnij się, że betujemy przynajmniej min_raise
                    if amt < state.min_raise: amt = state.min_raise
                    
                    return Action(ActionType.RAISE, amount=amt)
                return Action(ActionType.CHECK_CALL)

            # B. Płatne wejście (Call/Raise)
            if ev > 0:
                # Anti-Loop (Bezpiecznik przeciwko wojnie przebić)
                is_huge_bet = call_cost > state.stack * 0.35
                if is_huge_bet and equity < 0.85:
                     return Action(ActionType.CHECK_CALL)

                # Logika Agresji
                avg_win_rate = 1.0 / (simulated_opponents + 1)
                
                if equity > (avg_win_rate * 1.5): 
                    amt = self._get_dynamic_bet_size(state, equity, simulated_opponents)
                    total_raise = amt + call_cost
                    
                    # === CRITICAL FIX START ===
                    # 1. Logika All-in
                    if total_raise > state.stack * 0.6: 
                        total_raise = state.stack
                    else:
                        # Jeśli nie all-in, upewnij się, że nie przekraczamy stacka
                        total_raise = min(total_raise, state.stack)
                    
                    # 2. Walidacja Min Raise
                    # Nie możemy przebić mniej niż min_raise, chyba że wchodzimy all-in
                    if total_raise < state.min_raise and total_raise < state.stack:
                        return Action(ActionType.CHECK_CALL)
                        
                    # 3. Walidacja Logiczna
                    # Raise musi być większy od obecnego zakładu
                    if total_raise <= state.current_bet:
                         return Action(ActionType.CHECK_CALL)
                    # === CRITICAL FIX END ===

                    return Action(ActionType.RAISE, amount=total_raise)
                
                return Action(ActionType.CHECK_CALL)
            
            else:
                # Crying Call (tanie dobieranie)
                if call_cost < state.stack * 0.04 and equity > 0.2:
                    return Action(ActionType.CHECK_CALL)
                
                return Action(ActionType.FOLD)

        except Exception as e:
            print(f"TERMINATOR ERROR: {e}")
            return Action(ActionType.CHECK_CALL)

    def _play_preflop(self, state: PlayerState) -> Action:
        """Strategia Pre-flop"""
        hand = state.hand
        ranks = sorted([c[0] for c in hand], key=lambda x: '23456789TJQKA'.index(x), reverse=True)
        suited = 's' if hand[0][1] == hand[1][1] else ''
        hand_str = ''.join(ranks) + suited
        
        is_strong = hand_str in self.strong_hands
        if not is_strong and len(hand_str) == 3:
            is_strong = hand_str[:2] in self.strong_hands

        if is_strong:
            amt = max(state.min_raise * 2, 60)
            # FIX: Preflop raise też nie może przekroczyć stacka
            if amt > state.stack: amt = state.stack
            return Action(ActionType.RAISE, amount=amt)
        
        if state.current_bet <= state.stack * 0.02:
            return Action(ActionType.CHECK_CALL)
            
        return Action(ActionType.FOLD)