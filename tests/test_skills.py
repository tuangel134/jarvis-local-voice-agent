from jarvis.brain.intent_classifier import Intent
from jarvis.skills.shell_safe import ShellSafeSkill


def cfg():
    return {
        'security': {
            'allow_shell_commands': True,
            'dangerous_patterns': ['rm -rf', 'sudo'],
            'allowed_shell_commands': ['ls', 'pwd', 'df', 'free', 'uptime', 'systemctl', 'xdg-open', 'find', 'cat', 'grep'],
            'allowed_urls': ['https://www.youtube.com'],
            'allowed_apps': ['firefox'],
        }
    }


def test_shell_blocks_rm_rf():
    skill = ShellSafeSkill(cfg())
    intent = Intent('safe_shell', entities={'command': 'rm -rf ~'}, raw_text='rm -rf ~')
    result = skill.run(intent, intent.entities, {})
    assert not result['ok']


def test_shell_allows_pwd():
    skill = ShellSafeSkill(cfg())
    intent = Intent('safe_shell', entities={'command': 'pwd'}, raw_text='pwd')
    result = skill.run(intent, intent.entities, {})
    assert result['ok']
