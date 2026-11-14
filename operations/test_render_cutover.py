"""Verify the active migration surfaces no longer refer to suspended origins."""
import json
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ROOTS=('sites','discovery','jose-site','jose-backend/src','jose-backend/public','wallet-server/src','devnet','ledger-server/src','mcp-server/src','call-server/src','anchor-server/src','quantum-server/src')
class RenderCutover(unittest.TestCase):
    def test_active_sources_use_current_workspace_origins(self):
        mapping=json.loads((ROOT/'operations/render-cutover-map.json').read_text())['url_map']
        errors=[]
        for folder in ROOTS:
            for path in (ROOT/folder).rglob('*'):
                if not path.is_file() or path.suffix not in {'.py','.js','.html','.json','.mjs','.css'}:continue
                text=path.read_text()
                for old in mapping:
                    if old in text or old.replace('https://','wss://') in text:errors.append(str(path.relative_to(ROOT))+': '+old)
        self.assertEqual([],errors)
    def test_migration_does_not_claim_historical_state_verified(self):
        data=json.loads((ROOT/'operations/render-cutover-map.json').read_text())
        self.assertIs(data['data_migration_verified'],False)
        self.assertEqual(data['workspace'],'tea-dbr1aqjrjlhs73ccmcbg')
if __name__=='__main__':unittest.main()
