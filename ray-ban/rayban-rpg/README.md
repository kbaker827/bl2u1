# Ray-Ban Dungeon

A tiny turn-based dungeon-crawler RPG, styled as a stand-in for the small in-lens
HUD on Meta Ray-Ban Display glasses.

## Why a web app instead of a native glasses app

Meta Ray-Ban Display doesn't currently expose a public third-party app SDK — the
device only runs Meta's own apps and a small set of approved partner
integrations. There's no way to ship a real installable game to the hardware
today. This project instead simulates the experience: a small square "lens"
viewport with a monochrome amber HUD, driven by the same kind of input a pair
of smart glasses would realistically expose (directional swipes + a pinch to
select, here mapped to a D-pad + SEL/BACK). It runs in any browser, and works
well on a phone held up next to your face if you want the full effect.

## Running it

No build step or dependencies. Either:

- Open `index.html` directly in a browser, or
- Serve the folder so it works well on a phone: `python3 -m http.server 8123`
  from inside `rayban-rpg/`, then visit `http://<your-ip>:8123` from your phone.

## Controls

| Input | Explore | Battle |
|---|---|---|
| Up / Down / Left / Right | Move | Move menu cursor (Up/Down) |
| SEL (Enter/Space) | — | Confirm menu choice |
| BACK (Escape/Backspace) | — | — |

On the title, game-over, and victory screens, SEL starts/restarts the run.

## Game

- Descend 5 procedurally-generated 9x9 floors (deterministic per floor, so a
  given floor number always lays out the same way).
- Fog of war reveals a small radius around you as you explore.
- Random encounters trigger as you walk into unexplored floor tiles; pick up
  gold and potions along the way.
- Turn-based battles: Attack, Defend (halves incoming damage that turn),
  Item (drink a potion), or Run.
- Defeat enough enemies to level up (full heal + stat boost on level-up).
- Floor 5 replaces the stairs with a boss fight against **The Occluder** —
  defeat it to win.
- Dying at any point sends you to a game-over screen; SEL restarts from
  floor 1, level 1.

## Files

- `index.html` — page shell / device frame markup
- `style.css` — amber HUD styling
- `game.js` — game state, map generation, battle system, rendering, input
