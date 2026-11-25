// Privi Voice: free browser-native text-to-speech.
// Only settings are saved in this browser; conversation text stays in the chat.
import {
  DEFAULT_VOICE_SETTINGS,SPEECH_LANGUAGES,normalizeVoiceSettings,
  speechLanguage,prepareSpeechText,splitSpeechText,
} from './privi-voice-core.mjs';

const $=id=>document.getElementById(id);
const available=Boolean(window.speechSynthesis&&window.SpeechSynthesisUtterance);
const synth=available?window.speechSynthesis:null;
const STORE='hey-jose-privi-voice-settings-v1';
let settings={...DEFAULT_VOICE_SETTINGS},voiceList=[],run=0,active=false,paused=false;

try{settings=normalizeVoiceSettings(JSON.parse(localStorage.getItem(STORE)||'{}'));}
catch{settings={...DEFAULT_VOICE_SETTINGS};}

function save(){try{localStorage.setItem(STORE,JSON.stringify(settings));}catch{}}
function status(message){$('priviVoiceNotice').textContent=message;}
function controls(){
  $('priviVoiceStop').disabled=!available||!active;
  $('priviVoicePause').disabled=!available||!active;
  $('priviVoicePause').textContent=paused?'▶ Resume':'⏸ Pause';
  $('priviVoicePause').setAttribute('aria-label',paused?'Resume voice playback':'Pause voice playback');
}
function stop({quiet=false}={}){
  ++run;
  if(available)synth.cancel();
  active=false;paused=false;
  controls();
  if(!quiet)status(available?'Playback stopped.':'Text-to-speech unavailable in this browser.');
}
function chooseVoice(){
  const direct=voiceList.find(v=>v.voiceURI===settings.voiceUri);
  if(direct)return direct;
  const lang=speechLanguage(settings,navigator.language||'en-US').toLowerCase();
  return voiceList.find(v=>v.lang.toLowerCase()===lang)
    ||voiceList.find(v=>v.lang.slice(0,2).toLowerCase()===lang.slice(0,2))
    ||null;
}
function refreshVoices(){
  if(!available)return;
  try{voiceList=synth.getVoices().slice().sort((a,b)=>
    a.lang.localeCompare(b.lang)||a.name.localeCompare(b.name));}
  catch{voiceList=[];}
  const sel=$('priviVoiceSelect');
  sel.replaceChildren();
  const base=document.createElement('option');
  base.value='';base.textContent='Match language / system voice';
  sel.append(base);
  for(const v of voiceList){
    const option=document.createElement('option');
    option.value=v.voiceURI;
    option.textContent=v.name+' ('+v.lang+')'+(v.localService?' · device':'');
    sel.append(option);
  }
  // Do not throw away a stored preference while the browser loads its voices.
  sel.value=voiceList.some(v=>v.voiceURI===settings.voiceUri)?settings.voiceUri:'';
  if(!voiceList.length)status('Device voices are still loading; the default may be available.');
}
function read(value){
  if(!available){
    status('Text-to-speech is unavailable. Try a current Chrome, Edge or Safari browser.');
    return false;
  }
  const text=prepareSpeechText(value);
  if(!text){status('There is no reply text to read.');return false;}
  stop({quiet:true});
  const activeRun=run;
  const parts=splitSpeechText(text);
  const selected=chooseVoice();
  const language=speechLanguage(settings,navigator.language||'en-US');
  active=true;paused=false;controls();
  function next(index){
    if(run!==activeRun)return;
    if(index>=parts.length){
      active=false;paused=false;controls();status('Finished reading.');return;
    }
    const utterance=new SpeechSynthesisUtterance(parts[index]);
    utterance.rate=settings.rate;
    utterance.pitch=settings.pitch;
    utterance.volume=1;
    utterance.lang=selected?.lang||language;
    if(selected)utterance.voice=selected;
    utterance.onend=()=>next(index+1);
    utterance.onerror=(event)=>{
      if(run!==activeRun)return;
      active=false;paused=false;controls();
      if(event?.error!=='interrupted'&&event?.error!=='canceled')
        status('Speech was blocked or unavailable. Press Listen to try again.');
    };
    try{
      synth.speak(utterance);
      status('Reading with Privi Voice…');
    }catch{
      active=false;paused=false;controls();status('Unable to start browser speech.');
    }
  }
  next(0);
  return true;
}
function pauseResume(){
  if(!available||!active)return;
  try{
    if(paused){synth.resume();paused=false;status('Reading with Privi Voice…');}
    else{synth.pause();paused=true;status('Playback paused.');}
    controls();
  }catch{status('Pause/resume is unavailable in this browser.');}
}
function toggle(){
  const panel=$('priviVoicePanel');
  panel.hidden=!panel.hidden;
  $('priviVoiceBtn').setAttribute('aria-expanded',String(!panel.hidden));
  if(!panel.hidden){refreshVoices();$('priviVoiceSelect').focus();}
}

