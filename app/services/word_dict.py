"""
Child-friendly definitions for common story vocabulary words.
Used as an instant fallback before calling Gemma.
"""

STORY_WORDS: dict[str, dict] = {
    # A
    "adventurous": {"phonetic": "/ədˈvɛn.tʃər.əs/", "definition": "Willing to try new and exciting things.", "example": "The adventurous fox climbed to the very top of the hill."},
    "ancient":     {"phonetic": "/ˈeɪn.ʃənt/",       "definition": "Very, very old — from a long time ago.",  "example": "They found an ancient map hidden inside the wall."},
    "announced":   {"phonetic": "/əˈnaʊnst/",         "definition": "Said something loudly so everyone could hear.", "example": "The queen announced that the festival would begin."},
    "anxious":     {"phonetic": "/ˈæŋk.ʃəs/",        "definition": "Feeling worried or nervous about something.", "example": "She felt anxious before crossing the rickety bridge."},
    "astonished":  {"phonetic": "/əˈstɒn.ɪʃt/",      "definition": "Very surprised — almost too surprised to speak.", "example": "He was astonished to find a tiny door in the oak tree."},
    # B
    "bewildered":  {"phonetic": "/bɪˈwɪl.dərd/",     "definition": "So confused you don't know what to do next.", "example": "The little owl looked bewildered by all the noise."},
    "blossom":     {"phonetic": "/ˈblɒs.əm/",         "definition": "A flower, or to grow and become better.", "example": "The cherry blossom filled the air with a sweet smell."},
    "brave":       {"phonetic": "/breɪv/",             "definition": "Not afraid to do hard or scary things.", "example": "The brave mouse stood up to the enormous cat."},
    "brilliant":   {"phonetic": "/ˈbrɪl.i.ənt/",      "definition": "Very bright, or very clever and impressive.", "example": "A brilliant flash of light lit up the dark cave."},
    # C
    "cautious":    {"phonetic": "/ˈkɔː.ʃəs/",         "definition": "Being careful and watching out for danger.", "example": "The deer was cautious as it stepped out of the forest."},
    "cheerful":    {"phonetic": "/ˈtʃɪər.fəl/",       "definition": "Happy and in a good mood.", "example": "She gave a cheerful wave as she ran past."},
    "courageous":  {"phonetic": "/kəˈreɪ.dʒəs/",      "definition": "Very brave, even when things are hard or scary.", "example": "It was courageous of him to stand up for his friend."},
    "curious":     {"phonetic": "/ˈkjʊər.i.əs/",      "definition": "Wanting to find out about something new.", "example": "The curious kitten poked its nose into every corner."},
    "crept":       {"phonetic": "/krɛpt/",             "definition": "Moved very slowly and quietly.", "example": "She crept down the stairs so nobody would hear her."},
    # D
    "dazzling":    {"phonetic": "/ˈdæz.lɪŋ/",         "definition": "So bright or beautiful it almost hurts to look.", "example": "The dazzling stars filled the whole sky."},
    "delighted":   {"phonetic": "/dɪˈlaɪ.tɪd/",       "definition": "Very happy and pleased.", "example": "The children were delighted when it started to snow."},
    "determined":  {"phonetic": "/dɪˈtɜː.mɪnd/",      "definition": "Having made up your mind and not giving up.", "example": "She was determined to reach the top of the mountain."},
    "discovered":  {"phonetic": "/dɪˈskʌv.ərd/",      "definition": "Found something for the first time.", "example": "He discovered a secret garden behind the old gate."},
    # E
    "enchanted":   {"phonetic": "/ɪnˈtʃɑːn.tɪd/",    "definition": "Under a magic spell, or feeling wonderful magic.", "example": "They walked into the enchanted forest as the moon rose."},
    "enormous":    {"phonetic": "/ɪˈnɔː.məs/",        "definition": "Very, very big — much larger than normal.", "example": "The elephant was enormous, bigger than any animal she had ever seen."},
    "extraordinary": {"phonetic": "/ɪkˈstrɔːr.dɪ.nər.i/", "definition": "Way beyond normal — truly amazing and special.", "example": "She had an extraordinary talent for talking to animals."},
    # F
    "frightened":  {"phonetic": "/ˈfraɪ.tənd/",       "definition": "Feeling scared.", "example": "The frightened puppy hid under the bed during the storm."},
    # G
    "galloped":    {"phonetic": "/ˈɡæl.əpt/",         "definition": "Ran very fast the way a horse does.", "example": "The horse galloped across the field as fast as the wind."},
    "gentle":      {"phonetic": "/ˈdʒɛn.tl/",         "definition": "Soft and kind — not rough at all.", "example": "He had a gentle touch that made the bird feel safe."},
    "gleaming":    {"phonetic": "/ˈɡliː.mɪŋ/",        "definition": "Shining with a soft, steady light.", "example": "She picked up the gleaming coin from the riverbed."},
    "glimmer":     {"phonetic": "/ˈɡlɪm.ər/",         "definition": "A small, faint flicker of light.", "example": "There was a glimmer of light at the end of the tunnel."},
    "glorious":    {"phonetic": "/ˈɡlɔː.ri.əs/",      "definition": "Beautiful and wonderful in a big, impressive way.", "example": "A glorious sunrise turned the whole sky pink and gold."},
    "glowing":     {"phonetic": "/ˈɡloʊ.ɪŋ/",         "definition": "Giving off a warm, steady light.", "example": "The fireflies were glowing softly in the dark garden."},
    "graceful":    {"phonetic": "/ˈɡreɪs.fəl/",       "definition": "Moving in a smooth, beautiful way.", "example": "The swan glided across the lake in a graceful arc."},
    "grateful":    {"phonetic": "/ˈɡreɪt.fəl/",       "definition": "Feeling thankful for something kind that was done.", "example": "She was grateful for the warm soup on such a cold night."},
    "grumpy":      {"phonetic": "/ˈɡrʌm.pi/",         "definition": "In a bad mood and a little cross.", "example": "The grumpy bear didn't want to share his den."},
    # H
    "hesitated":   {"phonetic": "/ˈhɛz.ɪ.teɪ.tɪd/",  "definition": "Paused because you weren't sure what to do.", "example": "She hesitated at the edge of the dark forest."},
    "hollow":      {"phonetic": "/ˈhɒl.oʊ/",          "definition": "Empty inside, like a hole in a tree.", "example": "A family of rabbits lived inside the hollow log."},
    # I
    "immense":     {"phonetic": "/ɪˈmɛns/",           "definition": "So large it's hard to imagine.", "example": "An immense wave crashed against the rocks."},
    # J
    "journey":     {"phonetic": "/ˈdʒɜː.ni/",         "definition": "A long trip from one place to another.", "example": "The journey to the mountains took three whole days."},
    # K
    "kindness":    {"phonetic": "/ˈkaɪnd.nəs/",       "definition": "Being friendly, helpful, and caring to others.", "example": "Her kindness made everyone feel welcome."},
    # L
    "lurked":      {"phonetic": "/lɜːrkt/",            "definition": "Hid and waited, usually in a sneaky way.", "example": "Something lurked in the shadows behind the fence."},
    # M
    "magical":     {"phonetic": "/ˈmæd͡ʒ.ɪ.kəl/",     "definition": "Seeming to have special powers or wonder.", "example": "The forest felt magical in the early morning light."},
    "magnificent": {"phonetic": "/mæɡˈnɪf.ɪ.sənt/",   "definition": "Beautiful, grand, and deeply impressive.", "example": "The magnificent waterfall roared like a thousand drums."},
    "murmured":    {"phonetic": "/ˈmɜː.mərd/",        "definition": "Spoke in a very soft, quiet voice.", "example": "\"Come this way,\" the old owl murmured."},
    "mysterious":  {"phonetic": "/mɪˈstɪər.i.əs/",    "definition": "Strange and hard to explain — full of mystery.", "example": "A mysterious light flickered inside the old cottage."},
    # N
    "nervous":     {"phonetic": "/ˈnɜː.vəs/",         "definition": "Feeling a little worried or shaky inside.", "example": "He was nervous before he stepped onto the stage."},
    # P
    "patient":     {"phonetic": "/ˈpeɪ.ʃənt/",        "definition": "Able to wait calmly without complaining.", "example": "She was patient while the caterpillar slowly became a butterfly."},
    "peculiar":    {"phonetic": "/pɪˈkjuːl.i.ər/",    "definition": "Strange and unusual in an interesting way.", "example": "There was a peculiar smell coming from the old trunk."},
    "plunged":     {"phonetic": "/plʌndʒd/",           "definition": "Jumped or fell quickly into something.", "example": "The otter plunged into the cold river with a splash."},
    "proclaimed":  {"phonetic": "/prəˈkleɪmd/",       "definition": "Said something very loudly and officially.", "example": "The king proclaimed that the whole kingdom would celebrate."},
    "proud":       {"phonetic": "/praʊd/",             "definition": "Feeling good about something you or someone else did.", "example": "She was proud of every star she had collected."},
    # Q
    "quietly":     {"phonetic": "/ˈkwaɪ.ət.li/",      "definition": "Without making much sound.", "example": "He quietly slipped out the door before anyone woke up."},
    # R
    "radiant":     {"phonetic": "/ˈreɪ.di.ənt/",      "definition": "Giving off bright, warm light or happiness.", "example": "Her smile was as radiant as the summer sun."},
    "remarkable":  {"phonetic": "/rɪˈmɑːr.kə.bəl/",   "definition": "Unusual and worth noticing — truly special.", "example": "It was remarkable how fast the tiny seed had grown."},
    "remarkably":  {"phonetic": "/rɪˈmɑːr.kə.bli/",   "definition": "In a way that is really surprising and impressive.", "example": "The bird was remarkably small but had a very loud song."},
    # S
    "scrambled":   {"phonetic": "/ˈskræm.bəld/",      "definition": "Moved quickly in an awkward, hurried way.", "example": "He scrambled up the muddy bank to get away from the water."},
    "shimmered":   {"phonetic": "/ˈʃɪm.ərd/",         "definition": "Shone with a soft, flickering light.", "example": "The lake shimmered in the moonlight."},
    "slithered":   {"phonetic": "/ˈslɪð.ərd/",        "definition": "Moved smoothly along the ground like a snake.", "example": "The little lizard slithered under a warm rock."},
    "soared":      {"phonetic": "/sɔːrd/",             "definition": "Flew very high up into the sky.", "example": "The eagle soared above the clouds without a sound."},
    "sparkled":    {"phonetic": "/ˈspɑːr.kəld/",      "definition": "Shone with many tiny bright flashes of light.", "example": "The river sparkled under the bright morning sun."},
    "stubborn":    {"phonetic": "/ˈstʌb.ərn/",        "definition": "Refusing to change your mind, even when you should.", "example": "The stubborn goat would not move off the bridge."},
    # T
    "tanglement":  {"phonetic": "/ˈtæŋ.ɡəl.mənt/",   "definition": "A twisted, knotted mess that's hard to get out of.", "example": "He found himself in a tanglement of vines and branches."},
    "timid":       {"phonetic": "/ˈtɪm.ɪd/",          "definition": "Shy and a little scared.", "example": "The timid rabbit wouldn't come out until the forest was quiet."},
    "tremendous":  {"phonetic": "/trɪˈmɛn.dəs/",      "definition": "Very large, powerful, or impressive.", "example": "A tremendous storm shook the whole forest."},
    "trembled":    {"phonetic": "/ˈtrɛm.bəld/",       "definition": "Shook a little because of cold, fear, or excitement.", "example": "Her hands trembled as she opened the mysterious box."},
    "tumbled":     {"phonetic": "/ˈtʌm.bəld/",        "definition": "Fell or rolled over in an uncontrolled way.", "example": "He tumbled down the hill and landed in a pile of leaves."},
    # V
    "ventured":    {"phonetic": "/ˈvɛn.tʃərd/",      "definition": "Went somewhere new and a little risky.", "example": "She ventured deep into the forest where no one had gone before."},
    # W
    "wandered":    {"phonetic": "/ˈwɒn.dərd/",        "definition": "Walked slowly without a fixed direction.", "example": "The little bear wandered along the stream until he found honey."},
    "whispered":   {"phonetic": "/ˈwɪs.pərd/",       "definition": "Spoke in a very quiet, soft voice.", "example": "\"Look!\" she whispered, pointing to the sleeping dragon."},
    "wondrous":    {"phonetic": "/ˈwʌn.drəs/",        "definition": "Causing wonder and amazement.", "example": "They stared at the wondrous creature floating in the water."},
}


def lookup(word: str):
    """Case-insensitive lookup. Returns {phonetic, definition, example} or None."""
    return STORY_WORDS.get(word.lower())
