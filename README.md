# deadlockproject (working name)

A learning helper for Deadlock. Tell it your hero and the enemy team and it suggests
what items to build, which ability to max first, and how to play the matchup.
It's aimed at new players and people trying to improve, and is meant for unranked
and practice games, not ranked.

It runs as a separate app. It never reads game memory or modifies the game.
Data comes from the community [Deadlock API](https://deadlock-api.com) (last 30 days of matches).

## Status

Steps 1-3 of 4 done; screen reading has not been tried against the real game yet.

1. Data and recommender
2. Desktop app where you click your hero and enemies
3. Read heroes from the screen, and refuse to run in ranked
4. Name, packaged .exe and release

## Try it (Windows)

Install Python 3.10+ from python.org (tick "Add to PATH"), then double-click `run_app.bat`.
Or from a terminal:

```
pip install -r requirements.txt
python -m deadlock_helper
```

1. Pick what you're playing (top left). Choosing Ranked turns the helper off.
2. Click the "You" slot and pick your hero, then fill the enemy slots. Right-click a slot to clear it.
   Or press **Read heroes from screen** while Deadlock shows its top bar (or the scoreboard).
   **Keep watching** re-reads every 8 seconds and refreshes the advice when the enemy team changes.
   **Swap teams** fixes it if your team and the enemy came out the wrong way round.
3. Press **Get advice**.

Screen reading takes a normal screenshot and compares it with the hero portraits, nothing else.
It needs Deadlock in borderless or windowed mode (exclusive fullscreen can capture black).
After each read, `%USERPROFILE%\.deadlock_helper\last_detection.png` shows what it found, with boxes.
**From image...** runs the same reading on a saved screenshot, handy for checking it.

### Ranked guard

The app can't read the game, so it can't know the mode for certain. It stacks good-faith checks:
you must say what you're playing and Ranked is refused; with your Steam friend code entered it
also refuses if the community API lists you in a live ranked match (that list only covers ~200
top matches); and if your match history later shows advice was shown during a ranked match,
the app locks itself for 24 hours.

### Command line

```
python -m deadlock_helper Haze --enemies "Lash, Seven, Abrams, Bebop, Wraith, Paradox"
```

`--min-badge N` limits the stats to higher-rank games (badge = rank tier x 10 + sub-tier, so 71 is Emissary 1).

`python scripts/simulate.py --matches 3 --seed 2026 --out sim_output` draws random 6v6 lobbies
and runs the helper for all 12 heroes in each, which is a quick way to spot-check advice across
many heroes.

`python scripts/inspect_api.py` prints a sample from every API endpoint used, which helps
when the API changes. `python -m unittest` runs the logic tests.
