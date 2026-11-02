# deadlockproject (working name)

A learning helper for Deadlock. Tell it your hero and the enemy team and it suggests
what items to build, which ability to max first, and how to play the matchup.
It's aimed at new players and people trying to improve, and is meant for unranked
and practice games, not ranked.

It runs as a separate app. It never reads game memory or modifies the game.
Data comes from the community [Deadlock API](https://deadlock-api.com) (last 30 days of matches).

## Status

Step 1 of 4: data and recommender, run from the command line.

1. Data and recommender (this step)
2. Simple desktop app where you click your hero and enemies
3. Auto-detect heroes from the screen when you press Esc, and refuse to run in ranked
4. Name, packaged .exe and release

## Try it

```
pip install -r requirements.txt
python -m deadlock_helper Haze --enemies "Lash, Seven, Abrams, Bebop, Wraith, Paradox"
```

`--min-badge N` limits the stats to higher-rank games.

`python scripts/simulate.py --matches 3 --seed 2026 --out sim_output` draws random 6v6 lobbies
and runs the helper for all 12 heroes in each, which is a quick way to spot-check advice across
many heroes.

`python scripts/inspect_api.py` prints a sample from every API endpoint used, which helps
when the API changes. `python -m unittest` runs the logic tests.
