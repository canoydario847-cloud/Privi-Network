import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

const html=readFileSync(fileURLToPath(new URL('../public/chat.html',import.meta.url)),'utf8');
const js=readFileSync(fileURLToPath(new URL('../public/chat-sidebar.js',import.meta.url)),'utf8');
const home=readFileSync(fileURLToPath(new URL('../../jose-site/index.html',import.meta.url)),'utf8');
const aside=html.match(/<aside id="sidebar"[\s\S]*?<\/aside>/)?.[0]||'';
test('Professional sidebar has branded header, descriptive landmarks and accessible controls',()=>{
  assert.ok(aside.length>2500);
  for(const id of [
    'sidebar','closeSidebar','sidebarNewChat','sidebarSearch','sidebarChatCount',
    'conversationList','sidebarTasks','sidebarAccount','sidebarAccountTitle',
    'sidebarAccountSubtitle','sidebarStorage',
  ])assert.match(aside,new RegExp('id="'+id+'"'),id);
  assert.match(aside,/AI WORKSPACE/);
  assert.match(aside,/Recent conversations/);
  assert.match(aside,/Workspace/);
  assert.match(aside,/Build &amp; explore/);
  assert.match(aside,/aria-labelledby="recentChatsTitle"/);
  assert.match(aside,/aria-labelledby="workspaceToolsTitle"/);
  assert.match(aside,/aria-label="Search saved conversations"/);
  assert.match(aside,/<svg aria-hidden="true"/);
});
test('Every Jose shortcut is retained and no sidebar action is duplicated',()=>{
 const required=['powers','devnet','web3','quantum','quantumproject',
   'qubo','balance','cloudstatus','gmail','tasks','memory','voice','attach','export'];
 const actions=[...aside.matchAll(/data-action="([^"]+)"/g)].map(m=>m[1]);
 assert.deepEqual([...actions].sort(),[...required].sort());
 assert.equal(new Set(actions).size,required.length);
 assert.match(js,/\$\('sidebarTasks'\)\.addEventListener\('click'/);
});
test('No duplicate sidebar IDs and every date/selection group remains accessible',()=>{
 const ids=[...aside.matchAll(/\sid="([^"]+)"/g)].map(m=>m[1]);
 assert.equal(new Set(ids).size,ids.length);
 assert.match(js,/sidebar-date-label/);
 assert.match(js,/aria-current/);
 assert.match(js,/sidebarChatCount/);
 assert.match(js,/openChat\(c.id\)/);
 assert.match(js,/renameChat\(c\)/);
 assert.match(js,/deleteChat\(c\)/);
});
test('Mobile drawer and shortcuts are keyboard accessible and persisted',()=>{
 assert.match(js,/function syncDrawer\(/);
 assert.match(js,/\.inert=!open/);
 assert.match(js,/aria-hidden/);
 assert.match(js,/event\.key==='Tab'/);
 assert.match(js,/event\.key==='Escape'/);
 assert.match(js,/event\.metaKey/);
 assert.match(js,/PREFERENCE_KEY/);
 assert.match(js,/sidebarSearch'\)\.focus/);
 assert.match(html,/@media\(max-width:860px\)/);
 assert.match(html,/@media\(prefers-reduced-motion:reduce\)/);
});
test('Account area uses real Jose sign-in instead of misleading Gmail redirect',()=>{
 assert.match(js,/\/login\.html\?next=%2Fchat\.html/);
 assert.doesNotMatch(js,/\$\('sidebarAccount'\)\.onclick=\(\)=>\{\$\('gmailBtn'\)\.click\(\)/);
 assert.match(js,/TEMPORARY/ig); // history caveat stays visible
});
test('Homepage iframe requests the latest professional sidebar',()=>{
 assert.match(home,/chat\.html\?v=20261126-sidebar-pro/);
});
