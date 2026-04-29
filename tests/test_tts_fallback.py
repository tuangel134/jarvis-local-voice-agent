from jarvis.utils.text import split_for_tts


def test_split_for_tts():
    text = 'Hola. ' * 200
    parts = split_for_tts(text, max_chars=120)
    assert len(parts) > 1
    assert all(len(p) <= 140 for p in parts)
