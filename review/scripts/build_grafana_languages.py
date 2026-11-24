"""Generate the English dashboard from the Korean source without changing queries.

Run from any directory; --check verifies the checked-in generated file.
The translation map lives outside Grafana's auto-provisioned dashboard directory.
"""
import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def english_dashboard(source):
    translations = json.loads((ROOT / 'scripts/grafana.en.json').read_text(encoding='utf-8'))

    def translate(value):
        if isinstance(value, dict):
            # Keys are Grafana field identifiers, never display translations.
            return {key: translate(item) for key, item in value.items()}
        if isinstance(value, list):
            return [translate(item) for item in value]
        if not isinstance(value, str):
            return value
        if value.startswith('http://127.0.0.1:8765'):
            return value.replace('?lang=ko', '?lang=en')
        if value in translations:
            return translations[value]
        if re.search('[가-힣]', value):
            raise ValueError(f'Missing English dashboard translation: {value}')
        return value

    result = translate(source)
    result['uid'] = 'simasset-local-review-en'
    return result


def render(source):
    return json.dumps(english_dashboard(source), ensure_ascii=False, indent=2) + '\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    expected = render(json.loads((ROOT / 'grafana/dashboard.json').read_text(encoding='utf-8')))
    output = ROOT / 'grafana/dashboard-en.json'
    if args.check:
        if not output.exists() or output.read_text(encoding='utf-8') != expected:
            parser.exit(1, 'English dashboard is stale. Run scripts/build_grafana_languages.py\n')
        print('English dashboard is up to date.')
    else:
        output.write_text(expected, encoding='utf-8')
        print(output)
