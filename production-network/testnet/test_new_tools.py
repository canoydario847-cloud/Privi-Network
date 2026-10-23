import unittest
from unittest.mock import patch
from evm_smoke import check
from consensus_audit import audit

class FakeRPC:
    def __init__(self,chain=4221):self.chain=chain
    def call(self,method,params=None):
        return {
            'eth_chainId':hex(self.chain),
            'eth_blockNumber':'0x20',
            'eth_getBlockByNumber':{'hash':'0x'+'a'*64},
            'eth_getBalance':'0x100',
            'eth_getTransactionCount':'0x1',
        }[method]

class Tests(unittest.TestCase):
    def test_valid_rpc_balance(self):
        self.assertEqual(check(FakeRPC(),4221,'0x'+'a'*40)['balanceWei'],'256')
    def test_reject_real_chain(self):
        with self.assertRaises(ValueError):check(FakeRPC(56))
    def test_four_validators_sign(self):
        validators=[{'address':str(i).zfill(40),'voting_power':'1'} for i in range(4)]
        def fake(url,path):
            if path.startswith('/status'):
                return {'node_info':{'id':url,'network':'local-4221'},'sync_info':{'latest_block_height':'42','catching_up':False}}
            if path.startswith('/block?'):return {'block_id':{'hash':'abc'}}
            if path.startswith('/validators?'):return {'validators':validators,'total':'4'}
            if path.startswith('/commit?'):return {'signed_header':{'commit':{
                'height':'41', 'block_id':{'hash':'abc'},
                'signatures':[{'validator_address':v['address'],'block_id_flag':2,'signature':'AA=='} for v in validators]}}}
            raise RuntimeError(path)
        with patch('consensus_audit.get',side_effect=fake):
            self.assertEqual(audit(['a','b','c','d'],'local-4221')['votingValidators'],4)
    def test_reject_three_nodes(self):
        with self.assertRaises(ValueError):audit(['a','b','c'])
if __name__=='__main__':unittest.main()
