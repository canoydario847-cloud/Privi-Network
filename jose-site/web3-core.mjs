// Hey Jose Web3 Studio core. Deterministic, reviewable templates and local hash chain.
// Copyright (c) 2026 Privi World Corp. Generated templates use OpenZeppelin 5.x interfaces.
export const networks=Object.freeze([
  {id:84532,hex:'0x14a34',name:'Base Sepolia (testnet)',testnet:true,explorer:'https://sepolia.basescan.org'},
  {id:11155111,hex:'0xaa36a7',name:'Ethereum Sepolia (testnet)',testnet:true,explorer:'https://sepolia.etherscan.io'},
  {id:8453,hex:'0x2105',name:'Base Mainnet',testnet:false,explorer:'https://basescan.org'},
  {id:1,hex:'0x1',name:'Ethereum Mainnet',testnet:false,explorer:'https://etherscan.io'}
]);
export function validateName(input) {
  const name=String(input??'').trim();
  if(!/^[A-Za-z0-9][A-Za-z0-9 ._-]{1,38}[A-Za-z0-9]$/.test(name)) throw new Error('Name must be 3–40 letters, numbers, spaces, dots, dashes or underscores.');
  return name;
}
export function validateSymbol(input){
  const s=String(input??'').trim().toUpperCase();
  if(!/^[A-Z0-9]{2,8}$/.test(s))throw new Error('Symbol must be 2–8 letters or numbers.');
  return s;
}
export function validateSupply(input){
  const s=String(input??'').trim();
  if(!/^[1-9][0-9]{0,11}$/.test(s))throw new Error('Whole-token supply must be 1 to 999,999,999,999.');
  return s;
}
export function quoted(value){return JSON.stringify(value);}
const pragma='pragma solidity ^0.8.24;';
export function buildSource(kind,options={}){
  if(kind==='token'){
    const name=validateName(options.name),sym=validateSymbol(options.symbol),supply=validateSupply(options.supply);
    return {kind,contract:'JoseToken',file:'JoseToken.sol',label:'Fixed-supply ERC-20 token',constructorArgs:[],source:[
      '// SPDX-License-Identifier: MIT',pragma,
      'import "@openzeppelin/contracts/token/ERC20/ERC20.sol";',
      '// OpenZeppelin Contracts 5.x: install and pin the dependency in your compiler.',
      'contract JoseToken is ERC20 {',
      '    constructor() ERC20('+quoted(name)+', '+quoted(sym)+') {',
      '        _mint(msg.sender, uint256('+supply+') * 10 ** decimals());',
      '    }','}',''
    ].join('\n')};
  }
  if(kind==='nft'){
    const name=validateName(options.name),sym=validateSymbol(options.symbol);
    return {kind,contract:'JoseNFT',file:'JoseNFT.sol',label:'Owner-minted ERC-721 NFT',constructorArgs:[],source:[
      '// SPDX-License-Identifier: MIT',pragma,
      'import "@openzeppelin/contracts/token/ERC721/extensions/ERC721URIStorage.sol";',
      'import "@openzeppelin/contracts/access/Ownable.sol";',
      '// OpenZeppelin Contracts 5.x. Host NFT metadata URI independently.',
      'contract JoseNFT is ERC721URIStorage, Ownable {',
      '    uint256 public nextTokenId = 1;',
      '    constructor() ERC721('+quoted(name)+', '+quoted(sym)+') Ownable(msg.sender) {}',
      '    function mint(address to, string calldata metadataURI) external onlyOwner returns (uint256 id) {',
      '        require(to != address(0), "zero recipient");',
      '        require(bytes(metadataURI).length > 0, "missing metadata");',
      '        id = nextTokenId++;',
      '        _safeMint(to, id);',
      '        _setTokenURI(id, metadataURI);',
      '    }',
      '}',''
    ].join('\n')};
  }
  if(kind==='contract'){
    const label=validateName(options.name||'Jose Message Vault');
    return {kind,contract:'JoseMessageVault',file:'JoseMessageVault.sol',label:'Owner-controlled message vault',constructorArgs:[],source:[
      '// SPDX-License-Identifier: MIT',pragma,
      '// Contract state is public. Do not put secrets on-chain.',
      'contract JoseMessageVault {',
      '    address public immutable owner;',
      '    string public message;',
      '    event MessageUpdated(address indexed sender, string newMessage);',
      '    constructor() { owner = msg.sender; message = '+quoted(label)+'; }',
      '    function updateMessage(string calldata newMessage) external {',
      '        require(msg.sender == owner, "owner only");',
      '        require(bytes(newMessage).length <= 256, "too long");',
      '        message = newMessage;',
      '        emit MessageUpdated(msg.sender, newMessage);',
      '    }',
      '}',''
    ].join('\n')};
  }
  if(kind==='ledger-anchor'){
    return {kind,contract:'JoseLedgerAnchor',file:'JoseLedgerAnchor.sol',label:'Owner-controlled on-chain ledger root anchor',constructorArgs:[],source:[
      '// SPDX-License-Identifier: MIT',pragma,
      'contract JoseLedgerAnchor {',
      '    address public immutable owner;',
      '    bytes32 public latestRoot;',
      '    uint256 public anchorCount;',
      '    event RootAnchored(bytes32 indexed root, uint256 indexed sequence);',
      '    constructor() { owner = msg.sender; }',
      '    function anchor(bytes32 root) external {',
      '        require(msg.sender == owner, "owner only");',
      '        require(root != bytes32(0), "empty root");',
      '        latestRoot = root;',
      '        emit RootAnchored(root, ++anchorCount);',
      '    }',
      '}',''
    ].join('\n')};
  }
  throw new Error('Choose token, nft, contract or ledger-anchor.');
}
export function validateCreationBytecode(input){
  const bytecode=String(input??'').trim();
  if(!/^0x(?:[0-9a-fA-F]{2})+$/.test(bytecode))throw new Error('Paste EVM creation bytecode (0x and complete hexadecimal bytes).');
  if(bytecode.length>2+49152*2)throw new Error('Creation bytecode exceeds the EVM initcode size limit.');
  return bytecode;
}
export function networkById(value){const n=networks.find(n=>String(n.id)===String(value));if(!n)throw new Error('Unsupported chain.');return n;}
export function chainManifest(input){
  const name=validateName(input.name||'Jose Devnet');
  const chainId=String(input.chainId??'').trim();
  if(!/^[1-9][0-9]{0,8}$/.test(chainId))throw new Error('Devnet chain ID must be a positive integer up to nine digits.');
  const validators=Number(input.validators);
  if(!Number.isInteger(validators)||validators<4||validators>16)throw new Error('Configure 4–16 independent validators for a devnet.');
  return {kind:'independent-blockchain-blueprint',status:'DESIGN_ONLY_NOT_DEPLOYED',name,evmChainId:Number(chainId),validators,consensus:'CometBFT / Cosmos SDK (engineering integration required)',networkType:'devnet',prerequisites:[
    'Build and review chain binary and deterministic genesis',
    'Provision independent validator nodes with unique protected signing keys',
    'Configure peers, RPC, gas policy, observability and governance',
    'Test partitions, recovery, upgrades and state synchronization',
    'Audit consensus and validate written launch-readiness gates'
  ],generatedBy:'Hey Jose Web3 Studio'};
}
export function canonicalRecord(index,previousHash,createdAt,entry){
  return JSON.stringify({index,previousHash,createdAt,entry});
}
export async function sha256(text){
  if(!globalThis.crypto?.subtle)throw new Error('Secure browser context required for ledger hashing.');
  const b=new TextEncoder().encode(text),d=await globalThis.crypto.subtle.digest('SHA-256',b);
  return Array.from(new Uint8Array(d),x=>x.toString(16).padStart(2,'0')).join('');
}
export async function verifyRecords(records){
  if(!Array.isArray(records)||records.length>2000)return false;
  let prev='GENESIS';
  for(let i=0;i<records.length;i++){
    const r=records[i];
    if(!r||r.index!==i||r.previousHash!==prev||typeof r.createdAt!=='string'||typeof r.entry!=='string'||typeof r.hash!=='string')return false;
    if(await sha256(canonicalRecord(i,prev,r.createdAt,r.entry))!==r.hash)return false;
    prev=r.hash;
  }
  return true;
}
export async function appendRecord(records,entry,now=new Date().toISOString()){
  const msg=String(entry??'').trim();
  if(!msg||msg.length>2000)throw new Error('Ledger entry must be 1–2000 characters.');
  if(!Array.isArray(records)||records.length>=2000)throw new Error('Ledger full: export records first.');
  if(!(await verifyRecords(records)))throw new Error('Ledger integrity check failed. Export and investigate before appending.');
  const index=records.length,previousHash=index?records[index-1].hash:'GENESIS';
  const hash=await sha256(canonicalRecord(index,previousHash,now,msg));
  return [...records,{index,previousHash,createdAt:now,entry:msg,hash}];
}
