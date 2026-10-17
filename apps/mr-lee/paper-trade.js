"use strict";

// PAPER TRADING ONLY. No exchange connectors, custody, wallet signing,
// price feeds, broadcasts, approvals or real orders. Input prices are examples.
const SCALE = 1_000_000n;

function parseFixed(input, label) {
  if (typeof input !== "string" || !/^(?:0|[1-9][0-9]{0,14})(?:\.[0-9]{1,6})?$/.test(input)) {
    throw Error(label + " must be a nonnegative decimal string with up to six places");
  }
  const [int, fractional = ""] = input.split(".");
  return BigInt(int) * SCALE + BigInt(fractional.padEnd(6, "0"));
}
function displayFixed(n) {
  const whole = n / SCALE;
  const frac = String(n % SCALE).padStart(6, "0").replace(/0+$/, "");
  return String(whole) + (frac ? "." + frac : "");
}
function simulatePaperTrade(data) {
  if (!data || typeof data !== "object") throw Error("Paper trade payload required");
  const { symbol, side, price, quantity } = data;
  if (typeof symbol !== "string" || !/^[A-Z0-9._-]{2,16}\/[A-Z0-9._-]{2,16}$/.test(symbol)) {
    throw Error("Pair must be formatted like PRVI/USDC (illustrative only)");
  }
  if (side !== "buy" && side !== "sell") throw Error("Only buy or sell scenarios allowed");
  const p = parseFixed(price, "Price");
  const q = parseFixed(quantity, "Quantity");
  if (p <= 0n || q <= 0n) throw Error("Positive price and quantity required");
  const notional = (p * q) / SCALE;
  if (notional <= 0n) throw Error("Notional too small to calculate");
  // Fixed, illustrative ten basis points; not a quote from any market.
  const simulatedFee = (notional * 10n) / 10000n;
  return Object.freeze({
    mode: "paper_only", executed: false, connected_to_exchange: false,
    quote_is_live: false, user_supplied_price: true, symbol, side,
    price, quantity, simulated_fee_bps: 10,
    notional: displayFixed(notional),
    estimated_fee: displayFixed(simulatedFee),
    disclaimer: "Educational scenario only. No trade, transfer, swap or order was executed."
  });
}
module.exports = { simulatePaperTrade, parseFixed, displayFixed };
