(function (global) {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";

  // 16x16 pixel-art bot blueprints. Every row must be 16 chars wide.
  // Legend:
  //   . transparent | # dark outline | c primary chassis | h highlight
  //   s shadow      | a accent crest | e eye / visor     | g chest gem
  //   b boot / dock base
  const MATRICES = {
    prime: [
      "....a......a....",
      "...#a#....#a#...",
      "..#ccc####ccc#..",
      "..#hhhhhhhhhh#..",
      "..#h########h#..",
      "..#h#eeeeee#h#..",
      "..#h#eeeeee#h#..",
      "..#s########s#..",
      "...###ssss###...",
      "..#hhh#gg#hhh#..",
      ".#cchh#gg#hhcc#.",
      ".#ssccccccccss#.",
      "..##ssssssss##..",
      "....#cc##cc#....",
      "...#bb#..#bb#...",
      "...####..####...",
    ],
    lead: [
      ".......aa.......",
      ".......#........",
      "...##########...",
      "..#hhhhhhhhhh#..",
      "..#cc######cc#..",
      "..#c#eeeeee#c#..",
      "..#c#eeeeee#c#..",
      "..#ss######ss#..",
      "...##########...",
      ".#aahhhggghhaa#.",
      ".#cc#cccccc#cc#.",
      ".#ss#cccccc#ss#.",
      "..##.ssssss.##..",
      "....#cc##cc#....",
      "...#bb#..#bb#...",
      "...####..####...",
    ],
    coder: [
      "......####......",
      "....##hhhh##....",
      "..#a#cccccc#a#..",
      "..#a#h####h#a#..",
      "..#c#eeeeee#c#..",
      "..#c#eeeeee#c#..",
      "..#s########s#..",
      "...###ssss###...",
      "..#cc#hhhh#cc#..",
      ".#cc.#cggc#.cc#.",
      ".#ss.#cccc#.ss#.",
      ".....#ssss#.....",
      "....#cc##cc#....",
      "....#bb##bb#....",
      "...###....###...",
      "................",
    ],
    designer: [
      "...aaaaaaaa.....",
      "..#hhhhhhhh##...",
      "..#cccccccccc#..",
      "..#h########h#..",
      "..#h#ee##ee#h#..",
      "..#h#e####e#h#..",
      "..#s########s#..",
      "...##########...",
      "..#hhh#gg#hhh#..",
      ".#cc#ccagac#cc#.",
      ".#ss.#cccc#.ss#.",
      ".....#ssss#.....",
      "....#cc##cc#....",
      "....#bb##bb#....",
      "...###....###...",
      "................",
    ],
    critic: [
      ".......a........",
      "......#h#.......",
      "...###ccc###....",
      "..#hhhhhhhhh#...",
      "..#c###eee##c#..",
      "..#c#s#eee#cc#..",
      "..#s###eee##s#..",
      "...##########...",
      "..#cc#gggg#cc#..",
      ".#cc.#gbbg#.cc#.",
      ".#ss.#gbbg#.ss#.",
      ".....#gggg#.....",
      "....#cc##cc#....",
      "....#bb##bb#....",
      "...###....###...",
      "................",
    ],
    architect: [
      "..a..........a..",
      "..#..........#..",
      "..############..",
      "..#hhhhhhhhhh#..",
      "..#c########c#..",
      "..#c#ee##ee#c#..",
      "..#c########c#..",
      "..#ssssssssss#..",
      "..############..",
      ".#cc#ghhhhg#cc#.",
      ".#ss#cccccc#ss#.",
      "....#ssssss#....",
      "....#cc##cc#....",
      "....#bb##bb#....",
      "...###....###...",
      "................",
    ],
    specialist: [
      ".......aa.......",
      ".......##.......",
      "...##########...",
      "..#hhhhhhhhhh#..",
      "..#c########c#..",
      "..#c#ee##ee#c#..",
      "..#c#ee##ee#c#..",
      "..#ssssssssss#..",
      "...##########...",
      "..#cc#hggc#cc#..",
      ".#cc.#cccc#.cc#.",
      ".#ss.#ssss#.ss#.",
      "....#cc##cc#....",
      "....#bb##bb#....",
      "...###....###...",
      "................",
    ],
  };

  const ARCHETYPE_COLORS = {
    prime: {
      c: "#6b1d33",
      h: "#9f2c4b",
      s: "#42111f",
      a: "#fb7185",
      e: "#ff4d6d",
      g: "#38bdf8",
      b: "#334155",
    },
    lead: {
      c: "#785116",
      h: "#b47b1e",
      s: "#4a300b",
      a: "#fde68a",
      e: "#fbbf24",
      g: "#38bdf8",
      b: "#334155",
    },
    coder: {
      c: "#164e63",
      h: "#0e7490",
      s: "#083344",
      a: "#67e8f9",
      e: "#22d3ee",
      g: "#a5f3fc",
      b: "#334155",
    },
    designer: {
      c: "#581c87",
      h: "#7e22ce",
      s: "#3b0764",
      a: "#f0abfc",
      e: "#e879f9",
      g: "#2dd4bf",
      b: "#334155",
    },
    critic: {
      c: "#065f46",
      h: "#059669",
      s: "#064e3b",
      a: "#6ee7b7",
      e: "#34d399",
      g: "#38bdf8",
      b: "#1d4ed8",
    },
    architect: {
      c: "#312e81",
      h: "#4338ca",
      s: "#1e1b4b",
      a: "#a5b4fc",
      e: "#818cf8",
      g: "#38bdf8",
      b: "#334155",
    },
    specialist: {
      c: "#1e3a5f",
      h: "#2b5285",
      s: "#13243b",
      a: "#93c5fd",
      e: "#60a5fa",
      g: "#34d399",
      b: "#334155",
    },
  };

  function resolvePalette(kind, state) {
    const base = ARCHETYPE_COLORS[kind] || ARCHETYPE_COLORS.specialist;
    if (state === "active") {
      return { "#": "#090d16", ...base };
    }
    if (state === "standby") {
      return {
        "#": "#090d16",
        c: "#243044",
        h: "#334155",
        s: "#182030",
        a: "#64748b",
        e: base.e,
        g: "#475569",
        b: "#1e293b",
      };
    }
    if (state === "archived") {
      return {
        "#": "#090d16",
        c: "#1e2430",
        h: "#2a3242",
        s: "#141820",
        a: "#475569",
        e: "#475569",
        g: "#334155",
        b: "#1e2430",
      };
    }
    return {
      "#": "#090d16",
      c: "#202736",
      h: "#2e374d",
      s: "#151a24",
      a: "#64748b",
      e: "#475569",
      g: "#334155",
      b: "#1e293b",
    };
  }

  function archetypeForRole(roleObj) {
    if (!roleObj) return "specialist";
    const aid = String(roleObj.agent_id || "").toLowerCase();
    const role = String(roleObj.role || "").toLowerCase();
    if (aid === "ultron-prime" || role === "prime") return "prime";
    if (role === "lead") return "lead";
    if (
      roleObj.write_tools === false ||
      /(qa|test|review|critic|audit|slop)/.test(role)
    ) {
      return "critic";
    }
    if (/(ui|design|ux|visual|craft|drafter)/.test(role)) return "designer";
    if (/(coder|dev|backend|frontend|engineer|impl)/.test(role)) return "coder";
    if (/(spec|arch|writ|analy|explor)/.test(role)) return "architect";
    return "specialist";
  }

  function stateForAgent(agentObj, teamObj) {
    if (teamObj && teamObj.archived) return "archived";
    const status = String((agentObj && agentObj.status) || "disabled").toLowerCase();
    if (status === "unregistered") return "unregistered";
    if (status === "active") return "active";
    return "standby";
  }

  function renderBotSvg(kind, state, size) {
    const pxSize = Number(size) || 40;
    const grid = MATRICES[kind] || MATRICES.specialist;
    const palette = resolvePalette(kind, state || "standby");

    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("width", String(pxSize));
    svg.setAttribute("height", String(pxSize));
    svg.setAttribute("shape-rendering", "crispEdges");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("class", "bot-svg state-" + (state || "standby"));

    for (let y = 0; y < grid.length; y++) {
      const row = grid[y];
      let x = 0;
      while (x < row.length) {
        const ch = row[x];
        if (ch === ".") {
          x++;
          continue;
        }
        // Merge horizontal runs of identical pixel color into 1 rect to keep DOM crisp and fast
        let run = 1;
        while (x + run < row.length && row[x + run] === ch) {
          run++;
        }
        const rect = document.createElementNS(SVG_NS, "rect");
        rect.setAttribute("x", String(x));
        rect.setAttribute("y", String(y));
        rect.setAttribute("width", String(run));
        rect.setAttribute("height", "1");
        rect.setAttribute("fill", palette[ch] || "#64748b");
        if (ch === "e" && state === "standby") {
          rect.setAttribute("fill-opacity", "0.35");
        }
        svg.appendChild(rect);
        x += run;
      }
    }

    // Subtle charging-dock floor pixel bar when a standing permanent bot is sleeping
    if (state === "standby") {
      const dock = document.createElementNS(SVG_NS, "rect");
      dock.setAttribute("x", "2");
      dock.setAttribute("y", "15");
      dock.setAttribute("width", "12");
      dock.setAttribute("height", "1");
      dock.setAttribute("fill", "#334155");
      svg.appendChild(dock);
    }

    return svg;
  }

  global.UltronSprites = {
    archetypeForRole: archetypeForRole,
    stateForAgent: stateForAgent,
    renderBotSvg: renderBotSvg,
  };
})(window);
