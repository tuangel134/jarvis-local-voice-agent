#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter

from jarvis.brain.intent_classifier import IntentClassifier
from jarvis.skills.registry import SkillRegistry


def main() -> int:
    parser = argparse.ArgumentParser(description='Smoke test del catálogo e intents Linux de Jarvis.')
    parser.add_argument('phrases', nargs='*', help='Frases a clasificar. Si se omiten, usa ejemplos integrados.')
    parser.add_argument('--search', default='', help='Busca acciones por texto.')
    parser.add_argument('--namespace', default='', help='Filtra namespace para --search.')
    parser.add_argument('--limit', type=int, default=12, help='Límite de resultados en búsquedas.')
    parser.add_argument('--summary', action='store_true', help='Muestra conteo por namespace.')
    args = parser.parse_args()

    reg = SkillRegistry({})
    clf = IntentClassifier({})

    if args.summary:
        counts = Counter(item['action_id'].split('.', 1)[0] for item in reg.list_actions())
        print('NAMESPACES', len(counts))
        for namespace in sorted(counts):
            print(namespace, counts[namespace])

    if args.search:
        items = reg.search_actions(args.search, namespace=args.namespace or None, limit=args.limit)
        print('SEARCH', len(items))
        for item in items:
            print(f"{item['action_id']} {item['risk_label']} score={item.get('match_score', '')}")

    phrases = args.phrases or [
        'abre firefox',
        'que programas estan abiertos',
        'abre descargas',
        'que hay en documentos',
        'abre el segundo resultado',
        'estado del sistema',
        'como va jarvis',
        'subele',
        'quita el silencio',
    ]
    print('PHRASES', len(phrases))
    for phrase in phrases:
        intent = clf.classify(phrase)
        spec = reg.resolve_action(intent)
        action_id = spec.action_id if spec else '-'
        print(f"{phrase} => {intent.name} {intent.entities} action={action_id}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
