"""
Texas Hold'em Poker Engine
==========================

A simulation engine for running poker bot competitions. This engine implements
standard Texas Hold'em rules and provides a framework for AI agents to compete.

Usage:
    python engine.py

For detailed documentation, see DOCUMENTATION.md
"""

import random
import os
import sys
import importlib.util
from treys import Card, Evaluator, Deck  # Card/hand evaluation library
from enum import Enum, auto
from dataclasses import dataclass
from typing import List, Dict, Optional
import signal
import resource


# =============================================================================
# EXCEPTION HANDLING FOR BOT CONSTRAINTS
# =============================================================================

class TimeoutException(BaseException):
    """
    Custom exception raised when a bot exceeds its time limit.
    Inherits from BaseException (not Exception) to avoid being caught
    by generic except clauses in bot code.
    """
    pass


def timeout_handler(signum, frame):
    """
    Signal handler for SIGALRM.
    Raises TimeoutException when the alarm fires (time limit exceeded).
    
    Args:
        signum: Signal number (unused, but required by signal handler signature)
        frame: Current stack frame (unused)
    """
    raise TimeoutException("Timeout reached")


# =============================================================================
# LOGGING UTILITY
# =============================================================================

class DualLogger:
    """
    A file-like object that writes output to both terminal and a log file.
    Used to capture game history while still displaying real-time output.
    
    Attributes:
        terminal: Original stdout stream
        log: File handle for the log file
    
    Usage:
        sys.stdout = DualLogger("history.txt")
        print("This goes to both console and file")
    """
    
    def __init__(self, filepath):
        """
        Initialize the dual logger.
        
        Args:
            filepath: Path to the log file (will be overwritten)
        """
        self.terminal = sys.stdout
        self.log = open(filepath, "w")

    def write(self, message):
        """Write message to both terminal and log file."""
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()  # Ensure immediate write to file

    def flush(self):
        """Flush both output streams."""
        self.terminal.flush()
        self.log.flush()


# =============================================================================
# ACTION TYPES AND DATA STRUCTURES
# =============================================================================

class ActionType(Enum):
    """
    Enumeration of possible player actions in a betting round.
    
    FOLD: Give up the hand and forfeit any chips already bet
    CHECK_CALL: Check (if no bet to match) or call (match the current bet)
    RAISE: Increase the bet to a specified amount
    """
    FOLD = auto()
    CHECK_CALL = auto()
    RAISE = auto()


@dataclass
class Action:
    """
    Represents a player's action during their turn.
    
    Attributes:
        action_type: The type of action (FOLD, CHECK_CALL, or RAISE)
        amount: For RAISE actions, the total bet amount (not additional chips).
                Ignored for FOLD and CHECK_CALL actions.
    
    Examples:
        Action(ActionType.FOLD)                    # Fold the hand
        Action(ActionType.CHECK_CALL)              # Check or call
        Action(ActionType.RAISE, amount=100)       # Raise to 100 total
    """
    action_type: ActionType
    amount: int = 0


@dataclass
class PlayerState:
    """
    Information provided to a bot when it's their turn to act.
    This is the complete game state visible to the player.
    
    Attributes:
        name: The bot's name (identifier)
        hand: List of hole cards as strings (e.g., ['Ah', 'Kd'] for Ace of hearts, King of diamonds)
        community_cards: List of community cards visible on the table
        stack: The player's current chip count
        current_bet: The amount the player needs to add to match the current bet
        pot: Total chips in the pot
        min_raise: The minimum valid raise amount (current bet + big blind)
    
    Card Notation:
        Rank: 2, 3, 4, 5, 6, 7, 8, 9, T, J, Q, K, A
        Suit: s (spades), h (hearts), d (diamonds), c (clubs)
    """
    name: str
    hand: List[str]  # ['Ah', 'Td'] = Ace of hearts, Ten of diamonds
    community_cards: List[str]
    stack: int
    current_bet: int  # The amount needed to match to stay in
    pot: int
    min_raise: int


# =============================================================================
# BASE AGENT CLASS
# =============================================================================

