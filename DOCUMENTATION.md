# Texas Hold'em Poker Engine Documentation

A Python-based Texas Hold'em poker engine designed for bot competitions. This engine allows you to create AI agents (bots) that compete against each other in simulated poker games.

## Table of Contents

1. [Overview](#overview)
2. [Installation](#installation)
3. [Quick Start](#quick-start)
4. [Architecture](#architecture)
5. [Bot Development Tutorial](#bot-development-tutorial)
6. [API Reference](#api-reference)
7. [Game Rules](#game-rules)
8. [Bot Constraints & Safety](#bot-constraints--safety)
9. [Example Bots](#example-bots)
10. [Tips for Building Winning Bots](#tips-for-building-winning-bots)

---

## Overview

The Texas Hold'em Poker Engine is a simulation framework that:

- Implements standard Texas Hold'em poker rules
- Supports multiple AI agents competing simultaneously
- Automatically loads bot files from a `bots/` directory
- Enforces time and memory limits for fair competition
- Uses the [Treys](https://github.com/ihendley/treys) library for hand evaluation
- Logs all game actions to `history.txt`

---

## Installation

### Prerequisites

- Python 3.7+
- `treys` library for card evaluation

### Install Dependencies

```bash
pip install treys
```

### Project Structure

```
poker/
├── engine.py          # Main game engine
├── history.txt        # Game log output
├── DOCUMENTATION.md   # This file
└── bots/              # Directory for bot files
    ├── bot_01.py
    ├── bot_02.py
    └── ...
```

---

## Quick Start

### Running the Engine

```bash
python engine.py
```

The engine will:
1. Load all bot files from the `bots/` directory
2. If no bots are found, use built-in example bots
3. Run multiple simulations
4. Output results to console and `history.txt`

### Creating Your First Bot

1. Create a new Python file in the `bots/` directory (e.g., `my_bot.py`)
2. Implement a class that inherits from `BaseAgent`
3. Implement the `act()` method
4. Run the engine

```python
# bots/my_bot.py
from engine import BaseAgent, Action, ActionType, PlayerState

class MyFirstBot(BaseAgent):
    def act(self, state: PlayerState) -> Action:
        # Simple strategy: always check or call
        return Action(ActionType.CHECK_CALL)
```

---

## Architecture

### Core Components

```
┌─────────────────────────────────────────────────────────────┐
│                    TexasHoldemEngine                        │
├─────────────────────────────────────────────────────────────┤
│  • Manages game state                                       │
│  • Controls betting rounds                                  │
│  • Handles card dealing                                     │
│  • Evaluates hands at showdown                              │
│  • Enforces time/memory limits                              │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                      BaseAgent                              │
├─────────────────────────────────────────────────────────────┤
│  • Abstract base class for all bots                         │
│  • Defines the act(state) interface                         │
│  • Your bot inherits from this                              │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                     PlayerState                             │
├─────────────────────────────────────────────────────────────┤
│  • Information provided to your bot each turn               │
│  • Contains hand, community cards, pot, stack, etc.         │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                        Action                               │
├─────────────────────────────────────────────────────────────┤
│  • Your bot's response (FOLD, CHECK_CALL, or RAISE)         │
│  • Includes amount for RAISE actions                        │
└─────────────────────────────────────────────────────────────┘
```

### Game Flow

```
1. Setup
   ├── Reset deck and community cards
   ├── Reset player states
   └── Post blinds (SB and BB)

2. Pre-Flop
   ├── Deal 2 hole cards to each player
   └── Betting round (starts left of BB)

3. Flop
   ├── Deal 3 community cards
   └── Betting round (starts left of button)

4. Turn
   ├── Deal 1 community card
   └── Betting round

5. River
   ├── Deal 1 community card
   └── Betting round

6. Showdown (if >1 player remains)
   ├── Evaluate all hands
   ├── Determine winner(s)
   └── Award pot

7. Rotate button and repeat
```

---

## Bot Development Tutorial

### Step 1: Understanding the Interface

Your bot must inherit from `BaseAgent` and implement the `act()` method:

```python
from engine import BaseAgent, Action, ActionType, PlayerState

class MyBot(BaseAgent):
    def __init__(self, name: str):
        super().__init__(name)
        # Optional: initialize any state your bot needs
        
    def act(self, state: PlayerState) -> Action:
        # Your decision logic goes here
        # Must return an Action object
        pass
```

### Step 2: Understanding PlayerState

When it's your bot's turn to act, it receives a `PlayerState` object with the following information:

| Attribute | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Your bot's name |
| `hand` | `List[str]` | Your hole cards (e.g., `['Ah', 'Kd']`) |
| `community_cards` | `List[str]` | Shared cards on the table |
| `stack` | `int` | Your current chip count |
| `current_bet` | `int` | Amount you need to call |
| `pot` | `int` | Total chips in the pot |
| `min_raise` | `int` | Minimum amount for a valid raise |

### Step 3: Understanding Actions

Your bot can take one of three actions:

```python
from engine import Action, ActionType

# FOLD - Give up your hand
Action(ActionType.FOLD)

# CHECK_CALL - Check if no bet to match, otherwise call the current bet
Action(ActionType.CHECK_CALL)

# RAISE - Raise to a specific amount (total bet, not additional)
Action(ActionType.RAISE, amount=100)
```

### Step 4: Card Notation

Cards are represented as 2-character strings:
- **Rank**: `2`, `3`, `4`, `5`, `6`, `7`, `8`, `9`, `T`, `J`, `Q`, `K`, `A`
- **Suit**: `s` (spades), `h` (hearts), `d` (diamonds), `c` (clubs)

Examples:
- `Ah` = Ace of hearts
- `Td` = Ten of diamonds
- `2c` = Two of clubs

### Step 5: Basic Bot Example

```python
from engine import BaseAgent, Action, ActionType, PlayerState
import random

class TightAggressiveBot(BaseAgent):
    """
    A simple tight-aggressive bot:
    - Only plays strong starting hands
    - Raises when it has a good hand
    - Folds weak hands
    """
    
    def __init__(self, name: str):
        super().__init__(name)
        self.strong_hands = ['AA', 'KK', 'QQ', 'JJ', 'TT', 'AK', 'AQ', 'KQ']
    
    def _get_hand_type(self, hand: list) -> str:
        """Convert hole cards to a hand type string."""
        ranks = sorted([card[0] for card in hand], 
                      key=lambda x: '23456789TJQKA'.index(x), reverse=True)
        return ''.join(ranks)
    
    def act(self, state: PlayerState) -> Action:
        hand_type = self._get_hand_type(state.hand)
        
        # Pre-flop strategy
        if len(state.community_cards) == 0:
            if hand_type in self.strong_hands:
                # Strong hand: raise
                return Action(ActionType.RAISE, amount=state.min_raise * 2)
            elif state.current_bet <= state.stack * 0.05:
                # Cheap to see flop
                return Action(ActionType.CHECK_CALL)
            else:
                return Action(ActionType.FOLD)
        
        # Post-flop: simplified - just call most bets
        if state.current_bet <= state.stack * 0.1:
            return Action(ActionType.CHECK_CALL)
        else:
            return Action(ActionType.FOLD)
```

---

## API Reference

### ActionType (Enum)

```python
class ActionType(Enum):
    FOLD = auto()        # Give up the hand
    CHECK_CALL = auto()  # Check (if no bet) or call (match current bet)
    RAISE = auto()       # Raise to a specified amount
```

### Action (Dataclass)

```python
@dataclass
class Action:
    action_type: ActionType  # The type of action
    amount: int = 0          # For RAISE: the total bet amount
```

### PlayerState (Dataclass)

```python
@dataclass
class PlayerState:
    name: str                    # Bot's name
    hand: List[str]              # Hole cards ['Ah', 'Kd']
    community_cards: List[str]   # Community cards on table
    stack: int                   # Current chip count
    current_bet: int             # Amount needed to call
    pot: int                     # Total pot size
    min_raise: int               # Minimum valid raise amount
```

### BaseAgent (Abstract Class)

```python
class BaseAgent:
    def __init__(self, name: str):
        self.name = name
    
    def act(self, state: PlayerState) -> Action:
        """
        Called when it's the bot's turn to act.
        Must return an Action object.
        """
        raise NotImplementedError("Implement act method")
```

### TexasHoldemEngine

```python
class TexasHoldemEngine:
    def __init__(
        self, 
        small_blind: int = 10,    # Small blind amount
        big_blind: int = 20,      # Big blind amount
        start_stack: int = 1000   # Starting chips per player
    ):
        ...
    
    def add_agent(self, agent: BaseAgent):
        """Add a bot to the game."""
        ...
    
    def play_hand(self) -> bool:
        """Play a single hand. Returns False if game cannot continue."""
        ...
```

---

## Game Rules

### Texas Hold'em Basics

1. **Blinds**: Two forced bets (small blind and big blind) posted before cards are dealt
2. **Hole Cards**: Each player receives 2 private cards
3. **Community Cards**: 5 shared cards dealt in stages (Flop: 3, Turn: 1, River: 1)
4. **Betting Rounds**: 4 rounds of betting (pre-flop, flop, turn, river)
5. **Showdown**: Remaining players reveal hands; best 5-card hand wins

### Hand Rankings (Best to Worst)

1. Royal Flush (A-K-Q-J-T suited)
2. Straight Flush (5 consecutive cards, same suit)
3. Four of a Kind (4 cards of same rank)
4. Full House (3 of a kind + pair)
5. Flush (5 cards, same suit)
6. Straight (5 consecutive cards)
7. Three of a Kind (3 cards of same rank)
8. Two Pair (2 pairs)
9. One Pair (2 cards of same rank)
10. High Card (nothing else)

### Engine-Specific Rules

- **Minimum Raise**: Current bet + big blind amount
- **All-In**: A player can bet their entire stack at any time
- **Split Pot**: Ties result in pot being split equally
- **Bust Out**: Players with 0 chips are eliminated

---

## Bot Constraints & Safety

### Time Limit

- **3 seconds** per decision
- Exceeding time results in a **random action** being taken

### Memory Limit

- **1 GB** maximum memory usage
- Exceeding memory results in **immediate disqualification**
- Disqualified bots lose all chips

### Error Handling

- If your bot crashes (raises an exception), it will **automatically fold**
- Repeated crashes may indicate bugs in your code

## Example Bots

### CallBot (Built-in)

Always checks or calls. Never folds, never raises.

```python
class CallBot(BaseAgent):
    def act(self, state: PlayerState) -> Action:
        return Action(ActionType.CHECK_CALL)
```

### AggroBot (Built-in)

Aggressive player that raises frequently.

```python
class AggroBot(BaseAgent):
    def act(self, state: PlayerState) -> Action:
        if state.current_bet == 0:
            return Action(ActionType.RAISE, amount=state.min_raise)
        elif random.random() > 0.5:
            target = state.current_bet * 2 + state.min_raise
            return Action(ActionType.RAISE, amount=target)
        else:
            return Action(ActionType.CHECK_CALL)
```

### RandomBot (Built-in)

Makes random decisions.

```python
class RandomBot(BaseAgent):
    def act(self, state: PlayerState) -> Action:
        r = random.random()
        if r < 0.2:
            return Action(ActionType.FOLD)
        if r < 0.7:
            return Action(ActionType.CHECK_CALL)
        return Action(ActionType.RAISE, amount=state.min_raise + 100)
```

---


---

## Simulation Settings

When running `engine.py`, the following parameters control the simulation:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `small_blind` | 10 | Small blind amount |
| `big_blind` | 20 | Big blind amount |
| `start_stack` | 2000 | Starting chips per player |
| `MAX_HANDS` | 100 | Maximum hands per simulation |
| `num_simulations` | 10 (≤10 bots) or 100 (>10 bots) | Number of simulations to run |

### Output

Results are printed to console and saved to `history.txt`. Final rankings show:
- Total chips earned across all simulations
- Number of games played
- Win count and win percentage
- Average chips per game

---

## Troubleshooting

### Bot Not Loading

- Ensure your file is in the `bots/` directory
- Ensure your class has an `act()` method
- Check for syntax errors in your Python file
- Your class name shouldn't be `BaseAgent`

### Bot Acting Strangely

- Check the time limit isn't being exceeded
- Print debug information (will appear in `history.txt`)
- Verify your action amounts are valid

### Import Errors

- Make sure `treys` is installed: `pip install treys`
- The engine automatically adds `bots/` to `sys.path`

---

## License

This poker engine is provided for educational and competition purposes.

---

## Contact

For questions or issues, contact the tournament organizers.

---

*Happy bot building!*
