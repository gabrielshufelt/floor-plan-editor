# Floor Plan Nav Graph Editor

Lightweight tools for converting architectural floor plan images into navigable indoor maps. These tools were developed to help create navigation graphs for the campus exploration app, as part of SOEN 390.
<img width="1000" src="https://github.com/user-attachments/assets/ca45a1e1-89a7-4282-9a45-86ac2807f51e" />
<img width="1000" src="https://github.com/user-attachments/assets/b07a2d7f-a82d-4c77-a0ae-fed0cae3bf97" />

## Tools

### `graph_editor.html` — Navigation Graph Editor
A browser-based editor for placing navigation nodes on a floor plan image and connecting them with edges. Produces JSON files consumed directly by the React Native app's Dijkstra pathfinding engine.

**Open it:** just double-click the file or drag it into any browser — no server, no install, no build step.

**Basic workflow:**
1. Click **Image** to load a cleaned floor plan PNG
2. Use **N** to add a node
2. Use **R**, **D**, **W** to place room, doorway, and waypoint nodes
3. Switch to **E** (edge tool) and click two nodes to connect them

**Keyboard shortcuts:**

| Key | Action |
|-----|--------|
| `V` | Select / move tool |
| `N` | Node tool (uses current type) |
| `E` | Edge tool |
| `R` | Place Room node |
| `D` | Place Doorway node |
| `W` | Place Waypoint node |
| `Del` | Delete selected node or edge |
| `Ctrl+Z / Y` | Undo / Redo |
| `Ctrl+S` | Save |
| `Ctrl+O` | Load graph JSON |
| `0` | Fit view |
| Scroll | Zoom |
| Middle drag | Pan (any tool) |

**Node types:**

| Letter | Type | Color |
|--------|------|-------|
| R | Room | Blue |
| D | Doorway | Green |
| W | Hallway Waypoint | Yellow |
| S | Stair Landing | Red |
| E | Elevator Door | Purple |
| B | Building Entry/Exit | Cyan |

### Limitations

**Images over 3 MB are rejected;** very large images may not persist across refreshes (localStorage limit ~5–10 MB)

---

### `floor_plan_cleaner.py` — Floor Plan Cleaner
Strips clutter from raw architectural PNG floor plans (room numbers, furniture, hatching, labels), leaving only walls, door openings, and stair outlines.
As it stands, the script is not reliable, but feel free to experiment with it.

**Setup:**
```bash
pip install -r requirements.txt
```

**Usage:**
```bash
# Drop raw PNGs into temp_floor_plans/, then:
python floor_plan_cleaner.py

# Debug mode — prints connected-component sizes and saves intermediate stages:
python floor_plan_cleaner.py --debug
```

Output goes to `cleaned_floor_plans/`. Debug stage images go to `debug_stages/`.

**Tuning for a new building:** run with `--debug`, read the CC size report, then adjust `MIN_CC_AREA_PASS1` and `MIN_CC_AREA_PRE_CLOSE` in the script so they sit between the largest non-wall component and the wall network. See the parameter comments in the script for details.
