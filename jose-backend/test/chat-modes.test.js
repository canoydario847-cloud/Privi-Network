import test from 'node:test';
import assert from 'node:assert/strict';
import { inferChatMode, normalizeChatMode, maxCompletionTokens, systemPromptFor } from '../src/chat-modes.js';

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

test('Web3 assistant mode is distinct from browser app building',()=>{
 assert.equal(normalizeChatMode('web3'),'web3');
 assert.equal(maxCompletionTokens('web3'),4000);
 assert.match(systemPromptFor('web3'),/Never request private keys/);
 assert.match(systemPromptFor('web3'),/NOT the launch/);
});

test('one chat automatically chooses a useful response style without feature pages', () => {
  assert.equal(inferChatMode('What is photosynthesis?'), 'chat');
  assert.equal(inferChatMode('Can you explain how to build a website?'), 'chat');
  assert.equal(inferChatMode('Build me a task manager app'), 'build');
  assert.equal(inferChatMode('Make a responsive website for my business'), 'build');
  assert.equal(inferChatMode('Launch a token with 100 million supply'), 'web3');
  assert.equal(inferChatMode('Create an NFT collection'), 'web3');
  assert.equal(inferChatMode('Deploy a smart contract on Base'), 'web3');
  assert.equal(inferChatMode('Run a blockchain ledger'), 'web3');
  assert.equal(inferChatMode('Build a website for an NFT collection'), 'web3');
  assert.equal(inferChatMode(null), 'chat');
});