const languageSelect=$('priviVoiceLanguage');
for(const item of SPEECH_LANGUAGES){
  const opt=document.createElement('option');
  opt.value=item.code;opt.textContent=item.label;
  languageSelect.append(opt);
}
languageSelect.value=settings.language;
languageSelect.addEventListener('change',event=>{
  settings=normalizeVoiceSettings({...settings,language:event.target.value,voiceUri:''});
  $('priviVoiceSelect').value='';
  save();
  if(active)stop();
  status('Voice and microphone language: '+speechLanguage(settings,navigator.language)+'.');
});
$('priviVoiceBtn').addEventListener('click',toggle);
$('priviVoiceClose').addEventListener('click',()=>{
  $('priviVoicePanel').hidden=true;
  $('priviVoiceBtn').setAttribute('aria-expanded','false');
  $('priviVoiceBtn').focus();
});
$('priviVoiceSelect').addEventListener('change',event=>{
  settings=normalizeVoiceSettings({...settings,voiceUri:event.target.value});save();
  if(active)stop();
});
$('priviVoiceRate').addEventListener('input',event=>{
  settings=normalizeVoiceSettings({...settings,rate:Number(event.target.value)});
  $('priviVoiceRateValue').textContent=settings.rate.toFixed(1)+'×';save();
});
$('priviVoicePitch').addEventListener('input',event=>{
  settings=normalizeVoiceSettings({...settings,pitch:Number(event.target.value)});
  $('priviVoicePitchValue').textContent=settings.pitch.toFixed(1);save();
});
$('priviVoiceAuto').addEventListener('change',event=>{
  settings=normalizeVoiceSettings({...settings,autoRead:event.target.checked});save();
  status(settings.autoRead?'New regular replies will be read aloud when browser playback is allowed.':
    'Automatic read-aloud is off.');
});
$('priviVoiceAutoSend').addEventListener('change',event=>{
  settings=normalizeVoiceSettings({...settings,autoSend:event.target.checked});save();
  status(settings.autoSend?'Voice questions will be sent after recognition. Disable to review before sending.':
    'Dictated questions will remain in the composer until you press Send.');
});
$('priviVoicePreview').addEventListener('click',()=>{
  read('Hello! This is Privi Voice. Choose your language, voice, and speaking speed.');
});
$('priviVoicePause').addEventListener('click',pauseResume);
$('priviVoiceStop').addEventListener('click',()=>stop());
$('priviVoiceLast').addEventListener('click',()=>{
  const latest=window.joseAddons?.getLastReply?.()||'';
  if(latest)read(latest);
  else status('Ask Hey Jose a question first, or select Try voice.');
});
$('priviVoiceMic').addEventListener('click',()=>$('voice').click());
$('priviVoiceRate').value=String(settings.rate);
$('priviVoicePitch').value=String(settings.pitch);
$('priviVoiceRateValue').textContent=settings.rate.toFixed(1)+'×';
$('priviVoicePitchValue').textContent=settings.pitch.toFixed(1);
$('priviVoiceAuto').checked=settings.autoRead;
$('priviVoiceAutoSend').checked=settings.autoSend;
controls();
if(!available){
  for(const id of ['priviVoiceSelect','priviVoiceRate','priviVoicePitch',
    'priviVoiceAuto','priviVoicePreview','priviVoicePause',
    'priviVoiceStop','priviVoiceLast'])$(id).disabled=true;
  status('Your browser cannot play speech. Microphone dictation may still work.');
}else{
  synth.addEventListener?.('voiceschanged',refreshVoices);
  refreshVoices();
  status('Privi Voice is free. Choose a language and tap Listen on any reply.');
}
window.addEventListener('pagehide',()=>{if(available)synth.cancel();});
window.priviVoice=Object.freeze({
  supported:available,read,stop,pauseResume,
  getLanguage:()=>speechLanguage(settings,navigator.language||'en-US'),
  autoSend:()=>settings.autoSend,
  onAnswer(value){return settings.autoRead?read(value):false;},
  settings:()=>({...settings}),
});
