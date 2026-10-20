// Everything Jose v3 reads from the environment, in one place.
// Nothing here is secret except ANTHROPIC_API_KEY; /api/config exposes the
// public parts so the pages and the website use the same values.

const num = (v, d) => (v === undefined || v === '' || isNaN(Number(v)) ? d : Number(v));

export const config = {
  // --- Hey Jose (AI chat) ---
  anthropicApiKey: process.env.ANTHROPIC_API_KEY || '',
  anthropicBaseUrl: (process.env.ANTHROPIC_BASE_URL || 'https://api.anthropic.com').replace(/\/$/, ''),
  aiModel: process.env.JOSE_AI_MODEL || 'claude-sonnet-5-5',
  aiMaxTokens: num(process.env.JOSE_AI_MAX_TOKENS, 1024),
  freeCredits: num(process.env.JOSE_FREE_CREDITS, 10), // given once, at signup
  creditsPerMessage: num(process.env.JOSE_CREDITS_PER_MESSAGE, 1),

  // --- JOSE token on Base ---
  chainId: num(process.env.JOSE_CHAIN_ID, 8453), // Base mainnet
  chainName: process.env.JOSE_CHAIN_NAME || 'Base',
  rpcUrl: process.env.JOSE_RPC_URL || 'https://mainnet.base.org',
  explorerUrl: process.env.JOSE_EXPLORER_URL || 'https://basescan.org',
  tokenAddress: process.env.JOSE_TOKEN_ADDRESS || '',
  tokenSymbol: process.env.JOSE_TOKEN_SYMBOL || 'JOSE',
  tokenDecimals: num(process.env.JOSE_TOKEN_DECIMALS, 18),
  tokenImage: process.env.JOSE_TOKEN_IMAGE || '',
  // Wallet that receives JOSE paid for AI credits.
  treasuryAddress: process.env.JOSE_TREASURY_ADDRESS || '',
  // How many whole JOSE buy one credit (decimals are read from the token).
  josePerCredit: num(process.env.JOSE_PER_CREDIT, 1),
  minConfirmations: num(process.env.JOSE_MIN_CONFIRMATIONS, 3),
};

export function paymentsConfigured() {
  return Boolean(config.tokenAddress && config.treasuryAddress && config.rpcUrl);
}

export function publicConfig() {
  return {
    ai: { enabled: Boolean(config.anthropicApiKey), creditsPerMessage: config.creditsPerMessage, freeCredits: config.freeCredits },
    chain: {
      chainId: config.chainId,
      chainIdHex: '0x' + config.chainId.toString(16),
      chainName: config.chainName,
      rpcUrl: config.rpcUrl,
      explorerUrl: config.explorerUrl,
      nativeCurrency: { name: 'Ether', symbol: 'ETH', decimals: 18 },
    },
    token: {
      address: config.tokenAddress || null,
      symbol: config.tokenSymbol,
      decimals: config.tokenDecimals,
      image: config.tokenImage || null,
    },
    payments: {
      enabled: paymentsConfigured(),
      treasuryAddress: config.treasuryAddress || null,
      josePerCredit: config.josePerCredit,
      minConfirmations: config.minConfirmations,
    },
  };
}
