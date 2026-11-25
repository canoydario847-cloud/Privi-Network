import test from 'node:test';
import assert from 'node:assert/strict';
import {
  DEFAULT_VOICE_SETTINGS,SPEECH_LANGUAGES,normalizeVoiceSettings,speechLanguage,
  prepareSpeechText,splitSpeechText,
} from '../public/privi-voice-core.mjs';

test('Privi Voice defaults are free, bounded and opt-in',()=>{
  assert.deepEqual(normalizeVoiceSettings(),DEFAULT_VOICE_SETTINGS);
  const changed=normalizeVoiceSettings({
    rate:99,pitch:-4,autoRead:'yes',voiceUri:'x'.repeat(999),
  });
  assert.equal(changed.rate,2);
  assert.equal(changed.pitch,0.7);
  assert.equal(changed.autoRead,false);
  assert.equal(changed.voiceUri.length,250);
  assert.equal(changed.autoSend,false);
  assert.equal(changed.language,'auto');
  assert.deepEqual(normalizeVoiceSettings({rate:0.6,pitch:1.5,autoRead:true,language:'es-ES',autoSend:true}),
    {voiceUri:'',rate:0.6,pitch:1.5,autoRead:true,language:'es-ES',autoSend:true});
});
test('Voice language is validated and shared with optional dictation',()=>{
  const languages=SPEECH_LANGUAGES.map(x=>x.code);
  assert.ok(languages.includes('pt-BR'));
  assert.ok(languages.includes('hi-IN'));
  assert.ok(languages.includes('ar-SA'));
  assert.equal(speechLanguage({language:'es-ES'},'en-US'),'es-ES');
  assert.equal(speechLanguage({language:'auto'},'pt-BR'),'pt-BR');
  assert.equal(speechLanguage({language:'auto'},'INVALID LOCALE'),'en-US');
  assert.equal(normalizeVoiceSettings({language:'file:///etc/passwd'}).language,'auto');
  assert.equal(normalizeVoiceSettings({autoSend:'true'}).autoSend,false);
  assert.equal(normalizeVoiceSettings({autoSend:true}).autoSend,true);
});
test('Voice settings can recover invalid data without enabling automatic sending',()=>{
  assert.equal(normalizeVoiceSettings(null).autoSend,false);
  assert.equal(normalizeVoiceSettings([]).autoSend,false);
  assert.equal(normalizeVoiceSettings({language:29,autoSend:1}).autoSend,false);
});

test('Privi Voice reads prose, not entire generated code samples or URLs',()=>{
  const fence='\x60\x60\x60';
  const text='## Welcome!\nTry '+fence+'html\n<html>script source here</html>\n'+fence+
    '\nHere is [documentation](https://example.org/private?key=secret).';
  const spoken=prepareSpeechText(text);
  assert.match(spoken,/Welcome!/);
  assert.match(spoken,/Code sample omitted/);
  assert.match(spoken,/Here is documentation/);
  assert.doesNotMatch(spoken,/<html>|example.org|private\?key/);
  assert.equal(prepareSpeechText({content:'wrong'}),'');
});

test('Privi Voice splits longer replies into bounded phrases without losing words',()=>{
  const original=Array.from({length:65},(_,i)=>'Sentence '+i+' is spoken.').join(' ');
  const chunks=splitSpeechText(original,130);
  assert.ok(chunks.length>3);
  assert.ok(chunks.every(x=>x.length<=130));
  assert.equal(chunks.join(' '),original);
  assert.deepEqual(splitSpeechText(''),[]);
  assert.deepEqual(splitSpeechText('Hey Jose.'),['Hey Jose.']);
});

test('Privi Voice text length is capped for browser speech engines',()=>{
  assert.equal(prepareSpeechText('x'.repeat(20000)).length,10000);
  assert.ok(splitSpeechText('x'.repeat(1000),200).every(part=>part.length<=200));
});
