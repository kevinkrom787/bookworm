-- Migration 003: Seed 8 new starter characters into existing profiles
-- Each INSERT is guarded by NOT EXISTS on avatar_emoji so it is idempotent.

INSERT INTO characters (profile_id, name, canonical_description, avatar_emoji, is_starter)
SELECT id, 'Splash',
  'a curious octopus with eight curly tentacles, bright wide eyes, and shimmering teal skin',
  '🐙', 1
FROM child_profiles
WHERE NOT EXISTS (SELECT 1 FROM characters WHERE profile_id = child_profiles.id AND avatar_emoji = '🐙');

INSERT INTO characters (profile_id, name, canonical_description, avatar_emoji, is_starter)
SELECT id, 'Stella',
  'a magical unicorn with a shimmering silver horn, flowing rainbow mane, and a coat of pale gold',
  '🦄', 1
FROM child_profiles
WHERE NOT EXISTS (SELECT 1 FROM characters WHERE profile_id = child_profiles.id AND avatar_emoji = '🦄');

INSERT INTO characters (profile_id, name, canonical_description, avatar_emoji, is_starter)
SELECT id, 'Rex',
  'a friendly young T-rex with tiny arms, wide bright eyes, a big toothy grin, and cheerful green scales',
  '🦖', 1
FROM child_profiles
WHERE NOT EXISTS (SELECT 1 FROM characters WHERE profile_id = child_profiles.id AND avatar_emoji = '🦖');

INSERT INTO characters (profile_id, name, canonical_description, avatar_emoji, is_starter)
SELECT id, 'Stripe',
  'a bold tiger cub with vivid orange and black stripes, a fluffy chest, and curious amber eyes',
  '🐯', 1
FROM child_profiles
WHERE NOT EXISTS (SELECT 1 FROM characters WHERE profile_id = child_profiles.id AND avatar_emoji = '🐯');

INSERT INTO characters (profile_id, name, canonical_description, avatar_emoji, is_starter)
SELECT id, 'Bay',
  'a gentle blue whale with a wide friendly smile, a pale spotted belly, and soft round fins',
  '🐋', 1
FROM child_profiles
WHERE NOT EXISTS (SELECT 1 FROM characters WHERE profile_id = child_profiles.id AND avatar_emoji = '🐋');

INSERT INTO characters (profile_id, name, canonical_description, avatar_emoji, is_starter)
SELECT id, 'Shadow',
  'a wise silver wolf with soft grey fur, bright moonlit eyes, and a thick bushy tail',
  '🐺', 1
FROM child_profiles
WHERE NOT EXISTS (SELECT 1 FROM characters WHERE profile_id = child_profiles.id AND avatar_emoji = '🐺');

INSERT INTO characters (profile_id, name, canonical_description, avatar_emoji, is_starter)
SELECT id, 'Mochi',
  'a round fluffy panda with big black eye patches, a cheerful grin, and a bamboo sprig tucked behind one ear',
  '🐼', 1
FROM child_profiles
WHERE NOT EXISTS (SELECT 1 FROM characters WHERE profile_id = child_profiles.id AND avatar_emoji = '🐼');

INSERT INTO characters (profile_id, name, canonical_description, avatar_emoji, is_starter)
SELECT id, 'Scout',
  'a majestic golden eagle with keen amber eyes, broad brown-and-white wings, and a proud upright crest',
  '🦅', 1
FROM child_profiles
WHERE NOT EXISTS (SELECT 1 FROM characters WHERE profile_id = child_profiles.id AND avatar_emoji = '🦅');
