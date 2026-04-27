# Atlas Roadmap

A running doc of ideas, planned features, and deferred work.
Add to this when you have an idea; check it when you're picking up work.

---

## Phase 0 — Stabilization (current branch)

Ongoing cleanup and polish of the V1 feature set before layering on data infrastructure.

---

## Literacy-Grounded Story Vocabulary (HIGH VALUE)

**Problem:** The bedtime story prompt currently uses editorial judgment to pick vocabulary words (e.g., "rich words a child can feel from context"). This is good instinct but not grounded in any formal literacy framework. Every story gets the same guidance regardless of what the child already knows or their current reading level.

**Goal:** Inject each story prompt with child-specific literacy context so vocabulary is calibrated to their actual level and progression.

**What needs to be built:**

1. **`vocabulary_mastery` table** — tracks every word the child has encountered across stories, with a mastery signal (seen once / seen multiple times / quizzed correctly)
2. **`child_literacy_snapshot` table** — running Lexile estimate per child, updated after each story session
3. **Prompt injection** — before generating a story, query these tables and inject context like:
   ```
   Child's current Lexile estimate: 520L
   Words already mastered: [shimmered, cautious, enormous, ...]
   Target 2–3 words just above their comfort zone from band: 500–600L
   ```
4. **Word frequency backing** — use Dolch/Fry lists or a corpus to validate that target words are appropriate for the band (not just good guesses)

**Why it matters:** This is the core of the data moat. Once we're tracking vocabulary across sessions, we have a personalization signal no static reading app has — we know exactly what *this child* knows and what will stretch them.

**Starting point:** `app/templates/prompts/bedtime_story.txt` + `app/services/story_builder.py`

---

## Unified Child Data Model (HIGH VALUE — do before literacy features)

**Problem:** Right now each feature (library, stories, flashcards) has its own siloed data. There's no unified record of what a child has done, learned, or how they're progressing. Personalization is impossible without this foundation.

**Goal:** A single per-child data model that all features read from and write to.

**Entities to model:**

- **Child profile** — age, grade, reading level estimate, preferences (genre, character types)
- **Book progress** — per-book: pages read, last position, completion status, date started/finished
- **Story history** — each bedtime story generated: date, theme, words introduced, words quizzed
- **Vocabulary log** — every word the child has encountered, source (story/flashcard/book), times seen, times quizzed, last seen date, mastery level
- **Flashcard sessions** — session date, cards reviewed, correct/incorrect, band targeted
- **Reading sessions** — time spent reading, pages covered per session (once reader is active)

**Design principles:**
- All activity writes to this model — stories, flashcards, and books are all inputs to the same child record
- Literacy snapshot (Lexile estimate) is derived from this data, not stored separately
- Parent dashboard reads from this model — it should show a unified view of progress, not per-feature stats

**Starting point:** `migrations/` — new schema tables before touching any service layer

---

## Data Moat Infrastructure

See `memory/data_moat_architecture.md` for full design. Key pieces deferred from V1:

- Time-decayed preference signals (genre, length, character preferences)
- Lexile benchmarking against F&P literacy standards
- School district reporting layer (for the institutional GTM)

---

## Deferred / Parking Lot

- **E-reader push** — deprioritized; further down the road after data model and personalization are solid
- **SSE streaming for story generation** — replace polling on `/generating` with Server-Sent Events so story tokens stream to the screen as they arrive. Anthropic API already streams; work is wiring it through to the browser. WebSockets overkill, webhooks wrong pattern (server-to-server only).
- Edge inference (run models on-device for offline use) — long-term after product-market fit
- Parent dashboard expansion — currently shows quiz history; could show vocabulary growth curves (unblocked once unified data model exists)
- Multi-child profiles — currently single-child per account assumption