class BaseAgent:
    """
    Abstract base class for all poker bots.
    
    To create a bot, inherit from this class and implement the act() method.
    Your bot will be instantiated once and reused across all hands.
    
    Attributes:
        name: Unique identifier for the bot
    
    Example:
        class MyBot(BaseAgent):
            def act(self, state: PlayerState) -> Action:
                return Action(ActionType.CHECK_CALL)
    """
    
    def __init__(self, name: str):
        """
        Initialize the agent with a name.
        
        Args:
            name: Unique identifier for this bot
        """
        self.name = name

    def act(self, state: PlayerState) -> Action:
        """
        Decide what action to take given the current game state.
        
        This method is called each time it's the bot's turn to act.
        Must return an Action object within the time limit (3 seconds).
        
        Args:
            state: PlayerState containing all visible game information
            
        Returns:
            Action object specifying FOLD, CHECK_CALL, or RAISE
            
        Raises:
            NotImplementedError: If not overridden by subclass
        """
        raise NotImplementedError("Implement act method")


# =============================================================================
# MAIN GAME ENGINE
# =============================================================================

class TexasHoldemEngine:
    """
    Main game engine that manages Texas Hold'em poker games.
    
    This engine handles:
    - Player management and chip tracking
    - Card dealing and deck management
    - Blind posting and betting rounds
    - Hand evaluation and pot distribution
    - Bot safety (time/memory limits, crash handling)
    
    Attributes:
        players: List of player dictionaries containing agent, stack, and state
        sb_amt: Small blind amount
        bb_amt: Big blind amount
        start_stack: Initial chip count for each player
        evaluator: Treys Evaluator for hand ranking
        deck: Current deck of cards
        button_idx: Index of the dealer button
        community_cards: Shared cards on the table
        pot: Total chips in the pot
        active_bet: Current highest bet in the betting round
        last_hand_result: Result of the most recent hand (for debugging)
    
    Usage:
        engine = TexasHoldemEngine(small_blind=10, big_blind=20, start_stack=1000)
        engine.add_agent(MyBot("Bot1"))
        engine.add_agent(MyBot("Bot2"))
        engine.play_hand()
    """
    
    def __init__(
        self, small_blind: int = 10, big_blind: int = 20, start_stack: int = 1000
    ):
        """
        Initialize the poker engine.
        
        Args:
            small_blind: Amount of the small blind (default: 10)
            big_blind: Amount of the big blind (default: 20)
            start_stack: Starting chip count for each player (default: 1000)
        """
        self.players = []
        self.sb_amt = small_blind
        self.bb_amt = big_blind
        self.start_stack = start_stack

        # Treys library components for hand evaluation
        self.evaluator = Evaluator()
        self.deck = None

        # Game state
        self.button_idx = 0           # Dealer button position
        self.community_cards = []     # Flop/Turn/River cards
        self.pot = 0                  # Total pot size
        self.active_bet = 0           # Current highest bet on the table
        self.last_hand_result = None  # For debugging/analysis

    def add_agent(self, agent: BaseAgent):
        """
        Add a bot to the game.
        
        Args:
            agent: BaseAgent instance to add to the game
        """
        self.players.append(
            {
                "agent": agent,
                "stack": self.start_stack,
                "hand": [],  # Treys Int objects (internal card representation)
                "folded": False,
                "all_in": False,
                "current_round_bet": 0,  # How much put in THIS betting round
            }
        )

    def _reset_round_bets(self):
        """
        Reset betting state for a new betting round (flop, turn, river).
        Called at the start of each new betting round.
        """
        self.active_bet = 0
        for p in self.players:
            p["current_round_bet"] = 0

    def _get_active_players(self):
        """
        Get players who can still act (not folded and not all-in).
        
        Returns:
            List of player dictionaries for active players
        """
        return [p for p in self.players if not p["folded"] and not p["all_in"]]

    def _get_surviving_players(self):
        """
        Get players still in the hand (not folded, but may be all-in).
        
        Returns:
            List of player dictionaries for non-folded players
        """
        return [p for p in self.players if not p["folded"]]

    def _betting_round(self, starting_index):
        """
        Execute a complete betting round.
        
        A betting round continues until all active players have either:
        - Folded
        - Gone all-in
        - Matched the current bet with no pending raises
        
        Args:
            starting_index: Index of the first player to act
        """
        active_players = self._get_active_players()
        
        # Check if betting is even needed
        if len(active_players) <= 1:
            surviving = self._get_surviving_players()
            all_in_count = sum(1 for p in surviving if p["all_in"])
            if all_in_count > 0 and len(active_players) == 0:
                print("  (All remaining players are all-in)")
            return

        # Track how many players still need to act
        # When someone raises, this counter is reset to give others a chance to respond
        players_to_act = len(active_players)
        
        # Current position in the player rotation
        curr_idx = starting_index % len(self.players)

        # Main betting loop - continues until all bets are settled
        betting_open = True

        while betting_open:
            p = self.players[curr_idx]

            # Skip players who can't act (folded or all-in)
            if p["folded"] or p["all_in"]:
                curr_idx = (curr_idx + 1) % len(self.players)
                continue

            # Check if betting is complete
            # (player has matched the bet and everyone has had a chance to act)
            if p["current_round_bet"] == self.active_bet and players_to_act <= 0:
                betting_open = False
                break

            # Calculate how much this player needs to call
            to_call = self.active_bet - p["current_round_bet"]
            
            # Minimum raise is current bet + big blind (simplified rule)
            min_raise = self.active_bet + self.bb_amt

            # Prepare the state information for the bot
            state = PlayerState(
                name=p["agent"].name,
                hand=[Card.int_to_str(c) for c in p["hand"]],  # Convert to readable format
                community_cards=[Card.int_to_str(c) for c in self.community_cards],
                stack=p["stack"],
                current_bet=to_call,
                pot=self.pot,
                min_raise=min_raise,
            )

            # =================================================================
            # GET ACTION FROM BOT (with safety constraints)
            # =================================================================
            
            if p.get("disqualified", False):
                # Disqualified bots automatically fold
                action = Action(ActionType.FOLD)
            else:
                # Safety limits for bot execution
                LIMIT_MEMORY = 1024 * 1024 * 1024  # 1GB memory limit
                LIMIT_TIME = 3  # 3 second time limit

                # Save current resource limits to restore later
                old_soft, old_hard = resource.getrlimit(resource.RLIMIT_AS)
                
                # Calculate safe memory limit (don't exceed hard limit)
                new_soft = LIMIT_MEMORY
                if old_hard != resource.RLIM_INFINITY and LIMIT_MEMORY > old_hard:
                    new_soft = old_hard

                # Set up timeout handler
                old_handler = signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(LIMIT_TIME)  # Start the countdown
                
                try:
                    # Apply memory limit and execute bot's decision
                    resource.setrlimit(resource.RLIMIT_AS, (new_soft, old_hard))
                    action = p["agent"].act(state)
                    
                except MemoryError:
                    # Bot exceeded memory limit - disqualify immediately
                    print(f"  Bot {p['agent'].name} exceeded memory limit! Disqualifying.")
                    p["disqualified"] = True
                    p["stack"] = 0  # Disqualified bots lose all chips
                    action = Action(ActionType.FOLD)
                    
                except TimeoutException:
                    # Bot exceeded time limit - take random action
                    print(f"  Bot {p['agent'].name} exceeded time limit! Random action.")
                    opts = [ActionType.FOLD, ActionType.CHECK_CALL, ActionType.RAISE]
                    rt = random.choice(opts)
                    action = Action(rt, random.randint(0, p["stack"]))
                    
                except Exception as e:
                    # Bot crashed - fold and continue
                    print(f"  Bot {p['agent'].name} crashed: {e}. Folding.")
                    action = Action(ActionType.FOLD)
                    
                finally:
                    # Always restore original limits and handler
                    signal.alarm(0)  # Cancel the alarm
                    signal.signal(signal.SIGALRM, old_handler)
                    resource.setrlimit(resource.RLIMIT_AS, (old_soft, old_hard))

            # =================================================================
            # PROCESS THE ACTION
            # =================================================================
            
            # Handle ActionType comparison robustly (for module reloading scenarios)
            atype = action.action_type
            if hasattr(atype, "name"):
                atype = atype.name
            elif isinstance(atype, int):
                pass  # Fallback for edge cases

            # --- FOLD ---
            if atype == "FOLD" or atype == ActionType.FOLD.name:
                p["folded"] = True
                print(f"  {p['agent'].name} Folds.")
                print(f"    [Pot: {self.pot}]")
                
                # Check if only one player remains (instant win)
                survivors = self._get_surviving_players()
                if len(survivors) == 1:
                    return  # Hand ends, winner determined in play_hand()

            # --- CHECK/CALL ---
            elif atype == "CHECK_CALL" or atype == ActionType.CHECK_CALL.name:
                # Call amount is capped at player's stack (all-in call)
                amount = min(to_call, p["stack"])
                p["stack"] -= amount
                p["current_round_bet"] += amount
                self.pot += amount
                
                # Check if player went all-in
                if p["stack"] == 0:
                    p["all_in"] = True
                
                # Display appropriate message
                if amount == 0:
                    print(f"  {p['agent'].name} Checks.")
                else:
                    print(f"  {p['agent'].name} Calls {amount}.")
                print(f"    [Pot: {self.pot}]")

            # --- RAISE ---
            elif atype == "RAISE" or atype == ActionType.RAISE.name:
                actual_raise = action.amount
                
                # Validate raise amount (must meet minimum unless going all-in)
                if actual_raise < min_raise and actual_raise < p["stack"]:
                    actual_raise = min_raise  # Force minimum raise if invalid

                # Calculate the cost (difference from what already bet)
                cost = actual_raise - p["current_round_bet"]

                # Cap at player's stack (all-in raise)
                if cost > p["stack"]:
                    cost = p["stack"]
                    actual_raise = p["current_round_bet"] + cost
                    p["all_in"] = True

                # Update player state
                p["stack"] -= cost
                self.pot += cost
                p["current_round_bet"] += cost

                # Update the betting high-water mark
                if p["current_round_bet"] > self.active_bet:
                    diff = p["current_round_bet"] - self.active_bet
                    self.active_bet = p["current_round_bet"]
                    # Re-open action for all other players
                    players_to_act = len(self._get_active_players()) - 1

                print(f"  {p['agent'].name} Raises to {actual_raise}.")
                print(f"    [Pot: {self.pot}]")
                
            # Move to next player
            players_to_act -= 1
            curr_idx = (curr_idx + 1) % len(self.players)

            # Safety check: if no active players remain, end betting
            if len(self._get_active_players()) < 1:
                betting_open = False

    def play_hand(self):
        """
        Play a complete hand of Texas Hold'em.
        
        This method orchestrates an entire hand from dealing to showdown:
        1. Setup - Reset deck, community cards, and player states
        2. Blinds - Post small and big blinds
        3. Pre-Flop - Deal hole cards and betting round
        4. Flop - Deal 3 community cards and betting round
        5. Turn - Deal 1 community card and betting round
        6. River - Deal 1 community card and betting round
        7. Showdown - Evaluate hands and distribute pot
        
        Returns:
            bool: True if the hand was played successfully, False if not enough players
        """
        print(
            f"\n=== New Hand (Button: {self.players[self.button_idx]['agent'].name}) ==="
        )

        # =================================================================
        # STEP 1: SETUP
        # =================================================================
        self.deck = Deck()  # Fresh shuffled deck
        self.community_cards = []
        self.pot = 0

        # Reset each player's hand state (preserve stack from previous hands)
        for p in self.players:
            p["folded"] = p["stack"] == 0  # Auto-fold if busted (no chips)
            p["all_in"] = False
            p["hand"] = []
            p["current_round_bet"] = 0

        # Check if we have enough players to continue
        active_count = len([p for p in self.players if p["stack"] > 0])
        if active_count < 2:
            print("Game Over: Not enough players.")
            return False

        # =================================================================
        # STEP 2: POST BLINDS
        # =================================================================
        
        def find_next_active(start_idx):
            """Find the next player with chips (skips busted players)."""
            idx = start_idx % len(self.players)
            for _ in range(len(self.players)):
                if self.players[idx]["stack"] > 0:
                    return idx
                idx = (idx + 1) % len(self.players)
            return start_idx  # Fallback (shouldn't happen)

        # Small blind is left of button, big blind is left of small blind
        sb_idx = find_next_active(self.button_idx + 1)
        bb_idx = find_next_active(sb_idx + 1)

        # Post Small Blind
        sb_p = self.players[sb_idx]
        sb_val = min(self.sb_amt, sb_p["stack"])  # Can only post what you have
        sb_p["stack"] -= sb_val
        sb_p["current_round_bet"] = sb_val
        self.pot += sb_val
        if sb_p["stack"] == 0:
            sb_p["all_in"] = True

        # Post Big Blind
        bb_p = self.players[bb_idx]
        bb_val = min(self.bb_amt, bb_p["stack"])
        bb_p["stack"] -= bb_val
        bb_p["current_round_bet"] = bb_val
        self.pot += bb_val
        if bb_p["stack"] == 0:
            bb_p["all_in"] = True

        # Set the active bet to the highest blind posted
        self.active_bet = max(sb_val, bb_val)

        # =================================================================
        # STEP 3: DEAL HOLE CARDS
        # =================================================================
        for p in self.players:
            if not p["folded"]:
                p["hand"] = self.deck.draw(2)  # 2 private cards per player

        # =================================================================
        # STEP 4: PRE-FLOP BETTING
        # =================================================================
        print("--- Pre-Flop ---")
        # Action starts with player left of big blind (under the gun)
        start_idx = (bb_idx + 1) % len(self.players)
        self._betting_round(start_idx)

        # Check if someone won by everyone else folding
        if self._check_early_win():
            return True

        # =================================================================
        # STEP 5: FLOP
        # =================================================================
        self._reset_round_bets()
        self.community_cards = self.deck.draw(3)  # 3 community cards
        print(f"\n--- Flop: {[Card.int_to_str(c) for c in self.community_cards]} ---")
        
        # Post-flop betting starts with first active player left of button
        self._betting_round((self.button_idx + 1) % len(self.players))
        if self._check_early_win():
            return True

        # =================================================================
        # STEP 6: TURN
        # =================================================================
        self._reset_round_bets()
        self.community_cards.extend(self.deck.draw(1))  # 1 more community card
        print(f"\n--- Turn: {[Card.int_to_str(c) for c in self.community_cards]} ---")
        
        self._betting_round((self.button_idx + 1) % len(self.players))
        if self._check_early_win():
            return True

        # =================================================================
        # STEP 7: RIVER
        # =================================================================
        self._reset_round_bets()
        self.community_cards.extend(self.deck.draw(1))  # Final community card
        print(f"\n--- River: {[Card.int_to_str(c) for c in self.community_cards]} ---")
        
        self._betting_round((self.button_idx + 1) % len(self.players))
        if self._check_early_win():
            return True

        # =================================================================
        # STEP 8: SHOWDOWN
        # =================================================================
        self._showdown()

        # Display final chip counts
        self._print_stacks()

        # Move the dealer button for next hand
        self.button_idx = (self.button_idx + 1) % len(self.players)
        return True

    def _check_early_win(self):
        """
        Check if a player has won by all others folding.
        
        Returns:
            bool: True if there's an early winner, False if play continues
        """
        survivors = self._get_surviving_players()
        if len(survivors) == 1:
            # Only one player left - they win the pot
            winner = survivors[0]
            winner["stack"] += self.pot
            print(f"Winner by fold: {winner['agent'].name} wins {self.pot}")
            
            # Store result for analysis/debugging
            self.last_hand_result = {
                "winners": [winner['agent'].name],
                "pot": self.pot,
                "method": "Fold"
            }
            
            self._print_stacks()
            return True
        return False

    def _showdown(self):
        """
        Evaluate all remaining hands and distribute the pot.
        
        Uses the Treys library to rank hands. Lower scores are better.
        In case of ties, the pot is split equally among winners.
        """
        print("\n--- Showdown ---")
        survivors = self._get_surviving_players()

        # Evaluate each player's hand
        scores = []
        for p in survivors:
            # Treys evaluator returns a score (lower = better)
            score = self.evaluator.evaluate(self.community_cards, p["hand"])
            
            # Get human-readable hand description
            class_str = self.evaluator.get_rank_class(score)
            desc = self.evaluator.class_to_string(class_str)
            
            scores.append((score, p, desc))

            # Display the player's hand
            hand_str = [Card.int_to_str(c) for c in p["hand"]]
            print(f"{p['agent'].name} shows {hand_str} ({desc})")

        # Sort by score (lowest/best first)
        scores.sort(key=lambda x: x[0])

        # Handle ties (split pot)
        best_score = scores[0][0]
        winners = [x[1] for x in scores if x[0] == best_score]

        # Distribute pot equally among winners
        share = self.pot // len(winners)
        winner_names = []
        for w in winners:
            w["stack"] += share
            print(f"*** {w['agent'].name} WINS {share} ***")
            winner_names.append(w['agent'].name)

        # Store result for analysis
        self.last_hand_result = {
            "winners": winner_names,
            "pot": self.pot,
            "method": "Showdown"
        }

    def _print_stacks(self):
        """Display current chip counts for all players."""
        print("\n--- Player Stacks ---")
        for p in self.players:
            status = ""
            if p.get("disqualified", False):
                status = " [DISQUALIFIED]"
            elif p["stack"] == 0:
                status = " [BUSTED]"
            print(f"  {p['agent'].name}: {p['stack']}{status}")
        print()


