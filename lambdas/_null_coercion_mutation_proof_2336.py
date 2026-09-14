import json


def f(raw):
    data = json.loads(raw)
    return data.get('day_grade', {}).get('components')
