from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import requests
import pypinyin
import re
import os
import sys
import pykakasi
from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files('pykakasi')
app = Flask(__name__)
CORS(app)


# Initialize pykakasi with comprehensive error handling
def initialize_kakasi():
    try:
        # First try normal initialization
        return pykakasi.kakasi()
    except (FileNotFoundError, ImportError) as e:
        print(f"Initial pykakasi initialization failed: {e}")
        print("Attempting standalone mode workaround...")

        try:
            # Try to find the data file in alternative locations
            possible_paths = [
                os.path.join(os.path.dirname(pykakasi.__file__), 'data', 'kanwadict4.db'),
                os.path.join(sys._MEIPASS, 'pykakasi', 'data', 'kanwadict4.db') if getattr(sys, 'frozen', False) else None,
                os.path.join(os.path.dirname(__file__), 'pykakasi', 'data', 'kanwadict4.db'),
            ]

            for path in filter(None, possible_paths):
                if os.path.exists(path):
                    os.environ['KAKASI_DICT_PATH'] = path
                    return pykakasi.kakasi()

            # If no path found, try with a different dictionary file
            for dict_file in ['kanwadict4.db', 'kanwadict3.db', 'lkanwadictu.db']:
                try:
                    from pykakasi import kanji
                    kanji.JISYO = dict_file
                    return pykakasi.kakasi()
                except:
                    continue

            raise FileNotFoundError("Could not find any dictionary files")

        except Exception as e:
            print(f"Fallback initialization failed: {e}")

            class DummyConverter:
                def convert(self, text):
                    return [{'orig': text, 'hira': text, 'hepburn': text}]

            print("Using dummy converter - furigana functionality will be limited")
            return DummyConverter()

        except Exception as e:
            print(f"Fallback initialization failed: {e}")

            # Provide a dummy converter that won't crash the app
            class DummyConverter:
                def convert(self, text):
                    return [{'orig': text, 'hira': text, 'hepburn': text}]

            print("Using dummy converter - furigana functionality will be limited")
            return DummyConverter()


kks = initialize_kakasi()

# Supported languages with metadata
LANGUAGES = {
    'ja': {'name': 'Japanese', 'has_furigana': True, 'rtl': False},
    'ko': {'name': 'Korean', 'has_furigana': False, 'rtl': False},
    'zh': {'name': 'Chinese', 'has_furigana': False, 'rtl': False},
    'ar': {'name': 'Arabic', 'has_furigana': False, 'rtl': True}
}

# Translation API configurations
TRANSLATION_APIS = [
    {
        'name': 'LibreTranslate',
        'url': 'https://libretranslate.de/translate',
        'method': 'POST',
        'data': lambda text, source: {
            'q': text,
            'source': source,
            'target': 'en',
            'format': 'text'
        }
    },
    {
        'name': 'MyMemory',
        'url': 'https://api.mymemory.translated.net/get',
        'method': 'GET',
        'params': lambda text, source: {
            'q': text,
            'langpair': f'{source}|en'
        },
        'extract': lambda r: r.json()['responseData']['translatedText']
    }
]


def generate_furigana(text):
    """Generate basic furigana using pykakasi"""
    result = kks.convert(text)
    furigana_elements = []

    for item in result:
        if item['orig'] != item['hira']:
            furigana_elements.append({
                'text': item['orig'],
                'reading': item['hira']
            })
        else:
            furigana_elements.append({
                'text': item['orig'],
                'reading': None
            })

    return furigana_elements


def get_pronunciation(text, lang):
    """Generate pronunciation guides for different languages"""
    if lang == 'ja':
        result = kks.convert(text)
        romaji = " ".join([item['hepburn'] for item in result])
        return {'romaji': romaji}
    elif lang == 'zh':
        pinyin = " ".join([item[0] for item in pypinyin.lazy_pinyin(text)])
        return {'pinyin': pinyin}
    elif lang == 'ar':
        return {'arabic': text}  # Arabic pronunciation is the text itself
    return {}


@app.route('/')
def home():
    return render_template('index.html', languages=LANGUAGES)


@app.route('/furigana', methods=['POST'])
def furigana():
    data = request.get_json()
    text = data.get('text', '').strip()
    if not text:
        return jsonify({'error': 'No text provided'}), 400

    furigana_data = generate_furigana(text)
    return jsonify({'furigana': furigana_data})


@app.route('/translate', methods=['POST'])
def translate():
    data = request.get_json()
    text = data.get('text', '').strip()
    source_lang = data.get('source_lang', 'ja')

    if not text:
        return jsonify({'error': 'No text provided'}), 400
    if source_lang not in LANGUAGES:
        return jsonify({'error': 'Unsupported language'}), 400

    for api in TRANSLATION_APIS:
        try:
            if api['method'] == 'POST':
                response = requests.post(
                    api['url'],
                    json=api['data'](text, source_lang),
                    timeout=5
                )
            else:
                response = requests.get(
                    api['url'],
                    params=api['params'](text, source_lang),
                    timeout=5
                )

            response.raise_for_status()
            translation = api.get('extract', lambda r: r.json()['translatedText'])(response)

            return jsonify({
                'translation': translation,
                'service': api['name'],
                'source_lang': LANGUAGES[source_lang]['name'],
                'original_text': text,
                'pronunciation': get_pronunciation(text, source_lang),
                'has_furigana': LANGUAGES[source_lang]['has_furigana'],
                'is_rtl': LANGUAGES[source_lang]['rtl']
            })

        except Exception as e:
            print(f"Failed with {api['name']}: {str(e)}")
            continue

    return jsonify({'error': 'All translation services failed'}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
