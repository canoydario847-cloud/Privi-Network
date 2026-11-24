// Privi Voice for Hey Jose: browser speech synthesis, no voice API charges.
// Only voice preferences are saved. Speech content is never stored here.
import {DEFAULT_VOICE_SETTINGS,normalizeVoiceSettings,prepareSpeechText,splitSpeechText}
  from './privi-voice-core.mjs';

const $=id=>document.getElementById(id);
const available=Boolean(window.speechSynthesis&&window.SpeechSynthesisUtterance);
const synth=available?window.speechSynthesis:null;
const STORE='hey-jose-privi-voice-settings-v1';
let settings=DEFAULT_VOICE_SETTINGS,voiceList=[],run=0;

try{settings=normalizeVoiceSettings(JSON.parse(localStorage.getItem(STORE)||'{}'));}
catch{settings={...DEFAULT_VOICE_SETTINGS};}

function save(){
  try{localStorage.setItem(STORE,JSON.stringify(settings));}catch{}
}
function status(message){$('priviVoiceNotice').textContent=message;}
function resetStop(){
  $('priviVoiceStop').disabled=true;
}
function stop(){
  ++run;
  if(available)synth.cancel();
  resetStop();
  status(available?'Playback stopped.':'Text-to-speech is not supported in this browser.');
}
function chooseVoice(){
  return voiceList.find(v=>v.voiceURI===settings.voiceUri)||null;
}
function refreshVoices(){
  if(!available)return;
  try{voiceList=synth.getVoices().slice().sort((a,b)=>
    a.lang.localeCompare(b.lang)||a.name.localeCompare(b.name));}
  catch{voiceList=[];}
  const sel=$('priviVoiceSelect'),previous=sel.value||settings.voiceUri;
  sel.replaceChildren();
  const defaultOption=document.createElement('option');
  defaultOption.value='';defaultOption.textContent='System default';
  sel.append(defaultOption);
  for(const voice of voiceList){
    const option=document.createElement('option');
    option.value=voice.voiceURI;
    option.textContent=voice.name+' ('+voice.lang+')'+(voice.localService?' · device':'');
    sel.append(option);
  }
  sel.value=voiceList.some(v=>v.voiceURI===previous)?previous:'';
  if(!voiceList.some(v=>v.voiceURI===settings.voiceUri)){
    settings={...settings,voiceUri:''};
    save();
  }
  if(available&&voiceList.length===0)
    status('Using your system default voice. More voices may appear after your browser loads them.');
}
function read(value){
  if(!available){
    status('Privi Voice is unavailable in this browser. Try a current Chrome, Edge, or Safari browser.');
    return false;
  }
  const text=prepareSpeechText(value);
  if(!text){
    status('There is no text to read.');
    return false;
  }
  stop();
  const activeRun=run;
  const parts=splitSpeechText(text);
  const selected=chooseVoice();
  const speakNext=(index)=>{
    if(run!==activeRun)return;
    if(index>=parts.length){
      resetStop();status('Finished reading.');return;
    }
    const utterance=new SpeechSynthesisUtterance(parts[index]);
    utterance.rate=settings.rate;
    utterance.pitch=settings.pitch;
    utterance.volume=1;
    if(selected){utterance.voice=selected;utterance.lang=selected.lang;}
    else utterance.lang=navigator.language||'en-US';
    utterance.onend=()=>speakNext(index+1);
    utterance.onerror=event=>{
      if(run!==activeRun)return;
      resetStop();
      if(event?.error!=='interrupted'&&event?.error!=='canceled')
        status('Voice playback failed or was blocked. Try pressing Listen again.');
    };
    try{
      synth.speak(utterance);
      $('priviVoiceStop').disabled=false;
      status('Reading with Privi Voice…');
    }catch{
      resetStop();status('Unable to start speech in this browser.'); 
    }
  };
  speakNext(0);
  return true;
}
function toggle(){
  const panel=$('priviVoicePanel');
  panel.hidden=!panel.hidden;
  $('priviVoiceBtn').setAttribute('aria-expanded',String(!panel.hidden));
  if(!panel.hidden){
    refreshVoices();
    $('priviVoiceSelect').focus();
  }
}

$('priviVoiceBtn').addEventListener('click',toggle);
$('priviVoiceClose').addEventListener('click',()=>{ 
  $('priviVoicePanel').hidden=true;
  $('priviVoiceBtn').setAttribute('aria-expanded','false');
  $('priviVoiceBtn').focus();
});
$('priviVoiceSelect').addEventListener('change',event=>{
  settings={...settings,voiceUri:event.target.value};save();
  if(available&&synth.speaking)stop();
});
$('priviVoiceRate').addEventListener('input',event=>{
  settings=normalizeVoiceSettings({...settings,rate:Number(event.target.value)});
  $('priviVoiceRateValue').textContent=settings.rate.toFixed(1)+'×';
  save();
});
$('priviVoicePitch').addEventListener('input',event=>{
  settings=normalizeVoiceSettings({...settings,pitch:Number(event.target.value)});
  $('priviVoicePitchValue').textContent=settings.pitch.toFixed(1);
  save();
});
$('priviVoiceAuto').addEventListener('change',event=>{
  settings={...settings,autoRead:event.target.checked};
  save();
  status(settings.autoRead?
    'Auto-read enabled. New regular answers will be spoken when your browser allows playback.':
    'Auto-read off. Use Listen to hear any answer.');
});
$('priviVoicePreview').addEventListener('click',()=>{
  read('Hello! This is Privi Voice. You can listen to Hey Jose at your own speed.');
});
$('priviVoiceStop').addEventListener('click',stop);
$('priviVoiceLast').addEventListener('click',()=>{
  const latest=window.joseAddons?.getLastReply?.()||'';
  if(latest)read(latest);
  else status('Ask Hey Jose something first, or choose Try voice.');
});
$('priviVoiceMic').addEventListener('click',()=>{
  $('voice').click();
});
$('priviVoiceRate').value=String(settings.rate);
$('priviVoicePitch').value=String(settings.pitch);
$('priviVoiceSelect').value=settings.voiceUri;
$('priviVoiceRateValue').textContent=settings.rate.toFixed(1)+'×';
$('priviVoicePitchValue').textContent=settings.pitch.toFixed(1);
$('priviVoiceAuto').checked=settings.autoRead;
$('priviVoiceStop').disabled=true;
if(!available){
  for(const id of ['priviVoiceSelect','priviVoiceRate','priviVoicePitch','priviVoiceAuto',
    'priviVoicePreview','priviVoiceStop','priviVoiceLast'])$(id).disabled=true;
  status('Privi Voice text-to-speech is not available in this browser. Microphone dictation may still work.');
}else{
  synth.addEventListener?.('voiceschanged',refreshVoices);
  refreshVoices();
  status('Free browser voices. Choose a voice, then select Listen on any Jose reply.');
}
window.addEventListener('pagehide',()=>{if(available)synth.cancel();});
window.priviVoice=Object.freeze({
  supported:available,
  read,
  onAnswer(value){
    if(settings.autoRead)return read(value);
    return false;
  },
  stop,
  settings:()=>({...settings}),
});
