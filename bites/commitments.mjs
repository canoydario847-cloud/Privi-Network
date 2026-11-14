export const SERVICES = ['Ledger','Verify','Anchor','Quantum','Call','Guard','LIFE','Hey Jose','Hub','Mainnet','Chem','Car','Food','Space','DAO'];
export function validateProfile(value) {
  if (!value || typeof value !== 'object' || typeof value.name !== 'string' || value.name.trim().length < 1 || value.name.length > 100) throw new Error('Enter a name of 1–100 characters.');
  if (typeof value.contact !== 'string' || value.contact.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.contact)) throw new Error('Enter a valid contact email.');
  if (value.consent !== true) throw new Error('Consent is required to store this profile.');
  if (!Array.isArray(value.services) || value.services.some(x => !SERVICES.includes(x))) throw new Error('Unknown Privi service.');
  return {name:value.name.trim(), contact:value.contact.trim(), services:[...new Set(value.services)].sort(), consentVersion:'bites-1'};
}
export async function commitment(profile, salt = crypto.randomUUID()) {
  // Random salt stays out of the ledger: low-entropy contact data cannot be guessed from a receipt.
  const bytes = new TextEncoder().encode('privi-bites:v1\n'+salt+'\n'+JSON.stringify(profile));
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');
}