# =============================================================================
# EXAMPLE BOT IMPLEMENTATIONS
# =============================================================================

class CallBot(BaseAgent):
    """
    Simple bot that always checks or calls.
    
    Strategy: Never fold, never raise - just check when possible, call when not.
    This is the simplest possible bot and serves as a baseline.
    
    Strengths: Never folds a winning hand
    Weaknesses: Predictable, doesn't capitalize on strong hands
    """
    
    def act(self, state: PlayerState) -> Action:
        # Always Check or Call - never fold, never raise
        return Action(ActionType.CHECK_CALL)


class AggroBot(BaseAgent):
    """
    Aggressive bot that raises frequently.
    
    Strategy: Raise whenever possible, sometimes just call.
    Applies pressure on opponents with frequent betting.
    
    Strengths: Forces opponents to make tough decisions
    Weaknesses: Can bleed chips with weak hands
    """
    
    def act(self, state: PlayerState) -> Action:
        if state.current_bet == 0:
            # No bet to match - make an opening bet at minimum raise
            return Action(ActionType.RAISE, amount=state.min_raise)
        elif random.random() > 0.5:
            # 50% chance to re-raise
            target = state.current_bet * 2 + state.min_raise
            return Action(ActionType.RAISE, amount=target)
        else:
            # Otherwise just call
            return Action(ActionType.CHECK_CALL)


