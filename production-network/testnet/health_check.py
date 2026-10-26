#!/usr/bin/env python3
"""Read-only CometBFT RPC checks. Four node IDs do not prove four validators."""
import argparse
import json
import urllib.request
import urllib.parse


def status(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise ValueError('RPC must be an HTTP(S) origin without credentials, path, query or fragment')
    with urllib.request.urlopen(url.rstrip('/') + '/status', timeout=8) as response:
        result = json.load(response)['result']
    info = result['node_info']
    sync = result['sync_info']
    return {
        'url': url, 'network': info['network'],
        'node_id': info['id'], 'height': int(sync['latest_block_height']),
        'catching_up': bool(sync['catching_up']),
    }


def check(nodes, expected_chain):
    if len(nodes) < 4:
        raise ValueError('Four or more CometBFT endpoints required')
    if any(not isinstance(n.get('node_id'), str) or not n['node_id'].strip() for n in nodes):
        raise ValueError('Missing CometBFT node ID')
    if len({n['node_id'] for n in nodes}) != len(nodes):
        raise ValueError('Duplicate CometBFT node IDs')
    chains = {n['network'] for n in nodes}
    if len(chains) != 1 or (expected_chain and expected_chain not in chains):
        raise ValueError('Chain IDs disagree')
    if any(type(n.get('height')) is not int or n['height'] < 1 for n in nodes):
        raise ValueError('Invalid CometBFT block height')
    heights = [n['height'] for n in nodes]
    if min(heights) < 1 or max(heights) - min(heights) > 10:
        raise ValueError('Block heights are not synchronized')
    if any(n['catching_up'] for n in nodes):
        raise ValueError('At least one node is catching up')
    return {'chain': next(iter(chains)), 'height_range': [min(heights), max(heights)], 'nodes': len(nodes)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rpc', action='append', required=True)
    p.add_argument('--chain-id', default='local-4221')
    args = p.parse_args()
    try:
        nodes = [status(url) for url in args.rpc]
        print(json.dumps({'ok': True, **check(nodes, args.chain_id), 'details': nodes}, indent=2))
    except Exception as e:
        print(json.dumps({'ok': False, 'error': str(e)}))
        raise SystemExit(1) from e


if __name__ == '__main__':
    main()
