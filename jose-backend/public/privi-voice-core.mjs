// Privi Voice — cost-free browser speech helpers, no model API or paid TTS.
export const DEFAULT_VOICE_SETTINGS=Object.freeze({
  voiceUri:'',rate:1,pitch:1,autoRead:false,
});
const bound=(value,min,max,fallback)=>{
  const num=Number(value);
  return Number.isFinite(num)?Math.min(max,Math.max(min,num)):fallback;
};
export function normalizeVoiceSettings(value){
  const raw=value&&typeof value==='object'&&!Array.isArray(value)?value:{};
  return {
    voiceUri:typeof raw.voiceUri==='string'?raw.voiceUri.slice(0,250):'',
    rate:bound(raw.rate,0.6,2,1),
    pitch:bound(raw.pitch,0.7,1.5,1),
    autoRead:raw.autoRead===true,
  };
}

// Keep a clear spoken summary, not a recitation of enormous generated source code.
// Raw conversation contents and attachments are never stored by Privi Voice.
export function prepareSpeechText(value){
  if(typeof value!=='string')return '';
  return value
    .replace(/\x60{3}[\s\S]*?\x60{3}/g,' Code sample omitted. ')
    .replace(/!\[([^\]]*)\]\([^)]+\)/g,' $1 ')
    .replace(/\[([^\]]+)\]\([^)]+\)/g,'$1')
    .replace(/\x60([^\x60]+)\x60/g,'$1')
    .replace(/^(?:\s{0,3}#{1,6}|\s{0,3}[-*]|\s{0,3}\d+\.)\s+/gm,'')
    .replace(/[*_~]/g,'')
    .replace(/\s+/g,' ')
    .trim()
    .slice(0,10000);
}

export function splitSpeechText(value,maxChunk=230){
  const text=typeof value==='string'?value.trim():'';
  if(!text)return [];
  const cap=Math.max(80,Math.min(350,Math.trunc(maxChunk)||230));
  const chunks=[];
  let rest=text;
  while(rest.length>cap){
    // Keep sentence punctuation inside the cap (including the final mark).
    let cut=Math.max(
      rest.lastIndexOf('. ',cap-1),rest.lastIndexOf('! ',cap-1),
      rest.lastIndexOf('? ',cap-1),rest.lastIndexOf('。',cap-1),
      rest.lastIndexOf('।',cap-1));
    if(cut<cap*0.5)cut=rest.lastIndexOf(' ',cap);
    if(cut<cap*0.4)cut=cap;
    else if(rest[cut]==='。'||rest[cut]==='।')cut+=1;
    else if(rest[cut]==='.'||rest[cut]==='!'||rest[cut]==='?')cut+=1;
    const part=rest.slice(0,cut).trim();
    if(part)chunks.push(part);
    rest=rest.slice(cut).trim();
  }
  if(rest)chunks.push(rest);
  return chunks;
}
