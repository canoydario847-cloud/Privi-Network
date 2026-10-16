#!/usr/bin/env python3
"""Read-only, conservative ERC-20 Transfer-event snapshot for PRIV on BNB Chain.

Never broadcasts a transaction, mints a token, or creates a migration claim.
"""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

TOKEN = '0xbf154Ff2577F4B85db7B2ee910Db5880D06e0f64'
ZERO = '0x' + '0' * 40
# keccak256("Transfer(address,address,uint256)")
TRANSFER = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
SUPPLY_SELECTOR = '0x18160ddd'
DECIMALS_SELECTOR = '0x313ce567'
BALANCE_SELECTOR = '0x70a08231'


class RPC:
    def __init__(self, url):
        if not url.startswith(('https://', 'http://')):
            raise ValueError('Specify a valid HTTP(S) archive RPC URL')
        self.url = url
        self.req_id = 0

    def call(self, method, params):
        self.req_id += 1
        body = json.dumps({'jsonrpc': '2.0', 'id': self.req_id,
                           'method': method, 'params': params}).encode()
        request = urllib.request.Request(self.url, data=body, headers={
            'Content-Type': 'application/json', 'User-Agent': 'Privi-ReadOnlySnapshot/0.1'})
        for retry in range(4):
            try:
                with urllib.request.urlopen(request, timeout=45) as response:
                    answer = json.load(response)
                if answer.get('error'):
                    raise RuntimeError(f"RPC {method}: {answer['error']}")
                if 'result' not in answer:
                    raise RuntimeError(f'RPC {method}: result missing')
                return answer['result']
            except (urllib.error.URLError, TimeoutError) as exc:
                if retry == 3:
                    raise RuntimeError(f'RPC {method}: {exc}') from exc
                time.sleep(1.5 * (retry + 1))


def holder_from_topic(topic):
    if not isinstance(topic, str) or len(topic) != 66 or not topic.startswith('0x'):
        raise ValueError('Invalid indexed address topic')
    if int(topic[2:26], 16) != 0:
        raise ValueError('Indexed address has invalid padding')
    return '0x' + topic[-40:].lower()


def apply_transfer(balances, sender, recipient, amount):
    if amount < 0:
        raise ValueError('Negative ERC-20 value')
    if sender != ZERO:
        balances[sender] -= amount
        if balances[sender] < 0:
            raise ValueError(f'Insufficient reconstructed transfer balance at {sender}')
    if recipient != ZERO:
        balances[recipient] += amount


def parse_transfer(log, expected_contract):
    if log.get('removed'):
        raise ValueError('Removed log found: possible chain reorganization')
    if log.get('address', '').lower() != expected_contract.lower():
        raise ValueError('Unexpected log contract')
    topics = log.get('topics', [])
    if len(topics) != 3 or topics[0].lower() != TRANSFER:
        raise ValueError('Non-standard Transfer event')
    data = log.get('data', '')
    if not isinstance(data, str) or len(data) != 66:
        raise ValueError('Invalid Transfer amount')
    return holder_from_topic(topics[1]), holder_from_topic(topics[2]), int(data, 16)


def eth_call(rpc, token, selector, block_tag):
    value = rpc.call('eth_call', [{'to': token, 'data': selector}, block_tag])
    if not isinstance(value, str) or not value.startswith('0x') or len(value) < 3:
        raise ValueError('Invalid historical eth_call result')
    return int(value, 16)


def scan_range(rpc, token, low, high, balances):
    """Try splitting batches that exceed the RPC provider's log limit."""
    try:
        logs = rpc.call('eth_getLogs', [{
            'address': token, 'fromBlock': hex(low), 'toBlock': hex(high),
            'topics': [TRANSFER]
        }])
    except RuntimeError:
        if low == high:
            raise
        mid = (low + high) // 2
        return (scan_range(rpc, token, low, mid, balances) +
                scan_range(rpc, token, mid + 1, high, balances))
    if not isinstance(logs, list):
        raise ValueError('Invalid eth_getLogs response')
    logs.sort(key=lambda l: (int(l['blockNumber'], 16),
                             int(l['transactionIndex'], 16),
                             int(l['logIndex'], 16)))
    for log in logs:
        sender, recipient, amount = parse_transfer(log, token)
        apply_transfer(balances, sender, recipient, amount)
    return len(logs)


