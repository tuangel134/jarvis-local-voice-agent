from jarvis.llm.router import LLMRouter


def base_cfg():
    return {
        'llm': {
            'complexity_threshold': 0.65,
            'use_remote_for_complex_tasks': True,
            'local_model': 'qwen2.5:3b',
            'heavy_provider': 'groq',
            'heavy_model': 'llama-3.3-70b-versatile',
        },
        'ollama': {'base_url': 'http://localhost:11434'},
        'groq': {'api_key_env': 'GROQ_API_KEY'},
        'openai': {'api_key_env': 'OPENAI_API_KEY'},
        'openrouter': {'api_key_env': 'OPENROUTER_API_KEY'},
    }


def test_heavy_keywords_remote():
    r = LLMRouter(base_cfg())
    assert r.should_use_remote('usa la IA avanzada para analizar este error')


def test_simple_local():
    r = LLMRouter(base_cfg())
    assert not r.should_use_remote('qué hora es')
