// Shared browser helpers for Jose v3 pages: config, MetaMask (add network,
// add JOSE token, link wallet, pay for credits), and small UI utilities.
// Everything goes through window.ethereum; no wallet library needed.

window.Jose = (() => {
  let configPromise;
  const getConfig = () => (configPromise ||= fetch('/api/config').then((r) => r.json()));

  const hasWallet = () => typeof window.ethereum !== 'undefined';

  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  const shortAddr = (a) => (a ? `${a.slice(0, 6)}…${a.slice(-4)}` : '');

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      method: opts.method || (opts.body ? 'POST' : 'GET'),
      headers: opts.body ? { 'Content-Type': 'application/json' } : undefined,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    const body = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, body };
  }

  function requireWallet() {
    if (!hasWallet()) throw new Error('No encontramos MetaMask en este navegador. Instálalo desde metamask.io y recarga la página.');
  }

  async function connect() {
    requireWallet();
    const [account] = await window.ethereum.request({ method: 'eth_requestAccounts' });
    return account;
  }

  async function addNetwork() {
    requireWallet();
    const { chain } = await getConfig();
    try {
      await window.ethereum.request({ method: 'wallet_switchEthereumChain', params: [{ chainId: chain.chainIdHex }] });
    } catch (err) {
      // 4902 = this chain isn't in the wallet yet, so add it.
      if (err.code !== 4902 && err?.data?.originalError?.code !== 4902) throw err;
      await window.ethereum.request({
        method: 'wallet_addEthereumChain',
        params: [{
          chainId: chain.chainIdHex,
          chainName: chain.chainName,
          nativeCurrency: chain.nativeCurrency,
          rpcUrls: [chain.rpcUrl],
          blockExplorerUrls: [chain.explorerUrl],
        }],
      });
    }
  }

  async function addToken() {
    requireWallet();
    const { token } = await getConfig();
    if (!token.address) throw new Error('La dirección del token JOSE todavía no está publicada en este servidor.');
    await addNetwork();
    return window.ethereum.request({
      method: 'wallet_watchAsset',
      params: { type: 'ERC20', options: { address: token.address, symbol: token.symbol, decimals: token.decimals, ...(token.image ? { image: token.image } : {}) } },
    });
  }

  async function linkWallet() {
    const address = await connect();
    const challenge = await api('/api/wallet/challenge', { body: { address } });
    if (!challenge.ok) throw new Error(challenge.body.error);
    const signature = await window.ethereum.request({ method: 'personal_sign', params: [challenge.body.message, address] });
    const linked = await api('/api/wallet/link', { body: { signature } });
    if (!linked.ok) throw new Error(linked.body.error);
    return linked.body.wallet;
  }

  // "1.5" with 18 decimals -> 1500000000000000000n
  function toUnits(amount, decimals) {
    const [whole, frac = ''] = String(amount).split('.');
    return BigInt(whole || '0') * 10n ** BigInt(decimals) + BigInt((frac + '0'.repeat(decimals)).slice(0, decimals) || '0');
  }

  // Sends JOSE to the treasury for `credits` credits; returns the tx hash.
  async function payForCredits(credits, linkedWallet) {
    const cfg = await getConfig();
    if (!cfg.payments.enabled) throw new Error('Pagar con JOSE todavía no está activado en este servidor.');
    const from = await connect();
    if (linkedWallet && from.toLowerCase() !== linkedWallet.toLowerCase()) {
      throw new Error(`Cambia en MetaMask a tu billetera vinculada (${shortAddr(linkedWallet)}) para pagar.`);
    }
    await addNetwork();
    const amount = toUnits(String(cfg.payments.josePerCredit), cfg.token.decimals) * BigInt(credits);
    const to = cfg.payments.treasuryAddress.toLowerCase().replace(/^0x/, '').padStart(64, '0');
    const data = '0xa9059cbb' + to + amount.toString(16).padStart(64, '0'); // transfer(address,uint256)
    return window.ethereum.request({ method: 'eth_sendTransaction', params: [{ from, to: cfg.token.address, data }] });
  }

  // Polls the server until the payment is confirmed and credited.
  async function claimPayment(txHash, onWait) {
    for (let i = 0; i < 60; i++) {
      const r = await api('/api/credits/claim', { body: { txHash } });
      if (r.ok) return r.body;
      if (r.status !== 404 && r.status !== 425 && r.status !== 502) throw new Error(r.body.error);
      onWait?.(r.body.error);
      await new Promise((res) => setTimeout(res, 5000));
    }
    throw new Error('El pago tarda más de lo normal. Pega el hash de la transacción más tarde para reclamarlo.');
  }

  function ipfsToHttp(uri) {
    if (!uri) return '';
    if (uri.startsWith('ipfs://')) return 'https://ipfs.io/ipfs/' + uri.slice(7).replace(/^ipfs\//, '');
    if (uri.startsWith('ar://')) return 'https://arweave.net/' + uri.slice(5);
    return uri;
  }

  // Reads NFT metadata (name, image, description) from a tokenURI.
  async function loadMetadata(tokenURI) {
    if (!tokenURI) return {};
    try {
      if (tokenURI.startsWith('data:application/json')) {
        const [, payload] = tokenURI.split(',', 2);
        const json = tokenURI.includes(';base64,') ? atob(payload) : decodeURIComponent(payload);
        return JSON.parse(json);
      }
      const res = await fetch(ipfsToHttp(tokenURI), { signal: AbortSignal.timeout(10000) });
      return await res.json();
    } catch {
      return {};
    }
  }

  // Only let through image URLs a browser can safely load in <img>.
  function safeImage(url) {
    const u = ipfsToHttp(url || '');
    return /^(https:\/\/|data:image\/)/.test(u) ? u : '';
  }

  function nav(active) {
    const items = [
      ['chat.html', 'Hey Jose'],
      ['market.html', 'Mercado NFT'],
      ['dashboard.html', 'Mi cuenta'],
    ];
    return `<nav class="appnav">
      <a class="wordmark" href="dashboard.html">Jose</a>
      <div class="appnav-links">${items.map(([href, label]) => `<a href="${href}"${href === active ? ' class="active"' : ''}>${label}</a>`).join('')}</div>
    </nav>`;
  }

  return {
    getConfig, hasWallet, escapeHtml, shortAddr, api, connect, addNetwork, addToken,
    linkWallet, payForCredits, claimPayment, loadMetadata, safeImage, nav,
  };
})();
