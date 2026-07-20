(function () {
  "use strict";

  const SIZE = 9;
  const BOSS_FLOOR = 5;

  const ENEMY_TEMPLATES = [
    { name: "Static Wisp", hp: 8, atk: 3, def: 0, xp: 6, gold: 3, minFloor: 1 },
    { name: "Glitch Rat", hp: 12, atk: 4, def: 1, xp: 9, gold: 5, minFloor: 1 },
    { name: "Signal Wraith", hp: 18, atk: 6, def: 2, xp: 14, gold: 8, minFloor: 2 },
    { name: "Feedback Hound", hp: 20, atk: 9, def: 2, xp: 20, gold: 12, minFloor: 3 },
    { name: "Circuit Golem", hp: 26, atk: 8, def: 4, xp: 22, gold: 14, minFloor: 3 },
    { name: "Null Sentinel", hp: 34, atk: 11, def: 5, xp: 30, gold: 20, minFloor: 4 },
  ];

  const BOSS = { name: "The Occluder", hp: 70, atk: 14, def: 6, xp: 120, gold: 150, isBoss: true };

  let state = {};

  function mulberry32(seed) {
    return function () {
      seed |= 0;
      seed = (seed + 0x6d2b79f5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), seed | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function shuffle(arr, rng) {
    for (let i = arr.length - 1; i > 0; i--) {
      const j = Math.floor(rng() * (i + 1));
      [arr[i], arr[j]] = [arr[j], arr[i]];
    }
    return arr;
  }

  function isReachable(grid, sx, sy, tx, ty) {
    const seen = new Set([sx + "," + sy]);
    const queue = [[sx, sy]];
    while (queue.length) {
      const [x, y] = queue.shift();
      if (x === tx && y === ty) return true;
      for (const [dx, dy] of [[0, -1], [0, 1], [-1, 0], [1, 0]]) {
        const nx = x + dx, ny = y + dy;
        const key = nx + "," + ny;
        if (nx < 0 || ny < 0 || nx >= SIZE || ny >= SIZE) continue;
        if (grid[ny][nx] === "wall" || seen.has(key)) continue;
        seen.add(key);
        queue.push([nx, ny]);
      }
    }
    return false;
  }

  function generateFloor(floorNum) {
    const rng = mulberry32(floorNum * 7919 + 42);
    let grid;
    let attempts = 0;
    do {
      grid = [];
      for (let y = 0; y < SIZE; y++) {
        const row = [];
        for (let x = 0; x < SIZE; x++) {
          row.push(x === 0 || y === 0 || x === SIZE - 1 || y === SIZE - 1 ? "wall" : "floor");
        }
        grid.push(row);
      }
      for (let y = 1; y < SIZE - 1; y++) {
        for (let x = 1; x < SIZE - 1; x++) {
          if ((x === 1 && y === 1) || (x === SIZE - 2 && y === SIZE - 2)) continue;
          if (rng() < 0.22) grid[y][x] = "wall";
        }
      }
      attempts++;
    } while (!isReachable(grid, 1, 1, SIZE - 2, SIZE - 2) && attempts < 40);

    if (!isReachable(grid, 1, 1, SIZE - 2, SIZE - 2)) {
      for (let y = 1; y < SIZE - 1; y++) for (let x = 1; x < SIZE - 1; x++) grid[y][x] = "floor";
    }

    grid[1][1] = "floor";
    grid[SIZE - 2][SIZE - 2] = floorNum === BOSS_FLOOR ? "boss" : "stairs";

    const spots = [];
    for (let y = 1; y < SIZE - 1; y++) {
      for (let x = 1; x < SIZE - 1; x++) {
        if (grid[y][x] === "floor" && !(x === 1 && y === 1)) spots.push([x, y]);
      }
    }
    shuffle(spots, rng);
    if (spots[0]) grid[spots[0][1]][spots[0][0]] = "potion";
    if (spots[1]) grid[spots[1][1]][spots[1][0]] = "gold";
    if (spots[2]) grid[spots[2][1]][spots[2][0]] = "potion";

    return grid;
  }

  function xpToNext(level) {
    return 20 + (level - 1) * 15;
  }

  function scaledEnemy() {
    const pool = ENEMY_TEMPLATES.filter((t) => t.minFloor <= state.floor);
    const t = pool[Math.floor(Math.random() * pool.length)];
    const scale = 1 + (state.floor - 1) * 0.12;
    return {
      name: t.name,
      hp: Math.round(t.hp * scale),
      maxHp: Math.round(t.hp * scale),
      atk: Math.round(t.atk * scale),
      def: t.def,
      xp: Math.round(t.xp * scale),
      gold: Math.round(t.gold * scale),
    };
  }

  function makeBoss() {
    return { ...BOSS, maxHp: BOSS.hp };
  }

  function log(msg) {
    state.messages.push(msg);
    if (state.messages.length > 3) state.messages.shift();
  }

  function battleLog(msg) {
    state.battle.log.push(msg);
    if (state.battle.log.length > 4) state.battle.log.shift();
  }

  function initGame() {
    state = {
      player: { x: 1, y: 1, hp: 30, maxHp: 30, atk: 6, def: 2, level: 1, xp: 0, gold: 0, potions: 2 },
      floor: 1,
      map: generateFloor(1),
      visited: new Set(),
      encounterChecked: new Set(),
      messages: ["Welcome, Wanderer. Reach the depths and defeat the Occluder."],
      screen: "title",
      battle: null,
    };
    revealAround(1, 1);
  }

  function revealAround(x, y) {
    for (let dy = -1; dy <= 1; dy++) {
      for (let dx = -1; dx <= 1; dx++) {
        const nx = x + dx, ny = y + dy;
        if (nx >= 0 && ny >= 0 && nx < SIZE && ny < SIZE) state.visited.add(nx + "," + ny);
      }
    }
  }

  function movePlayer(dx, dy) {
    const p = state.player;
    const nx = p.x + dx, ny = p.y + dy;
    const cell = state.map[ny] && state.map[ny][nx];
    if (!cell || cell === "wall") return;
    p.x = nx;
    p.y = ny;
    revealAround(nx, ny);
    handleTile(nx, ny);
  }

  function handleTile(x, y) {
    const cell = state.map[y][x];
    if (cell === "potion") {
      state.player.potions++;
      state.map[y][x] = "floor";
      log("Found a potion.");
      return;
    }
    if (cell === "gold") {
      const g = 5 + state.floor * 3;
      state.player.gold += g;
      state.map[y][x] = "floor";
      log(`Found ${g} gold.`);
      return;
    }
    if (cell === "stairs") {
      descend();
      return;
    }
    if (cell === "boss") {
      startBattle(makeBoss());
      return;
    }
    const key = x + "," + y;
    const firstVisit = !state.encounterChecked.has(key);
    state.encounterChecked.add(key);
    const chance = firstVisit ? 0.28 : 0.1;
    if (Math.random() < chance) startBattle(scaledEnemy());
  }

  function descend() {
    state.floor++;
    state.map = generateFloor(state.floor);
    state.player.x = 1;
    state.player.y = 1;
    state.visited = new Set();
    state.encounterChecked = new Set();
    revealAround(1, 1);
    log(`Descending to floor ${state.floor}...`);
  }

  function startBattle(enemy) {
    state.screen = "battle";
    state.battle = { enemy, defending: false, cursor: 0, won: false, log: [`A wild ${enemy.name} appears!`] };
  }

  function levelUpCheck() {
    const p = state.player;
    let leveled = false;
    while (p.xp >= xpToNext(p.level)) {
      p.xp -= xpToNext(p.level);
      p.level++;
      p.maxHp += 6;
      p.atk += 2;
      p.def += 1;
      p.hp = p.maxHp;
      leveled = true;
    }
    if (leveled) battleLog(`Level up! Now level ${p.level}.`);
  }

  function enemyTurn() {
    const b = state.battle, p = state.player, e = b.enemy;
    let dmg = Math.max(1, e.atk - p.def + Math.floor(Math.random() * 3) - 1);
    if (b.defending) dmg = Math.ceil(dmg / 2);
    p.hp -= dmg;
    battleLog(`${e.name} hits you for ${dmg}.`);
    b.defending = false;
    if (p.hp <= 0) {
      p.hp = 0;
      state.screen = "gameover";
    }
  }

  function battleAction(action) {
    const b = state.battle, p = state.player, e = b.enemy;
    if (action === "attack") {
      const dmg = Math.max(1, p.atk - e.def + Math.floor(Math.random() * 3) - 1);
      e.hp -= dmg;
      battleLog(`You hit ${e.name} for ${dmg}.`);
      if (e.hp <= 0) {
        e.hp = 0;
        p.gold += e.gold;
        p.xp += e.xp;
        battleLog(`Defeated ${e.name}! +${e.xp} XP, +${e.gold} gold.`);
        if (!e.isBoss) levelUpCheck();
        b.won = true;
        return;
      }
      enemyTurn();
    } else if (action === "defend") {
      b.defending = true;
      battleLog("You brace yourself.");
      enemyTurn();
    } else if (action === "item") {
      if (p.potions > 0) {
        p.potions--;
        const heal = 12;
        p.hp = Math.min(p.maxHp, p.hp + heal);
        battleLog(`You drink a potion. +${heal} HP.`);
        enemyTurn();
      } else {
        battleLog("No potions left!");
      }
    } else if (action === "run") {
      if (Math.random() < 0.6) {
        battleLog("Got away safely.");
        state.screen = "explore";
        state.battle = null;
        return;
      }
      battleLog("Could not escape!");
      enemyTurn();
    }
  }

  function continueAfterBattle() {
    const wasBoss = state.battle.enemy.isBoss;
    state.battle = null;
    state.screen = wasBoss ? "win" : "explore";
  }

  function restart() {
    initGame();
  }

  function handleInput(action) {
    switch (state.screen) {
      case "title":
        if (action === "select") state.screen = "explore";
        break;
      case "explore":
        if (action === "up") movePlayer(0, -1);
        else if (action === "down") movePlayer(0, 1);
        else if (action === "left") movePlayer(-1, 0);
        else if (action === "right") movePlayer(1, 0);
        break;
      case "battle": {
        const b = state.battle;
        if (b.won) {
          if (action === "select") continueAfterBattle();
          break;
        }
        const opts = ["attack", "defend", "item", "run"];
        if (action === "up") b.cursor = (b.cursor + 3) % 4;
        else if (action === "down") b.cursor = (b.cursor + 1) % 4;
        else if (action === "select") battleAction(opts[b.cursor]);
        break;
      }
      case "gameover":
      case "win":
        if (action === "select") restart();
        break;
    }
    render();
  }

  const SYMBOLS = { wall: "#", floor: "", stairs: ">", boss: "☠", potion: "!", gold: "$" };

  function renderExploreHud() {
    const p = state.player;
    const pct = Math.max(0, Math.round((p.hp / p.maxHp) * 100));
    return `<span>F${state.floor} Lv${p.level}</span>` +
      `<div id="hpbar-wrap"><div id="hpbar" style="width:${pct}%"></div></div>` +
      `<span>G${p.gold} ✦${p.potions}</span>`;
  }

  function renderGrid() {
    const p = state.player;
    let html = '<div id="grid">';
    for (let y = 0; y < SIZE; y++) {
      for (let x = 0; x < SIZE; x++) {
        const isPlayer = x === p.x && y === p.y;
        const visited = state.visited.has(x + "," + y);
        if (!visited && !isPlayer) {
          html += '<div class="cell fog"></div>';
          continue;
        }
        const cell = state.map[y][x];
        const cls = isPlayer ? "player" : cell;
        const sym = isPlayer ? "@" : SYMBOLS[cell] || "";
        html += `<div class="cell ${cls}">${sym}</div>`;
      }
    }
    html += "</div>";
    return html;
  }

  function renderTitle() {
    document.getElementById("hud-top").innerHTML = "";
    document.getElementById("viewport").innerHTML = `
      <div class="title-screen">
        <h1>RAY-BAN<br>DUNGEON</h1>
        <p>A tiny turn-based RPG</p>
        <p class="blink">PRESS SEL TO BEGIN</p>
      </div>`;
    document.getElementById("log").innerHTML = "";
  }

  function renderExplore() {
    document.getElementById("hud-top").innerHTML = renderExploreHud();
    document.getElementById("viewport").innerHTML = renderGrid();
    document.getElementById("log").innerHTML = state.messages.map((m) => `<div>${m}</div>`).join("");
  }

  function renderBattle() {
    const p = state.player, b = state.battle, e = b.enemy;
    document.getElementById("hud-top").innerHTML = `<span>F${state.floor} Lv${p.level}</span><span>BATTLE</span>`;
    const pPct = Math.max(0, Math.round((p.hp / p.maxHp) * 100));
    const ePct = Math.max(0, Math.round((e.hp / e.maxHp) * 100));
    const opts = ["Attack", "Defend", "Item", "Run"];
    let menuHtml = "";
    if (!b.won) {
      menuHtml = '<div class="menu">' +
        opts.map((o, i) => `<div class="opt${i === b.cursor ? " sel" : ""}">${i === b.cursor ? "&gt; " : "  "}${o}</div>`).join("") +
        "</div>";
    } else {
      menuHtml = '<div class="menu"><div class="opt sel">&gt; Continue</div></div>';
    }
    document.getElementById("viewport").innerHTML = `
      <div class="battle-screen">
        <div class="combatant">
          <div class="name-row"><span>${e.name}</span><span>${e.hp}/${e.maxHp}</span></div>
          <div class="bar-wrap"><div class="bar enemy" style="width:${ePct}%"></div></div>
        </div>
        <div class="combatant">
          <div class="name-row"><span>You</span><span>${p.hp}/${p.maxHp}</span></div>
          <div class="bar-wrap"><div class="bar player" style="width:${pPct}%"></div></div>
        </div>
        ${menuHtml}
      </div>`;
    document.getElementById("log").innerHTML = b.log.map((m) => `<div>${m}</div>`).join("");
  }

  function renderGameOver() {
    const p = state.player;
    document.getElementById("hud-top").innerHTML = "";
    document.getElementById("viewport").innerHTML = `
      <div class="end-screen">
        <h2>YOU PERISHED</h2>
        <p>Reached floor ${state.floor}, level ${p.level}</p>
        <p class="blink">PRESS SEL TO RESTART</p>
      </div>`;
    document.getElementById("log").innerHTML = "";
  }

  function renderWin() {
    const p = state.player;
    document.getElementById("hud-top").innerHTML = "";
    document.getElementById("viewport").innerHTML = `
      <div class="end-screen">
        <h2>OCCLUDER DEFEATED</h2>
        <p>Level ${p.level} &middot; ${p.gold} gold</p>
        <p class="blink">PRESS SEL TO PLAY AGAIN</p>
      </div>`;
    document.getElementById("log").innerHTML = "";
  }

  function render() {
    if (state.screen === "title") renderTitle();
    else if (state.screen === "explore") renderExplore();
    else if (state.screen === "battle") renderBattle();
    else if (state.screen === "gameover") renderGameOver();
    else if (state.screen === "win") renderWin();
  }

  const KEY_MAP = {
    ArrowUp: "up", w: "up", W: "up",
    ArrowDown: "down", s: "down", S: "down",
    ArrowLeft: "left", a: "left", A: "left",
    ArrowRight: "right", d: "right", D: "right",
    Enter: "select", " ": "select",
    Escape: "back", Backspace: "back",
  };

  document.addEventListener("keydown", (e) => {
    const action = KEY_MAP[e.key];
    if (!action) return;
    e.preventDefault();
    handleInput(action);
  });

  document.querySelectorAll(".ctl").forEach((btn) => {
    btn.addEventListener("click", () => handleInput(btn.dataset.action));
  });

  initGame();
  render();
})();
