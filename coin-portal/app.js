"use strict";
/**
 * Pre-launch portal. No purchase code, custody, analytics or outbound RPC.
 * Enabling a real sale requires a separately audited implementation and
 * verified deployment; changing a flag is intentionally not sufficient.
 */
const SALE_ENABLED = false;
if (SALE_ENABLED) {
  throw new Error("This pre-launch website does not implement sales. A reviewed, separate purchase application is required.");
}
const connectButton = document.getElementById("wallet-connect");
const status = document.getElementById("wallet-status");
const year = document.getElementById("copyright-year");
if (year) year.textContent = String(new Date().getFullYear());

const abbreviate = (address) => address.length > 16
  ? address.slice(0, 8) + "…" + address.slice(-6)
  : address;
const setStatus = (message) => {
  if (status) status.textContent = message;
};
async function connectReadOnly() {
  const provider = window.ethereum;
  if (!provider || typeof provider.request !== "function") {
    setStatus("No compatible browser wallet found. Install an EVM wallet to run this optional read-only check.");
    return;
  }
  connectButton.disabled = true;
  connectButton.textContent = "Checking wallet…";
  try {
    // No signatures, approvals, account imports, transactions or RPC POSTs.
    const accounts = await provider.request({method:"eth_requestAccounts"});
    const chain = await provider.request({method:"eth_chainId"});
    if (!Array.isArray(accounts) || !accounts.length || typeof chain !== "string") {
      setStatus("Unable to read an account and network. Try opening your wallet.");
      return;
    }
    const address = String(accounts[0]);
    if (!/^0x[a-fA-F0-9]{40}$/.test(address) || !/^0x[0-9a-fA-F]+$/.test(chain)) {
      setStatus("Wallet returned an unexpected address or network. No action was taken.");
      return;
    }
    const chainId = BigInt(chain).toString(10);
    setStatus("Wallet detected: " + abbreviate(address) + " · EVM chain " + chainId + ". Read-only check complete; PRVI purchases are unavailable.");
  } catch (err) {
    const code = typeof err === "object" && err !== null ? err.code : undefined;
    setStatus(code === 4001 ? "Wallet connection canceled. No action was taken."
      : "Wallet could not be checked. No action was taken.");
  } finally {
    connectButton.disabled = false;
    connectButton.textContent = "Check wallet (read only) ↗";
  }
}
if (connectButton) connectButton.addEventListener("click", connectReadOnly);
if (window.ethereum && typeof window.ethereum.on === "function") {
  window.ethereum.on("accountsChanged", () => setStatus("Account changed. Recheck wallet if desired; no funds are requested."));
  window.ethereum.on("chainChanged", () => setStatus("Network changed. Recheck wallet if desired; no funds are requested."));
}
