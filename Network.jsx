/**
 * Network — Live Ethereum chain data + animated global node map + subnet ID.
 * Node map uses SVG with ~30 known validator node locations plotted on a
 * world-map projection. Each node pulses when a new block arrives.
 */
import { useEffect, useState, useRef, useCallback } from 'react';
import { pb } from '../lib/pb.js';
import { useLedgerPageView } from '../lib/useLedgerPageView.js';

// ── Network presets ───────────────────────────────────────────────────────────
const NETWORK_PRESETS = {
  bnb_chain:        { label: '⭐ BNB Chain (Privi)', rpc: 'https://bsc-dataseed.binance.org/', chainId: 56,  explorer: 'https://bscscan.com',            blockTime: '~3s',  consensus: 'Proof of Staked Authority', priviContract: '0x901d2460c916e6dD8d3eb21007722731A172fA57' },
  ethereum_mainnet: { label: 'Ethereum',    rpc: 'https://cloudflare-eth.com',     chainId: 1,       explorer: 'https://etherscan.io',          blockTime: '~12s', consensus: 'Proof of Stake' },
  sepolia_testnet:  { label: 'Sepolia',     rpc: 'https://rpc.sepolia.org',        chainId: 11155111, explorer: 'https://sepolia.etherscan.io',  blockTime: '~12s', consensus: 'Proof of Stake' },
  polygon:          { label: 'Polygon',     rpc: 'https://polygon-rpc.com',        chainId: 137,     explorer: 'https://polygonscan.com',        blockTime: '~2s',  consensus: 'Proof of Stake' },
  arbitrum:         { label: 'Arbitrum',    rpc: 'https://arb1.arbitrum.io/rpc',   chainId: 42161,   explorer: 'https://arbiscan.io',            blockTime: '<1s',  consensus: 'Optimistic Rollup' },
};