class RandomBot(BaseAgent):
    """
    Bot that makes random decisions.
    
    Strategy: Randomly fold (20%), call (50%), or raise (30%).
    Useful for testing and as an unpredictable opponent.
    
    Strengths: Unpredictable
    Weaknesses: No actual strategy, loses long-term
    """
    
    def act(self, state: PlayerState) -> Action:
        r = random.random()
        if r < 0.2:
            # 20% chance to fold
            return Action(ActionType.FOLD)
        if r < 0.7:
            # 50% chance to check/call
            return Action(ActionType.CHECK_CALL)
        # 30% chance to raise
        return Action(ActionType.RAISE, amount=state.min_raise + 100)


# =============================================================================
# BOT LOADER
# =============================================================================

def load_bots(directory: str) -> List[BaseAgent]:
    """
    Dynamically load bot agents from Python files in a directory.
    
    This function scans the specified directory for .py files and attempts
    to instantiate bot classes from each file. A valid bot class must:
    - Have an 'act' method
    - Not be named 'BaseAgent'
    - Be instantiable with a single name argument (or no arguments)
    """
    bots = []
    
    # Check if directory exists
    if not os.path.exists(directory):
        return bots
    
    # Add directory to Python path for imports
    abs_dir = os.path.abspath(directory)
    if abs_dir not in sys.path:
        sys.path.append(abs_dir)
    
    # Scan for Python files
    for filename in os.listdir(directory):
        if filename.endswith(".py") and filename != "__init__.py":
            name = filename[:-3]  # Remove .py extension
            path = os.path.join(directory, filename)
            
            try:
                # Load the module dynamically
                spec = importlib.util.spec_from_file_location(name, path)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[name] = module
                    spec.loader.exec_module(module)
                    
                    # Search for a valid agent class in the module
                    found = False
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        
                        # Check if it's a class with an 'act' method (but not BaseAgent)
                        if isinstance(attr, type) and hasattr(attr, 'act') and attr_name != 'BaseAgent':
                            try:
                                # Try to instantiate with name argument
                                agent = attr(name)
                                bots.append(agent)
                                found = True
                                break 
                            except TypeError:
                                # Try without arguments (some bots might not take name)
                                try:
                                    agent = attr()
                                    agent.name = name
                                    bots.append(agent)
                                    found = True
                                    break
                                except:
                                    pass
                    
                    if not found:
                        print(f"No valid agent class found in {filename}")
                        
            except Exception as e:
                print(f"Failed to load bot from {filename}: {e}")
                
    return bots


