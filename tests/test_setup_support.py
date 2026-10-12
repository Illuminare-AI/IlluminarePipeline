"""Setup must preserve credentials and remain safe to run repeatedly."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    'setup_support', Path(__file__).resolve().parents[1] / 'scripts/setup-support.py'
)
setup_support = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup_support)


def test_env_update_preserves_credentials_and_is_repeatable(tmp_path):
    path = tmp_path / '.env'
    path.write_text(
        '# keep this comment\nANTHROPIC_API_KEY=private-test-key\n'
        'export VISION_MODEL=old\nVISION_ENABLED=false\n', encoding='utf-8-sig'
    )
    updates = {'VISION_MODEL': 'local-model', 'VISION_ENABLED': 'true', 'NEW_SETTING': '600'}
    setup_support.update_env(path, updates)
    first = path.read_bytes()
    setup_support.update_env(path, updates)
    assert path.read_bytes() == first
    text = path.read_text(encoding='utf-8')
    assert 'ANTHROPIC_API_KEY=private-test-key' in text
    assert '# keep this comment' in text
    assert "VISION_MODEL='local-model'" in text
    assert text.count('NEW_SETTING=') == 1


def test_env_creation_uses_example_without_modifying_it(tmp_path):
    path = tmp_path / '.env'
    example = tmp_path / '.env.example'
    example.write_text('LLM_BACKEND=fake\nVISION_ENABLED=false\n', encoding='utf-8')
    original = example.read_bytes()
    setup_support.update_env(path, {'VISION_ENABLED': 'true'})
    assert example.read_bytes() == original
    assert 'LLM_BACKEND=fake' in path.read_text(encoding='utf-8')
    assert "VISION_ENABLED='true'" in path.read_text(encoding='utf-8')