// ── RPC helpers ───────────────────────────────────────────────────────────────
function makeRpc(url) {
  return async (method, params = []) => {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }),
      signal: AbortSignal.timeout(10000),
    });
    return (await r.json()).result;
  };
}
const hexN = h => h ? parseInt(h, 16) : 0;
const gwei = w => (hexN(w) / 1e9).toFixed(2);
function timeAgo(ts) {
  const s = Math.floor(Date.now() / 1000) - hexN(ts);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

// ── Known ETH validator node locations (lat/lng → SVG x/y via simple equirect) ─
// 60 nodes spread across actual Ethereum validator hotspots
const RAW_NODES = [
  // North America
  {lat:40.71,lng:-74.01},{lat:37.77,lng:-122.42},{lat:47.61,lng:-122.33},
  {lat:41.88,lng:-87.63},{lat:43.65,lng:-79.38},{lat:45.50,lng:-73.57},
  {lat:33.75,lng:-84.39},{lat:29.76,lng:-95.37},{lat:39.95,lng:-75.17},
  {lat:47.65,lng:-117.43},{lat:36.17,lng:-115.14},
  // Europe
  {lat:51.51,lng:-0.13},{lat:48.85,lng:2.35},{lat:52.52,lng:13.40},
  {lat:59.91,lng:10.75},{lat:55.68,lng:12.57},{lat:60.17,lng:24.94},
  {lat:52.37,lng:4.90},{lat:50.85,lng:4.35},{lat:47.37,lng:8.54},
  {lat:41.01,lng:28.98},{lat:48.21,lng:16.37},{lat:53.34,lng:-6.27},
  {lat:45.46,lng:9.19},{lat:40.42,lng:-3.70},{lat:59.33,lng:18.07},
  {lat:50.07,lng:14.44},{lat:47.50,lng:19.04},{lat:44.44,lng:26.10},
  // Asia
  {lat:35.69,lng:139.69},{lat:31.23,lng:121.47},{lat:37.57,lng:126.98},
  {lat:1.35,lng:103.82},{lat:22.32,lng:114.17},{lat:25.05,lng:121.53},
  {lat:13.75,lng:100.52},{lat:28.61,lng:77.21},{lat:19.08,lng:72.88},
  {lat:55.76,lng:37.62},{lat:59.44,lng:24.75},{lat:56.95,lng:24.11},
  // Oceania / South America / Africa
  {lat:-33.87,lng:151.21},{lat:-37.82,lng:144.97},{lat:-23.55,lng:-46.63},
  {lat:-34.61,lng:-58.38},{lat:-33.46,lng:-70.65},{lat:-4.32,lng:15.32},
  {lat:30.06,lng:31.25},{lat:-26.20,lng:28.04},{lat:6.45,lng:3.40},
  {lat:3.15,lng:101.69},
];

const W = 800, H = 420;
function latLngToXY(lat, lng) {
  const x = ((lng + 180) / 360) * W;
  const y = ((90 - lat) / 180) * H;
  return { x, y };
}
const NODE_POSITIONS = RAW_NODES.map((n, i) => ({ ...latLngToXY(n.lat, n.lng), id: i }));

// ── World map SVG paths (simplified continents) ───────────────────────────────
// Tiny approximate continent outlines in equirectangular projection (W=800,H=420)
const CONTINENT_PATHS = [
  // North America
  "M 115 60 L 165 55 L 200 80 L 220 110 L 195 160 L 170 180 L 145 175 L 120 155 L 100 130 L 90 100 Z",
  // South America
  "M 185 200 L 215 195 L 230 220 L 235 270 L 215 320 L 190 335 L 170 300 L 165 260 L 175 230 Z",
  // Europe
  "M 365 60 L 415 55 L 430 75 L 420 95 L 400 100 L 380 110 L 360 100 L 355 80 Z",
  // Africa
  "M 375 120 L 415 115 L 440 145 L 445 200 L 430 260 L 405 290 L 380 280 L 360 250 L 350 200 L 355 160 Z",
  // Asia (rough)
  "M 435 55 L 560 50 L 650 70 L 670 110 L 630 140 L 580 150 L 520 140 L 480 120 L 450 100 L 430 80 Z",
  // South/SE Asia peninsula
  "M 520 145 L 560 155 L 565 195 L 545 210 L 520 200 L 510 175 Z",
  // Australia
  "M 600 245 L 660 240 L 685 265 L 670 300 L 640 315 L 605 300 L 590 275 Z",
  // Greenland
  "M 230 30 L 270 25 L 285 50 L 260 70 L 230 60 Z",
  // UK
  "M 358 72 L 368 68 L 372 78 L 362 84 Z",
  // Japan
  "M 648 95 L 662 90 L 668 105 L 655 110 Z",
];

// ── Node map ──────────────────────────────────────────────────────────────────
function NodeMap({ pulse, status }) {
  const [lit, setLit] = useState(new Set());
  const litRef = useRef(new Set());

  useEffect(() => {
    if (!pulse) return;
    // Light up a random subset of 8-14 nodes on each new block
    const count = 8 + Math.floor(Math.random() * 7);
    const chosen = new Set();
    while (chosen.size < count) chosen.add(Math.floor(Math.random() * NODE_POSITIONS.length));
    setLit(chosen);
    litRef.current = chosen;
    const t = setTimeout(() => { setLit(new Set()); litRef.current = new Set(); }, 1800);
    return () => clearTimeout(t);
  }, [pulse]);

  return (
    <div className="relative w-full overflow-hidden rounded-sm border border-white/8 bg-[#060a12]" style={{ aspectRatio: `${W}/${H}` }}>
      {/* Grid lines */}
      <svg className="absolute inset-0 w-full h-full opacity-[0.06]" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet">
        {Array.from({length:9},(_,i)=><line key={`v${i}`} x1={i*100} y1={0} x2={i*100} y2={H} stroke="#22d3ee" strokeWidth="0.5"/>)}
        {Array.from({length:5},(_,i)=><line key={`h${i}`} x1={0} y1={i*105} x2={W} y2={i*105} stroke="#22d3ee" strokeWidth="0.5"/>)}
      </svg>

      {/* Continent fills */}
      <svg className="absolute inset-0 w-full h-full" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet">
        {CONTINENT_PATHS.map((d, i) => (
          <path key={i} d={d} fill="#1e3a4a" stroke="#22d3ee22" strokeWidth="0.5" />
        ))}
      </svg>

      {/* Connection lines between lit nodes */}
      <svg className="absolute inset-0 w-full h-full" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet">
        {lit.size > 1 && (() => {
          const arr = [...lit].slice(0, 6);
          const lines = [];
          for (let i = 0; i < arr.length - 1; i++) {
            const a = NODE_POSITIONS[arr[i]], b = NODE_POSITIONS[arr[i+1]];
            lines.push(<line key={`l${i}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#22d3ee" strokeWidth="0.5" opacity="0.3" />);
          }
          return lines;
        })()}
      </svg>

      {/* Nodes */}
      <svg className="absolute inset-0 w-full h-full" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet" aria-label="Ethereum validator node map">
        {NODE_POSITIONS.map(n => {
          const isLit = lit.has(n.id);
          return (
            <g key={n.id}>
              {isLit && <circle cx={n.x} cy={n.y} r="12" fill="#22d3ee" opacity="0.12">
                <animate attributeName="r" values="6;18;6" dur="1.6s" repeatCount="1" />
                <animate attributeName="opacity" values="0.15;0;0.15" dur="1.6s" repeatCount="1" />
              </circle>}
              <circle
                cx={n.x} cy={n.y}
                r={isLit ? 4 : 2.5}
                fill={isLit ? '#22d3ee' : '#1a3a48'}
                stroke={isLit ? '#22d3ee' : '#22d3ee44'}
                strokeWidth={isLit ? 1.5 : 0.8}
                style={{ transition: 'all 0.3s ease' }}
              />
            </g>
          );
        })}
      </svg>

      {/* Status overlay */}
      <div className="absolute bottom-3 left-3 flex items-center gap-2">
        <span className="relative flex h-2 w-2">
          {status === 'live'
            ? <><span className="animate-ping absolute h-full w-full rounded-full bg-emerald-400 opacity-75"/><span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-400"/></>
            : <span className="inline-flex rounded-full h-2 w-2 bg-gray-600"/>}
        </span>
        <span className="text-[10px] text-gray-500 font-mono">
          {status === 'live' ? `${NODE_POSITIONS.length} validator nodes` : 'Connecting to network…'}
        </span>
      </div>
    </div>
  );
}

// ── Stat tile ─────────────────────────────────────────────────────────────────
function Tile({ label, value, sub, accent, live }) {
  return (
    <div className={`relative overflow-hidden rounded-sm border p-5 ${accent ? 'border-cyan-500/30 bg-gradient-to-br from-cyan-500/10 to-transparent' : 'border-white/8 bg-white/3'}`}>
      {live && (
        <span className="absolute top-3 right-3 flex h-2 w-2">
          <span className="animate-ping absolute h-full w-full rounded-full bg-emerald-400 opacity-75"/>
          <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-400"/>
        </span>
      )}
      <div className="text-[10px] text-gray-500 uppercase tracking-widest mb-1.5">{label}</div>
      <div className={`text-2xl font-black font-mono tabular-nums ${accent ? 'text-cyan-400' : 'text-white'}`}>{value}</div>
      {sub && <div className="text-[11px] text-gray-600 mt-1">{sub}</div>}
    </div>
  );
}

// ── Block row ─────────────────────────────────────────────────────────────────
function BlockRow({ block, fresh }) {
  return (
    <div className={`grid items-center px-4 py-2.5 border-b border-white/4 last:border-0 text-xs font-mono transition-colors ${fresh ? 'bg-cyan-500/8' : 'hover:bg-white/2'}`}
      style={{ gridTemplateColumns: '5rem 1fr 4rem 5rem' }}>
      <span className="text-cyan-400 font-bold tabular-nums text-right">{hexN(block.number).toLocaleString()}</span>
      <span className="text-gray-500 truncate px-3">{block.hash?.slice(0, 16)}…</span>
      <span className="text-gray-400 tabular-nums text-right">{block.transactions?.length ?? 0} tx</span>
      <span className="text-gray-600 text-right">{block.timestamp ? timeAgo(block.timestamp) : ''}</span>
    </div>
  );
}

// ── RPC Generator ─────────────────────────────────────────────────────────────
const RPC_CHAINS = [
  {
    id: 'bnb', label: 'BNB Chain', short: 'BSC', chainId: 56,
    symbol: 'BNB', color: '#f0b90b', dot: '🟡',
    explorer: 'https://bscscan.com',
    providers: [
      { name: 'Binance Public',  url: 'https://bsc-dataseed.binance.org/' },
      { name: 'DefiB Public',    url: 'https://bsc-dataseed1.defibit.io/' },
      { name: 'Ankr',            url: 'https://rpc.ankr.com/bsc' },
      { name: 'QuickNode',       url: 'https://bsc-mainnet.nodereal.io/v1/{API_KEY}' },
    ],
  },
  {
    id: 'eth', label: 'Ethereum', short: 'ETH', chainId: 1,
    symbol: 'ETH', color: '#627eea', dot: '🔵',
    explorer: 'https://etherscan.io',
    providers: [
      { name: 'Cloudflare',  url: 'https://cloudflare-eth.com/' },
      { name: 'Ankr',        url: 'https://rpc.ankr.com/eth' },
      { name: 'Infura',      url: 'https://mainnet.infura.io/v3/{API_KEY}' },
      { name: 'Alchemy',     url: 'https://eth-mainnet.g.alchemy.com/v2/{API_KEY}' },
    ],
  },
  {
    id: 'polygon', label: 'Polygon', short: 'POL', chainId: 137,
    symbol: 'POL', color: '#8247e5', dot: '🟣',
    explorer: 'https://polygonscan.com',
    providers: [
      { name: 'Polygon Public', url: 'https://polygon-rpc.com/' },
      { name: 'Ankr',           url: 'https://rpc.ankr.com/polygon' },
      { name: 'Infura',         url: 'https://polygon-mainnet.infura.io/v3/{API_KEY}' },
      { name: 'Alchemy',        url: 'https://polygon-mainnet.g.alchemy.com/v2/{API_KEY}' },
    ],
  },
  {
    id: 'arbitrum', label: 'Arbitrum One', short: 'ARB', chainId: 42161,
    symbol: 'ETH', color: '#28a0f0', dot: '🔷',
    explorer: 'https://arbiscan.io',
    providers: [
      { name: 'Arbitrum Public', url: 'https://arb1.arbitrum.io/rpc' },
      { name: 'Ankr',            url: 'https://rpc.ankr.com/arbitrum' },
      { name: 'Infura',          url: 'https://arbitrum-mainnet.infura.io/v3/{API_KEY}' },
    ],
  },
  {
    id: 'optimism', label: 'Optimism', short: 'OP', chainId: 10,
    symbol: 'ETH', color: '#ff0420', dot: '🔴',
    explorer: 'https://optimistic.etherscan.io',
    providers: [
      { name: 'Optimism Public', url: 'https://mainnet.optimism.io/' },
      { name: 'Ankr',            url: 'https://rpc.ankr.com/optimism' },
      { name: 'Infura',          url: 'https://optimism-mainnet.infura.io/v3/{API_KEY}' },
    ],
  },
  {
    id: 'base', label: 'Base', short: 'BASE', chainId: 8453,
    symbol: 'ETH', color: '#0052ff', dot: '🟦',
    explorer: 'https://basescan.org',
    providers: [
      { name: 'Base Public',  url: 'https://mainnet.base.org/' },
      { name: 'Public Node', url: 'https://base.publicnode.com/' },
      { name: 'Ankr',         url: 'https://rpc.ankr.com/base' },
    ],
  },
  {
    id: 'avalanche', label: 'Avalanche', short: 'AVAX', chainId: 43114,
    symbol: 'AVAX', color: '#e84142', dot: '🔺',
    explorer: 'https://snowtrace.io',
    providers: [
      { name: 'Avalanche Public', url: 'https://api.avax.network/ext/bc/C/rpc' },
      { name: 'Ankr',             url: 'https://rpc.ankr.com/avalanche' },
      { name: 'Infura',           url: 'https://avalanche-mainnet.infura.io/v3/{API_KEY}' },
    ],
  },
  {
    id: 'fantom', label: 'Fantom', short: 'FTM', chainId: 250,
    symbol: 'FTM', color: '#1969ff', dot: '👻',
    explorer: 'https://ftmscan.com',
    providers: [
      { name: 'FTM Tools',    url: 'https://rpc.ftm.tools/' },
      { name: 'Ankr',         url: 'https://rpc.ankr.com/fantom' },
      { name: 'Public Node', url: 'https://fantom.publicnode.com/' },
    ],
  },
];

function RpcGenerator() {
  const [chainId,    setChainId]    = useState('bnb');
  const [provIdx,    setProvIdx]    = useState(0);
  const [apiKey,     setApiKey]     = useState('');
  const [copied,     setCopied]     = useState(false);
  const [testState,  setTestState]  = useState(null); // null | 'testing' | 'ok' | 'fail'
  const [latency,    setLatency]    = useState(null);
  const [mmState,    setMmState]    = useState(null); // null | 'pending' | 'ok' | 'fail'
  const [showConfig, setShowConfig] = useState(false);

  const chain    = RPC_CHAINS.find(c => c.id === chainId) || RPC_CHAINS[0];
  const provider = chain.providers[provIdx] || chain.providers[0];
  const needsKey = provider.url.includes('{API_KEY}');
  const finalUrl = needsKey && apiKey.trim()
    ? provider.url.replace('{API_KEY}', apiKey.trim())
    : provider.url.replace(/\/{API_KEY}/, '').replace('{API_KEY}', '');

  function pickChain(id) {
    setChainId(id); setProvIdx(0); setApiKey('');
    setTestState(null); setLatency(null);
  }

  async function copyUrl() {
    try { await navigator.clipboard.writeText(finalUrl); } catch {}
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  async function testConn() {
    setTestState('testing'); setLatency(null);
    const t0 = performance.now();
    try {
      const r = await fetch(finalUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 99, method: 'eth_blockNumber', params: [] }),
        signal: AbortSignal.timeout(7000),
      });
      const j = await r.json();
      if (j.result) { setLatency(Math.round(performance.now() - t0)); setTestState('ok'); }
      else setTestState('fail');
    } catch { setTestState('fail'); }
  }

  async function addMM() {
    setMmState('pending');
    try {
      await window.ethereum.request({
        method: 'wallet_addEthereumChain',
        params: [{
          chainId: '0x' + chain.chainId.toString(16),
          chainName: chain.label,
          nativeCurrency: { name: chain.symbol, symbol: chain.symbol, decimals: 18 },
          rpcUrls: [finalUrl],
          blockExplorerUrls: [chain.explorer],
        }],
      });
      setMmState('ok');
    } catch { setMmState('fail'); }
    setTimeout(() => setMmState(null), 3000);
  }

  // MetaMask config snippet
  const configSnippet = `// MetaMask / Web3 provider config
const provider = new ethers.JsonRpcProvider("${finalUrl}");
// Chain ID: ${chain.chainId}  |  Symbol: ${chain.symbol}`;

  return (
    <section aria-labelledby="rpc-gen-h" className="mb-6">
      {/* Section header */}
      <div className="flex items-center justify-between mb-3">
        <h2 id="rpc-gen-h" className="text-xs text-gray-500 uppercase tracking-widest">⚙️ RPC Endpoint Generator</h2>
        {testState === 'ok' && (
          <span className="text-[10px] font-bold text-emerald-400 border border-emerald-500/30 bg-emerald-500/8 px-2.5 py-1 rounded-sm font-mono" aria-live="polite">
            ✓ LIVE · {latency}ms
          </span>
        )}
        {testState === 'fail' && (
          <span className="text-[10px] font-bold text-red-400 border border-red-400/30 bg-red-400/8 px-2.5 py-1 rounded-sm font-mono" aria-live="polite">
            ✗ UNREACHABLE
          </span>
        )}
      </div>

      <div className="border border-white/8 rounded-sm overflow-hidden">
        {/* Accent bar */}
        <div className="h-0.5 w-full" style={{ background: `linear-gradient(90deg, ${chain.color}88, transparent 70%)` }} />

        <div className="p-5 space-y-5 bg-[#080d18]">

          {/* ① Chain grid */}
          <div>
            <div className="text-[9px] text-gray-600 uppercase tracking-widest font-mono mb-2.5">① Select network</div>
            <div className="grid grid-cols-4 sm:grid-cols-8 gap-1.5">
              {RPC_CHAINS.map(c => (
                <button
                  key={c.id}
                  onClick={() => pickChain(c.id)}
                  aria-pressed={chainId === c.id}
                  className={`flex flex-col items-center gap-1 py-2.5 px-1 rounded-sm text-center transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 text-[10px] font-bold border ${
                    chainId === c.id
                      ? 'text-white'
                      : 'border-white/6 bg-white/2 text-gray-500 hover:text-gray-300 hover:border-white/15'
                  }`}
                  style={chainId === c.id ? { borderColor: c.color + '55', background: c.color + '18', color: '#fff' } : {}}
                >
                  <span className="text-base leading-none" aria-hidden="true">{c.dot}</span>
                  <span className="font-mono">{c.short}</span>
                </button>
              ))}
            </div>
          </div>

          {/* ② Provider */}
          <div>
            <div className="text-[9px] text-gray-600 uppercase tracking-widest font-mono mb-2.5">② Choose provider</div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
              {chain.providers.map((p, i) => (
                <button
                  key={i}
                  onClick={() => { setProvIdx(i); setTestState(null); setLatency(null); }}
                  aria-pressed={provIdx === i}
                  className={`text-left px-3 py-2.5 rounded-sm text-xs transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 border ${
                    provIdx === i
                      ? 'border-cyan-400/35 bg-cyan-400/8 text-cyan-300'
                      : 'border-white/6 bg-white/2 text-gray-500 hover:text-gray-300 hover:border-white/15'
                  }`}
                >
                  <span className="font-semibold text-white block mb-0.5">{p.name}</span>
                  <span className="font-mono text-[10px] text-gray-500 truncate block">{p.url.replace('{API_KEY}', '…')}</span>
                </button>
              ))}
            </div>
          </div>

          {/* ③ API Key — shown when needed */}
          {needsKey && (
            <div>
              <label htmlFor="rpc-key" className="text-[9px] text-gray-600 uppercase tracking-widest font-mono block mb-2">
                ③ API key <span className="text-amber-400">required</span>
              </label>
              <input
                id="rpc-key"
                type="text"
                value={apiKey}
                onChange={e => setApiKey(e.target.value)}
                placeholder="Paste your Infura / Alchemy / QuickNode key…"
                autoComplete="off"
                spellCheck={false}
                className="w-full px-3 py-2.5 rounded-sm bg-black/40 border border-white/10 text-white text-xs font-mono placeholder:text-gray-700 focus:outline-none focus:border-cyan-400/50 focus:ring-1 focus:ring-cyan-400/25"
              />
              <p className="text-[10px] text-gray-700 mt-1.5">Your key is never stored — it's only used to build the URL.</p>
            </div>
          )}

          {/* Generated URL */}
          <div>
            <div className="text-[9px] text-gray-600 uppercase tracking-widest font-mono mb-2">
              {needsKey ? '④' : '③'} Generated RPC URL
            </div>
            <div className="flex items-stretch gap-2">
              <div
                className="flex-1 px-4 py-3 rounded-sm bg-black/60 border border-cyan-400/20 font-mono text-xs break-all select-all leading-relaxed"
                style={{ color: chain.color }}
                role="textbox"
                aria-readonly="true"
                aria-label="Generated RPC URL"
              >
                {finalUrl}
              </div>
              <button
                onClick={copyUrl}
                aria-label="Copy RPC URL to clipboard"
                className={`shrink-0 px-4 rounded-sm text-xs font-bold transition-all border focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 ${
                  copied
                    ? 'bg-emerald-500/15 border-emerald-500/35 text-emerald-300'
                    : 'bg-white/5 border-white/12 text-gray-300 hover:text-white hover:border-white/25'
                }`}
              >
                {copied ? '✓' : 'Copy'}
              </button>
            </div>
          </div>

          {/* Meta row */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {[
              { l: 'Chain ID',  v: chain.chainId },
              { l: 'Currency',  v: chain.symbol },
              { l: 'Provider',  v: provider.name },
              { l: 'Explorer',  v: chain.explorer.replace('https://', '') },
            ].map(d => (
              <div key={d.l} className="bg-black/30 border border-white/5 rounded-sm px-3 py-2">
                <div className="text-[8px] text-gray-700 uppercase tracking-widest font-mono mb-0.5">{d.l}</div>
                <div className="text-xs text-white font-mono truncate">{String(d.v)}</div>
              </div>
            ))}
          </div>

          {/* Action bar */}
          <div className="flex flex-wrap gap-2 pt-1">
            <button
              onClick={testConn}
              disabled={testState === 'testing' || (needsKey && !apiKey.trim())}
              aria-live="polite"
              className="flex items-center gap-2 px-4 py-2 rounded-sm text-xs font-bold transition-all border focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 disabled:opacity-35 disabled:cursor-not-allowed"
              style={{ background: 'rgba(34,211,238,0.08)', borderColor: 'rgba(34,211,238,0.25)', color: '#22d3ee' }}
            >
              {testState === 'testing'
                ? <><span className="w-3 h-3 border-2 border-cyan-400/30 border-t-cyan-400 rounded-full animate-spin" aria-hidden="true"/><span>Testing…</span></>
                : '⚡ Test Connection'}
            </button>

            {typeof window !== 'undefined' && window.ethereum && (
              <button
                onClick={addMM}
                disabled={mmState === 'pending' || (needsKey && !apiKey.trim())}
                className="flex items-center gap-2 px-4 py-2 rounded-sm text-xs font-bold transition-all border focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 disabled:opacity-35"
                style={{ background: 'rgba(245,158,11,0.08)', borderColor: 'rgba(245,158,11,0.25)', color: '#f59e0b' }}
              >
                {mmState === 'pending' ? '…' : mmState === 'ok' ? '✓ Added!' : mmState === 'fail' ? '✗ Failed' : '🦊 Add to MetaMask'}
              </button>
            )}

            <a
              href={chain.explorer}
              target="_blank"
              rel="noreferrer"
              className="flex items-center gap-2 px-4 py-2 rounded-sm text-xs font-bold transition-all border focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-400"
              style={{ background: 'rgba(167,139,250,0.08)', borderColor: 'rgba(167,139,250,0.25)', color: '#a78bfa' }}
            >
              🔍 Explorer ↗
            </a>

            <button
              onClick={() => setShowConfig(s => !s)}
              className="flex items-center gap-2 px-4 py-2 rounded-sm text-xs font-bold transition-all border border-white/10 text-gray-400 hover:text-gray-200 hover:border-white/20 focus:outline-none focus-visible:ring-2 focus-visible:ring-white/30"
            >
              {showConfig ? '↑ Hide snippet' : '{} Code snippet'}
            </button>
          </div>

          {/* Code snippet */}
          {showConfig && (
            <div>
              <div className="text-[9px] text-gray-600 uppercase tracking-widest font-mono mb-1.5">Web3 / ethers.js provider snippet</div>
              <pre className="bg-black/60 border border-white/8 rounded-sm px-4 py-3 text-[11px] font-mono text-emerald-400 overflow-x-auto whitespace-pre-wrap">{configSnippet}</pre>
            </div>
          )}

        </div>
      </div>
    </section>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────
export default function Network() {
  useLedgerPageView('Network');
  const company = pb.authStore.record;

  const subnetId = company?.id
    ? `CF-${company.id.slice(0, 4).toUpperCase()}-${company.id.slice(-4).toUpperCase()}`
    : 'CF-0000-0000';
  const [copied, setCopied] = useState(false);

  const isPrivate  = company?.company_type === 'private';
  const customRpc  = company?.custom_rpc_url;
  const networkKey = company?.blockchain_network || 'bnb_chain';
  const preset     = NETWORK_PRESETS[networkKey];
  const rpcUrl     = isPrivate && customRpc ? customRpc : (preset?.rpc || 'https://cloudflare-eth.com');
  const networkLabel = isPrivate ? (company?.network_name || 'Private Network') : (preset?.label || 'Ethereum');
  const explorerUrl  = isPrivate ? null : preset?.explorer;

  const [status,     setStatus]     = useState('connecting');
  const [blockNumber,setBlockNumber] = useState(null);
  const [gasPrice,   setGasPrice]   = useState(null);
  const [baseFee,    setBaseFee]    = useState(null);
  const [blocks,     setBlocks]     = useState([]);
  const [freshHashes,setFreshHashes]= useState(new Set());
  const [lastUpdated,setLastUpdated]= useState(null);
  const [error,      setError]      = useState(null);
  const [pulse,      setPulse]      = useState(0); // increments on each new block → triggers map flash

  const pollRef  = useRef(null);
  const knownRef = useRef(new Set());

  const fetchData = useCallback(async () => {
    const rpc = makeRpc(rpcUrl);
    try {
      const [hexBlock, hexGas] = await Promise.all([rpc('eth_blockNumber'), rpc('eth_gasPrice')]);
      const num = hexN(hexBlock);
      setBlockNumber(num);
      setGasPrice(gwei(hexGas));

      const nums = Array.from({ length: 6 }, (_, i) => num - i);
      const data = await Promise.all(nums.map(n => rpc('eth_getBlockByNumber', ['0x' + n.toString(16), false])));
      const valid = data.filter(Boolean);

      const freshSet = new Set();
      valid.forEach(b => {
        if (b.hash && !knownRef.current.has(b.hash)) {
          freshSet.add(b.hash);
          knownRef.current.add(b.hash);
        }
      });

      if (valid[0]?.baseFeePerGas) setBaseFee(gwei(valid[0].baseFeePerGas));
      setBlocks(valid);
      setFreshHashes(freshSet);
      setStatus('live');
      setLastUpdated(new Date());
      setError(null);
      if (freshSet.size > 0) setPulse(p => p + 1);
      setTimeout(() => setFreshHashes(new Set()), 4000);
    } catch {
      setError('Could not reach the network. Retrying…');
      setStatus('connecting');
    }
  }, [rpcUrl]);

  useEffect(() => {
    knownRef.current = new Set();
    setBlocks([]); setStatus('connecting'); setError(null);
    fetchData();
    pollRef.current = setInterval(fetchData, 12000);
    return () => clearInterval(pollRef.current);
  }, [fetchData]);

  const totalTxns = blocks.reduce((s, b) => s + (b.transactions?.length ?? 0), 0);

  async function copySubnet() {
    await navigator.clipboard.writeText(subnetId);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="max-w-7xl mx-auto px-4 md:px-8 py-8">

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4 mb-6">
        <div>
          <h1 className="text-3xl font-black text-white mb-1" style={{ fontFamily: "'Syne', sans-serif" }}>
            Network
          </h1>
          <p className="text-gray-500 text-sm flex items-center gap-2 flex-wrap">
            <span>{networkLabel} · refreshes every 12s</span>
            {explorerUrl && (
              <a href={explorerUrl} target="_blank" rel="noopener noreferrer"
                className="text-cyan-400/70 hover:text-cyan-400 transition-colors">
                Explorer ↗
              </a>
            )}
            {lastUpdated && <span className="text-gray-600">· {lastUpdated.toLocaleTimeString()}</span>}
          </p>
        </div>

        <div className={`flex items-center gap-2 text-xs font-medium px-3 py-1.5 rounded-full border ${
          status === 'live'
            ? 'border-emerald-500/30 bg-emerald-500/8 text-emerald-400'
            : 'border-gray-600/30 bg-gray-600/8 text-gray-500'
        }`}>
          {status === 'live'
            ? <><span className="relative flex h-2 w-2"><span className="animate-ping absolute h-full w-full rounded-full bg-emerald-400 opacity-75"/><span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-400"/></span> Live</>
            : <><span className="w-2 h-2 rounded-full bg-gray-600"/> Connecting…</>}
        </div>
      </div>

      {error && (
        <div role="alert" className="mb-5 text-amber-400 text-sm bg-amber-400/8 border border-amber-400/20 rounded-sm px-4 py-3">
          {error}
        </div>
      )}

      {/* Live Node Map */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-xs text-gray-500 uppercase tracking-widest">Live validator nodes</h2>
          <span className="text-[10px] text-gray-700 font-mono">{NODE_POSITIONS.length} global nodes · flashes on block</span>
        </div>
        <NodeMap pulse={pulse} status={status} />
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <Tile label="Block height" value={blockNumber ? blockNumber.toLocaleString() : '—'} sub="current block" accent live={status === 'live'} />
        <Tile label="Gas price"   value={gasPrice ?? '—'} sub="gwei" />
        <Tile label="Base fee"    value={baseFee  ?? '—'} sub="gwei EIP-1559" />
        <Tile label="Txns (last 6 blocks)" value={totalTxns || '—'} sub="transactions" />
      </div>

      {/* RPC Endpoint Generator */}
      <RpcGenerator />

      {/* Chain info + Subnet ID side by side */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        {/* Chain info */}
        <div className="border border-white/8 bg-white/2 rounded-sm p-5">
          <div className="text-xs text-gray-500 uppercase tracking-widest mb-3">Chain info</div>
          <div className="space-y-2">
            {[
              ['Chain ID',   preset?.chainId ?? 'Custom'],
              ['Block time', preset?.blockTime ?? '—'],
              ['Consensus',  preset?.consensus ?? '—'],
              ['Network',    networkLabel],
            ].map(([l, v]) => (
              <div key={l} className="flex justify-between text-sm">
                <span className="text-gray-500">{l}</span>
                <span className="text-white font-medium font-mono text-xs">{v}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Subnet / Network ID */}
        <div className="border border-cyan-500/25 bg-gradient-to-br from-cyan-500/8 to-transparent rounded-sm p-5">
          <div className="text-xs text-cyan-400/70 uppercase tracking-widest mb-2">Your Network ID (Subnet)</div>
          <div className="flex items-center gap-3 mb-3">
            <code className="text-2xl font-black font-mono text-cyan-400 tracking-widest flex-1">{subnetId}</code>
            <button
              onClick={copySubnet}
              className={`text-xs px-3 py-1.5 border rounded-sm transition-colors ${copied ? 'border-emerald-500/40 text-emerald-400' : 'border-white/15 text-gray-400 hover:text-cyan-400 hover:border-cyan-500/40'}`}
            >
              {copied ? '✓ Copied' : 'Copy'}
            </button>
          </div>
          <p className="text-xs text-gray-500 leading-relaxed">
            Enter this ID on any machine, scanner, or computer to join your chain.
            Visit <a href="../../dashboard/devices" className="text-cyan-400/80 hover:text-cyan-400 underline">Devices</a> to manage connections.
          </p>
        </div>
      </div>

      {/* Recent blocks */}
      <div className="border border-white/8 rounded-sm overflow-hidden">
        <div className="px-4 py-3 bg-white/3 flex items-center justify-between">
          <span className="text-xs text-gray-400 uppercase tracking-widest">Recent blocks</span>
          <button onClick={fetchData} className="text-[10px] text-cyan-400/60 hover:text-cyan-400 border border-cyan-500/20 px-2 py-1 rounded-sm transition-colors">
            Refresh
          </button>
        </div>
        <div className="px-4 py-2 border-b border-white/5 text-[10px] text-gray-600 uppercase tracking-widest"
          style={{ display: 'grid', gridTemplateColumns: '5rem 1fr 4rem 5rem' }}>
          <span className="text-right">Number</span>
          <span className="px-3">Hash</span>
          <span className="text-right">Txns</span>
          <span className="text-right">Time</span>
        </div>
        {blocks.length === 0 ? (
          <div className="px-4 py-8 text-center text-gray-600 text-sm font-mono animate-pulse">
            Fetching blocks…
          </div>
        ) : (
          blocks.map(b => (
            <BlockRow key={b.hash} block={b} fresh={freshHashes.has(b.hash)} />
          ))
        )}
      </div>
    </div>
  );
}
