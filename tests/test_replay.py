"""Recorded evidence must preserve cloud output and reproduce its own tally."""
import json
from pathlib import Path
from tools.render_replay import page

DATA = json.loads((Path(__file__).resolve().parents[1] / 'docs/replay/recordings.json').read_text())


def test_recording_tallies_come_from_the_actual_responses():
    assert DATA['delivered_notes'] == sum(len(c['result']['notes']) for c in DATA['cases'])
    assert DATA['model_invocations'] == sum(c['result']['model_invocations'] for c in DATA['cases'])
    assert DATA['measurement']['changes'] == sum(c['record']['total_count'] for c in DATA['cases'])
    for c in DATA['cases']:
        assert c['result']['date'] == c['record']['date']
        assert c['result']['controls_version'] == 'shared-v1'
        if any(d['outcome'] == 'repeat_held' for d in c['result']['decisions']):
            assert c['result']['model_invocations'] == 0
            assert not c['result']['notes']
            assert c['impact']['delivery_history']


def test_display_keeps_model_text_and_separates_a_held_repeat_from_an_all_clear():
    import html
    for i, c in enumerate(DATA['cases']):
        rendered = page(DATA, i)
        if c['result']['note']:
            for paragraph in c['result']['note'].split('\n\n'):
                if '--- forward this part' not in paragraph:
                    assert html.escape(paragraph.strip()) in rendered
        elif any(d['outcome'] == 'repeat_held' for d in c['result']['decisions']):
            assert 'not proof the issue is resolved' in rendered
        assert 'not measured accuracy' in rendered
