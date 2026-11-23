import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeChatMode, maxCompletionTokens, systemPromptFor } from '../src/chat-modes.js';

test('only explicit build mode enables browser app generation', () => {
  assert.equal(normalizeChatMode('build'), 'build');
  for (const input of [undefined, null, 'chat', 'BUILD', 'assistant', {}, []]) {
    assert.equal(normalizeChatMode(input), 'chat');
  }
});

test('coding budget is bounded and separate from regular chat', () => {
  assert.equal(maxCompletionTokens('build'), 4500);
  assert.equal(maxCompletionTokens('chat'), 2500);
  assert.equal(maxCompletionTokens('build', '9000'), 6000);
  assert.equal(maxCompletionTokens('build', '300'), 300);
  assert.equal(maxCompletionTokens('build', 'invalid'), 4500);
  assert.equal(maxCompletionTokens('build', '-1'), 4500);
});

test('the build instructions do not promise deployments or external tool access', () => {
  const buildPrompt = systemPromptFor('build');
  const chatPrompt = systemPromptFor('chat');
  assert.match(buildPrompt, /self-contained/);
  assert.match(buildPrompt, /Do not claim deployment/);
  assert.match(buildPrompt, /single fenced html code block/);
  assert.doesNotMatch(chatPrompt, /BUILD APP MODE/);
  assert.match(chatPrompt, /Never claim/);
});
