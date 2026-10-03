# Pins & Counters — a Collection tab of its own (2026-09-11)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

Pins and lore counters were two sections of tiles at the foot of the Sealed tab. They aren't
sealed product — nobody sells them — and what a collector does with them is *display* them, so
Zaven asked for their own tab: *"make it look like an actual pin board (and lore counter board,
since they all can kinda snap together) … but also still having a list element and way to see
what you're missing and where it's from."* `/collection?c=pins` → `CollectiblesView` (just above
the Graded collection in Index.html), with three views: **Pin board · Counter board · Checklist**
(`packsink:collectibles:view`). Guarded by `node scripts/test_collectible_boards.mjs`.

- **Ownership did not move.** An owned pin is still a `sealed_collection_items` row under its
  synthetic pid (950000000+n / 960000000+n), so the owned marks, the offline mirror and sharing are
  untouched. `isCollectiblePid` keeps them out of the Sealed tab's unit / SKU counts, its Δ% fetch
  and the viewer compare counts, where pins used to inflate "Units owned".
- **Sharing rides the SEALED visibility axis**, because the data behind the tab lives there: the
  tab appears in viewer mode exactly when sealed is visible (`effectiveSection`).
- **Only the arrangement is new — `139_collectible_boards`:** `collectible_boards(user_id, board,
  layout jsonb)`, one document per board, owner-only RLS, and `get_shared_collectible_boards` for
  viewers under the same rule as `get_shared_collection_sealed`. **Safe to ship first**: until it
  lands, boards save to `localStorage["packsink:collectibleBoards:<uid8>"]` and the tab says
  "saved on this device"; the first load after it lands carries a device-only board up.
- **⚠ `sync === "offline"` writes nothing to the account.** A load that failed for any reason
  other than a missing table leaves the device copy on screen and neither saves nor
  auto-arranges — writing a fresh arrangement over a board we couldn't read would destroy it.
- **The pin board is a 3:2 cork sheet, and placements are fractions of it** (`{x, y, r, z}`), so an
  arrangement made on a monitor reads the same on a phone. **Every pin gets the same AREA, not the
  same width** (`pinWidthOf`): the 41 photos run 0.70–2.35 wide-to-tall, and one fixed width made
  logo pins slivers and pendant pins towers. Aspects are measured as the photos load.
- **The counter board is a honeycomb of POINTY-TOP hexagons because that is the counters' shape** —
  measured off the photos: the Weekly Play dials and most Trove dials are 0.866 wide-to-tall with a
  point at the top. Placements are sockets (`{c, r}`), odd rows shifted half a socket, so
  neighbouring counters butt edge to edge. The test asserts every neighbouring pair of sockets is
  exactly one socket-width apart, which is what makes it a honeycomb. A few Trove dials were
  photographed at an angle (1.25–1.58 wide-to-tall) and sit smaller in their socket.
- One pointer-event drag path for mouse and touch. Items are `touch-action:none`; the board keeps
  `pan-y` so the page still scrolls past it. Drop a counter on another to swap them; drag anything
  off the board to send it back to the tray. Keyboard: arrows move, `[` `]` turn a pin, Delete
  takes it down.
- **⚠ "Take off board" and Delete do NOT un-own anything — deliberate, and it left the boards
  one-way until 2026-09-13.** The add drawer only lists what you DON'T own, so an owned pin is not
  in it, and the only route back to qty 0 was the Checklist tab or the detail modal's stepper —
  neither on screen while you are looking at a board. Reported from the pin board, which is where
  it bites. The mirror of the drawer's "I have it" now sits on both surfaces that can hold
  something you own: **"I don't have it"** on the selection bar, and a **corner ×** on a tray
  thumbnail (`.cb-tray-rm`).
  - **Two-tap** (`armedRemove`, 3s), the graded slot-remove contract — both boards are drag
    surfaces, so a one-tap destructive control is one mis-drop from deleting an owned mark.
  - **⚠ The armed key is `"<kind>|<n>"`, never a bare `n`.** Pin 7 and counter 7 are different
    things: the two lists number from 1 independently.
  - **⚠ The tray's × is a SIBLING of the draggable button, never a child** — a button inside a
    button is invalid markup, and nesting hands its pointerdown straight to `beginDrag`.
    Hover-only on desktop, always there on touch, per the `.tile-magnify-btn` rule.
  - **The board PLACEMENT is left alone**, per `normalizeCollectibleBoard`'s standing contract: it
    keeps a placement for something you no longer own and never draws it, so re-owning puts the pin
    back exactly where it sat.
- **The first look at a never-saved board lays out what you own** (`tidyPins` / `tidyCounters`),
  but only once the store has actually been read. After that, newly owned items wait in the TRAY
  so they never disturb an arranged board — except "I have it" in the add drawer, which is you
  asking to put that one up.
- `normalizeCollectibleBoard` is the only way a stored layout enters: it repairs, never throws. A
  placement for something you no longer own is KEPT (re-own it and it goes back where it was) but
  never drawn, and on the honeycomb it can't hold a socket against a counter you can see.
- The Checklist is the "what am I missing, and where did it come from" view: All / Missing /
  Owned, Pins / Lore counters, a name-or-source search, and the owned stepper. A row opens the
  collectible branch of `SealedDetailModal`.
- The Sealed tab carries a one-line pointer to the new tab, for everyone who remembers the pins
  living there.
