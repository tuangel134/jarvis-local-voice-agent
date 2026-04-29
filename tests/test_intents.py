from jarvis.brain.intent_classifier import IntentClassifier


def cfg():
    return {
        'security': {
            'url_aliases': {'youtube': 'https://www.youtube.com', 'google': 'https://www.google.com'},
        }
    }


def test_open_youtube():
    intent = IntentClassifier(cfg()).classify('abre youtube')
    assert intent.name == 'open_url'
    assert intent.entities['url'] == 'https://www.youtube.com'


def test_time():
    intent = IntentClassifier(cfg()).classify('qué hora es')
    assert intent.name == 'get_time'


def test_service():
    intent = IntentClassifier(cfg()).classify('revisa si jellyfin está activo')
    assert intent.name == 'service_status'
    assert intent.entities['service'] == 'jellyfin'


def test_note():
    intent = IntentClassifier(cfg()).classify('crea una nota que diga revisar build de Expo')
    assert intent.name == 'create_note'
    assert 'revisar build' in intent.entities['content']