# =============================================================================
# MAIN SIMULATION RUNNER
# =============================================================================

if __name__ == "__main__":
    """
    Main entry point for running poker simulations.
    
    This script:
    1. Sets up logging to both console and history.txt
    2. Loads bots from the 'bots/' directory
    3. Runs multiple simulations (tournaments)
    4. Tracks and displays final rankings
    
    Configuration:
    - If ≤10 bots: 10 simulations with all players
    - If >10 bots: 100 simulations with random 10-player subsets
    - Each simulation plays up to 100 hands or until one player wins all chips
    """
    
    # Setup paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    history_file = os.path.join(script_dir, "history.txt")
    
    # Enable dual logging (console + file)
    sys.stdout = DualLogger(history_file)

    # Load bots from the bots/ directory
    bots_dir = os.path.join(script_dir, "bots")
    loaded_bots = load_bots(bots_dir)
    
    # Fall back to example bots if none found
    if not loaded_bots:
        print(f"No bots found in '{bots_dir}'. Using example bots.")
        loaded_bots = [
            CallBot("Caller"),
            AggroBot("Maniac"),
            RandomBot("Randy"),
            RandomBot("Randy2")
        ]

    num_players = len(loaded_bots)
    print(f"Loaded {num_players} bots.")

    # Configure simulation parameters based on number of bots
    if num_players > 10:
        # Large field: run more simulations with random subsets
        num_simulations = 100
        subset_size = 10
        print(f"More than 10 players. Running {num_simulations} simulations with subsets of {subset_size}.")
    else:
        # Small field: fewer simulations with all players
        num_simulations = 10
        subset_size = num_players
        print(f"Running {num_simulations} simulations with all players.")

    # Statistics tracking
    total_chips = {bot.name: 0 for bot in loaded_bots}    # Total chips earned
    games_played = {bot.name: 0 for bot in loaded_bots}   # Number of games participated
    games_won = {bot.name: 0 for bot in loaded_bots}      # Number of tournament wins

    # =================================================================
    # RUN SIMULATIONS
    # =================================================================
    
    for i in range(num_simulations):
        # Select players for this simulation
        if num_players > 10:
            current_bots = random.sample(loaded_bots, subset_size)
        else:
            current_bots = loaded_bots

        # Create a fresh game engine
        game = TexasHoldemEngine(start_stack=2000)
        for bot in current_bots:
            game.add_agent(bot)

        print(f"\n--- Simulation {i+1}/{num_simulations} ---")
        
        # Play hands until elimination or hand limit
        hand_num = 0
        MAX_HANDS = 100  # Prevent infinite games
        
        while True:
            hand_num += 1
            
            # Check for winner (only one player with chips)
            players_with_chips = [p for p in game.players if p["stack"] > 0]
            if len(players_with_chips) <= 1:
                if len(players_with_chips) == 1:
                    winner = players_with_chips[0]
                    print(f"\n=== SIMULATION WINNER: {winner['agent'].name} with {winner['stack']} chips after {hand_num-1} hands ===")
                    games_won[winner['agent'].name] += 1
                else:
                    print(f"\n=== No players left with chips after {hand_num-1} hands ===")
                break
            
            # Check hand limit (declare winner by chip lead)
            if hand_num > MAX_HANDS:
                players_with_chips.sort(key=lambda p: p["stack"], reverse=True)
                winner = players_with_chips[0]
                print(f"\n=== HAND LIMIT REACHED ({MAX_HANDS} hands) ===")
                print(f"=== SIMULATION WINNER: {winner['agent'].name} with {winner['stack']} chips ===")
                games_won[winner['agent'].name] += 1
                print("Final standings:")
                for idx, p in enumerate(players_with_chips, 1):
                    print(f"  {idx}. {p['agent'].name}: {p['stack']} chips")
                break
            
            # Play the next hand
            if not game.play_hand():
                print("Game could not be played (not enough players?)")
                break

        # Record final chip counts for statistics
        for p in game.players:
            bot_name = p["agent"].name
            total_chips[bot_name] += p["stack"]
            games_played[bot_name] += 1

    # =================================================================
    # DISPLAY FINAL RANKINGS
    # =================================================================
    
    print("\n" + "=" * 80)
    print("=== FINAL RANKING (Total chips across all simulations) ===")
    print("=" * 80)
    
    # Sort bots by total chips earned (descending)
    ranking = sorted(total_chips.items(), key=lambda x: x[1], reverse=True)
    
    for rank, (bot_name, chips) in enumerate(ranking, 1):
        games = games_played[bot_name]
        wins = games_won[bot_name]
        avg_chips = chips / games if games > 0 else 0
        win_pct = (wins / games * 100) if games > 0 else 0
        print(f"  {rank:2}. {bot_name:20} | Total: {chips:8} chips | Games: {games:4} | Wins: {wins:3} ({win_pct:5.1f}%) | Avg: {avg_chips:8.1f}")
    
    print("=" * 80)
