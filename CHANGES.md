# My Story — v0.1 Changes

## New files

| File | Purpose |
|------|---------|
| `migrations/001_story_tables.sql` | 7 new tables: `characters`, `story_history`, `vocab_encounters`, `streaks`, `portrait_cache`, `cloud_spend`, `virtue_rotation` |
| `app/ai_provider.py` | Provider abstraction — `AIProvider` base + `ClaudeProvider`. Swap to on-device by setting `config.AI_PROVIDER`. |
| `app/image_provider.py` | Image provider abstraction — `ImageProvider` base + `ReplicateProvider` (Flux Schnell) + `NullImageProvider` fallback. |
| `app/services/character_service.py` | Character library CRUD. Visual identity fields (`canonical_description`, `style_descriptor`, `generation_seed`, `provider_name`, `model_version`) are **immutable after first write**. |
| `app/services/streak_service.py` | Streak tracking + home screen stat aggregation. |
| `app/services/story_builder.py` | Main orchestrator: virtue rotation → prompt assembly → AI call → per-page moderation → image dispatch → DB write. |
| `app/templates/prompts/bedtime_story.txt` | System prompt template. Edit this file to iterate on story quality without touching code. |
| `app/templates/stories/setup.html` | Screen 1 — character selection, story type, length. |
| `app/templates/stories/generating.html` | Screen 2 — ink-bloom animation, polls `/api/bedtime/<id>/status`. |
| `app/templates/stories/bedtime_read.html` | Screen 3 — page-by-page reader. Tap to advance. Skip-and-defer images. No Pip. |
| `app/templates/stories/recap.html` | Screen 4 — lesson, talk-about-it, vocab cards (mocked), streak, save + goodnight. |
| `app/templates/stories/moderation_stop.html` | Shown when story generation trips the alert moderation tier. |
| `app/static/css/story.css` | All story-specific styles. Uses `atlas.css` tokens. Inherits night-mode and red-light-mode automatically. |
| `tests/__init__.py` | |
| `tests/test_story_builder.py` | Unit tests: virtue rotation, moderation fallback, skip-and-defer, vocab encounters, streaks. One integration test with mock provider. |

## Modified files

| File | Change |
|------|--------|
| `app/__init__.py` | Added `_run_migrations()` — applies all `migrations/*.sql` files at startup. |
| `app/routes/stories.py` | Full rewrite. Old legacy routes preserved. New bedtime story routes under `/stories/new`, `/stories/start`, `/stories/bedtime/<id>/*`. Stats API at `/stories/api/stats`. Characters API at `/stories/api/characters`. |
| `app/templates/home/index.html` | My Story card unlocked (was `soon: true`). Stat bar now fetches from `/stories/api/stats` instead of localStorage. |
| `config.py` | Added `AI_PROVIDER`, `IMAGE_PROVIDER`, `REPLICATE_API_KEY`, `MONTHLY_IMAGE_BUDGET`. |

## One-way doors

These decisions are **irreversible** without a data migration — get them right now:

1. **`characters` visual identity schema** — `canonical_description`, `style_descriptor`, `generation_seed`, `provider_name`, `model_version` are written once and treated as immutable by `lock_visual_identity()`. Changing these fields requires a manual SQL migration and risks visual inconsistency across stories.

2. **`story_history.full_story_json` shape** — stores raw model output as JSON. The page structure (`page_number`, `text`, `illustration_moment`, `image_url`) is now load-bearing in `bedtime_read.html`. Changing the JSON schema requires a migration or app-level version handling.

3. **Virtue rotation window = 3 nights** — stored in `virtue_rotation.last_virtues_used`. Widening or narrowing the window later requires data migration.

4. **Pip's absence from Screen 3** — `bedtime_read.html` has no mascot, no Pip, no speech bubbles. This is a product identity decision. Reversing it means a screen redesign.

## Out of scope (v0.2+)

- On-device model integration (abstraction is in place — add a new `AIProvider` subclass)
- TTS / read-aloud
- Flashcard integration for vocab (mocked in recap — `# TODO v0.2` comment in template)
- Streaming paragraph generation
- Parent pre-review gate
- Sequel/multi-night arcs
- Voice input
- Parent dashboard moderation log UI (events are logged to `story_history.moderation_events`)
- Budget warning UI in parent dashboard (spend tracked in `cloud_spend`)

## Image generation setup (Replicate)

Set `REPLICATE_API_KEY` in your `.env`. Leave it blank and the story renders text-only — images are fully optional and never block the reading experience.

```
REPLICATE_API_KEY=r8_your_key_here
MONTHLY_IMAGE_BUDGET=5.0   # dollars, default $5
```

## Running tests

```bash
source .venv/bin/activate
python -m pytest tests/test_story_builder.py -v
```