def build_snapshot(rpc, block_number, min_confirmations, chunk_size, sample_count):
    if int(rpc.call('eth_chainId', []), 16) != 56:
        raise ValueError('Not connected to BNB Chain ID 56')
    tip = int(rpc.call('eth_blockNumber', []), 16)
    if block_number <= 0 or block_number > tip - min_confirmations:
        raise ValueError('Snapshot block is not old enough for requested confirmations')
    block_tag = hex(block_number)
    before = rpc.call('eth_getBlockByNumber', [block_tag, False])
    if not before or not before.get('hash'):
        raise ValueError('Snapshot block not found')
    total = eth_call(rpc, TOKEN, SUPPLY_SELECTOR, block_tag)
    decimals = eth_call(rpc, TOKEN, DECIMALS_SELECTOR, block_tag)
    if decimals != 18:
        raise ValueError(f'Unexpected token decimals: {decimals}')
    balances = defaultdict(int)
    events = 0
    for low in range(0, block_number + 1, chunk_size):
        high = min(block_number, low + chunk_size - 1)
        events += scan_range(rpc, TOKEN, low, high, balances)
        if high == block_number or low % max(chunk_size * 200, 1) == 0:
            print(f'Processed blocks 0..{high}/{block_number} · events={events}', file=sys.stderr)
    after = rpc.call('eth_getBlockByNumber', [block_tag, False])
    if before['hash'].lower() != after['hash'].lower():
        raise ValueError('Snapshot block changed during scan')
    allocations = {key: str(value) for key, value in sorted(balances.items()) if value > 0}
    counted = sum(int(v) for v in allocations.values())
    if counted != total:
        raise ValueError(f'Supply mismatch: reconstructed={counted}, onchain={total}')
    keys = sorted(allocations)
    if sample_count:
        stride = max(1, len(keys) // sample_count)
        selected = keys[::stride][:sample_count]
        for key in selected:
            address_argument = key[2:].rjust(64, '0')
            onchain = eth_call(rpc, TOKEN, BALANCE_SELECTOR + address_argument, block_tag)
            if onchain != int(allocations[key]):
                raise ValueError(f'Balance audit failed at {key}')
    digest = hashlib.sha256(json.dumps(allocations, sort_keys=True,
                                       separators=(',', ':')).encode()).hexdigest()
    return {
        'chainId': 56, 'token': TOKEN, 'snapshotBlock': block_number,
        'snapshotBlockHash': before['hash'], 'decimals': decimals,
        'onchainTotalSupplyBaseUnits': str(total),
        'reconstructedSupplyBaseUnits': str(counted),
        'holders': len(allocations), 'transferEvents': events,
        'balanceChecks': min(sample_count, len(keys)),
        'allocationSha256': digest, 'allocationsBaseUnits': allocations,
        'status': 'READ_ONLY_UNAUDITED_NOT_MIGRATION_AUTHORIZATION'
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rpc-url', default=os.getenv('BNB_ARCHIVE_RPC_URL'))
    parser.add_argument('--snapshot-block', type=int, required=True)
    parser.add_argument('--min-confirmations', type=int, default=64)
    parser.add_argument('--chunk-size', type=int, default=2000)
    parser.add_argument('--sample-count', type=int, default=25)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not args.rpc_url:
        parser.error('Set --rpc-url or BNB_ARCHIVE_RPC_URL')
    if args.chunk_size < 1 or args.min_confirmations < 0 or args.sample_count < 0:
        parser.error('Invalid sizes or confirmation count')
    if args.out.exists():
        parser.error('Output exists; refusing to overwrite')
    report = build_snapshot(RPC(args.rpc_url), args.snapshot_block,
                            args.min_confirmations, args.chunk_size, args.sample_count)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as f:
        json.dump(report, f, indent=2)
        f.write('\n')
    print(f"Snapshot written: {args.out}; holders={report['holders']}; sha256={report['allocationSha256']}")


if __name__ == '__main__':
    main()
